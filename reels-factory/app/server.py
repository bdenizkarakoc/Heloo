#!/usr/bin/env python3
"""Reels Fabrikası — yerel uygulama (kontrol paneli + otomatik mod).

Yalnızca bu bilgisayardan erişilir (127.0.0.1). Bağımlılık gerektirmez (Python standart kütüphanesi).

    python app/server.py --open           # sunucuyu başlat ve tarayıcıda aç
    python app/server.py --port 8765

Otomatik mod açıkken, belirlenen aralıklarla kategori seçip araştırır, senaryo yazar (Claude API veya
kurulu Claude Code), videoyu üretir ve output/ klasörüne kaydeder. Görevler sırayla, tek tek işlenir.
Bulutta üretilen videolar (GitHub 'reels-videos' dalı) açılışta ve 30 dakikada bir output/cloud/ altına indirilir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import queue
import socket
import subprocess
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

from reels import audience, claude_setup, kesim, knowledge, notes, cloud_sync, doctor, log, pipeline, publish, publish_sources, studio, voice  # noqa: E402
from reels.config import load_config  # noqa: E402
from reels.job import Job  # noqa: E402
from reels.util import read_json, write_json  # noqa: E402

APP_STATE = ROOT / "config" / "app.json"
CLOUD_SYNC_MIN = 30
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
        self.cloud: dict = {"running": False, "last": None}
        self.cloud_wake = threading.Event()
        threading.Thread(target=self._cloud_loop, daemon=True, name="cloud").start()
        self.pub_wake = threading.Event()
        threading.Thread(target=self._publisher, daemon=True, name="publisher").start()
        threading.Thread(target=self._telegram, daemon=True, name="telegram").start()
        threading.Thread(target=self._kesim_loop, daemon=True, name="kesim").start()

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

    def _kesim_loop(self) -> None:
        """Masaüstü\\kesim\\Montaja at klasörü ve Kesim.exe çıktıları (15 sn'de bir)."""
        while True:
            time.sleep(15)
            kesim.tick(self.enqueue)

    def _run(self, task: dict) -> None:
        if task["kind"] == "kesim_learn":
            with self.lock:
                self.current["job"] = "kesim-stil"
            kesim.learn(task["video"])
            return
        if task["kind"] == "audiofx":
            from reels import audiofx
            src = studio.UPLOADS / task["file"]
            kind = studio.media_info(src)["kind"]
            outdir = ROOT / "output" / "enhanced"
            outdir.mkdir(parents=True, exist_ok=True)
            stem = Path(task["file"]).stem
            dest = outdir / f"{stem}-iyilestirilmis{'.mp4' if kind == 'video' else '.wav'}"
            rep = audiofx.enhance_media(src, dest, task.get("strength", "orta"))
            # karşılaştırma için özgün sesin dinlenebilir kopyası
            orig = outdir / f"{stem}-ozgun.m4a"
            from reels.util import run as _run
            _run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-c:a", "aac", "-b:a", "160k", orig])
            lst = read_json(outdir / "list.json", []) or []
            lst.insert(0, {"name": task["file"], "kind": kind, "strength": task.get("strength", "orta"),
                           "output": dest.relative_to(ROOT).as_posix(), "original": orig.relative_to(ROOT).as_posix(),
                           "steps": rep["steps"], "analysis": rep["analysis"], "at": now().isoformat(timespec="seconds")})
            write_json(outdir / "list.json", lst[:50])
            L.info("✔ Ses iyileştirildi: %s (%s)", dest.name, "; ".join(rep["steps"]))
            return
        if task["kind"] == "knowledge":
            res = knowledge.build_graph()
            L.info("✔ Bilgi haritası: %s kavram, %s bağ", res.get("nodes"), res.get("edges"))
            return
        if task["kind"] == "note":
            src = studio.download_url(task["url"]) if task.get("url") else studio.UPLOADS / task["file"]
            notes.make_note(src, task.get("url") or src.name)
            return
        if task["kind"] == "pub_prepare":
            info = publish_sources.info_for(task["video"])
            it = publish.enqueue(info["video"], task.get("title") or info["title"],
                                 task.get("caption") if task.get("caption") is not None else info["caption"],
                                 info["text"], task.get("channel"), task.get("targets"), info["source"], info["sheet"],
                                 info.get("chapters", ""))
            with self.lock:
                self.current["job"] = it["id"]
            mode = publish.settings().get("audience_auto", "claude")
            if mode != "off" and not it.get("audience"):
                self._audience(it["id"], mode)
            if not it.get("notified"):
                it = publish.load(it["id"])
                publish.tg_notify(it)
                it["notified"] = True
                publish.save(it)
            return
        if task["kind"] == "audience":
            with self.lock:
                self.current["job"] = task["item"]
            self._audience(task["item"], task.get("method", "claude"))
            return
        if task["kind"] == "voice_learn":  # kayıttan / videodan / bağlantıdan konuşma tarzı
            with self.lock:
                self.current["job"] = "ses-tarzi"
            handler = log.attach_job_log("ses-tarzi")
            try:
                src = studio.download_url(task["url"]) if task.get("url") else studio.UPLOADS / task["file"]
                voice.learn_from_media(src, task.get("name") or "", bool(task.get("consent")), task.get("into") or None)
            finally:
                log.detach(handler)
            return
        if task["kind"] in ("voice_build", "voice_setup"):
            with self.lock:
                self.current["job"] = f"ses-{task.get('slug', 'motor')}"
            handler = log.attach_job_log(self.current["job"])
            try:
                if task["kind"] == "voice_setup" or not voice.engine_available():
                    voice.install_engine()
                if task["kind"] == "voice_build":
                    voice.build(task["slug"])
                    L.info("✔ Ses profili hazır: %s", task["slug"])
            finally:
                log.detach(handler)
            return
        if task["kind"] in ("studio_analyze", "studio_edit"):
            with self.lock:
                self.current["job"] = task["project"]
            proj = (studio.run_analyze if task["kind"] == "studio_analyze" else studio.run_edit)(task["project"])
            L.info("✔ Stüdyo işi bitti: %s", task["project"])
            if task["kind"] == "studio_edit" and (proj or {}).get("options", {}).get("kesim"):
                proj["delivered"] = kesim.deliver(proj)
                studio.save_project(proj)
            for c in (proj or {}).get("clips", []) if task["kind"] == "studio_edit" else []:
                if c.get("output"):
                    self.auto_queue(c["output"], "studio")
            return
        cfg = load_config()
        if task["kind"] == "new":
            media = [studio.UPLOADS / Path(f).name for f in (task.get("media") or [])
                     if (studio.UPLOADS / Path(f).name).is_file()]
            job = pipeline.new_job(cfg, task.get("category") or None, task.get("topic") or None,
                                   text=task.get("text") or None, draw=bool(task.get("draw")), media=media or None)
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
        if task.get("kesim") and out.get("video"):  # Kesim penceresinden istendi: Hazır klasörüne de koy
            kesim.to_ready(ROOT / out["video"])
        if out.get("video"):
            self.auto_queue(out["video"], "local")
            self.maybe_refresh_knowledge()

    def maybe_refresh_knowledge(self) -> None:
        """Bilgi haritası 24 saatten eskiyse (ve Graphify + Claude varsa) arka planda günceller."""
        try:
            s = knowledge.summary(1)
            fresh = s.get("ready") and time.time() - s.get("updated", 0) < 24 * 3600
            if not fresh and knowledge.available() and knowledge.backend():
                self.enqueue("knowledge", topic="bilgi haritası")
        except Exception as exc:  # noqa: BLE001
            L.debug("harita güncelleme denetimi: %s", exc)

    # --- yayın
    def auto_queue(self, video_rel: str, origin: str) -> None:
        """Varsayılan kanal bu kaynaktan gelen videoları otomatik onay kuyruğuna almak üzere ayarlıysa ekler."""
        c = publish.default_channel()
        if c and (c.get("auto_queue") or {}).get(origin) and not publish.find_by_video(video_rel):
            self.enqueue("pub_prepare", video=video_rel, topic=f"yayın: {Path(video_rel).name}")

    def _audience(self, pid: str, method: str) -> None:
        it = publish.load(pid)
        vinfo = {"id": pid, "title": it["title"], "text": it.get("text", ""), "caption": it.get("caption", ""),
                 "platforms": it["targets"]}
        try:
            if method == "mirofish":
                res = audience.mirofish_test(vinfo, publish.QUEUE / pid)
            else:
                res = audience.panel_test(vinfo, ROOT / it["sheet"], publish.QUEUE / pid)
        except Exception as exc:  # noqa: BLE001 — test yapılamasa da yayın akışı sürer
            res = {"method": method, "error": str(exc)[:300]}
            L.warning("Kitle testi yapılamadı: %s", exc)
        it = publish.load(pid)
        it.setdefault("audience_runs", {})[method] = res
        if method == "claude" or not it.get("audience"):
            it["audience"] = res
        publish.save(it)

    def _publisher(self) -> None:
        while True:
            self.pub_wake.wait(30)
            self.pub_wake.clear()
            try:
                for it in publish.due():
                    publish.publish_item(it["id"])
            except Exception as exc:  # noqa: BLE001
                L.error("Yayın zamanlayıcısı hatası: %s", exc)

    def _telegram(self) -> None:
        offset = 0
        while True:
            time.sleep(4)
            if not publish.secret("TELEGRAM_BOT_TOKEN"):
                continue
            try:
                offset = publish.tg_poll(offset)
                self.pub_wake.set()
            except Exception as exc:  # noqa: BLE001
                L.debug("Telegram: %s", exc)
                time.sleep(20)

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

    # --- bulut videoları
    def _cloud_loop(self) -> None:
        while True:
            with self.lock:
                self.cloud["running"] = True
            res = cloud_sync.sync()
            with self.lock:
                self.cloud.update(running=False, last=res)
            if res.get("new"):
                for v in cloud_sync.videos():
                    if v["name"] in res["new"]:
                        self.auto_queue(v["video"], "cloud")
            self.cloud_wake.wait(CLOUD_SYNC_MIN * 60)
            self.cloud_wake.clear()

    def snapshot(self) -> dict:
        with self.lock:
            return {"current": self.current, "pending": list(self.pending), "auto": dict(self.auto),
                    "cloud": dict(self.cloud)}


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

FACTORY: Factory | None = None
_caps_cache: dict = {}
KESIM_API = 2  # Kesim'in beklediği uç sürümü; Kesim daha eski bir fabrika görürse (boşta ise) yeniden başlatır
KESIM_RESULTS: dict = {}  # Kesim'in yan işleri (altyazı, AI planı, ses) -> durum/sonuç


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
        if path.startswith("/studio/"):
            p = self._safe(ROOT / "studio", path[len("/studio/"):])
            ok = (".jpg", ".png", ".json") + ((".wav", ".mp3", ".m4a") if p and "voices" in p.parts else ())
            if p and p.suffix.lower() in ok and "uploads" not in p.parts:
                return self._file(p)
            return self.send_error(403)
        if path in ("/publish", "/publish.html"):
            return self._file(ROOT / "app" / "publish.html")
        if path.startswith("/publish/queue/"):
            p = self._safe(ROOT / "publish" / "queue", path[len("/publish/queue/"):])
            return self._file(p) if p and p.suffix.lower() in (".mp4", ".jpg", ".json") else self.send_error(403)
        if path.startswith("/channels/"):
            p = self._safe(ROOT / "channels", path[len("/channels/"):])
            return self._file(p) if p and p.suffix.lower() == ".png" else self.send_error(403)
        if path in ("/knowledge", "/knowledge/graph.html"):
            g = knowledge.OUT / "graph.html"
            if g.exists():
                return self._file(g)
            body = ("<!doctype html><meta charset=utf-8><body style='font:16px system-ui;background:#0b0f1a;color:#eef2fb;"
                    "padding:40px'>Bilgi haritası henüz kurulmadı. Kontrol panelinde <b>🧠 Harita</b> → "
                    "<b>Haritayı kur</b>.</body>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        if path == "/api/knowledge":
            return self._json(knowledge.info())
        if path == "/api/audio/list":
            return self._json(read_json(ROOT / "output" / "enhanced" / "list.json", []) or [])
        if path == "/api/notes":
            return self._json({"vault": str(notes.vault()), "notes": notes.list_notes()})
        if path == "/api/publish/items":
            items = publish.items()
            for it in items:
                it["minutes_left"] = publish.ceil_minutes(it) if it["status"] == "pending" else None
            return self._json(items)
        if path == "/api/publish/channels":
            return self._json(publish.channels())
        if path == "/api/publish/status":
            return self._json(publish.status_summary())
        if path == "/api/publish/youtube/start":
            from urllib.parse import parse_qs
            slug = (parse_qs(url.query).get("slug") or [""])[0]
            try:
                target = publish.youtube_auth_url(slug, self._yt_redirect())
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return None
        if path == "/oauth/youtube":
            from urllib.parse import parse_qs
            q = parse_qs(url.query)
            try:
                res = publish.youtube_callback(q.get("state", [""])[0], q.get("code", [""])[0], self._yt_redirect())
                msg = f"YouTube kanalı bağlandı: {res['channel']}"
            except Exception as exc:  # noqa: BLE001
                msg = f"YouTube bağlanamadı: {exc}"
            from urllib.parse import quote
            self.send_response(302)
            self.send_header("Location", "/publish?msg=" + quote(msg))
            self.end_headers()
            return None
        if path in ("/voice", "/voice.html"):
            return self._file(ROOT / "app" / "voice.html")
        if path == "/api/voice/styles":
            return self._json({"styles": voice.styles()})
        if path == "/api/voice/turns":
            from urllib.parse import parse_qs
            try:
                return self._json({"turns": voice.turns((parse_qs(url.query).get("slug") or [""])[0])})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
        if path == "/api/voice/profiles":
            return self._json({"profiles": voice.profiles(), "active": voice.active(), **voice.engine_status()})
        if path == "/api/voice/say":
            from urllib.parse import parse_qs
            text = (parse_qs(url.query).get("text") or [""])[0][:400]
            try:
                return self._file(voice.say(text))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 502)
        if path in ("/kesim", "/kesim.html"):
            return self._file(ROOT / "app" / "kesim.html")
        if path.startswith("/api/kesim/result/"):
            return self._json(KESIM_RESULTS.get(path.rsplit("/", 1)[-1], {"status": "unknown"}))
        if path.startswith("/api/kesim/style"):
            try:
                return self._json(kesim.style_data(path[len("/api/kesim/style"):].strip("/")))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
        if path == "/api/kesim":
            st = kesim.status()
            st["styles"] = [{"slug": x["slug"], "name": x["name"], "version": x["version"]} for x in studio.list_styles()]
            st["projects"] = [p for p in studio.list_projects(15) if p.get("options", {}).get("kesim")][:8]
            st["api"] = KESIM_API
            return self._json(st)
        if path in ("/studio", "/studio.html"):
            return self._file(ROOT / "app" / "studio.html")
        if path == "/api/studio/styles":
            return self._json(studio.list_styles())
        if path == "/api/studio/projects":
            return self._json(studio.list_projects())
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
        if path == "/api/claude":
            _caps_cache.clear()  # kurulum/giriş sonrası senaryo sağlayıcısı yeniden belirlensin
            return self._json(claude_setup.status())
        if path == "/api/cloud":
            return self._json(cloud_sync.videos())
        if path.startswith("/api/log/"):
            job_id = path.rsplit("/", 1)[-1]
            p = self._safe(ROOT / "logs", f"{job_id}.log")
            text = p.read_text(encoding="utf-8", errors="replace") if p and p.exists() else ""
            return self._json({"log": text[-20000:]})
        if path == "/api/mcp":
            from reels import mcp_setup
            return self._json([{"name": n, "ready": bool(c), "note": note} for n, c, note in mcp_setup.servers()])
        if path == "/api/doctor":
            return self._json(doctor.check(load_config(), network=True))
        return self.send_error(404)

    # --- PUT: büyük video yükleme (diske akıtılarak; bellek kullanmaz)
    def do_PUT(self):  # noqa: N802
        url = urlparse(self.path)
        from urllib.parse import parse_qs
        if url.path == "/api/voice/answer":
            q = parse_qs(url.query)
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n < 60 * 1024 * 1024:
                return self._json({"error": "kayıt boş veya çok büyük"}, 400)
            try:
                return self._json(voice.add_answer(q.get("slug", [""])[0], self.rfile.read(n),
                                                   q.get("ext", ["webm"])[0]))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
        if url.path == "/api/publish/logo":
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n < 10 * 1024 * 1024:
                return self._json({"error": "logo boş veya çok büyük (en fazla 10 MB)"}, 400)
            try:
                return self._json({"logo": publish.save_logo(parse_qs(url.query).get("slug", [""])[0],
                                                             self.rfile.read(n))})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
        if url.path != "/api/studio/upload":
            return self.send_error(404)
        name = studio.safe_upload_name((parse_qs(url.query).get("name") or ["video.mp4"])[0])
        left = int(self.headers.get("Content-Length") or 0)
        if left <= 0:
            return self._json({"error": "boş dosya"}, 400)
        studio.UPLOADS.mkdir(parents=True, exist_ok=True)
        dest = studio.UPLOADS / name
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as fh:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                fh.write(chunk)
                left -= len(chunk)
        if left:
            tmp.unlink(missing_ok=True)
            return self._json({"error": "yükleme yarıda kesildi"}, 400)
        tmp.replace(dest)
        try:
            info = studio.media_info(dest)  # video, fotoğraf (HEIC dahil) veya ses
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            return self._json({"error": f"dosya okunamadı: {exc}"}, 400)
        L.info("Yüklendi: %s (%s, %.0f sn)", name, info["kind"], info["duration"])
        return self._json({"file": name, **info})

    # --- POST
    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        data = self._body()
        if path.startswith("/api/studio/"):
            return self._studio_post(path[len("/api/studio/"):], data)
        if path.startswith("/api/kesim/"):
            return self._kesim_post(path[len("/api/kesim/"):], data)
        if path.startswith("/api/voice/"):
            return self._voice_post(path[len("/api/voice/"):], data)
        if path.startswith("/api/publish/"):
            return self._publish_post(path[len("/api/publish/"):], data)
        if path == "/api/knowledge/build":
            if not knowledge.available():
                return self._json({"error": "Graphify kurulu değil (kurulum komutunu tekrar çalıştırın)"}, 400)
            return self._json({"queued": [FACTORY.enqueue("knowledge", topic="bilgi haritası")]})
        if path == "/api/knowledge/query":
            try:
                return self._json({"answer": knowledge.query(str(data.get("q", ""))[:300])})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
        if path == "/api/shutdown":  # paneldeki "Kapat": arka plandaki bütün işler durur
            L.info("Uygulama kullanıcı isteğiyle kapatılıyor")
            self._json({"ok": True})
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return None
        if path == "/api/audio/enhance":  # ses kaydı veya videonun sesini iyileştir
            name = Path(str(data.get("file", ""))).name
            if not (studio.UPLOADS / name).is_file():
                return self._json({"error": "önce dosya yükleyin"}, 400)
            strength = data.get("strength") if data.get("strength") in ("hafif", "orta", "güçlü") else "orta"
            return self._json({"queued": [FACTORY.enqueue("audiofx", file=name, strength=strength,
                                                          topic=f"ses iyileştirme: {name}")]})
        if path.startswith("/api/notes/"):
            try:
                act = path[len("/api/notes/"):]
                if act == "create":
                    if data.get("url"):
                        t = FACTORY.enqueue("note", url=str(data["url"]).strip(), topic="not: bağlantı")
                    else:
                        name = Path(str(data.get("file", ""))).name
                        if not (studio.UPLOADS / name).is_file():
                            return self._json({"error": "önce video yükleyin"}, 400)
                        t = FACTORY.enqueue("note", file=name, topic=f"not: {name}")
                    return self._json({"queued": [t]})
                if act == "vault":
                    return self._json({"vault": notes.set_vault(str(data.get("path", "")))})
                if act == "to_video":
                    meta = next((m for m in notes.list_notes(500) if m["path"] == data.get("path")), None)
                    if not meta:
                        return self._json({"error": "not bulunamadı"}, 400)
                    t = FACTORY.enqueue("new", category=None, topic=None, text=notes.idea_text(meta, data.get("idea")),
                                        draw=bool(data.get("draw")), source="not")
                    return self._json({"queued": [t]})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
            return self.send_error(404)
        if path == "/api/new":
            n = max(1, min(10, int(data.get("count") or 1)))
            text = (data.get("text") or "").strip() or None
            tasks = [FACTORY.enqueue("new", category=data.get("category") or None,
                                     topic=(data.get("topic") or "").strip() or None, text=text,
                                     draw=bool(data.get("draw")), source="elle", kesim=bool(data.get("kesim")),
                                     media=[Path(str(f)).name for f in (data.get("media") or [])])
                     for _ in range(1 if (text or data.get("media")) else n)]
            return self._json({"queued": tasks})
        if path == "/api/produce":
            t = FACTORY.enqueue("produce", job=data["job"], from_stage=data.get("from_stage") or None)
            return self._json({"queued": [t]})
        if path == "/api/auto":
            return self._json(FACTORY.save_auto(data))
        if path == "/api/claude/install":
            return self._json(claude_setup.open_console("install"))
        if path == "/api/claude/open":
            return self._json(claude_setup.open_console("open"))
        if path == "/api/claude/test":
            return self._json(claude_setup.test())
        if path == "/api/mcp/setup":  # MCP sunucularını Claude Code'a kaydet
            from reels import mcp_setup
            return self._json(mcp_setup.register())
        if path == "/api/cloud/sync":
            FACTORY.cloud_wake.set()
            return self._json({"ok": True})
        return self.send_error(404)

    def _kesim_side(self, kind: str, fn) -> dict:
        """Kısa Kesim işlerini (altyazı, AI planı, ses) montaj kuyruğunu beklemeden ayrı iş parçacığında çalıştırır."""
        tid = f"k{int(time.time() * 1000)}"
        KESIM_RESULTS[tid] = {"status": "running", "kind": kind}

        def work():
            try:
                KESIM_RESULTS[tid] = {"status": "done", "kind": kind, "result": fn()}
            except Exception as exc:  # noqa: BLE001
                L.warning("Kesim %s başarısız: %s", kind, exc)
                KESIM_RESULTS[tid] = {"status": "failed", "kind": kind, "error": str(exc)[:600]}
        threading.Thread(target=work, daemon=True, name=f"kesim-{kind}").start()
        while len(KESIM_RESULTS) > 200:
            KESIM_RESULTS.pop(next(iter(KESIM_RESULTS)))
        return {"task": tid}

    def _kesim_post(self, action: str, data: dict):
        try:
            if action in ("transcribe", "enhance", "learn"):
                src = studio.UPLOADS / Path(str(data.get("file", ""))).name
                if not src.is_file():
                    return self._json({"error": "önce dosyayı yükleyin"}, 400)
                if action == "transcribe":
                    return self._json(self._kesim_side("transcribe", lambda: kesim.transcribe_segments(
                        src, int(data.get("words") or 3))))
                if action == "learn":  # Kesim'den dışa aktarılan videodan "Kesim" stilini öğren
                    return self._json({"queued": [FACTORY.enqueue("kesim_learn", video=src.relative_to(ROOT).as_posix(),
                                                                  topic=f"Kesim stilini öğren: {src.name}")]})

                def enh():
                    from reels import audiofx
                    out = ROOT / "output" / "kesim" / "islem"
                    out.mkdir(parents=True, exist_ok=True)
                    kind = studio.media_info(src)["kind"]
                    dest = out / f"{src.stem}-temizses{'.mp4' if kind == 'video' else '.wav'}"
                    rep = audiofx.enhance_media(src, dest, data.get("strength") or "orta")
                    return {"output": dest.relative_to(ROOT).as_posix(), "steps": rep["steps"]}
                return self._json(self._kesim_side("enhance", enh))
            if action == "assist":
                import base64
                frames = [base64.b64decode(str(f).split(",")[-1]) for f in (data.get("frames") or [])[:4]]
                return self._json(self._kesim_side("assist", lambda: kesim.assist(
                    str(data.get("request", "")), data.get("state") or {}, data.get("tools") or [],
                    str(data.get("rules", "")), frames)))
            if action == "edit":  # yüklenen dosyalarla tek tık montaj
                files = [studio.UPLOADS / Path(str(f)).name for f in (data.get("files") or [])]
                files = [f for f in files if f.is_file()]
                if not files:
                    return self._json({"error": "önce video veya fotoğraf bırakın"}, 400)
                return self._json(kesim.start(files, FACTORY.enqueue))
            if action == "settings":
                return self._json(kesim.save_settings(data))
            if action == "probe":
                return self._json(kesim.probe(try_help=bool(data.get("help"))))
            if action == "open":  # bir videoyu Kesim.exe'de aç
                p = (ROOT / str(data.get("video", ""))).resolve()
                if ROOT.resolve() not in p.parents:
                    return self._json({"error": "izinsiz yol"}, 400)
                return self._json(kesim.open_in_kesim(p))
            if action == "folder":  # Montaja at / Hazır klasörünü Gezgin'de aç
                d = kesim.kesim_dir() / (kesim.READY_NAME if data.get("which") == "ready" else kesim.INBOX_NAME)
                d.mkdir(parents=True, exist_ok=True)
                if os.name == "nt":
                    os.startfile(d)  # noqa: S606
                return self._json({"ok": True, "path": str(d)})
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        return self.send_error(404)

    def _studio_post(self, action: str, data: dict):
        try:
            if action == "analyze" and data.get("url"):
                link = str(data["url"]).strip()
                if not link.startswith(("http://", "https://")):
                    return self._json({"error": "geçerli bir bağlantı girin"}, 400)
                proj = studio.new_project("analyze", None, {}, url=link)
                FACTORY.enqueue("studio_analyze", project=proj["id"], topic=link)
                return self._json(proj)
            if action in ("analyze", "edit"):
                files = [Path(str(f)).name for f in (data.get("files") or [data.get("file", "")]) if f]
                files = [f for f in files if (studio.UPLOADS / f).is_file()]
                if not files:
                    return self._json({"error": "önce video veya fotoğraf yükleyin"}, 400)
                src = studio.UPLOADS / files[0]
                if action == "analyze" and studio.media_info(src)["kind"] != "video":
                    return self._json({"error": "stil öğrenmek için bir video gerekli"}, 400)
                opts = {k: data[k] for k in ("style", "mode", "count", "min_sec", "max_sec", "aspect", "frame",
                                             "music", "captions", "improve_rounds", "notes", "title", "enhance") if k in data}
                if action == "edit":
                    opts["files"] = files
                proj = studio.new_project(action, src, opts)
                FACTORY.enqueue(f"studio_{action}", project=proj["id"], topic=src.name)
                return self._json(proj)
            if action == "style/save":
                return self._json(studio.save_from_analysis(data["project"], data.get("name", "")))
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        return self.send_error(404)


    def _voice_post(self, action: str, data: dict):
        try:
            if action == "start":
                return self._json(voice.start(str(data.get("name", "")), bool(data.get("consent"))))
            if action == "build":
                slug = str(data["slug"])
                voice.vdir(slug)
                return self._json({"queued": [FACTORY.enqueue("voice_build", slug=slug, topic=f"ses: {slug}")]})
            if action == "setup":
                return self._json({"queued": [FACTORY.enqueue("voice_setup", topic="ses motoru")]})
            if action == "activate":
                voice.set_active(data.get("slug") or None)
                _caps_cache.clear()
                return self._json({"active": voice.active()})
            if action == "delete_turn":
                return self._json(voice.delete_turn(str(data["slug"]), int(data["n"])))
            if action == "reset":  # bütün kayıtları sil, sohbeti baştan başlat
                return self._json(voice.reset(str(data["slug"])))
            if action == "delete":
                voice.delete_profile(str(data["slug"]))
                _caps_cache.clear()
                return self._json({"deleted": data["slug"]})
            if action == "learn":  # ses kaydı / video / bağlantıdan tarz öğren
                consent, into = bool(data.get("consent")), (data.get("into") or None)
                if into and not consent:
                    return self._json({"error": "Kaydı kendi ses profiline eklemek için bu sesin sana ait olduğunu onayla"}, 400)
                task = {"name": str(data.get("name", "")).strip()[:60], "consent": consent, "into": into}
                if data.get("url"):
                    link = str(data["url"]).strip()
                    if not link.startswith(("http://", "https://")):
                        return self._json({"error": "geçerli bir bağlantı girin"}, 400)
                    task["url"] = link
                else:
                    name = Path(str(data.get("file", ""))).name
                    if not (studio.UPLOADS / name).is_file():
                        return self._json({"error": "önce dosyayı yükleyin"}, 400)
                    task["file"] = name
                return self._json({"queued": [FACTORY.enqueue("voice_learn", topic="ses tarzı öğrenme", **task)]})
            if action == "style":  # tarzı etkinleştir (slug boş: kapat)
                voice.set_active_style(data.get("slug") or None)
                return self._json({"styles": voice.styles()})
            if action == "style_delete":
                voice.delete_style(str(data["slug"]))
                return self._json({"styles": voice.styles()})
            if action == "speak":
                slug, text = str(data["slug"]), str(data.get("text", "")).strip()[:600]
                if not text:
                    return self._json({"error": "metin boş"}, 400)
                d = voice.vdir(slug) / "tries"
                d.mkdir(exist_ok=True)
                import hashlib
                out = voice.speak(slug, text, d / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".wav"))
                return self._json({"audio": out.relative_to(ROOT).as_posix()})
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        return self.send_error(404)


    def _yt_redirect(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/oauth/youtube"

    # Uygulamadan girilebilecek gizli değerler (başka ad yazılamaz; değerler asla geri gönderilmez)
    SECRET_NAMES = {"YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
                    "TELEGRAM_BOT_TOKEN", "PEXELS_API_KEY", "PIXABAY_API_KEY", "HF_TOKEN", "REPLICATE_API_TOKEN",
                    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BRAVE_API_KEY", "CONTEXT7_API_KEY", "GITHUB_PAT", "POSTGRES_DSN"}

    def _publish_post(self, action: str, data: dict):
        from reels.config import set_secret
        try:
            if action == "queue":
                video = str(data.get("video", ""))
                publish_sources.info_for(video)  # var mı / izinli klasörde mi
                t = FACTORY.enqueue("pub_prepare", video=video, channel=data.get("channel") or None,
                                    targets=data.get("targets") or None, topic=f"yayın: {Path(video).name}")
                return self._json({"queued": [t]})
            if action == "act":
                it = publish.act(data["id"], data["action"], by="panel",
                                 **{k: data.get(k) for k in ("caption", "title", "targets", "channel", "hours")
                                    if k in data})
                FACTORY.pub_wake.set()
                return self._json(it)
            if action == "audience":
                return self._json({"queued": [FACTORY.enqueue("audience", item=data["id"],
                                                              method=data.get("method", "claude"),
                                                              topic="kitle testi")]})
            if action == "channel":
                return self._json(publish.save_channel(data))
            if action == "settings":
                return self._json(publish.save_settings(data))
            if action == "secret":
                name = str(data.get("name", ""))
                slug_tok = name.startswith("RF_") and name.endswith(("_TIKTOK_TOKEN", "_TIKTOK_REFRESH_TOKEN"))
                if name not in self.SECRET_NAMES and not slug_tok:
                    return self._json({"error": "bu ad kaydedilemez"}, 400)
                if name == "ANTHROPIC_API_KEY" and data.get("value") and not str(data["value"]).strip().startswith("sk-ant-"):
                    return self._json({"error": "Claude API anahtarı sk-ant- ile başlamalı"}, 400)
                set_secret(name, str(data.get("value", "")))
                _caps_cache.clear()
                return self._json({"saved": name})
            if action == "tiktok":
                slug = str(data["slug"])
                set_secret(publish.env_key(slug, "TIKTOK_TOKEN"), str(data.get("access_token", "")))
                if data.get("refresh_token"):
                    set_secret(publish.env_key(slug, "TIKTOK_REFRESH_TOKEN"), str(data["refresh_token"]))
                return self._json({"saved": True})
            if action == "meta/pages":
                pages = publish.meta_pages(str(data["token"]).strip())
                return self._json([{k: v for k, v in p.items() if k != "page_token"} for p in pages])
            if action == "meta/connect":
                return self._json(publish.connect_meta(str(data["slug"]), str(data["token"]).strip(),
                                                       str(data["page_id"])))
            if action == "telegram/test":
                publish._tg("sendMessage", data={"chat_id": publish.tg_chat(), "text": "Reels Fabrikası test ✅"})
                return self._json({"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        return self.send_error(404)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_window(url: str, app: bool = False) -> None:
    """Sayfayı açar; app=True ise (Kesim) adres çubuğu olmayan sade bir pencerede (Edge/Chrome --app)."""
    if app and os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            for exe in (Path(base) / "Microsoft/Edge/Application/msedge.exe",
                        Path(base) / "Google/Chrome/Application/chrome.exe"):
                if base and exe.is_file():
                    subprocess.Popen([str(exe), f"--app={url}", "--window-size=560,780"])  # noqa: S603
                    return
    webbrowser.open(url)


def main() -> int:
    global FACTORY
    ap = argparse.ArgumentParser(description="Reels Fabrikası uygulaması")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="tarayıcıda aç")
    ap.add_argument("--page", default="", help="açılacak sayfa (ör. kesim: sade montaj penceresi)")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/{args.page}"
    as_app = args.page == "kesim"
    if port_in_use(args.port):  # zaten çalışıyor: yalnızca paneli aç
        print(f"Uygulama zaten çalışıyor: {url}")
        if args.open:
            open_window(url, as_app)
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
        threading.Timer(1.0, lambda: open_window(url, as_app)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
