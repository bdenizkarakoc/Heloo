"""Ortak yardımcılar: yeniden deneme, alt süreç, ffprobe, HTTP, ses dizileri, Türkçe metin."""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import requests

from . import log

L = log.get("util")


class StageError(RuntimeError):
    """Bir üretim adımının kalıcı hatası."""


class TransientError(RuntimeError):
    """Yeniden denemeye değer geçici hata (ağ, 5xx, zaman aşımı)."""


# ----------------------------------------------------------------------------
# Yeniden deneme
# ----------------------------------------------------------------------------

def retry(attempts: int = 3, backoff: float = 2.0, exceptions: tuple = (TransientError,)):
    """Geçici hatalarda üstel bekleme ile sınırlı sayıda yeniden dener (2s, 4s, 8s...)."""

    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last: Exception | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last = exc
                    if i == attempts - 1:
                        break
                    wait = backoff ** (i + 1)
                    L.warning("%s başarısız (%s); %.0f sn sonra tekrar (%d/%d)",
                              fn.__name__, exc, wait, i + 2, attempts)
                    time.sleep(wait)
            assert last is not None
            raise last

        return wrapper

    return deco


# ----------------------------------------------------------------------------
# Alt süreçler
# ----------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None, timeout: float | None = None,
        check: bool = True, env: dict | None = None, quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        L.debug("$ %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2500:]
        raise StageError(f"Komut başarısız ({proc.returncode}): {cmd[0]} ...\n{tail}")
    return proc


def which(name: str) -> str | None:
    return shutil.which(name)


def ffprobe(path: Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)], quiet=True)
    return json.loads(proc.stdout)


def media_duration(path: Path) -> float:
    info = ffprobe(path)
    return float(info["format"].get("duration") or 0.0)


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

_session: requests.Session | None = None


DEFAULT_UA = "ReelsFactory/0.1 (automated short-video generator; python-requests)"


def http(user_agent: str | None = None) -> requests.Session:
    """Paylaşılan HTTP oturumu. Bazı servisler (ör. Wikimedia) iletişim bilgisi içeren User-Agent ister:
    settings.yaml → visuals.user_agent."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = user_agent or DEFAULT_UA
    elif user_agent:
        _session.headers["User-Agent"] = user_agent
    return _session


def http_json(method: str, url: str, **kw) -> Any:
    """JSON isteği; 429/5xx ve ağ hataları TransientError olarak işaretlenir."""
    try:
        resp = http().request(method, url, timeout=kw.pop("timeout", 60), **kw)
    except requests.RequestException as exc:
        raise TransientError(f"ağ hatası: {type(exc).__name__}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientError(f"HTTP {resp.status_code} {url.split('?')[0]}")
    if resp.status_code >= 400:
        raise StageError(f"HTTP {resp.status_code} {url.split('?')[0]}: {resp.text[:300]}")
    return resp.json()


def download(url: str, dest: Path, max_mb: float = 200, headers: dict | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with http().get(url, stream=True, timeout=120, headers=headers or {}) as resp:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise TransientError(f"HTTP {resp.status_code} indirme")
            if resp.status_code >= 400:
                raise StageError(f"HTTP {resp.status_code} indirme: {url.split('?')[0]}")
            size = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    size += len(chunk)
                    if size > max_mb * 1024 * 1024:
                        raise StageError(f"dosya çok büyük (> {max_mb} MB)")
                    fh.write(chunk)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise TransientError(f"indirme hatası: {type(exc).__name__}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)   # yarım dosya bırakma
        raise
    tmp.replace(dest)
    return dest


# ----------------------------------------------------------------------------
# Ses dizileri (float32, mono/stereo)
# ----------------------------------------------------------------------------

def load_audio(path: Path, sr: int = 48000, channels: int = 1) -> np.ndarray:
    """Herhangi bir ses dosyasını ffmpeg ile float32 diziye çözer. Şekil: (n,) veya (n, ch)."""
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac",
                           str(channels), "-ar", str(sr), "-"], capture_output=True)
    if proc.returncode != 0:
        raise StageError(f"ses çözülemedi: {path.name}: {proc.stderr.decode()[-300:]}")
    data = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if channels > 1:
        data = data.reshape(-1, channels)
    return data


def write_wav(path: Path, data: np.ndarray, sr: int = 48000) -> Path:
    """float32 diziyi 16-bit PCM WAV olarak yazar (kırpma ile)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.clip(data, -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2")
    ch = 1 if arr.ndim == 1 else arr.shape[1]
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20.0))


# ----------------------------------------------------------------------------
# Türkçe metin
# ----------------------------------------------------------------------------

_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})
_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_VOWELS = set("aeıioöuüAEIİOÖUÜâîûÂÎÛ")


def tr_upper(text: str) -> str:
    return text.translate(_TR_UPPER).upper()


def tr_lower(text: str) -> str:
    return text.translate(_TR_LOWER).lower()


def norm_word(text: str) -> str:
    """Eşleştirme için kelime normalizasyonu: küçük harf, noktalama yok."""
    t = tr_lower(text)
    t = re.sub(r"[^\w%]+", "", t, flags=re.UNICODE)
    return t


def syllables(word: str) -> int:
    """Türkçede hece sayısı ≈ ünlü sayısı. Rakamlar için kaba tahmin."""
    if any(ch.isdigit() for ch in word):
        digits = sum(ch.isdigit() for ch in word)
        return max(2, digits * 2)
    return max(1, sum(1 for ch in word if ch in _VOWELS))


def slugify(text: str, max_len: int = 48) -> str:
    table = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                           "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    t = text.translate(table)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:max_len].strip("-") or "video"


def words_of(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def chunks(seq: Iterable, n: int) -> list[list]:
    out, cur = [], []
    for item in seq:
        cur.append(item)
        if len(cur) == n:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def env_ca_bundle() -> str | None:
    """Ortamda tanımlı özel CA paketi (kurumsal proxy vb.)."""
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        value = os.environ.get(key)
        if value and Path(value).exists():
            return value
    return None
