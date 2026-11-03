"""Higgsfield resmî API'si (docs.higgsfield.ai): görselden video (image-to-video) klip üretimi.

Kimlik: `.env` → HIGGSFIELD_KEY_ID + HIGGSFIELD_KEY_SECRET (console.higgsfield.ai, ön ödemeli dolar bakiyesi).
Akış: görsel önceden imzalı adrese yüklenir (/files/generate-upload-url) → model uç noktasına istek → `status_url`
completed olana kadar sorgulanır → `video.url` indirilir. Ücretli olduğu için yalnızca anahtar varsa ve
`budget.max_ai_video_clips_per_video` sınırı içinde çağrılır (çağıran sayar).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import requests

from . import log
from .config import Config, secret
from .util import StageError

L = log.get("higgsfield")
API = "https://api.higgsfield.ai"
TERMINAL = {"completed", "failed", "nsfw", "canceled"}
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def available() -> bool:
    return bool(secret("HIGGSFIELD_KEY_ID") and secret("HIGGSFIELD_KEY_SECRET"))


def _auth() -> dict:
    if not available():
        raise StageError("Higgsfield anahtarı yok: Yayın → Ayarlar'a HIGGSFIELD_KEY_ID ve HIGGSFIELD_KEY_SECRET gir")
    return {"Authorization": f"Key {secret('HIGGSFIELD_KEY_ID')}:{secret('HIGGSFIELD_KEY_SECRET')}"}


def _check(r: requests.Response, what: str) -> dict:
    if r.status_code >= 400:
        try:
            msg = r.json().get("detail") or r.text[:200]
        except ValueError:
            msg = r.text[:200]
        raise StageError(f"Higgsfield {what}: {r.status_code} {msg}")
    return r.json()


def upload(path: Path) -> str:
    """Yerel görseli Higgsfield deposuna yükler, model girdisi olarak kullanılacak public_url'i döndürür."""
    ctype = MIME.get(path.suffix.lower())
    if not ctype:
        raise StageError(f"Higgsfield yalnızca jpg/png/webp görsel kabul eder: {path.name}")
    up = _check(requests.post(f"{API}/files/generate-upload-url", headers=_auth(), json={"content_type": ctype},
                              timeout=60), "yükleme adresi")
    with open(path, "rb") as fh:  # imzalı adrese API kimliği gönderilmez
        r = requests.put(up["upload_url"], data=fh, headers=up.get("upload_headers") or {"Content-Type": ctype},
                         timeout=300)
    if r.status_code >= 400:
        raise StageError(f"Higgsfield görsel yüklenemedi: {r.status_code}")
    return up["public_url"]


def image_to_video(image_url: str, prompt: str, dest: Path, cfg: Config, duration: int | None = None) -> Path:
    model = str(cfg.get_path("higgsfield.image_to_video", "kling-video/v2.5-turbo/standard/image-to-video")).strip("/")
    body = {"prompt": prompt, "image_url": image_url,
            "duration": int(duration or cfg.get_path("higgsfield.duration", 5))}
    neg = cfg.get_path("higgsfield.negative_prompt", "")
    if neg and model.startswith("kling"):
        body["negative_prompt"] = neg
    sub = _check(requests.post(f"{API}/{model}", headers={**_auth(), "Content-Type": "application/json"}, json=body,
                               timeout=120), "istek")
    status_url = sub.get("status_url") or f"{API}/requests/{sub['request_id']}/status"
    L.info("Higgsfield %s isteği: %s", model, sub.get("request_id"))
    delay, deadline = 2.0, time.time() + float(cfg.get_path("higgsfield.timeout_sec", 900))
    while True:
        try:
            st = _check(requests.get(status_url, headers=_auth(), timeout=30), "durum")
        except requests.RequestException:
            st = {"status": "in_progress"}
        if st.get("status") in TERMINAL:
            break
        if time.time() > deadline:
            raise StageError("Higgsfield zaman aşımı (higgsfield.timeout_sec)")
        time.sleep(delay + random.uniform(0, 0.5))
        delay = min(delay * 1.5, 10.0)
    if st["status"] != "completed" or not (st.get("video") or {}).get("url"):
        raise StageError(f"Higgsfield klip üretemedi: {st.get('status')} {st.get('error') or ''}".strip())
    r = requests.get(st["video"]["url"], timeout=600)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest
