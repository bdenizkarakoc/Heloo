"""mpv indirici (varlık seçimi, BCJ2'li 7z açma) ve arayüz uçtan uca testi (offscreen Qt + başsız libmpv)."""
import os
import shutil
import subprocess
import time

import pytest

from helootv import settings as settings_mod
from helootv.tools import fetch_mpv

ASSETS = [{"name": n, "browser_download_url": f"https://example/{n}", "size": 1} for n in (
    "ffmpeg-x86_64-git-abc123.7z",
    "mpv-debug-x86_64-20261108-git-8bc4688.7z",
    "mpv-dev-lgpl-x86_64-20261108-git-8bc4688.7z",
    "mpv-dev-x86_64-20261108-git-8bc4688.7z",
    "mpv-dev-x86_64-v3-20261108-git-8bc4688.7z",
    "mpv-dev-aarch64-20261108-git-8bc4688.7z",
    "mpv-x86_64-20261108-git-8bc4688.7z",
    "mpv-x86_64-v3-20261108-git-8bc4688.7z",
)]


def test_pick_asset():
    assert fetch_mpv.pick_asset(ASSETS, "dev", avx2=True)["name"] == "mpv-dev-x86_64-v3-20261108-git-8bc4688.7z"
    assert fetch_mpv.pick_asset(ASSETS, "dev", avx2=False)["name"] == "mpv-dev-x86_64-20261108-git-8bc4688.7z"
    assert fetch_mpv.pick_asset(ASSETS, "player", avx2=True)["name"] == "mpv-x86_64-v3-20261108-git-8bc4688.7z"
    assert fetch_mpv.pick_asset(ASSETS, "dev", True, "aarch64")["name"] == "mpv-dev-aarch64-20261108-git-8bc4688.7z"
    assert fetch_mpv.pick_asset(ASSETS[:3], "dev", True) is None
    assert fetch_mpv.arch_name("ARM64") == "aarch64" and fetch_mpv.arch_name("AMD64") == "x86_64"


@pytest.mark.skipif(not (shutil.which("7z") or shutil.which("7zz")), reason="7z yok")
def test_extract_bcj2_archive(tmp_path):
    # mpv-winbuild ile aynı bayraklar: 7z a -m0=lzma2 -mx=9 -ms=on → .dll için BCJ2 filtresi
    pkg = tmp_path / "mpv-dev-x86_64-20261108-git-abc"
    (pkg / "include").mkdir(parents=True)
    (pkg / "libmpv-2.dll").write_bytes(os.urandom(4096) + b"MZ" * 2000)
    (pkg / "include" / "client.h").write_text("// h")
    archive = tmp_path / "pkg.7z"
    sevenzip = shutil.which("7z") or shutil.which("7zz")
    subprocess.run([sevenzip, "a", "-m0=lzma2", "-mx=9", "-ms=on", str(archive), f"{pkg}/*"], check=True,
                   capture_output=True)
    files = fetch_mpv.extract(archive, ["libmpv-2.dll"], tmp_path / "out", sevenzip)
    assert [f.name for f in files] == ["libmpv-2.dll"]
    assert files[0].read_bytes() == (pkg / "libmpv-2.dll").read_bytes()
    dest = tmp_path / "bin"
    dest.mkdir()
    (dest / "libmpv-2.dll").write_bytes(b"old")
    fetch_mpv._install_file(files[0], dest)
    assert (dest / "libmpv-2.dll").read_bytes() == files[0].read_bytes()


