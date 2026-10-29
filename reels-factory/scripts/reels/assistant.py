"""AI asistan: kullanıcının yazdığı ya da söylediği isteği komutlara çevirir ve ne anladığını açıkça söyler.

Sayfa (Fabrika paneli, Kesim, Fotoğraflarım) kendi komut listesini gönderir ({name, args, desc}); asistan bunlardan
plan çıkarır: {"anladigim": "...", "adimlar": [{"komut": "video", "arg": "..."}], "soru": null}. Planı sayfa
çalıştırır (her adımın sonucu ekranda görünür). Claude kullanılamazsa basit anahtar kelime kuralları devreye girer.
Konuşma: ses kaydı yüklenir, ekran kartı varsa büyük modelle (large-v3-turbo) yazıya dökülür.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import log
from .config import ROOT, load_config
from .util import run

L = log.get("assistant")
URL_RE = re.compile(r"https?://\S+", re.I)

PROMPT = """Sen "Reels Fabrikası" uygulamasının Türkçe asistanısın. Kullanıcı bir istek yazdı ya da söyledi
(konuşmadan yazıya dökülmüş olabilir; küçük yazım/anlama hatalarını mantıkla düzelt).

İstek: «{text}»
{context}
Kullanabileceğin komutlar (yalnızca bunlar):
{commands}

Görevin: isteği bu komutlardan bir ya da birkaç adıma çevir. Kurallar:
- "anladigim": ne yapacağını kullanıcıya tek, sade bir Türkçe cümleyle söyle (ör. "Venüs hakkında 40 saniyelik bir
  video üreteceğim."). Teknik terim ve komut adı kullanma.
- "adimlar": [{{"komut": "<ad>", "arg": "<argüman metni>"}}] — argüman, komutun beklediği biçimde (ör. video için konu,
  ref için önce bağlantı sonra istek). En çok 4 adım.
- İstek belirsizse ya da gerekli bilgi yoksa (ör. konu yok, bağlantı yok) adim yazma; "soru" alanına kısa bir soru yaz.
- İstek komutlarla yapılamıyorsa "adimlar" boş, "soru" null, "anladigim" içinde neyin yapılamadığını dürüstçe söyle.
- Sohbet/soru ise (ör. "neler yapabiliyorsun?") adım yazma, "cevap" alanında kısa cevap ver.
Biçim: {{"anladigim": "...", "adimlar": [...], "soru": null, "cevap": null}}"""


def _rules(text: str, names: set[str]) -> dict:
    """Claude yokken: anahtar kelimelerle en olası komut."""
    t = text.lower()
    url = URL_RE.search(text)
    rest = URL_RE.sub("", text).strip()
    if url and "ref" in names and re.search(r"gibi|benze|aynı|tarz", t):
        return {"anladigim": "Bu bağlantıdaki videonun tarzıyla montaj yapacağım.", "adimlar": [{"komut": "ref", "arg": f"{url.group(0)} {rest}"}]}
    q = re.split(r"[:：]", text, maxsplit=1)
    if re.search(r"kanca|açılış|ilk cümle|hook", t) and "kanca" in names:
        return {"anladigim": "Açılış cümlesinin kanca puanına bakacağım.",
                "adimlar": [{"komut": "kanca", "arg": (q[1] if len(q) > 1 else text).strip().strip('"“”')}]}
    if re.search(r"başlık", t) and "baslik" in names and len(q) > 1:
        return {"anladigim": "Başlığı denetleyeceğim.", "adimlar": [{"komut": "baslik", "arg": q[1].strip().strip('"“”')}]}
    if url and "not" in names:
        return {"anladigim": "Bu videodan not çıkaracağım.", "adimlar": [{"komut": "not", "arg": url.group(0)}]}
    if re.search(r"fotoğraf|foto", t) and "foto" in names:
        anlat = re.search(r"anlat|seslendir|hikaye|hikâye", t) and "anlat" in names
        return {"anladigim": "Seçili fotoğraflarından " + ("anlatımlı" if anlat else "müzikli") + " bir video yapacağım.",
                "adimlar": [{"komut": "anlat" if anlat else "foto", "arg": text}]}
    if re.search(r"montaj|birleştir|kes", t) and "kesim" in names:
        return {"anladigim": "Videolarını montajlayacağım.", "adimlar": [{"komut": "kesim", "arg": text}]}
    if re.search(r"altyazı", t) and "altyazi" in names:
        return {"anladigim": "Seçili klibe altyazı ekleyeceğim.", "adimlar": [{"komut": "altyazi", "arg": ""}]}
    if re.search(r"durum|ne yapıyor|bitti mi", t) and "durum" in names:
        return {"anladigim": "Fabrikanın durumuna bakıyorum.", "adimlar": [{"komut": "durum", "arg": ""}]}
    m = re.search(r"(.+?)\s+(hakkında|ile ilgili|konulu)?\s*(bir )?video", t)
    if "video" in names and ("video" in t or len(text.split()) <= 8):
        topic = m.group(1) if m else text
        return {"anladigim": f"“{topic.strip()}” hakkında video üreteceğim.", "adimlar": [{"komut": "video", "arg": topic.strip()}]}
    return {"anladigim": "", "adimlar": [], "soru": "Tam olarak ne yapmamı istersin? (ör. “Venüs hakkında video yap”)"}


def plan(text: str, commands: list[dict], context: str = "") -> dict:
    text = (text or "").strip()[:1500]
    if not text:
        return {"anladigim": "", "adimlar": [], "soru": "Bir şey yazmadın ya da söylemedin."}
    names = {str(c.get("name")) for c in commands}
    cmd_txt = "\n".join(f"- {c.get('name')} {c.get('args') or ''} — {c.get('desc') or ''}" for c in commands
                        if c.get("name") not in ("yardim",))
    cfg = load_config()
    from .studio import ai_mode, ask_ai
    res = None
    if ai_mode(cfg) != "none":
        out = ROOT / "studio" / "cache" / "assistant.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        res = ask_ai(cfg, PROMPT.format(text=text, commands=cmd_txt,
                                        context=f"Ekrandaki durum: {context[:600]}\n" if context else ""), [], out, timeout=180)
    if not isinstance(res, dict):
        res = _rules(text, names)
        res["kural"] = True
        from . import llm
        if llm.cli_limited():   # Claude sınırı: kullanıcı neden "basit" cevap aldığını bilsin
            res["uyari"] = llm.limit_message()
    steps = [s for s in (res.get("adimlar") or []) if isinstance(s, dict) and s.get("komut") in names][:4]
    res["adimlar"] = [{"komut": s["komut"], "arg": str(s.get("arg") or "")} for s in steps]
    L.info("Asistan: «%s» → %s", text[:80], [s["komut"] for s in steps] or res.get("soru") or "cevap")
    return res


def listen(upload_name: str) -> dict:
    """Yüklenmiş ses kaydını yazıya döker (ekran kartı varsa büyük model)."""
    from . import studio
    src = studio.UPLOADS / Path(str(upload_name)).name
    if not src.is_file():
        raise ValueError("ses kaydı bulunamadı")
    work = ROOT / "studio" / "cache" / "listen"
    work.mkdir(parents=True, exist_ok=True)
    for f in work.glob("words_*.json"):
        f.unlink()
    wav = work / "kayit.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1", "-ar", "16000", wav])
    words = studio.transcribe(wav, work, load_config())
    src.unlink(missing_ok=True)   # geçici kayıt
    text = " ".join(w["word"] for w in words).strip()
    return {"text": text, "gpu": bool(studio._WHISPER.get("gpu"))}
