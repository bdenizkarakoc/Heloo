"""factory.py anahtar --pano: panoda etiket/komut/bozuk değer olsa da yanlış anahtar kaydedilmez."""
import importlib.util
import subprocess
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def factory(monkeypatch):
    spec = importlib.util.spec_from_file_location("factory_cli", ROOT / "scripts" / "factory.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    saved = {}
    from reels import config
    monkeypatch.setattr(config, "set_secret", lambda n, v: saved.update({n: v}))
    monkeypatch.setattr("builtins.input", lambda *a: "")
    return mod, saved


def run(mod, monkeypatch, clips):
    seq = iter(clips)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=next(seq)))
    return mod.cmd_anahtar(types.SimpleNamespace(ad="GEMINI_API_KEY", pano=True), None)


KEY = "AIza" + "B" * 35
AQ = "AQ.Ab8" + "x" * 47


@pytest.mark.parametrize("clip,expect", [(KEY, KEY), ("Gemini API Key\n" + KEY, KEY), (AQ, AQ), ("Anahtarı kopyala\n" + AQ, AQ)])
def test_extracts(factory, monkeypatch, clip, expect):
    mod, saved = factory
    assert run(mod, monkeypatch, [clip]) == 0 and saved["GEMINI_API_KEY"] == expect


@pytest.mark.parametrize("clip", ["x", "abc defghijklmnopqrstuvwxyz0123456789", "AQ.Ab8RN6Lnr pKV9cJkgfeaPbqOTyw2IAGFu2O381npafSY9BSBig",
                                  KEY + "X ek"])
def test_rejects(factory, monkeypatch, clip):
    mod, saved = factory
    assert run(mod, monkeypatch, [clip]) == 1 and not saved


def test_waits_when_clipboard_has_command(factory, monkeypatch):
    mod, saved = factory
    assert run(mod, monkeypatch, ["python scripts\\factory.py anahtar GEMINI_API_KEY --pano", KEY]) == 0
    assert saved["GEMINI_API_KEY"] == KEY
