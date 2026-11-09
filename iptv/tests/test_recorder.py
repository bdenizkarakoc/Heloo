"""Kayıt (DVR), zamanlanmış kayıt ve hatırlatıcılar."""
from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
import time

import pytest

from helootv import recorder


def test_ffmpeg_args_copy_headers_reconnect(tmp_path):
    args = recorder.ffmpeg_args("ffmpeg", "http://x/live/1.ts", tmp_path / "a.ts",
                                {"user_agent": "UA/1", "referrer": "https://r", "extra": {"X-Token": "t"}}, 120)
    j = " ".join(args)
    assert "-c copy" in j and "-f mpegts" in j and "-t 120" in j and "-user_agent UA/1" in j
    assert "Referer: https://r\r\nX-Token: t\r\n" in args[args.index("-headers") + 1]
    assert "-reconnect_streamed" in args
    assert "-reconnect" not in recorder.ffmpeg_args("ffmpeg", "udp://239.1.1.1:1234", tmp_path / "b.ts")
    assert recorder.safe_name('Maç: A/B "canlı"?') == "Maç A B canlı"


def test_scheduler_due_missed_and_dedupe(tmp_path):
    sch = recorder.Scheduler(tmp_path / "schedule.json")
    now = 1_000_000.0
    prog = {"start": now + 600, "stop": now + 3600, "title": "Haberler"}
    a = sch.add("record", prog, "Kanal 1", (1, "live", "5"), "http://x/5.ts", {"user_agent": "UA"})
    assert sch.add("record", prog, "Kanal 1", (1, "live", "5")) is a          # aynı program iki kez eklenmez
    r = sch.add("remind", prog, "Kanal 1", (1, "live", "5"))
    old = sch.add("record", {"start": now - 7200, "stop": now - 3600, "title": "Eski"}, "K", (1, "live", "6"))
    assert sch.due(now) == [] and old.state == "missed"
    due = sch.due(now + 560)                                                   # 1 dk önce başlar
    assert {j.id for j in due} == {a.id, r.id}
    assert recorder.Scheduler.record_duration(a, now + 560) == pytest.approx(3600 + 120 - 560)
    sch.mark(a, "running")
    again = recorder.Scheduler(tmp_path / "schedule.json")                     # diske yazıldı
    assert [j.state for j in again.jobs if j.id == a.id] == ["running"]
    assert sch.find("remind", (1, "live", "5"), prog["start"]).id == r.id
    sch.remove(r.id)
    assert sch.find("remind", (1, "live", "5"), prog["start"]) is None
    assert "Kanal 1 — Haberler" in a.label()


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")
def test_real_recording_and_stop(tmp_path):
    src = tmp_path / "www"
    src.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi",
                    "-i", "sine", "-t", "20", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-f", "mpegts", str(src / "live.ts")], check=True)
    httpd = _serve(src)
    try:
        rec = recorder.Recorder(ffmpeg=shutil.which("ffmpeg"), folder=tmp_path / "kayit")
        url = f"http://127.0.0.1:{httpd.server_address[1]}/live.ts"
        # süreli kayıt (zamanlanmış kayıt gibi) kendiliğinden biter
        timed = rec.start(url, "Test: Kanal 1", {"user_agent": "UA"}, duration=3)
        assert rec.recording_url(url) is timed
        deadline = time.time() + 20
        while timed.running and time.time() < deadline:
            time.sleep(0.2)
        done = rec.reap()
        assert done and done[0][0].id == timed.id and done[0][1] == ""
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                               "-of", "csv=p=0", timed.path], capture_output=True, text=True).stdout
        assert "video" in info and "audio" in info
        # elle durdurma: dosya yine geçerli MPEG-TS
        live = rec.start(url, "Test: Kanal 1", duration=None)
        time.sleep(1.5)
        stopped = rec.stop(live.id)
        assert stopped and not stopped.running and stopped.size() > 10_000 and live.path != timed.path
        assert rec.active == {}
    finally:
        httpd.shutdown()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")
def test_ui_record_button_and_pip(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv import settings as settings_mod
    from helootv.player.engine import PlayRequest
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    src = tmp_path / "www"
    src.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-f", "mpegts", str(src / "k.ts")], check=True)
    httpd = _serve(src)
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["record"]["folder"] = str(tmp_path / "kayit")
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), s, headless=True)
    win.recorder.ffmpeg = shutil.which("ffmpeg")
    win.resize(1200, 800)
    win.show()
    try:
        win.current_req = PlayRequest(url=f"http://127.0.0.1:{httpd.server_address[1]}/k.ts", title="Kanal 7",
                                      kind="live")
        win.toggle_record()
        assert win._rec_current in win.recorder.active and "⏺ 0:00" == win.player.btn_rec.text()
        time.sleep(1.2)
        win.toggle_record()
        assert win._rec_current is None and win.player.btn_rec.text() == "⏺"
        files = list((tmp_path / "kayit").glob("Kanal 7 - *.ts"))
        assert files and files[0].stat().st_size > 0
        # dosya/fotoğraf kaydedilmez
        win.current_req = PlayRequest(url="/a.mp4", title="a", kind="file")
        win.toggle_record()
        assert win._rec_current is None
        # resim içinde resim: yalnız video, küçük pencere; Esc ile geri
        win._set_pip(True)
        app.processEvents()
        assert win._pip and win.player.bar.isHidden() and win.topbar.isHidden() and win.width() <= 600
        win._on_key("esc", [])
        app.processEvents()
        assert not win._pip and not win.player.bar.isHidden() and not win.topbar.isHidden()
    finally:
        win.recorder.stop_all()
        win.close()
        httpd.shutdown()


