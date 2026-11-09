"""Küçük HTTP yardımcıları (standart kütüphane): zaman aşımı, yeniden deneme, gzip, akışlı indirme."""
from __future__ import annotations

import gzip
import io
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Callable

DEFAULT_UA = "VLC/3.0.21 LibVLC/3.0.21"


class NetError(Exception):
    """Kullanıcıya gösterilebilir ağ hatası (Türkçe ileti)."""


def _context(verify: bool = True) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(url: str, user_agent: str | None, headers: dict | None,
             accept_encoding: str = "gzip, deflate") -> urllib.request.Request:
    h = {"User-Agent": user_agent or DEFAULT_UA, "Accept": "*/*", "Accept-Encoding": accept_encoding}
    if headers:
        h.update({k: v for k, v in headers.items() if v})
    return urllib.request.Request(url, headers=h)


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        msg = {
            401: "kimlik doğrulama başarısız (kullanıcı adı/şifre)",
            403: "erişim reddedildi (hesap süresi, IP ya da bağlantı sınırı)",
            404: "bulunamadı",
            407: "vekil sunucu kimlik doğrulaması gerekli",
            429: "çok fazla istek; biraz sonra tekrar deneyin",
            500: "sunucu hatası",
            502: "sunucu ağ geçidi hatası",
            503: "sunucu şu an hizmet veremiyor",
            512: "sunucu hatası",
        }.get(exc.code, exc.reason if isinstance(exc.reason, str) else "HTTP hatası")
        return f"HTTP {exc.code}: {msg}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            return "sunucu adı çözümlenemedi (adres yanlış ya da internet yok)"
        if isinstance(reason, ssl.SSLError):
            return f"TLS/SSL hatası: {reason}"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "zaman aşımı"
        if isinstance(reason, ConnectionRefusedError):
            return "bağlantı reddedildi"
        return f"bağlantı hatası: {reason}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "zaman aşımı"
    return str(exc) or exc.__class__.__name__


def _decode_body(data: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip" or data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except (OSError, EOFError):
            return data
    if enc == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def http_get(url: str, *, user_agent: str | None = None, headers: dict | None = None, timeout: float = 20,
             retries: int = 2, verify: bool = True, max_bytes: int = 512 * 1024 * 1024) -> bytes:
    """URL'yi belleğe indirir (gzip açılır). Ağ hatalarında kısa beklemeyle yeniden dener; 4xx'te denemez."""
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            req = _request(url, user_agent, headers)
            with urllib.request.urlopen(req, timeout=timeout, context=_context(verify)) as resp:
                data = resp.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise NetError("yanıt çok büyük")
                return _decode_body(data, resp.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as e:
            last = e
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, ssl.SSLError) as e:
            last = e
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    raise NetError(describe_error(last) if last else "bilinmeyen ağ hatası")


def http_download(url: str, dest: Path, *, user_agent: str | None = None, headers: dict | None = None,
                  timeout: float = 30, verify: bool = True,
                  progress: Callable[[int, int], None] | None = None) -> Path:
    """Büyük dosyayı diske akıtarak indirir (EPG, libmpv arşivi). İçerik gzip ise açılmadan yazılır."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = _request(url, user_agent, headers, accept_encoding="identity")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_context(verify)) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        tmp.replace(dest)
        return dest
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, ssl.SSLError) as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise NetError(describe_error(e)) from e


def open_text_maybe_gzip(path: Path) -> io.TextIOBase:
    f = open(path, "rb")
    magic = f.read(2)
    f.seek(0)
    raw = gzip.GzipFile(fileobj=f) if magic == b"\x1f\x8b" else f
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


def open_binary_maybe_gzip(path: Path):
    f = open(path, "rb")
    magic = f.read(2)
    f.seek(0)
    return gzip.GzipFile(fileobj=f) if magic == b"\x1f\x8b" else f


def copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
