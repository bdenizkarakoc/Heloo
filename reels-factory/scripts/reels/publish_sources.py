"""Bir video dosyası için yayın bilgisi: başlık, paylaşım yazısı, konuşma metni ve kare tablosu.

Kaynaklar: bu bilgisayarda üretilen görevler (output/videos), buluttan gelenler (output/cloud) ve
Stüdyo klipleri (output/studio)."""
from __future__ import annotations

from pathlib import Path

from .config import ROOT
from .job import Job
from .util import StageError, read_json


def _post_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    txt = path.read_text(encoding="utf-8")
    return txt.split("\nKaynaklar:")[0].strip()  # kaynak/lisans listesi paylaşım yazısına girmez


def info_for(video_rel: str) -> dict:
    p = (ROOT / video_rel).resolve()
    if not p.is_file() or ROOT.resolve() not in p.parents:
        raise StageError("video bulunamadı")
    rel = p.relative_to(ROOT.resolve()).as_posix()
    if rel.startswith("output/videos/"):
        for job in Job.all():
            if (job.state.get("outputs") or {}).get("video") == rel:
                script = read_json(job.script_path, {}) or {}
                return {"video": p, "title": script.get("title") or p.stem, "source": "yerel",
                        "caption": _post_text(ROOT / job.state["outputs"].get("post", "")),
                        "text": " ".join(s.get("narration", "") for s in script.get("scenes", [])),
                        "sheet": job.dir / "qc" / "contact_sheet.jpg"}
    if rel.startswith("output/cloud/"):
        hist = {Path(h.get("output", "")).stem: h for h in read_json(ROOT / "output/cloud/history.json", []) or []}
        h = hist.get(p.stem, {})
        return {"video": p, "title": h.get("title") or p.stem, "source": "bulut",
                "caption": _post_text(p.with_suffix(".txt")), "text": "", "sheet": None}
    if rel.startswith("output/studio/"):
        pid = p.parent.name
        proj = read_json(ROOT / "studio" / "projects" / pid / "project.json", {}) or {}
        clip = next((c for c in proj.get("clips", []) if c.get("output") == rel), {})
        srt = p.with_suffix(".srt")
        text = " ".join(l for l in srt.read_text(encoding="utf-8").splitlines()
                        if l and not l[0].isdigit()) if srt.exists() else ""
        title = clip.get("title") or p.stem
        return {"video": p, "title": title, "source": "stüdyo", "caption": title, "text": text,
                "sheet": ROOT / clip["sheet"] if clip.get("sheet") else None, "chapters": clip.get("chapters", "")}
    return {"video": p, "title": p.stem, "source": "elle", "caption": "", "text": "", "sheet": None}
