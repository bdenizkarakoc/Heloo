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
        win._on_key("dblclick", [])
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
        win._cursor_pos = lambda: win.frameGeometry().center()   # fare küçük ekranın üstünde: düğmeler görünür
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
        # mini oynatıcının kendi düğmeleri: 10 sn ileri/geri, durdur/sürdür, ses, büyüt
        bar = win.player.pip_bar
        assert not bar.isHidden() and win.player.bar.isHidden()
        scr = win.screen().availableGeometry()
        assert win.y() <= scr.top() + 60                       # ekranın üstünde
        p4 = pos()
        win.player.pip_fwd.click()
        assert pump(3, lambda: abs(pos() - (p4 + 10)) < 1.5), (p4, pos())
        win.player.pip_back.click()
        assert pump(3, lambda: abs(pos() - p4) < 1.5)
        was = real_get("pause")
        win.player.pip_pause.click()
        assert real_get("pause") is (not was)
        v0 = float(real_get("volume"))
        win.player.pip_vol_down.click()
        assert float(real_get("volume")) == v0 - 10 and win.player.pip_vol_label.text() == f"%{int(v0 - 10)}"
        win.player.pip_vol_up.click()
        assert float(real_get("volume")) == v0
        win.player.pip_expand.click()                        # ⤢: normal pencereye dön
        assert not win._pip and not win._pip_top_timer.isActive()
        assert bar.isHidden() and not win.player.bar.isHidden()
        # tek tık ANINDA uygulanır (bekleme yok)
        mouse["x"] = 256
        was = real_get("pause")
        win._on_key("click", [])
        assert real_get("pause") is (not was)
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


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_mouse_poll_and_keys_work_without_mpv_input(tmp_path, monkeypatch):
    """mpv'nin gömülü penceresi tıklamayı/tuşu iletmese de: fare durumu yoklanarak videoya tıklama (sağ: ileri,
    sol: geri, orta: durdur, çift tık: tam ekran) ve odak Qt'deyken → ← Boşluk J K L tuşları çalışır."""
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    vid = tmp_path / "film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:d=240",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", str(vid)], check=True)
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.resize(1280, 720)
    win.show()
    eng = MpvEngine(s, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d), extra_options={"ao": "null"})
    eng.start()
    win.engine = eng
    get = eng._get

    def pump(sec, until=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())

    def pos():
        return float(get("time-pos") or 0)

    clock = [50.0]

    def click(frac, gap=1.0):
        """Video alanının yatayda `frac` oranındaki noktasına bas-bırak (fare yoklaması)."""
        host = win.player.host
        g = host.mapToGlobal(QPoint(int(host.width() * frac), host.height() // 2))
        clock[0] += gap
        win._mouse_poll(True, g, clock[0])
        win._mouse_poll(False, g, clock[0] + 0.08)
    try:
        win.play_file(str(vid))
        assert pump(10, lambda: pos() > 0.3 and not win.player.loading)
        eng.seek_abs(60)
        assert pump(5, lambda: abs(pos() - 60) < 1.5)
        eng._set("pause", "yes")
        p0 = pos()
        click(0.9)                                         # sağ: 5 sn ileri
        assert pump(3, lambda: abs(pos() - (p0 + 5)) < 1.5), (p0, pos())
        click(0.1)                                         # sol: 5 sn geri
        assert pump(3, lambda: abs(pos() - p0) < 1.5)
        click(0.5)                                         # orta: sürdür
        assert get("pause") is False
        click(0.5)
        assert get("pause") is True
        # sürükleme tıklama sayılmaz; video dışı (alt çubuk) tıklaması sayılmaz
        host = win.player.host
        a = host.mapToGlobal(QPoint(50, 50))
        win._mouse_poll(True, a, 100.0)
        win._mouse_poll(False, a + QPoint(200, 0), 100.1)
        b = win.player.bar.mapToGlobal(QPoint(20, 20))
        win._mouse_poll(True, b, 101.0)
        win._mouse_poll(False, b, 101.05)
        assert get("pause") is True and abs(pos() - p0) < 1.5
        # çift tık: tam ekran, video durumu değişmez
        monkeypatch.setattr(win, "showFullScreen", lambda: None)
        clock[0] = 200.0
        click(0.5, gap=0)
        click(0.5, gap=0.15)
        assert win._fs and get("pause") is True
        win._set_fullscreen(False)
        # aynı tıklama mpv'den de gelirse bir kez işlenir
        clock[0] = 300.0
        click(0.5)
        state = get("pause")
        win._on_key("click", [])
        assert get("pause") is state
        # klavye: odak listedeyken de → ← Boşluk J K L videoya gider
        focus = [win.live_page.view]                       # başsız ortamda odak bilgisi gelmez: elle ver
        monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: focus[0]))
        monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: win))
        eng._set("pause", "yes")

        def key(k):
            return win._keys_to_player(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
        p1 = pos()
        assert key(Qt.Key_Right) and pump(3, lambda: abs(pos() - (p1 + 5)) < 1.5)
        assert key(Qt.Key_Left) and pump(3, lambda: abs(pos() - p1) < 1.5)
        assert key(Qt.Key_L) and pump(3, lambda: abs(pos() - (p1 + 10)) < 1.5)
        assert key(Qt.Key_J) and pump(3, lambda: abs(pos() - p1) < 1.5)
        assert key(Qt.Key_Space) and get("pause") is False
        assert key(Qt.Key_K) and get("pause") is True
        assert not key(Qt.Key_Up)                          # liste odaktayken ↑↓ listeye kalır
        focus[0] = win.search                              # yazı kutusunda tuşlar yazıya gider
        assert not key(Qt.Key_Space) and not key(Qt.Key_L)
        assert not win._keys_to_player(QKeyEvent(QEvent.KeyPress, Qt.Key_L, Qt.ControlModifier))
    finally:
        win.close()


def test_pip_remembers_place_and_stays_visible(tmp_path, monkeypatch):
    """Mini oynatıcı bırakıldığı yerde (ekran/boyut) yeniden açılır; küçültülse de kendiliğinden geri gelir."""
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    assert s["ui"]["pip_rect"] is None
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.show()
    try:
        scr = win.screen().availableGeometry()
        win._set_pip(True)
        app.processEvents()
        assert win._pip_top_timer.interval() <= 1000
        # kullanıcı sol alta sürükleyip büyütür
        win.setGeometry(scr.left() + 30, scr.bottom() - 330, 400, 300)
        app.processEvents()
        want = [win.geometry().x(), win.geometry().y(), win.geometry().width(), win.geometry().height()]
        assert s["ui"]["pip_rect"] == want
        win._set_pip(False)
        app.processEvents()
        assert s["ui"]["pip_rect"] == want                    # normal pencereye dönmek yeri bozmaz
        win._set_pip(True)
        app.processEvents()
        g = win.geometry()
        assert [g.x(), g.y(), g.width(), g.height()] == want
        # küçültüldü (oyun öne geçti): zamanlayıcı geri açar, yer korunur
        win.showMinimized()
        app.processEvents()
        win._pip_keep_on_top()
        app.processEvents()
        assert not win.isMinimized()
        assert s["ui"]["pip_rect"] == want
        win._set_pip(False)
        # artık olmayan bir ekrandaki yer (monitör çıkarıldı) → varsayılan sağ üst köşe
        s["ui"]["pip_rect"] = [scr.right() + 5000, 0, 400, 300]
        win._set_pip(True)
        app.processEvents()
        assert scr.contains(win.geometry().center())
        assert win.y() <= scr.top() + 60
        s["ui"]["pip_rect"] = ["bozuk"]
        assert win._saved_pip_rect() is None
    finally:
        win.close()


def test_pip_buttons_show_on_hover(tmp_path, monkeypatch):
    """Mini oynatıcıda düğmeler yalnız fare üstündeyken; ayrılınca gizlenir, pencere boyutu değişmez."""
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from helootv.store import Store
    from helootv.ui import main_window as mw
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = mw.MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.show()
    clock = {"t": 1000.0}
    monkeypatch.setattr(mw.time, "monotonic", lambda: clock["t"])
    cursor = {"p": QPoint(-5000, -5000)}
    win._cursor_pos = lambda: cursor["p"]
    try:
        win._set_pip(True)
        app.processEvents()
        bar = win.player.pip_bar
        assert win._pip_bar_timer.isActive() and not bar.isHidden()     # açılışta kısa süre görünür
        win._update_layout()                                              # kanal değişimi: listeler açılmasın
        app.processEvents()
        assert win.pages.isHidden() and win.epg_panel.isHidden() and win.topbar.isHidden()
        size = win.size()
        clock["t"] += 1.0
        win._pip_bar_tick()
        assert not bar.isHidden()
        clock["t"] += 2.0
        win._pip_bar_tick()
        assert bar.isHidden()                                             # fare dışarıda: yalnız video
        app.processEvents()
        assert win.size() == size
        cursor["p"] = win.frameGeometry().center()                       # fare üstüne geldi
        win._pip_bar_tick()
        assert not bar.isHidden()
        clock["t"] += 10
        win._pip_bar_tick()
        assert not bar.isHidden()                                         # üstünde kaldıkça gizlenmez
        cursor["p"] = QPoint(-5000, -5000)
        clock["t"] += 1.0
        win._pip_bar_tick()
        assert not bar.isHidden()
        clock["t"] += 1.0
        win._pip_bar_tick()
        assert bar.isHidden()
        win._set_pip(False)
        assert not win._pip_bar_timer.isActive() and bar.isHidden()
    finally:
        win.close()
