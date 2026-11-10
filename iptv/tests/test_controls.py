"""Videoya tıklama (YouTube gibi) ve çoklu görüntüde fareyle ses / yeniden boyutlandırma."""
from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from helootv import settings as settings_mod
from helootv.player import options as opt


def test_click_zones():
    z = opt.click_zone
    assert z(100, 1200, "movie") == "back" and z(600, 1200, "movie") == "pause" and z(1100, 1200, "live") == "forward"
    assert z(1100, 1200, "movie", "pause") == "pause" and z(600, 1200, "movie", "none") == "none"
    assert z(None, None, "movie") == "pause"            # konum bilinmiyorsa duraklat
    assert z(100, 1200, "image") == "none"              # fotoğrafta sarma/duraklatma yok
    s = settings_mod.merged_defaults()
    assert s["controls"] == {"click_action": "zones", "seek_step": 5, "mv_audio_hover": True,
                             "arrow_keys": "volume", "media_keys_zap": False, "stay_live": True, "catchup": "ask"}
    bad = settings_mod._sanitize({"controls": {"click_action": "x", "seek_step": 999}})
    assert bad["controls"]["click_action"] == "zones" and bad["controls"]["seek_step"] == 60


def _mpv_ok() -> bool:
    try:
        import mpv  # noqa: F401
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_click_pause_and_side_seek(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    vid = tmp_path / "film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:d=60",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", str(vid)], check=True)
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.show()
    eng = MpvEngine(s, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d), extra_options={"ao": "null"})
    eng.start()
    win.engine = eng
    real_get = eng._get
    mouse = {"x": 600}
    eng._get = lambda name: ({"x": mouse["x"], "y": 300, "hover": True} if name == "mouse-pos" else
                             {"w": 1200, "h": 675} if name == "osd-dimensions" else real_get(name))

    def pump(sec, until=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())

    def pos():
        return float(real_get("time-pos") or 0)

    def click(x):
        mouse["x"] = x
        win._on_key("click", [])
        pump(0.8)                                  # çift tık süresi geçsin
    try:
        win.play_file(str(vid))
        assert pump(10, lambda: pos() > 0.5)
        eng.seek_abs(20)
        assert pump(5, lambda: 19.5 < pos() < 22)
        click(600)                                 # orta → duraklat
        assert real_get("pause") is True
        click(600)                                 # orta → sürdür
        assert real_get("pause") is False
        eng._set("pause", "yes")
        p0 = pos()
        click(1150)                                # sağ → 5 sn ileri
        assert pump(3, lambda: abs(pos() - (p0 + 5)) < 1.5), (p0, pos())
        p1 = pos()
        click(50)                                  # sol → 5 sn geri
        assert pump(3, lambda: abs(pos() - (p1 - 5)) < 1.5), (p1, pos())
        win.settings["controls"]["seek_step"] = 10
        p2 = pos()
        click(1150)
        assert pump(3, lambda: abs(pos() - (p2 + 10)) < 1.5)
        # çift tık: duraklatma/sarma yok, yalnız tam ekran
        paused, p3 = real_get("pause"), pos()
        mouse["x"] = 600
        win._on_key("click", [])
        win._on_key("click", [])
        win._on_key("fullscreen", [])
        pump(0.8)
        assert win._fs and real_get("pause") == paused and abs(pos() - p3) < 0.5
        win._set_fullscreen(False)
        # ayardan kapatılabilir
        win.settings["controls"]["click_action"] = "none"
        click(600)
        assert real_get("pause") == paused
    finally:
        win.close()


