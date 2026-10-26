"""Kullanıcı ayarları (data/config.json)."""
import json

from . import paths

DEFAULTS = {
    # approve: iyileştirmeler doğrulanır, sen onaylayınca uygulanır (önerilen)
    # auto:    doğrulamayı geçen iyileştirmeler kendiliğinden uygulanır
    "mode": "approve",
    "interval_minutes": 60,
    "max_per_day": 4,
    "max_pending": 5,
    "model": "claude-sonnet-5-5",
}
MODES = ("approve", "auto")


def _file():
    return paths.data() / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(_file().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict) -> None:
    _file().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def set_value(key: str, value) -> dict:
    if key not in DEFAULTS:
        raise KeyError(f"Bilinmeyen ayar: {key}")
    if key == "mode" and value not in MODES:
        raise ValueError(f"mode şunlardan biri olmalı: {', '.join(MODES)}")
    if isinstance(DEFAULTS[key], int):
        value = int(value)
    cfg = load()
    cfg[key] = value
    save(cfg)
    return cfg
