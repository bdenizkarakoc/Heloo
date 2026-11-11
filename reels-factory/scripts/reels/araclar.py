"""Araçlar: açık kaynak video otomasyon projelerini indirir, kurar, başlatır (`factory.py araclar`, `/araclar` sayfası).

Her araç `araclar/<ad>/` altına kendi deposundan indirilir (git, sabit sürüm) ve KENDİ ortamına kurulur
(`.venv` / `node_modules`); fabrikanın Python ortamına paket kurulmaz, kodları bu depoya eklenmez
(`araclar/` .gitignore'da). Lisansları farklıdır (AGPL/LGPL dahil): ayrı program olarak çalışırlar,
kodları fabrikaya kopyalanmaz. API anahtarı isteyen araçların anahtarı kendi ayar dosyasına/sayfasına girilir.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import log
from .config import ROOT

L = log.get("araclar")
DIR = ROOT / "araclar"
STATE = DIR / "durum.json"
WIN = sys.platform.startswith("win")
_LOCK = threading.Lock()
_BUSY: dict[str, str] = {}          # ad → şu an çalışan kurulum adımı
_PROCS: dict[str, subprocess.Popen] = {}

# {py}: aracın kendi .venv Python'u. Adım: (klasör, komut). Sürüm: denetlenen commit (araclar --guncel en yenisini alır).
TOOLS: dict[str, dict] = {
    "openmontage": {
        "ad": "OpenMontage", "repo": "https://github.com/OpenMontageInc/OpenMontage", "lisans": "AGPL-3.0",
        "surum": "fecb9a1e3cc23ef84de30b272059457a427f16f8",
        "ne": "Ajanla video prodüksiyonu: 12 üretim hattı, 100+ araç. Klasörünü Claude Code'da açıp ne istediğini yazarsın; "
              "Backlot panosu üretimi canlı gösterir.",
        "gerek": ["uv", "npm"],
        "kur": [(".", ["uv", "venv", ".venv", "--python", "3.12"]),
                (".", ["uv", "pip", "install", "--python", "{py}", "-r", "requirements.txt"]),
                ("remotion-composer", ["npm", "install", "--no-audit", "--no-fund"])],
        "calistir": (".", ["{py}", "-m", "backlot", "serve", "--port", "4750"]), "port": 4750,
        "kullan": "Claude Code'u araclar/openmontage klasöründe aç ve videoyu tarif et (anahtarsız yol: Piper + FFmpeg + Remotion).",
    },
    "moneyprinterturbo": {
        "ad": "MoneyPrinterTurbo", "repo": "https://github.com/harry0703/MoneyPrinterTurbo", "lisans": "MIT",
        "surum": "53c4ca3d85100eeb8660ec3d5e5f7c90bcc7849a",
        "ne": "Konu yaz → senaryo, seslendirme, stok görüntü, altyazı ile kısa video. Kendi web arayüzü var.",
        "gerek": ["uv"],
        "kur": [(".", ["uv", "sync", "--frozen"])],
        "calistir": (".", ["uv", "run", "--frozen", "streamlit", "run", "webui/Main.py", "--server.address=127.0.0.1",
                           "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=False"]),
        "port": 8501,
        "kullan": "Arayüzde LLM ve stok görüntü (Pexels/Pixabay) anahtarlarını gir; anahtarlar araclar/moneyprinterturbo/config.toml'a yazılır.",
    },
    "vimax": {
        "ad": "ViMax", "repo": "https://github.com/HKUDS/ViMax", "lisans": "MIT",
        "surum": "fd4b72e7731be6e5f88486206d25ea59849b0285",
        "ne": "Fikirden çok çekimli hikâye videosu (yönetmen + senarist + yapımcı ajanları). Görüntü/video modeli anahtarı ister.",
        "gerek": ["uv", "npm"],
        "kur": [(".", ["uv", "sync"]), ("web", ["npm", "install", "--no-audit", "--no-fund"])],
        "calistir": ("web", ["npm", "run", "dev"]), "port": 4173,
        "kullan": "Arayüzde sağlayıcı ayarlarına LLM, görsel ve video modeli anahtarlarını gir (ücretli API; her üretim kredi harcar).",
    },
    "shotcraft": {
        "ad": "Video-Shotcraft", "repo": "https://github.com/Vincentwei1021/video-shotcraft", "lisans": "Apache-2.0",
        "surum": "3ac67b75dd0b3bc2fd807c17f6b7ce35373eef3d",
        "ne": "Ürün tanıtım videosu becerisi: 124 çekim tarifi kartı + Remotion şablonu + tarayıcıda hareket tezgâhı.",
        "gerek": ["npm"],
        "kur": [("template", ["npm", "install", "--no-audit", "--no-fund"]),
                ("workbench", ["npm", "install", "--no-audit", "--no-fund"])],
        "calistir": ("workbench", ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5273", "--strictPort"]),
        "port": 5273,
        "kullan": "Claude Code'da /tanitim <ürün> yaz; beceri araclar/shotcraft/SKILL.md akışını izler.",
    },
    "toonflow": {
        "ad": "Toonflow", "repo": "https://github.com/HBAI-Ltd/Toonflow-app", "lisans": "MIT",
        "surum": "6086cdffceb704a632eca143dd16cd461a78cdac",
        "ne": "Uzun metinden (roman, hikâye) kısa dizi/çizgi roman: senaryo, storyboard, karakter, görsel ve video; sonsuz tuval.",
        "gerek": ["bun"],
        "kur": [(".", ["bun", "install", "--frozen-lockfile"]), (".", ["bun", "run", "build:server"])],
        "calistir": (".", ["bun", "run", "start:server"]), "port": 3000,
        "kullan": "Arayüzde model hizmeti anahtarlarını gir (ya da yerel ComfyUI/LLM bağla).",
    },
    "do-mpc": {
        "ad": "do-mpc", "repo": "https://github.com/do-mpc/do-mpc", "lisans": "LGPL-3.0",
        "surum": "9d5a8df0e4d6acac899bf0a65ffd4c30a6e2e4cc",
        "ne": "Model Öngörülü Kontrol (MPC) Python kitaplığı — kontrol mühendisliği içindir, video üretimiyle ilgisi yok "
              "(MCP sunucuları için: factory.py mcp).",
        "gerek": ["uv"],
        "kur": [(".", ["uv", "venv", ".venv", "--python", "3.12"]),
                (".", ["uv", "pip", "install", "--python", "{py}", "-e", "."])],
        "calistir": None, "port": None,
        "kullan": "Kitaplık: araclar/do-mpc/.venv Python'u ile `import do_mpc`; örnekler araclar/do-mpc/examples.",
    },
}

INSTALL_HINT = {"uv": "pip install uv", "npm": "Node.js kur (nodejs.org)", "bun": "bun.sh → kurulum komutu", "git": "git-scm.com"}


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(name: str, **kw) -> None:
    with _LOCK:
        st = _state()
        st.setdefault(name, {}).update(kw)
        DIR.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def tool_dir(name: str) -> Path:
    return DIR / name


def venv_python(name: str) -> Path:
    d = tool_dir(name) / ".venv"
    return d / "Scripts" / "python.exe" if WIN else d / "bin" / "python"


def _exe(cmd: str) -> str | None:
    """Windows'ta npm/bun birer .cmd dosyasıdır: tam yolu bulunur (kabuk kullanılmaz)."""
    found = shutil.which(cmd)
    if found:
        return found
    if cmd == "uv":  # pip install --user uv → PATH dışında kalabilir
        import sysconfig
        for d in (Path(sys.executable).parent, Path(sys.executable).parent / "Scripts",
                  Path(sysconfig.get_path("scripts", f"{os.name}_user"))):
            for n in ("uv.exe", "uv"):
                if (d / n).is_file():
                    return str(d / n)
    return None


