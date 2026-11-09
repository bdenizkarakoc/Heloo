"""NVIDIA ekran kartı algılama ve RTX Video (VSR / HDR) uygunluk değerlendirmesi."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

# Sürücü alt sınırları (NVIDIA sürüm notları): VSR 531.18 (RTX 30/40), RTX 20 desteği 545.84, RTX Video HDR 551.23.
VSR_MIN_DRIVER = (531, 18)
VSR_MIN_DRIVER_TURING = (545, 84)
HDR_MIN_DRIVER = (551, 23)


def _creationflags() -> int:
    return 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def nvidia_smi_path() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.name == "nt":
        for p in (r"C:\Windows\System32\nvidia-smi.exe",
                  r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.isfile(p):
                return p
    return None


def query_gpus() -> list[dict]:
    exe = nvidia_smi_path()
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=6, creationflags=_creationflags())
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            mem = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            gpus.append({"name": parts[0], "driver": parts[1], "memory_mb": mem})
    return gpus


def _driver_tuple(text: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def assess(gpu: dict | None, platform: str = sys.platform) -> dict:
    """RTX VSR / RTX HDR uygunluğu ve kullanıcıya Türkçe öneriler."""
    out = {"vsr": False, "hdr": False, "notes": []}
    if not platform.startswith("win"):
        out["notes"].append("RTX Video Super Resolution yalnızca Windows'ta çalışır; bu sistemde mpv'nin yüksek kaliteli "
                            "ölçekleyicisi (ewa_lanczossharp) kullanılır.")
        return out
    if not gpu:
        out["notes"].append("NVIDIA ekran kartı bulunamadı (nvidia-smi yok). RTX VSR için GeForce RTX 20/30/40/50 serisi "
                            "ve güncel sürücü gerekir.")
        return out
    name = gpu.get("name", "")
    drv = _driver_tuple(gpu.get("driver", ""))
    is_rtx = bool(re.search(r"\bRTX\b", name, re.I))
    turing = bool(re.search(r"RTX\s*20\d\d|TITAN RTX|Quadro RTX", name, re.I))
    if not is_rtx:
        out["notes"].append(f"{name}: RTX olmayan kartta Video Super Resolution yok; yüksek kaliteli ölçekleyici "
                            "kullanılır.")
        return out
    need = VSR_MIN_DRIVER_TURING if turing else VSR_MIN_DRIVER
    if drv < need:
        out["notes"].append(f"Sürücü {gpu.get('driver')} eski: RTX VSR için en az {need[0]}.{need[1]:02d} gerekir. "
                            "NVIDIA App ile güncelleyin.")
    else:
        out["vsr"] = True
    out["hdr"] = drv >= HDR_MIN_DRIVER
    out["notes"].append("NVIDIA App → Sistem → Video → RTX Video Enhancement: 'Super Resolution' açık, kalite "
                        "'Otomatik' ya da 4 (RTX xx70 ve üstü). HDR ekranda 'High Dynamic Range' de açılabilir.")
    return out


def cpu_has_avx2() -> bool:
    """mpv x86-64-v3 derlemesi (AVX2) seçimi için."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # PF_AVX2_INSTRUCTIONS_AVAILABLE
        except Exception:
            return False
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            return " avx2 " in f.read().replace("\n", " ")
    except OSError:
        return False


def open_nvidia_settings() -> bool:
    """NVIDIA App ya da Denetim Masası'nı açar (Windows)."""
    if os.name != "nt":
        return False
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\NVIDIA Corporation\NVIDIA App\CEF\NVIDIA App.exe"),
        os.path.expandvars(r"%ProgramFiles%\NVIDIA Corporation\Control Panel Client\nvcplui.exe"),
    ]
    for exe in candidates:
        if os.path.isfile(exe):
            try:
                subprocess.Popen([exe], close_fds=True)
                return True
            except OSError:
                continue
    try:
        os.startfile("shell:AppsFolder\\NVIDIACorp.NVIDIAControlPanel_56jybvy8sckqj!NVIDIACorp.NVIDIAControlPanel")  # type: ignore[attr-defined]
        return True
    except OSError:
        return False