def test_tv_guide_grid(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from helootv import catalog
    from helootv import settings as settings_mod
    from helootv.store import Store
    from helootv.ui.guide import CH_W, HEAD_H, ROW_H
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    m3u = tmp_path / "k.m3u"
    m3u.write_text("#EXTM3U\n" + "".join(
        f'#EXTINF:-1 tvg-id="k{i}" tvg-rec="3" group-title="Ulusal",Kanal {i}\nhttp://127.0.0.1:9/k{i}.ts\n'
        for i in range(1, 4)), encoding="utf-8")
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Test", kind="m3u", url=str(m3u))
    s = settings_mod.merged_defaults()
    s["ui"]["resume_last_channel"] = False
    s["ui"]["auto_refresh_hours"] = 0
    catalog.refresh_source(store, store.get_source(sid), s)
    now = int(time.time())
    base = now - now % 3600
    with store.epg_transaction() as c:
        for i in (1, 2):
            for h in range(-3, 6):
                c.execute("INSERT INTO epg(source_id, channel, start, stop, title, descr) VALUES (?,?,?,?,?,?)",
                          (sid, f"k{i}", base + h * 3600, base + (h + 1) * 3600, f"Program {i}/{h}", "açıklama"))
    grid = store.epg_grid([(sid, "k1"), (sid, "k2"), (sid, "k3")], now - 7200, now + 7200)
    assert len(grid[(sid, "k1")]) == 5 and (sid, "k3") not in grid
    win = MainWindow(store, s, headless=True)
    win.show()

    def pump(sec, until):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until():
                return True
            time.sleep(0.02)
        return until()

    assert pump(5, lambda: len(win.live_page.model.items) == 3)
    win.open_guide()
    g = win._guide
    assert pump(5, lambda: len(g.canvas.items) == 3 and g.canvas.progs)
    assert "2 kanalın yayın akışı var" in g.info.text()
    played, caught, remind = [], [], []
    g.play_live.disconnect()
    g.catchup.disconnect()
    g.remind.disconnect()
    g.play_live.connect(lambda it: played.append(it.name))
    g.catchup.connect(lambda it, p: caught.append(p["title"]))
    g.remind.connect(lambda it, p: remind.append(p["title"]))
    c = g.canvas
    y = HEAD_H + ROW_H // 2                       # 1. kanal satırı
    item, prog, _ = c.hit(QPoint(c.x_of(now) + 1, y))
    assert item.name == "Kanal 1" and prog["title"] == "Program 1/0"
    g._activated(item, prog)                      # şimdi → kanalı aç
    _, past, _ = c.hit(QPoint(c.x_of(now - 7000), y))
    g._activated(item, past)                      # geçmiş + arşiv → geri izle
    _, fut, _ = c.hit(QPoint(c.x_of(now + 7300), y))
    g._activated(item, fut)                       # gelecek → hatırlat
    assert played == ["Kanal 1"] and caught == ["Program 1/-2"] and remind == ["Program 1/2"]
    assert c.hit(QPoint(CH_W // 2, y))[1] is None  # kanal sütunu
    c.repaint()                                   # çizim hatasız
    g.grab().save(str(tmp_path / "rehber.png"))
    # gerçek bağlantı: rehberden hatırlatıcı → zamanlayıcıda ve işaretli
    g.remind.disconnect()
    g.remind.connect(win.schedule_reminder)
    g.remind.emit(item, fut)
    assert win.scheduler.find("remind", item.key, fut["start"]) and c.marks(item, fut) == "🔔 "
    g.close()
    win.close()


def test_parental_pin(tmp_path, monkeypatch):
    from helootv import parental
    h = parental.hash_pin("1234")
    assert parental.verify_pin("1234", h) and not parental.verify_pin("4321", h)
    assert "1234" not in h and parental.hash_pin("1234") != h          # tuzlu
    assert not parental.verify_pin("1234", "bozuk")
    assert parental.valid_pin("0042") and not parental.valid_pin("12") and not parental.valid_pin("12ab")
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from helootv import settings as settings_mod
    from helootv.store import Store
    from helootv.ui.context import AppContext
    from helootv.ui.images import ImageLoader
    from helootv.ui.settings_page import SettingsPage
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    s = settings_mod.merged_defaults()
    page = SettingsPage(AppContext(Store(tmp_path / "s.db"), s, ImageLoader()))
    answers = []
    page.ask_pin = lambda *a: answers.pop(0)
    answers[:] = ["2468", "2468"]                  # PIN belirle
    page._pin_dialog()
    assert parental.verify_pin("2468", s["ui"]["pin_hash"]) and s["ui"]["hide_adult"] is True
    answers[:] = ["0000"]                          # yanlış PIN: yetişkin içerik açılmaz
    page.hide_adult.setChecked(False)
    assert s["ui"]["hide_adult"] is True and page.hide_adult.isChecked()
    answers[:] = ["2468"]                          # doğru PIN
    page.hide_adult.setChecked(False)
    assert s["ui"]["hide_adult"] is False
    answers[:] = ["9999"]                          # kaldırmak için eski PIN yanlış → değişmez
    page._pin_dialog()
    assert s["ui"]["pin_hash"]
    answers[:] = ["2468", ""]                      # doğru PIN + boş → kilit kalkar
    page._pin_dialog()
    assert s["ui"]["pin_hash"] == ""
