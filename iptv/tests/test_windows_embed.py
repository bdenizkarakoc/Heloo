"""Windows: mpv'nin gerçek Qt penceresine gömülmesi (wid) + Direct3D 11 çıkışı.

Ayrı süreçte çalıştırılır (offscreen olmayan Qt): HELOOTV_EMBED_TEST=1 QT_QPA_PLATFORM=windows
GPU'suz makinede (GitHub Actions) mpv Direct3D 11 için WARP yazılım işleyicisini kullanır; d3d11vpp orada olmadığından
RTX VSR ve deinterlace bu testte kapalıdır.
"""
import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("win") or os.environ.get("HELOOTV_EMBED_TEST") != "1",
                                reason="yalnız Windows'ta HELOOTV_EMBED_TEST=1 ile")


def test_embedded_d3d11_playback(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication

    from helootv import settings as settings_mod
    from helootv.player.engine import PlayRequest
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    from helootv.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "windows"
    apply_theme(app)
    settings = settings_mod.merged_defaults()
    settings["video"]["rtx_vsr"] = False
    settings["video"]["deinterlace"] = "no"
    settings["ui"]["auto_refresh_hours"] = 0
    win = MainWindow(Store(tmp_path / "t.db"), settings)
    win.resize(1280, 800)
    win.show()

    def pump(seconds, until):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until():
                return True
            time.sleep(0.02)
        return until()

    assert pump(15, lambda: win.engine is not None), win.status_msg.text()
    assert win.engine.wid == int(win.player.host.winId())
    win._start(PlayRequest(url="av://lavfi:testsrc2=size=1280x720:rate=25,realtime", title="Gömülü test", kind="live"))
    assert pump(20, lambda: (win.engine.status().get("out_w") or 0) == 1280), win.engine.status()
    vo = win.engine._get("current-vo")
    gpu_ctx = win.engine._get("current-gpu-context")
    print("current-vo:", vo, "gpu-context:", gpu_ctx, "hwdec:", win.engine._get("hwdec-current"))
    assert vo == "gpu-next"
    assert gpu_ctx in ("d3d11", None)
    win._set_fullscreen(True)
    assert pump(3, lambda: win.isFullScreen())
    win._set_fullscreen(False)
    win.close()
    assert win.engine is None
