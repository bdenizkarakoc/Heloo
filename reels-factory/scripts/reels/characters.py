"""Animasyon karakterleri: Gemini (Google'ın resmî Gemini API'si, GEMINI_API_KEY) ile özgün karakter çizimi.

Her karakter düz yeşil zeminde, tam boy, kameraya dönük çizilir; yeşil zemin saydamlaştırılır ve görsel animasyon
şablonunun kart ölçüsüne (600x1000 tasarım tuvali, tabanlar y=975) yerleştirilir:
`animasyon/studio/public/<film>/chars/<karakter>_<poz>.png`. Sahnede `gemcast.ts` (imgDraw) bu PNG'leri kart yapar.
Aynı karakterin diğer pozlarında ilk poz referans olarak verilir (tutarlı görünüm). Ücretli/kotali bir API olduğu için
yalnızca anahtar tanımlıysa ve `animation.max_character_images` sınırı içinde çağrılır; üretilen her görsel
`chars.json`'a (istem, model, tarih) yazılır.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import re
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from . import log
from .config import ROOT, Config, secret
from .util import StageError

L = log.get("characters")
API = "https://generativelanguage.googleapis.com/v1beta"
STUDIO = ROOT / "animasyon" / "studio"
CANVAS = (600, 1000)   # toon.ts tasarım tuvali
SOLE_Y = 975           # tabanların hizası

STYLE = ("Flat 2D cartoon character for an animated short: simple bean-shaped head, small dot eyes, simple mouth, thin "
         "stick limbs with round ink-dot hands, bold dark plum (#241726) variable-width ink outline, flat colours with "
         "one soft shade tone, no gradients, no text, no logo, no watermark. Full body from head to feet, standing, "
         "facing the camera, centred, feet fully visible at the bottom, generous empty margin all around. Background: "
         "one perfectly flat pure green (#00FF00) colour, no shadow, no floor, no other objects. Do not use the colour "
         "green anywhere on the character. The design must be ORIGINAL and must not resemble any existing copyrighted "
         "or trademarked character, mascot or real person.")

POSES = {
    "neutral": "neutral relaxed expression, arms down",
    "konusma": "talking, mouth open mid-word, one hand raised slightly as if explaining",
    "gulme": "laughing, eyes squeezed shut, big open smile",
    "sasirma": "shocked, eyes wide, mouth a small round O, hands up",
    "yuruyus": "walking pose, one leg forward, arms swinging",
    "uzgun": "sad, eyebrows tilted up, small frown, shoulders down",
}


def slug(text: str) -> str:
    t = text.lower().translate(str.maketrans("çğıöşü", "cgiosu"))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "karakter"


def _err(r: requests.Response) -> str:
    """Gemini hata yanıtını anlaşılır kısa metne çevirir (yanıt JSON olmasa da)."""
    try:
        msg = (r.json().get("error") or {}).get("message") or r.text[:200]
    except ValueError:
        msg = r.text[:200].strip() or "boş yanıt"
    hint = {400: "istek ya da anahtar biçimi hatalı", 401: "anahtar geçersiz", 403: "anahtarın Gemini API izni yok "
            "(aistudio.google.com/apikey'den Gemini API anahtarı al)", 429: "kota doldu, biraz sonra dene"}.get(r.status_code, "")
    return f"HTTP {r.status_code}" + (f" ({hint})" if hint else "") + f": {msg}"


def _json(r: requests.Response) -> dict:
    try:
        return r.json()
    except ValueError as exc:
        raise StageError(f"Gemini yanıtı okunamadı: {_err(r)}") from exc


def _models(cfg: Config) -> list[str]:
    return list(cfg.get_path("animation.gemini_models", ["gemini-3.1-flash-image", "gemini-3.1-flash-image-preview",
                                                         "gemini-3-pro-image", "gemini-3-pro-image-preview"]))


def _discover(key: str) -> list[str]:
    """Ayardaki modeller bulunamazsa hesabın görsel üretebilen Gemini modelleri."""
    try:
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=60)
        r.raise_for_status()
    except requests.RequestException:
        return []
    out = []
    for m in _json(r).get("models", []):
        name = m.get("name", "").split("/")[-1]
        if "image" in name and "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(name)
    return out


def _call(key: str, model: str, prompt: str, ref: Image.Image | None) -> Image.Image:
    parts: list[dict] = [{"text": prompt}]
    if ref is not None:
        buf = io.BytesIO()
        flat = Image.new("RGB", ref.size, (0, 255, 0))  # saydam kart → aynı yeşil zemin
        flat.paste(ref, mask=ref.getchannel("A") if ref.mode == "RGBA" else None)
        flat.save(buf, "PNG")
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "2:3"}}}
    r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=300)
    if r.status_code == 404:
        raise FileNotFoundError(model)
    if r.status_code == 400 and "imageConfig" in r.text:  # eski model: en-boy oranı ayarı yok
        body["generationConfig"].pop("imageConfig")
        r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=300)
    if r.status_code >= 400:
        raise StageError(f"Gemini ({model}): {_err(r)}")
    data_ = _json(r)
    for cand in data_.get("candidates", []):
        for p in (cand.get("content") or {}).get("parts", []):
            data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
            if data:
                return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    reason = (data_.get("promptFeedback") or {}).get("blockReason") or "görsel dönmedi"
    raise StageError(f"Gemini ({model}): {reason}")


def extend_vertical(src: Path, dest: Path, cfg: Config) -> Path:
    """Yatay/kare görseli Gemini ile 9:16 dikey kareye genişletir (kenarlar sahneye uygun doldurulur, asıl içerik
    değişmez). Model sırası `animation.gemini_models`."""
    key = secret("GEMINI_API_KEY")
    if not key:
        raise StageError("GEMINI_API_KEY yok")
    img = Image.open(src).convert("RGB")
    w = img.height * 9 / 16
    canvas = Image.new("RGB", (max(img.width, round(w)), max(img.height, round(img.width * 16 / 9))), (255, 255, 255))
    canvas.paste(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2))
    prompt = ("Outpaint this picture into a 9:16 vertical frame: the original photo sits in the middle of the white "
              "canvas. Fill ONLY the white empty areas by naturally continuing the scene (same lighting, perspective, "
              "style). Do not change, move, recolour or redraw anything in the original part. No text, no borders.")
    models = _models(cfg)
    for model in models:
        try:
            body = {"contents": [{"parts": [{"text": prompt}, _inline(canvas)]}],
                    "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
            r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body,
                              timeout=300)
            if r.status_code == 404:
                continue
            if r.status_code >= 400:
                raise StageError(f"Gemini ({model}): {_err(r)}")
            for cand in _json(r).get("candidates", []):
                for p in (cand.get("content") or {}).get("parts", []):
                    data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
                    if data:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB").save(dest, quality=95)
                        return dest
            raise StageError(f"Gemini ({model}): görsel dönmedi")
        except requests.RequestException as exc:
            raise StageError(f"Gemini bağlantı hatası: {exc}") from exc
    raise StageError("kullanılabilir bir Gemini görsel modeli bulunamadı")


def _inline(img: Image.Image) -> dict:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92)
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


def key_out(img: Image.Image) -> Image.Image:
    """Yeşil zemini saydam yapar (yumuşak kenar), kenardaki yeşil yansımayı temizler."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    green = g - np.maximum(r, b)                      # yeşil baskınlığı
    alpha = np.clip(1 - (green - 0.12) / 0.25, 0, 1)  # >0.37 tamamen saydam, <0.12 tamamen dolu
    g2 = np.minimum(g, np.maximum(r, b) + 0.04)       # kenarlarda yeşil taşmasını bastır
    rgba = np.dstack([r, np.where(alpha < 1, g2, g), b, alpha])
    return Image.fromarray((rgba * 255).round().astype(np.uint8), "RGBA")


