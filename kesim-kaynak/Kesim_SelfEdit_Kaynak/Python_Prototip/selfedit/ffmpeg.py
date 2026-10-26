"""FFmpeg / ffprobe sarmalayıcıları."""
import json
import shutil
import subprocess


class FFmpegError(RuntimeError):
    pass


def _bin(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise FFmpegError(f"{name} bulunamadı. FFmpeg'i kurup PATH'e ekleyin (https://ffmpeg.org).")
    return p


def ffmpeg_path() -> str:
    return _bin("ffmpeg")


def probe(path) -> dict:
    r = subprocess.run(
        [_bin("ffprobe"), "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise FFmpegError(f"Dosya okunamadı ({path}): {r.stderr.strip()[-300:]}")
    d = json.loads(r.stdout or "{}")
    streams = d.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    return {
        "duration": float((d.get("format") or {}).get("duration") or 0),
        "has_video": bool(video),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video[0].get("width") if video else None,
        "height": video[0].get("height") if video else None,
    }


def run(args: list, timeout: float = 900):
    """(returncode, stderr_sonu) döndürür."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "zaman aşımı"
    return r.returncode, (r.stderr or "")[-2000:]


def make_test_video(path, seconds: float = 2.0, audio: bool = True, size: str = "320x240") -> None:
    """Deneme/test için sentetik video üretir."""
    cmd = [ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    rc, tail = run(cmd, timeout=120)
    if rc != 0:
        raise FFmpegError(tail)
