"""İnternetten altyazı: OpenSubtitles.com REST API (ücretsiz API anahtarı gerekir: opensubtitles.com/consumers).

Ara → (dil, sürüm adı, indirme sayısı) listesi → seçileni indir → mpv'ye ekle. Anahtar Ayarlar'da saklanır.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, paths
from .netutil import NetError, _context, describe_error

API = "https://api.opensubtitles.com/api/v1"
UA = f"HelooTV v{__version__}"


class SubsError(Exception):
    pass


def clean_title(title: str) -> tuple[str, int | None, int | None]:
    """'Dizi X — S02B05 · Bölüm adı' / 'Film (2023) 1080p' → (sorgu, sezon, bölüm)."""
    t = title or ""
    season = episode = None
    m = re.search(r"S(\d{1,2})\s*[BE](\d{1,3})", t, re.I)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        t = t[:m.start()]
    t = re.split(r"\s+[—·|-]\s+", t)[0]
    t = re.sub(r"\.(mkv|mp4|avi|mov|ts|m4v)$", "", t, flags=re.I)
    t = re.sub(r"[._]", " ", t)
    t = re.sub(r"\b(1080p|720p|2160p|4k|x26[45]|hevc|web-?dl|bluray|hdr|tr|dublaj|altyaz[ıi]l[ıi])\b.*", "", t, flags=re.I)
    t = re.sub(r"[\(\[]?\b(19|20)\d{2}\b[\)\]]?", "", t)
    return re.sub(r"\s+", " ", t).strip(" -"), season, episode


def _call(method: str, path: str, key: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Api-Key": key, "User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        msg = describe_error(e)
        if "401" in msg or "403" in msg:
            msg += " — API anahtarını kontrol edin (opensubtitles.com/consumers)"
        if "406" in msg or "429" in msg:
            msg += " — günlük indirme sınırı dolmuş olabilir"
        raise SubsError(msg) from e


def search(key: str, query: str, languages: str = "tr,en", season: int | None = None,
           episode: int | None = None) -> list[dict]:
    if not key:
        raise SubsError("OpenSubtitles API anahtarı yok. opensubtitles.com/consumers adresinden ücretsiz alın.")
    params = {"query": query, "languages": languages, "order_by": "download_count"}
    if season:
        params["season_number"] = season
    if episode:
        params["episode_number"] = episode
    data = _call("GET", "/subtitles", key, params)
    out = []
    for row in data.get("data") or []:
        a = row.get("attributes") or {}
        files = a.get("files") or []
        if not files:
            continue
        fd = a.get("feature_details") or {}
        out.append({"file_id": files[0].get("file_id"), "lang": a.get("language") or "",
                    "release": a.get("release") or files[0].get("file_name") or "",
                    "downloads": a.get("download_count") or 0, "title": fd.get("title") or "",
                    "year": fd.get("year") or "", "hi": bool(a.get("hearing_impaired"))})
    return out


def download(key: str, file_id: int, name_hint: str = "altyazi") -> str:
    data = _call("POST", "/download", key, body={"file_id": file_id})
    link = data.get("link")
    if not link:
        raise SubsError(data.get("message") or "İndirme bağlantısı alınamadı.")
    req = urllib.request.Request(link, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_context()) as r:
            blob = r.read()
    except Exception as e:  # noqa: BLE001
        raise SubsError(describe_error(e)) from e
    name = data.get("file_name") or f"{name_hint}.srt"
    safe = re.sub(r"[^\w.\-]+", "_", name)[:120] or "altyazi.srt"
    out = paths.cache_dir() / "subs" / safe
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    return str(out)


__all__ = ["search", "download", "clean_title", "SubsError", "NetError", "Path"]
