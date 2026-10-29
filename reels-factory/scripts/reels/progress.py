"""İlerleme: her iş için yüzde, kalan süre ve adım listesi (bitti / şu an / bekliyor).

Fabrika videoları (projects/*/job.json) için adım ağırlıkları bu bilgisayardaki geçmiş görevlerin gerçek
sürelerinden (medyan) öğrenilir; çalışan adımın payı geçen süre / beklenen süre ile ilerler (en çok %95).
Stüdyo/Kesim işleri yalnızca bir "aşama" metni yazar; yüzde bu metinden kestirilir.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
import time

from .config import ROOT
from .util import read_json

STAGE_TR = {"script": "Senaryo", "voice": "Seslendirme", "captions": "Altyazı", "visuals": "Görseller",
            "music": "Müzik", "compose": "Kurgu", "render": "Görüntü oluşturma", "mix": "Ses miksajı",
            "qc": "Kalite kontrolü", "export": "Teslim"}
DEFAULT_SEC = {"script": 150, "voice": 60, "captions": 1, "visuals": 300, "music": 30, "compose": 20,
               "render": 240, "mix": 20, "qc": 60, "export": 2}
KIND_TR = {"new": "Yeni video", "compose": "Video Kur", "produce": "Yeniden üretim", "studio_edit": "Montaj", "studio_analyze": "Stil öğrenme",
           "voice_build": "Ses profili", "voice_setup": "Ses motoru kurulumu", "note": "Reel notu", "audiofx": "Ses iyileştirme",
           "knowledge": "Bilgi haritası", "kesim_learn": "Kesim stili öğrenme", "studio_improve": "Stil iyileştirme"}
_HIST: dict = {"t": 0.0, "sec": dict(DEFAULT_SEC)}


def _ts(s: str | None) -> float | None:
    try:
        return dt.datetime.fromisoformat(s).timestamp() if s else None
    except ValueError:
        return None


def stage_seconds() -> dict:
    """Adım başına beklenen süre: son 30 görevin medyanı (10 dakikada bir yenilenir)."""
    if time.time() - _HIST["t"] < 600:
        return _HIST["sec"]
    from .job import STAGES
    seen: dict[str, list[float]] = {s: [] for s in STAGES}
    files = sorted((ROOT / "projects").glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    for f in files:
        for k, v in ((read_json(f, {}) or {}).get("stages") or {}).items():
            if k in seen and v.get("status") == "done" and v.get("seconds"):
                seen[k].append(float(v["seconds"]))
    _HIST.update(t=time.time(), sec={k: (statistics.median(v) if len(v) >= 2 else DEFAULT_SEC[k]) for k, v in seen.items()})
    return _HIST["sec"]


def job_progress(state: dict) -> dict:
    """job.json durumundan yüzde, kalan süre ve adım listesi."""
    from .job import STAGES
    exp = stage_seconds()
    stages = state.get("stages") or {}
    total = sum(max(exp[s], 1) for s in STAGES)
    done_w, steps, current, eta = 0.0, [], None, 0.0
    now = time.time()
    for s in STAGES:
        st = stages.get(s) or {}
        status = st.get("status", "pending")
        w = max(exp[s], 1)
        item = {"key": s, "name": STAGE_TR[s], "status": status}
        if status in ("done", "skipped"):
            done_w += w
            item["sec"] = round(st.get("seconds") or 0)
        elif status == "running":
            el = now - (_ts(st.get("started")) or now)
            frac = min(0.95, el / w)
            done_w += w * frac
            item.update(sec=round(el), pct=round(100 * frac))
            current = STAGE_TR[s]
            eta += max(w - el, w * 0.05)
        else:
            eta += w
        steps.append(item)
    status = state.get("status")
    pct = 100 if status == "done" else round(100 * done_w / total)
    if status == "failed":
        failed = next((x for x in steps if x["status"] == "failed"), None)
        err = str((stages.get(failed["key"]) or {}).get("error") or "") if failed else ""
        err = err.split(": ", 1)[-1] if err.startswith(("StageError", "RuntimeError")) else err
        current = (f"{failed['name']} adımında hata" if failed else "hata") + (f": {err[:300]}" if err else "")
    return {"pct": pct, "eta": None if status in ("done", "failed") else round(eta), "current": current, "steps": steps}


# Stüdyo/Kesim aşama metni → yaklaşık yüzde
_EDIT_STEPS = [("birleştiriliyor", 5, "Dosyalar birleştiriliyor"), ("video inceleniyor", 10, "Video inceleniyor"),
               ("referans", 15, "Referans inceleniyor"), ("konuşma", 25, "Konuşma yazıya dökülüyor"),
               ("en iyi anlar", 40, "En iyi anlar seçiliyor"), ("klip", 45, "Klipler düzenleniyor"),
               ("iyileştir", 85, "Stil iyileştiriliyor")]
_ANALYZE_STEPS = [("indiriliyor", 10, "Bağlantı indiriliyor"), ("inceleniyor", 25, "Video inceleniyor"),
                  ("konuşma", 40, "Konuşma dinleniyor"), ("kareler", 55, "Kareler hazırlanıyor"), ("stil", 70, "Stil çıkarılıyor")]


def project_progress(proj: dict) -> dict:
    status, stage = proj.get("status"), str(proj.get("stage") or "")
    table = _ANALYZE_STEPS if proj.get("kind") == "analyze" else _EDIT_STEPS
    if status == "done":
        return {"pct": 100, "eta": None, "current": "Bitti", "steps": [{"name": n, "status": "done"} for _, _, n in table]}
    pct, idx = 2, -1
    for i, (key, p, _) in enumerate(table):
        if key in stage:
            pct, idx = p, i
    m = re.search(r"klip (\d+)/(\d+)", stage)
    if m:   # klip i/n: %45 → %85 arası
        i, n = int(m.group(1)), max(1, int(m.group(2)))
        pct = 45 + round(40 * (i - 1) / n)
    steps = [{"name": n, "status": "done" if i < idx else "running" if i == idx else "pending"} for i, (_, _, n) in enumerate(table)]
    if status == "failed":
        return {"pct": pct, "eta": None, "current": "Hata: " + str(proj.get("error") or "")[:160], "steps": steps}
    return {"pct": pct, "eta": None, "current": stage or "sırada", "steps": steps}


def overview(factory_snapshot: dict) -> dict:
    """Şu an çalışan iş + sıradakiler (başlamadı) + son bitenler; panel ve Kesim için."""
    from . import studio
    from .job import Job
    out: dict = {"running": None, "queued": [], "recent": []}
    cur = factory_snapshot.get("current")
    if cur:
        item = {"id": cur.get("id"), "kind": KIND_TR.get(cur.get("kind"), cur.get("kind")), "title": cur.get("topic") or "",
                "started": cur.get("started"), "state": "çalışıyor", "pct": 1, "eta": None, "current": "hazırlanıyor", "steps": []}
        try:
            if cur.get("project"):
                proj = studio.load_project(cur["project"])
                item.update(project_progress(proj), project=proj["id"], title=item["title"] or proj.get("source_name", ""))
            elif cur.get("job") and (ROOT / "projects" / str(cur["job"]) / "job.json").exists():
                job = Job.load(cur["job"])
                script = read_json(job.script_path, {}) or {}
                item.update(job_progress(job.state), job=job.id, title=script.get("title") or item["title"] or job.id)
            elif cur.get("kind") in ("new", "compose"):
                item.update(current="Konu seçiliyor / görev hazırlanıyor",
                            steps=[{"key": s, "name": n, "status": "pending"} for s, n in STAGE_TR.items()])
        except Exception:  # noqa: BLE001 — ilerleme hiçbir zaman paneli bozmasın
            pass
        out["running"] = item
    for i, t in enumerate(factory_snapshot.get("pending") or []):
        out["queued"].append({"id": t.get("id"), "kind": KIND_TR.get(t.get("kind"), t.get("kind")), "title": t.get("topic") or "",
                              "state": "sırada — başlamadı", "position": i + 1, "added": t.get("added")})
    for job in sorted(Job.all(), key=lambda j: j.state.get("updated", ""), reverse=True)[:6]:
        if job.state.get("status") not in ("done", "failed") or (cur and cur.get("job") == job.id):
            continue
        script = read_json(job.script_path, {}) or {}
        out["recent"].append({"job": job.id, "title": script.get("title") or job.id, "kind": "Video",
                              "state": "bitti" if job.state["status"] == "done" else "hata",
                              "updated": job.state.get("updated"), **job_progress(job.state),
                              "video": (job.state.get("outputs") or {}).get("video")})
        if len(out["recent"]) >= 4:
            break
    return out
