"""Yayın öncesi kitle testi: "Bu video nasıl?"

İki yöntem:
  claude   : Claude'a videonun kareleri, metni ve paylaşım yazısı gösterilir; farklı Türk izleyici profillerinin
             (yaş, ilgi alanı, platform) videoyu nasıl karşılayacağı canlandırılır. Hızlı ve ucuzdur.
  mirofish : Kullanıcının kendi çalıştırdığı MiroFish (github.com/666ghj/MiroFish, AGPL-3.0) sunucusuna bağlanır;
             videonun içeriği "tohum" belge olarak verilir, çok ajanlı sosyal medya simülasyonu çalıştırılır ve
             raporu alınır. MiroFish kendi LLM ve Zep anahtarlarıyla çalışır; çok sayıda LLM çağrısı yapar (maliyetli).

Her iki sonuç da TAHMİNDİR, gerçek izlenme verisi değildir; böyle gösterilir.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from . import log
from .config import ROOT, Config, load_config
from .util import StageError, read_json, write_json

L = log.get("audience")

PANEL_PROMPT = """Bir kısa dikey videonun (Reels/TikTok/Shorts) yayın öncesi kitle testini yapıyorsun.
Görüntü: videodan zamana göre kareler. Video bilgileri:
- Başlık: {title}
- Seslendirme/konuşma metni: {text}
- Paylaşım yazısı: {caption}
- Yayınlanacak platformlar: {platforms}

Türkiye'den 10 farklı izleyici profili canlandır (yaş, cinsiyet, ilgi alanı, en çok kullandığı platform çeşitli
olsun; konuya ilgisiz olanlar da bulunsun). Her biri için videoyu akışta gördüğünde ne yapacağını gerçekçi
biçimde tahmin et: ilk 2 saniyede durur mu, ne kadarını izler, beğenir/yorum yapar/paylaşır/kaydeder mi ve
yazabileceği bir yorum. Sonra genel değerlendirme yap: açılışın gücü, anlaşılırlık, görsel kalite, altyazı,
olası eleştiriler (hatalı bilgi, telif, hassas konu riski dahil) ve somut iyileştirme önerileri.
Abartma; ortalama bir video için ortalama sonuç ver. Bu bir tahmin, gerçek veri değil.

