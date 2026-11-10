"""Kanallar karışmasın: beIN Sports gibi adı birbirine yakın kanallar — her biri kendi yayınını, kendi yayın akışını
ve kendi numarasını göstermeli; hızlı kanal değiştirmede son seçilen kanal açılmalı."""
from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
import time

import pytest

from helootv import catalog
from helootv import settings as settings_mod
from helootv.store import Store, _number_conflict
from helootv.textnorm import match_key

NOW = int(time.time())
H = NOW - NOW % 3600


def _xmltv(path, chans):
    def t(ts):
        return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(ts))
    body = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
    for cid, name in chans:
        body.append(f'<channel id="{cid}"><display-name>{name}</display-name></channel>')
    for cid, name in chans:
        body.append(f'<programme start="{t(H - 3600)}" stop="{t(H + 7200)}" channel="{cid}">'
                    f"<title>{name} canlı maç</title></programme>")
    body.append("</tv>")
    path.write_text("\n".join(body), encoding="utf-8")


def test_match_keys_keep_channel_numbers():
    keys = {n: match_key(n) for n in ("beIN SPORTS 1 HD", "TR: beIN Sports 1 FHD", "beIN SPORTS 1 4K",
                                      "beIN SPORTS 2 HD", "TR | BEIN SPORT 3 HEVC", "beIN SPORTS 3",
                                      "beIN SPORTS MAX 1", "beIN SPORTS HABER")}
    assert keys["beIN SPORTS 1 HD"] == keys["TR: beIN Sports 1 FHD"] == keys["beIN SPORTS 1 4K"] == "beinsports1"
    assert keys["beIN SPORTS 2 HD"] == "beinsports2"
    assert keys["TR | BEIN SPORT 3 HEVC"] == keys["beIN SPORTS 3"] == "beinsports3"      # "SPORT" = "Sports"
    assert len({keys["beIN SPORTS 1 HD"], keys["beIN SPORTS 2 HD"], keys["beIN SPORTS 3"],
                keys["beIN SPORTS MAX 1"], keys["beIN SPORTS HABER"]}) == 5
    assert _number_conflict("beinsports2", {"beinsports1"})
    assert not _number_conflict("beinsports2", {"beinsports2", "beinsports2tr"})
    assert not _number_conflict("beinsportshaber", {"beinsports1"})      # numarasız adda karar verilmez


