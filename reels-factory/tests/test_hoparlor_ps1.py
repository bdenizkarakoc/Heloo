"""hoparlor-app: HoparlorSesAyari.ps1 Windows PowerShell 5.1 Türkçe harfleri ancak BOM ile okur; hazırlar Python sürümüyle aynı."""
import re
from pathlib import Path

from reels import hoparlor as h

APP = Path(__file__).resolve().parents[2] / "hoparlor-app"
PS1 = APP / "HoparlorSesAyari.ps1"


def test_bom_and_presets_match_python():
    raw = PS1.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    found = dict(re.findall(r"^\s+(\w+)\s+= @\{ ad = '[^']*';\s+b = @\(([-\d, ]+)\)", text, re.M))
    assert set(found) == set(h.PRESETS)
    for k, v in found.items():
        assert [int(x) for x in v.split(",")] == h.PRESETS[k]["b"], k
    for k, v in h.KINDS.items():
        assert re.search(rf"{k}\s+= @\{{ ad = '[^']*';\s+hp = {v['hp']};\s+max = {v['max']};", text), k


def test_installer_is_ascii_and_points_to_app():
    text = (APP / "kur.ps1").read_text(encoding="utf-8")
    assert text.isascii()                       # irm | iex hangi kodlamayla okursa okusun bozulmaz
    assert "/hoparlor-app/kur.ps1" in text and "$Raw/HoparlorSesAyari.ps1" in text


def test_power_modes_match_python():
    text = PS1.read_bytes().decode("utf-8-sig")
    for k, (_, pay) in h.POWER.items():
        assert re.search(rf"{k}\s+= @\{{ ad = '[^']*';\s+pay = {pay};", text), k
    assert "GraphicEQ: " in text and f"$LevelMax = {int(h.LEVEL_MAX)}" in text


def test_custom_presets_in_app():
    text = PS1.read_bytes().decode("utf-8-sig")
    for fn in ("function Save-Custom", "function Load-Custom", "function Remove-Custom", "StartsWith('my:')", "custom = @()"):
        assert fn in text, fn


def test_window_is_never_started_hidden():
    """Gizli başlatılan süreçte Windows ilk pencereyi de gizler: program açılmaz görünür (kullanıcı hatası)."""
    app = PS1.read_bytes().decode("utf-8-sig")
    kur = (APP / "kur.ps1").read_text(encoding="utf-8")
    for text in (app, kur):
        assert "-WindowStyle Hidden" not in text and '"-WindowStyle", "Hidden"' not in text
    assert app.index("ShowWindow($hw, 0)") < app.index("Start-Process powershell -Verb RunAs")
    assert "trap {" in app and "Set-StrictMode" not in app
