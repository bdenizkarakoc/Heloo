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
