"""HLS ana listesi (master playlist) çözümü: en yüksek kaliteyi seçip mpv'ye doğrudan onu vermek.

Neden: FFmpeg'in hls çözücüsü açılışta her kalite seçeneğinin (1080p/720p/480p/360p …) ilk parçalarını indirip
ancak sonra birini seçer. Dört seçenekli bir kanalda bu 8 gereksiz parça indirmesi ve saniyelerce gecikme demektir.
Ana listeyi kendimiz okuyup tek bir kalite listesini açınca kanal neredeyse anında başlar.

Güvenli düşüş: ayrı ses/görüntü izleri (#EXT-X-MEDIA ... URI=) olan listelerde, okunamayan listelerde ve
sabitlenen adres oynatılamazsa (ör. çerez gerektiren CDN) özgün adres kullanılır.
"""
from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin

from .netutil import _context, _decode_body, _request

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
SUPPORTED_CODECS = ("avc1", "avc3", "hvc1", "hev1", "av01", "mp4a", "ac-3", "ec-3", "mp3", "vp09", "opus")


@dataclass
class Variant:
    uri: str
    bandwidth: int = 0
    width: int = 0
    height: int = 0
    codecs: str = ""
    fps: float = 0.0


def parse_attrs(text: str) -> dict:
    return {k: v.strip('"') for k, v in _ATTR.findall(text)}


def parse_master(text: str) -> tuple[list[Variant], bool]:
    """(varyantlar, ayrı_medya_var_mı). Ana liste değilse boş liste döner."""
    variants: list[Variant] = []
    separate_media = False
    pending: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA:"):
            a = parse_attrs(line[13:])
            if a.get("URI") and a.get("TYPE", "").upper() in ("AUDIO", "VIDEO"):
                separate_media = True
        elif line.startswith("#EXT-X-STREAM-INF:"):
            pending = parse_attrs(line[18:])
        elif line.startswith("#"):
            continue
        elif pending is not None:
            res = pending.get("RESOLUTION", "")
            w, _, h = res.partition("x")
            try:
                fps = float(pending.get("FRAME-RATE") or 0)
            except ValueError:
                fps = 0.0
            variants.append(Variant(uri=line, bandwidth=int(pending.get("BANDWIDTH") or 0),
                                    width=int(w) if w.isdigit() else 0, height=int(h) if h.isdigit() else 0,
                                    codecs=pending.get("CODECS", ""), fps=fps))
            pending = None
    return variants, separate_media


def best_variant(variants: list[Variant]) -> Variant | None:
    def playable(v: Variant) -> bool:
        if not v.codecs:
            return True
        return all(c.strip().lower().startswith(SUPPORTED_CODECS) for c in v.codecs.split(",") if c.strip())

    cands = [v for v in variants if playable(v)] or variants
    if not cands:
        return None
    return max(cands, key=lambda v: (v.height, v.width, v.fps, v.bandwidth))


def _fetch(url: str, headers: dict | None, default_ua: str | None, timeout: float, verify: bool) -> tuple[str, str]:
    headers = headers or {}
    extra = {}
    if headers.get("referrer"):
        extra["Referer"] = headers["referrer"]
    if headers.get("origin"):
        extra["Origin"] = headers["origin"]
    for k, v in (headers.get("extra") or {}).items():
        extra[k] = v
    req = _request(url, headers.get("user_agent") or default_ua, extra)
    with urllib.request.urlopen(req, timeout=timeout, context=_context(verify)) as resp:
        final_url = resp.geturl() or url
        body = _decode_body(resp.read(512 * 1024), resp.headers.get("Content-Encoding"))
    return body.decode("utf-8", "replace"), final_url


def target_duration(text: str) -> float | None:
    m = re.search(r"#EXT-X-TARGETDURATION:\s*([\d.]+)", text)
    return float(m.group(1)) if m else None


def probe_target_duration(url: str, headers: dict | None = None, default_ua: str | None = None,
                          timeout: float = 4.0, verify: bool = True) -> float | None:
    """Kalite (medya) listesinin parça süresi — HLS'de canlıya yetişme eşikleri buna göre ayarlanır."""
    text, _final = _fetch(url, headers, default_ua, timeout, verify)
    return target_duration(text)


def resolve_variant(url: str, headers: dict | None = None, default_ua: str | None = None,
                    timeout: float = 3.0, verify: bool = True) -> tuple[str, Variant | None]:
    """Ana listeyse en iyi kalitenin mutlak adresini döndürür; değilse (ya da ayrı ses izi varsa) özgün adresi."""
    text, final_url = _fetch(url, headers, default_ua, timeout, verify)
    if "#EXTM3U" not in text[:1024] or "#EXT-X-STREAM-INF" not in text:
        return url, None
    variants, separate = parse_master(text)
    if separate:
        return url, None
    best = best_variant(variants)
    if best is None:
        return url, None
    return urljoin(final_url, best.uri), best