def test_bein_channels_get_their_own_stream_and_epg(tmp_path):
    # sağlayıcı hataları: beIN 2'ye beIN 1'in tvg-id'si verilmiş, beIN 3 "SPORT" yazılmış ve kimliksiz,
    # beIN 4'ün kimliği doğru, beIN 1 aynı adresle iki grupta, beIN 5'in yayın akışı yok
    m3u = tmp_path / "liste.m3u"
    rows = [("beinsports1.tr", "Spor", "beIN SPORTS 1 HD", "http://p/live/u/p/101.ts"),
            ("beinsports1.tr", "Spor", "beIN SPORTS 2 HD", "http://p/live/u/p/102.ts"),
            ("", "Spor", "TR | BEIN SPORT 3 HEVC", "http://p/live/u/p/103.ts"),
            ("beinsports4.tr", "Spor", "beIN SPORTS 4 HD", "http://p/live/u/p/104.ts"),
            ("beinsports1.tr", "Spor", "beIN SPORTS 5 HD", "http://p/live/u/p/105.ts"),
            ("beinsports1.tr", "beIN", "beIN SPORTS 1 HD", "http://p/live/u/p/101.ts")]
    m3u.write_text("#EXTM3U\n" + "".join(f'#EXTINF:-1 tvg-id="{i}" group-title="{g}",{n}\n{u}\n'
                                         for i, g, n, u in rows), encoding="utf-8")
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Test", kind="m3u", url=str(m3u))
    s = settings_mod.merged_defaults()
    catalog.refresh_source(store, store.get_source(sid), s)
    guide = tmp_path / "epg.xml"
    _xmltv(guide, [(f"beinsports{i}.tr", f"beIN SPORTS {i}") for i in range(1, 5)])
    store.update_source(sid, epg_url=str(guide))
    catalog.refresh_epg(store, store.get_source(sid), s)
    live = {it.name: it for it in store.items("live")}
    # her kanal kendi adresi ve kimliği
    names = ["beIN SPORTS 1 HD", "beIN SPORTS 2 HD", "TR | BEIN SPORT 3 HEVC", "beIN SPORTS 4 HD",
             "beIN SPORTS 5 HD"]
    urls = [catalog.play_url(store, live[n], s, store.get_source(sid)) for n in names]
    assert urls == [f"http://p/live/u/p/10{i}.ts" for i in range(1, 6)]
    assert len({live[n].item_id for n in names}) == 5
    # her kanal kendi yayın akışı: yanlış kimlik düzeltildi, eksik eşleşti, karşılığı olmayan boş kaldı
    epg_of = {n: live[n].epg_id for n in names}
    assert epg_of == {"beIN SPORTS 1 HD": "beinsports1.tr", "beIN SPORTS 2 HD": "beinsports2.tr",
                      "TR | BEIN SPORT 3 HEVC": "beinsports3.tr", "beIN SPORTS 4 HD": "beinsports4.tr",
                      "beIN SPORTS 5 HD": ""}
    nn = store.epg_now_next([(sid, e) for e in epg_of.values() if e])
    titles = {n: (nn.get((sid, e)) or (None, None))[0] for n, e in epg_of.items() if e}
    assert {n: t["title"] for n, t in titles.items()} == {
        "beIN SPORTS 1 HD": "beIN SPORTS 1 canlı maç", "beIN SPORTS 2 HD": "beIN SPORTS 2 canlı maç",
        "TR | BEIN SPORT 3 HEVC": "beIN SPORTS 3 canlı maç", "beIN SPORTS 4 HD": "beIN SPORTS 4 canlı maç"}


def test_channel_numbers_are_stable():
    pytest.importorskip("PySide6")
    from helootv.store import Item
    from helootv.ui.lists import ItemModel

    def it(num, name):
        return Item(1, "live", name, num, name, "", "", "", "", "", None, "", 0, 0, 0, "")
    m = ItemModel()
    m.set_items([it(301, "beIN SPORTS 1"), it(302, "beIN SPORTS 2"), it(305, "beIN SPORTS 5")])
    # sağlayıcı numaraları tekrarsız → onlar gösterilir ve tuşla onlar açılır (kategori değişse de aynı)
    assert m.provider_numbers and [m.number_of(r) for r in range(3)] == [301, 302, 305]
    assert m.row_for_number(305) == 2 and m.row_for_number(3) == -1
    # tekrarlı/eksik numara → sıra numarası
    m.set_items([it(1, "A"), it(1, "B"), it(0, "C")])
    assert not m.provider_numbers and [m.number_of(r) for r in range(3)] == [1, 2, 3]
    assert m.row_for_number(2) == 1 and m.row_for_number(9) == -1


