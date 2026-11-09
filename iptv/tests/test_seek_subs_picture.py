"""İlerleme çubuğu, altyazı (dosya / OpenSubtitles / yapay zekâ) ve görüntü ayarları penceresi."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from helootv import ai_subs, settings as settings_mod, subs_online
from helootv.player import options as opt


def _qt_ok() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def _mpv_ok() -> bool:
    try:
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- saf işlevler

def test_clean_title_and_srt():
    assert subs_online.clean_title("Kuruluş Osman S02E05") == ("Kuruluş Osman", 2, 5)
    assert subs_online.clean_title("The.Matrix.1999.1080p.BluRay.x264")[0] == "The Matrix"
    srt = ai_subs.to_srt([(0.5, 2.25, " Merhaba "), (3661.0, 3662.5, "Dünya")])
    assert srt == "1\n00:00:00,500 --> 00:00:02,250\nMerhaba\n\n2\n01:01:01,000 --> 01:01:02,500\nDünya\n\n"


def test_opensubtitles_search_and_download(monkeypatch, tmp_path):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    calls = []

    def fake_call(method, path, key, params=None, body=None):
        calls.append((method, path, key, params, body))
        if path == "/subtitles":
            return {"data": [
                {"attributes": {"language": "tr", "release": "Dizi.S02E05.WEB", "download_count": 900,
                                "hearing_impaired": False, "files": [{"file_id": 42, "file_name": "a.srt"}],
                                "feature_details": {"title": "Dizi", "year": 2020}}},
                {"attributes": {"language": "en", "files": []}},   # dosyasız satır atlanır
            ]}
        return {"link": "http://dl/x", "file_name": "Dizi S02E05.srt"}

    monkeypatch.setattr(subs_online, "_call", fake_call)
    rows = subs_online.search("KEY", "Dizi", "tr,en", 2, 5)
    assert [(r["file_id"], r["lang"], r["downloads"]) for r in rows] == [(42, "tr", 900)]
    assert calls[0][3]["season_number"] == 2 and calls[0][3]["episode_number"] == 5

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "1\n00:00:01,000 --> 00:00:02,000\nSelam\n".encode("utf-8")

    monkeypatch.setattr(subs_online.urllib.request, "urlopen", lambda *a, **k: Resp())
    path = subs_online.download("KEY", 42, "Dizi")
    assert path.endswith("Dizi_S02E05.srt") and "Selam" in open(path, encoding="utf-8").read()
    with pytest.raises(subs_online.SubsError):
        subs_online.search("", "x")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")
def test_ai_subs_chunked_transcribe(monkeypatch, tmp_path):
    """Yapay zekâ altyazı izlenen yerden parça parça ilerler, zamanlar kaynağa göre kaydırılır."""
    np = pytest.importorskip("numpy")
    src = tmp_path / "ses.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=100", str(src)], check=True)

    class Seg:
        def __init__(self, a, b, t):
            self.start, self.end, self.text = a, b, t

    class Info:
        language = "tr"

    seen = []

    class Model:
        def transcribe(self, audio, **kw):
            assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
            seen.append(len(audio) / 16000)
            return iter([Seg(1.0, 2.0, f"parça {len(seen)}")]), Info()

    monkeypatch.setattr(ai_subs, "_load_model", lambda name: (Model(), "işlemci"))
    monkeypatch.setattr("helootv.upscale.find_ffmpeg", lambda: shutil.which("ffmpeg"))
    updates = []
    out = ai_subs.transcribe(str(src), tmp_path / "o.srt", start=12.0, duration=100.0,
                             on_update=lambda p, n: updates.append(n))
    text = open(out, encoding="utf-8").read()
    # 10 sn'den (12 − 2) başlar: 10–50, 50–90, 90–100
    assert [round(s) for s in seen] == [40, 40, 10]
    assert "00:00:11,000 --> 00:00:12,000\nparça 1" in text and "00:01:31,000" in text
    assert updates[0] == 1 and updates[-1] == 3


def test_picture_presets_roundtrip():
    s = settings_mod.merged_defaults()
    opt.apply_preset(s, "noisy")
    assert s["picture"]["denoise"] == "strong" and s["picture"]["preset"] == "noisy"
    o = opt.picture_options(s, {"w": 720, "h": 576})
    assert o["deband"] == "yes" and float(o["glsl-shader-opts"].split("=")[1]) > shaders_sharp("medium")
    # bozuk değerler varsayılana döner
    bad = settings_mod._sanitize({"picture": {"brightness": 500, "denoise": "x"}, "video": {"sharpen": 3}})
    assert bad["picture"]["brightness"] == 100 and bad["picture"]["denoise"] == "auto"
    assert bad["video"]["sharpen"] == "light"


def shaders_sharp(name):
    from helootv import shaders
    return shaders.SHARPNESS[name]


# ---------------------------------------------------------------- arayüz

@pytest.mark.skipif(not _qt_ok(), reason="PySide6 yok")
def test_player_panel_seek_and_picture_dialog(monkeypatch, tmp_path):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from helootv.ui.picture_dialog import PictureDialog
    from helootv.ui.player_panel import PlayerPanel, _clock
    from helootv.ui.subs_dialogs import AiSubsDialog, OnlineSubsDialog

    app = QApplication.instance() or QApplication([])
    p = PlayerPanel()
    p.resize(1000, 600)
    p.show()
    got = []
    p.seek_to.connect(lambda v: got.append(("to", v)))
    p.seek_by.connect(lambda v: got.append(("by", v)))
    p.set_status({"kind": "movie", "duration": 3600.0, "pos": 900.0})
    assert not p.seek_box.isHidden() and p.seek.value() == 2500
    assert (p.pos_label.text(), p.dur_label.text()) == ("15:00", "1:00:00")
    p.seek.setValue(5000)
    p._seek_release()
    assert got[-1] == ("to", 1800.0)
    plus = [b for b in p.bar.findChildren(type(p.btn_stop)) if b.text() == "+10"][0]
    plus.click()
    assert got[-1] == ("by", 10.0)
    p.set_status({"kind": "live", "duration": 0, "pos": 5})
    assert p.seek_box.isHidden()
    assert _clock(3725) == "1:02:05" and set(p.menus) == {"audio", "sub", "picture"}

    s = settings_mod.merged_defaults()
    d = PictureDialog(s)
    changed = []
    d.changed.connect(lambda: changed.append(1))
    d.sliders["contrast"].setValue(25)
    d.denoise.setCurrentIndex(d.denoise.findData("strong"))
    assert s["picture"]["contrast"] == 25 and s["picture"]["denoise"] == "strong"
    assert s["picture"]["preset"] == "custom"
    d._preset("cinema")
    assert s["picture"]["preset"] == "cinema" and d.preset_btns["cinema"].isChecked()
    assert d.sliders["contrast"].value() == opt.PICTURE_PRESETS["cinema"]["contrast"]
    end = time.time() + 1
    while time.time() < end and not changed:
        app.processEvents()
    assert changed

    o = OnlineSubsDialog(s, "Kuruluş Osman S02E05")
    assert (o.query.text(), o.season.value(), o.episode.value()) == ("Kuruluş Osman", 2, 5)
    a = AiSubsDialog(s)
    assert a.model.currentData() == "small"
    # üst öğesiz pencereleri Qt'de sil (yorumlayıcı kapanırken rastgele sırada silinip çökmesin)
    from PySide6.QtCore import QCoreApplication, QEvent
    for w in (p, d, o, a):
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.skipif(not (_qt_ok() and _mpv_ok() and shutil.which("ffmpeg")), reason="PySide6/libmpv/ffmpeg yok")
def test_vod_seek_tracks_subs_picture(monkeypatch, tmp_path):
    """Gerçek oynatma: dosya → ilerleme çubuğu, ileri/geri sarma, altyazı ekleme/seçme, görüntü ayarı anında."""
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    vid = tmp_path / "film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=25:d=60",
                    "-f", "lavfi", "-i", "sine=d=60", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                    "-c:a", "aac", "-shortest", str(vid)], check=True)
    srt = tmp_path / "film.tr.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:30,000\nMerhaba dünya\n", encoding="utf-8")
    from PySide6.QtWidgets import QApplication

    from helootv.player.engine import MpvEngine
    from helootv.store import Store
    from helootv.ui.main_window import MainWindow
    from helootv.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    settings = settings_mod.merged_defaults()
    settings["ui"]["auto_refresh_hours"] = 0
    settings["ui"]["resume_last_channel"] = False
    win = MainWindow(Store(tmp_path / "t.db"), settings, headless=True)
    win.resize(1400, 860)
    win.show()

    def pump(seconds, until=None):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            if until and until():
                return True
            time.sleep(0.02)
        return bool(until and until())

    eng = MpvEngine(settings, headless=True, on_event=lambda n, d: win.bridge.event.emit(n, d),
                    extra_options={"ao": "null"})
    eng.start()
    win.engine = eng
    try:
        win.play_file(str(vid))
        assert pump(10, lambda: not win.player.seek_box.isHidden()), "ilerleme çubuğu görünmedi"
        assert win.player.dur_label.text() == "1:00"
        win.player.seek_to.emit(30.0)
        assert pump(5, lambda: 29 <= (eng.status().get("pos") or 0) <= 33)
        win.player.seek_by.emit(-10.0)
        assert pump(5, lambda: 19 <= (eng.status().get("pos") or 0) <= 23)
        # çubuk konumu izler (yarım saniyede bir güncellenir)
        assert pump(3, lambda: 3000 <= win.player.seek.value() <= 4200), win.player.seek.value()
        # mpv aynı adlı altyazıyı kendisi bulur (film.tr.srt); menüde listelenir
        assert pump(5, lambda: any(t["type"] == "sub" for t in eng.tracks()))
        win._fill_sub_menu()
        texts = [a.text() for a in win.player.menus["sub"].actions()]
        assert texts[0] == "Kapalı" and any("Türkçe" in t for t in texts)
        assert any("İnternetten" in t for t in texts) and any("Yapay zekâ" in t for t in texts)
        win.player.menus["sub"].actions()[0].trigger()          # Kapalı
        assert pump(3, lambda: not any(t["selected"] for t in eng.tracks() if t["type"] == "sub"))
        extra = tmp_path / "ek.srt"
        extra.write_text("1\n00:00:00,000 --> 00:01:00,000\nEk altyazı\n", encoding="utf-8")
        eng.sub_add(str(extra), "Ek", "tr")
        assert pump(3, lambda: any(t["selected"] and t["external"] and t["title"] == "Ek"
                                   for t in eng.tracks() if t["type"] == "sub"))
        win._nudge("sub-delay", 0.5, "Altyazı gecikmesi")
        assert abs(float(eng._get("sub-delay")) - 0.5) < 1e-6
        win._fill_audio_menu()
        assert any("kanal" in a.text() or "İz" in a.text() or a.text().startswith("1.")
                   for a in win.player.menus["audio"].actions())
        # görüntü: hazır ayar + karıncalanma anında
        win._apply_preset("noisy")
        assert pump(3, lambda: "hqdn3d=4:3:9:7" in str(eng._get("vf")))
        assert int(eng._get("contrast")) == opt.PICTURE_PRESETS["noisy"]["contrast"]
        win._set_picture("picture", "denoise", "off")
        assert pump(3, lambda: "hqdn3d" not in str(eng._get("vf")))
        assert settings["picture"]["preset"] == "custom" and win.settings_page.denoise.currentData() == "off"
        win.picture_dialog()
        win._picture_dlg.sliders["brightness"].setValue(10)
        assert pump(3, lambda: int(eng._get("brightness")) == 10)
        win._fill_picture_menu()
        assert any(a.text() == "Karıncalı yayın" for a in win.player.menus["picture"].actions())
        assert any("Lossless Scaling" in a.text() for a in win.player.menus["picture"].actions())
        # Lossless Scaling kare üretimi açıkken mpv interpolasyonu kapanır, kapanınca geri gelir
        eng.set_external_framegen(True)
        assert eng._get("interpolation") is False and eng._get("video-sync") == "audio"
        eng.set_external_framegen(False)
        assert eng._get("interpolation") is True and eng._get("video-sync") == "display-resample"
        if os.environ.get("HELOOTV_SHOT"):
            win.grab().save(os.environ["HELOOTV_SHOT"])
    finally:
        win.close()
