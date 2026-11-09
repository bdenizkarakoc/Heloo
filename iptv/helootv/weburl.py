"""Bağlantı aç: doğrudan medya adresleri olduğu gibi; web sayfaları (YouTube, Instagram, TikTok, Vimeo …) yt-dlp ile
en yüksek kaliteli akışa çözülür (ayrı ses izi mpv'ye audio-files olarak verilir)."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from .m3u import VOD_EXTS

DIRECT_EXTS = VOD_EXTS | {".m3u8", ".mpd", ".ts", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wav"}
STREAM_SCHEMES = ("rtmp", "rtmps", "rtsp", "srt", "udp", "rtp", "mms")


def is_url(text: str) -> bool:
    return "://" in (text or "") and urlsplit(text.strip()).scheme.lower() in ("http", "https", *STREAM_SCHEMES)


def is_direct(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme.lower() in STREAM_SCHEMES:
        return True
    return os.path.splitext(parts.path.lower())[1] in DIRECT_EXTS


def looks_live(url: str) -> bool:
    p = urlsplit(url).path.lower()
    return p.endswith((".m3u8", ".ts")) or "/live/" in p or urlsplit(url).scheme.lower() in STREAM_SCHEMES


def resolve(url: str) -> dict:
    """{'url', 'audio', 'title', 'headers', 'live'}"""
    url = url.strip()
    if is_direct(url):
        return {"url": url, "audio": None, "title": os.path.basename(urlsplit(url).path) or url, "headers": {},
                "live": looks_live(url)}
    try:
        import yt_dlp
    except ImportError:
        return {"url": url, "audio": None, "title": url, "headers": {}, "live": False}
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 20,
            "format": "bestvideo*+bestaudio/best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    fmts = info.get("requested_formats") or []
    video = next((f for f in fmts if f.get("vcodec") not in (None, "none")), None)
    audio = next((f for f in fmts if f.get("acodec") not in (None, "none") and f is not video), None)
    main = video or info
    hdr = dict(main.get("http_headers") or info.get("http_headers") or {})
    headers = {}
    if hdr.get("User-Agent"):
        headers["user_agent"] = hdr.pop("User-Agent")
    if hdr.get("Referer"):
        headers["referrer"] = hdr.pop("Referer")
    hdr.pop("Accept", None)
    hdr.pop("Accept-Language", None)
    hdr.pop("Sec-Fetch-Mode", None)
    if hdr:
        headers["extra"] = hdr
    return {"url": main.get("url") or info.get("url") or url, "audio": audio.get("url") if audio else None,
            "title": info.get("title") or url, "headers": headers, "live": bool(info.get("is_live")),
            "height": main.get("height")}
