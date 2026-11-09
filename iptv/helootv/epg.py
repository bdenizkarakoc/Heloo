"""EPG: XMLTV akışlı ayrıştırma (gz destekli), Xtream kısa EPG çözümü ve M3U geri izleme (catch-up) adresleri."""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

_XMLTV_TIME = re.compile(r"^\s*(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-]\d{2}:?\d{2}|Z)?")


def parse_xmltv_time(value: str | None, shift_hours: float = 0.0) -> int | None:
    """'20241109203000 +0300' → UTC unix zamanı. Bölge yoksa UTC kabul edilir; tvg-shift saat olarak eklenir."""
    if not value:
        return None
    m = _XMLTV_TIME.match(value)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i) or 0) for i in range(1, 7))
    try:
        base = dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    tz = m.group(7)
    offset = 0
    if tz and tz != "Z":
        tz = tz.replace(":", "")
        sign = 1 if tz[0] == "+" else -1
        offset = sign * (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60)
    return int(base.timestamp()) - offset + int(shift_hours * 3600)


def _text_pref(elem: ET.Element, tag: str, langs=("tr", "tur", "tr-tr")) -> str:
    best = ""
    for child in elem.findall(tag):
        text = (child.text or "").strip()
        if not text:
            continue
        if (child.get("lang") or "").lower() in langs:
            return text
        if not best:
            best = text
    return best


def iter_xmltv(fileobj, shift_hours: float = 0.0) -> Iterator[tuple]:
    """('channel', id, [görünen adlar], ikon) ve ('programme', kanal, başlangıç, bitiş, başlık, açıklama) üretir."""
    context = ET.iterparse(fileobj, events=("start", "end"))
    root = None
    for event, elem in context:
        if event == "start":
            if root is None:
                root = elem
            continue
        tag = elem.tag
        if tag == "programme":
            start = parse_xmltv_time(elem.get("start"), shift_hours)
            stop = parse_xmltv_time(elem.get("stop"), shift_hours)
            channel = elem.get("channel") or ""
            if start and channel:
                if not stop or stop <= start:
                    stop = start + 1800
                yield ("programme", channel, start, stop, _text_pref(elem, "title"), _text_pref(elem, "desc"))
            elem.clear()
            if root is not None:
                root.clear()
        elif tag == "channel":
            names = [(n.text or "").strip() for n in elem.findall("display-name") if (n.text or "").strip()]
            icon = elem.find("icon")
            yield ("channel", elem.get("id") or "", names, icon.get("src") if icon is not None else "")
            elem.clear()
            if root is not None:
                root.clear()


def _b64(text) -> str:
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    compact = re.sub(r"\s+", "", s)
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact) and len(compact) % 4 == 0:
        try:
            decoded = base64.b64decode(compact, validate=True).decode("utf-8")  # katı: düz metni bozmaz
            if decoded and all(c.isprintable() or c in "\n\r\t" for c in decoded):
                return decoded.strip()
        except (binascii.Error, ValueError, UnicodeDecodeError):
            pass
    return s.strip()


def _ts(value, fallback_str=None) -> int | None:
    try:
        v = int(float(value))
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    if fallback_str:
        try:
            # Xtream 'start': '2024-11-09 20:30:00' (sunucu saati) — en iyi tahmin: yerel saat
            return int(time.mktime(time.strptime(str(fallback_str)[:19], "%Y-%m-%d %H:%M:%S")))
        except (ValueError, OverflowError):
            return None
    return None


def parse_xtream_listings(obj) -> list[dict]:
    rows = obj.get("epg_listings") if isinstance(obj, dict) else None
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        start = _ts(r.get("start_timestamp"), r.get("start"))
        stop = _ts(r.get("stop_timestamp") or r.get("end_timestamp"), r.get("end") or r.get("stop"))
        if not start:
            continue
        if not stop or stop <= start:
            stop = start + 1800
        out.append({
            "start": start,
            "stop": stop,
            "title": _b64(r.get("title")) or "Program",
            "desc": _b64(r.get("description")),
            "archive": str(r.get("has_archive", "0")) == "1",
        })
    out.sort(key=lambda p: p["start"])
    return out


# ---------------------------------------------------------------------- M3U catch-up

_TOKEN_RE = re.compile(r"\$?\{([a-zA-Z]+)(?::([^}]*))?\}")
_STRFTIME = {"Y": "%Y", "m": "%m", "d": "%d", "H": "%H", "M": "%M", "S": "%S", "y": "%y"}


def _fmt_time(ts: int, fmt: str | None, utc: bool = True) -> str:
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc if utc else None)
    if not fmt:
        return str(ts)
    return "".join(when.strftime(_STRFTIME[c]) if c in _STRFTIME else c for c in fmt)


def catchup_url(url: str, attrs: dict, start: int, stop: int, now: int | None = None,
                default_mode: str = "") -> str | None:
    """M3U catch-up: default/append/shift/flussonic/xc biçimlerinden geri izleme adresi üretir (desteklenmezse None)."""
    now = int(now or time.time())
    mode = (attrs.get("catchup") or attrs.get("catchup-type") or default_mode or "").lower()
    source = attrs.get("catchup-source") or ""
    duration = max(60, stop - start)

    def fill(template: str) -> str:
        def rep(m: re.Match) -> str:
            name, arg = m.group(1).lower(), m.group(2)
            if name in ("utc", "start", "timestamp") and not arg:
                return str(start)
            if name in ("utc", "start"):
                return _fmt_time(start, arg)
            if name in ("utcend", "end"):
                return _fmt_time(stop, arg) if arg else str(stop)
            if name in ("lutc", "now"):
                return _fmt_time(now, arg) if arg else str(now)
            if name == "duration":
                div = int(arg) if arg and arg.isdigit() else 1
                return str(duration // max(1, div))
            if name == "offset":
                div = int(arg) if arg and arg.isdigit() else 1
                return str(max(0, now - start) // max(1, div))
            if name in _STRFTIME:
                return _fmt_time(start, name)
            return m.group(0)
        return _TOKEN_RE.sub(rep, template)

    if mode in ("default", "") and source:
        return fill(source) if source.startswith(("http://", "https://", "rtmp://")) else url + fill(source)
    if mode == "append":
        return url + fill(source or "?utc={utc}&lutc={lutc}")
    if mode in ("shift", "timeshift"):
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}utc={start}&lutc={now}"
    if mode in ("flussonic", "flussonic-hls", "flussonic-ts", "fs"):
        m = re.match(r"^(.*)/(index|video|mono|playlist)\.m3u8(\?.*)?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}-{start}-{duration}.m3u8{m.group(3) or ''}"
        m = re.match(r"^(.*)/mpegts(\?.*)?$", url)
        if m:
            return f"{m.group(1)}/timeshift_abs-{start}.ts{m.group(2) or ''}"
        return None
    if mode == "xc":
        m = re.match(r"^(https?://[^/]+)/(?:live/)?([^/]+)/([^/]+)/(\d+)(\.\w+)?$", url)
        if m:
            local = dt.datetime.fromtimestamp(start).strftime("%Y-%m-%d:%H-%M")
            ext = (m.group(5) or ".ts")
            return f"{m.group(1)}/timeshift/{m.group(2)}/{m.group(3)}/{duration // 60}/{local}/{m.group(4)}{ext}"
    return None
