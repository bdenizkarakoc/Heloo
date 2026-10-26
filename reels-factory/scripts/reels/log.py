"""Log yapılandırması. Gizli değerler (API anahtarları) log kayıtlarından maskelenir."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import ROOT, secret_values

LOG_DIR = ROOT / "logs"
_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


class SecretFilter(logging.Filter):
    """Ortamdaki anahtar/token değerlerini log metninden çıkarır."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = secret_values()
        if not secrets:
            return True
        msg = record.getMessage()
        changed = False
        for value in secrets:
            if value in msg:
                msg = msg.replace(value, "***")
                changed = True
        if changed:
            record.msg = msg
            record.args = ()
        return True


_configured = False


def setup_logging(verbose: bool = False) -> logging.Logger:
    global _configured
    root = logging.getLogger("reels")
    if _configured:
        return root
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    console.addFilter(SecretFilter())
    root.addHandler(console)
    fh = logging.FileHandler(LOG_DIR / "factory.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT))
    fh.addFilter(SecretFilter())
    root.addHandler(fh)
    _configured = True
    return root


def attach_job_log(job_id: str) -> logging.Handler:
    """Her üretim görevi için ayrı bir log dosyası: logs/<job_id>.log"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_DIR / f"{job_id}.log", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FMT))
    handler.addFilter(SecretFilter())
    logging.getLogger("reels").addHandler(handler)
    return handler


def detach(handler: logging.Handler) -> None:
    logging.getLogger("reels").removeHandler(handler)
    handler.close()


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"reels.{name}")


def log_path(job_id: str) -> Path:
    return LOG_DIR / f"{job_id}.log"