@pytest.mark.skipif(not _mpv_ok(), reason="PySide6/libmpv yok")
def test_multiview_audio_follows_mouse_and_resize(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from helootv.ui import multiview as mv_mod
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    mv = mv_mod.MultiViewWindow(s, [], lambda it: None, headless=True)
    mv.resize(1200, 800)
    mv.show()
    app.processEvents()
    try:
        assert mv.count == 2 and mv.rows[1].isHidden()
        mv.set_layout(4)
        app.processEvents()
        # 2 → 4'e geçişte alt sıra da görünür boyutta olmalı (eskiden yüksekliği 0 kalıyordu)
        assert min(c.height() for c in mv.cells) > 200, [c.height() for c in mv.cells]
        target = mv.cells[3]
        g = target.mapToGlobal(target.rect().center())
        mv.cursor_pos = lambda: QPoint(g)
        mv._follow_mouse()
        assert mv.active == 3 and mv.cells[3].sound.text() == "🔊" and mv.cells[0].sound.text() == "🔇"
        s["controls"]["mv_audio_hover"] = False              # ayardan kapatılabilir
        g0 = mv.cells[0].mapToGlobal(mv.cells[0].rect().center())
        mv.cursor_pos = lambda: QPoint(g0)
        mv._follow_mouse()
        assert mv.active == 3
        # bölücüyle büyüt / küçült, sonra eşit böl
        w0 = mv.cells[0].width()
        mv.rows[0].setSizes([900, 200])
        app.processEvents()
        assert mv.cells[0].width() > w0 * 1.4 > mv.cells[1].width()
        mv.equalize()
        app.processEvents()
        assert abs(mv.cells[0].width() - mv.cells[1].width()) < 20
        mv.set_solo(3)
        assert mv.rows[0].isHidden() and not mv.cells[3].isHidden()
        mv.set_solo(None)
        assert not mv.rows[0].isHidden()
    finally:
        mv.close()


@pytest.mark.skipif(not _mpv_ok(), reason="libmpv/PySide6 yok")
def test_live_stays_live_and_replay_never_opens_by_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from helootv import catalog
    from helootv.player.engine import MpvEngine
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    m3u = tmp_path / "k.m3u"
    m3u.write_text('#EXTM3U catchup="shift" catchup-days="3"\n'
                   '#EXTINF:-1 tvg-id="b1" group-title="Spor",beIN SPORTS 1\nav://lavfi:testsrc2=size=640x360:rate=25,realtime\n',
                   encoding="utf-8")
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Test", kind="m3u", url=str(m3u))
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    catalog.refresh_source(store, store.get_source(sid), s)
    win = MainWindow(store, s, headless=True)
    win.show()
    eng = MpvEngine(s, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d), extra_options={"ao": "null"})
    eng.start()
    win.engine = eng
    went_live = []
    real_go_live = eng.go_live
    eng.go_live = lambda: (went_live.append(1), real_go_live())

    def pump(sec, until=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())
    try:
        assert pump(5, lambda: len(win.live_page.model.items) == 1)
        bein = win.live_page.model.items[0]
        win.play_live(bein)
        assert pump(10, lambda: eng.status().get("w") == 640)
        assert win.player.live_badge.text() == "● CANLI"
        # duraklat → sürdür: canlı kenara döner (geriden "tekrar gibi" izlenmez)
        win._toggle_pause()
        assert eng._get("pause") is True
        win._toggle_pause()
        assert eng._get("pause") is False and went_live and eng._user_paused is False
        # canlıda geri sarma yok (← tuşu ve sola tıklama)
        p0 = float(eng._get("time-pos") or 0)
        win._on_key("left", [])
        pump(0.5)
        assert float(eng._get("time-pos") or 0) >= p0
        prog = {"start": int(time.time()) - 7200, "stop": int(time.time()) - 3600, "title": "Maç (1. yarı)"}
        # tekrar kapalı: hiç açılmaz
        s["controls"]["catchup"] = "off"
        win.play_catchup(bein, prog)
        assert win.current_req.kind == "live"
        # sorarak: soru penceresinde varsayılan "Canlıda kal" → açılmaz
        s["controls"]["catchup"] = "ask"
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)       # kullanıcı Enter/Esc: varsayılan
        win.play_catchup(bein, prog)
        assert win.current_req.kind == "live"
        # bilerek onaylanırsa açılır ve TEKRAR olduğu açıkça görünür; "Canlıya dön" canlı kanala geçer
        monkeypatch.setattr(win, "confirm_catchup", lambda it, p: True)
        win.play_catchup(bein, prog)
        assert win.current_req.kind == "catchup"
        assert win.player.live_badge.text() == "⟲ TEKRAR" and not win.player.live_badge.isHidden()
        assert win.player.btn_live.text() == "⦿ Canlıya dön" and not win.player.btn_live.isHidden()
        win.player.live_clicked.emit()
        assert win.current_req.kind == "live" and win.switch_log[-1][3] == "tekrardan canlıya dönüş"
        assert pump(10, lambda: eng.status().get("w") == 640)
        assert win.player.live_badge.text() == "● CANLI"
    finally:
        win.close()
