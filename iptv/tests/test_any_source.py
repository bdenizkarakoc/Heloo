"""Her kaynak 4K: kendi dosyalarım/fotoğraflar, bağlantılar, tek örnek iletimi, VSR yedeği, 4K dışa aktarma."""
import os
import shutil
import subprocess
import time

import pytest

from helootv import settings as settings_mod
from helootv import upscale, weburl
from helootv.player import options as opt


def S():
    return settings_mod.merged_defaults()


def test_vsr_fallback_and_images():
    vp = {"w": 1920, "h": 1080}
    assert "scaling-mode=nvidia" in opt.vsr_plan(S(), vp, None, "win32")["vf"]
    # RTX yok / sürücü reddetti / fotoğraf → VP ölçeklemesi yok (yapay zekâ + ewa büyütür), deinterlace kalır
    for plan in (opt.vsr_plan(S(), vp, None, "win32", vsr_available=False),
                 opt.vsr_plan(S(), vp, None, "win32", kind="image")):
        assert plan["scale"] is None and "scale=" not in plan["vf"] and "deint=yes" in plan["vf"]
    assert opt.play_options(S(), "image", "/a.jpg")["image-display-duration"] == "inf"
    assert opt.play_options(S(), "file", "/a.mp4")["video-sync"] == "display-resample"
    assert opt.quality_options(S(), "win32")[("input-builtin-drag-and-drop", "drag-and-drop")] == "no"


def test_shader_resolution(tmp_path, monkeypatch):
    from helootv import shaders
    monkeypatch.setenv("HELOOTV_BIN", str(tmp_path))
    assert shaders.resolve("fsrcnnx") is None and opt.quality_options(S())["glsl-shaders"] == []
    (tmp_path / "shaders").mkdir()
    (tmp_path / "shaders" / "ArtCNN_C4F16_DS.glsl").write_text("//!HOOK LUMA\n" + "x" * 2000)
    # FSRCNNX yoksa indirilmiş diğer model kullanılır
    assert shaders.resolve("fsrcnnx").name == "ArtCNN_C4F16_DS.glsl"
    assert opt.quality_options(S())["glsl-shaders"][0].endswith("ArtCNN_C4F16_DS.glsl")
    assert shaders.resolve("off") is None


def test_target_sizes_and_paths(tmp_path):
    assert upscale.target_size(1920, 1080) == (3840, 2160, 2.0)
    assert upscale.target_size(1080, 1920) == (2160, 3840, 2.0)       # dikey Reels/telefon → dikey 4K
    assert upscale.target_size(1280, 720, "1440")[:2] == (2560, 1440)
    assert upscale.target_size(3840, 2160)[2] == 1.0                     # küçültmez
    (tmp_path / "a (4K).mp4").write_text("x")
    assert upscale.output_path(str(tmp_path / "a.mp4")).name == "a (4K 2).mp4"
    assert upscale.output_path(str(tmp_path / "f.jpg"), image=True).suffix == ".png"
    assert upscale.kind_of("x.HEIC") == "image" and upscale.kind_of("x.mkv") == "video"


def test_weburl(monkeypatch):
    assert weburl.is_url("https://youtu.be/abc") and not weburl.is_url("C:/video.mp4")
    assert weburl.is_direct("http://h/live/u/p/1.ts") and weburl.looks_live("http://h/x/index.m3u8")
    r = weburl.resolve("http://cdn/film.mp4")
    assert r["url"] == "http://cdn/film.mp4" and not r["live"]

    class FakeYDL:
        def __init__(self, opts):
            assert opts["format"].startswith("bestvideo")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            return {"title": "Klip", "requested_formats": [
                {"url": "https://v/video", "vcodec": "vp9", "acodec": "none", "height": 2160,
                 "http_headers": {"User-Agent": "UA", "Referer": "https://r/"}},
                {"url": "https://v/audio", "vcodec": "none", "acodec": "opus"}]}

    import types
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    r = weburl.resolve("https://www.youtube.com/watch?v=x")
    assert (r["url"], r["audio"], r["title"], r["height"]) == ("https://v/video", "https://v/audio", "Klip", 2160)
    assert r["headers"] == {"user_agent": "UA", "referrer": "https://r/"}


