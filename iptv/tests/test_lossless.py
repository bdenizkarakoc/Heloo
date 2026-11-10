"""Lossless Scaling ile birlikte çalışma: kurulum bulma, kısayol çözümleme, mpv interpolasyonunun kapanması."""
from __future__ import annotations

import time

import pytest

from helootv import lossless, settings as settings_mod
from helootv.player import options as opt


def test_parse_hotkey():
    assert lossless.parse_hotkey("Ctrl+Alt+S") == ([0x11, 0x12], ord("S"))
    assert lossless.parse_hotkey("shift + f9") == ([0x10], 0x78)
    assert lossless.parse_hotkey("Alt+Home") == ([0x12], 0x24)
    for bad in ("", "Ctrl+", "Hyper+S", "Ctrl+Alt+ÇÇ"):
        with pytest.raises(ValueError):
            lossless.parse_hotkey(bad)


def test_find_exe_in_steam_libraries(tmp_path):
    steam = tmp_path / "Steam"
    other = tmp_path / "Oyunlar"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (str(steam).replace("\\", "\\\\"), str(other).replace("\\", "\\\\")), encoding="utf-8")
    assert lossless.find_exe(roots=[steam]) is None
    exe = other / "steamapps" / "common" / "Lossless Scaling" / lossless.EXE
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert lossless.find_exe(roots=[steam]) == str(exe)
    custom = tmp_path / "LS.exe"
    custom.write_bytes(b"MZ")
    assert lossless.find_exe(str(custom), roots=[]) == str(custom)


def test_external_framegen_disables_mpv_interpolation():
    s = settings_mod.merged_defaults()
    assert s["lossless"] == {"mode": "manual", "app_shortcut": "Ctrl+Z", "hotkey": "Ctrl+Alt+S", "exe": "",
                             "tips_shown": False}
    vod = opt.play_options(s, "movie", "http://x/film.mkv")
    assert vod["interpolation"] == "yes" and vod["video-sync"] == "display-resample"
    ls = opt.play_options(s, "movie", "http://x/film.mkv", external_framegen=True)
    assert ls["interpolation"] == "no" and ls["video-sync"] == "audio"
    # bozuk değerler varsayılana döner
    bad = settings_mod._sanitize({"lossless": {"mode": "evet", "hotkey": 5}})
    assert bad["lossless"]["mode"] == "manual" and bad["lossless"]["hotkey"] == "Ctrl+Alt+S"


def test_send_hotkey_requires_windows(monkeypatch):
    monkeypatch.setattr(lossless.sys, "platform", "linux")
    with pytest.raises(RuntimeError):
        lossless.send_hotkey("Ctrl+Alt+S")
    assert lossless.is_running() is False


def test_settings_page_lossless(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from helootv.store import Store
    from helootv.ui.context import AppContext
    from helootv.ui.images import ImageLoader
    from helootv.ui.settings_page import SettingsPage
    QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    page = SettingsPage(AppContext(Store(tmp_path / "s.db"), s, ImageLoader()))
    page.ls_mode.setCurrentIndex(page.ls_mode.findData("manual"))
    page.ls_hotkey.setText("Ctrl+Shift+L")
    page.ls_hotkey.editingFinished.emit()
    assert s["lossless"]["mode"] == "manual" and s["lossless"]["hotkey"] == "Ctrl+Shift+L"
    page.ls_hotkey.setText("Bozuk+++")
    page.ls_hotkey.editingFinished.emit()
    assert s["lossless"]["hotkey"] == "Ctrl+Shift+L"   # geçersiz kısayol kaydedilmez
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_enhancement_summary_live_and_vod():
    s = settings_mod.merged_defaults()
    # canlı SD yayın, RTX VSR çalışıyor
    plan = opt.vsr_plan(s, {"w": 720, "h": 576, "dw": 1024, "dh": 576}, platform="win32", kind="live")
    enh = opt.enhancement_summary(s, plan, True, {"w": 720, "h": 576}, "win32", framegen=True)
    assert enh[0] == "RTX VSR 576p→2160p" and "Gürültü azaltma" in enh and "Keskinlik" in enh
    assert "Bant yumuşatma" in enh and enh[-1] == "Lossless Scaling kare üretimi"
    # VSR yoksa (NVIDIA olmayan kart / Linux) yine iyileştirme var
    plan = opt.vsr_plan(s, {"w": 1280, "h": 720}, platform="linux", kind="live")
    enh = opt.enhancement_summary(s, plan, False, {"w": 1280, "h": 720}, "linux")
    assert enh and "Gürültü azaltma" in enh and "Keskinlik" in enh


def test_ctrl_z_toggles_lossless_and_fullscreen_does_not(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import INPUT_CONF, write_input_conf
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    assert lossless.mpv_key("Ctrl+Z") == "ctrl+z" and lossless.mpv_key("Alt+F9") == "alt+F9"
    assert lossless.mpv_key("bozuk+++") == ""
    conf = write_input_conf(tmp_path, "ctrl+z  script-message helootv lossless\n")
    assert conf.read_text(encoding="utf-8").endswith("ctrl+z  script-message helootv lossless\n")
    assert "lossless" not in INPUT_CONF
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    calls = []
    monkeypatch.setattr(win, "toggle_lossless", lambda quiet=False, want=None: calls.append((quiet, want)))
    win._ls_shortcut.activated.disconnect()
    win._ls_shortcut.activated.connect(win.toggle_lossless)
    try:
        assert win._ls_shortcut.key().toString() == "Ctrl+Z"
        win._ls_shortcut.activated.emit()                    # Heloo TV penceresinde Ctrl+Z
        win._on_key("lossless", [])                          # video (mpv) penceresinde Ctrl+Z
        assert calls == [(False, None), (False, None)]
        from helootv.player.engine import PlayRequest
        win.current_req = PlayRequest(url="x", title="beIN SPORTS 1", kind="live")
        monkeypatch.setattr(win, "showFullScreen", lambda: None)
        win._set_fullscreen(True)                            # tam ekran: kendiliğinden AÇILMAZ (kip: elle)
        end = time.time() + 1.5
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        assert len(calls) == 2
        win._set_fullscreen(False)
        s["lossless"]["app_shortcut"] = "Ctrl+Shift+L"       # ayardan değiştirilebilir
        win._on_settings_changed()
        assert win._ls_shortcut.key().toString() == "Ctrl+Shift+L"
    finally:
        win.current_req = None
        win.close()
