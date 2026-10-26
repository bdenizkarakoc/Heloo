#!/usr/bin/env python3
"""Reels Fabrikası — yerel uygulama (kontrol paneli + otomatik mod).

Yalnızca bu bilgisayardan erişilir (127.0.0.1). Bağımlılık gerektirmez (Python standart kütüphanesi).

    python app/server.py --open           # sunucuyu başlat ve tarayıcıda aç
    python app/server.py --port 8765

Otomatik mod açıkken, belirlenen aralıklarla kategori seçip araştırır, senaryo yazar (Claude API veya
kurulu Claude Code), videoyu üretir ve output/ klasörüne kaydeder. Görevler sırayla, tek tek işlenir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import queue
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reels import doctor, log, pipeline  # noqa: E402
from reels.config import load_config  # noqa: E402
from reels.job import Job  # noqa: E402
from reels.util import read_json, write_json  # noqa: E402

APP_STATE = ROOT / "config" / "app.json"
DEFAULT_AUTO = {"enabled": False, "interval_hours": 6, "daily_max": 4, "categories": [], "next_run": None}
L = log.get("app")


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


# ----------------------------------------------------------------------------
# Kuyruk ve işçi
# ----------------------------------------------------------------------------

class Factory:
    def __init__(self):
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.pending: list[dict] = []
        self.current: dict | None = None
        self.lock = threading.Lock()
        self.auto = {**DEFAULT_AUTO, **(read_json(APP_STATE, {}) or {}).get("auto", {})}
        threading.Thread(target=self._worker, daemon=True, name="worker").start()
        threading.Thread(target=self._scheduler, daemon=True, name="scheduler").start()

    # --- görev ekleme
    def enqueue(self, kind: str, **kw) -> dict:
        task = {"id": f"t{int(time.time() * 1000)}", "kind": kind, "added": now().isoformat(timespec="seconds"), **kw}
        with self.lock:
            self.pending.append(task)
        self.q.put(task)
        L.info("Kuyruğa eklendi: %s %s", kind, {k: v for k, v in kw.items() if v})
        return task

    def _worker(self) -> None:
        while True:
            task = self.q.get()
            with self.lock:
                self.pending = [t for t in self.pending if t["id"] != task["id"]]
                self.current = {**task, "started": now().isoformat(timespec="seconds"), "job": task.get("job")}
            try:
                self._run(task)
            except Exception as exc:  # noqa: BLE001 — bir görevin hatası uygulamayı durdurmamalı
                L.error("Görev başarısız: %s", exc)
                L.debug("%s", traceback.format_exc())
            finally:
                with self.lock:
                    self.current = None

    def _run(self, task: dict) -> None:
        cfg = load_config()
        if task["kind"] == "new":
            job = pipeline.new_job(cfg, task.get("category") or None, task.get("topic") or None)
            with self.lock:
                self.current["job"] = job.id
            handler = log.attach_job_log(job.id)
            try:
                pipeline.auto_script(job, cfg)
            except Exception:
                job.set_status("failed")
                raise
            finally:
                log.detach(handler)
        else:  # mevcut görevi (yeniden) üret
            job = Job.load(task["job"])
            with self.lock:
                self.current["job"] = job.id
        out = pipeline.produce(job, cfg, from_stage=task.get("from_stage"))
        L.info("✔ Video hazır: %s", out.get("video"))

    # --- otomatik mod
    def save_auto(self, data: dict) -> dict:
        with self.lock:
            for k in ("enabled", "interval_hours", "daily_max", "categories"):
                if k in data:
                    self.auto[k] = data[k]
            self.auto["interval_hours"] = max(0.5, float(self.auto["interval_hours"]))
            self.auto["daily_max"] = max(1, int(self.auto["daily_max"]))
            if self.auto["enabled"] and not self.auto.get("next_run"):
                self.auto["next_run"] = (now() + dt.timedelta(minutes=1)).isoformat(timespec="seconds")
            if not self.auto["enabled"]:
                self.auto["next_run"] = None
            state = read_json(APP_STATE, {}) or {}
            state["auto"] = self.auto
            write_json(APP_STATE, state)
            return dict(self.auto)

    def _today_count(self) -> int:
        today = dt.date.today().isoformat()
        return sum(1 for h in pipeline.history() if h.get("date") == today)

    def _scheduler(self) -> None:
        rr = 0
        while True:
            time.sleep(20)
            try:
                with self.lock:
                    a = dict(self.auto)
                    busy = self.current is not None or bool(self.pending)
                if not a["enabled"] or busy or not a.get("next_run"):
                    continue
                if now() < dt.datetime.fromisoformat(a["next_run"]):
                    continue
                nxt = now() + dt.timedelta(hours=float(a["interval_hours"]))
                if self._today_count() >= int(a["daily_max"]):
                    L.info("Otomatik mod: günlük sınır (%s) doldu", a["daily_max"])
                else:
                    cats = a.get("categories") or []
                    cat = cats[rr % len(cats)] if cats else None
                    rr += 1
                    self.enqueue("new", category=cat, topic=None, source="otomatik")
                with self.lock:
                    self.auto["next_run"] = nxt.isoformat(timespec="seconds")
                    state = read_json(APP_STATE, {}) or {}
                    state["auto"] = self.auto
                    write_json(APP_STATE, state)
            except Exception as exc:  # noqa: BLE001
                L.error("Zamanlayıcı hatası: %s", exc)

    def snapshot(self) -> dict:
        with self.lock:
            return {"current": self.current, "pending": list(self.pending), "auto": dict(self.auto)}


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

FACTORY: Factory | None = None
_caps_cache: dict = {}


def job_summary(job: Job) -> dict:
    st = job.state
    script = read_json(job.script_path, {}) or {}
    return {"id": job.id, "status": st.get("status"), "category": st.get("category"),
            "title": script.get("title") or st.get("topic_hint") or "",
            "created": st.get("created"), "updated": st.get("updated"),
            "stages": {k: v.get("status") for k, v in st.get("stages", {}).items()},
            "errors": {k: v.get("error") for k, v in st.get("stages", {}).items() if v.get("error")},
            "warnings": [w["msg"] for w in st.get("warnings", [])][-6:],
            "outputs": st.get("outputs", {})}


class Handler(BaseHTTPRequestHandler):
    server_version = "ReelsFactory/0.1"

    def log_message(self, fmt, *args):  # sessiz
        pass

    # --- yardımcılar
    def _json(self, data, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json",):
            ctype += "; charset=utf-8"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if a and b else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 16, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _safe(self, base: Path, rel: str) -> Path | None:
        p = (base / unquote(rel)).resolve()
        return p if str(p).startswith(str(base.resolve())) else None

    # --- GET
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self._file(ROOT / "app" / "index.html")
        if path.startswith("/output/"):
            p = self._safe(ROOT / "output", path[len("/output/"):])
            return self._file(p) if p else self.send_error(403)
        if path.startswith("/projects/"):
            p = self._safe(ROOT / "projects", path[len("/projects/"):])
            if p and p.suffix.lower() in (".jpg", ".png", ".json"):
                return self._file(p)
            return self.send_error(403)
        if path == "/api/status":
            cfg = load_config()
            from reels.llm import resolve_provider
            if not _caps_cache or time.time() - _caps_cache.get("t", 0) > 300:
                rows = doctor.check(cfg, network=False)
                _caps_cache.update(t=time.time(), ready=all(r["ok"] for r in rows if r["need"] == "zorunlu"),
                                   missing=[r["name"] for r in rows if not r["ok"] and r["need"] == "zorunlu"])
            return self._json({
                "ready": _caps_cache["ready"], "missing": _caps_cache["missing"],
                "provider": resolve_provider(cfg), "capabilities": doctor.capabilities(cfg),
                "categories": {k: v.get("label", k) for k, v in cfg.get_path("categories", {}).items()},
                "license": {"visuals": cfg.get_path("visuals.license_mode", "strict"),
                            "music": cfg.get_path("music.license_mode", "strict")},
                **FACTORY.snapshot()})
        if path == "/api/jobs":
            jobs = sorted(Job.all(), key=lambda j: j.state.get("created", ""), reverse=True)[:40]
            return self._json([job_summary(j) for j in jobs])
        if path.startswith("/api/log/"):
            job_id = path.rsplit("/", 1)[-1]
            p = self._safe(ROOT / "logs", f"{job_id}.log")
            text = p.read_text(encoding="utf-8", errors="replace") if p and p.exists() else ""
            return self._json({"log": text[-20000:]})
        if path == "/api/doctor":
            return self._json(doctor.check(load_config(), network=True))
        return self.send_error(404)

    # --- POST
    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        data = self._body()
        if path == "/api/new":
            n = max(1, min(10, int(data.get("count") or 1)))
            tasks = [FACTORY.enqueue("new", category=data.get("category") or None,
                                     topic=(data.get("topic") or "").strip() or None, source="elle")
                     for _ in range(n)]
            return self._json({"queued": tasks})
        if path == "/api/produce":
            t = FACTORY.enqueue("produce", job=data["job"], from_stage=data.get("from_stage") or None)
            return self._json({"queued": [t]})
        if path == "/api/auto":
            return self._json(FACTORY.save_auto(data))
        return self.send_error(404)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    global FACTORY
    ap = argparse.ArgumentParser(description="Reels Fabrikası uygulaması")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="tarayıcıda aç")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if port_in_use(args.port):  # zaten çalışıyor: yalnızca paneli aç
        print(f"Uygulama zaten çalışıyor: {url}")
        if args.open:
            webbrowser.open(url)
        return 0
    log.setup_logging(False)
    import logging
    fh = logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s"))
    fh.addFilter(log.SecretFilter())
    logging.getLogger("reels").addHandler(fh)
    FACTORY = Factory()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Reels Fabrikası çalışıyor: {url}  (durdurmak için Ctrl+C)")
    L.info("Uygulama başladı: %s", url)
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
