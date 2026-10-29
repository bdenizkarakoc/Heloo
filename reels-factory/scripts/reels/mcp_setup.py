"""Claude Code'a MCP sunucularını kaydeder (kullanıcı kapsamı: her klasörde geçerli).

Anahtarsız olanlar her zaman eklenir; anahtar/DSN isteyenler yalnızca `.env`'de değeri varsa (Yayın → Ayarlar).
Değerler `claude mcp add-json` ile Claude Code'un kendi ayar dosyasına yazılır; bu depoya ve loglara yazılmaz.
OAuth isteyenler (GitHub belirteçsiz, Sentry) eklendikten sonra Claude Code'da `/mcp` ile giriş yapılır.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import log
from .config import ROOT, secret
from .llm import claude_cli

L = log.get("mcp")
WIN = sys.platform.startswith("win")
REPO = ROOT.parent  # Heloo klasörü: filesystem ve git sunucularının izinli yolu


def _npx(*args: str) -> dict:
    # Windows'ta npx bir .cmd dosyasıdır; Claude Code onu doğrudan başlatamaz
    return {"command": "cmd", "args": ["/c", "npx", "-y", *args]} if WIN else {"command": "npx", "args": ["-y", *args]}


def _uvx() -> str | None:
    found = shutil.which("uvx")
    if found:
        return found
    import sysconfig
    user_scripts = Path(sysconfig.get_path("scripts", f"{os.name}_user"))   # pip install --user (ör. AppData\Roaming)
    for d in (Path(sys.executable).parent, Path(sys.executable).parent / "Scripts", user_scripts):
        for name in ("uvx.exe", "uvx"):
            if (d / name).is_file():
                return str(d / name)
    return None


def _python() -> str:
    """MCP stdio ister: uygulama pythonw.exe (penceresiz) ile çalışıyorsa yanındaki python.exe kullanılır."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return str(exe)


def _graphify(graph: Path) -> dict | None:
    """Graphify MCP sunucusu (graph.json'u sorgulanabilir yapar); paket kurulu ve harita varsa."""
    import importlib.util
    if not graph.is_file() or importlib.util.find_spec("graphify") is None:
        return None
    return {"type": "stdio", "command": _python(), "args": ["-m", "graphify.serve", str(graph)]}


def _premiere() -> dict | None:
    """Premiere Pro MCP (leancoderkavy/premiere-pro-mcp, MIT): yalnızca paket kurulu ve Premiere Pro varsa eklenir."""
    exe = shutil.which("premiere-pro-mcp")
    if not exe:
        return None
    if WIN:
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe"
        if not any(pf.glob("Adobe Premiere Pro*")):
            return None
        return {"type": "stdio", "command": "cmd", "args": ["/c", "premiere-pro-mcp"]}
    if sys.platform == "darwin" and not any(Path("/Applications").glob("Adobe Premiere Pro*")):
        return None
    return {"type": "stdio", "command": exe, "args": []}


