"""Heloo TV giriş noktası: `python -m helootv` (Windows'ta "Heloo TV.bat" / masaüstü kısayolu)."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys

from . import APP_ID, APP_NAME, __version__, paths


def _setup_logging(debug: bool) -> None:
    handler = logging.handlers.RotatingFileHandler(paths.log_path(), maxBytes=2_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if debug or (sys.stderr is not None and sys.stderr.isatty()):
        root.addHandler(logging.StreamHandler())
    root.setLevel(logging.DEBUG if debug else logging.INFO)


def main(argv: list[str] | None = None) -> int:
    paths.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(prog="helootv", description=f"{APP_NAME} {__version__} — IPTV oynatıcı")
    ap.add_argument("--debug", action="store_true", help="ayrıntılı günlük (mpv dahil)")
    ap.add_argument("--reset-settings", action="store_true", help="ayarları en iyi varsayılanlara döndür")
    ap.add_argument("--write-icon", metavar="YOL", help="uygulama simgesini .ico/.png olarak yaz ve çık")
    ap.add_argument("--screenshot", metavar="YOL", help="(test) pencereyi çizip PNG kaydet ve çık")
    ap.add_argument("paths", nargs="*", help="açılacak video/fotoğraf dosyaları ya da bağlantılar (4K'ya yükseltilir)")
    args = ap.parse_args(argv)

    if args.write_icon:
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication(sys.argv[:1])
        from .ui.theme import draw_logo
        ok = draw_logo(256).save(args.write_icon)
        del app
        return 0 if ok else 1

    _setup_logging(args.debug)
    log = logging.getLogger("helootv")
    log.info("%s %s başlıyor (Python %s, %s)", APP_NAME, __version__, sys.version.split()[0], sys.platform)
    paths.prepare_libmpv_search_path()
    if os.name == "nt":
        try:  # görev çubuğunda python simgesi yerine uygulama simgesi
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"Heloo.{APP_ID}")
        except Exception:
            pass

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Heloo")
    app.setApplicationVersion(__version__)
    if not args.screenshot and forward_to_running(args.paths):
        return 0  # uygulama zaten açık: dosyalar ona gönderildi
    if os.name != "nt":
        import locale
        locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv şartı (Qt yereli değiştirir)

    from .settings import load_settings, merged_defaults, save_settings
    from .store import Store
    from .ui.main_window import MainWindow
    from .ui.theme import app_icon, apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    settings = merged_defaults() if args.reset_settings else load_settings(paths.settings_path())
    if args.reset_settings:
        save_settings(settings, paths.settings_path())
    store = Store(paths.db_path())
    win = MainWindow(store, settings, debug=args.debug, headless=bool(args.screenshot))
    win.restore_geometry()
    if args.screenshot:
        from PySide6.QtCore import QTimer
        win.resize(1600, 960)
        win.show()

        def shot():
            win.grab().save(args.screenshot)
            win.close()
            app.quit()

        QTimer.singleShot(2500, shot)
        return app.exec()
    server = start_server(win)
    win.show()
    if args.paths:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(800, lambda: win.open_paths(args.paths))
    code = app.exec()
    if server is not None:
        server.close()
    store.close()
    return code


def _server_name() -> str:
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"HelooTV-{user}"


def forward_to_running(items: list[str]) -> bool:
    """Açık bir Heloo TV varsa dosyaları ona iletir (Gönder/Birlikte aç ile ikinci pencere açılmaz)."""
    import json
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(400):
        return False
    full = [str(os.path.abspath(p)) if os.path.exists(p) else p for p in items]
    sock.write(json.dumps(full).encode("utf-8"))
    sock.waitForBytesWritten(2000)
    sock.disconnectFromServer()
    return True


def start_server(win):
    import json
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(win)
    QLocalServer.removeServer(_server_name())
    if not server.listen(_server_name()):
        return None

    def on_conn():
        sock = server.nextPendingConnection()

        def read():
            try:
                items = json.loads(bytes(sock.readAll()).decode("utf-8") or "[]")
            except ValueError:
                items = []
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
            if items:
                win.open_paths(items)

        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(on_conn)
    return server