def _mpv_ok():
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _mpv_ok() or shutil.which("ffmpeg") is None, reason="libmpv/ffmpeg yok")
def test_open_own_files_and_photos(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    vid = tmp_path / "benim videom.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=25", "-t", "3",
                    "-c:v", "libx264", "-preset", "ultrafast", str(vid)], check=True)
    photo = tmp_path / "foto.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x480", "-frames:v", "1",
                    str(photo)], check=True)
    app = QApplication.instance() or QApplication([])
    settings = S()
    settings["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), settings, headless=True)
    eng = MpvEngine(settings, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d),
                    extra_options={"ao": "null"})
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

    pump(0.5, lambda: False)  # açılış (sekme seçimi) tamamlansın
    try:
        win.open_paths([str(tmp_path)])                # klasör: içindeki video + fotoğraf sırayla
        assert win._file_queue == sorted([str(vid), str(photo)])
        assert pump(10, lambda: "1080×1920" in win.status_stats.text() or "640×480" in win.status_stats.text())
        assert win._theater and win.current_req.kind in ("file", "image")
        win.open_paths([str(photo)])
        assert pump(10, lambda: "640×480" in win.status_stats.text())
        assert win.current_req.kind == "image" and eng._get("image-display-duration") in ("inf", float("inf"))
        win.open_paths([str(vid)])
        assert pump(10, lambda: "1080×1920" in win.status_stats.text())
        hist = win.store.history(("file", "image"))
        assert {h["title"] for h in hist} >= {"benim videom.mp4", "foto.jpg"}
        # mpv'ye bırakılan dosya uygulamaya iletilir
        win.bridge.event.emit("dropped", {"files": [str(photo)]})
        assert pump(10, lambda: win.current_req and win.current_req.title == "foto.jpg")
    finally:
        win.close()


def test_single_instance_forwarding(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    from helootv import app as appmod

    qapp = QApplication.instance() or QApplication([])
    got = []

    class FakeWin:
        def isMinimized(self):
            return False

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        def open_paths(self, items):
            got.extend(items)

    from PySide6.QtCore import QObject
    holder = QObject()
    fake = FakeWin()
    monkeypatch.setattr(appmod, "_server_name", lambda: f"HelooTV-test-{os.getpid()}")
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(holder)
    QLocalServer.removeServer(appmod._server_name())
    assert server.listen(appmod._server_name())

    def on_conn():
        sock = server.nextPendingConnection()
        sock.readyRead.connect(lambda: fake.open_paths(__import__("json").loads(bytes(sock.readAll()).decode())))

    server.newConnection.connect(on_conn)
    assert appmod.forward_to_running(["https://youtu.be/abc"])
    end = time.time() + 3
    while time.time() < end and not got:
        qapp.processEvents()
        time.sleep(0.02)
    server.close()
    assert got == ["https://youtu.be/abc"]


def _vulkan_ok():
    ff = upscale.find_ffmpeg()
    return bool(ff) and upscale.capabilities(ff)["libplacebo"]


@pytest.mark.skipif(not _mpv_ok() or shutil.which("ffmpeg") is None, reason="libmpv/ffmpeg yok")
def test_export_pipeline(tmp_path):
    """Gerçek dışa aktarma (küçük boyutta): libplacebo varsa GPU/Vulkan, yoksa CPU lanczos yolu."""
    src = tmp_path / "klip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10", "-f", "lavfi",
                    "-i", "sine", "-t", "1", "-c:v", "libx264", "-c:a", "aac", str(src)], check=True)
    ff = upscale.find_ffmpeg()
    caps = upscale.capabilities(ff)
    info = upscale.probe(str(src))
    assert (info["dw"], info["dh"], info["audio"]) == (160, 90, "aac")
    dst = tmp_path / "out.mp4"
    cmd = upscale.build_command(ff, str(src), str(dst), info, (320, 180), caps, None,
                                caps["encoders"][-1] if caps["encoders"] else "libx264", "fast")
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-500:]
    out = upscale.probe(str(dst))
    assert (out["dw"], out["dh"]) == (320, 180) and out["audio"] == "aac"