def test_install_refuses_non_windows(monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows'ta gerçek indirme CI'da ayrı adımda denenir")
    monkeypatch.delenv("HELOOTV_FETCH_ANY_OS", raising=False)
    with pytest.raises(fetch_mpv.FetchError):
        fetch_mpv.install()


# ---------------------------------------------------------------- arayüz (offscreen)

def _qt_ok() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def _mpv_ok() -> bool:
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _qt_ok(), reason="PySide6 yok")
def test_ui_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv import catalog
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    from helootv.ui.theme import apply_theme

    lavfi = "av://lavfi:testsrc2=size={w}x{h}:rate=25"
    m3u = tmp_path / "kanallar.m3u"
    m3u.write_text("#EXTM3U\n" + "".join(
        f'#EXTINF:-1 tvg-id="k{i}" group-title="{g}",Kanal {i}\n{lavfi.format(w=w, h=h)}\n'
        for i, (g, w, h) in enumerate([("Ulusal", 1280, 720), ("Ulusal", 1920, 1080), ("Haber", 720, 576)], 1)),
        encoding="utf-8")
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Test", kind="m3u", url=str(m3u))
    settings = settings_mod.merged_defaults()
    settings["ui"]["auto_refresh_hours"] = 0
    settings["ui"]["resume_last_channel"] = False
    catalog.refresh_source(store, store.get_source(sid), settings)
    store.update_source(sid, last_epg=time.time())

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    win = MainWindow(store, settings, headless=True)
    win.resize(1400, 860)
    win.show()

    def pump(seconds: float, until=None) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())

    assert pump(5, lambda: len(win.live_page.model.items) == 3)
    names = [r["name"] for r in win.live_page.cat_model.rows]
    assert names[:3] == ["⭐  Favori kanallar", "🕘  Son izlenenler", "📺  Tüm kanallar"] and "Ulusal" in names
    # arama Türkçe karakter duyarsız
    win.search.setText("KANAL 2")
    assert pump(3, lambda: [i.name for i in win.live_page.model.items] == ["Kanal 2"])
    win.search.setText("")
    assert pump(3, lambda: len(win.live_page.model.items) == 3)
    for i in range(5):
        win._select_tab(i)
        pump(0.2)
    win._select_tab(0)

    if not _mpv_ok():
        win.close()
        return
    from helootv.player.engine import MpvEngine
    eng = MpvEngine(settings, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d),
                    extra_options={"ao": "null"})
    eng.start()
    win.engine = eng
    try:
        first = win.live_page.model.items[0]
        win.play_live(first)
        assert pump(10, lambda: "1280×720" in win.status_stats.text()), win.status_stats.text()
        assert win.live_page.model.playing_key == first.key
        # kanal geçişi (Aşağı ok mpv'den gelir) ve numara ile kanal açma
        win._on_key("down", [])
        assert pump(10, lambda: "1920×1080" in win.status_stats.text())
        win._on_key("digit", ["3"])
        win._on_key("enter", [])
        assert pump(10, lambda: "720×576" in win.status_stats.text())
        win._on_key("last", [])
        assert pump(10, lambda: win.current_item and win.current_item.name == "Kanal 2")
        # tam ekran / sinema modu
        win._on_key("fullscreen", [])
        assert win._fs and not win.topbar.isVisible()
        win._on_key("esc", [])
        assert not win._fs and win.topbar.isVisible()
        win._set_theater(True)
        assert not win.pages.isVisible()
        win._on_key("esc", [])
        assert win.pages.isVisible()
        # favori + son izlenenler
        win.toggle_favorite(win.current_item)
        assert store.is_favorite(win.current_item.key)
        assert len(store.history(("live",))) >= 3
        win.stop()
        assert win.current_req is None
    finally:
        win.close()
        assert win.engine is None


def test_cli_survives_non_utf8_stdout(tmp_path):
    """Windows CI'da yakalanan hata: çıktı cp1252 boruya giderken 'İ'/'ı' yazmak çöküyordu."""
    import subprocess
    import sys
    env = dict(os.environ, PYTHONIOENCODING="cp1252", HELOOTV_HOME=str(tmp_path))
    root = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    res = subprocess.run([sys.executable, "-m", "helootv.tools.fetch_mpv", "--help"], cwd=root, env=env,
                         capture_output=True)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert "yalnız" in res.stdout.decode("utf-8")


@pytest.mark.skipif(not _qt_ok(), reason="PySide6 yok")
def test_source_dialog_and_settings_page(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.store import Store
    from helootv.ui.context import AppContext
    from helootv.ui.images import ImageLoader
    from helootv.ui.settings_page import SettingsPage, SourceDialog

    app = QApplication.instance() or QApplication([])
    dlg = SourceDialog(kind="m3u")
    dlg.m_url.setText("http://panel.tv:8080/get.php?username=ali&password=gizli&type=m3u_plus&output=ts")
    v = dlg.values()
    # get.php bağlantısı Xtream hesabına çevrilir (film/dizi ayrıntıları + EPG için)
    assert (v["kind"], v["url"], v["username"], v["password"]) == ("xtream", "http://panel.tv:8080", "ali", "gizli")
    dlg.tabs.setCurrentIndex(0)
    dlg.x_server.setText("")
    assert dlg._validate(dlg.values())  # boş sunucu → hata iletisi
    edit = SourceDialog(source={"kind": "m3u", "name": "Liste", "url": "C:/liste.m3u", "user_agent": "Özel UA/1.0",
                                "epg_url": "http://e/x.xml"})
    ev = edit.values()
    assert ev["kind"] == "m3u" and ev["user_agent"] == "Özel UA/1.0" and ev["epg_url"] == "http://e/x.xml"

    settings = settings_mod.merged_defaults()
    ctx = AppContext(Store(tmp_path / "s.db"), settings, ImageLoader())
    page = SettingsPage(ctx)
    changed = []
    page.settings_changed.connect(lambda: changed.append(1))
    page.lat_buttons["ultra"].setChecked(True)
    page.target.setCurrentIndex(page.target.findData("1440"))
    page.hdr.setChecked(True)
    assert settings["latency"]["mode"] == "ultra" and settings["video"]["vsr_target"] == "1440"
    assert settings["video"]["rtx_hdr"] is True and changed
    app.processEvents()


def test_download_retries_transient_github_errors(monkeypatch):
    """Windows CI'da yakalanan: GitHub 504 Gateway Time-out verince indirme hemen düşüyordu."""
    import urllib.error

    from helootv.tools import fetch_mpv as fm
    monkeypatch.setattr(fm.time, "sleep", lambda s: None)
    calls = []

    def flaky(x):
        calls.append(x)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 504, "Gateway Time-out", {}, None)
        return x

    msgs = []
    assert fm._retry(flaky, 7, progress=msgs.append) == 7 and len(calls) == 3 and len(msgs) == 2

    def missing():
        calls.append("404")
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        fm._retry(missing)
    assert calls.count("404") == 1   # kalıcı hata yeniden denenmez
