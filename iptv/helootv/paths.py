"""Uygulama klasörleri: veri (ayarlar, veritabanı, önbellek) ve indirilen ikili dosyalar (libmpv)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Kodun bulunduğu iptv/ klasörü."""
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    env = os.environ.get("HELOOTV_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "HelooTV"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "HelooTV"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "helootv"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bin_dir() -> Path:
    """libmpv-2.dll, mpv.exe ve 7zr.exe burada durur (tools/fetch_mpv.py indirir)."""
    env = os.environ.get("HELOOTV_BIN")
    return Path(env) if env else app_dir() / "bin"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def db_path() -> Path:
    return data_dir() / "helootv.db"


def log_path() -> Path:
    return data_dir() / "helootv.log"


def prepare_libmpv_search_path() -> None:
    """python-mpv `import mpv` öncesinde libmpv-2.dll'i bulabilsin diye bin/ klasörünü PATH'e ekler."""
    b = bin_dir()
    if b.is_dir():
        os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(b))
            except OSError:
                pass
