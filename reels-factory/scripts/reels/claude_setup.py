"""Bilgisayardaki Claude Code'un durumu, kurulumu ve bağlantı testi (uygulamadaki düğmeler için).

Kurulum resmî yükleyiciyle yapılır (Windows: `irm https://claude.ai/install.ps1 | iex`); giriş
`claude auth login` ile tarayıcıda yapılır. Hiçbir kimlik bilgisi bu uygulamaya geçmez.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import log
from .config import ROOT
from .llm import claude_cli

L = log.get("claude")
WIN = sys.platform.startswith("win")
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def status() -> dict:
    exe = claude_cli()
    st = {"installed": bool(exe), "path": exe, "version": None, "logged_in": False, "method": None,
          "can_install": WIN}
    if not exe:
        return st
    try:
        st["version"] = _run([exe, "--version"], 30).stdout.strip() or None
        auth = _run([exe, "auth", "status"], 30)
        data = json.loads(auth.stdout or "{}")
        st["logged_in"] = bool(data.get("loggedIn"))
        st["method"] = data.get("authMethod")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        L.debug("claude durum denetimi: %s", exc)
    return st


def open_console(action: str) -> dict:
    """Görünür bir pencerede kurulum/giriş (install) veya etkileşimli Claude Code (open) başlatır."""
    if not WIN:
        cmd = "bash scripts/install-claude.sh" if action == "install" else "claude"
        return {"ok": False, "manual": f"Terminalde bu klasörde çalıştırın: {cmd}"}
    if action == "install":
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(ROOT / "scripts" / "install-claude.ps1")]
    else:
        exe = claude_cli()
        if not exe:
            return {"ok": False, "manual": "Önce Claude Code'u kurun"}
        args = ["powershell", "-NoProfile", "-NoExit", "-Command", f"& '{exe}'"]
    subprocess.Popen(args, cwd=ROOT, creationflags=NEW_CONSOLE)
    L.info("Claude Code penceresi açıldı (%s)", action)
    return {"ok": True}


def test() -> dict:
    """Gerçek bir kısa istekle uçtan uca dener (abonelikten çok küçük bir kullanım harcar)."""
    exe = claude_cli()
    if not exe:
        return {"ok": False, "message": "Claude Code kurulu değil"}
    try:
        p = _run([exe, "-p", "Yalnızca TAMAM yaz, başka hiçbir şey yazma."], 180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Yanıt gelmedi (3 dk zaman aşımı)"}
    out = (p.stdout or p.stderr or "").strip()
    ok = p.returncode == 0 and "TAMAM" in out.upper()
    return {"ok": ok, "message": "Bağlantı çalışıyor — senaryolar artık Claude Code ile yazılacak" if ok
            else f"Hata: {out[-400:] or p.returncode}"}
