"""scripts/hoparlor.ps1: Windows PowerShell 5.1 Türkçe harfleri ancak BOM ile okur; hazırlar Python sürümüyle aynı."""
import re
from pathlib import Path

from reels import hoparlor as h

PS1 = Path(__file__).resolve().parents[1] / "scripts" / "hoparlor.ps1"


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
