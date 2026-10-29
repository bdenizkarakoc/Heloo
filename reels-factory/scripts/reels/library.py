"""Kesim kütüphanesi: internetten ücretsiz ve lisansı serbest medya (CapCut'taki hazır içerik paneli gibi).

Kaynaklar (anahtarsız):
  ses efekti / müzik : Openverse ses (çoğu Freesound / Jamendo / ccMixter)
  görsel / PNG       : Openverse görsel
  video              : Wikimedia Commons (küçültülmüş webm sürümü indirilir)
Yalnızca CC0, kamu malı ve CC BY kabul edilir (fabrikanın katı lisans kuralıyla aynı; BY-SA / NC / ND yok).
İndirilenler output/kesim/kutuphane/ altına, atıflar aynı yerdeki credits.json dosyasına yazılır. İndirme yalnızca
son aramalardan dönen kimliklerle yapılır (rastgele adres indirilmez).
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
from pathlib import Path

from . import log
from .config import ROOT
from .util import StageError, download, http_json, retry

L = log.get("library")
OUT = ROOT / "output" / "kesim" / "kutuphane"
CREDITS = OUT / "credits.json"
KINDS = {"sfx": "Ses efekti", "music": "Müzik", "image": "Görsel", "png": "PNG / çıkartma", "video": "Video"}
OK_LICENSES = {"cc0", "pdm", "by"}

# Türkçe hızlı aramalar → kaynakların anladığı İngilizce sorgu
PRESETS = {
    "sfx": [("Vınlama", "whoosh"), ("Geçiş", "swoosh transition"), ("Darbe", "impact hit"), ("Patlama", "explosion"),
            ("Alkış", "applause"), ("Kahkaha", "laugh"), ("Tık", "click"), ("Pop", "pop"), ("Zil", "bell ding"),
            ("Bildirim", "notification"), ("Kamera", "camera shutter"), ("Daktilo", "typewriter"),
            ("Kalp atışı", "heartbeat"), ("Yağmur", "rain"), ("Rüzgâr", "wind"), ("Kalabalık", "crowd"),
            ("Kayıt çizilmesi", "record scratch"), ("Yükseliş", "riser"), ("Glitch", "glitch"), ("Para", "cash register")],
    "music": [("Neşeli", "happy upbeat"), ("Sinematik", "cinematic"), ("Duygusal", "sad piano"), ("Lo-fi", "lofi"),
              ("Elektronik", "electronic"), ("Hip hop", "hip hop beat"), ("Gerilim", "suspense"), ("Akustik", "acoustic guitar"),
              ("Epik", "epic orchestral"), ("Sakin", "ambient calm")],
    "image": [("Doku", "texture"), ("Gökyüzü", "sky"), ("Şehir", "city night"), ("Doğa", "nature landscape"),
              ("Uzay", "space galaxy"), ("Deniz", "ocean"), ("Arka plan", "abstract background"), ("Kâğıt", "paper texture"),
              ("Bokeh", "bokeh"), ("Duman", "smoke")],
    "png": [("Ok", "arrow"), ("Kalp", "heart"), ("Yıldız", "star"), ("Konuşma balonu", "speech bubble"),
            ("Çerçeve", "frame border"), ("Ateş", "fire"), ("Kupa", "trophy"), ("Logo şekli", "icon"),
            ("Konfeti", "confetti"), ("Taç", "crown")],
    "video": [("Okyanus", "ocean"), ("Uzay", "space"), ("Şehir", "city timelapse"), ("Bulutlar", "clouds timelapse"),
              ("Ateş", "fire"), ("Hayvanlar", "animals"), ("Doğa", "forest"), ("Yağmur", "rain"),
              ("Havai fişek", "fireworks"), ("Trafik", "traffic")],
}

_cache: dict[str, tuple[float, list[dict]]] = {}
_items: dict[str, dict] = {}       # kimlik → arama sonucu (indirme yalnızca buradan)
_lock = threading.Lock()


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _key(src: str, ident: str) -> str:
    return hashlib.sha1(f"{src}:{ident}".encode()).hexdigest()[:16]


def _openverse(kind: str, q: str, page: int) -> list[dict]:
    audio = kind in ("sfx", "music")
    params = {"q": q, "license": ",".join(sorted(OK_LICENSES)), "page_size": 20,  # anahtarsız istekte üst sınır
              "page": page, "mature": "false"}
    if kind == "png":
        params["extension"] = "png"
    data = retry(2, 2.0)(http_json)("GET", f"https://api.openverse.org/v1/{'audio' if audio else 'images'}/",
                                     params=params, timeout=25)   # 2 deneme < Kesim istemcisinin 60 sn sınırı
    out = []
    for r in data.get("results", []):
        if r.get("license") not in OK_LICENSES or not r.get("url"):
            continue
        dur = (r.get("duration") or 0) / 1000
        if kind == "sfx" and not (0 < dur <= 20):
            continue
        if kind == "music" and dur and dur < 30:
            continue
        lic = f"{'Kamu malı' if r['license'] == 'pdm' else r['license'].upper()} {r.get('license_version') or ''}".strip()
        creator = r.get("creator") or ""
        out.append({"id": _key("ov", r["id"]), "kind": kind, "title": (r.get("title") or q)[:90],
                    "media_url": r["url"], "preview": r["url"] if audio else (r.get("thumbnail") or r["url"]),
                    "duration": round(dur, 1) if dur else None, "w": r.get("width"), "h": r.get("height"),
                    "ext": (r.get("filetype") or Path(r["url"].split("?")[0]).suffix.lstrip(".") or ("mp3" if audio else "jpg")).lower(),
                    "license": lic, "creator": creator, "page": r.get("foreign_landing_url") or "",
                    "source": f"Openverse / {r.get('source') or r.get('provider') or ''}".rstrip(" /"),
                    "credit": f"“{(r.get('title') or '')[:80]}” — {creator or 'bilinmiyor'} ({lic})"})
    return out


def _commons_license(meta: dict) -> str | None:
    short = _strip(meta.get("LicenseShortName", {}).get("value", ""))
    code = meta.get("License", {}).get("value", "").lower()
    if code in ("cc0", "pd") or code.startswith("pd-") or "public domain" in short.lower() or short.upper() == "CC0":
        return "Kamu malı" if "public" in short.lower() or code.startswith("pd") else "CC0"
    if re.fullmatch(r"cc-by-\d(\.\d)?", code):
        return short or code.upper()
    return None


def _commons_video(q: str, page: int) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:video {q}",
              "gsrnamespace": 6, "gsrlimit": 30, "gsroffset": (page - 1) * 30, "prop": "videoinfo",
              "viprop": "url|extmetadata|size|derivatives", "viurlwidth": 320}
    data = retry(2, 2.0)(http_json)("GET", "https://commons.wikimedia.org/w/api.php", params=params, timeout=30)
    out = []
    for pg in (data.get("query") or {}).get("pages", {}).values():
        vi = (pg.get("videoinfo") or [{}])[0]
        meta = vi.get("extmetadata") or {}
        lic = _commons_license(meta)
        if not lic or not vi.get("url") or float(vi.get("duration") or 0) > 600:   # uzun filmler Reels'e uymaz
            continue
        ders = [d for d in vi.get("derivatives") or [] if "webm" in d.get("type", "") and d.get("height")]
        top = 720 if float(vi.get("duration") or 0) <= 60 else 480   # uzun videoda küçük sürüm: hızlı indirme
        pick = max((d for d in ders if 360 <= int(d["height"]) <= top), key=lambda d: int(d["height"]), default=None)
        if not pick and (vi.get("size") or 0) > 150 * 1024 * 1024:
            continue
        url = pick["src"] if pick else vi["url"]
        creator = _strip(meta.get("Artist", {}).get("value", ""))[:80]
        title = _strip(meta.get("ObjectName", {}).get("value", "")) or pg.get("title", "").removeprefix("File:")
        out.append({"id": _key("wc", str(pg.get("pageid"))), "kind": "video", "title": title[:90], "media_url": url,
                    "preview": vi.get("thumburl") or "", "duration": round(float(vi.get("duration") or 0), 1) or None,
                    "w": vi.get("width"), "h": vi.get("height"), "ext": "webm" if pick else Path(url.split("?")[0]).suffix.lstrip("."),
                    "license": lic, "creator": creator, "page": vi.get("descriptionurl") or "",
                    "source": "Wikimedia Commons", "credit": f"“{title[:80]}” — {creator or 'Wikimedia Commons'} ({lic})"})
    return out


def search(kind: str, q: str, page: int = 1) -> dict:
    if kind not in KINDS:
        raise StageError(f"bilinmeyen tür: {kind}")
    q = (q or "").strip()[:100] or PRESETS[kind][0][1]
    page = max(1, min(int(page or 1), 20))
    ck = f"{kind}|{q.lower()}|{page}"
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 3600:
        res = hit[1]
    else:
        res = _commons_video(q, page) if kind == "video" else _openverse(kind, q, page)
        _cache[ck] = (time.time(), res)
        while len(_cache) > 150:
            _cache.pop(next(iter(_cache)))
    with _lock:
        for r in res:
            _items[r["id"]] = r
        while len(_items) > 3000:
            _items.pop(next(iter(_items)))
    return {"kind": kind, "q": q, "page": page, "results": res}


def presets() -> dict:
    return {"kinds": KINDS, "presets": {k: [{"label": a, "q": b} for a, b in v] for k, v in PRESETS.items()}}


def credits() -> list[dict]:
    try:
        return json.loads(CREDITS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def fetch(item_id: str) -> dict:
    """Arama sonucundaki öğeyi indirir, atfını kaydeder; Kesim'in alabileceği göreli yolu döndürür."""
    with _lock:
        it = _items.get(str(item_id))
    if not it:
        raise StageError("öğe bulunamadı; aramayı yenileyin")
    ext = re.sub(r"[^a-z0-9]", "", it["ext"].lower())[:5] or "bin"
    ext = {"mpeg": "mp3", "mp32": "mp3", "mpga": "mp3", "jpeg": "jpg", "oga": "ogg", "x-wav": "wav"}.get(ext, ext)
    safe = re.sub(r"[^\w\-]+", "-", it["title"].lower(), flags=re.U).strip("-")[:50] or it["kind"]
    dest = OUT / it["kind"] / f"{safe}-{it['id'][:6]}.{ext}"
    if not dest.is_file():
        retry(2, 2.0)(download)(it["media_url"], dest, max_mb=150 if it["kind"] == "video" else 40)
        rec = {k: it.get(k) for k in ("kind", "title", "license", "creator", "source", "page", "credit")}
        rec["file"] = dest.relative_to(ROOT).as_posix()
        rec["date"] = time.strftime("%Y-%m-%d %H:%M")
        with _lock:
            cur = [c for c in credits() if c.get("file") != rec["file"]]
            cur.append(rec)
            CREDITS.parent.mkdir(parents=True, exist_ok=True)
            CREDITS.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        L.info("Kütüphane: %s indirildi (%s)", dest.name, it["license"])
    return {"output": dest.relative_to(ROOT).as_posix(), "name": dest.name, "kind": it["kind"],
            "credit": it["credit"], "license": it["license"]}