def _mpv_ok() -> bool:
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_fast_zapping_plays_the_last_chosen_channel(tmp_path):
    """Her beIN kanalı farklı çözünürlükte bir HLS yayını; ana liste çözümü kanal başına farklı sürer (yavaş sunucu).
    Hızla 1→2→3→4 geçilince ekranda 4. kanal olmalı (geç biten çözüm eski kanalı açmamalı); sonra her kanal tek tek
    kendi yayınını açmalı."""
    from helootv.player.engine import MpvEngine, PlayRequest
    from helootv import hls as hls_mod
    www = tmp_path / "www"
    sizes = {1: (640, 360), 2: (480, 270), 3: (320, 180), 4: (800, 450)}
    for i, (w, h) in sizes.items():
        d = www / f"bein{i}"
        d.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25", "-t", "8",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-f", "hls", "-hls_time", "2",
                        "-hls_list_size", "0", str(d / "v.m3u8")], check=True)
        (d / "master.m3u8").write_text(f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION={w}x{h}\nv.m3u8\n",
                                       encoding="utf-8")
    httpd = _serve(www)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    delay = {1: 1.5, 2: 1.0, 3: 0.5, 4: 0.0}       # önce seçilen kanalın çözümü en geç biter
    real = hls_mod.resolve_variant

    def slow(url, *a, **k):
        n = int(url.split("/bein")[1][0])
        time.sleep(delay[n])
        return real(url, *a, **k)

    s = settings_mod.merged_defaults()
    eng = MpvEngine(s, headless=True, extra_options={"ao": "null"})
    eng.start()
    eng.resolver = slow
    try:
        def req(i):
            return PlayRequest(url=f"{base}/bein{i}/master.m3u8", title=f"beIN SPORTS {i}", kind="live")

        def wait_size(want, sec=15):
            end = time.time() + sec
            while time.time() < end:
                st = eng.tick() or {}
                if (st.get("w"), st.get("h")) == want:
                    return True
                time.sleep(0.1)
            return False

        for i in (1, 2, 3, 4):
            eng.play(req(i))
            time.sleep(0.15)
        assert wait_size(sizes[4]), "hızlı geçişte son kanal açılmadı"
        time.sleep(2.0)                              # geç biten eski çözümler hiçbir şeyi değiştirmemeli
        st = eng.tick()
        assert (st["w"], st["h"]) == sizes[4] and eng.request.title == "beIN SPORTS 4"
        for i in (2, 1, 3):                           # tek tek: her kanal kendi yayını (önbellekten de)
            eng.play(req(i))
            assert wait_size(sizes[i]), f"beIN SPORTS {i} yanlış yayın açtı"
            assert eng.status()["title"] == f"beIN SPORTS {i}"
    finally:
        eng.shutdown()
        httpd.shutdown()


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_session_redirect_panel_does_not_show_old_channel(tmp_path):
    """Bazı Xtream panelleri: /live/u/p/N.m3u8 → 302 → /hls/oturum/index.m3u8 (kanala değil OTURUMA bağlı adres).
    Oturum adresi, o oturumda en son istenen kanalı yayınlar. Bu adres önbellekten yeniden kullanılırsa 1→2→1 geçişinde
    ekranda 2 (eski kanal) kalırdı. Doğru davranış: her geçişte ana adres yeniden istenir → doğru kanal."""
    from helootv.player.engine import MpvEngine, PlayRequest
    www = tmp_path / "www"
    sizes = {1: (640, 360), 2: (320, 180)}
    for i, (w, h) in sizes.items():
        d = www / f"ch{i}"
        d.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25", "-t", "8",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-f", "hls", "-hls_time", "2",
                        "-hls_list_size", "0", "-hls_base_url", f"/ch{i}/", str(d / "v.m3u8")], check=True)
    state = {"current": 1}

    class Panel(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/live/"):
                state["current"] = int(self.path.split("/")[-1].split(".")[0])
                self.send_response(302)
                self.send_header("Location", "/hls/session/index.m3u8")
                self.end_headers()
                return
            if self.path.startswith("/hls/session/"):
                w, h = sizes[state["current"]]
                if self.path.endswith("chunks.m3u8"):     # oturumun kalite listesi: şu anki kanalın parçaları
                    body = (www / f"ch{state['current']}" / "v.m3u8").read_bytes()
                else:
                    body = (f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION={w}x{h}\n"
                            "chunks.m3u8\n").encode()
                if self.path.endswith(".m3u8"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            return super().do_GET()

    handler = functools.partial(Panel, directory=str(www))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    eng = MpvEngine(settings_mod.merged_defaults(), headless=True, extra_options={"ao": "null"})
    eng.start()
    try:
        def play(i):
            eng.play(PlayRequest(url=f"{base}/live/u/p/{i}.m3u8", title=f"Kanal {i}", kind="live"))
            end = time.time() + 15
            while time.time() < end:
                st = eng.tick() or {}
                if st.get("w"):
                    return (st["w"], st["h"])
                time.sleep(0.1)
            return None

        assert play(1) == sizes[1]
        assert play(2) == sizes[2]
        assert play(1) == sizes[1], "eski kanal (2) gösterildi"
    finally:
        eng.shutdown()
        httpd.shutdown()


@pytest.mark.skipif(not _mpv_ok(), reason="libmpv yok")
def test_ui_hides_old_picture_until_new_channel_plays(tmp_path, monkeypatch):
    """Kanal değişince eski kanalın görüntüsü kalmaz: 'Açılıyor: <kanal>' ekranı, yeni yayının ilk karesiyle video."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    m3u = tmp_path / "k.m3u"
    m3u.write_text("#EXTM3U\n" + "".join(
        f'#EXTINF:-1 group-title="Spor",beIN SPORTS {i}\nav://lavfi:testsrc2=size={w}x{h}:rate=25,realtime\n'
        for i, (w, h) in ((1, (640, 360)), (2, (320, 180)))), encoding="utf-8")
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

    def pump(sec, until):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until():
                return True
            time.sleep(0.02)
        return until()
    try:
        assert pump(5, lambda: len(win.live_page.model.items) == 2)
        ch1, ch2 = win.live_page.model.items
        win.play_live(ch1)
        assert win.player.loading and "beIN SPORTS 1" in win.player.placeholder.title.text()
        assert pump(10, lambda: not win.player.loading)                 # ilk kare geldi → video
        assert pump(5, lambda: (eng.status().get("w"), eng.status().get("h")) == (640, 360))
        win.play_live(ch2)
        # geçişte eski kanalın karesi değil bekleme ekranı görünür
        assert win.player.loading and "beIN SPORTS 2" in win.player.placeholder.title.text()
        assert pump(10, lambda: not win.player.loading)
        assert (eng.status()["w"], eng.status()["h"]) == (320, 180) and win.player.title.text() == "beIN SPORTS 2"
    finally:
        win.close()


@pytest.mark.skipif(not _mpv_ok(), reason="libmpv yok")
def test_beIN1_stays_on_beIN1(tmp_path, monkeypatch):
    """beIN SPORTS 1 açıldıktan sonra kendiliğinden başka kanala geçmemeli: ↑/↓ (ses), medya tuşları, takılma
    sonrası yeniden açma ve 20 sn oynatma boyunca kanal ve görüntü aynı kalır; kanal değişirse sebebi kaydedilir."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    m3u = tmp_path / "k.m3u"
    chans = [("beIN SPORTS 1 HD", 640, 360), ("beIN SPORTS 2 HD", 480, 270), ("beIN SPORTS 3 HD", 320, 180)]
    m3u.write_text("#EXTM3U\n" + "".join(f'#EXTINF:-1 group-title="Spor",{n}\nav://lavfi:testsrc2=size={w}x{h}:rate=25,realtime\n'
                                         for n, w, h in chans), encoding="utf-8")
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

    def pump(sec, until=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())

    def on_bein1():
        st = eng.status()
        return win.current_item.name == "beIN SPORTS 1 HD" and (st.get("w"), st.get("h")) == (640, 360)
    try:
        assert pump(5, lambda: len(win.live_page.model.items) == 3)
        bein1 = win.live_page.model.items[0]
        win.play_live(bein1)
        assert pump(10, on_bein1)
        vol = float(eng._get("volume"))
        for action in ("down", "down", "up", "next", "prev"):        # ses tuşları ve medya tuşları
            win._on_key(action, [])
            pump(0.3)
            assert on_bein1(), action
        assert float(eng._get("volume")) == vol - 5
        eng._schedule_retry(0.05)                                    # takılma sonrası yeniden açma
        pump(3)
        assert pump(10, on_bein1)
        end = time.time() + 20                                       # 20 sn izle: hep beIN 1
        while time.time() < end:
            pump(0.5)
            assert on_bein1()
        assert [e[2] for e in win.switch_log] == ["beIN SPORTS 1 HD"]
        # ayardan ok tuşları kanal değiştirsin: değişir ve sebebi kaydedilir
        s["controls"]["arrow_keys"] = "channel"
        win._on_key("down", [])
        assert pump(10, lambda: win.current_item.name == "beIN SPORTS 2 HD")
        assert win.switch_log[-1][1:] == ("beIN SPORTS 1 HD", "beIN SPORTS 2 HD", "↓ tuşu")
        s["controls"]["media_keys_zap"] = True
        win._on_key("next", [])
        assert pump(10, lambda: win.current_item.name == "beIN SPORTS 3 HD")
        assert win.switch_log[-1][3] == "medya tuşu"
    finally:
        win.close()


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_playlist_url_does_not_advance_to_other_stream(tmp_path):
    """Sağlayıcı kanal adresi olarak birden çok öğeli bir oynatma listesi verirse ilk öğe bitince mpv listedeki BAŞKA
    yayına geçerdi ("başka programa geçiyor"). Aynı kanal yeniden açılmalı."""
    from helootv.player.engine import MpvEngine, PlayRequest
    www = tmp_path / "www"
    www.mkdir()
    for name, (w, h), dur in (("kanal", (640, 360), 3), ("baska", (320, 180), 30)):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25", "-t", str(dur),
                        "-c:v", "libx264", "-preset", "ultrafast", "-f", "mpegts", str(www / f"{name}.ts")], check=True)
    httpd = _serve(www)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    (www / "bein1.m3u").write_text(f"#EXTM3U\n#EXTINF:-1,beIN 1\n{base}/kanal.ts\n#EXTINF:-1,Başka\n{base}/baska.ts\n",
                                   encoding="utf-8")
    eng = MpvEngine(settings_mod.merged_defaults(), headless=True, extra_options={"ao": "null"})
    eng.start()
    try:
        eng.play(PlayRequest(url=f"{base}/bein1.m3u", title="beIN SPORTS 1", kind="live"))
        seen, late = set(), set()
        t0 = time.time()
        while time.time() - t0 < 14:                 # ilk öğe 3 sn; bitince aynı kanal yeniden açılmalı
            st = eng.tick() or {}
            if st.get("w"):
                seen.add((st["w"], st["h"]))
                if time.time() - t0 > 7:
                    late.add((st["w"], st["h"]))
            time.sleep(0.1)
        assert seen == {(640, 360)}, seen            # başka yayına geçmedi
        assert late == {(640, 360)}, "kanal bitince durdu, yeniden açılmadı"
    finally:
        eng.shutdown()
        httpd.shutdown()