def servers() -> list[tuple[str, dict | None, str]]:
    """(ad, yapılandırma ya da None, not) listesi; None: eksik gereksinim nedeniyle atlanır."""
    uvx = _uvx()
    brave, pg, gh, c7 = (secret(k) for k in ("BRAVE_API_KEY", "POSTGRES_DSN", "GITHUB_PAT", "CONTEXT7_API_KEY"))
    memory = ROOT / "knowledge" / "claude-memory.jsonl"
    rows: list[tuple[str, dict | None, str]] = [
        ("reels-fabrikasi", {"type": "stdio", "command": _python(),
                             "args": [str(ROOT / "app" / "mcp_server.py")]}, "video üret, sesi iyileştir, stüdyo, yayın kuyruğu"),
        ("playwright", {"type": "stdio", **_npx("@playwright/mcp@latest")},
         "tarayıcı otomasyonu (Instagram/TikTok'ta beğeni/yorum için kullanılmaz)"),
        ("memory", {"type": "stdio", **_npx("@modelcontextprotocol/server-memory"),
                    "env": {"MEMORY_FILE_PATH": str(memory)}}, f"kalıcı bellek: {memory.name}"),
        ("filesystem", {"type": "stdio", **_npx("@modelcontextprotocol/server-filesystem", str(REPO))},
         f"izinli klasör: {REPO}"),
        ("fetch", {"type": "stdio", "command": uvx, "args": ["mcp-server-fetch"]} if uvx else None,
         "URL → markdown" if uvx else "uv kurulu değil (python -m pip install uv)"),
        ("git", {"type": "stdio", "command": uvx, "args": ["mcp-server-git", "--repository", str(REPO)]} if uvx
         else None, f"depo: {REPO}" if uvx else "uv kurulu değil (python -m pip install uv)"),
        ("github", {"type": "http", "url": "https://api.githubcopilot.com/mcp/",
                    **({"headers": {"Authorization": f"Bearer {gh}"}} if gh else {})},
         "GITHUB_PAT ile" if gh else "belirteçsiz: Claude Code'da /mcp ile GitHub girişi"),
        ("sentry", {"type": "http", "url": "https://mcp.sentry.dev/mcp"}, "Claude Code'da /mcp ile Sentry girişi"),
        ("context7", {"type": "http", "url": "https://mcp.context7.com/mcp", "headers": {"CONTEXT7_API_KEY": c7}}
         if c7 else {"type": "stdio", **_npx("@upstash/context7-mcp")},
         "API anahtarıyla" if c7 else "anahtarsız yerel sürüm (düşük kota)"),
        ("graphify-icerik", _graphify(ROOT / "knowledge" / "corpus" / "graphify-out" / "graph.json"),
         "Graphify içerik haritası (işlenen konular, kavramlar)" if _graphify(ROOT / "knowledge" / "corpus" / "graphify-out" / "graph.json")
         else "içerik haritası henüz yok (panelde Bilgi haritası → Oluştur)"),
        ("graphify-kod", _graphify(ROOT / "scripts" / "graphify-out" / "graph.json"),
         "Graphify kod haritası (fabrika kodu)" if _graphify(ROOT / "scripts" / "graphify-out" / "graph.json")
         else "kod haritası yok (python -m graphify update scripts)"),
        ("premiere-pro", _premiere(), "Adobe Premiere Pro'yu yönetir (Premiere açık + MCP paneli)" if _premiere()
         else "Premiere Pro ya da premiere-pro-mcp yok (scripts/install-premiere-mcp.ps1)"),
        ("brave-search", {"type": "stdio", **_npx("@brave/brave-search-mcp-server"), "env": {"BRAVE_API_KEY": brave}}
         if brave else None, "web/görsel/video/haber araması" if brave else "BRAVE_API_KEY yok (ücretsiz anahtar)"),
        ("postgres", {"type": "stdio", **_npx("@bytebase/dbhub", "--readonly", "--dsn", pg)} if pg else None,
         "salt okunur SQL" if pg else "POSTGRES_DSN yok (bağlanılacak veritabanı)"),
    ]
    return rows


def register() -> dict:
    """Sunucuları Claude Code'a ekler/günceller. Sonuç: {ok, rows:[{name, status, note}], message}."""
    exe = claude_cli()
    if not exe:
        return {"ok": False, "rows": [], "message": "Claude Code kurulu değil — önce kurun"}
    rows = []
    for name, conf, note in servers():
        if conf is None:
            rows.append({"name": name, "status": "atlandı", "note": note})
            continue
        subprocess.run([exe, "mcp", "remove", "-s", "user", name], capture_output=True, timeout=60,  # noqa: S603
                       stdin=subprocess.DEVNULL)
        # Aynı ad bu klasörlerde "local" kapsamda da kayıtlıysa Claude Code "Conflicting scopes" uyarısı verir
        for cwd in (REPO, ROOT):
            subprocess.run([exe, "mcp", "remove", "-s", "local", name], capture_output=True,  # noqa: S603
                           timeout=60, stdin=subprocess.DEVNULL, cwd=str(cwd))
        p = subprocess.run([exe, "mcp", "add-json", "-s", "user", name, json.dumps(conf)],  # noqa: S603
                           capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                           stdin=subprocess.DEVNULL)
        ok = p.returncode == 0
        rows.append({"name": name, "status": "eklendi" if ok else "hata",
                     "note": note if ok else (p.stderr or p.stdout).strip()[-200:]})
    added = sum(r["status"] == "eklendi" for r in rows)
    L.info("MCP sunucuları: %d eklendi, %d atlandı", added, sum(r["status"] == "atlandı" for r in rows))
    return {"ok": all(r["status"] != "hata" for r in rows), "rows": rows,
            "message": f"{added} MCP sunucusu Claude Code'a eklendi; Claude Code'u yeniden başlatın"}