def missing(name: str) -> list[str]:
    return [g for g in ["git", *TOOLS[name]["gerek"]] if not _exe(g)]


def _argv(name: str, argv: list[str]) -> list[str]:
    out = [a.replace("{py}", str(venv_python(name))) for a in argv]
    if out[0] in ("uv", "npm", "bun", "git"):
        out[0] = _exe(out[0]) or out[0]
    return out


def _log_path(name: str) -> Path:
    (DIR / "logs").mkdir(parents=True, exist_ok=True)
    return DIR / "logs" / f"{name}.log"


def _run(name: str, cwd: Path, argv: list[str], timeout: int = 3600) -> None:
    line = " ".join(argv)
    _BUSY[name] = line
    with _log_path(name).open("a", encoding="utf-8") as fh:
        fh.write(f"\n$ ({cwd.name}) {line}\n")
        fh.flush()
        r = subprocess.run(_argv(name, argv), cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f"{line} → çıkış kodu {r.returncode} (ayrıntı: araclar/logs/{name}.log)")


def download(name: str, latest: bool = False) -> Path:
    """Depoyu araclar/<ad> altına indirir: sabit sürüm (denetlenen commit) ya da --guncel ile en yenisi."""
    t, d = TOOLS[name], tool_dir(name)
    DIR.mkdir(parents=True, exist_ok=True)
    if not (d / ".git").is_dir():
        if d.exists() and any(d.iterdir()):
            raise RuntimeError(f"{d} dolu ama git deposu değil; elle bak (silinmedi).")
        _run(name, DIR, ["git", "clone", "--depth", "1", t["repo"], name])
    ref = "HEAD" if latest else t["surum"]
    try:
        _run(name, d, ["git", "fetch", "--depth", "1", "origin", ref])
        _run(name, d, ["git", "checkout", "--detach", "FETCH_HEAD"])
    except RuntimeError:
        if latest:
            raise
        L.warning("%s: sabit sürüm alınamadı, indirilen sürüm kullanılıyor", name)
    sha = subprocess.run(_argv(name, ["git", "rev-parse", "HEAD"]), cwd=d, capture_output=True, text=True).stdout.strip()
    _save(name, commit=sha, downloaded=time.strftime("%Y-%m-%d %H:%M"))
    return d