@pytest.mark.skipif(not (_mpv_ok() and shutil.which("ffmpeg")), reason="libmpv/ffmpeg yok")
def test_failing_channel_does_not_jump_to_other_channels(tmp_path):
    """beIN 1 geçici olarak hata verince (sunucu 404/kopma) listedeki diğer kanallara ATLAMAMALI; beIN 1 yeniden
    denenip düzelince beIN 1'den devam etmeli."""
    from helootv.player.engine import MpvEngine, PlayRequest
    www = tmp_path / "www"
    www.mkdir()
    for name, (w, h) in (("bein1", (640, 360)), ("bein2", (480, 270)), ("bein3", (320, 180))):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25", "-t", "30",
                        "-c:v", "libx264", "-preset", "ultrafast", "-f", "mpegts", str(www / f"{name}.ts")], check=True)
    fails = {"left": 2}

    class Flaky(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/bein1.ts") and fails["left"] > 0:
                fails["left"] -= 1
                self.send_error(404)                   # beIN 1 geçici sorun
                return
            return super().do_GET()

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Flaky, directory=str(www)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    (www / "liste.m3u").write_text("#EXTM3U\n" + "".join(f"#EXTINF:-1,beIN {i}\n{base}/bein{i}.ts\n" for i in (1, 2, 3)),
                                   encoding="utf-8")
    eng = MpvEngine(settings_mod.merged_defaults(), headless=True, extra_options={"ao": "null"})
    eng.start()
    try:
        eng.play(PlayRequest(url=f"{base}/liste.m3u", title="beIN SPORTS 1", kind="live"))
        seen = set()
        t0 = time.time()
        while time.time() - t0 < 15:
            st = eng.tick() or {}
            if st.get("w"):
                seen.add((st["w"], st["h"]))
            time.sleep(0.1)
        assert (480, 270) not in seen and (320, 180) not in seen, f"başka kanala atladı: {seen}"
        assert seen == {(640, 360)}, "beIN 1 düzelince yeniden açılmadı"
    finally:
        eng.shutdown()
        httpd.shutdown()
