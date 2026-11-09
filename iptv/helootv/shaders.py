"""Yapay zekâ büyütücü shader'ları (mpv/libplacebo .glsl). RTX VSR çalışmadığında (fotoğraf, NVIDIA olmayan kart,
sürücüde VSR kapalı) ve 4K dışa aktarmada kullanılır. Dosyalar GitHub'dan bin/shaders altına indirilir."""
from __future__ import annotations

from pathlib import Path

from . import paths

SHADERS = {
    # canlı çekim (TV, film, dizi) — igv/FSRCNN-TensorFlow sürüm dosyası
    "fsrcnnx": {"file": "FSRCNNX_x2_8-0-4-1.glsl", "repo": "igv/FSRCNN-TensorFlow",
                "fallback": "https://github.com/igv/FSRCNN-TensorFlow/releases/download/1.1/FSRCNNX_x2_8-0-4-1.glsl",
                "label": "FSRCNNX (canlı çekim: TV, film, dizi)"},
    # çizgi film / anime — Artoriuz/ArtCNN (MIT), gürültü azaltıp keskinleştiren DS modeli
    "artcnn": {"file": "ArtCNN_C4F16_DS.glsl",
               "url": "https://raw.githubusercontent.com/Artoriuz/ArtCNN/v1.6.2/GLSL/ArtCNN_C4F16_DS.glsl",
               "label": "ArtCNN (çizgi film, anime)"},
    # AMD FidelityFX Super Resolution 1.0.2 (AMD, MIT; mpv'ye agyild uyarladı) — pakette, indirme gerekmez.
    # AMD (ve Intel) kartlarda varsayılan; her GPU'da çalışır, hafiftir, canlı yayına gecikme eklemez.
    "fsr": {"file": "fsr.glsl", "bundled": True, "label": "AMD FSR (AMD/Intel kartlar; her kartta çalışır)"},
}


BUNDLED = Path(__file__).resolve().parent / "glsl"
CAS = BUNDLED / "cas.glsl"   # kendi keskinleştirme shader'ımız (pakette)
SHARPNESS = {"off": 0.0, "light": 0.3, "medium": 0.5, "strong": 0.75}


def shader_dir() -> Path:
    return paths.bin_dir() / "shaders"


def pick(settings: dict) -> str:
    """Kullanılacak büyütücü: AMD/Intel kartta (ayar açıksa) AMD FSR, aksi halde seçilen yapay zekâ modeli."""
    v = settings["video"]
    if v.get("gpu_vendor") in ("amd", "intel") and v.get("amd_fsr", True) and v.get("ai_upscaler") != "off":
        return "fsr"
    return v.get("ai_upscaler", "fsrcnnx")


def resolve(name: str | None) -> Path | None:
    """Seçilen modelin dosyası; yoksa indirilmiş diğer model; hiçbiri yoksa None."""
    if not name or name == "off":
        return None
    order = [name] + [k for k in SHADERS if k != name]
    for key in order:
        if key in SHADERS:
            p = (BUNDLED / SHADERS[key]["file"]) if SHADERS[key].get("bundled") else shader_dir() / SHADERS[key]["file"]
            if p.is_file() and p.stat().st_size > 1000:
                return p
    return None
