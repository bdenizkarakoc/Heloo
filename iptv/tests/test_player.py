"""Oynatıcı: RTX VSR ölçek planı, gecikme kipleri ve (libmpv varsa) başsız gerçek oynatma testleri."""
import functools
import http.server
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from helootv import settings as settings_mod
from helootv.player import options as opt


def S(**over):
    s = settings_mod.merged_defaults()
    for path, val in over.items():
        sec, key = path.split("__")
        s[sec][key] = val
    return s


# ---------------------------------------------------------------- RTX VSR planı

@pytest.mark.parametrize("w,h,scale,out", [
    (1920, 1080, 2.0, (3840, 2160)),
    (1280, 720, 3.0, (3840, 2160)),
    (720, 576, 3.75, (2700, 2160)),   # anamorfik SD: dw=1024 → 16:9 görüntü 3840×2160
    (640, 360, 6.0, (3840, 2160)),
])
def test_vsr_plan_4k(w, h, scale, out):
    dw = 1024 if (w, h) == (720, 576) else w
    plan = opt.vsr_plan(S(video__vsr_target="2160"), {"w": w, "h": h, "dw": dw, "dh": h}, (2560, 1440),
                        platform="win32")
    assert plan["scale"] == scale and plan["out"] == out
    assert "@helootv:d3d11vpp=" in plan["vf"] and "scaling-mode=nvidia" in plan["vf"]
    # karıncalanma: gürültü azaltma VSR'den önce (otomatik: ≤576p orta, 720p hafif, 1080p kapalı — VSR yeter)
    if h <= 720:
        assert plan["vf"].startswith("@helootv-dn:lavfi=[hqdn3d=") and plan["denoise"]
    else:
        assert plan["denoise"] is None and plan["vf"].startswith("@helootv:d3d11vpp=")
    assert "deint=yes" in plan["vf"] and "interlaced-only=yes" in plan["vf"]
    assert "nvidia-true-hdr" not in plan["vf"]


def test_vsr_plan_variants():
    vp = {"w": 1920, "h": 1080, "dw": 1920, "dh": 1080}
    # sinemaskop: genişlik sınırı (3840) aşılmaz
    wide = opt.vsr_plan(S(), {"w": 1920, "h": 800, "dw": 1920, "dh": 800}, None, "win32")
    assert wide["scale"] == 2.0 and wide["out"] == (3840, 1600)
    # 4K kaynak: büyütme yok, yalnız deinterlace
    uhd = opt.vsr_plan(S(), {"w": 3840, "h": 2160}, None, "win32")
    assert uhd["scale"] is None and "scale=" not in uhd["vf"] and "deint=yes" in uhd["vf"]
    # ekran çözünürlüğü hedefi
    scr = opt.vsr_plan(S(video__vsr_target="screen"), vp, (2560, 1440), "win32")
    assert scr["scale"] == pytest.approx(1.3333, abs=1e-3)
    # RTX HDR yalnız SDR kaynakta
    hdr = opt.vsr_plan(S(video__rtx_hdr=True), vp, None, "win32")
    assert "nvidia-true-hdr=yes" in hdr["vf"]
    hdr_src = opt.vsr_plan(S(video__rtx_hdr=True), dict(vp, gamma="pq"), None, "win32")
    assert "nvidia-true-hdr" not in hdr_src["vf"]
    # kapalı + deinterlace yok → filtre yok
    off = opt.vsr_plan(S(video__rtx_vsr=False, video__deinterlace="no", picture__denoise="off"), vp, None, "win32")
    assert off["vf"] == ""
    # Windows dışı: VSR yok, yalnız gürültü azaltma
    assert opt.vsr_plan(S(picture__denoise="off"), vp, None, "linux")["vf"] == ""
    assert opt.vsr_plan(S(picture__denoise="strong"), vp, None, "linux")["vf"] == "@helootv-dn:lavfi=[hqdn3d=4:3:9:7]"
    # 4K kaynakta otomatik gürültü azaltma kapalı; fotoğrafta hiç yok
    assert opt.vsr_plan(S(), {"w": 3840, "h": 2160}, None, "win32")["denoise"] is None
    assert opt.vsr_plan(S(), vp, None, "win32", kind="image")["denoise"] is None


