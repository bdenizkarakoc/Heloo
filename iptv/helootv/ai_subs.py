"""Yapay zekâ altyazı: konuşmayı yazıya çevirir (faster-whisper, ekran kartında; yoksa işlemcide).

Oyunlardaki canlı altyazı araçları gibi altyazısı olmayan videoya kendiliğinden altyazı üretir. Altyazı dosyası
parça parça yazılır ve mpv'ye eklenir; izlediğiniz yerden başlar, ilerledikçe dolar. "Çevir: İngilizce" seçilirse
Whisper konuşmayı İngilizceye çevirerek yazar. Kurulum isteğe bağlıdır (Altyazı menüsü → "Kur", ~200 MB + model).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from . import paths


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def install(progress: Callable[[str], None] | None = None) -> bool:
    say = progress or (lambda m: None)
    say("Yapay zekâ altyazı bileşeni kuruluyor (faster-whisper)…")
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper>=1.1"], capture_output=True,
                       text=True, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError("faster-whisper kurulamadı: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    say("Yapay zekâ altyazı bileşeni kuruldu.")
    return True


def _ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[tuple[float, float, str]]) -> str:
    return "".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{t.strip()}\n\n" for i, (a, b, t) in enumerate(segments, 1))


def _load_model(name: str):
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(name, device="cuda", compute_type="float16"), "GPU"
    except Exception:
        return WhisperModel(name, device="cpu", compute_type="int8"), "işlemci"


CHUNK = 40.0  # sn: her parça bitince altyazı dosyası güncellenir (ilk satırlar birkaç saniyede gelir)


def _pcm_chunk(ffmpeg: str, source: str, start: float, dur: float, headers: dict | None = None):
    """ffmpeg ile kaynağın [start, start+dur) aralığını 16 kHz tek kanal float diziye çevirir (None: bitti)."""
    import numpy as np
    args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    ua = (headers or {}).get("User-Agent")
    if ua and "://" in source:
        args += ["-user_agent", ua]
    args += ["-ss", f"{start:.2f}", "-i", source, "-t", f"{dur:.2f}", "-vn", "-ac", "1", "-ar", "16000",
             "-f", "s16le", "-"]
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    r = subprocess.run(args, capture_output=True, timeout=max(60.0, dur * 3), creationflags=flags)
    if not r.stdout:
        return None
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(source: str, out: str | Path, *, model: str = "small", language: str | None = None,
               translate: bool = False, start: float = 0.0, duration: float | None = None,
               headers: dict | None = None, progress: Callable[[str], None] | None = None,
               on_update: Callable[[str, int], None] | None = None,
               cancelled: Callable[[], bool] | None = None) -> str:
    """Kaynağı (dosya ya da bağlantı) izlenen yerden başlayarak parça parça yazıya döker; her parçada SRT'yi
    yazıp on_update(yol, adet) çağırır. ffmpeg yoksa faster-whisper kaynağı kendisi (tek seferde) çözer."""
    from .upscale import find_ffmpeg
    say = progress or (lambda m: None)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    say(f"Yapay zekâ modeli yükleniyor ({model})…")
    m, dev = _load_model(model)
    kwargs = {"vad_filter": True, "language": language, "task": "translate" if translate else "transcribe",
              "beam_size": 5, "condition_on_previous_text": False}
    done: list[tuple[float, float, str]] = []

    def flush():
        out.write_text(to_srt(done), encoding="utf-8")
        if on_update:
            on_update(str(out), len(done))

    ffmpeg = find_ffmpeg()
    lang = None
    if ffmpeg:
        pos = max(0.0, float(start) - 2.0)
        while not (cancelled and cancelled()):
            if duration and pos >= duration:
                break
            audio = _pcm_chunk(ffmpeg, source, pos, CHUNK, headers)
            if audio is None or len(audio) < 1600:
                break
            segs, info = m.transcribe(audio, **dict(kwargs, language=language or lang))
            lang = lang or getattr(info, "language", None)
            for seg in segs:
                if seg.text.strip():
                    done.append((pos + seg.start, pos + seg.end, seg.text))
            flush()
            say(f"Yapay zekâ altyazı ({dev}): {_ts(pos + CHUNK)[:8]} konumuna kadar hazır")
            if len(audio) < CHUNK * 16000 * 0.95:
                break
            pos += CHUNK
    else:
        say(f"Konuşma yazıya çevriliyor ({dev})…")
        if start > 5:
            kwargs["clip_timestamps"] = [float(start)]
        segments, info = m.transcribe(source, **kwargs)
        lang = getattr(info, "language", None)
        last = time.monotonic()
        for seg in segments:
            if cancelled and cancelled():
                break
            if seg.text.strip():
                done.append((seg.start, seg.end, seg.text))
            if len(done) in (1, 3) or time.monotonic() - last > 4:
                last = time.monotonic()
                flush()
    flush()
    say(f"Yapay zekâ altyazı hazır: {len(done)} satır ({lang or '?'})")
    return str(out)


def output_for(title: str) -> Path:
    import hashlib
    return paths.cache_dir() / "subs" / f"ai-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:10]}.srt"
