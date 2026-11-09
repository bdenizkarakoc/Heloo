"""Lossless Scaling ile birlikte çalışma: kurulum bulma, kısayol çözümleme, mpv interpolasyonunun kapanması."""
from __future__ import annotations

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
    assert s["lossless"] == {"auto_fullscreen": False, "hotkey": "Ctrl+Alt+S", "exe": "", "tips_shown": False}
    vod = opt.play_options(s, "movie", "http://x/film.mkv")
    assert vod["interpolation"] == "yes" and vod["video-sync"] == "display-resample"
    ls = opt.play_options(s, "movie", "http://x/film.mkv", external_framegen=True)
    assert ls["interpolation"] == "no" and ls["video-sync"] == "audio"
    # bozuk değerler varsayılana döner
    bad = settings_mod._sanitize({"lossless": {"auto_fullscreen": "evet", "hotkey": 5}})
    assert bad["lossless"]["auto_fullscreen"] is False and bad["lossless"]["hotkey"] == "Ctrl+Alt+S"


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
    page.ls_auto.setChecked(True)
    page.ls_hotkey.setText("Ctrl+Shift+L")
    page.ls_hotkey.editingFinished.emit()
    assert s["lossless"]["auto_fullscreen"] is True and s["lossless"]["hotkey"] == "Ctrl+Shift+L"
    page.ls_hotkey.setText("Bozuk+++")
    page.ls_hotkey.editingFinished.emit()
    assert s["lossless"]["hotkey"] == "Ctrl+Shift+L"   # geçersiz kısayol kaydedilmez
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
