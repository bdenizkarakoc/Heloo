"""Video iyileştirme ve çözünürlük yükseltme (Kesim'den ve fabrikadan): 1080p / 2K / 4K.

Zincir (ffmpeg, her adım seçilebilir):
  gürültü azaltma (hqdn3d) → ölçekleme (lanczos; kısa kenar = hedef) → keskinleştirme (CAS) → hafif renk canlandırma
  → kodlama: NVIDIA varsa h264_nvenc (çok hızlı), yoksa libx264. Ses istenirse audiofx ile temizlenir, yoksa kopyalanır.
Not: Bu klasik (yapay zekâsız) büyütmedir; ayrıntı uydurmaz, ama yumuşaklığı ve gürültüyü belirgin biçimde azaltır.
"""
from __future__ import annotations

import functools
import time
from pathlib import Path

from . import log
from .util import StageError, ffprobe, run

L = log.get("videofx")
TARGETS = {"orijinal": None, "1080p": 1080, "2k": 1440, "4k": 2160}
DENOISE = {"yok": None, "hafif": "hqdn3d=1.5:1.2:3:2.5", "orta": "hqdn3d=3:2.5:5:4", "güçlü": "hqdn3d=5:4:8:6"}
SHARPEN = {"yok": 0.0, "hafif": 0.35, "orta": 0.55, "güçlü": 0.8}


@functools.lru_cache(maxsize=1)
def nvenc_ok() -> bool:
    """NVIDIA donanım kodlayıcısı gerçekten çalışıyor mu (sürücü + ffmpeg)?"""
    p = run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2", "-c:v", "h264_nvenc",
             "-f", "null", "-"], check=False, quiet=True)
    return p.returncode == 0


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def enhance_video(src: Path, dest: Path, target: str = "orijinal", denoise: str = "hafif", sharpen: str = "orta",
                  color: bool = True, audio: bool = False, fps: int | None = None) -> dict:
    """src → dest (mp4). Rapor: boyutlar, uygulanan adımlar, kodlayıcı, süre."""
    t0 = time.time()
    info = ffprobe(src)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic") != 1), None)
    if not v:
        raise StageError("dosyada video yok")
    w, h = int(v["width"]), int(v["height"])
    rot = abs(int(((v.get("side_data_list") or [{}])[0]).get("rotation", 0) or 0))
    if rot in (90, 270):
        w, h = h, w
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    steps, vf = [], []

    if DENOISE.get(denoise):
        vf.append(DENOISE[denoise])
        steps.append(f"gürültü azaltma ({denoise})")
    short = TARGETS.get(target.lower()) if target else None
    ow, oh = w, h
    if short and short != min(w, h):
        k = short / min(w, h)
        ow, oh = _even(w * k), _even(h * k)
        vf.append(f"scale={ow}:{oh}:flags=lanczos")
        steps.append(f"{'büyütme' if k > 1 else 'küçültme'} {w}×{h} → {ow}×{oh}")
    if SHARPEN.get(sharpen):
        vf.append(f"cas={SHARPEN[sharpen]}")
        steps.append(f"keskinleştirme ({sharpen})")
    if color:
        vf.append("eq=contrast=1.04:saturation=1.10:gamma=1.01")
        steps.append("renk canlandırma")
    if fps:
        vf.append(f"fps={int(fps)}")
    vf.append("format=yuv420p")

    if nvenc_ok():
        enc = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
               "-profile:v", "high"]
        encoder = "NVIDIA (h264_nvenc)"
    else:
        enc = ["-c:v", "libx264", "-preset", "fast" if max(ow, oh) > 2000 else "medium", "-crf", "18", "-profile:v", "high"]
        encoder = "işlemci (libx264)"

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
    clean = None
    if audio and has_audio:
        from . import audiofx
        clean = dest.with_suffix(".ses.wav")
        audiofx.enhance(src, clean, "orta", -14.0, channels=2)
        cmd += ["-i", clean, "-map", "0:v:0", "-map", "1:a:0"]
        steps.append("ses temizleme")
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
    cmd += ["-vf", ",".join(vf), *enc, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            "-shortest", dest]
    try:
        run(cmd)
    finally:
        if clean:
            clean.unlink(missing_ok=True)
    rep = {"output": str(dest), "size": f"{ow}×{oh}", "steps": steps, "encoder": encoder,
           "seconds": round(time.time() - t0, 1)}
    L.info("Video iyileştirildi: %s (%s, %s sn)", dest.name, ", ".join(steps), rep["seconds"])
    return rep