def test_picture_presets_and_options():
    s = S()
    opt.apply_preset(s, "noisy")
    assert s["picture"]["denoise"] == "strong" and s["picture"]["preset"] == "noisy"
    po = opt.picture_options(s, {"w": 720, "h": 576})
    assert po["deband"] == "yes" and po["deband-iterations"] == "4" and po["contrast"] == "3"
    assert float(po["glsl-shader-opts"].split("=")[1]) > 0.5     # düşük kalite: keskinlik artar
    s["picture"]["deband"] = 0
    assert opt.picture_options(s, {"w": 1920, "h": 1080})["deband"] == "no"
    # kareler yalnız gürültü azaltma gereken kaynakta belleğe kopyalanır; HD'de GPU'da kalır
    assert opt.resolve_hwdec(S(), "win32") == "d3d11va"
    assert opt.resolve_hwdec(S(), "win32", need_copy=True).startswith("d3d11va-copy")
    # RTX VSR büyütürken CAS yarıya iner (VSR zaten keskinleştirir; hale olmasın)
    n = S()
    full = float(opt.picture_options(n, {"w": 1280, "h": 720})["glsl-shader-opts"].split("=")[1])
    half = float(opt.picture_options(n, {"w": 1280, "h": 720}, vsr=True)["glsl-shader-opts"].split("=")[1])
    assert half == pytest.approx(full / 2)


def test_interlaced_denoise_and_migration(tmp_path):
    # geçmeli SD: önce bwdif (alan hızında), sonra hqdn3d; d3d11vpp'de ikinci kez deinterlace yok
    plan = opt.vsr_plan(S(), {"w": 720, "h": 576, "interlaced": True}, (3840, 2160), "win32")
    assert plan["vf"].startswith("@helootv-dn:lavfi=[bwdif=mode=send_field:deint=interlaced,hqdn3d=")
    assert "deint=yes" not in plan["vf"] and plan["deint"] and "scaling-mode=nvidia" in plan["vf"]
    # 1080i: gürültü azaltma yok → GPU deinterlace
    hd = opt.vsr_plan(S(), {"w": 1920, "h": 1080, "interlaced": True}, (3840, 2160), "win32")
    assert hd["denoise"] is None and "deint=yes" in hd["vf"]
    # ekran hedefi: 1080p ekranda 1080p kaynak büyütülmez (4K üretip geri küçültme yok)
    assert opt.vsr_plan(S(), {"w": 1920, "h": 1080}, (1920, 1080), "win32")["scale"] is None
    assert opt.vsr_plan(S(), {"w": 1280, "h": 720}, (1920, 1080), "win32")["scale"] == 1.5
    # eski ayar dosyası: varsayılan 4K hedefi ekran hedefine taşınır, diğer seçimler korunur
    import json
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"video": {"vsr_target": "2160", "sharpen": "strong"}}), encoding="utf-8")
    s = settings_mod.load_settings(p)
    assert s["video"]["vsr_target"] == "screen" and s["video"]["sharpen"] == "strong" and s["meta"]["version"] == 4
    p.write_text(json.dumps({"meta": {"version": 2}, "video": {"vsr_target": "2160"}}), encoding="utf-8")
    assert settings_mod.load_settings(p)["video"]["vsr_target"] == "2160"   # yeni sürümde seçilen 4K kalır
    # v2 → v3: 1,5 sn tampon donma yapıyordu → Dengeli, canlıya yetişme kapalı; v3'te seçilen "low" korunur
    p.write_text(json.dumps({"meta": {"version": 2}, "latency": {"mode": "low", "chase": True}}), encoding="utf-8")
    lat = settings_mod.load_settings(p)["latency"]
    assert lat["mode"] == "auto" and lat["chase"] is False          # v2 → v3 Dengeli → v4 Akıllı
    p.write_text(json.dumps({"meta": {"version": 3}, "latency": {"mode": "low", "chase": True}}), encoding="utf-8")
    lat = settings_mod.load_settings(p)["latency"]
    assert lat["mode"] == "low" and lat["chase"] is True
    p.write_text(json.dumps({"lossless": {"mode": "always"}}), encoding="utf-8")
    assert settings_mod.load_settings(p)["lossless"]["mode"] == "fullscreen"
    # AMD FSR kendi keskinleştirmesini yapar → CAS yarıya; küçültmede hafif filtre
    amd = S(video__gpu_vendor="amd")
    nv = S(video__gpu_vendor="nvidia")
    sa = float(opt.picture_options(amd, {"w": 1280, "h": 720})["glsl-shader-opts"].split("=")[1])
    sn = float(opt.picture_options(nv, {"w": 1280, "h": 720})["glsl-shader-opts"].split("=")[1])
    assert sa == pytest.approx(sn / 2)
    assert opt.quality_options(S())["dscale"] == "mitchell"


