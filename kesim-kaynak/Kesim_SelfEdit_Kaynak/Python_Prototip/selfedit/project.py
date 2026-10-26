"""Proje modeli (JSON dosyası)."""
import json
from pathlib import Path


def new_project(width=1280, height=720, fps=30) -> dict:
    return {"version": 1, "output": {"width": width, "height": height, "fps": fps}, "clips": []}


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(proj: dict, path) -> None:
    Path(path).write_text(json.dumps(proj, indent=2, ensure_ascii=False), encoding="utf-8")


def add_clip(proj: dict, src: str, start=0.0, end=None) -> dict:
    clip = {"src": str(src), "start": float(start or 0), "end": float(end) if end else None, "effects": []}
    proj["clips"].append(clip)
    return clip


def add_effect(proj: dict, clip_index: int, name: str, params: dict = None) -> None:
    proj["clips"][clip_index]["effects"].append({"name": name, "params": params or {}})