Yalnızca şu JSON:
{{"score": 0-100, "hook": 0-10, "clarity": 0-10, "visual": 0-10,
  "est_watch_through": "ör. %45", "verdict": "tek cümle Türkçe değerlendirme",
  "personas": [{{"who": "ör. 24, üniversite öğrencisi, Instagram", "stops": true, "watch": "%80",
                 "action": "beğenir|yorum|paylaşır|kaydeder|geçer", "comment": "..."}}],
  "strengths": ["..."], "risks": ["..."], "improvements": ["..."],
  "platform_fit": {{"instagram": "iyi|orta|zayıf", "tiktok": "...", "youtube": "...", "facebook": "..."}}}}"""


def panel_test(video_info: dict, sheet: Path, out_dir: Path, cfg: Config | None = None) -> dict:
    """Claude ile sanal izleyici paneli."""
    from .studio import ask_ai, ai_mode
    cfg = cfg or load_config()
    if ai_mode(cfg) == "none":
        raise StageError("Kitle testi için Claude gerekli (bilgisayardaki Claude Code veya Claude API)")
    prompt = PANEL_PROMPT.format(title=video_info.get("title", ""), text=(video_info.get("text") or "")[:2500],
                                 caption=(video_info.get("caption") or "")[:800],
                                 platforms=", ".join(video_info.get("platforms") or []) or "Instagram, TikTok")
    out = out_dir / "audience_claude.json"
    res = ask_ai(cfg, prompt, [sheet] if sheet and sheet.exists() else [], out, timeout=600)
    if not res or "score" not in res:
        raise StageError("Claude kitle testi sonucu üretemedi")
    res.update(method="claude", at=time.strftime("%Y-%m-%d %H:%M"), note="Tahmindir; gerçek izlenme verisi değildir.")
    write_json(out, res)
    return res


# ----------------------------------------------------------------------------
# MiroFish bağlayıcısı (kullanıcının kendi sunucusu: docker compose up → http://localhost:5001)
# ----------------------------------------------------------------------------

class MiroFish:
    def __init__(self, base: str, timeout_min: float = 60):
        self.base = base.rstrip("/")
        self.deadline = time.time() + timeout_min * 60

    def _req(self, method: str, path: str, **kw) -> dict:
        try:
            r = requests.request(method, self.base + path, timeout=120, **kw)
        except requests.RequestException as exc:
            raise StageError(f"MiroFish'e bağlanılamadı ({self.base}): {type(exc).__name__}") from exc
        try:
            data = r.json()
        except ValueError as exc:
            raise StageError(f"MiroFish geçersiz yanıt ({r.status_code})") from exc
        if not data.get("success", r.ok):
            raise StageError(f"MiroFish hatası: {str(data.get('error'))[:300]}")
        return data.get("data") or {}

    def _wait(self, fetch, done, what: str, every: float = 10):
        while time.time() < self.deadline:
            d = fetch()
            st = str(d.get("status") or d.get("runner_status") or "")
            if st in ("failed", "error"):
                raise StageError(f"MiroFish {what} başarısız: {d.get('message') or d.get('error')}")
            if done(d, st):
                return d
            L.info("MiroFish %s: %s %s", what, st, d.get("progress") or d.get("progress_percent") or "")
            time.sleep(every)
        raise StageError(f"MiroFish {what} zaman aşımı")

    def run(self, seed_md: str, requirement: str, name: str, max_rounds: int) -> dict:
        files = {"files": ("video.md", seed_md.encode("utf-8"), "text/markdown")}
        proj = self._req("POST", "/api/graph/ontology/generate", files=files,
                         data={"simulation_requirement": requirement, "project_name": name})
        pid = proj["project_id"]
        task = self._req("POST", "/api/graph/build", json={"project_id": pid, "graph_name": name})
        self._wait(lambda: self._req("GET", f"/api/graph/task/{task['task_id']}"),
                   lambda d, st: st in ("completed", "success", "done"), "bilgi grafiği")
        sim = self._req("POST", "/api/simulation/create", json={"project_id": pid})
        sid = sim["simulation_id"]
        prep = self._req("POST", "/api/simulation/prepare", json={"simulation_id": sid})
        if not prep.get("already_prepared"):
            self._wait(lambda: self._req("POST", "/api/simulation/prepare/status",
                                         json={"task_id": prep.get("task_id"), "simulation_id": sid}),
                       lambda d, st: st in ("completed", "ready") or d.get("already_prepared"), "hazırlık")
        self._req("POST", "/api/simulation/start", json={"simulation_id": sid, "max_rounds": max_rounds})
        self._wait(lambda: self._req("GET", f"/api/simulation/{sid}/run-status"),
                   lambda d, st: st in ("completed", "stopped", "finished"), "simülasyon", every=15)
        rep = self._req("POST", "/api/report/generate", json={"simulation_id": sid})
        self._wait(lambda: self._req("POST", "/api/report/generate/status",
                                     json={"task_id": rep.get("task_id"), "simulation_id": sid}),
                   lambda d, st: st in ("completed",), "rapor")
        report = self._req("GET", f"/api/report/by-simulation/{sid}")
        return {"project_id": pid, "simulation_id": sid, "report_id": report.get("report_id"),
                "markdown": report.get("markdown_content", "")}


def mirofish_test(video_info: dict, out_dir: Path, cfg: Config | None = None) -> dict:
    cfg = cfg or load_config()
    from .publish import settings
    url = settings().get("mirofish_url") or cfg.get_path("audience.mirofish.url", "")
    if not url:
        raise StageError("MiroFish adresi ayarlanmamış (Yayın → Ayarlar → MiroFish adresi, ör. http://localhost:5001)")
    seed = (f"# Yayınlanacak kısa video: {video_info.get('title', '')}\n\n"
            f"Platformlar: {', '.join(video_info.get('platforms') or [])}\n\n"
            f"## Videoda anlatılanlar\n{video_info.get('text', '')}\n\n"
            f"## Paylaşım yazısı\n{video_info.get('caption', '')}\n")
    requirement = ("Bu kısa video Türkiye'deki sosyal medya kullanıcılarına paylaşıldığında nasıl karşılanır? "
                   "İlgi, beğeni, paylaşım ve yorum eğilimlerini, olası eleştirileri ve tartışmaları, hangi kitlenin "
                   "daha çok ilgileneceğini tahmin et ve videonun daha iyi karşılanması için öneriler ver. "
                   "Raporu Türkçe yaz.")
    res = MiroFish(url, float(cfg.get_path("audience.mirofish.timeout_min", 90))).run(
        seed, requirement, f"reels-{video_info.get('id', 'video')}",
        int(cfg.get_path("audience.mirofish.max_rounds", 10)))
    res.update(method="mirofish", at=time.strftime("%Y-%m-%d %H:%M"),
               note="MiroFish simülasyonu: tahmindir, gerçek izlenme verisi değildir.")
    write_json(out_dir / "audience_mirofish.json", res)
    return res
