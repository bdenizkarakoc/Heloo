"""Görselden video: tek bir görselden seslendirmeli, altyazılı dikey video.

1. Claude görseli inceler: sahne, karakterler (kimlik tespiti YOK — uydurma takma adlar), kişilik/ruh hâli, her
   karaktere uygun ses tarifi, görselden ilham alan kısa Türkçe anlatı (anlatıcı + karakter repliği) ve hareket istemleri.
2. Görsel dikey değilse kenarları Gemini ile 9:16'ya genişletilir (GEMINI_API_KEY; yoksa fabrika bulanık kenar kullanır).
3. Her konuşan için ElevenLabs'te tarife göre ses tasarlanır (ELEVENLABS_API_KEY; yoksa seçilen Türkçe ses).
4. Higgsfield görseli hareketli kliplere çevirir (HIGGSFIELD_KEY_ID/SECRET; yoksa fotoğraf + kamera hareketi).
5. Fabrika hattı: sahne başına doğru karakterin sesi (scene.voice_id), altyazı, müzik, QC, dışa aktarım, Supabase, yayın kuyruğu.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from . import log
from .config import load_config
from .util import StageError, write_json

L = log.get("gorsel")

PROMPT = """Bu görselden kısa (25-45 sn) dikey bir sosyal medya videosu yapılacak. Görseli dikkatle incele ve YALNIZCA JSON döndür.

Kurallar:
- Görseldeki gerçek kişileri TANIMLAMA, isimlerini tahmin etme; karakterlere uydurma Türkçe takma ad ver.
- Anlatı görselden ilham alan, eğlenceli ya da duygulu kısa bir hikâye; gerçekmiş gibi sunulan iddia, sayı ya da tarih yok.
- Satırlar Türkçe, konuşma dilinde, her biri tek cümle (5-16 kelime); 5-9 satır. Konuşan: "anlatici" ya da karakter id'si.
- Ses tarifleri İngilizce, 25-60 kelime: yaş aralığı, cinsiyet ifadesi, tını, tempo, enerji, ruh hâli, "speaks Turkish
  natively". Ünlü/gerçek bir kişinin sesine benzetme YAZMA.
- Hareket istemleri İngilizce, görseldeki sahneyi canlandıran sinematik hareket (kamera + karakter hareketi), yeni nesne
  ekleme, yazı yok; her biri farklı bir an/kamera.
{istek}
Biçim:
{{"title": "≤60 karakter Türkçe başlık", "category": "{kategoriler} içinden biri",
  "scene": "görselde ne var (kısa Türkçe)",
  "characters": [{{"id": "c1", "ad": "takma ad", "kim": "yaş/görünüş (kimlik değil)", "kisilik": "...", "ruh_hali": "...",
                  "voice_en": "..."}}],
  "narrator_voice_en": "anlatıcı sesi tarifi (İngilizce)",
  "lines": [{{"speaker": "anlatici|c1", "text": "Türkçe cümle."}}],
  "motions": ["English motion prompt 1", "English motion prompt 2", "English motion prompt 3"],
  "music": "English music search query (mood/genre)",
  "hashtags": ["..."]}}"""


def analyze(image: Path, istek: str, cfg) -> dict:
    from . import studio
    cats = ", ".join((cfg.get_path("categories") or {}).keys())
    prompt = PROMPT.format(istek=f"- Kullanıcının isteği (öncelikli): {istek}" if istek else "", kategoriler=cats)
    res = studio.ask_ai(cfg, prompt, [image], image.with_name(image.stem + "_analiz.json"), timeout=600)
    if not res or not res.get("lines"):
        raise StageError("görsel incelenemedi (Claude yanıtı yok ya da anlatı boş)")
    return res


def vertical(image: Path, cfg) -> Path:
    """Görsel 9:16'ya yakın değilse Gemini ile kenarları genişletilir; olmazsa olduğu gibi kalır."""
    from . import characters
    from .config import secret
    w, h = Image.open(image).size
    if w / h <= 0.62 or not secret("GEMINI_API_KEY") or not cfg.get_path("gorsel.extend", True):
        return image
    try:
        out = characters.extend_vertical(image, image.with_name(image.stem + "_916.jpg"), cfg)
        L.info("görsel 9:16'ya genişletildi: %s", out.name)
        return out
    except StageError as exc:
        L.warning("görsel genişletilemedi (bulanık kenar kullanılacak): %s", exc)
        return image


