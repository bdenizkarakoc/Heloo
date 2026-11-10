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
    block = text[text.index("$Presets = [ordered]@{"):]
    block = block[:block.index("\n}\n")]
    rows = re.findall(r"^\s+(\w+)\s+= @\{ ad = '((?:[^']|'')*)'; grup = '(\w+)'; b = @\(([-\d., ]+)\)(.*)\}$", block, re.M)
    assert [r[0] for r in rows] == list(h.PRESETS)            # aynı sıra (en iyi ayarlar önce)
    for k, ad, grup, b, rest in rows:
        p = h.PRESETS[k]
        assert ad.replace("&&", "&").replace("''", "'") == p["ad"] and grup == p["grup"], k
        assert [float(x) for x in b.split(",")] == [float(x) for x in p["b"]], k
        for extra in ("sub", "merkez"):
            m = re.search(rf"{extra} = ([-\d.]+)", rest)
            assert (float(m.group(1)) if m else None) == (float(p[extra]) if extra in p else None), (k, extra)
        assert ("ipucu = " in rest) == bool(p.get("ipucu")), k
    for k, v in h.KINDS.items():
        assert re.search(rf"{k}\s+= @\{{ ad = '[^']*';\s+hp = {v['hp']};\s+max = {v['max']};\s+k51 = \$\w+; oneri = '{v['oneri']}' }}", text), k
        assert v["oneri"] in h.PRESETS


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


def test_no_variables_differing_only_in_case():
    """PowerShell değişken adlarında büyük/küçük harf ayırmaz: `$c` döngüsü `$C` renk tablosunu ezmişti
    ("The property 'muted' cannot be found")."""
    import collections
    code = "\n".join(line.split(" #")[0] for line in PS1.read_bytes().decode("utf-8-sig").splitlines()
                     if not line.lstrip().startswith("#"))
    names = collections.defaultdict(set)
    for m in re.findall(r"\$(?:script:)?([A-Za-z_]\w*)", code):
        names[m.lower()].add(m)
    assert {k: v for k, v in names.items() if len(v) > 1} == {}
