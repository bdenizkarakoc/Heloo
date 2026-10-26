"""Ortam denetimi: araçlar, bağımlılıklar ve hizmetler. Eksik hizmetleri varmış gibi göstermez."""
from __future__ import annotations

import importlib.util
import shutil

from .config import Config, ROOT, secret
from .util import run


def _ok(name: str, ok: bool, detail: str, need: str = "zorunlu") -> dict:
    return {"name": name, "ok": ok, "detail": detail, "need": need}


def _ver(cmd: list[str]) -> str:
    try:
        return run(cmd, check=False, quiet=True).stdout.splitlines()[0][:80]
    except Exception:  # noqa: BLE001
        return ""


def check(cfg: Config, network: bool = True) -> list[dict]:
    rows = []
    ff = shutil.which("ffmpeg")
    rows.append(_ok("ffmpeg", bool(ff), _ver(["ffmpeg", "-version"]) if ff else "kurulu değil"))
    rows.append(_ok("ffprobe", bool(shutil.which("ffprobe")), "video analizi"))
    node = shutil.which("node")
    rows.append(_ok("node (>=22)", bool(node), _ver(["node", "--version"]) if node else "kurulu değil"))
    import os
    hf = ROOT / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    rows.append(_ok("hyperframes", hf.exists(), _ver([str(hf), "--version"]) if hf.exists() else "npm install gerekli"))
    gsap = ROOT / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    rows.append(_ok("gsap", gsap.exists(), "animasyon motoru" if gsap.exists() else "npm install gerekli"))
    chrome = list((__import__("pathlib").Path.home() / ".cache" / "hyperframes" / "chrome").glob("*/*/*"))
    rows.append(_ok("headless chrome", bool(chrome), "HyperFrames render tarayıcısı" if chrome
                    else "npx hyperframes browser ensure"))
    for mod, need, why in [("yaml", "zorunlu", "ayarlar"), ("numpy", "zorunlu", "ses işleme"),
                           ("PIL", "zorunlu", "görsel işleme / metin ölçümü"), ("jinja2", "zorunlu", "şablonlar"),
                           ("edge_tts", "zorunlu", "varsayılan Türkçe seslendirme"),
                           ("faster_whisper", "isteğe bağlı", "QC: konuşma tanıma ile anlaşılırlık/senkron"),
                           ("anthropic", "isteğe bağlı", "tam otonom mod (Claude API)")]:
        rows.append(_ok(f"python:{mod}", importlib.util.find_spec(mod) is not None, why, need))
    font = cfg.path(cfg.get_path("brand.font_file"))
    rows.append(_ok("font", font.exists(), str(font.relative_to(ROOT))))
    sfx = [d for d in cfg.get_path("sfx.library_dirs", []) if (ROOT / d).exists() and any((ROOT / d).iterdir())]
    rows.append(_ok("sfx kütüphanesi", bool(sfx), ", ".join(sfx) or "yok (efektsiz devam edilir)", "isteğe bağlı"))

    keys = {
        "ANTHROPIC_API_KEY": "Claude API — tam otonom konu/araştırma/senaryo",
        "ELEVENLABS_API_KEY": "ElevenLabs seslendirme",
        "PEXELS_API_KEY": "Pexels stok video/fotoğraf",
        "OPENAI_API_KEY": "OpenAI görsel üretimi",
        "REPLICATE_API_TOKEN": "Replicate görsel/video üretim modelleri",
    }
    for k, why in keys.items():
        rows.append(_ok(k, bool(secret(k)), why + (" — tanımlı" if secret(k) else " — tanımlı değil"),
                        "isteğe bağlı"))
    if network:
        from .util import http
        for name, url in [("edge-tts uç noktası", "https://speech.platform.bing.com/"),
                          ("Openverse API", "https://api.openverse.org/v1/images/?q=test&page_size=1"),
                          ("NASA görsel API", "https://images-api.nasa.gov/search?q=moon&page_size=1")]:
            try:
                r = http().get(url, timeout=15)
                rows.append(_ok(name, r.status_code < 500, f"HTTP {r.status_code}", "isteğe bağlı"))
            except Exception as exc:  # noqa: BLE001
                rows.append(_ok(name, False, type(exc).__name__, "isteğe bağlı"))
    return rows


def capabilities(cfg: Config) -> dict:
    """Hangi üretim yöntemlerinin gerçekten kullanılabilir olduğunu özetler."""
    from .llm import resolve_provider
    return {
        "senaryo": {"anthropic": "Claude API (otonom)", "claude_cli": "bilgisayardaki Claude Code (otonom)",
                    "manual": "Claude Code oturumunda elle (SKILL.md)"}[resolve_provider(cfg)],
        "seslendirme": "edge-tts (tr-TR nöral)" + (" + ElevenLabs" if secret("ELEVENLABS_API_KEY") else ""),
        "ai_gorsel": "OpenAI" if secret("OPENAI_API_KEY") else
                     ("Replicate" if secret("REPLICATE_API_TOKEN") and cfg.get_path("visuals.replicate.image_model")
                      else "YOK (anahtar tanımlı değil)"),
        "ai_video": "Replicate" if secret("REPLICATE_API_TOKEN") and cfg.get_path("visuals.replicate.video_model")
                    else "YOK — fotoğraf + kamera hareketi + hareketli grafik kullanılır",
        "stok": "Pexels + NASA + Openverse" if secret("PEXELS_API_KEY") else "NASA + Openverse (anahtarsız)",
        "muzik": "kütüphane / Openverse CC0-CC BY / prosedürel",
        "kurgu": "HyperFrames + GSAP (HTML → MP4)",
    }
