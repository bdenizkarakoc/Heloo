"""Ekran kartı algılama (NVIDIA / AMD / Intel) ve görüntü iyileştirme uygunluk değerlendirmesi.

NVIDIA RTX: RTX Video Super Resolution (d3d11vpp). AMD (ve diğerleri): AMD FidelityFX Super Resolution (FSR 1, MIT,
pakette `glsl/fsr.glsl`) + CAS keskinleştirme mpv'nin GPU işleyicisinde; kare üretimi için AMD Fluid Motion Frames
ya da Lossless Scaling."""
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


def vendor_of(name: str) -> str:
    n = (name or "").lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or re.search(r"\brtx\b", n):
        return "nvidia"
    if "amd" in n or "radeon" in n or "ati " in n:
        return "amd"
    if "intel" in n or "arc" in n.split():
        return "intel"
    return ""


def query_adapters() -> list[dict]:
    """Windows'taki bütün ekran kartları (Win32_VideoController): NVIDIA olmayan kartlar için."""
    if not sys.platform.startswith("win"):
        return []
    cmd = ("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM | "
           "ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                             text=True, timeout=15, creationflags=_creationflags()).stdout
        import json
        data = json.loads(out or "[]")
    except Exception:
        return []
    rows = data if isinstance(data, list) else [data]
    gpus = []
    for r in rows:
        name = str((r or {}).get("Name") or "").strip()
        if not name or "basic display" in name.lower() or "remote" in name.lower():
            continue
        ram = (r or {}).get("AdapterRAM") or 0
        gpus.append({"name": name, "driver": str(r.get("DriverVersion") or ""), "vendor": vendor_of(name),
                     "memory_mb": int(ram) // (1 << 20) if isinstance(ram, int) else 0})
    # öncelik: AMD (çoğunlukla harici kart) > Intel > diğer
    rank = {"amd": 0, "intel": 1}
    gpus.sort(key=lambda g: rank.get(g["vendor"], 2))
    return gpus


def query_gpus() -> list[dict]:
    """Önce NVIDIA (nvidia-smi); yoksa Windows'taki AMD/Intel kartları."""
    exe = nvidia_smi_path()
    if not exe:
        return query_adapters()
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
            gpus.append({"name": parts[0], "driver": parts[1], "memory_mb": mem, "vendor": "nvidia"})
    return gpus or query_adapters()


def _driver_tuple(text: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def assess(gpu: dict | None, platform: str = sys.platform) -> dict:
    """RTX VSR / RTX HDR uygunluğu ve kullanıcıya Türkçe öneriler."""
    out = {"vsr": False, "hdr": False, "notes": [], "vendor": (gpu or {}).get("vendor") or vendor_of((gpu or {}).get("name", ""))}
    if not platform.startswith("win"):
        out["notes"].append("RTX Video Super Resolution yalnızca Windows'ta çalışır; bu sistemde mpv'nin yüksek kaliteli "
                            "ölçekleyicisi (ewa_lanczossharp) kullanılır.")
        return out
    if not gpu:
        out["notes"].append("Ekran kartı tanınamadı. Görüntü AMD FSR + keskinlik ile iyileştirilir (her kartta çalışır).")
        return out
    if out["vendor"] == "amd":
        out["notes"].append(f"{gpu.get('name')}: AMD kartta görüntü AMD FidelityFX Super Resolution (FSR) + CAS keskinlik "
                            "ile 4K'ya büyütülür (canlı yayın dahil), deinterlace GPU'da yapılır.")
        out["notes"].append("Akıcılık için AMD Software (Adrenalin) → Oyun → Grafik → 'AMD Fluid Motion Frames' açılabilir "
                            "ya da Lossless Scaling kullanılabilir. AFMF kullanırken Ayarlar → 'Film/dizide akıcı oynatma'yı "
                            "kapatın (iki ara kare üretimi titreme yapar); Lossless Scaling'de Heloo TV bunu kendisi yapar.")
        return out
    if out["vendor"] == "intel":
        out["notes"].append(f"{gpu.get('name')}: görüntü AMD FSR (her kartta çalışır) ya da yapay zekâ büyütücü + keskinlik "
                            "ile iyileştirilir.")
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
