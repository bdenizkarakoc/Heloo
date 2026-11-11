"""Araçlar — ayrı uygulama: Fabrika çalışmadan, kendi penceresinde açık kaynak video araçlarını indirir/kurar/başlatır.

    python app/araclar_app.py            # kendi penceresinde aç (Araclar.bat aynısını yapar)
    python app/araclar_app.py --kisayol  # Masaüstüne "Araçlar" kısayolu koy (Windows)

Yalnızca 127.0.0.1'de dinler; başka siteden gelen istekleri (Host/Origin denetimi) kabul etmez.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reels import araclar, log  # noqa: E402

PORT = 8790
PAGE = ROOT / "app" / "araclar.html"
OPS = {"kur": araclar.install_async, "baslat": araclar.start, "durdur": araclar.stop}


class Handler(BaseHTTPRequestHandler):
    server_version = "Araclar"

    def log_message(self, fmt, *args):  # sessiz
        pass

    def _local(self) -> bool:
        """Yalnızca bu uygulamanın kendi sayfası: Host 127.0.0.1/localhost olmalı, Origin varsa aynı adres."""
        port = self.server.server_address[1]
        ok = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host", "") in ok and (not origin or urlparse(origin).netloc in ok)

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

    def do_GET(self):  # noqa: N802
        if not self._local():
            return self.send_error(400)
        path = urlparse(self.path).path
        if path in ("/", "/araclar"):
            return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/araclar":
            return self._json(araclar.status())
        if path.startswith("/api/araclar/log/"):
            return self._json({"log": araclar.log_tail(path.rsplit("/", 1)[-1])})
        if path == "/favicon.ico":
            return self._send(b"", "image/x-icon", 204)
        return self.send_error(404)

    def do_POST(self):  # noqa: N802
        if not self._local() or "json" not in self.headers.get("Content-Type", ""):
            return self.send_error(400)
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return self.send_error(400)
        if path == "/api/araclar/kapat":  # pencere kapanınca: başlatılan araçları durdur, uygulamadan çık
            self._json({"ok": True, "message": "Kapatıldı."})
            threading.Thread(target=shutdown, args=(self.server,), daemon=True).start()
            return None
        fn = OPS.get(path.rsplit("/", 1)[-1]) if path.startswith("/api/araclar/") else None
        if not fn:
            return self.send_error(404)
        return self._json(fn(str(data.get("name", ""))))


def shutdown(srv) -> None:
    for name in list(araclar._PROCS):
        araclar.stop(name)
    srv.shutdown()


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_window(url: str) -> None:
    """Edge/Chrome varsa adres çubuksuz uygulama penceresi; yoksa varsayılan tarayıcı."""
    names = ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")
    found = next((p for p in map(shutil.which, names) if p), None)
    if not found and os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                if base and (Path(base) / rel).is_file():
                    found = found or str(Path(base) / rel)
    if found:
        try:
            subprocess.Popen([found, f"--app={url}", "--window-size=1120,860"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def make_shortcut() -> int:
    """Masaüstüne "Araçlar" kısayolu (Windows): çift tıklayınca bu uygulama penceresiz Python ile açılır."""
    if os.name != "nt":
        print("Kısayol yalnızca Windows'ta oluşturulur; başlatmak için: python app/araclar_app.py")
        return 1
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").is_file() else exe
    ps = ("$d=[Environment]::GetFolderPath('Desktop');$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\Araçlar.lnk\");"
          f"$s.TargetPath='{pyw}';$s.Arguments='\"{Path(__file__).resolve()}\"';$s.WorkingDirectory='{ROOT}';"
          "$s.Description='Açık kaynak video araçları';$s.Save();Write-Output \"$d\\Araçlar.lnk\"")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print("Kısayol: " + r.stdout.strip() if r.returncode == 0 else "Kısayol oluşturulamadı: " + r.stderr.strip())
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Araçlar uygulaması (ayrı pencere)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-open", action="store_true", help="pencere açma (yalnızca sunucu)")
    ap.add_argument("--kisayol", action="store_true", help="Masaüstüne kısayol koy ve çık")
    args = ap.parse_args()
    if args.kisayol:
        return make_shortcut()
    url = f"http://127.0.0.1:{args.port}/"
    if port_in_use(args.port):  # zaten açık: yalnızca pencereyi göster
        if not args.no_open:
            open_window(url)
        return 0
    log.setup_logging(False)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if sys.stdout:
        print(f"Araçlar çalışıyor: {url}  (durdurmak için Ctrl+C ya da sayfadaki Kapat)")
    if not args.no_open:
        threading.Timer(0.8, open_window, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        shutdown_tools = list(araclar._PROCS)
        for name in shutdown_tools:
            araclar.stop(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
