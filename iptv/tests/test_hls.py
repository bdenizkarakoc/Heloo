"""HLS: ana liste ayrıştırma, en iyi kalite seçimi, kalite sabitleme (hızlı açılış) ve güvenli geri dönüş."""
import functools
import http.server
import shutil
import subprocess
import threading
import time

import pytest

from helootv import hls
from helootv import settings as settings_mod
from helootv.player import options as opt

MASTER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.42c01e,mp4a.40.2"
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,FRAME-RATE=50.000,CODECS="avc1.640028,mp4a.40.2"
https://cdn.example/hd/index.m3u8?token=abc
#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=1920x1080,FRAME-RATE=25.000,CODECS="avc1.640028,mp4a.40.2"
hd25/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=12000000,RESOLUTION=3840x2160,CODECS="dvh1.05.06,ec-3"
dv/index.m3u8
"""


def test_parse_and_pick_best():
    variants, separate = hls.parse_master(MASTER)
    assert len(variants) == 4 and not separate
    best = hls.best_variant(variants)
    # Dolby Vision (dvh1) oynatılamaz sayılır; 1080p50 aynı çözünürlükte 25 fps'den önce gelir
    assert best.uri == "https://cdn.example/hd/index.m3u8?token=abc" and best.height == 1080 and best.fps == 50
    _v, separate = hls.parse_master(MASTER + '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="tr",URI="audio/tr.m3u8"\n')
    assert separate
    assert hls.target_duration("#EXTM3U\n#EXT-X-TARGETDURATION:6\n") == 6.0


def test_chase_targets_scale_with_segments():
    s = settings_mod.merged_defaults()
    s["latency"]["mode"] = "balanced"
    assert opt.chase_targets(s) == (3.0, 9.0)
    assert opt.chase_targets(s, 6.0) == (pytest.approx(7.2), pytest.approx(18.0))
    # takılmadan sonra eklenen pay hedefi ve üst sınırı büyütür
    assert opt.chase_targets(s, None, 2.0) == (5.0, 13.0)
    s["latency"]["mode"] = "low"
    assert opt.chase_targets(s) == (1.5, 5.0)


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_resolve_variant_relative_and_separate_audio(tmp_path):
    (tmp_path / "master.m3u8").write_text(MASTER.replace("https://cdn.example/hd/index.m3u8?token=abc",
                                                         "hd/index.m3u8"), encoding="utf-8")
    (tmp_path / "media.m3u8").write_text("#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\na.ts\n", encoding="utf-8")
    (tmp_path / "alt.m3u8").write_text(MASTER + '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="a.m3u8"\n',
                                       encoding="utf-8")
    httpd = _serve(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        url, v = hls.resolve_variant(f"{base}/master.m3u8")
        assert url == f"{base}/hd/index.m3u8" and v.height == 1080
        assert hls.resolve_variant(f"{base}/media.m3u8") == (f"{base}/media.m3u8", None)   # zaten medya listesi
        assert hls.resolve_variant(f"{base}/alt.m3u8")[1] is None                           # ayrı ses izi → dokunma
        assert hls.probe_target_duration(f"{base}/media.m3u8") == 4.0
    finally:
        httpd.shutdown()


def _mpv_ok():
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _mpv_ok() or shutil.which("ffmpeg") is None, reason="libmpv/ffmpeg yok")
def test_engine_pins_best_variant_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    from helootv.player.engine import MpvEngine, PlayRequest
    for name, size in (("low", "640x360"), ("high", "1280x720")):
        d = tmp_path / name
        d.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25", "-f", "lavfi",
                        "-i", "sine=frequency=440", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                        "-c:a", "aac", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
                        str(d / "index.m3u8")], check=True)
    (tmp_path / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\nlow/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\nhigh/index.m3u8\n", encoding="utf-8")
    (tmp_path / "broken.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\nmissing/index.m3u8\n", encoding="utf-8")
    httpd = _serve(tmp_path)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    events = []
    eng = MpvEngine(settings_mod.merged_defaults(), headless=True, on_event=lambda n, d: events.append((n, d)),
                    extra_options={"ao": "null"})
    eng.start()
    try:
        eng.play(PlayRequest(url=f"{base}/master.m3u8", title="HLS", kind="live"))
        deadline = time.time() + 15
        while time.time() < deadline and not (eng.status().get("w") and eng._loaded_at):
            time.sleep(0.1)
        st = eng.status()
        assert eng._pinned_url == f"{base}/high/index.m3u8"
        assert (st["w"], st["h"]) == (1280, 720) and st["hls"]
        deadline = time.time() + 5
        while time.time() < deadline and not eng._hls_td:
            time.sleep(0.1)
        assert eng._hls_td == 2.0
        # sabitlenen kalite adresi açılamazsa (404) özgün adrese döner ve bu kanalda sabitlemeyi bırakır
        events.clear()
        eng.play(PlayRequest(url=f"{base}/broken.m3u8", title="Bozuk", kind="live"))
        deadline = time.time() + 15
        while time.time() < deadline and f"{base}/broken.m3u8" not in eng._no_pin:
            time.sleep(0.1)
        assert f"{base}/broken.m3u8" in eng._no_pin
    finally:
        eng.shutdown()
        httpd.shutdown()
