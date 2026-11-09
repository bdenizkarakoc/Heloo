"""M3U / M3U8 (m3u_plus) ayrıştırıcı.

Desteklenenler: #EXTM3U başlığı (url-tvg, x-tvg-url, tvg-shift, catchup), #EXTINF öznitelikleri (tvg-id, tvg-name,
tvg-logo, group-title, catchup, catchup-source, catchup-days, tvg-rec), #EXTGRP, #EXTVLCOPT (http-user-agent,
http-referrer, http-origin), #EXTHTTP (JSON başlıklar), Kodi "url|User-Agent=..&Referer=.." ve #KODIPROP.

Sınıflandırma: URL yolu (/movie/, /series/) ve dosya uzantısı (.mkv, .mp4 ...) önceliklidir; canlı yayın gibi görünen
bir bağlantı grup adı "Movies" olsa bile canlı kalır (iptv-org'daki film kanalları gibi).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

VOD_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".webm", ".flv", ".mpg", ".mpeg", ".divx", ".vob",
    ".3gp", ".ogv", ".m2ts", ".iso",
}
_ATTR_RE = re.compile(r'([A-Za-z0-9_\-:.]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\',]+))')

SERIES_PATTERNS = [
    # "Dizi Adı S01 E05", "Dizi.Adi.S01E05", "Dizi - s1e5"
    re.compile(r"^(?P<series>.+?)[\s._\-:|]*\bS(?P<season>\d{1,2})[\s._\-]*E[Pp]?(?P<episode>\d{1,4})\b", re.I),
    # "Dizi Adı 2. Sezon 14. Bölüm"
    re.compile(r"^(?P<series>.+?)[\s\-:|]*(?P<season>\d{1,2})\s*\.?\s*Sezon[\s\-:|]*(?P<episode>\d{1,4})\s*\.?\s*B[oö]l[uü]m", re.I),
    # "Dizi Adı Sezon 2 Bölüm 14"
    re.compile(r"^(?P<series>.+?)[\s\-:|]*Sezon\s*(?P<season>\d{1,2})[\s\-:|]*B[oö]l[uü]m\s*(?P<episode>\d{1,4})", re.I),
    # "Dizi Adı 1x05"
    re.compile(r"^(?P<series>.+?)[\s\-:|]+(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b", re.I),
    # "Dizi Adı 14. Bölüm" (tek sezon)
    re.compile(r"^(?P<series>.+?)[\s\-:|]*(?P<episode>\d{1,4})\s*\.?\s*B[oö]l[uü]m", re.I),
]
_SERIES_GROUP_RE = re.compile(r"(^|[^a-z])(series|dizi|diziler|tv shows?|sezon)([^a-z]|$)", re.I)


@dataclass
class M3UEntry:
    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    duration: float = -1
    attrs: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)   # {"user_agent":..., "referrer":..., "origin":..., "extra": {...}}
    kind: str = "live"                            # live | movie | series
    series: str | None = None
    season: int | None = None
    episode: int | None = None
    drm: bool = False


@dataclass
class M3UPlaylist:
    entries: list[M3UEntry] = field(default_factory=list)
    header: dict = field(default_factory=dict)

    @property
    def epg_urls(self) -> list[str]:
        urls: list[str] = []
        for key in ("url-tvg", "x-tvg-url", "tvg-url"):
            for u in re.split(r"[,\s]+", self.header.get(key, "")):
                if u.startswith(("http://", "https://")) and u not in urls:
                    urls.append(u)
        return urls

    def counts(self) -> dict:
        out = {"live": 0, "movie": 0, "series": 0}
        for e in self.entries:
            out[e.kind] = out.get(e.kind, 0) + 1
        return out


def parse_attrs(text: str) -> dict:
    attrs = {}
    for m in _ATTR_RE.finditer(text or ""):
        key = m.group(1).lower()
        val = next((g for g in m.groups()[1:] if g is not None), "")
        attrs[key] = val.strip()
    return attrs


def _split_extinf(body: str) -> tuple[float, dict, str]:
    """'-1 tvg-id="x" group-title="a,b",Ad' → (-1, attrs, 'Ad'). Tırnak içindeki virgülleri atlar."""
    quote = None
    split_at = -1
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            # yalnızca öznitelik değeri başlangıcında tırnak say ( key="..." )
            if i > 0 and body[i - 1] == "=":
                quote = ch
        elif ch == ",":
            split_at = i
            break
    if split_at < 0:
        head, title = body, ""
    else:
        head, title = body[:split_at], body[split_at + 1:]
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", head)
    duration = float(m.group(1)) if m else -1.0
    attrs = parse_attrs(head[m.end():] if m else head)
    return duration, attrs, title.strip()


def split_pipe_headers(url: str) -> tuple[str, dict]:
    """Kodi biçimi: 'http://x/y.m3u8|User-Agent=abc&Referer=https://r/' → (url, başlıklar)."""
    if "|" not in url:
        return url, {}
    base, _, rest = url.partition("|")
    headers = {}
    for k, v in parse_qsl(rest, keep_blank_values=True):
        headers[k.strip()] = unquote(v).strip()
    return base.strip(), headers


def _normalize_headers(raw: dict) -> dict:
    out: dict = {}
    extra: dict = {}
    for k, v in raw.items():
        lk = k.lower().replace("_", "-")
        if lk in ("user-agent", "http-user-agent"):
            out["user_agent"] = v
        elif lk in ("referer", "referrer", "http-referrer", "http-referer"):
            out["referrer"] = v
        elif lk in ("origin", "http-origin"):
            out["origin"] = v
        elif v:
            extra[k] = v
    if extra:
        out["extra"] = extra
    return out


def parse_series(name: str) -> tuple[str, int, int] | None:
    for rx in SERIES_PATTERNS:
        m = rx.search(name or "")
        if m:
            series = re.sub(r"[\s._\-:|]+$", "", m.group("series")).strip(" .-_|:")
            if not series:
                continue
            season = int(m.groupdict().get("season") or 1)
            return series, season, int(m.group("episode"))
    return None


def classify(url: str, group: str = "", name: str = "") -> str:
    try:
        path = unquote(urlsplit(url).path).lower()
    except ValueError:
        path = url.lower()
    if "/series/" in path:
        return "series"
    if "/movie/" in path or "/movies/" in path:
        return "movie"
    if "/vod/" in path:
        return "series" if parse_series(name) else "movie"
    ext = os.path.splitext(path)[1]
    if ext in VOD_EXTS:
        if parse_series(name) or _SERIES_GROUP_RE.search(group or ""):
            return "series"
        return "movie"
    return "live"


def parse_m3u(text: str) -> M3UPlaylist:
    pl = M3UPlaylist()
    if text.startswith("﻿"):
        text = text[1:]
    pending: dict | None = None
    opts: dict = {}
    group_hint = ""
    kodi_props: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            pl.header.update(parse_attrs(line[7:]))
            continue
        if line.startswith("#EXTINF:"):
            duration, attrs, title = _split_extinf(line[8:])
            pending = {"duration": duration, "attrs": attrs, "title": title}
            continue
        if line.startswith("#EXTGRP:"):
            group_hint = line[8:].strip()
            continue
        if line.startswith("#EXTVLCOPT:"):
            key, _, val = line[11:].partition("=")
            opts[key.strip()] = val.strip()
            continue
        if line.startswith("#EXTHTTP:"):
            try:
                data = json.loads(line[9:])
                if isinstance(data, dict):
                    opts.update({str(k): str(v) for k, v in data.items()})
            except ValueError:
                pass
            continue
        if line.startswith("#KODIPROP:"):
            key, _, val = line[10:].partition("=")
            kodi_props[key.strip().lower()] = val.strip()
            continue
        if line.startswith("#"):
            continue
        # URL satırı
        url, pipe = split_pipe_headers(line)
        raw_headers = dict(opts)
        raw_headers.update(pipe)
        stream_headers = kodi_props.get("inputstream.adaptive.stream_headers") or kodi_props.get(
            "inputstream.adaptive.manifest_headers")
        if stream_headers:
            raw_headers.update(dict(parse_qsl(stream_headers, keep_blank_values=True)))
        info = pending or {"duration": -1, "attrs": {}, "title": ""}
        attrs = info["attrs"]
        name = info["title"] or attrs.get("tvg-name") or os.path.basename(urlsplit(url).path) or url
        group = attrs.get("group-title") or group_hint
        entry = M3UEntry(
            name=name.strip(),
            url=url,
            group=group.strip(),
            logo=attrs.get("tvg-logo", "") or attrs.get("logo", ""),
            tvg_id=attrs.get("tvg-id", ""),
            tvg_name=attrs.get("tvg-name", ""),
            duration=info["duration"],
            attrs=attrs,
            headers=_normalize_headers(raw_headers),
            drm=bool(kodi_props.get("inputstream.adaptive.license_type") or kodi_props.get("inputstream.adaptive.license_key")),
        )
        entry.kind = classify(url, entry.group, entry.name)
        if entry.kind == "series":
            parsed = parse_series(entry.name)
            if parsed:
                entry.series, entry.season, entry.episode = parsed
            else:
                entry.series, entry.season, entry.episode = entry.name, 1, 1
        pl.entries.append(entry)
        pending, opts, group_hint, kodi_props = None, {}, "", {}
    return pl


def xtream_from_m3u_url(url: str) -> tuple[str, str, str] | None:
    """'http://h:8080/get.php?username=u&password=p&type=m3u_plus' → ('http://h:8080', 'u', 'p')."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    q = dict(parse_qsl(parts.query))
    if parts.path.rstrip("/").endswith(("get.php", "player_api.php")) and q.get("username") and q.get("password"):
        return f"{parts.scheme}://{parts.netloc}", q["username"], q["password"]
    return None
