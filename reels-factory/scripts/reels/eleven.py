"""ElevenLabs ses tasarımı: karakter tarifinden yeni bir ses (Voice Design, /v1/text-to-voice/design + /v1/text-to-voice).

Gerçek bir kişinin sesi taklit edilmez: tarif yalnızca yaş, cinsiyet ifadesi, tını, tempo ve ruh hâlinden oluşur (görsel
analizi kimlik tespiti yapmaz). Aynı tarif için oluşturulan ses `studio/eleven_voices.json`'da saklanır ve yeniden
kullanılır (her tasarım ElevenLabs kredisi harcar). Anahtar: `.env` → ELEVENLABS_API_KEY.
"""
from __future__ import annotations

import hashlib
import json

import requests

from . import log
from .config import ROOT, Config, secret
from .util import StageError

L = log.get("eleven")
API = "https://api.elevenlabs.io/v1"
CACHE = ROOT / "studio" / "eleven_voices.json"
NO_IMITATION = " Original synthetic voice; must not imitate or resemble any real, famous or identifiable person."


def available() -> bool:
    return bool(secret("ELEVENLABS_API_KEY"))


def _hdr() -> dict:
    key = secret("ELEVENLABS_API_KEY")
    if not key:
        raise StageError("ElevenLabs anahtarı yok: Yayın → Ayarlar'a ELEVENLABS_API_KEY gir")
    return {"xi-api-key": key, "Content-Type": "application/json"}


def _post(path: str, body: dict, timeout: int = 180) -> dict:
    r = requests.post(f"{API}/{path}", headers=_hdr(), json=body, timeout=timeout)
    if r.status_code >= 400:
        try:
            d = r.json().get("detail")
            msg = d.get("message") if isinstance(d, dict) else d
        except ValueError:
            msg = r.text[:200]
        raise StageError(f"ElevenLabs {path}: {r.status_code} {msg}")
    return r.json()


def design_voice(name: str, description: str, cfg: Config) -> str:
    """Tarife uygun bir ses tasarlar (ilk önizlemeyi seçer) ve kalıcı ses kimliğini (voice_id) döndürür."""
    desc = (description.strip().rstrip(".") + "." + NO_IMITATION)[:1000]
    if len(desc) < 20:
        raise StageError("ses tarifi çok kısa (en az 20 karakter)")
    key = hashlib.sha1(desc.encode()).hexdigest()[:16]
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if key in cache:
        return cache[key]["voice_id"]
    design = _post("text-to-voice/design", {
        "voice_description": desc, "model_id": cfg.get_path("tts.elevenlabs.design_model", "eleven_multilingual_ttv_v2"),
        "auto_generate_text": True})
    previews = design.get("previews") or []
    if not previews:
        raise StageError("ElevenLabs ses önizlemesi üretmedi")
    voice = _post("text-to-voice", {"voice_name": f"Fabrika · {name}"[:60], "voice_description": desc,
                                    "generated_voice_id": previews[0]["generated_voice_id"],
                                    "labels": {"source": "reels-fabrikasi"}})
    cache[key] = {"voice_id": voice["voice_id"], "name": name, "description": desc}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    L.info("ElevenLabs sesi tasarlandı: %s → %s", name, voice["voice_id"])
    return voice["voice_id"]
