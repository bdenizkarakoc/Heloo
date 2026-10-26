"""Dizin yolları. SELFEDIT_HOME ortam değişkeni ile taşınabilir (test ve sandbox için)."""
import os
from pathlib import Path


def code_root() -> Path:
    """selfedit paketinin bulunduğu klasörün üstü."""
    return Path(__file__).resolve().parent.parent


def root() -> Path:
    return Path(os.environ.get("SELFEDIT_HOME") or code_root())


def data() -> Path:
    p = root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def plugins() -> Path:
    p = Path(os.environ.get("SELFEDIT_PLUGINS") or (root() / "plugins"))
    p.mkdir(parents=True, exist_ok=True)
    return p
