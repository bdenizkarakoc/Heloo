"""Video Kur: görseller, senaryo, ses, altyazı ve kurgu ayrı ayrı verilir; fabrika bunları birleştirir.

Alanlar (hepsi /api/compose ile gelir):
- media: yüklenen fotoğraf/video/müzik (studio/uploads) · photos: Fotoğraflarım'dan seçilenler (sırasıyla)
- senaryo: metin · senaryo_mod: "aynen" (kelimesi kelimesine okunur; Claude gerekmez) | "duzenle" (Claude araştırır,
  doğrular, Reels senaryosuna çevirir)
- ses: "benim" (Sesim) | "kadin" | "erkek" (hazır sesler) | "kayit" (kendi ses kaydın; konuşman yazıya dökülür,
  sahneler ona göre bölünür) | "yok" (seslendirmesiz müzikli montaj → Kesim hattı)
- altyazi: true/false · kurgu: serbest istek (tempo, müzik, geçiş) · muzik: "otomatik" | "yok" · baslik
Kişisel videolarda kaynak zorunluluğu ve süre alt sınırı uygulanmaz (job.state["overrides"]).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import log
from .config import ROOT, load_config
from .util import StageError, load_audio, words_of, write_json, write_wav

L = log.get("composer")
VOICES = {"kadin": "tr-TR-EmelNeural", "erkek": "tr-TR-AhmetNeural"}
TRANS_BY_TEMPO = {"hizli": ["whip", "cut", "whip", "zoom"], "sakin": ["zoom", "wipe", "iris", "zoom"],
                  "normal": ["zoom", "whip", "wipe", "iris"]}


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    return [p if p[-1] in ".!?…" else p + "." for p in parts]


def _chunks(sents: list[str], n_media: int, max_words: int = 22) -> list[str]:
    """Cümleleri sahnelere böler: sahne ≈ 1-2 cümle (≤ max_words kelime); medya sayısı kadar sahne olmaya çalışır."""
    scenes: list[str] = []
    for s in sents:
        if scenes and len((scenes[-1] + " " + s).split()) <= max_words and len(scenes[-1].split()) < 9:
            scenes[-1] += " " + s
        else:
            scenes.append(s)
    while len(scenes) < n_media:    # medya fazlaysa en uzun sahneyi virgülden ikiye böl
        i = max(range(len(scenes)), key=lambda k: len(scenes[k].split()))
        sc = scenes[i]
        cut = sc.find(", ", len(sc) // 3)
        if cut < 0 or len(sc.split()) < 8:
            break
        scenes[i:i + 1] = [sc[:cut] + ".", sc[cut + 2:][:1].upper() + sc[cut + 2:][1:]]
    return scenes


def _headline(text: str, limit: int) -> str:
    t = re.sub(r"[.!?…]+$", "", text.strip())
    if len(t) <= limit:
        return t
    out = ""
    for w in t.split():
        if len(out) + len(w) + 1 > limit - 1:
            break
        out = (out + " " + w).strip()
    return out + "…"


def _visual(i: int, media_n: int) -> dict:
    """Sahne görseli: sıradaki kullanıcı medyası; medya bittiyse baştakiler tekrar (reuse); hiç yoksa hareketli grafik."""
    if not media_n:
        return {"kind": "graphic"}
    if i < media_n:
        return {"kind": "photo", "user": True, "providers": ["agent_media"]}
    return {"kind": "photo", "reuse": f"s{i % media_n + 1}"}


def build_script(title: str, scenes_text: list[str], opts: dict, category: str) -> dict:
    """Kelimesi kelimesine okunacak senaryo (Claude'suz). Görseller kullanıcı medyasıdır."""
    from .brief import keywords
    kw = keywords(opts.get("kurgu") or "")
    trans = TRANS_BY_TEMPO.get(kw.get("tempo") or "normal", TRANS_BY_TEMPO["normal"])
    caps = opts.get("altyazi", True) is not False
    scenes = []
    for i, txt in enumerate(scenes_text):
        sc = {"id": f"s{i + 1}", "role": "hook" if i == 0 else ("outro" if i == len(scenes_text) - 1 and i > 1 else "body"),
              "layout": "hook" if i == 0 else "photo", "narration": txt,
              "on_screen": {"headline": _headline(title or txt, 42)} if i == 0 else {},
              "visual": _visual(i, opts.get("_media_n", 0)),
              "transition": trans[i % len(trans)], "captions": caps}
        scenes.append(sc)
    from .brief import MUZIK
    mq = kw.get("music_query") or MUZIK.get(kw.get("muzik") or "", None)
    return {"title": title or _headline(scenes_text[0], 60), "category": category, "summary": scenes_text[0],
            "music": {"queries": [mq] if mq else ["warm acoustic background", "uplifting ambient"]},
            "scenes": scenes, "sources": [], "facts": [], "personal": True,
            "post": {"caption": title or scenes_text[0], "hashtags": []}}


def own_audio_scenes(job, audio_path: Path, cfg) -> tuple[list[str], dict]:
    """Kullanıcının kendi ses kaydı: yazıya dök (ekran kartı varsa büyük model), sahnelere böl, sesi dilimle."""
    from . import studio
    work = job.d("voice")
    wav48 = work / "kayit48.wav"
    from .util import run
    from .voice import enhance
    enhance(audio_path, wav48, sr=48000, strength="orta")   # gürültü/uğultu temizliği, seviye
    words = studio.transcribe(wav48, work, cfg)
    if not words:
        raise StageError("ses kaydında konuşma bulunamadı")
    groups, cur = [], []
    for w in words:   # cümle sonunda ya da ~7 sn'de böl
        cur.append(w)
        dur = cur[-1]["end"] - cur[0]["start"]
        if (w["word"][-1:] in ".!?" and dur > 2.5) or dur > 7.5:
            groups.append(cur)
            cur = []
    if cur:
        if groups and cur[-1]["end"] - cur[0]["start"] < 1.5:
            groups[-1] += cur
        else:
            groups.append(cur)
    audio = load_audio(wav48, 48000, 1)
    metas, texts = {}, []
    for i, g in enumerate(groups):
        sid = f"s{i + 1}"
        a0 = max(0.0, g[0]["start"] - 0.08)
        nxt = groups[i + 1][0]["start"] if i + 1 < len(groups) else len(audio) / 48000
        a1 = min(nxt, g[-1]["end"] + 0.25)
        clip = audio[int(a0 * 48000):int(a1 * 48000)].copy()
        write_wav(work / f"{sid}.wav", clip, 48000)
        text = " ".join(w["word"] for w in g).strip()
        text = text if text[-1:] in ".!?…" else text + "."
        texts.append(text)
        ws = [{"i": n, "text": t, "start": round(w["start"] - a0, 3), "end": round(w["end"] - a0, 3)}
              for n, (t, w) in enumerate(zip(words_of(text), g))]
        metas[sid] = {"id": sid, "provider": "kendi kaydın", "duration": round(len(clip) / 48000, 3),
                      "timing": "asr", "words": ws}
        write_json(work / f"{sid}.json", metas[sid])
    return texts, metas


def run_compose(task: dict, enqueue_produce) -> str:
    """Video Kur görevini hazırlar (sunucunun iş kuyruğunda çalışır) ve üretimi başlatır. Görev kimliğini döndürür."""
    from . import pipeline, studio
    from .job import Job
    cfg = load_config()
    o = task["opts"]
    files = [studio.UPLOADS / Path(f).name for f in (o.get("media") or []) if (studio.UPLOADS / Path(f).name).is_file()]
    if o.get("photos"):
        from . import photos
        files = photos.to_uploads(list(o["photos"])) + files
    senaryo = (o.get("senaryo") or "").strip()
    ses = o.get("ses") or "benim"
    title = (o.get("baslik") or "").strip()
    mod = o.get("senaryo_mod") or "aynen"
    job = pipeline.new_job(cfg, o.get("category") or None, title or (senaryo[:80] if senaryo else None),
                           text=senaryo or None, media=files or None)
    over = {"script.require_sources": False, "script.min_scenes": 1, "script.max_scenes": 16,
            "output.duration.min": 5, "output.duration.hard_max": 180}
    over[f"categories.{job.state['category']}.kicker"] = ""   # kişisel videoda kategori etiketi (ör. "BEYNİN OYUNLARI") olmasın
    if ses in VOICES:
        over.update({"tts.provider_chain": ["edge", "elevenlabs"], "tts.edge.voices": [VOICES[ses]]})
    elif ses == "benim":
        over["tts.provider_chain"] = ["my_voice", "edge", "elevenlabs"]
    job.state.update(overrides=over, kurgu=o.get("kurgu") or None, compose=o, no_music=o.get("muzik") == "yok")
    job.save()
    pipeline.make_brief(job, cfg)
    media_n = len(job.state.get("user_media") or [])
    cfgj = pipeline.job_config(job, cfg)
    o["_media_n"] = media_n

    if ses == "kayit":
        rec = studio.UPLOADS / Path(str(o.get("kayit") or "")).name
        if not rec.is_file():
            raise StageError("ses kaydı bulunamadı (önce kaydet ya da yükle)")
        texts, metas = own_audio_scenes(job, rec, cfgj)
        script = build_script(title, texts, o, job.state["category"])
        write_json(job.script_path, script)
        with job.stage("script") as info:
            info.update(provider="kendi kaydın", title=script["title"], scenes=len(texts))
        with job.stage("voice") as info:
            write_json(job.dir / "voice" / "index.json", metas)
            info.update(providers=["kendi kaydın"], seconds=round(sum(m["duration"] for m in metas.values()), 2),
                        timing=["asr"])
        job.state["script_hash"] = pipeline._script_hash(job.script_path)
        job.save()
    elif mod == "aynen" or not senaryo:
        if not senaryo:
            raise StageError("senaryo boş: metni yaz ya da “kendi kaydım”ı seç")
        script = build_script(title, _chunks(_sentences(senaryo), media_n), o, job.state["category"])
        write_json(job.script_path, script)
        with job.stage("script") as info:
            info.update(provider="kullanıcı metni (aynen)", title=script["title"], scenes=len(script["scenes"]))
    else:   # duzenle: Claude araştırır ve senaryoya çevirir (kurgu isteği brief'te)
        pipeline.auto_script(job, cfgj)
        if o.get("altyazi") is False:
            import json
            sc = json.loads(job.script_path.read_text(encoding="utf-8"))
            for s in sc.get("scenes", []):
                s["captions"] = False
            write_json(job.script_path, sc)
    L.info("Video Kur: %s hazır (ses: %s, senaryo: %s, %d medya)", job.id, ses, mod, media_n)
    enqueue_produce(job)
    return job.id
