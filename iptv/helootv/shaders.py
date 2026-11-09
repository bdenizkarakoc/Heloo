"""Yapay zekâ büyütücü shader'ları (mpv/libplacebo .glsl). RTX VSR çalışmadığında (fotoğraf, NVIDIA olmayan kart,
sürücüde VSR kapalı) ve 4K dışa aktarmada kullanılır. Dosyalar GitHub'dan bin/shaders altına indirilir."""
from __future__ import annotations

from pathlib import Path

from . import paths

SHADERS = {
    # canlı çekim (TV, film, dizi) — igv/FSRCNN-TensorFlow sürüm dosyası
    "fsrcnnx": {"file": "FSRCNNX_x2_8-0-4-1.glsl", "repo": "igv/FSRCNN-TensorFlow",
                "label": "FSRCNNX (canlı çekim: TV, film, dizi)"},
    # çizgi film / anime — Artoriuz/ArtCNN (MIT), gürültü azaltıp keskinleştiren DS modeli
    "artcnn": {"file": "ArtCNN_C4F16_DS.glsl",
               "url": "https://raw.githubusercontent.com/Artoriuz/ArtCNN/v1.6.2/GLSL/ArtCNN_C4F16_DS.glsl",
               "label": "ArtCNN (çizgi film, anime)"},
}


def shader_dir() -> Path:
    return paths.bin_dir() / "shaders"


def resolve(name: str | None) -> Path | None:
    """Seçilen modelin dosyası; yoksa indirilmiş diğer model; hiçbiri yoksa None."""
    if not name or name == "off":
        return None
    order = [name] + [k for k in SHADERS if k != name]
    for key in order:
        if key in SHADERS:
            p = shader_dir() / SHADERS[key]["file"]
            if p.is_file() and p.stat().st_size > 1000:
                return p
    return None
