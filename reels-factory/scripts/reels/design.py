"""Tasarım temaları: her video farklı görünsün diye renk, yazı tipi, altyazı biçimi, geçiş seti ve görüntü efektleri.

Tema, `config/settings.yaml` → `design.themes.<ad>` altında ayar katmanıdır: içindeki anahtarlar (brand, captions,
design ...) ayarların üzerine yazılır. Görev için seçilen tema `job.json`'da saklanır (yeniden render aynı görünür).
Seçim: son videolarda kullanılmayan temalar arasından, kategoriye uygun olanlar öncelikli, sırayla.
"""
from __future__ import annotations

import copy

from . import log
from .config import Config

L = log.get("design")

# Temanın vermediği tasarım değerleri (şablonlar ve Remotion bunları okur)
DEFAULTS = {
    "caption_style": "stroke",     # stroke: konturlu; box: konuşulan kelime renkli kutuda; shadow: yumuşak gölge
    "headline_upper": True,        # başlıklar büyük harf
    "chip": "pill",                # pill: yuvarlak etiket; bar: düz şerit
    "grain": 0.0,                  # film greni (0-1)
    "vignette": 0.0,               # kenar karartma (0-1)
    "letterbox": False,            # sinema şeritleri (üst/alt)
    "scanlines": False,            # eski ekran tarama çizgileri
    "cam_filter": "",              # arka plana CSS filtresi (ör. "saturate(1.2) contrast(1.05)")
    "move_scale": 1.0,             # kamera hareketi şiddeti
    "transitions": [],             # boş: senaryodaki geçişler; dolu: yalnızca bunlar (sırayla)
    "progress": "top",             # top / bottom / none
}


def themes(cfg: Config) -> dict:
    return cfg.get_path("design.themes", {}) or {}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def pick(cfg: Config, category: str | None, history: list[dict]) -> str | None:
    """Son kullanılmayan, kategoriye uygun temayı seçer (deterministik: en uzun süredir kullanılmayan)."""
    th = themes(cfg)
    if not th or not cfg.get_path("design.rotate", True):
        return cfg.get_path("design.default") or None
    last_seen = {name: -1 for name in th}
    for i, h in enumerate(history):
        if h.get("design") in last_seen:
            last_seen[h["design"]] = i
    fits = [n for n, t in th.items() if not t.get("categories") or category in t.get("categories", [])] or list(th)
    # en uzun süredir kullanılmayan; eşitlikte kategoriye özel tema genel temadan önce gelir
    return min(fits, key=lambda n: (last_seen[n], 0 if th[n].get("categories") else 1, list(th).index(n)))


def apply(cfg: Config, name: str | None) -> Config:
    """Temanın ayar katmanını uygulanmış yeni bir Config döndürür (özgün değişmez)."""
    th = themes(cfg).get(name or "", {})
    data = _merge(dict(cfg), {k: v for k, v in th.items() if k not in ("label", "categories", "description", "look")})
    data.setdefault("design", {})
    data["design"]["active"] = {**DEFAULTS, **(data["design"].get("look") or {}), **(th.get("look") or {}),
                                "name": name or "", "label": th.get("label", name or "")}
    return Config(data)


def look(cfg: Config) -> dict:
    """Etkin temanın görsel değerleri (tema uygulanmamışsa varsayılanlar)."""
    return cfg.get_path("design.active") or {**DEFAULTS, **(cfg.get_path("design.look") or {}), "name": ""}
