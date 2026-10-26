"""Ayarların ve ortam değişkenlerinin yüklenmesi.

API anahtarları yalnızca ortam değişkenlerinden veya .env dosyasından okunur;
settings.yaml içine gizli bilgi yazılmaz.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "settings.yaml"

# İsimleri bu kalıplara uyan ortam değişkenleri gizli kabul edilir ve loglarda maskelenir.
SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")

KNOWN_KEYS = (
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "PEXELS_API_KEY",
    "OPENAI_API_KEY",
    "REPLICATE_API_TOKEN",
)


def load_dotenv(path: Path | None = None) -> None:
    """Basit .env okuyucu: mevcut ortam değişkenlerinin üzerine yazmaz."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def set_secret(name: str, value: str) -> None:
    """Bir gizli değeri .env dosyasına yazar (varsa günceller) ve bu oturumda etkinleştirir.

    Uygulamadaki hesap bağlama ekranları kullanır; değer loglara yazılmaz (SecretFilter)."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", name or ""):
        raise ValueError("geçersiz anahtar adı")
    value = (value or "").strip().replace("\n", "").replace("\r", "")
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == name:
            if not done and value:
                out.append(f"{name}={value}")
            done = True
        else:
            out.append(line)
    if not done and value:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def secret(name: str) -> str | None:
    """Bir API anahtarını döndürür; tanımlı değilse None."""
    value = os.environ.get(name, "").strip()
    return value or None


def secret_values() -> list[str]:
    values = []
    for key, value in os.environ.items():
        if value and len(value) >= 8 and any(h in key.upper() for h in SECRET_ENV_HINTS):
            values.append(value)
    return values


class Config(dict):
    """Noktalı yol ile erişilebilen ayar sözlüğü: cfg.get_path("tts.edge.rate")."""

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p


def load_config(path: Path | None = None) -> Config:
    load_dotenv()
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config(data)