def fit_card(img: Image.Image) -> Image.Image:
    """Karakteri 600x1000 tuvale, tabanları y=975'te, ortada olacak şekilde yerleştirir."""
    bbox = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if not bbox:
        raise StageError("görselde karakter bulunamadı (zemin saydamlaştırılınca boş kaldı)")
    fig = img.crop(bbox)
    w, h = CANVAS
    s = min((SOLE_Y - 40) / fig.height, (w - 40) / fig.width)
    fig = fig.resize((max(1, round(fig.width * s)), max(1, round(fig.height * s))), Image.LANCZOS)
    out = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    out.alpha_composite(fig, ((w - fig.width) // 2, SOLE_Y - fig.height))
    return out


def generate(film: str, name: str, desc: str, poses: list[str], cfg: Config) -> list[Path]:
    key = secret("GEMINI_API_KEY")
    if not key:
        raise StageError("GEMINI_API_KEY yok: Yayın → Ayarlar'a Gemini API anahtarını gir (aistudio.google.com/apikey)")
    film, cid = slug(film), slug(name)
    folder = STUDIO / "public" / film / "chars"
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "chars.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"images": []}
    limit = int(cfg.get_path("animation.max_character_images", 24))
    if len(meta["images"]) + len(poses) > limit:
        raise StageError(f"karakter görseli sınırı: bu film için en çok {limit} (animation.max_character_images)")
    models, ref, out = _models(cfg), None, []
    first = folder / f"{cid}_{poses[0]}.png" if poses else None
    if first and first.exists() and len(poses) > 1:
        ref = Image.open(first)
    for pose in poses:
        prompt = f"{STYLE}\nCharacter: {desc}.\nPose and expression: {POSES.get(pose, pose)}."
        if ref is not None:
            prompt += ("\nThe attached image shows this SAME character: keep exactly the same design, colours, clothes "
                       "and proportions; change only the pose and expression.")
        img = None
        while models:
            try:
                img = _call(key, models[0], prompt, ref)
                break
            except FileNotFoundError:
                L.warning("Gemini modeli bulunamadı: %s", models.pop(0))
                if not models:
                    models = [m for m in _discover(key) if m not in _models(cfg)][:3]
        if img is None:
            raise StageError("kullanılabilir bir Gemini görsel modeli bulunamadı (animation.gemini_models)")
        card = fit_card(key_out(img))
        dest = folder / f"{cid}_{slug(pose)}.png"
        card.save(dest)
        if ref is None:
            ref = card
        meta["images"].append({"file": dest.name, "character": name, "pose": pose, "model": models[0], "prompt": prompt,
                               "created": dt.datetime.now().isoformat(timespec="seconds"),
                               "license": "AI üretimi (Gemini API, Google kullanım koşulları)"})
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        L.info("karakter %s / %s → %s (%s)", name, pose, dest.name, models[0])
        out.append(dest)
    return out
