"""Hızlı birim testleri (ağ yok, ücretli API yok). Çalıştır: python -m pytest tests -q (reels-factory klasöründen)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
