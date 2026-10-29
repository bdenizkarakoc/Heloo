"""Montaj sihirbazı: kullanıcının (isteğe bağlı) cevaplarını stil ayarlarına ve aramalara çevirir.

Girdi (hepsi isteğe bağlı; boş/“fark etmez” alanlar dokunulmaz):
  reference : {"url": "..."} veya {"file": "<studio/uploads içindeki ad>"} — “şuna benzet” (stil referanstan öğrenilir)
  tarz, sure, altyazi, muzik, efekt, renk, tempo : hazır seçenek anahtarları (aşağıdaki tablolar)
  serbest   : kullanıcının kendi cümleleri — Claude varsa yorumlatılır, yoksa Türkçe anahtar kelimelerle eşlenir
Çıktı: run_edit seçenekleri {"style_overrides", "reference", "mode", "max_sec", "music", "sfx", "brief_notes"}.
Müzik türü stildeki music.mood ile internette (kütüphane → Openverse → üretilmiş) aranır; geçiş sesi Kesim
kütüphanesinden (Openverse, CC0/CC BY) bulunur.
"""
from __future__ import annotations

import json
import re

from . import log

L = log.get("brief")

TARZ = {
    "enerjik": {"punch": {"enabled": True, "scale": 1.18}, "flash": {"enabled": True},
                "grade": {"contrast": 1.10, "saturation": 1.25}, "pacing": {"max_pause": 0.3},
                "music": {"enabled": True, "mood": "energetic upbeat"}},
    "sinematik": {"punch": {"enabled": False}, "flash": {"enabled": False}, "frame": {"mode": "crop"},
                  "grade": {"contrast": 1.12, "saturation": 0.92, "warmth": 0.06, "vignette": True},
                  "captions": {"uppercase": False, "weight": 700, "size": 64, "highlight": "#FFFFFF"},
                  "progress": {"enabled": False}, "music": {"enabled": True, "mood": "cinematic"}},
    "vlog": {"punch": {"enabled": True, "scale": 1.08}, "grade": {"saturation": 1.12, "warmth": 0.08},
             "captions": {"uppercase": False, "weight": 800}, "music": {"enabled": True, "mood": "happy acoustic"}},
    "egitici": {"punch": {"enabled": True, "scale": 1.06}, "flash": {"enabled": False},
                "captions": {"box": True, "uppercase": False, "words": 4, "highlight": "#4FC3F7"},
                "music": {"enabled": True, "mood": "calm corporate", "gain_db": -22}},
    "komik": {"punch": {"enabled": True, "scale": 1.25}, "flash": {"enabled": True},
              "captions": {"highlight": "#FF4D6D", "size": 86, "words": 2}, "pacing": {"max_pause": 0.25},
              "music": {"enabled": True, "mood": "funny quirky"}},
    "duygusal": {"punch": {"enabled": False}, "flash": {"enabled": False},
                 "grade": {"saturation": 0.95, "warmth": 0.1, "contrast": 1.04},
                 "captions": {"uppercase": False, "weight": 600, "highlight": "#FFFFFF"},
                 "pacing": {"max_pause": 0.7}, "music": {"enabled": True, "mood": "sad piano emotional"}},
    "minimal": {"punch": {"enabled": False}, "flash": {"enabled": False}, "title": {"enabled": False},
                "progress": {"enabled": False}, "grade": {"contrast": 1.02, "saturation": 1.0, "vignette": False},
                "captions": {"uppercase": False, "weight": 600, "size": 60, "highlight": "#FFFFFF", "outline": 3}},
    "haber": {"captions": {"box": True, "box_color": "#C62828", "uppercase": True, "highlight": "#FFFFFF"},
              "title": {"bg": "#C62828", "fg": "#FFFFFF"}, "progress": {"color": "#C62828"},
              "music": {"enabled": True, "mood": "news tension", "gain_db": -24}},
}
RENK = {
    "canli": {"grade": {"contrast": 1.08, "saturation": 1.3}},
    "sicak": {"grade": {"warmth": 0.15, "saturation": 1.1}},
    "soguk": {"grade": {"warmth": -0.15, "saturation": 1.0}},
    "siyahbeyaz": {"grade": {"saturation": 0.0, "contrast": 1.15}},
    "dogal": {"grade": {"contrast": 1.0, "saturation": 1.0, "warmth": 0.0, "vignette": False}},
    "retro": {"grade": {"saturation": 0.8, "warmth": 0.12, "contrast": 0.95, "vignette": True}},
}
TEMPO = {"hizli": {"pacing": {"max_pause": 0.22, "keep_gaps": 1.5}},
         "normal": {"pacing": {"max_pause": 0.45}},
         "sakin": {"pacing": {"max_pause": 0.9, "keep_gaps": 6.0}, "punch": {"enabled": False}}}
ALTYAZI = {"yok": {"captions": {"enabled": False}},
           "vurgulu": {"captions": {"enabled": True, "uppercase": True, "weight": 900, "box": False}},
           "sade": {"captions": {"enabled": True, "uppercase": False, "weight": 600, "highlight": "#FFFFFF", "outline": 4}},
           "kutulu": {"captions": {"enabled": True, "box": True, "uppercase": False}}}