def test_latency_and_vod_options():
    hls = opt.play_options(S(latency__mode="low"), "live", "http://x/live/index.m3u8?token=1",
                           {"user_agent": "UA", "origin": "https://o"})
    # önerilen kip: nobuffer yok (zaman damgası sapması/kare atlama yapıyordu), HLS'de 3 parça geriden
    assert hls["demuxer-lavf-o"] == "live_start_index=-3" and hls["video-latency-hacks"] == "no"
    assert hls["cache-pause"] == "yes" and float(hls["cache-pause-wait"]) >= 1
    assert hls["user-agent"] == "UA" and hls["http-header-fields"] == ["Origin: https://o"]
    assert hls["video-sync"] == "audio" and hls["interpolation"] == "no"
    ultra = opt.play_options(S(latency__mode="ultra"), "live", "http://x/live/u/p/1.ts")
    assert ultra["demuxer-lavf-o"] == "fflags=+nobuffer" and ultra["audio-buffer"] == "0.05"
    assert ultra["cache-pause"] == "yes" and ultra["demuxer-lavf-probe-info"] == "nostreams"
    stable = opt.play_options(S(latency__mode="stable"), "live", "http://x/1.ts")
    assert stable["cache-pause-initial"] == "yes" and stable["demuxer-lavf-o"] == ""
    vod = opt.play_options(S(), "movie", "http://x/movie/u/p/1.mkv")
    assert vod["video-sync"] == "display-resample" and vod["interpolation"] == "yes"
    assert vod["demuxer-max-bytes"] == "400MiB" and vod["af"] == ""
    assert "dynaudnorm" in opt.play_options(S(audio__normalize=True), "episode", "http://x/1.mp4")["af"]
    q = opt.quality_options(S(), "win32")
    assert q["hwdec-codecs"] == "all" and q["deinterlace"] == "no" and q["alang"].startswith("tur")
    assert opt.create_options(S(), wid=123, platform="win32")["gpu-api"] == "d3d11"
    assert opt.create_options(S(), platform="win32")["hwdec"] == "d3d11va"
    args = opt.cli_args({"vf": "@x:d3d11vpp=scale=2", "http-header-fields": ["A: 1"], "referrer": ""})
    assert args == ["--vf=@x:d3d11vpp=scale=2", "--http-header-fields-append=A: 1", "--referrer="]


def test_external_profiles_and_input_conf(tmp_path):
    from helootv.player import engine
    text = engine.external_profiles(S(), "win32")
    assert "profile-cond=height and height > 620 and height <= 800" in text
    assert "@helootv:d3d11vpp=scale=3:scaling-mode=nvidia" in text and "hqdn3d" in text
    conf = engine.write_input_conf(tmp_path)
    content = conf.read_text(encoding="utf-8")
    assert "UP            script-message helootv up" in content and "KP5  script-message helootv digit 5" in content
    assert engine.describe_mpv_error(["[ffmpeg] http: HTTP error 403 Forbidden"]).startswith("Sunucu erişimi")


# ---------------------------------------------------------------- gerçek libmpv (başsız)

def _libmpv_available() -> bool:
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


needs_mpv = pytest.mark.skipif(not _libmpv_available(), reason="libmpv yok")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")


