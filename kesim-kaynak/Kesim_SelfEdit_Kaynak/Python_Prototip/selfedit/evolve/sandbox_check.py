"""Bir eklentiyi gerçek bir deneme render'ından geçirir. Ayrı süreçte çalışır.

Kullanım: python -I sandbox_check.py <repo_kökü> <eklenti_adı>
Son satıra JSON sonuç yazar; başarılıysa çıkış kodu 0.
"""
import json
import sys
import tempfile
import traceback
from pathlib import Path


def main(repo: str, name: str) -> dict:
    sys.path.insert(0, repo)
    from selfedit import ffmpeg, project, render
    from selfedit.effects import load_registry

    reg = load_registry()
    if name not in reg.effects:
        return {"ok": False, "detail": f"yüklenemedi: {reg.errors}"}
    eff = reg.get(name)

    d = Path(tempfile.mkdtemp(prefix="selfedit_check_"))
    ffmpeg.make_test_video(d / "in.mp4", seconds=2, audio=True)

    # varsayılan parametrelerle
    proj = project.new_project(320, 240, 30)
    project.add_clip(proj, str(d / "in.mp4"))
    project.add_effect(proj, 0, name, {})
    render.render_project(proj, d / "out.mp4", d, registry=reg)
    info = ffmpeg.probe(d / "out.mp4")
    if not info["has_video"] or info["duration"] <= 0:
        return {"ok": False, "detail": "çıktı boş"}
    if (info["width"], info["height"]) != (320, 240):
        return {"ok": False, "detail": f"çıktı boyutu bozuldu: {info['width']}x{info['height']}"}

    # sessiz bir klip ve ikinci klip ile birleştirme de çalışmalı
    ffmpeg.make_test_video(d / "mute.mp4", seconds=1, audio=False)
    proj2 = project.new_project(320, 240, 30)
    project.add_clip(proj2, str(d / "mute.mp4"))
    project.add_effect(proj2, 0, name, {})
    project.add_clip(proj2, str(d / "in.mp4"), 0, 1)
    render.render_project(proj2, d / "out2.mp4", d, registry=reg)
    info2 = ffmpeg.probe(d / "out2.mp4")
    if not info2["has_video"] or info2["duration"] < 1.5:
        return {"ok": False, "detail": f"birleştirme sonucu beklenenden kısa: {info2['duration']:.2f}s"}
    return {"ok": True, "detail": f"{eff.name}: render ve birleştirme başarılı"}


if __name__ == "__main__":
    try:
        res = main(sys.argv[1], sys.argv[2])
    except Exception as e:
        res = {"ok": False, "detail": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)
