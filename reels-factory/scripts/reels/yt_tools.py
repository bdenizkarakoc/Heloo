"""YouTube agent skill araçlarının (skills/youtube-agent, MIT) Türkçe uyarlaması ve sisteme bağlanması.

Özgün araçlar İngilizce kelime listeleri ve yalnızca a-z harfleriyle çalışır; Türkçe bir kancayı yanlış
puanlar (ç, ğ, ı, ö, ş, ü harfli kelimeleri böler, "sen/neden/kaybet" gibi sinyalleri görmez). Burada
araçların kendi puanlama mantığı korunur; kelime listeleri Türkçe karşılıklarla genişletilir ve kelime
bölücü Türkçe harfleri tanır. Dosyalar değiştirilmez, modüller yüklendikten sonra uyarlanır.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from functools import lru_cache
from pathlib import Path

from .config import ROOT

SKILLS = ROOT / "skills" / "youtube-agent"
_WORD = re.compile(r"[0-9a-zçğıöşüâîû'%$.]+")


def _lower(t: str) -> str:
    return t.replace("I", "ı").replace("İ", "i").lower()


def _words(t: str) -> list[str]:
    return _WORD.findall(_lower(t))


@lru_cache(maxsize=None)
def _load(name: str, rel: str):
    path = SKILLS / rel
    if str(path.parent) not in sys.path:  # chapters.py, deadair'i kendi klasörü üzerinden içe aktarır
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"ytskill_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- kanca puanı
TR_FILLER = {"yani", "işte", "şey", "arkadaşlar", "merhaba", "selam", "bugün", "video", "videoda", "abone",
             "kanal", "kanala", "açıkçası", "gerçekten", "çok", "hani", "evet", "tamam", "hadi"}
TR_VAGUE = {"inanılmaz", "harika", "muhteşem", "çılgın", "büyük", "dev", "efsane", "efsanevi", "mükemmel",
            "şok", "akılalmaz", "müthiş", "olağanüstü", "devasa", "süper", "en", "iyi"}
# Türkçede 2. kişi çoğunlukla ektedir: biliyor-muydunuz, yapıyor-san, ev-iniz-de
TR_YOU = (r"\b(sen|sana|seni|senin|siz|size|sizi|sizin|sence|sizce)\w*|"
          r"\b\w+(sınız|siniz|sunuz|sünüz|dınız|diniz|dunuz|dünüz|tınız|tiniz|tunuz|tünüz|ysan|ysen|san|sen)\b|"
          r"\b\w{2,}(ınız|iniz|unuz|ünüz)\w*")
TR_STAKE = (r"\b(kaybet\w*|kaybed\w*|kayıp\w*|kaçır\w*|hata\w*|yanlış\w*|dikkat\w*|asla|ölüm\w*|öl\w*|tehlike\w*|bedel\w*|"
            r"pahalı\w*|önce|dur\w*|boşa|risk\w*|yasak\w*|sürgün\w*)\b")
TR_CURIOSITY = (r"\b(neden|niye|nasıl|ne|hangi|kimse|aslında|ama|meğer|gerçek\w*|bilmiyor\w*|bilmediğin\w*|"
                r"sır\w*|gizli\w*|tahmin|düşün\w*|biliyor\s+mu\w*|mı|mi|mu|mü)\b")
TR_CLOSED = r"\b(çünkü|bu yüzden|bu nedenle|yani şu)\b"
TR_CONCRETE = (r"\b(\d[\d,.]*\s?(%|bin|milyon|milyar|k|m|x)?|\d+\s?(saniye|dakika|saat|gün|hafta|ay|yıl|"
               r"yaşında|kilometre|km|metre|derece)\w*)\b|%\s?\d+")


def _hook_module():
    m = _load("hookscore", "yt-script/hookscore.py")
    if not getattr(m, "_tr", False):
        m.words = _words
        m.FILLER = set(m.FILLER) | TR_FILLER
        m.VAGUE = set(m.VAGUE) | TR_VAGUE
        m.CONCRETE = re.compile(m.CONCRETE.pattern + "|" + TR_CONCRETE, re.I)
        m.YOU = re.compile(m.YOU.pattern + "|" + TR_YOU, re.I)
        m.STAKE = re.compile(m.STAKE.pattern + "|" + TR_STAKE, re.I)
        m.CURIOSITY = re.compile(m.CURIOSITY.pattern + "|" + TR_CURIOSITY, re.I)
        closed = re.compile(TR_CLOSED, re.I)
        orig_cur = m.curiosity

        def curiosity(t, _o=orig_cur):  # Türkçede "çünkü" de cevabı kendinde kapatır
            return max(0, _o(t) - (18 if closed.search(t) else 0))

        def brevity(t):  # Türkçe eklemeli: aynı süre ~%20 daha az kelime → 7-20 kelime bandı
            n = len(_words(t))
            if n == 0:
                return 0
            if 7 <= n <= 20:
                return 100
            return max(30, 100 - (7 - n) * 12) if n < 7 else max(10, 100 - (n - 20) * 8)

        m.PROPS = [("SPECIFICITY", m.specificity), ("ADDRESS", m.address), ("STAKES", m.stakes),
                   ("CURIOSITY", curiosity), ("BREVITY", brevity)]
        m._tr = True
    return m


FIX_TR = {"SPECIFICITY": "bir sıfatı sayı, isim veya tarihle değiştir",
          "ADDRESS": "ilk altı kelimede izleyiciye seslen (sen/siz)",
          "STAKES": "izleyicinin neyi kaçıracağını/kaybedeceğini söyle",
          "CURIOSITY": "cümlenin kendi sorusunu cevaplayan yarısını at; kapanmayan bir soru bırak",
          "BREVITY": "7-20 kelime; nefesin bittiği yerde dur"}
BAND_TR = {"STRONG": "güçlü", "WORKABLE": "idare eder", "WEAK": "zayıf"}


def hook_score(text: str) -> dict:
    """Kanca puanı (0-100): ortalamanın %60'ı + en zayıf özelliğin %40'ı (özgün aracın yöntemi)."""
    m = _hook_module()
    parts, verdict, formula, hits = m.score(text)
    weakest = min(parts, key=parts.get)
    return {"hook": text.strip(), "verdict": verdict, "band": m.band(verdict), "band_tr": BAND_TR[m.band(verdict)],
            "properties": parts, "formula": formula, "weakest": weakest, "fix": FIX_TR[weakest]}


def hook_formulas() -> list[dict]:
    import json
    return json.loads((SKILLS / "yt-script" / "hooks.json").read_text(encoding="utf-8"))["hooks"]


# --------------------------------------------------------------------------- başlık + kapak
TR_STOP = {"ve", "ile", "bir", "bu", "şu", "o", "da", "de", "ki", "mi", "mı", "için", "gibi", "en", "çok", "ne",
           "nasıl", "neden", "sen", "siz", "senin", "sizin", "benim", "ben", "biz", "bunu", "şunu", "olan"}


def _title_module():
    m = _load("title", "yt-package/title.py")
    if not getattr(m, "_tr", False):
        m.words = _words
        m.VAGUE = set(m.VAGUE) | TR_VAGUE - {"en", "iyi"}
        m.STOP = set(m.STOP) | TR_STOP
        m._tr = True
    return m


TITLE_ISSUES_TR = {"length": "uzunluk", "mobile": "mobilde kesilir", "shouting": "çok büyük harf", "vague": "belirsiz",
                   "no-number": "sayı/isim/tarih yok", "front-load": "özne başta değil",
                   "duplicate": "kapak başlığı tekrarlıyor", "thumb-length": "kapakta çok kelime"}


def title_check(title: str, thumb: str | None = None) -> dict:
    """Başlık + kapak yazısı denetimi (60 karakter masaüstü, 40 mobil; kapak başlığı tekrar etmemeli).

    Türkçe başlıklarda Türkçe sayılar ve özel adlar da 'somut' sayılır."""
    m = _title_module()
    r = m.check(title, thumb)
    if any(i[0] == "no-number" for i in r["issues"]) and re.search(r"(\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\b.*){2}", title[1:]):
        r["issues"] = [i for i in r["issues"] if i[0] != "no-number"]  # özel ad var (ör. Cem Karaca)
        r["good"].append("özel ad içeriyor")
        r["score"] = max(0, min(100, 100 - 14 * len(r["issues"]) + 4 * len(r["good"])))
    r["issues_tr"] = [f"{TITLE_ISSUES_TR.get(k, k)}: {msg}" for k, msg in r["issues"]]
    return r


# --------------------------------------------------------------------------- kesim listesi + bölümler
TR_FILLER_ONLY = re.compile(r"^[\s,.-]*((ı+|ee+|ıı+|hmm+|şey|yani|işte|hani|tamam|evet|neyse|aslında|"
                            r"nasıl desem|ne diyordum)[\s,.-]*)+$", re.I)


def edl(srt: Path, floor: float = 0.45) -> dict:
    """Boşluk / dolgu / yeniden başlama kesim listesi (özgün deadair mantığı + Türkçe dolgu sözcükleri)."""
    m = _load("deadair", "yt-edit/deadair.py")
    cues = m.load(str(srt))
    cuts = []
    for i, (s, e, t) in enumerate(cues):
        if m.FILLER_ONLY.match(t) or TR_FILLER_ONLY.match(t):
            cuts.append({"kind": "FILLER", "start": s, "end": e, "why": t.strip()[:48]})
        if i and s - cues[i - 1][1] > floor:
            cuts.append({"kind": "DEAD", "start": round(cues[i - 1][1] + floor / 2, 3), "end": round(s - floor / 2, 3),
                         "why": f"{s - cues[i - 1][1]:.2f} sn boşluk"})
        if i:
            a, b = _words(cues[i - 1][2])[:5], _words(t)[:5]
            if len(a) >= 3 and a == b:
                cuts.append({"kind": "REPEAT", "start": cues[i - 1][0], "end": cues[i - 1][1],
                             "why": "yeniden başlama: " + " ".join(a)})
    cuts = sorted((c for c in cuts if c["end"] > c["start"]), key=lambda c: c["start"])
    dur = cues[-1][1] if cues else 0.0
    removed = sum(c["end"] - c["start"] for c in cuts)
    return {"duration": dur, "cuts": cuts, "removed": round(removed, 2), "out": round(dur - removed, 2)}


TR_CH_STOP = TR_STOP | {"olarak", "daha", "sonra", "kadar", "çünkü", "ama", "ancak", "değil", "var", "yok", "oldu",
                        "olur", "olan", "olarak", "şimdi", "zaman", "bunun", "onun", "gerçekten", "aslında"}


def chapters(srt: Path, target: int = 7) -> dict:
    """YouTube bölümleri (00:00 ile başlar, en az 3 bölüm, her biri ≥10 sn) — Türkçe anahtar kelimelerle."""
    m = _load("chapters", "yt-chapters/chapters.py")
    m.keywords = lambda text: {w for w in re.findall(r"[a-zçğıöşü']{4,}", _lower(text)) if w not in m.STOP | TR_CH_STOP}
    cues = m.load(str(srt))
    if len(cues) < 6:
        return {"valid": False, "chapters": [], "reason": "çok az konuşma"}
    dur = cues[-1][1]
    cand = []
    for i in range(1, len(cues)):
        gap = cues[i][0] - cues[i - 1][1]
        kb = m.keywords(" ".join(c[2] for c in cues[max(0, i - 12):i]))
        ka = m.keywords(" ".join(c[2] for c in cues[i:i + 12]))
        shift = 1 - (len(kb & ka) / len(kb | ka)) if (kb | ka) else 0
        cand.append((gap * 1.6 + shift * 3.2, cues[i][0]))
    picked = [0.0]
    for _, t in sorted(cand, reverse=True):
        if len(picked) >= target:
            break
        if all(abs(t - p) >= 10 for p in picked) and dur - t >= 10:
            picked.append(t)
    picked.sort()
    out = []
    for n, t in enumerate(picked):
        end = picked[n + 1] if n + 1 < len(picked) else dur
        text = " ".join(c[2] for c in cues if c[0] >= t and c[1] <= end)
        kw = sorted(m.keywords(text), key=lambda w: -_lower(text).count(w))
        out.append({"start": round(t, 2), "label": m.mmss(t), "title": " ".join(w.capitalize() for w in kw[:3]) or "Bölüm",
                    "seconds": round(end - t, 2)})
    ok = len(out) >= 3 and all(c["seconds"] >= 10 for c in out)
    return {"valid": ok, "chapters": out, "text": "\n".join(f"{c['label']} {c['title']}" for c in out)}
