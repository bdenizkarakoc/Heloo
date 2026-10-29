"""script.json biçimi, doğrulama ve varsayılanlar.

Senaryo bir dil modeli (Claude Code oturumu veya Claude API) tarafından yazılır;
bu modül hatalı/eksik senaryonun üretim hattına girmesini engeller.
"""
from __future__ import annotations

import re
from typing import Any

from .config import Config
from .util import words_of

LAYOUT_FIELDS: dict[str, dict[str, Any]] = {
    "hook": {"required": ["headline"], "optional": ["kicker", "highlight"]},
    "photo": {"required": [], "optional": ["label", "headline", "highlight"]},
    "stat": {"required": ["value", "unit"], "optional": ["label", "decimals", "prefix", "suffix", "cue", "note"]},
    "compare": {"required": ["items"], "optional": ["title", "unit", "cues", "note"]},
    "list": {"required": ["items"], "optional": ["title", "cues"]},
    "fact": {"required": ["headline"], "optional": ["label", "highlight"]},
    "outro": {"required": ["headline"], "optional": ["highlight", "cta"]},
}
ROLES = {"hook", "setup", "body", "payoff", "outro"}
VISUAL_KINDS = {"photo", "video", "graphic"}
TRANSITIONS = {"zoom", "whip", "iris", "wipe", "cut"}
DEFAULT_TRANSITIONS = ["zoom", "whip", "wipe", "iris", "whip", "zoom", "wipe", "iris", "whip"]

MAX_CTA_CHARS = 28
MAX_HEADLINE_CHARS = {"hook": 42, "photo": 48, "fact": 90, "outro": 60}


class ScriptError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def text_problems(text: str, where: str) -> list[str]:
    """Basit yazım/noktalama kontrolleri (otomatik düzeltilemeyenler hata olarak döner)."""
    probs = []
    if "  " in text:
        probs.append(f"{where}: çift boşluk")
    if re.search(r"\s[,.;:!?]", text):
        probs.append(f"{where}: noktalama işaretinden önce boşluk")
    if re.search(r"[,.;:!?](?=[^\s\d\"'’)».…!?])", text):
        probs.append(f"{where}: noktalama işaretinden sonra boşluk eksik")
    for a, b in (("(", ")"), ("“", "”"), ("«", "»")):
        if text.count(a) != text.count(b):
            probs.append(f"{where}: eşleşmeyen {a}{b}")
    if text.count('"') % 2:
        probs.append(f"{where}: eşleşmeyen tırnak")
    return probs


