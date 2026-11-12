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


@pytest.mark.skipif(not _mpv_ok(), reason="libmpv/PySide6 yok")
def test_fullscreen_bar_settings_close_and_flash(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine, PlayRequest
    from helootv.store import Store
    from helootv.ui import main_window as mw
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = mw.MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.resize(1280, 720)
    win.show()
    app.processEvents()
    clock = [1000.0]
    monkeypatch.setattr(mw.time, "monotonic", lambda: clock[0])
    try:
        # --- tam ekranda alt çubuk: fare alta gelince görünür, ayrılınca 2,5 sn sonra gizlenir
        win.current_req = PlayRequest(url="x", title="Film", kind="movie")
        monkeypatch.setattr(win, "showFullScreen", lambda: None)
        win._set_fullscreen(True)
        assert win.player.bar.isHidden() and win._fs_bar_timer.isActive()
        mouse = [QPoint(600, 100)]
        win._cursor_pos = lambda: win.mapToGlobal(mouse[0])
        win._fs_bar_tick()
        assert win.player.bar.isHidden()
        mouse[0] = QPoint(600, win.height() - 10)
        win._fs_bar_tick()
        assert not win.player.bar.isHidden()
        mouse[0] = QPoint(600, 100)
        clock[0] += 1
        win._fs_bar_tick()
        assert not win.player.bar.isHidden()               # hemen kaybolmaz
        clock[0] += 3
        win._fs_bar_tick()
        assert win.player.bar.isHidden()
        win._set_fullscreen(False)
        assert not win._fs_bar_timer.isActive() and not win.player.bar.isHidden()
        win.current_req = None
        # --- ayarlar: sabit ✕ düğmesi, en alta kaydırılsa da yerinde; basınca son sekmeye döner
        win._select_tab(1)                                   # Filmler
        win._select_tab(4)                                   # Ayarlar
        app.processEvents()
        st = win.settings_page
        y0 = st.close_btn.y()
        st.verticalScrollBar().setValue(st.verticalScrollBar().maximum())
        app.processEvents()
        assert st.verticalScrollBar().value() > 0 and st.close_btn.y() == y0 and st.close_btn.isVisible()
        assert st.close_btn.x() + st.close_btn.width() <= st.width()
        st.close_btn.click()
        assert win._tab_key() == "movie"
        win._select_tab(4)
        win._on_key("esc", [])                               # Esc de kapatır
        assert win._tab_key() == "movie"
        # --- büyük ekran simgesi gerçek mpv'de hata vermez
        eng = MpvEngine(s, headless=True, extra_options={"ao": "null"})
        eng.start()
        errors = []
        monkeypatch.setattr(eng, "show_text", lambda *a, **k: errors.append(a))   # yedek yola düşerse hata say
        eng.flash("⏸")
        eng.flash("5 sn ⏩", "right")
        eng.flash("⏪ 5 sn", "left")
        assert errors == []
        eng.shutdown()
    finally:
        win.close()


def test_parse_goto():
    assert opt.parse_goto("45") == 45 * 60
    assert opt.parse_goto("12:30") == 12 * 60 + 30
    assert opt.parse_goto("1:05:00") == 3900
    assert opt.parse_goto(" 1.05.00 ") == 3900
    for bad in ("", "abc", "1:2:3:4", "-5", "1:xx"):
        assert opt.parse_goto(bad) is None


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_goto_arrow_seek_and_pip_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    vid = tmp_path / "film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:d=240",
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
    try:
        win.play_file(str(vid))
        assert pump(10, lambda: pos() > 0.3)
        eng._set("pause", "yes")
        # istenen dakikaya git: "2" = 2. dakika, "1:30" = 1 dk 30 sn; süreyi aşan değer sona yakın yere gider
        win.goto_time("2")
        assert pump(5, lambda: abs(pos() - 120) < 1.5), pos()
        win.goto_time("1:30")
        assert pump(5, lambda: abs(pos() - 90) < 1.5), pos()
        win.goto_time("bozuk")
        pump(0.3)
        assert abs(pos() - 90) < 1.5
        win.goto_time("30")
        assert pump(5, lambda: pos() > 200), pos()
        win.goto_time("1:00")
        assert pump(5, lambda: abs(pos() - 60) < 1.5)
        # → / ← ok tuşları: ayardaki süre (5 sn)
        p0 = pos()
        win._on_key("right", [])
        assert pump(3, lambda: abs(pos() - (p0 + 5)) < 1.5), (p0, pos())
        p1 = pos()
        win._on_key("left", [])
        assert pump(3, lambda: abs(pos() - (p1 - 5)) < 1.5), (p1, pos())
        # YouTube tuşları: L 10 sn ileri, J 10 sn geri, K durdur/sürdür, Home baştan
        p3 = pos()
        win._on_key("fwd10", [])
        assert pump(3, lambda: abs(pos() - (p3 + 10)) < 1.5), (p3, pos())
        win._on_key("j", [])
        assert pump(3, lambda: abs(pos() - p3) < 1.5)
        win._on_key("live", [])                              # filmde küçük "l" de 10 sn ileri
        assert pump(3, lambda: abs(pos() - (p3 + 10)) < 1.5)
        win._on_key("home", [])
        assert pump(3, lambda: pos() < 1.5)
        win.goto_time("1:00")
        assert pump(5, lambda: abs(pos() - 60) < 1.5)
        # ↑ / ↓: ses
        vol = float(real_get("volume"))
        win._on_key("up", [])
        assert float(real_get("volume")) == vol + 5
        # küçük ekranda (mini oynatıcı) da aynı: sağa tık 5 sn ileri, ortaya tık durdur/sürdür, hep üstte zamanlayıcısı
        win._set_pip(True)
        app.processEvents()
        assert win._pip and win._pip_top_timer.isActive()
        mouse = {"x": 480}
        eng._get = lambda name: ({"x": mouse["x"], "y": 100, "hover": True} if name == "mouse-pos" else
                                 {"w": 512, "h": 288} if name == "osd-dimensions" else real_get(name))
        p2 = pos()
        win._on_key("click", [])
        pump(0.8)
        assert pump(3, lambda: abs(pos() - (p2 + 5)) < 1.5), (p2, pos())
        mouse["x"] = 256
        win._on_key("click", [])
        pump(0.8)
        assert real_get("pause") is False                    # ortaya tık: sürdür
        win._on_key("click", [])
        pump(0.8)
        assert real_get("pause") is True
        win._on_key("esc", [])
        assert not win._pip and not win._pip_top_timer.isActive()
    finally:
        win.close()


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_seek_on_server_without_range_support(tmp_path, monkeypatch):
    """Birçok IPTV sunucusu film adresinde "ortadan başlat"ı (HTTP Range) desteklemez; mpv uzak atlamayı sessizce
    reddederdi ("ileri geri yapamıyorum"). Artık: yakın sarma çalışır, uzak hedef inen en ileri noktaya gider ve
    bildirilir; film arka planda inmeye devam eder."""
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    import functools
    import http.server
    import threading

    from helootv.player.engine import MpvEngine, PlayRequest
    www = tmp_path / "www"
    www.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:d=600", "-c:v",
                    "libx264", "-preset", "ultrafast", "-g", "50", "-b:v", "800k", str(www / "film.mkv")], check=True)

    class NoRange(http.server.SimpleHTTPRequestHandler):       # Range'i yok sayar, yavaş gönderir
        def log_message(self, *a):
            pass

        def copyfile(self, src, dst):
            while True:
                b = src.read(64 * 1024)
                if not b:
                    break
                dst.write(b)
                time.sleep(0.03)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(NoRange, directory=str(www)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    events = []
    eng = MpvEngine(settings_mod.merged_defaults(), headless=True, on_event=lambda n, d: events.append((n, d)),
                    extra_options={"ao": "null"})
    eng.start()

    def pos():
        return float(eng._get("time-pos") or 0)

    def wait(cond, sec=10):
        end = time.time() + sec
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return cond()
    try:
        eng.play(PlayRequest(url=f"http://127.0.0.1:{httpd.server_address[1]}/film.mkv", title="Film", kind="movie"))
        assert wait(lambda: pos() > 2)
        assert eng.linear and any(n == "linear" for n, _ in events)
        eng._set("pause", "yes")
        p0 = pos()
        eng.seek(5)                                            # yakın sarma (inen kısım içinde)
        assert wait(lambda: abs(pos() - (p0 + 5)) < 1.5), (p0, pos())
        got = eng.seek_abs(540)                                # 9. dakika: henüz inmedi
        rng = eng.cached_range()
        assert got < 540 and wait(lambda: abs(pos() - got) < 3), (got, pos())
        assert got > p0 + 5 and rng and got <= rng[1]          # inen en ileri noktaya gitti
        clamp = [d for n, d in events if n == "seek-clamped"]
        assert clamp and clamp[-1]["wanted"] == 540
        back = eng.seek_abs(3)                                 # geri: inen kısmın içinde, olduğu gibi
        assert abs(back - 3) < 0.01 and wait(lambda: abs(pos() - 3) < 2.5)
    finally:
        eng.shutdown()
        httpd.shutdown()