class Recorder:
    def __init__(self):
        self.events = []
        self.cv = threading.Condition()

    def __call__(self, name, data):
        with self.cv:
            self.events.append((name, data))
            self.cv.notify_all()

    def wait(self, name, timeout=10, count=1):
        end = time.time() + timeout
        with self.cv:
            while sum(1 for n, _ in self.events if n == name) < count:
                left = end - time.time()
                if left <= 0:
                    return False
                self.cv.wait(left)
        return True

    def names(self):
        return [n for n, _ in self.events]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    from helootv.player.engine import MpvEngine
    rec = Recorder()
    eng = MpvEngine(S(), headless=True, on_event=rec, extra_options={"ao": "null"})
    eng.start()
    eng.rec = rec
    yield eng
    eng.shutdown()


@needs_mpv
def test_engine_plays_live_lavfi(engine):
    from helootv.player.engine import PlayRequest
    engine.play(PlayRequest(url="av://lavfi:testsrc2=size=1280x720:rate=25", title="Test Kanal", kind="live"))
    assert engine.rec.wait("file-loaded", 10)
    deadline = time.time() + 10
    st = {}
    while time.time() < deadline:
        st = engine.tick()
        if st.get("w"):
            break
        time.sleep(0.2)
    assert st["w"] == 1280 and st["h"] == 720 and st["title"] == "Test Kanal"
    assert engine.version_tuple >= (0, 35, 0)
    # tuş iletisi uygulamaya ulaşır
    engine.command("script-message", "helootv", "digit", "7")
    assert engine.rec.wait("key", 5)
    key = next(d for n, d in engine.rec.events if n == "key")
    assert key == {"action": "digit", "args": ["7"]}
    # canlıya yetişme: anlık dalgalanmada hızlanmaz; tampon 8 sn boyunca sınırı aşarsa %4 hızlanır,
    # hedefe inince normale döner; ileri atlama yok (atlama görüntüyü dondurur)
    from helootv.player import engine as eng_mod
    clock = [1000.0]
    monkey_time = eng_mod.time.monotonic
    eng_mod.time.monotonic = lambda: clock[0]
    try:
        fake = dict(st, paused=False, buffering=False, seeking=False, hls=False, cache=8.0)
        engine._user_paused = False
        engine._loaded_at = 900.0
        engine._boost, engine._over_since, engine._last_jump = False, 0.0, 0.0   # gerçek tick'lerin durumu
        engine.settings["latency"].update(mode="low", chase=True)              # varsayılanda kapalı
        engine._set("speed", "1")
        engine._chase(fake)
        assert not engine._boost
        clock[0] += 9
        engine._chase(fake)
        assert engine._boost and float(engine._get("speed")) == pytest.approx(1.04)
        engine._chase(dict(fake, cache=1.0))
        assert not engine._boost and float(engine._get("speed")) == pytest.approx(1.0)
        # takılma: tampon payı büyür, mpv yeniden doldurmayı daha uzun bekler; hiç ileri atlanmaz
        engine._chase(dict(fake, buffering=True, cache=0.0))
        assert engine.underruns == 1 and engine._extra == 1.0
        assert float(engine._get("cache-pause-wait")) == pytest.approx(2.0)
        engine._chase(dict(fake, buffering=False, cache=12.0))
        assert engine._last_jump == 0.0
    finally:
        eng_mod.time.monotonic = monkey_time
    engine.stop()
    assert engine.rec.wait("stopped", 5)


