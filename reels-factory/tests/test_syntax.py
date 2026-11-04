"""Gönderilen bir sözdizimi hatası bütün fabrikayı durdurur: her Python ve tarayıcı JS dosyası derlenebilmeli."""
import py_compile
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sorted(p for d in ("scripts", "app", "cizgi") for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts)
JS = sorted([*(ROOT / "app").glob("*.js"), *(ROOT / "kesim-app" / "fabrika").glob("*.js")])


@pytest.mark.parametrize("path", PY, ids=lambda p: str(p.relative_to(ROOT)))
def test_python_compiles(path):
    py_compile.compile(str(path), doraise=True)


@pytest.mark.skipif(not shutil.which("node"), reason="node yok")
@pytest.mark.parametrize("path", JS, ids=lambda p: str(p.relative_to(ROOT)))
def test_js_parses(path):
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_cli_help():
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "factory.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for cmd in ("produce", "kesim", "gorsel", "anahtar", "anim-karakter"):
        assert cmd in r.stdout