def autofix_text(text: str) -> str:
    """Güvenli otomatik düzeltmeler: boşluklar ve noktalama aralıkları."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:!?])(?=[^\s\d\"'’)»])", r"\1 ", t)
    t = re.sub(r"\.(?=[A-ZÇĞİÖŞÜ])", ". ", t)
    return t


def estimate_seconds(script: dict, wps: float) -> float:
    words = sum(len(words_of(s.get("narration", ""))) for s in script.get("scenes", []))
    return words / max(wps, 0.5) + 0.3 * len(script.get("scenes", []))


def normalize(script: dict, cfg: Config) -> dict:
    """Varsayılanları doldurur ve güvenli düzeltmeleri uygular; ardından validate() çağrılmalı."""
    s = dict(script)
    s.setdefault("language", "tr")
    scenes = []
    for i, raw in enumerate(s.get("scenes", [])):
        sc = dict(raw)
        sc.setdefault("id", f"s{i + 1}")
        sc["id"] = re.sub(r"[^a-z0-9]", "", str(sc["id"]).lower()) or f"s{i + 1}"
        if not sc["id"][0].isalpha():
            sc["id"] = f"s{sc['id']}"
        sc.setdefault("role", "hook" if i == 0 else "body")
        sc.setdefault("layout", "hook" if i == 0 else "photo")
        sc["narration"] = autofix_text(str(sc.get("narration", "")))
        sc.setdefault("on_screen", {})
        cta = str(sc["on_screen"].get("cta") or "").strip()
        if len(cta) > MAX_CTA_CHARS:  # takip çağrısı tek satırlık etikettir: ilk bölümü kalır
            head = re.split(r"[,;:—–]", cta)[0].strip()
            if not (4 <= len(head) <= MAX_CTA_CHARS):  # yarım cümle yerine kanalın kısa çağrısı
                brand = str(cfg.get_path("brand.cta", "") or "")
                head = brand if 0 < len(brand) <= MAX_CTA_CHARS else "Takip et"
            sc["on_screen"]["cta"] = head.rstrip(",;:—–-. ")
        vis = dict(sc.get("visual") or {})
        vis.setdefault("kind", "graphic" if sc["layout"] in ("compare", "list") else "photo")
        vis.setdefault("fit", "auto")
        sc["visual"] = vis
        sc.setdefault("emphasis", [])
        sc.setdefault("captions", True)
        if i == 0:
            sc.setdefault("transition", "cut")
        else:
            sc.setdefault("transition", DEFAULT_TRANSITIONS[(i - 1) % len(DEFAULT_TRANSITIONS)])
        scenes.append(sc)
    s["scenes"] = scenes
    s.setdefault("sources", [])
    s.setdefault("facts", [])
    post = dict(s.get("post") or {})
    post.setdefault("caption", s.get("title", ""))
    post.setdefault("hashtags", [])
    post["hashtags"] = [h if h.startswith("#") else f"#{h}" for h in post["hashtags"]]
    s["post"] = post
    return s


def validate(script: dict, cfg: Config) -> list[str]:
    """Hata listesi döndürür (boşsa senaryo üretime hazırdır). Uyarılar 'UYARI:' ile başlar."""
    probs: list[str] = []
    if not script.get("title"):
        probs.append("title eksik")
    scenes = script.get("scenes") or []
    lo, hi = cfg.get_path("script.min_scenes", 5), cfg.get_path("script.max_scenes", 10)
    if not (lo <= len(scenes) <= hi):
        probs.append(f"sahne sayısı {len(scenes)}; {lo}-{hi} olmalı")
    ids = [sc.get("id") for sc in scenes]
    if len(set(ids)) != len(ids):
        probs.append("sahne kimlikleri benzersiz değil")
    for sc in scenes:
        where = f"sahne {sc.get('id')}"
        layout = sc.get("layout")
        if layout not in LAYOUT_FIELDS:
            probs.append(f"{where}: bilinmeyen layout '{layout}' ({', '.join(LAYOUT_FIELDS)})")
            continue
        if sc.get("role") not in ROLES:
            probs.append(f"{where}: role {sorted(ROLES)} içinden olmalı")
        narration = sc.get("narration", "")
        if len(words_of(narration)) < 3:
            probs.append(f"{where}: seslendirme metni çok kısa")
        if narration and narration[-1] not in ".!?…":
            probs.append(f"{where}: seslendirme cümlesi noktalama ile bitmeli")
        probs += text_problems(narration, f"{where}.narration")
        ons = sc.get("on_screen") or {}
        for key in LAYOUT_FIELDS[layout]["required"]:
            if ons.get(key) in (None, "", []):
                probs.append(f"{where}: on_screen.{key} zorunlu ({layout})")
        head = ons.get("headline")
        if head and layout in MAX_HEADLINE_CHARS and len(head) > MAX_HEADLINE_CHARS[layout]:
            probs.append(f"{where}: başlık {len(head)} karakter; en fazla {MAX_HEADLINE_CHARS[layout]}")
        if layout == "stat" and not isinstance(ons.get("value"), (int, float)):
            probs.append(f"{where}: stat.value sayı olmalı")
        if layout == "compare":
            items = ons.get("items") or []
            if not (2 <= len(items) <= 3):
                probs.append(f"{where}: compare 2-3 öğe içermeli")
            for it in items:
                if not isinstance(it, dict) or not isinstance(it.get("value"), (int, float)) or not it.get("label"):
                    probs.append(f"{where}: compare öğeleri {{label, value}} olmalı")
                    break
        if layout == "list":
            items = ons.get("items") or []
            if not (2 <= len(items) <= 4):
                probs.append(f"{where}: list 2-4 madde içermeli")
            long_items = [i for i in items if len(str(i)) > 28]
            if long_items:
                probs.append(f"{where}: liste maddeleri en fazla 28 karakter olmalı: {long_items[0]}")
        if re.search(r"[°&/#@]", narration):
            probs.append(f"{where}: seslendirmede sembol var (°, &, /, #, @) — kelimeyle yazın")
        vis = sc.get("visual") or {}
        if vis.get("kind") not in VISUAL_KINDS:
            probs.append(f"{where}: visual.kind {sorted(VISUAL_KINDS)} içinden olmalı")
        if vis.get("kind") in ("photo", "video") and not (vis.get("query") or vis.get("prompt") or vis.get("url")
                                                          or vis.get("reuse") or vis.get("user") or "agent_media" in (vis.get("providers") or [])):
            probs.append(f"{where}: fotoğraf/video sahnesi için visual.query, visual.prompt veya visual.reuse gerekli")
        if vis.get("reuse") and vis["reuse"] not in ids[: ids.index(sc.get("id"))]:
            probs.append(f"{where}: visual.reuse önceki bir sahnenin kimliği olmalı")
        if sc.get("transition") not in TRANSITIONS:
            probs.append(f"{where}: transition {sorted(TRANSITIONS)} içinden olmalı")
    if scenes and scenes[0].get("layout") != "hook":
        probs.append("ilk sahne 'hook' layout'u olmalı (ilk 1-3 saniye)")
    if cfg.get_path("script.require_sources", True):
        srcs = script.get("sources") or []
        if not srcs or not all(isinstance(x, dict) and x.get("url") for x in srcs):
            probs.append("sources: en az bir kaynak {title, url} zorunlu (uydurma bilgi engeli)")
    est = estimate_seconds(script, cfg.get_path("script.words_per_second", 2.3))
    dmin = cfg.get_path("output.duration.min", 30)
    dmax = cfg.get_path("output.duration.hard_max", 90)
    if est < dmin * 0.8:
        probs.append(f"tahmini süre {est:.0f} sn; çok kısa (en az ~{dmin} sn)")
    elif est > dmax:
        probs.append(f"tahmini süre {est:.0f} sn; çok uzun (en fazla {dmax} sn)")
    elif est > cfg.get_path("output.duration.max", 60):
        probs.append(f"UYARI: tahmini süre {est:.0f} sn; varsayılan üst sınırın üzerinde")
    probs += packaging_warnings(script, cfg)
    return probs


def packaging_warnings(script: dict, cfg: Config) -> list[str]:
    """YouTube agent skill araçlarıyla (Türkçe uyarlama) kanca ve başlık/kapak denetimi — yalnızca uyarı."""
    try:
        from .yt_tools import hook_score, title_check
    except Exception:  # noqa: BLE001 — beceri klasörü yoksa denetim atlanır
        return []
    out = []
    scenes = script.get("scenes") or []
    hook = (scenes[0].get("narration") or "") if scenes else ""
    if hook:
        h = hook_score(hook)
        if h["verdict"] < int(cfg.get_path("script.min_hook_score", 45)):
            out.append(f"UYARI: kanca puanı {h['verdict']}/100 ({h['band_tr']}; kalıp: {h['formula']}) — en zayıf: "
                       f"{h['weakest']} → {h['fix']}. `factory.py hook \"...\"` ile alternatifleri puanla.")
    title = script.get("title") or ""
    cover = (scenes[0].get("headline") or "") if scenes else ""
    if title:
        t = title_check(title, cover or None)
        bad = [i for k, i in zip([x[0] for x in t["issues"]], t["issues_tr"]) if k in ("duplicate", "length", "shouting")]
        if bad:
            out.append("UYARI: başlık/kapak — " + "; ".join(bad))
    return out


def errors_only(problems: list[str]) -> list[str]:
    return [p for p in problems if not p.startswith("UYARI:")]
