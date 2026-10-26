"""Reel notları: bir videodan (dosya veya bağlantı) Obsidian notu çıkarır ve notu yeni video fikrine bağlar.

Videonun konuşması yerelde yazıya dökülür (faster-whisper), kareleri ve ekrandaki yazılar Claude'a gösterilir;
özet, önemli noktalar, ekrandaki metin, konuşma metni ve video fikirleri Markdown not olarak kasaya yazılır.

Telefonu kumanda edip Instagram'da otomatik gezinme/yorum yapma bilerek yoktur (Instagram kullanım koşullarına
aykırıdır, hesap kısıtlanabilir): videoları kullanıcı seçer — dosya yükler veya bağlantı yapıştırır.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import log
from .config import ROOT, load_config
from .util import StageError, read_json, slugify, write_json

L = log.get("notes")
APP_STATE = ROOT / "config" / "app.json"
WORK = ROOT / "studio" / "notes"


def vault() -> Path:
    """Obsidian kasası (Ayarlardan değiştirilebilir); yoksa output/notes. Notlar <kasa>/Reels altına yazılır."""
    p = ((read_json(APP_STATE, {}) or {}).get("notes") or {}).get("vault") or ""
    return (Path(p).expanduser() if p else ROOT / "output" / "notes") / "Reels"


def set_vault(path: str) -> str:
    path = (path or "").strip()
    if path and not Path(path).expanduser().is_dir():
        raise StageError("Klasör bulunamadı (Obsidian kasanızın klasör yolunu yazın)")
    state = read_json(APP_STATE, {}) or {}
    state["notes"] = {**(state.get("notes") or {}), "vault": path}
    write_json(APP_STATE, state)
    return str(vault())


PROMPT = """Bir kısa videonun (Reels/TikTok/Shorts) notunu çıkarıyorsun. Görüntü: videodan zamana göre kareler.
Konuşma dökümü (otomatik, hatalı olabilir):
{transcript}

Kareleri incele: ekrandaki yazıları/altyazıları oku. Görmediğini veya duymadığını uydurma; döküm hatalıysa
bağlamdan düzelt ama emin olmadığın yeri belirt. Yalnızca JSON:
{{"title": "kısa Türkçe başlık", "summary": "2-4 cümle özet",
  "key_points": ["..."], "on_screen_text": ["ekranda okunan yazılar"],
  "claims_to_verify": ["doğruluğu kontrol edilmesi gereken iddialar"],
  "video_ideas": ["bu videodan esinlenen, bizim kanalımız için özgün video fikri (kopya değil)"],
  "tags": ["küçük-harf-etiket"]}}"""


def make_note(src: Path, source_label: str) -> dict:
    """Notu üretir ve kasaya yazar; dönen sözlükte not yolu ve içerik alanları vardır."""
    from .studio import ai_mode, ask_ai, grab, probe, sheet, transcribe
    cfg = load_config()
    info = probe(src)
    work = WORK / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(src.stem, 30)}"
    work.mkdir(parents=True, exist_ok=True)
    words = transcribe(src, work, cfg) if info["audio"] else []
    text = " ".join(w["word"] for w in words)
    dur = info["duration"]
    tiles = [(grab(src, t, work / f"k{i:02d}.jpg", 480), f"{t:.0f} sn")
             for i, t in enumerate([dur * f for f in (0.03, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 0.98)])]
    shot = sheet(tiles, work / "sheet.jpg", cols=4)
    data = None
    if ai_mode(cfg) != "none":
        data = ask_ai(cfg, PROMPT.format(transcript=text[:6000] or "(konuşma yok)"), [shot], work / "note.json",
                      timeout=600)
    if not data:
        data = {"title": src.stem, "summary": "(Claude bağlı olmadığı için yalnızca konuşma dökümü kaydedildi.)",
                "key_points": [], "on_screen_text": [], "claims_to_verify": [], "video_ideas": [], "tags": []}
    title = str(data.get("title") or src.stem)[:80]
    day = dt.date.today().isoformat()
    folder = vault()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "_kareler").mkdir(exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", title).strip()  # dosya adında geçersiz karakterler
    safe = " ".join(safe.split())
    name = f"{day} {safe}"
    img = folder / "_kareler" / f"{slugify(name, 60)}.jpg"
    img.write_bytes(shot.read_bytes())
    tags = [slugify(t, 30) for t in (data.get("tags") or []) if t] + ["reel"]

    def bullets(key: str) -> str:
        return "\n".join(f"- {x}" for x in data.get(key) or []) or "-"

    md = (f"---\ntitle: \"{title}\"\ndate: {day}\nsource: \"{source_label}\"\nduration: {dur:.0f}\n"
          f"tags: [{', '.join(dict.fromkeys(tags))}]\n---\n\n# {title}\n\n"
          f"![[_kareler/{img.name}]]\n\n## Özet\n{data.get('summary', '')}\n\n"
          f"## Önemli noktalar\n{bullets('key_points')}\n\n## Ekrandaki yazılar\n{bullets('on_screen_text')}\n\n"
          f"## Doğrulanacak iddialar\n{bullets('claims_to_verify')}\n\n## Video fikirleri\n{bullets('video_ideas')}\n\n"
          f"## Konuşma metni\n{text or '(konuşma yok)'}\n")
    path = folder / f"{name}.md"
    n = 2
    while path.exists():  # var olan notun üzerine yazılmaz
        path = folder / f"{name} ({n}).md"
        n += 1
    path.write_text(md, encoding="utf-8")
    meta = {"path": str(path), "title": title, "summary": data.get("summary", ""),
            "video_ideas": data.get("video_ideas") or [], "key_points": data.get("key_points") or [],
            "source": source_label, "date": day}
    write_json(work / "meta.json", meta)
    L.info("Not yazıldı: %s", path)
    return meta


def list_notes(limit: int = 40) -> list[dict]:
    out = [read_json(p) for p in WORK.glob("*/meta.json")] if WORK.exists() else []
    out = [m for m in out if m and Path(m["path"]).exists()]
    return sorted(out, key=lambda m: m["path"], reverse=True)[:limit]


def idea_text(meta: dict, idea: str | None = None) -> str:
    """Yeni video için kullanıcı metni: seçilen fikir + notun özeti (kopya değil, esinlenme)."""
    base = idea or (meta.get("video_ideas") or [meta.get("title", "")])[0]
    return (f"{base}\n\nEsinlenilen notun özeti (birebir kopyalama, kendi araştırmanla özgün anlat): "
            f"{meta.get('summary', '')}\n" + "\n".join(f"- {k}" for k in meta.get("key_points", [])[:6]))


def to_json(meta: dict) -> str:
    return json.dumps(meta, ensure_ascii=False)
