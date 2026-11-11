"""Kayıt (DVR): canlı yayını, filmi ya da geri izlemeyi dosyaya kaydeder; EPG programını zamanlar; hatırlatıcılar.

TiviMate/IPTVnator'daki kayıt gibi: FFmpeg akışı yeniden kodlamadan (`-c copy`) MPEG-TS dosyasına yazar — işlemci
yükü yok, kalite kaybı yok, kayıt kesilse de dosya oynatılabilir. Zamanlanmış kayıtlar ve hatırlatıcılar
`schedule.json`'da tutulur; `Scheduler.due()` arayüzün zamanlayıcısıyla (15 sn'de bir) çağrılır.
Bu modül Qt'ye bağımlı değildir.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

PRE_ROLL, POST_ROLL = 60, 120        # zamanlanmış kayıtta programdan 1 dk önce başla, 2 dk sonra bitir


def default_folder() -> Path:
    home = Path.home()
    videos = home / "Videos" if (home / "Videos").is_dir() else home
    return videos / "Heloo TV Kayıtlar"


def safe_name(text: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "kayit").strip().rstrip(".")
    return re.sub(r"\s+", " ", s)[:90] or "kayit"


def ffmpeg_args(ffmpeg: str, url: str, out: Path, headers: dict | None = None, duration: float | None = None,
                user_agent: str = "") -> list[str]:
    headers = headers or {}
    args = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    ua = headers.get("user_agent") or user_agent
    if ua:
        args += ["-user_agent", ua]
    extra = []
    if headers.get("referrer"):
        extra.append(f"Referer: {headers['referrer']}")
    if headers.get("origin"):
        extra.append(f"Origin: {headers['origin']}")
    for k, v in (headers.get("extra") or {}).items():
        if v and k.lower() not in ("user-agent", "referer", "referrer", "origin"):
            extra.append(f"{k}: {v}")
    if extra:
        args += ["-headers", "".join(h + "\r\n" for h in extra)]
    if url.lower().startswith(("http://", "https://")):
        args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                 "-reconnect_delay_max", "5"]
    args += ["-i", url, "-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy", "-ignore_unknown"]
    if duration:
        args += ["-t", f"{float(duration):.0f}"]
    args += ["-f", "mpegts", str(out)]
    return args


@dataclass
class Recording:
    id: str
    title: str
    path: str
    started: float
    until: float | None = None
    url: str = ""
    proc: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


class Recorder:
    """Aynı anda birden çok kayıt (her biri ayrı FFmpeg süreci)."""

    def __init__(self, ffmpeg: str | None = None, folder: str | Path | None = None, user_agent: str = ""):
        self.ffmpeg = ffmpeg
        self.folder = Path(folder) if folder else default_folder()
        self.user_agent = user_agent
        self.active: dict[str, Recording] = {}
        self._lock = threading.Lock()

    def _find_ffmpeg(self) -> str:
        if self.ffmpeg:
            return self.ffmpeg
        from .upscale import find_ffmpeg
        ff = find_ffmpeg()
        if not ff:
            raise RuntimeError("Kayıt için ffmpeg gerekli (Ayarlar → Sistem → mpv bileşenlerini indir).")
        return ff

    def start(self, url: str, title: str, headers: dict | None = None, duration: float | None = None,
              folder: str | Path | None = None) -> Recording:
        out_dir = Path(folder) if folder else self.folder
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H.%M")
        out = out_dir / f"{safe_name(title)} - {stamp}.ts"
        n = 2
        while out.exists():
            out = out_dir / f"{safe_name(title)} - {stamp} ({n}).ts"
            n += 1
        args = ffmpeg_args(self._find_ffmpeg(), url, out, headers, duration, self.user_agent)
        flags = 0x08000000 if sys.platform.startswith("win") else 0   # CREATE_NO_WINDOW
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, creationflags=flags)
        rec = Recording(id=uuid.uuid4().hex[:10], title=title, path=str(out), started=time.time(),
                        until=(time.time() + duration) if duration else None, url=url, proc=proc)
        with self._lock:
            self.active[rec.id] = rec
        return rec

    def stop(self, rec_id: str) -> Recording | None:
        with self._lock:
            rec = self.active.pop(rec_id, None)
        if rec and rec.running:
            rec.proc.terminate()       # MPEG-TS: sonlandırılan kayıt da oynatılabilir (dosya sonu bilgisi gerekmez)
            try:
                rec.proc.wait(5)
            except subprocess.TimeoutExpired:
                rec.proc.kill()
        return rec

    def stop_all(self) -> None:
        for rid in list(self.active):
            self.stop(rid)

    def reap(self) -> list[tuple[Recording, str]]:
        """Biten kayıtları listeden çıkarır: [(kayıt, hata iletisi ya da "")]."""
        done = []
        with self._lock:
            for rid, rec in list(self.active.items()):
                if not rec.running:
                    err = ""
                    if rec.proc is not None and rec.proc.returncode not in (0, None):
                        try:
                            err = (rec.proc.stderr.read() or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
                            err = err[0] if err else f"ffmpeg çıkış kodu {rec.proc.returncode}"
                        except Exception:
                            err = f"ffmpeg çıkış kodu {rec.proc.returncode}"
                        if rec.size() > 0:
                            err = ""       # bir kısmı kaydedildi (sağlayıcı yayını bitirdi): hata sayma
                    done.append((rec, err))
                    del self.active[rid]
        return done

    def recording_url(self, url: str) -> Recording | None:
        return next((r for r in self.active.values() if r.running and r.url == url), None)


@dataclass
class Job:
    """Zamanlanmış kayıt ya da hatırlatıcı."""
    id: str
    kind: str                 # record | remind
    title: str                # program adı
    channel: str              # kanal adı
    start: float
    stop: float
    key: list                 # kanalın (kaynak, tür, kimlik) anahtarı
    url: str = ""
    headers: dict = field(default_factory=dict)
    state: str = "waiting"    # waiting | running | done | failed | missed

    def label(self) -> str:
        t = time.strftime("%d.%m %H:%M", time.localtime(self.start))
        return f"{t} · {self.channel} — {self.title}"


class Scheduler:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.data_dir() / "schedule.json"
        self.jobs: list[Job] = []
        self.load()

    def load(self) -> None:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            self.jobs = [Job(**{k: v for k, v in r.items() if k in Job.__dataclass_fields__}) for r in rows]
        except (OSError, ValueError, TypeError):
            self.jobs = []
        # uygulama kayıt sürerken kapandıysa iş "sürüyor" kalmasın: programı bitmediyse yeniden beklemeye alınır
        # (due() kalan kısmı kaydeder), bittiyse yarım kaldı sayılır
        now = time.time()
        for j in self.jobs:
            if j.state == "running":
                j.state = "waiting" if now < j.stop else "failed"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(j) for j in self.jobs], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, kind: str, prog: dict, channel: str, key, url: str = "", headers: dict | None = None) -> Job:
        for j in self.jobs:
            if j.kind == kind and j.key == list(key) and int(j.start) == int(prog["start"]) and j.state == "waiting":
                return j
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, title=prog.get("title") or channel, channel=channel,
                  start=float(prog["start"]), stop=float(prog["stop"]), key=list(key), url=url,
                  headers=dict(headers or {}))
        self.jobs.append(job)
        self.save()
        return job

    def remove(self, job_id: str) -> None:
        self.jobs = [j for j in self.jobs if j.id != job_id]
        self.save()

    def find(self, kind: str, key, start: float) -> Job | None:
        return next((j for j in self.jobs if j.kind == kind and j.key == list(key) and int(j.start) == int(start)
                     and j.state == "waiting"), None)

    def upcoming(self) -> list[Job]:
        return sorted((j for j in self.jobs if j.state in ("waiting", "running")), key=lambda j: j.start)

    def due(self, now: float | None = None) -> list[Job]:
        """Şimdi başlaması gerekenler (kayıt: başlangıçtan 1 dk önce; hatırlatıcı: 1 dk önce). Kaçırılanları işaretler."""
        now = now or time.time()
        out = []
        changed = False
        for j in self.jobs:
            if j.state != "waiting":
                continue
            lead = PRE_ROLL
            if now >= j.stop:
                j.state = "missed"
                changed = True
            elif now >= j.start - lead:
                out.append(j)
        # 7 günden eski bitmiş işleri temizle
        before = len(self.jobs)
        self.jobs = [j for j in self.jobs if j.state in ("waiting", "running") or j.stop > now - 7 * 86400]
        if changed or len(self.jobs) != before:
            self.save()
        return out

    def mark(self, job: Job, state: str) -> None:
        job.state = state
        self.save()

    @staticmethod
    def record_duration(job: Job, now: float | None = None) -> float:
        now = now or time.time()
        return max(60.0, job.stop + POST_ROLL - now)


__all__ = ["Recorder", "Recording", "Scheduler", "Job", "ffmpeg_args", "default_folder", "safe_name"]
