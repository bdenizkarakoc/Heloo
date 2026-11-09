"""4K olarak kaydet: video ya da fotoğrafı yapay zekâ ile büyütüp dosyaya yazar.

NVIDIA RTX VSR yalnız oynatırken (sürücüde) çalışır, dosya üretmez. Kayıt için FFmpeg'in libplacebo filtresi (Vulkan,
ekran kartında) + yapay zekâ shader'ı (FSRCNNX / ArtCNN) + ewa_lanczossharp + deband kullanılır; video NVIDIA
NVENC (hevc_nvenc) ile, yoksa x265/x264 ile kodlanır. Vulkan/libplacebo yoksa lanczos + keskinleştirme (CPU).
FFmpeg: Windows'ta tools/fetch_mpv'nin indirdiği bin/ffmpeg.exe (zhongfly/mpv-winbuild; libplacebo + NVENC'li).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import paths, shaders

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".wmv", ".webm", ".flv", ".ts", ".m2ts", ".mts", ".mpg",
              ".mpeg", ".3gp", ".vob", ".ogv", ".hevc", ".h264", ".y4m", ".divx"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".jfif", ".avif", ".heic"}
BOXES = {"2160": (3840, 2160), "1440": (2560, 1440)}
COPY_AUDIO = {"aac", "mp3", "ac3", "eac3", "opus", "alac", "flac"}


class UpscaleError(Exception):
    pass


def _flags() -> int:
    return 0x08000000 if os.name == "nt" else 0


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    return "image" if ext in IMAGE_EXTS else "video"


def find_ffmpeg() -> str | None:
    for name in ("ffmpeg.exe", "ffmpeg"):
        p = paths.bin_dir() / name
        if p.is_file():
            return str(p)
    return shutil.which("ffmpeg")


def _run(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                          creationflags=_flags())


def capabilities(ffmpeg: str) -> dict:
    """libplacebo + Vulkan çalışıyor mu, hangi kodlayıcılar var (deneme kodlamasıyla)."""
    caps = {"libplacebo": False, "encoders": []}
    filt = _run([ffmpeg, "-hide_banner", "-filters"]).stdout
    if " libplacebo " in filt:
        r = _run([ffmpeg, "-hide_banner", "-v", "error", "-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk",
                  "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=1", "-frames:v", "1", "-vf",
                  "format=yuv420p,hwupload,libplacebo=w=128:h=128:format=yuv420p,hwdownload,format=yuv420p",
                  "-f", "null", "-"], timeout=60)
        caps["libplacebo"] = r.returncode == 0
    for enc in ("hevc_nvenc", "libx265", "h264_nvenc", "libx264"):
        r = _run([ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=256x256:rate=5",
                  "-frames:v", "2", "-c:v", enc, "-f", "null", "-"], timeout=60)
        if r.returncode == 0:
            caps["encoders"].append(enc)
    return caps


def probe(path: str) -> dict:
    """libmpv ile (ffprobe gerekmez): görüntü boyutu (döndürme dahil), süre, bit derinliği, ses kodlayıcısı."""
    paths.prepare_libmpv_search_path()
    import mpv
    m = mpv.MPV(vo="null", ao="null", pause="yes", ytdl="no", osc="no", image_display_duration="inf")
    try:
        m.play(path)
        end = time.time() + 20
        vp = None
        while time.time() < end:
            vp = m._get_property("video-params")
            if isinstance(vp, dict) and vp.get("w"):
                break
            time.sleep(0.05)
        if not (isinstance(vp, dict) and vp.get("w")):
            raise UpscaleError("Görüntü okunamadı (desteklenmeyen dosya?).")
        tracks = m._get_property("track-list") or []
        audio = next((t for t in tracks if t.get("type") == "audio" and t.get("selected")), None) or \
            next((t for t in tracks if t.get("type") == "audio"), None)
        rot = int(vp.get("rotate") or 0) % 180
        dw, dh = int(vp.get("dw") or vp["w"]), int(vp.get("dh") or vp["h"])
        if rot == 90:
            dw, dh = dh, dw
        pixfmt = str(vp.get("hw-pixelformat") or vp.get("pixelformat") or "")
        return {"w": int(vp["w"]), "h": int(vp["h"]), "dw": dw, "dh": dh,
                "duration": float(m._get_property("duration") or 0), "ten_bit": "10" in pixfmt or "p010" in pixfmt,
                "audio": (audio or {}).get("codec") or "", "gamma": str(vp.get("gamma") or "")}
    finally:
        m.terminate()


def target_size(dw: int, dh: int, target: str = "2160") -> tuple[int, int, float]:
    """Yatay → 3840×2160 kutusu, dikey (telefon/Reels) → 2160×3840. Yalnız büyütür; çift sayıya yuvarlar."""
    bw, bh = BOXES.get(target, BOXES["2160"])
    if dh > dw:
        bw, bh = bh, bw
    scale = max(1.0, min(bw / dw, bh / dh))
    w, h = int(round(dw * scale / 2) * 2), int(round(dh * scale / 2) * 2)
    return w, h, scale


def _filter_path(p: Path) -> str:
    s = p.resolve().as_posix().replace("'", "")
    return "'" + s.replace(":", "\\:") + "'"


def build_command(ffmpeg: str, src: str, dst: str, info: dict, size: tuple[int, int], caps: dict,
                  shader: Path | None, encoder: str | None, quality: str = "high", image: bool = False) -> list[str]:
    w, h = size
    pf = "p010le" if (info.get("ten_bit") and not image) else "yuv420p"
    if image:
        pf = "rgb24" if not caps.get("libplacebo") else "yuv444p"
    args = [ffmpeg, "-hide_banner", "-y", "-nostdin"]
    if caps.get("libplacebo"):
        args += ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"]
        lp = f"libplacebo=w={w}:h={h}:upscaler=ewa_lanczossharp:downscaler=mitchell:deband=true:format={pf}"
        if shader:
            lp += f":custom_shader_path={_filter_path(shader)}"
        vf = f"format={pf},hwupload,{lp},hwdownload,format={pf}"
    else:
        vf = f"scale={w}:{h}:flags=lanczos+accurate_rnd+full_chroma_int,unsharp=5:5:0.45:5:5:0,format={pf}"
    args += ["-i", src, "-vf", vf]
    if image:
        if pf != "rgb24":
            args[-1] = vf + ",format=rgb24"
        return args + ["-frames:v", "1", dst]
    args += ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_metadata", "0"]
    q = {"fast": 0, "high": 1, "max": 2}.get(quality, 1)
    if encoder in ("hevc_nvenc", "h264_nvenc"):
        args += ["-c:v", encoder, "-preset", ("p5", "p7", "p7")[q], "-tune", "hq", "-rc", "vbr",
                 "-cq", str((23, 19, 16)[q]), "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1"]
        if encoder == "hevc_nvenc":
            args += ["-profile:v", "main10" if pf == "p010le" else "main", "-tag:v", "hvc1"]
    elif encoder == "libx265":
        args += ["-c:v", "libx265", "-preset", ("fast", "medium", "slow")[q], "-crf", str((22, 19, 16)[q]),
                 "-tag:v", "hvc1"]
    else:
        args += ["-c:v", "libx264", "-preset", ("fast", "medium", "slow")[q], "-crf", str((21, 18, 15)[q])]
    if info.get("audio"):
        args += ["-c:a", "copy"] if info["audio"] in COPY_AUDIO else ["-c:a", "aac", "-b:a", "256k"]
    return args + ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", dst]


def output_path(src: str, target: str = "2160", folder: str = "", image: bool = False) -> Path:
    p = Path(src)
    label = "4K" if target == "2160" else "1440p"
    out_dir = Path(folder) if folder else p.parent
    ext = ".png" if image else ".mp4"
    cand = out_dir / f"{p.stem} ({label}){ext}"
    i = 2
    while cand.exists():
        cand = out_dir / f"{p.stem} ({label} {i}){ext}"
        i += 1
    return cand


def export(src: str, *, target: str = "2160", model: str = "fsrcnnx", quality: str = "high", folder: str = "",
           progress: Callable[[str], None] | None = None, percent: Callable[[float], None] | None = None,
           cancelled: Callable[[], bool] | None = None, caps: dict | None = None) -> str:
    say = progress or (lambda m: None)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise UpscaleError("ffmpeg bulunamadı. Ayarlar → Sistem → 'mpv bileşenlerini indir' ffmpeg'i de indirir.")
    caps = caps or capabilities(ffmpeg)
    image = kind_of(src) == "image"
    say(f"İnceleniyor: {Path(src).name}")
    info = probe(src)
    size = target_size(info["dw"], info["dh"], target)
    shader = shaders.resolve(model) if (caps.get("libplacebo") and model != "off") else None
    dst = output_path(src, target, folder, image)
    dst.parent.mkdir(parents=True, exist_ok=True)
    encoders = [e for e in ("hevc_nvenc", "h264_nvenc", "libx265", "libx264") if e in caps.get("encoders", [])]
    if not image and not encoders:
        raise UpscaleError("Kullanılabilir video kodlayıcı yok (NVENC/x265/x264).")
    how = ("yapay zekâ (" + shader.stem + ")" if shader else "ewa_lanczossharp" if caps.get("libplacebo")
           else "lanczos + keskinleştirme")
    for enc in (encoders or [None]):
        cmd = build_command(ffmpeg, src, str(dst), info, size, caps, shader, enc, quality, image)
        say(f"{Path(src).name}: {info['dw']}×{info['dh']} → {size[0]}×{size[1]} · {how}" +
            (f" · {enc}" if enc else ""))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                creationflags=_flags())
        err_tail: list[str] = []
        import threading

        def drain():
            for line in proc.stderr:
                err_tail.append(line.rstrip())
                del err_tail[:-30]

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        for line in proc.stdout:
            if cancelled and cancelled():
                proc.kill()
                break
            if line.startswith("out_time_us=") and info["duration"] > 0 and percent:
                try:
                    percent(min(100.0, int(line.split("=", 1)[1]) / 1e6 / info["duration"] * 100))
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=2)
        if cancelled and cancelled():
            dst.unlink(missing_ok=True)
            raise UpscaleError("İptal edildi.")
        if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            if percent:
                percent(100.0)
            return str(dst)
        dst.unlink(missing_ok=True)
        say(f"{enc or 'ffmpeg'} başarısız, sonraki kodlayıcı deneniyor…")
    raise UpscaleError("Dışa aktarma başarısız: " + " | ".join(err_tail[-3:]) if err_tail else "bilinmeyen hata")
