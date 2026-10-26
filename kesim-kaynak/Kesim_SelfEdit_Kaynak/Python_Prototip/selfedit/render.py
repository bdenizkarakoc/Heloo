"""Projeyi tek bir FFmpeg komutuna çevirir ve çalıştırır."""
import shutil
import tempfile
import time
from pathlib import Path

from . import ffmpeg, telemetry
from .effects import EffectError, UnknownEffect, load_registry


class RenderError(RuntimeError):
    pass


_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]


def _esc_path(p) -> str:
    return "'" + str(p).replace("\\", "/").replace(":", "\\:") + "'"


def _find_font():
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return _esc_path(f)
    return None


def build_command(proj: dict, out, base_dir, reg, tmp):
    o = {"width": 1280, "height": 720, "fps": 30, **(proj.get("output") or {})}
    W, H, F = int(o["width"]), int(o["height"]), int(o["fps"])
    clips = proj.get("clips") or []
    if not clips:
        raise RenderError("Projede klip yok.")

    counter = [0]

    def textfile(text):
        counter[0] += 1
        p = Path(tmp) / f"text{counter[0]}.txt"
        p.write_text(str(text), encoding="utf-8")
        return _esc_path(p)

    font = _find_font()
    cmd = [ffmpeg.ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    chains, concat_in, all_fx = [], [], []

    for i, c in enumerate(clips):
        src = Path(c["src"])
        if not src.is_absolute():
            src = Path(base_dir) / src
        if not src.exists():
            raise RenderError(f"Dosya yok: {src}")
        info = ffmpeg.probe(src)
        if not info["has_video"]:
            raise RenderError(f"Görüntü akışı yok: {src}")
        start = float(c.get("start") or 0)
        end = float(c["end"]) if c.get("end") else info["duration"]
        if end <= start:
            raise RenderError(f"Klip {i}: bitiş başlangıçtan büyük olmalı")
        cmd += ["-i", str(src)]

        ctx = {"duration": end - start, "fps": F, "width": W, "height": H,
               "font": font, "textfile": textfile}
        vf = [f"trim=start={start}:end={end}", "setpts=PTS-STARTPTS", f"fps={F}",
              f"scale={W}:{H}:force_original_aspect_ratio=decrease",
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2", "setsar=1", "format=yuv420p"]
        af = [f"atrim=start={start}:end={end}", "asetpts=PTS-STARTPTS", "aresample=48000",
              "aformat=sample_fmts=fltp:channel_layouts=stereo"]

        for fx in c.get("effects") or []:
            all_fx.append(fx["name"])
            v, a, factor = reg.apply(fx["name"], fx.get("params"), dict(ctx))
            if v:
                vf.append(v)
            if a and info["has_audio"]:
                af.append(a)
            ctx["duration"] *= factor
        dur = ctx["duration"]

        vf += [f"scale={W}:{H}", "setsar=1"]
        chains.append(f"[{i}:v]" + ",".join(vf) + f"[v{i}]")
        if info["has_audio"]:
            af += ["apad", f"atrim=duration={dur:.4f}"]
            chains.append(f"[{i}:a]" + ",".join(af) + f"[a{i}]")
        else:
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.4f},asetpts=PTS-STARTPTS[a{i}]")
        concat_in.append(f"[v{i}][a{i}]")

    chains.append("".join(concat_in) + f"concat=n={len(clips)}:v=1:a=1[outv][outa]")
    cmd += ["-filter_complex", ";".join(chains), "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    return cmd, all_fx


def render_project(proj: dict, out, base_dir=".", registry=None) -> dict:
    reg = registry or load_registry()
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="selfedit_")
    effects = [fx["name"] for c in proj.get("clips", []) for fx in c.get("effects", [])]
    try:
        try:
            cmd, effects = build_command(proj, out, base_dir, reg, tmp)
        except UnknownEffect as e:
            telemetry.log("unknown_effect", name=str(e).split(": ")[-1])
            raise RenderError(str(e))
        except EffectError as e:
            telemetry.log("render_fail", effects=effects, error=str(e))
            raise RenderError(str(e))
        rc, tail = ffmpeg.run(cmd)
        if rc != 0:
            telemetry.log("render_fail", effects=effects, error=tail)
            raise RenderError(f"FFmpeg hata verdi:\n{tail}")
        seconds = time.time() - t0
        telemetry.log("render_ok", effects=effects, clips=len(proj["clips"]), seconds=round(seconds, 2))
        return {"output": str(out), "seconds": round(seconds, 2), "effects": effects}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