def voices(an: dict, cfg) -> dict[str, str]:
    """Konuşan başına ElevenLabs ses kimliği (anahtar yoksa boş)."""
    from . import eleven
    if not eleven.available() or not cfg.get_path("gorsel.eleven_voices", True):
        return {}
    speakers = [s for s in dict.fromkeys(ln.get("speaker", "anlatici") for ln in an["lines"])]
    chars = {c.get("id"): c for c in an.get("characters") or []}
    out: dict[str, str] = {}
    for sp in speakers[: int(cfg.get_path("gorsel.max_voices", 3))]:
        if sp in chars:
            c = chars[sp]
            desc = c.get("voice_en") or ""
            name = c.get("ad") or sp
        else:
            desc, name = an.get("narrator_voice_en") or "Warm, clear storyteller voice, adult, medium pace, speaks Turkish natively", "Anlatıcı"
        try:
            out[sp] = eleven.design_voice(name, desc, cfg)
        except StageError as exc:
            L.warning("%s için ElevenLabs sesi tasarlanamadı: %s", name, exc)
    return out


def edge_voice(desc: str) -> tuple[str, str]:
    """ElevenLabs yokken tarife en yakın Türkçe Edge sesi ve perde: kadın → Emel, erkek → Ahmet; çocuk/çizgi karakter
    daha ince, yaşlı daha kalın."""
    d = (desc or "").lower()
    voice = "tr-TR-EmelNeural" if any(w in d for w in ("female", "woman", "girl", "kadın", "kız")) else "tr-TR-AhmetNeural"
    pitch = "+25Hz" if any(w in d for w in ("child", "kid", "young", "cartoon", "squeaky", "çocuk")) else \
        ("-12Hz" if any(w in d for w in ("old", "elderly", "deep", "yaşlı")) else "+0Hz")
    return voice, pitch


def clips(image: Path, an: dict, n: int, cfg) -> list[Path]:
    """Higgsfield ile görselden n hareketli klip (anahtar yoksa ya da hata olursa boş liste)."""
    from . import higgsfield, studio
    if n <= 0 or not higgsfield.available():
        return []
    n = min(n, int(cfg.get_path("budget.max_ai_video_clips_per_video", 4)))
    motions = (an.get("motions") or ["slow cinematic push-in, subtle natural movement"])
    out: list[Path] = []
    try:
        url = higgsfield.upload(image)
    except StageError as exc:
        L.warning("Higgsfield'a yüklenemedi (fotoğraf + kamera hareketi kullanılacak): %s", exc)
        return []
    for i in range(n):
        dest = studio.UPLOADS / f"{image.stem}_klip{i + 1}.mp4"
        try:
            out.append(higgsfield.image_to_video(url, motions[i % len(motions)], dest, cfg))
            L.info("Higgsfield klibi %d/%d hazır", i + 1, n)
        except StageError as exc:
            L.warning("Higgsfield klibi %d üretilemedi: %s", i + 1, exc)
    return out


