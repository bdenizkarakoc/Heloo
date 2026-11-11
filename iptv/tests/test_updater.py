"""Uygulama içi güncelleme: gerçek git depolarıyla (uzak = çıplak depo)."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from helootv import updater

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git yok")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"],
                        "HOME": str(cwd)})


def _setup(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    dev = tmp_path / "dev"
    _git(tmp_path, "clone", str(origin), str(dev))
    (dev / "iptv").mkdir()
    (dev / "iptv" / "requirements.txt").write_text("PySide6\n")
    (dev / "a.txt").write_text("1")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-m", "ilk")
    _git(dev, "push", "origin", "HEAD:main")
    user = tmp_path / "user"
    _git(tmp_path, "clone", str(origin), str(user))
    return dev, user


def test_check_and_apply(tmp_path, monkeypatch):
    dev, user = _setup(tmp_path)
    info = updater.check(user)
    assert info["behind"] == 0 and info["branch"] == "main" and not info["dirty"]
    (dev / "a.txt").write_text("2")
    _git(dev, "commit", "-am", "Canlı yayın donması düzeltildi")
    (dev / "b.txt").write_text("x")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-m", "TV rehberi eklendi")
    _git(dev, "push", "origin", "HEAD:main")
    info = updater.check(user)
    assert info["behind"] == 2 and info["changes"] == ["TV rehberi eklendi", "Canlı yayın donması düzeltildi"]
    res = updater.apply(user)
    assert res["from"] != res["to"] and not res["requirements_changed"]
    assert (user / "a.txt").read_text() == "2" and (user / "b.txt").exists()
    assert updater.check(user)["behind"] == 0
    # requirements değişirse paketler kurulur (pip çağrısı taklit)
    calls = []
    monkeypatch.setattr(updater.subprocess, "run", _spy(updater.subprocess.run, calls))
    (dev / "iptv" / "requirements.txt").write_text("PySide6\nmpv\n")
    _git(dev, "commit", "-am", "paket")
    _git(dev, "push", "origin", "HEAD:main")
    res = updater.apply(user)
    assert res["requirements_changed"] and any("pip" in c for c in calls)


def _spy(real, calls):
    def run(args, *a, **k):
        if "pip" in args:
            calls.append("pip")
            return subprocess.CompletedProcess(args, 0, "", "")
        return real(args, *a, **k)
    return run


def test_apply_refuses_to_overwrite_local_changes(tmp_path):
    dev, user = _setup(tmp_path)
    (dev / "a.txt").write_text("2")
    _git(dev, "commit", "-am", "yeni")
    _git(dev, "push", "origin", "HEAD:main")
    (user / "a.txt").write_text("kullanıcının değişikliği", encoding="utf-8")
    assert updater.check(user)["dirty"]
    with pytest.raises(updater.UpdateError, match="yerel değişiklik"):
        updater.apply(user)
    assert (user / "a.txt").read_text(encoding="utf-8") == "kullanıcının değişikliği"


def test_not_a_git_checkout(tmp_path):
    with pytest.raises(updater.UpdateError, match="git klonu değil"):
        updater.check(tmp_path)


def test_silent_check_never_prompts_and_restart_flag(tmp_path, monkeypatch):
    dev, user = _setup(tmp_path)
    seen = {}
    real = updater.subprocess.run

    def spy(args, *a, **k):
        if "fetch" in args:
            seen.update(k.get("env") or {})
        return real(args, *a, **k)

    monkeypatch.setattr(updater.subprocess, "run", spy)
    assert updater.check(user, interactive=False)["behind"] == 0
    assert seen["GIT_TERMINAL_PROMPT"] == "0" and seen["GCM_INTERACTIVE"] == "Never"
    # güncellemeden sonra yeniden açılış: --restart bayrağı tanınır (tek örnek denetimi atlanır)
    import argparse
    import inspect

    from helootv import app
    src = inspect.getsource(app._main)
    assert '"--restart"' in src and "argparse.SUPPRESS" in src
    assert src.index("if args.restart:") < src.index("forward_to_running(args.paths)")
    assert argparse.SUPPRESS