def install(name: str, latest: bool = False) -> dict:
    """İndir + kur. Başarısız adım kaydedilir; yeniden çağrılınca kaldığı yerden değil baştan (adımlar yinelenebilir) dener."""
    if name not in TOOLS:
        return {"ok": False, "name": name, "message": f"Bilinmeyen araç: {name} (seçenekler: {', '.join(TOOLS)})"}
    if name in _BUSY:
        return {"ok": False, "name": name, "message": "Kurulum zaten sürüyor."}
    miss = missing(name)
    if miss:
        msg = "Eksik: " + "; ".join(f"{m} ({INSTALL_HINT[m]})" for m in miss)
        _save(name, installed=False, error=msg)
        return {"ok": False, "name": name, "message": msg}
    _BUSY[name] = "indiriliyor"
    try:
        d = download(name, latest)
        for sub, argv in TOOLS[name]["kur"]:
            _run(name, d / sub, argv)
        _save(name, installed=True, error="", installed_at=time.strftime("%Y-%m-%d %H:%M"))
        L.info("%s kuruldu: %s", name, d)
        return {"ok": True, "name": name, "message": f"Kuruldu: {d}"}
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        _save(name, installed=False, error=str(exc))
        L.error("%s kurulamadı: %s", name, exc)
        return {"ok": False, "name": name, "message": str(exc)}
    finally:
        _BUSY.pop(name, None)


def install_async(name: str, latest: bool = False) -> dict:
    if name not in TOOLS:
        return {"ok": False, "message": f"Bilinmeyen araç: {name}"}
    if name in _BUSY:
        return {"ok": False, "message": "Kurulum zaten sürüyor."}
    threading.Thread(target=install, args=(name, latest), daemon=True, name=f"arac-kur-{name}").start()
    return {"ok": True, "message": "Kurulum başladı (birkaç dakika sürebilir)."}


def _alive(port: int | None) -> bool:
    if not port:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5):
            return True
    except urllib.error.HTTPError:
        return True          # yanıt veriyor (ör. 404): sunucu ayakta
    except OSError:
        return False


def start(name: str, wait: float = 60) -> dict:
    """Aracın kendi arayüzünü yalnızca bu bilgisayarda (127.0.0.1) başlatır; adresi döndürür."""
    t = TOOLS.get(name)
    if not t:
        return {"ok": False, "message": f"Bilinmeyen araç: {name}"}
    if not t["calistir"]:
        return {"ok": False, "message": t["kullan"]}
    if not _state().get(name, {}).get("installed"):
        return {"ok": False, "message": f"Önce kur: factory.py araclar kur {name}"}
    url = f"http://127.0.0.1:{t['port']}"
    if _alive(t["port"]):
        return {"ok": True, "url": url, "message": f"Zaten çalışıyor: {url}"}
    sub, argv = t["calistir"]
    env = {**os.environ, "BROWSER": "none", "VIMAX_WEB_PORT": str(t["port"]), "PORT": str(t["port"])}
    fh = _log_path(name).open("a", encoding="utf-8")
    fh.write(f"\n$ ({sub}) {' '.join(argv)}\n")
    fh.flush()
    proc = subprocess.Popen(_argv(name, argv), cwd=tool_dir(name) / sub, stdout=fh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, start_new_session=not WIN)
    _PROCS[name] = proc
    _save(name, pid=proc.pid)
    end = time.time() + wait
    while time.time() < end:
        if _alive(t["port"]):
            return {"ok": True, "url": url, "message": f"Çalışıyor: {url}"}
        if proc.poll() is not None:
            return {"ok": False, "message": f"Başlamadı (çıkış kodu {proc.returncode}); araclar/logs/{name}.log dosyasına bak."}
        time.sleep(1)
    return {"ok": False, "url": url, "message": f"Henüz yanıt vermiyor; birazdan dene: {url}"}


def stop(name: str) -> dict:
    proc = _PROCS.pop(name, None)
    if not proc or proc.poll() is not None:
        return {"ok": True, "message": "Bu uygulamanın başlattığı çalışan süreç yok."}
    try:
        if WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
    return {"ok": True, "message": "Durduruldu."}


def status(probe: bool = True) -> list[dict]:
    st = _state()
    rows = []
    for name, t in TOOLS.items():
        s = st.get(name, {})
        rows.append({
            "name": name, "ad": t["ad"], "repo": t["repo"], "lisans": t["lisans"], "ne": t["ne"], "kullan": t["kullan"],
            "downloaded": (tool_dir(name) / ".git").is_dir(), "installed": bool(s.get("installed")),
            "commit": (s.get("commit") or "")[:10], "error": s.get("error", ""), "busy": _BUSY.get(name, ""),
            "missing": missing(name), "runnable": bool(t["calistir"]),
            "url": f"http://127.0.0.1:{t['port']}" if t["port"] else "",
            "running": bool(probe and s.get("installed") and _alive(t["port"])),
        })
    return rows


def log_tail(name: str, chars: int = 4000) -> str:
    p = DIR / "logs" / f"{name}.log"
    if name not in TOOLS or not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[-chars:]