MUZIK = {"yok": None, "neseli": "happy upbeat", "lofi": "lofi chill", "epik": "epic cinematic", "duygusal": "sad piano",
         "elektronik": "electronic dance", "hiphop": "hip hop beat", "akustik": "acoustic guitar", "gerilim": "suspense"}
EFEKT = {"yok": None, "whoosh": "whoosh", "pop": "pop", "darbe": "impact hit", "klik": "click"}
SURE = {"15": 15, "30": 30, "60": 60, "90": 90}

# serbest metinde anahtar kelimeler (Claude yoksa)
WORDS = [
    (r"enerji|hareketli|coşku|hızlı tempo|dinamik", ("tarz", "enerjik")), (r"sinema|film gibi|cinematic", ("tarz", "sinematik")),
    (r"vlog|günlük", ("tarz", "vlog")), (r"eğit|öğret|anlat|bilgi", ("tarz", "egitici")),
    (r"komik|eğlenceli|mizah|güldür", ("tarz", "komik")), (r"duygu|hüzün|dokunaklı|romantik", ("tarz", "duygusal")),
    (r"sade|minimal|temiz|yalın", ("tarz", "minimal")), (r"haber|son dakika", ("tarz", "haber")),
    (r"siyah.?beyaz", ("renk", "siyahbeyaz")), (r"sıcak renk|sıcak ton|turuncu", ("renk", "sicak")),
    (r"soğuk renk|soğuk ton|mavi ton", ("renk", "soguk")), (r"canlı renk|doygun", ("renk", "canli")),
    (r"retro|eski film|nostalj", ("renk", "retro")), (r"doğal renk|filtresiz", ("renk", "dogal")),
    (r"lo.?fi", ("muzik", "lofi")), (r"epik|destansı", ("muzik", "epik")), (r"elektronik|edm", ("muzik", "elektronik")),
    (r"hip.?hop|rap", ("muzik", "hiphop")), (r"gitar|akustik", ("muzik", "akustik")), (r"gerilim|gizem", ("muzik", "gerilim")),
    (r"müziksiz|müzik olmasın|müzik yok", ("muzik", "yok")),
    (r"whoosh|vınla|geçiş sesi|swoosh", ("efekt", "whoosh")), (r"\bpop\b|patlama sesi", ("efekt", "pop")),
    (r"altyazısız|altyazı olmasın|altyazı yok", ("altyazi", "yok")), (r"kutulu altyazı", ("altyazi", "kutulu")),
    (r"hızlı kes|kısa kes|boşlukları kes", ("tempo", "hizli")), (r"yavaş|sakin|rahat", ("tempo", "sakin")),
    (r"(\d{2})\s*(sn|saniye)", ("sure", None)),
]


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def keywords(text: str) -> dict:
    """Serbest Türkçe metinden seçenekler (Claude olmadan)."""
    t = (text or "").lower()
    got: dict = {}
    for pat, (key, val) in WORDS:
        m = re.search(pat, t)
        if not m or key in got:
            continue
        if key == "sure":
            sec = int(m.group(1))
            val = min(SURE.values(), key=lambda s: abs(s - sec))
            val = str(val)
        got[key] = val
    return got


def interpret_free_text(text: str) -> dict:
    """Serbest metni Claude ile yorumla (API ya da bilgisayardaki Claude Code); olmazsa anahtar kelimeler."""
    text = (text or "").strip()[:800]
    if not text:
        return {}
    from .config import ROOT, load_config
    from .studio import ai_mode, ask_ai
    cfg = load_config()
    if ai_mode(cfg) != "none":
        prompt = (
            "Kullanıcı kısa dikey video (Reels/TikTok) montajı için şunu istedi:\n"
            f"«{text}»\n\nBunu şu seçeneklere eşle (emin olmadığın alanı hiç yazma):\n"
            f"tarz: {list(TARZ)}\nrenk: {list(RENK)}\ntempo: {list(TEMPO)}\naltyazi: {list(ALTYAZI)}\n"
            f"muzik: {list(MUZIK)}\nefekt: {list(EFEKT)}\nsure: {list(SURE)}\n"
            "Ayrıca istersen music_query (İngilizce müzik arama sözcükleri), sfx_query (İngilizce ses efekti arama "
            "sözcükleri) ve title (videonun başına kısa Türkçe başlık; yalnızca kullanıcı açıkça istediyse) ekle.\n"
            'Biçim: {"tarz": "...", "renk": "...", "music_query": "...", ...}')
        out = ROOT / "studio" / "cache" / "brief_ai.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        res = ask_ai(cfg, prompt, [], out, timeout=240)
        if isinstance(res, dict) and res:
            L.info("Sihirbaz: serbest metin Claude ile yorumlandı: %s", res)
            return {k: v for k, v in res.items() if isinstance(v, str) and v}
    return keywords(text)


