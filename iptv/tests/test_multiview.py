"""Çoklu görüntü: 4 kanal aynı anda (gerçek libmpv, başsız)."""
from __future__ import annotations

import time

import pytest

from helootv import settings as settings_mod


def _mpv_ok() -> bool:
    try:
        import mpv  # noqa: F401
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def test_cell_settings_are_light():
    from helootv.ui.multiview import cell_settings
    s = settings_mod.merged_defaults()
    c = cell_settings(s)
    assert c["video"]["rtx_vsr"] is False and c["video"]["ai_upscaler"] == "off" and c["picture"]["denoise"] == "off"
    assert s["video"]["rtx_vsr"] is True                     # asıl ayarlar değişmez


@pytest.mark.skipif(not _mpv_ok(), reason="libmpv/PySide6 yok")
def test_multiview_four_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from helootv import catalog
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    m3u = tmp_path / "k.m3u"
    m3u.write_text("#EXTM3U\n" + "".join(
        f'#EXTINF:-1 tvg-id="k{i}" group-title="Ulusal",Kanal {i}\n'
        f"av://lavfi:testsrc2=size={w}x{h}:rate=25\n" for i, (w, h) in enumerate(
            [(640, 360), (480, 270), (320, 180), (800, 450)], 1)), encoding="utf-8")
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Test", kind="m3u", url=str(m3u))
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    catalog.refresh_source(store, store.get_source(sid), s)
    win = MainWindow(store, s, headless=True)
    win._mv_extra_options = {"ao": "null"}
    win.show()

    def pump(sec, until):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until():
                return True
            time.sleep(0.05)
        return until()

    assert pump(5, lambda: len(win.live_page.model.items) == 4)
    resumed = []
    win.play_live = lambda it: resumed.append(it.name)
    win.open_multiview()
    mv = win._multiview
    try:
        assert mv.count == 4 and len(mv.cells) == 4
        items = win.live_page.model.items
        for i in range(4):
            mv.assign(i, items[i])

        def sizes():
            out = []
            for c in mv.cells:
                st = c.engine.status() if c.engine else {}
                out.append(st.get("w"))
            return out
        assert pump(15, lambda: sizes() == [640, 480, 320, 800]), sizes()
        import os
        if os.environ.get("HELOOTV_SHOT"):
            mv.resize(1100, 700)
            app.processEvents()
            mv.grab().save(os.environ["HELOOTV_SHOT"])
        # ses yalnız etkin hücrede
        assert [bool(c.engine._get("mute")) for c in mv.cells] == [False, True, True, True]
        mv._on_event(2, "key", {"action": "click"})
        assert [bool(c.engine._get("mute")) for c in mv.cells] == [True, True, False, True]
        assert mv.cells[2].sound.text() == "🔊"
        # çift tık: tek hücre büyür, yeniden çift tık: geri
        mv._on_event(2, "key", {"action": "fullscreen"})
        assert mv.solo == 2 and mv.cells[0].isHidden() and not mv.cells[2].isHidden()
        mv._on_event(2, "key", {"action": "fullscreen"})
        assert mv.solo is None and not mv.cells[0].isHidden()
        mv.tick()
        # bağlantı sınırı uyarısı
        mv.max_connections = 2
        mv._check_limit()
        assert "2 bağlantıya" in mv.warn.text()
        # 2 kanala geçince fazladan hücrelerin yayını kapanır, etkin hücre ilk hücreye döner
        mv.set_layout(2)
        assert mv.cells[2].engine is None and mv.cells[3].engine is None and mv.active == 0
        assert mv.warn.text() == ""
        mv.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        assert all(c.engine is None for c in mv.cells)
        assert pump(2, lambda: resumed == ["Kanal 1"])     # etkin hücre ana oynatıcıda sürer
    finally:
        if getattr(win, "_multiview", None):
            win._multiview.shutdown()
        win.close()
