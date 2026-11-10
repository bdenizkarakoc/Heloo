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