def build(answers: dict) -> dict:
    """Sihirbaz cevaplarından run_edit seçenekleri üretir."""
    a = {k: v for k, v in (answers or {}).items() if v not in (None, "", "farketmez", "fark etmez")}
    notes = []
    free = interpret_free_text(a.get("serbest", "")) if a.get("serbest") else {}
    for k, v in free.items():   # açıkça seçilen düğme serbest metinden önce gelir
        a.setdefault(k, v)
    over: dict = {}
    for key, table in (("tarz", TARZ), ("renk", RENK), ("tempo", TEMPO), ("altyazi", ALTYAZI)):
        if a.get(key) in table:
            over = _merge(over, table[a[key]])
            notes.append(f"{key}: {a[key]}")
    opts: dict = {}
    if "muzik" in a:
        q = a.get("music_query") or MUZIK.get(a["muzik"], a["muzik"] if a["muzik"] not in MUZIK else None)
        if a["muzik"] == "yok":
            opts["music"] = False
            notes.append("müzik: yok")
        elif q:
            over = _merge(over, {"music": {"enabled": True, "mood": q}})
            opts["music"] = True
            notes.append(f"müzik araması: {q}")
    elif a.get("music_query"):
        over = _merge(over, {"music": {"enabled": True, "mood": a["music_query"]}})
        opts["music"] = True
        notes.append(f"müzik araması: {a['music_query']}")
    elif over.get("music", {}).get("enabled"):
        opts["music"] = True
    sfx_q = a.get("sfx_query") or EFEKT.get(a.get("efekt", ""), None)
    if sfx_q:
        opts["sfx"] = {"query": sfx_q}
        notes.append(f"geçiş sesi araması: {sfx_q}")
    if a.get("sure") in SURE:
        opts.update(mode="clips", max_sec=SURE[a["sure"]], min_sec=max(8, SURE[a["sure"]] // 2), count=1)
        notes.append(f"süre: en çok {SURE[a['sure']]} sn")
    if a.get("title"):
        opts["title"] = str(a["title"])[:60]
    ref = a.get("reference") or {}
    if isinstance(ref, dict) and (ref.get("url") or ref.get("file")):
        opts["reference"] = {k: str(ref[k]) for k in ("url", "file") if ref.get(k)}
        opts["ref_mode"] = "tarz" if (ref.get("mode") or a.get("ref_mode")) == "tarz" else "birebir"
        if ref.get("text_mode") in ("aynen", "uyarla", "yok"):
            opts["text_mode"] = ref["text_mode"]
        notes.append(("birebir şablon: " if opts["ref_mode"] == "birebir" else "tarzı: ") + (ref.get("url") or ref.get("file")))
    if a.get("serbest"):
        opts["istek"] = str(a["serbest"])[:800]   # şablon yazılarını konuya uyarlamak için
    if over:
        opts["style_overrides"] = over
    opts["brief_notes"] = notes
    return opts


QUESTIONS = [  # Kesim sihirbazının soruları (anahtar, soru, [(değer, etiket)])
    ("tarz", "Nasıl bir tarz?", [("enerjik", "Enerjik"), ("sinematik", "Sinematik"), ("vlog", "Vlog"),
                                 ("egitici", "Eğitici"), ("komik", "Komik"), ("duygusal", "Duygusal"),
                                 ("minimal", "Sade / minimal"), ("haber", "Haber")]),
    ("sure", "Ne kadar uzun?", [("15", "15 sn"), ("30", "30 sn"), ("60", "60 sn"), ("90", "90 sn")]),
    ("altyazi", "Altyazı", [("vurgulu", "Kalın + vurgulu"), ("sade", "Sade"), ("kutulu", "Kutulu"), ("yok", "Olmasın")]),
    ("muzik", "Müzik (internetten ücretsiz aranır)", [("neseli", "Neşeli"), ("lofi", "Lo-fi"), ("epik", "Epik"),
                                                      ("duygusal", "Duygusal"), ("elektronik", "Elektronik"),
                                                      ("hiphop", "Hip hop"), ("akustik", "Akustik"),
                                                      ("gerilim", "Gerilim"), ("yok", "Olmasın")]),
    ("efekt", "Geçiş sesi (kütüphaneden)", [("whoosh", "Vınlama"), ("pop", "Pop"), ("darbe", "Darbe"),
                                            ("klik", "Tık"), ("yok", "Olmasın")]),
    ("renk", "Renk", [("canli", "Canlı"), ("sicak", "Sıcak"), ("soguk", "Soğuk"), ("siyahbeyaz", "Siyah-beyaz"),
                      ("retro", "Retro"), ("dogal", "Doğal")]),
    ("tempo", "Kesim temposu", [("hizli", "Hızlı"), ("normal", "Normal"), ("sakin", "Sakin")]),
]


def options() -> dict:
    return {"questions": [{"key": k, "label": q, "choices": [{"value": v, "label": n} for v, n in c]}
                          for k, q, c in QUESTIONS]}


def describe(opts: dict) -> str:
    return "; ".join(opts.get("brief_notes") or []) or "otomatik"


if __name__ == "__main__":  # hızlı deneme: python -m reels.brief "enerjik, lofi müzik, whoosh, 30 sn"
    import sys
    print(json.dumps(build({"serbest": " ".join(sys.argv[1:])}), ensure_ascii=False, indent=1))
