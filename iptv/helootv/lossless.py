"""Lossless Scaling (THS, Steam 993090) ile birlikte çalışma.

Lossless Scaling ücretli, kapalı kaynaklı bir Windows uygulamasıdır; Heloo TV onu içermez ve değiştirmez. Kullanıcının
bilgisayarında kuruluysa bulur, çalıştırır ve "Ölçekle" kısayolunu (varsayılan Ctrl+Alt+S) Heloo TV penceresi öndeyken
gönderir. Önerilen kullanım: Lossless Scaling'de **ölçekleme Kapalı** (büyütmeyi RTX VSR yapar), **kare üretimi
LSFG 3 ×2** — 25/30 fps TV yayını 50/60 fps akıcılığında görünür. Bu sırada mpv'nin kendi interpolasyonu kapatılır.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

APP_ID = 993090
EXE = "LosslessScaling.exe"
STORE_URL = "https://store.steampowered.com/app/993090/Lossless_Scaling/"
DEFAULT_HOTKEY = "Ctrl+Alt+S"

# Windows sanal tuş kodları
_MODS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}
_NAMED = {**{f"f{i}": 0x6F + i for i in range(1, 25)}, "space": 0x20, "enter": 0x0D, "tab": 0x09,
          "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22}


def parse_hotkey(text: str) -> tuple[list[int], int]:
    """'Ctrl+Alt+S' → ([VK_CONTROL, VK_MENU], ord('S')). Geçersizse ValueError."""
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", text or "") if p.strip()]
    if not parts:
        raise ValueError("boş kısayol")
    mods, key = [], parts[-1]
    for p in parts[:-1]:
        if p not in _MODS:
            raise ValueError(f"bilinmeyen değiştirici: {p}")
        mods.append(_MODS[p])
    if key in _NAMED:
        vk = _NAMED[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"bilinmeyen tuş: {key}")
    return mods, vk


def mpv_key(shortcut: str) -> str:
    """'Ctrl+Z' → 'ctrl+z' (mpv input.conf adı; video penceresi odaktayken de kısayol çalışsın). Geçersizse ''."""
    try:
        mods, vk = parse_hotkey(shortcut)
    except ValueError:
        return ""
    names = {0x11: "ctrl", 0x12: "alt", 0x10: "shift", 0x5B: "meta"}
    key = shortcut.split("+")[-1].strip()
    key = key.lower() if len(key) == 1 else key.upper()
    return "+".join([names[m] for m in mods] + [key])


def steam_libraries(steam_root: Path) -> list[Path]:
    """steamapps/libraryfolders.vdf içindeki tüm kütüphane klasörleri (+ Steam'in kendisi)."""
    libs = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)
    return libs


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
    return list(dict.fromkeys(roots))


def find_exe(custom: str = "", roots: list[Path] | None = None) -> str | None:
    if custom and Path(custom).is_file():
        return custom
    for root in (roots if roots is not None else _steam_roots()):
        for lib in steam_libraries(root):
            p = lib / "steamapps" / "common" / "Lossless Scaling" / EXE
            if p.is_file():
                return str(p)
    return None


def is_running() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True, text=True,
                             timeout=5, creationflags=0x08000000).stdout
    except Exception:
        return False
    return EXE.lower() in out.lower()


def launch(exe: str) -> None:
    """Steam'den başlatılırsa lisans denetimi sorunsuz olur; yoksa doğrudan."""
    if sys.platform.startswith("win"):
        try:
            os.startfile(f"steam://rungameid/{APP_ID}")  # noqa: S606 — kullanıcının kendi Steam'i
            return
        except OSError:
            pass
    subprocess.Popen([exe], cwd=str(Path(exe).parent))


def send_hotkey(hotkey: str) -> None:
    """Kısayolu sistem geneline basar (Lossless Scaling genel kısayol dinler; öndeki pencereyi ölçekler)."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("Lossless Scaling yalnız Windows'ta çalışır")
    import ctypes
    mods, vk = parse_hotkey(hotkey)
    user32 = ctypes.windll.user32
    KEYUP = 0x0002
    for m in mods:
        user32.keybd_event(m, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYUP, 0)
    for m in reversed(mods):
        user32.keybd_event(m, 0, KEYUP, 0)


TIPS = ("Lossless Scaling'de önerilen ayar (Heloo TV profili):\n"
        "• Ölçekleme türü: Kapalı — 4K büyütmeyi RTX VSR zaten yapıyor (ikisi birlikte görüntüyü bozar)\n"
        "• Kare üretimi: LSFG 3, ×2 (25/30 fps yayın → 50/60 fps). Gecikmeyi düşük tutmak için 'Max frame latency' 1\n"
        "• Yakalama API'si: WGC; 'Draw FPS' isteğe bağlı\n"
        "• Kısayol Heloo TV ayarlarındakiyle aynı olmalı (varsayılan Ctrl+Alt+S)")