def run(image_name: str, opts: dict, enqueue_produce) -> str:
    """Sunucu iş kuyruğunda ya da komut satırında çalışır; görevi hazırlar, üretimi başlatır, görev kimliğini döndürür."""
    from . import composer, pipeline, studio
    cfg = load_config()
    src = studio.UPLOADS / Path(image_name).name
    if not src.is_file():
        raise StageError(f"görsel bulunamadı: {image_name}")
    istek = (opts.get("istek") or "").strip()
    an = analyze(src, istek, cfg)
    img = vertical(src, cfg)
    vids = voices(an, cfg) if opts.get("ses", "otomatik") == "otomatik" else {}
    kl = clips(img, an, int(opts.get("klip", cfg.get_path("gorsel.clips", 2))), cfg)
    media = kl + [img]   # önce hareketli klipler, sonra görselin kendisi (kamera hareketiyle)
    cat = an.get("category") if an.get("category") in (cfg.get_path("categories") or {}) else None
    title = (opts.get("baslik") or an.get("title") or "Görselden video").strip()[:60]
    job = pipeline.new_job(cfg, cat, title, media=media)
    over = {"script.require_sources": False, "script.min_scenes": 1, "script.max_scenes": 16,
            "output.duration.min": 5, "output.duration.hard_max": 180,
            f"categories.{job.state['category']}.kicker": ""}
    ses = opts.get("ses", "otomatik")
    if vids:
        over["tts.provider_chain"] = ["elevenlabs", "edge"]
    elif ses in composer.VOICES:
        over.update({"tts.provider_chain": ["edge"], "tts.edge.voices": [composer.VOICES[ses]]})
    elif ses == "benim":
        over["tts.provider_chain"] = ["my_voice", "edge"]
    lines = [ln for ln in an["lines"] if str(ln.get("text", "")).strip()]
    job.state.update(overrides=over, no_music=opts.get("muzik") == "yok", gorsel={
        "image": src.name, "framed": img.name, "clips": [p.name for p in kl], "voices": vids,
        "characters": an.get("characters"), "scene": an.get("scene"),
        "credits": [x for x in ("Higgsfield (görselden video)" if kl else "", "ElevenLabs (ses tasarımı)" if vids else "",
                                "Gemini (kenar genişletme)" if img != src else "") if x]})
    job.save()
    pipeline.make_brief(job, cfg)
    o = {"_media_n": len(job.state.get("user_media") or []), "altyazi": opts.get("altyazi", True),
         "kurgu": istek}
    script = composer.build_script(title, [str(ln["text"]).strip() for ln in lines], o, job.state["category"])
    for sc, ln in zip(script["scenes"], lines):
        sp = ln.get("speaker", "anlatici")
        if vids.get(sp):
            sc["voice_id"] = vids[sp]
        elif ses == "otomatik":
            ch = next((c for c in an.get("characters") or [] if c.get("id") == sp), None)
            sc["edge_voice"], sc["edge_pitch"] = edge_voice(ch.get("voice_en", "") if ch else
                                                            an.get("narrator_voice_en") or "female storyteller")
        sc["speaker"] = sp
    if an.get("music"):
        script["music"] = {"queries": [an["music"], "uplifting ambient"]}
    credits = job.state["gorsel"]["credits"]
    script["post"] = {"caption": title + (f"\n\nAI: {', '.join(credits)}" if credits else ""),
                      "hashtags": [h.lstrip("#") for h in an.get("hashtags") or []][:8]}
    write_json(job.script_path, script)
    write_json(job.dir / "gorsel_analiz.json", an)
    with job.stage("script") as info:
        info.update(provider="görsel analizi (Claude)", title=script["title"], scenes=len(script["scenes"]),
                    voices=len(vids), clips=len(kl))
    L.info("Görselden video: %s hazır (%d satır, %d ses, %d klip)", job.id, len(lines), len(vids), len(kl))
    enqueue_produce(job)
    return job.id


def from_file(path: Path, opts: dict) -> str:
    """Komut satırı: dosyayı yüklemeler klasörüne kopyalayıp `run` ile aynı akışı eşzamanlı çalıştırır."""
    from . import pipeline, studio
    studio.UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = studio.UPLOADS / studio.safe_upload_name(path.name)
    shutil.copy2(path, dest)
    holder = {}
    jid = run(dest.name, opts, lambda j: holder.update(job=j))
    pipeline.produce(holder["job"], load_config())
    return jid