def _serve(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


@needs_mpv
@needs_ffmpeg
def test_engine_reconnects_live_and_resumes_vod(engine, tmp_path):
    from helootv.player.engine import PlayRequest
    media = tmp_path / "media"
    media.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                    "-c:a", "aac", "-f", "mpegts", str(media / "live.ts")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", "20", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                    "-c:a", "aac", str(media / "film.mp4")], check=True)
    httpd = _serve(media)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        # 2 sn'lik "canlı" yayın biter → motor kendiliğinden yeniden bağlanır
        engine.play(PlayRequest(url=f"{base}/live.ts", title="Kopan Kanal", kind="live"))
        assert engine.rec.wait("reconnecting", 15)
        assert engine.rec.wait("file-loaded", 15, count=2)
        data = next(d for n, d in engine.rec.events if n == "reconnecting")
        assert data["attempt"] == 1 and data["max"] >= 3

        # film: kaldığın yerden (12. sn) başlar, sonunda "ended" gelir
        loaded = engine.rec.names().count("file-loaded")
        # (test sunucusu HTTP Range desteklemediği için film yerel dosyadan açılır)
        engine.play(PlayRequest(url=str(media / "film.mp4"), title="Film", kind="movie", start=12,
                                key=(1, "movie", "9")))
        assert engine.rec.wait("file-loaded", 10, count=loaded + 1)
        deadline = time.time() + 10
        pos = None
        while time.time() < deadline:
            pos = engine.status()["pos"]
            if pos is not None and pos > 0:
                break
            time.sleep(0.1)
        assert pos is not None and pos >= 11.5
        assert engine.rec.wait("ended", 20)
        ended = next(d for n, d in engine.rec.events if n == "ended")
        assert ended["key"] == (1, "movie", "9")

        # olmayan adres → hata iletisi (canlı değilse yeniden denemez)
        engine.play(PlayRequest(url=f"{base}/yok.mp4", title="Yok", kind="movie"))
        assert engine.rec.wait("error", 15)
        err = [d for n, d in engine.rec.events if n == "error"][-1]
        assert err["message"]
    finally:
        httpd.shutdown()


def test_live_reconnect_options():
    live = opt.play_options(S(), "live", "http://x/live/u/p/1.ts")
    assert "reconnect_streamed=1" in live["stream-lavf-o"] and "reconnect_on_network_error=1" in live["stream-lavf-o"]
    assert "stream-lavf-o" not in opt.play_options(S(), "live", "udp://239.0.0.1:1234")
    assert "stream-lavf-o" not in opt.play_options(S(), "movie", "http://x/movie/1.mkv")
    bal = opt.play_options(S(latency__mode="balanced"), "live", "http://x/1.ts")
    assert bal["cache-pause-wait"] == "3" and bal["demuxer-lavf-o"] == ""   # Dengeli: nobuffer yok


class _FakeEngine:
    """Bekçi ve kare atlama korumasını mpv olmadan sınamak için motorun yalnız gereken parçaları."""

    def __init__(self):
        from helootv.player.engine import MpvEngine
        self.e = MpvEngine.__new__(MpvEngine)
        e = self.e
        e.settings = S()
        e.request = None
        e._loaded_at, e._user_paused = 1.0, False
        e._wd_pos, e._wd_moved, e._wd_buf_since, e._last_reload, e.reloads = None, 0.0, 0.0, 0.0, 0
        e._wd_data_at, e._wd_cache = 0.0, 0.0
        e._drop_mark, e.lighten = None, 0
        self.retries, self.texts, self.vf = [], [], []
        e._schedule_retry = lambda d: self.retries.append(d)
        e.show_text = lambda t, ms=0: self.texts.append(t)
        e._emit = lambda n, d=None: None
        e._update_vf = lambda force=False: self.vf.append(force)
        e._get = lambda name: 0


def test_watchdog_reloads_stuck_live(monkeypatch):
    from helootv.player import engine as eng_mod
    clock = [100.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: clock[0])
    f = _FakeEngine()
    e = f.e
    # henüz hiç oynamadı (konum yok): yavaş açılan kanal yeniden başlatılmaz
    e._watchdog({"paused": False, "seeking": False, "buffering": False, "pos": None})
    clock[0] += 9
    e._watchdog({"paused": False, "seeking": False, "buffering": False, "pos": None})
    assert f.retries == []
    st = {"paused": False, "seeking": False, "buffering": False, "pos": 10.0}
    e._watchdog(st)
    for _ in range(5):            # konum ilerliyor → bir şey yapılmaz
        clock[0] += 1
        st["pos"] += 1
        e._watchdog(st)
    assert f.retries == []
    clock[0] += 7                 # görüntü 7 sn dondu → yeniden açılır
    e._watchdog(st)
    assert f.retries == [0.05] and e.reloads == 1 and "yeniden açılıyor" in f.texts[0]
    clock[0] += 7                 # 20 sn dolmadan ikinci kez açılmaz
    e._watchdog(st)
    assert len(f.retries) == 1
    clock[0] += 30                # tampon boş ama yavaş doluyor (veri geliyor): 10 sn beklenir
    e._watchdog(dict(st, buffering=True, cache=0.0))
    for i in range(1, 6):
        clock[0] += 1
        e._watchdog(dict(st, buffering=True, cache=0.2 * i))
    assert len(f.retries) == 1
    clock[0] += 6
    e._watchdog(dict(st, buffering=True, cache=1.2))
    assert len(f.retries) == 2
    clock[0] += 30                # tampon boş ve hiç dolmuyor (bağlantı ölü) → 4 sn'de yeniden açılır
    e._watchdog(dict(st, buffering=True, cache=0.0))
    clock[0] += 4.5
    e._watchdog(dict(st, buffering=True, cache=0.0))
    assert len(f.retries) == 3
    # kullanıcı duraklattıysa asla
    clock[0] += 60
    e._watchdog(dict(st, paused=True))
    clock[0] += 60
    e._watchdog(dict(st, paused=True))
    assert len(f.retries) == 3


def test_frame_drops_lighten_enhancement(monkeypatch):
    from helootv.player import engine as eng_mod
    clock = [100.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: clock[0])
    f = _FakeEngine()
    e = f.e
    st = {"active": True, "paused": False, "buffering": False, "dropped": 0}
    e._watch_drops(st)
    clock[0] += 11
    e._watch_drops(dict(st, dropped=10))      # 0,9/sn: sorun yok
    assert e.lighten == 0
    clock[0] += 11
    e._watch_drops(dict(st, dropped=80))      # 6,4/sn → gürültü azaltma kapanır
    assert e.lighten == 1 and f.vf == [True]
    eff = e._effective_settings()
    assert eff["picture"]["denoise"] == "off" and e.settings["picture"]["denoise"] == "auto"
    clock[0] += 11
    e._watch_drops(dict(st, dropped=200))     # hâlâ → VSR/yapay zekâ da kapanır, daha ileri gitmez
    assert e.lighten == 2 and e._effective_settings()["video"]["rtx_vsr"] is False
    clock[0] += 11
    e._watch_drops(dict(st, dropped=400))
    assert e.lighten == 2


def test_auto_latency_adapts_per_channel(monkeypatch):
    """Akıllı kip: takılınca kanalın payı büyür ve hatırlanır; 1 dk sorunsuzsa küçülür; yetişme hep açık."""
    from helootv.player import engine as eng_mod
    from helootv.player.engine import MpvEngine, PlayRequest
    clock = [1000.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: clock[0])
    e = MpvEngine.__new__(MpvEngine)
    e.settings = S()
    assert e.settings["latency"]["mode"] == "auto" and e.settings["latency"]["chase"] is False
    sets = {}
    e._set = lambda k, v: sets.__setitem__(k, v)
    e.command = lambda *a: None
    e.request = PlayRequest(url="http://x/kanal1.ts", title="K1")
    e._was_buffering, e._loaded_at, e.underruns, e._last_underrun = False, 900.0, 0, 0.0
    e._extra, e._extra_mem, e._user_paused, e._hls_td = 0.0, {}, False, None
    e._boost, e._over_since, e._last_jump = False, 0.0, 0.0
    st = {"paused": False, "buffering": False, "seeking": False, "hls": False, "cache": 1.0}
    e._chase(dict(st, buffering=True, cache=0.0))
    assert e._extra == 1.0 and e._extra_mem["http://x/kanal1.ts"] == 1.0 and sets["cache-pause-wait"] == "2"
    e._chase(st)
    # yetişme ayarı kapalı olsa da Akıllı kipte gecikme büyürse fark edilmeden geri alınır
    for _ in range(3):
        clock[0] += 5
        e._chase(dict(st, cache=6.0))
    assert e._boost and sets["speed"] == "1.04"
    e._chase(dict(st, cache=1.5))
    assert not e._boost
    # 1 dk sorunsuz → pay küçülür (gecikme yeniden azalır)
    clock[0] += 61
    e._chase(st)
    assert e._extra == 0.5 and e._extra_mem["http://x/kanal1.ts"] == 0.5
    # Dengeli kipte yetişme ayarı kapalıysa hiç hızlanmaz
    e.settings["latency"]["mode"] = "balanced"
    e._boost, e._over_since = False, 0.0
    for _ in range(3):
        clock[0] += 5
        e._chase(dict(st, cache=20.0))
    assert not e._boost
