"""Öneri üreticiler: Claude API (varsa) veya çevrimdışı şablon kütüphanesi.

İkisi de yalnızca TEK BİR yeni eklenti dosyası önerebilir; çekirdek koda dokunamazlar.
"""
import json
import os
import re

from . import store

INTERFACE_DOC = '''Bir eklenti, plugins/ klasöründe tek bir .py dosyasıdır ve tam olarak şunu tanımlar:

NAME = "ad"                       # dosya adıyla aynı, küçük harf/rakam/_
DESCRIPTION = "Türkçe kısa açıklama"
PARAMS = {"amount": 1.0}          # varsayılan değerler; tür varsayılandan çıkarılır (int/float/str/bool)

def video_filter(params, ctx):    # FFmpeg video filtresi metni döndürür (veya None)
    return f"eq=contrast={params['amount']}"

def audio_filter(params, ctx):    # isteğe bağlı, FFmpeg ses filtresi
    return None

def duration_factor(params):      # isteğe bağlı; süreyi değiştiriyorsa (ör. hız) yeni/eski oranı
    return 1.0

ctx sözlüğü: duration (sn), fps, width, height, font, textfile(metin)->güvenli dosya yolu.

KATI KURALLAR:
- Yalnızca `math` ve `re` import edilebilir. open/eval/exec/getattr/__dunder__/class/lambda yasak.
- Üst düzeyde yalnızca import, sabit atamalar, fonksiyonlar. Import anında kod çalışamaz.
- Döndürülen filtre ';', '[', ']' veya satır sonu içeremez.
- Filtre çıktı boyutunu (width x height) DEĞİŞTİRMEMELİ.
- Geçersiz parametrede ValueError fırlat. Dosya 8000 baytı geçmesin.'''


class Proposal(dict):
    pass


def _make(name, title, rationale, code, source) -> dict:
    import time
    return {
        "id": store.new_id(name), "created": time.time(), "plugin_name": name, "title": title,
        "rationale": rationale, "code": code, "source": source, "status": "pending",
        "validation": None,
    }


# ---------- Çevrimdışı şablonlar ----------

_TEMPLATES = [
    # (ad, açıklama, anahtar kelimeler, PARAMS, gövde)
    ("sepia", "Sepya (nostaljik kahverengi) ton", ["sepya", "sepia", "nostalji", "eski film"], {},
     'return "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"'),
    ("vignette", "Kenarları karartan vinyet", ["vinyet", "vignette", "kenar"], {},
     'return "vignette=PI/4"'),
    ("sharpen", "Keskinleştirme", ["keskin", "sharpen", "netleş"], {"amount": 1.0},
     'a = params["amount"]\n    if not 0.0 <= a <= 5.0:\n        raise ValueError("amount 0 ile 5 arasında olmalı")\n'
     '    return f"unsharp=5:5:{a}:5:5:0.0"'),
    ("negate", "Renkleri tersine çevirir (negatif)", ["negatif", "negate", "ters renk"], {},
     'return "negate"'),
    ("hflip", "Yatay aynalama", ["aynala", "mirror", "hflip", "yatay"], {},
     'return "hflip"'),
    ("vflip", "Dikey çevirme", ["dikey", "vflip", "baş aşağı"], {},
     'return "vflip"'),
    ("contrast", "Kontrast ayarı", ["kontrast", "contrast"], {"amount": 1.3},
     'a = params["amount"]\n    if not 0.0 <= a <= 4.0:\n        raise ValueError("amount 0 ile 4 arasında olmalı")\n'
     '    return f"eq=contrast={a}"'),
    ("saturation", "Renk doygunluğu ayarı", ["doygun", "saturation", "canlı", "renk"], {"amount": 1.5},
     'a = params["amount"]\n    if not 0.0 <= a <= 3.0:\n        raise ValueError("amount 0 ile 3 arasında olmalı")\n'
     '    return f"eq=saturation={a}"'),
    ("noise", "Film grenine benzer gürültü ekler", ["gürültü", "grain", "noise", "tane", "gren"], {"strength": 20},
     's = params["strength"]\n    if not 0 <= s <= 100:\n        raise ValueError("strength 0 ile 100 arasında olmalı")\n'
     '    return f"noise=alls={s}:allf=t+u"'),
    ("pixelate", "Pikselleştirme / mozaik", ["piksel", "pixel", "mozaik", "sansür"], {"factor": 16},
     'f = params["factor"]\n    if not 2 <= f <= 128:\n        raise ValueError("factor 2 ile 128 arasında olmalı")\n'
     '    return f"scale=iw/{f}:ih/{f},scale={ctx[\'width\']}:{ctx[\'height\']}:flags=neighbor"'),
]


def _template_code(name, desc, params, body) -> str:
    return (f'NAME = "{name}"\nDESCRIPTION = "{desc}"\nPARAMS = {params!r}\n\n\n'
            f"def video_filter(params, ctx):\n    {body}\n")


class OfflineProposer:
    source = "offline"

    def propose(self, summary: dict, registry):
        taken = set(registry.names()) | store.known_names()
        wish_text = " ".join(summary.get("wishes", [])).lower()
        wanted = " ".join(summary.get("unknown_effects_requested", {})).lower()
        candidates = [t for t in _TEMPLATES if t[0] not in taken]
        if not candidates:
            return None

        def score(t):
            s = 0
            if t[0] in wanted:
                s += 10                     # kullanıcı bu adla efekt aradı
            s += sum(3 for k in t[2] if k in wish_text)   # dilek listesinde geçiyor
            return s

        best = max(candidates, key=score)  # eşitlikte listedeki ilk
        why = ("Kullanıcı bu efekti istedi/aradı." if score(best) else
               "Efekt kütüphanesindeki bir sonraki yaygın eksik efekt.")
        return _make(best[0], f"Yeni efekt: {best[0]}", why,
                     _template_code(best[0], best[1], best[3], best[4]), self.source)


# ---------- Claude API ----------

class LLMProposer:
    source = "claude"

    def __init__(self, model: str):
        self.model = model

    @staticmethod
    def available() -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def propose(self, summary: dict, registry):
        import anthropic
        client = anthropic.Anthropic()
        taken = sorted(set(registry.names()) | store.known_names())
        prompt = (
            "Bir video düzenleme uygulamasının efekt kütüphanesini geliştiriyorsun.\n\n"
            f"{INTERFACE_DOC}\n\n"
            f"Mevcut/önerilmiş eklenti adları (tekrar etme): {taken}\n\n"
            f"Kullanım özeti (JSON):\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n\n"
            "Bu verilere göre kullanıcıya en çok fayda sağlayacak TEK yeni eklentiyi yaz. "
            "Önce kullanıcı dileklerine ve bulunamayan efekt isteklerine bak, yoksa yaygın bir eksik efekti seç.\n"
            'Yanıtın yalnızca şu JSON olsun: {"plugin_name": "...", "title": "...", '
            '"rationale": "...", "code": "...tam .py dosyası..."}')
        resp = client.messages.create(
            model=self.model, max_tokens=3000,
            system="Yalnızca istenen JSON'u döndür. Kod kurallara tam uymalı.",
            messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
            return _make(d["plugin_name"], d.get("title", d["plugin_name"]),
                         d.get("rationale", ""), d["code"], self.source)
        except (ValueError, KeyError, TypeError):
            return None


def pick(cfg: dict, offline: bool = False):
    if not offline and LLMProposer.available():
        return LLMProposer(cfg.get("model", "claude-sonnet-5-5"))
    return OfflineProposer()
