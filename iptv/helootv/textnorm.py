"""Türkçe duyarlı metin işlemleri: arama/sıralama anahtarı, EPG ad eşleştirme, grup çevirisi, yetişkin filtresi."""
from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
})


def norm(text: str | None) -> str:
    """Arama anahtarı: küçük harf, Türkçe karakterler sadeleşir ("İstanbul" → "istanbul", "Şov" → "sov")."""
    s = (text or "").translate(_TR_MAP).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


_QUALITY_RE = re.compile(
    r"\b(4k|uhd|fhd|hd|sd|hevc|h265|h\.265|h264|backup|yedek|raw|50fps|60fps|1080p|720p|576p|480p|2160p|"
    r"1080i|576i|720|1080|tr|turk|turkiye|tur)\b"
)
_BRACKETS_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")
_PREFIX_RE = re.compile(r"^\s*([a-z]{2,3})\s*[:|\-]\s*")


def match_key(name: str | None) -> str:
    """EPG eşleştirme anahtarı: kalite/ülke etiketleri ve parantezler atılır ("TR: TRT 1 HD (1080p)" → "trt1")."""
    s = norm(name)
    s = _BRACKETS_RE.sub(" ", s)
    s = _PREFIX_RE.sub("", s)
    s = re.sub(r"[|:•·]", " ", s)
    s = _QUALITY_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


GROUP_TR = {
    "general": "Genel", "news": "Haber", "sports": "Spor", "sport": "Spor", "music": "Müzik", "kids": "Çocuk",
    "documentary": "Belgesel", "entertainment": "Eğlence", "religious": "Dini", "undefined": "Diğer",
    "movies": "Film", "movie": "Film", "series": "Dizi", "education": "Eğitim", "animation": "Animasyon",
    "culture": "Kültür", "travel": "Gezi", "lifestyle": "Yaşam", "business": "Ekonomi", "weather": "Hava Durumu",
    "cooking": "Yemek", "comedy": "Komedi", "classic": "Klasik", "family": "Aile", "legislative": "Meclis",
    "outdoor": "Doğa", "science": "Bilim", "shop": "Alışveriş", "auto": "Otomobil", "relax": "Rahatlama",
    "local": "Yerel", "public": "Kamu", "interactive": "Etkileşimli", "other": "Diğer", "uncategorized": "Diğer",
}


def translate_group(name: str) -> str:
    """iptv-org gibi İngilizce grup adlarını Türkçeye çevirir ("Animation;Kids" → "Animasyon, Çocuk")."""
    parts = [p.strip() for p in re.split(r"[;]", name or "") if p.strip()]
    if not parts:
        return name or ""
    out = [GROUP_TR.get(p.lower(), p) for p in parts]
    return ", ".join(dict.fromkeys(out))


_ADULT_RE = re.compile(r"(^|[^a-z0-9])(xxx|adult|adults|porn|porno|erotik|erotic|yetiskin|18\s?\+|\+\s?18|for adults)([^a-z0-9]|$)")


def is_adult(*names: str | None) -> bool:
    return any(_ADULT_RE.search(norm(n)) for n in names if n)


def sort_key(text: str | None) -> str:
    return norm(text)
