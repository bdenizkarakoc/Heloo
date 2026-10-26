"""Üretim görevleri: her video için ayrı bir klasör ve izlenebilir durum dosyası (job.json)."""
from __future__ import annotations

import contextlib
import datetime as dt
import secrets
import time
import traceback
from pathlib import Path
from typing import Any, Iterator

from . import log
from .config import ROOT
from .util import read_json, slugify, write_json

PROJECTS = ROOT / "projects"
STAGES = ["script", "voice", "captions", "visuals", "music", "compose", "render", "mix", "qc", "export"]

L = log.get("job")


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = PROJECTS / job_id
        self.state_path = self.dir / "job.json"
        self.state: dict[str, Any] = read_json(self.state_path, None) or {}

    # ------------------------------------------------------------------ paths
    def p(self, *parts: str) -> Path:
        path = self.dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def d(self, *parts: str) -> Path:
        path = self.dir.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def script_path(self) -> Path:
        return self.dir / "script.json"

    # ------------------------------------------------------------------ state
    @classmethod
    def create(cls, category: str, topic_hint: str | None = None) -> "Job":
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        job_id = f"{stamp}-{slugify(category, 20)}-{secrets.token_hex(2)}"
        job = cls(job_id)
        job.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("media", "voice", "visuals", "audio", "composition", "render", "qc", "final"):
            (job.dir / sub).mkdir(exist_ok=True)
        job.state = {
            "id": job_id,
            "created": _now(),
            "category": category,
            "topic_hint": topic_hint,
            "status": "new",
            "stages": {s: {"status": "pending"} for s in STAGES},
            "warnings": [],
            "providers": {},
            "outputs": {},
        }
        job.save()
        return job

    @classmethod
    def load(cls, job_id: str) -> "Job":
        job = cls(job_id)
        if not job.state_path.exists():
            raise FileNotFoundError(f"Görev bulunamadı: {job_id}")
        return job

    @classmethod
    def all(cls) -> list["Job"]:
        if not PROJECTS.exists():
            return []
        return [cls(p.name) for p in sorted(PROJECTS.iterdir()) if (p / "job.json").exists()]

    def save(self) -> None:
        self.state["updated"] = _now()
        write_json(self.state_path, self.state)

    def set_status(self, status: str) -> None:
        self.state["status"] = status
        self.save()

    def warn(self, msg: str) -> None:
        L.warning("[%s] %s", self.id, msg)
        self.state.setdefault("warnings", []).append({"time": _now(), "msg": msg})
        self.save()

    def stage_state(self, name: str) -> dict:
        return self.state.setdefault("stages", {}).setdefault(name, {"status": "pending"})

    def stage_done(self, name: str) -> bool:
        return self.stage_state(name).get("status") == "done"

    def reset_from(self, name: str) -> None:
        """Belirtilen adımdan itibaren bütün adımları yeniden çalıştırılacak şekilde işaretler."""
        hit = False
        for s in STAGES:
            if s == name:
                hit = True
            if hit:
                self.state["stages"][s] = {"status": "pending"}
        self.save()

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[dict]:
        """Bir adımı zaman, deneme sayısı ve hata bilgisiyle kaydeder.

        Başarısız adımlar asla 'done' olarak işaretlenmez.
        """
        st = self.stage_state(name)
        st["status"] = "running"
        st["started"] = _now()
        st["attempts"] = int(st.get("attempts", 0)) + 1
        st.pop("error", None)
        info: dict[str, Any] = {}
        self.save()
        t0 = time.time()
        L.info("▶ %s", name)
        try:
            yield info
        except Exception as exc:
            st["status"] = "failed"
            st["error"] = f"{type(exc).__name__}: {exc}"[:2000]
            st["finished"] = _now()
            st["seconds"] = round(time.time() - t0, 2)
            st["info"] = info
            L.error("✖ %s başarısız: %s", name, exc)
            L.debug("%s", traceback.format_exc())
            self.save()
            raise
        st["status"] = "done"
        st["finished"] = _now()
        st["seconds"] = round(time.time() - t0, 2)
        st["info"] = info
        self.save()
        L.info("✔ %s (%.1f sn)", name, st["seconds"])
