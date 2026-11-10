#!/usr/bin/env python3
"""Aktarım — bilgisayar ile telefon (iPhone/iOS ve Samsung/Android) arasında
dosya, fotoğraf, video, belge ve yazı aktarımı.

Bilgisayarda yerel bir sunucu çalışır; telefon aynı Wi-Fi ağında tarayıcıdan
(Safari/Chrome) QR kodu okutarak bağlanır. Uygulama yüklemek gerekmez.

  python aktarim.py                 # sunucuyu başlat, tarayıcıyı aç
  python aktarim.py ekle <dosya...> # dosyaları çalışan sunucuya gönder (Windows "Gönder" menüsü)
  python aktarim.py gonder-kur      # Windows "Gönder" (SendTo) menüsüne Aktarım'ı ekle

Silinen öğeler "Sonradan Sil" kutusuna gider: seçilen süre (1 hafta, 2 hafta,
1 ay) dolana kadar geri yüklenebilir, süre dolunca kendiliğinden silinir.

Yalnızca Python standart kitaplığı kullanır.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
DEFAULT_PORT = 8765
DAY = 86400
RETENTION_CHOICES = (7, 14, 30)          # 1 hafta, 2 hafta, 1 ay
MAX_TEXT = 1_000_000
CHUNK = 1 << 20


def default_data_dir() -> Path:
    env = os.environ.get("AKTARIM_DIR")
    if env:
        return Path(env).expanduser()
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "Masaüstü"
    base = desktop if desktop.is_dir() else Path.home()
    return base / "Aktarım"


def device_from_ua(ua: str) -> str:
    ua = ua or ""
    if re.search(r"iPhone", ua):
        return "iPhone"
    if re.search(r"iPad", ua) or ("Macintosh" in ua and "Mobile" in ua):
        return "iPad"
    if re.search(r"SM-|Samsung", ua, re.I):
        return "Samsung"
    if "Android" in ua:
        return "Android"
    if "Windows" in ua:
        return "Bilgisayar"
    if "Macintosh" in ua:
        return "Mac"
    if "Linux" in ua:
        return "Bilgisayar"
    return "Cihaz"


def safe_name(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    return name[:180] or "dosya"


def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


class Store:
    """Öğelerin (dosya/yazı) kaydı. Dosyalar `files/`, kayıt `items.json`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.files = self.root / "files"
        self.files.mkdir(parents=True, exist_ok=True)
        self.meta = self.root / "items.json"
        self.cfg_path = self.root / "ayarlar.json"
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.version = 0
        self.cfg = {"token": secrets.token_urlsafe(9), "retention_days": 14,
                    "port": DEFAULT_PORT}
        self._load()

    # ---- kalıcılık -------------------------------------------------------
    def _load(self) -> None:
        if self.cfg_path.exists():
            try:
                self.cfg.update(json.loads(self.cfg_path.read_text("utf-8")))
            except (OSError, ValueError):
                pass
        self._save_cfg()
        if self.meta.exists():
            try:
                self.items = json.loads(self.meta.read_text("utf-8"))
            except (OSError, ValueError):
                self.items = []
        self.purge_expired()

    def _save_cfg(self) -> None:
        self._atomic_write(self.cfg_path, self.cfg)

    def _save(self) -> None:
        self.version += 1
        self._atomic_write(self.meta, self.items)

    @staticmethod
    def _atomic_write(path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, path)

    # ---- yardımcılar -----------------------------------------------------
    def get(self, item_id: str) -> dict | None:
        with self.lock:
            return next((i for i in self.items if i["id"] == item_id), None)

    def path_of(self, item: dict) -> Path:
        return self.files / item["file"]

    def _new_item(self, **kw) -> dict:
        item = {"id": uuid.uuid4().hex[:12], "created": time.time(),
                "deleted_at": None, "expires_at": None}
        item.update(kw)
        return item

    def set_retention(self, days: int) -> None:
        if days not in RETENTION_CHOICES:
            raise ValueError("süre 7, 14 ya da 30 gün olmalı")
        with self.lock:
            self.cfg["retention_days"] = days
            self._save_cfg()
            self.version += 1

    # ---- ekleme ----------------------------------------------------------
    def add_file_stream(self, name: str, stream, length: int, source: str,
                        mime: str | None = None) -> dict:
        name = safe_name(name)
        fid = uuid.uuid4().hex[:12]
        ext = Path(name).suffix[:12]
        fname = f"{fid}{ext}"
        tmp = self.files / (fname + ".part")
        written = 0
        try:
            with open(tmp, "wb") as fh:
                remaining = length
                while remaining > 0:
                    chunk = stream.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
            if written != length:
                raise IOError("aktarım yarıda kesildi")
            os.replace(tmp, self.files / fname)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        item = self._new_item(id=fid, kind="file", name=name, file=fname,
                              size=written, mime=mime, source=source)
        with self.lock:
            self.items.append(item)
            self._save()
        return item

    def add_file_path(self, src: Path, source: str = "Bilgisayar") -> dict:
        src = Path(src)
        with open(src, "rb") as fh:
            return self.add_file_stream(src.name, fh, src.stat().st_size, source)

    def add_text(self, text: str, source: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("boş yazı")
        if len(text) > MAX_TEXT:
            raise ValueError("yazı çok uzun")
        item = self._new_item(kind="text", text=text, name=text.splitlines()[0][:60],
                              size=len(text.encode("utf-8")), source=source)
        with self.lock:
            self.items.append(item)
            self._save()
        return item

    # ---- silme / geri yükleme -------------------------------------------
    def soft_delete(self, item_id: str, days: int | None = None) -> dict:
        days = days or int(self.cfg.get("retention_days", 14))
        if days not in RETENTION_CHOICES:
            raise ValueError("süre 7, 14 ya da 30 gün olmalı")
        with self.lock:
            item = self.get(item_id)
            if not item:
                raise KeyError(item_id)
            now = time.time()
            item["deleted_at"] = item["deleted_at"] or now
            item["expires_at"] = now + days * DAY
            item["retention_days"] = days
            self._save()
            return item

    def restore(self, item_id: str) -> dict:
        with self.lock:
            item = self.get(item_id)
            if not item:
                raise KeyError(item_id)
            item["deleted_at"] = None
            item["expires_at"] = None
            item.pop("retention_days", None)
            self._save()
            return item

    def hard_delete(self, item_id: str) -> None:
        with self.lock:
            item = self.get(item_id)
            if not item:
                raise KeyError(item_id)
            self._remove(item)
            self._save()

    def _remove(self, item: dict) -> None:
        if item.get("kind") == "file":
            self.path_of(item).unlink(missing_ok=True)
        self.items = [i for i in self.items if i["id"] != item["id"]]

    def empty_bin(self) -> int:
        with self.lock:
            gone = [i for i in self.items if i.get("deleted_at")]
            for item in gone:
                self._remove(item)
            if gone:
                self._save()
            return len(gone)

    def purge_expired(self, now: float | None = None) -> int:
        now = now or time.time()
        with self.lock:
            gone = [i for i in self.items
                    if i.get("expires_at") and i["expires_at"] <= now]
            for item in gone:
                self._remove(item)
            if gone:
                self._save()
            return len(gone)

    def listing(self) -> dict:
        with self.lock:
            active = [i for i in self.items if not i.get("deleted_at")]
            binned = [i for i in self.items if i.get("deleted_at")]
            active.sort(key=lambda i: i["created"], reverse=True)
            binned.sort(key=lambda i: i["expires_at"] or 0)
            return {"items": active, "bin": binned, "version": self.version,
                    "retention_days": self.cfg.get("retention_days", 14),
                    "choices": list(RETENTION_CHOICES), "now": time.time(),
                    "total_size": sum(i.get("size", 0) for i in self.items)}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

STATIC = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css",
          "/manifest.webmanifest": "manifest.webmanifest", "/icon.svg": "icon.svg"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Aktarim/1.0"
    store: Store = None  # type: ignore[assignment]
    urls: list[str] = []

    def log_message(self, fmt, *args):  # sessiz çalış
        if os.environ.get("AKTARIM_LOG"):
            super().log_message(fmt, *args)

    # ---- yardımcılar -----------------------------------------------------
    def _token_ok(self) -> bool:
        token = self.store.cfg["token"]
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if q.get("k", [""])[0] == token:
            return True
        if self.headers.get("X-Aktarim-Key") == token:
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return "aktarim" in cookie and cookie["aktarim"].value == token

    def _json(self, data, status=200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status)

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_TEXT * 4:
            raise ValueError("istek çok büyük")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    @property
    def source(self) -> str:
        return device_from_ua(self.headers.get("User-Agent", ""))

    # ---- GET -------------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in STATIC:
            if path == "/" and not self._token_ok():
                return self._locked_page()
            return self._static(STATIC[path], set_cookie=(path == "/"))
        if not self._token_ok():
            return self._error(401, "bağlantı anahtarı gerekli — QR kodunu yeniden okutun")
        if path == "/api/items":
            return self._json(self.store.listing())
        if path == "/api/info":
            return self._json({"urls": self.urls, "token": self.store.cfg["token"],
                               "device": self.source, "data_dir": str(self.store.root)})
        if path == "/api/version":
            return self._json({"version": self.store.version})
        m = re.fullmatch(r"/api/file/([0-9a-f]{12})(?:/.*)?", path)
        if m:
            return self._send_file(m.group(1))
        return self._error(404, "bulunamadı")

    def _locked_page(self) -> None:
        body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<title>Aktarım</title><body style='font-family:-apple-system,system-ui;"
                "padding:40px 20px;text-align:center;color:#1c1c1e'><h2>Aktarım</h2>"
                "<p>Bağlanmak için bilgisayardaki Aktarım ekranında görünen QR kodunu "
                "telefonunun kamerasıyla okut.</p>").encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str, set_cookie=False) -> None:
        p = WEB / name
        data = p.read_bytes()
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml",
                 "webmanifest": "application/manifest+json"}[p.suffix[1:]]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if set_cookie:
            self.send_header("Set-Cookie", f"aktarim={self.store.cfg['token']}; Path=/; "
                                           "Max-Age=31536000; SameSite=Strict; HttpOnly")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, item_id: str) -> None:
        item = self.store.get(item_id)
        if not item or item.get("kind") != "file":
            return self._error(404, "dosya yok")
        p = self.store.path_of(item)
        if not p.exists():
            return self._error(404, "dosya diskte yok")
        size = p.stat().st_size
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng or "")
        if m and size:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = 206
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        disp = "attachment" if q.get("dl") else "inline"
        quoted = urllib.parse.quote(item["name"])
        self.send_response(status)
        self.send_header("Content-Type", item.get("mime") or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{quoted}")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        if self.command == "HEAD" or not size:
            return
        with open(p, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_HEAD(self):
        self.do_GET()

    # ---- POST ------------------------------------------------------------
    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._token_ok():
            return self._error(401, "bağlantı anahtarı gerekli")
        try:
            if path == "/api/upload":
                length = int(self.headers.get("Content-Length") or -1)
                if length < 0:
                    return self._error(411, "Content-Length gerekli")
                name = urllib.parse.unquote(self.headers.get("X-Filename", "dosya"))
                mime = self.headers.get("Content-Type")
                if mime in (None, "", "application/x-www-form-urlencoded"):
                    mime = None
                item = self.store.add_file_stream(name, self.rfile, length,
                                                  self.headers.get("X-Source") or self.source,
                                                  mime)
                return self._json(item, 201)
            data = self._body_json()
            if path == "/api/text":
                return self._json(self.store.add_text(data.get("text", ""), self.source), 201)
            if path == "/api/delete":
                days = data.get("days")
                return self._json(self.store.soft_delete(data["id"], int(days) if days else None))
            if path == "/api/restore":
                return self._json(self.store.restore(data["id"]))
            if path == "/api/purge":
                self.store.hard_delete(data["id"])
                return self._json({"ok": True})
            if path == "/api/empty-bin":
                return self._json({"removed": self.store.empty_bin()})
            if path == "/api/settings":
                self.store.set_retention(int(data["retention_days"]))
                return self._json({"retention_days": self.store.cfg["retention_days"]})
        except KeyError:
            return self._error(404, "öğe bulunamadı")
        except (ValueError, TypeError) as exc:
            return self._error(400, str(exc))
        except OSError as exc:
            return self._error(500, f"kaydedilemedi: {exc}")
        return self._error(404, "bulunamadı")


def make_server(store: Store, host="0.0.0.0", port=DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": store})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    real_port = srv.server_address[1]
    handler.urls = [f"http://{ip}:{real_port}/?k={store.cfg['token']}" for ip in local_ips()]
    return srv


def janitor(store: Store, stop: threading.Event, every=600) -> None:
    while not stop.wait(every):
        store.purge_expired()


# ---------------------------------------------------------------------------
# komut satırı
# ---------------------------------------------------------------------------

def cmd_serve(args) -> None:
    store = Store(Path(args.dir) if args.dir else default_data_dir())
    port = args.port or int(store.cfg.get("port", DEFAULT_PORT))
    try:
        srv = make_server(store, port=port)
    except OSError:
        srv = make_server(store, port=0)
    port = srv.server_address[1]
    stop = threading.Event()
    threading.Thread(target=janitor, args=(store, stop), daemon=True).start()
    local = f"http://127.0.0.1:{port}/?k={store.cfg['token']}"
    print("Aktarım çalışıyor.")
    print(f"  Klasör   : {store.root}")
    print(f"  Bilgisayar: {local}")
    for u in srv.RequestHandlerClass.urls:
        print(f"  Telefon  : {u}")
    print("Telefon ile bilgisayar aynı Wi-Fi ağında olmalı. Kapatmak için Ctrl+C.")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(local,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


def cmd_add(args) -> None:
    store_dir = Path(args.dir) if args.dir else default_data_dir()
    cfg_path = store_dir / "ayarlar.json"
    cfg = json.loads(cfg_path.read_text("utf-8")) if cfg_path.exists() else {}
    port = args.port or cfg.get("port", DEFAULT_PORT)
    files = [Path(f) for f in args.files]
    paths: list[Path] = []
    for f in files:
        paths += [p for p in sorted(f.rglob("*")) if p.is_file()] if f.is_dir() else [f]
    try:
        for p in paths:
            with open(p, "rb") as fh:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/upload", data=fh, method="POST",
                    headers={"X-Aktarim-Key": cfg.get("token", ""),
                             "X-Filename": urllib.parse.quote(p.name),
                             "X-Source": "Bilgisayar",
                             "Content-Length": str(p.stat().st_size),
                             "Content-Type": mimetypes.guess_type(p.name)[0]
                             or "application/octet-stream"})
                urllib.request.urlopen(req, timeout=600).read()
            print(f"gönderildi: {p.name}")
    except OSError:
        # sunucu kapalı: doğrudan klasöre ekle
        store = Store(store_dir)
        for p in paths:
            store.add_file_path(p)
            print(f"eklendi: {p.name}")


def cmd_sendto(args) -> None:
    if os.name != "nt":
        sys.exit("Bu komut yalnızca Windows içindir.")
    sendto = Path(os.environ["APPDATA"]) / "Microsoft/Windows/SendTo"
    bat = sendto / "Telefona gönder (Aktarım).bat"
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    bat.write_text(f'@echo off\r\n"{pyw if pyw.exists() else py}" "{HERE / "aktarim.py"}" ekle %*\r\n',
                   encoding="utf-8")
    print(f"Eklendi: sağ tık → Gönder → {bat.stem}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="aktarim", description="Bilgisayar ↔ telefon aktarımı")
    ap.add_argument("--dir", help="veri klasörü (varsayılan: Masaüstü\\Aktarım)")
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("ekle", help="dosyaları/klasörleri ekle")
    a.add_argument("files", nargs="+")
    sub.add_parser("gonder-kur", help="Windows Gönder menüsüne ekle")
    args = ap.parse_args(argv)
    if args.cmd == "ekle":
        cmd_add(args)
    elif args.cmd == "gonder-kur":
        cmd_sendto(args)
    else:
        cmd_serve(args)


if __name__ == "__main__":
    main()
