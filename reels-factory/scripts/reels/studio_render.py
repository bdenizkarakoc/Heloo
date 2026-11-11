"""Stüdyo render motoru: kullanıcının videosunu bir stile göre düzenler (yalnızca ffmpeg + libass).

Bir klip = kaynağın bir penceresi. Pencere içinde konuşma boşlukları kesilir (jump cut), görüntü 9:16'ya
(veya kaynağın oranına) çerçevelenir, renk düzenlenir, kesimlerde zoom "punch" uygulanır, kelime vurgulu
altyazılar + açılış başlığı (ASS) ve ilerleme çubuğu eklenir; ses isteğe bağlı müzikle kısılarak
(sidechain) karıştırılır ve -14 LUFS'a normalize edilir.
"""
from __future__ import annotations

import copy
import math
import re
import shutil
from pathlib import Path

from PIL import ImageFont

from . import log
from .audio import loudnorm_two_pass, pick_music
from .config import ROOT, Config
from .util import StageError, ffprobe, run, tr_upper

L = log.get("studio")
FONT_VF = ROOT / "assets" / "fonts" / "Montserrat-VariableFont_wght.ttf"
FONT_CACHE = ROOT / "studio" / "cache" / "fonts"
FONT_FAMILY = "RF Studio"

DEFAULT_STYLE: dict = {
    "name": "Fabrika", "description": "Kalın büyük harf altyazı, sarı kelime vurgusu, kesimlerde zoom, canlı renk.",
    "pacing": {"max_pause": 0.45, "pad": 0.10, "keep_gaps": 4.0, "fillers": True},   # fillers: "ııı", "eee" kesilir
    "frame": {"mode": "blur"},
    "grade": {"contrast": 1.06, "saturation": 1.15, "brightness": 0.0, "gamma": 1.0, "warmth": 0.0,
              "vignette": True, "look": ""},   # look: "" | teal | film | dramatik | pastel
    # mode: "punch" ani zoom | "smooth" parça boyunca yavaş yakınlaşma; bump: her kesimde 0,2 sn'lik zoom darbesi
    "punch": {"enabled": True, "scale": 1.12, "interrupt": 2.8, "emphasis": 1.08, "mode": "punch", "bump": 0.04},
    "captions": {"enabled": True, "weight": 900, "size": 78, "uppercase": True, "color": "#FFFFFF",
                 "highlight": "#FFD23F", "outline": 7, "outline_color": "#000000", "shadow": 2, "box": False,
                 "box_color": "#000000", "words": 3, "y": 0.64, "pop": True,
                 # anim: pop | bounce (her kelime zıplar) | kutu (konuşulan kelime renkli kutuda) | tek (tek kelime) | daktilo
                 "anim": "pop", "keyword": ""},   # keyword: sayı/vurgu kelimelerinin kalıcı rengi ("" = kapalı)
    "title": {"enabled": True, "seconds": 3.0, "size": 70, "weight": 900, "uppercase": True,
              "fg": "#111111", "bg": "#FFD23F", "y": 0.17},
    "progress": {"enabled": True, "color": "#FFD23F", "height": 10, "position": "bottom"},
    "flash": {"enabled": True},
    # kesim/film efektleri: cut_flash kesimde beyaz parlama (0-0.3), grain film greni (0-30), letterbox sinema şeridi
    # (ekran oranı 0-0.15), glow parıltı (0-0.5), vhs renk kayması (px 0-8), sharpen keskinlik (0-1.5), fade_out sn
    "fx": {"cut_flash": 0.0, "grain": 0, "letterbox": 0.0, "glow": 0.0, "vhs": 0, "sharpen": 0.0, "fade_out": 0.35},
    "outro": {"enabled": False, "text": "Takip et!", "seconds": 1.8},   # bitiş kartı
    "music": {"enabled": False, "gain_db": -18, "mood": "upbeat"},
    "sfx": {"enabled": False, "query": "whoosh", "gain_db": -9, "min_gap": 2.5},   # kesimlerde geçiş sesi (kütüphane)
}


LOOKS = {   # hazır renk görünümleri (grade.look)
    "": "",
    "teal": "colorbalance=rs=-0.06:bs=0.08:rh=0.07:bh=-0.07",              # turkuaz gölge, turuncu ten
    "film": "curves=all='0/0.06 0.5/0.5 1/0.94'",                          # soluk film: siyahlar kalkık
    "dramatik": "curves=all='0/0 0.25/0.17 0.75/0.83 1/1'",                # sert kontrast eğrisi
    "pastel": "curves=all='0/0.10 1/0.95',eq=saturation=0.85",
}
CAPTION_ANIMS = ("pop", "bounce", "kutu", "tek", "daktilo")


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        elif k in out or k in ("name", "description", "slug", "source", "created", "version", "history",
                               "effects", "summary", "reference_sheet"):
            out[k] = v
    return out


def full_style(style: dict) -> dict:
    """Eksik alanları varsayılanla tamamlar ve değerleri güvenli aralıklara sıkıştırır."""
    s = merge(DEFAULT_STYLE, style)
    clamp = lambda v, a, b: max(a, min(b, float(v)))  # noqa: E731
    g = s["grade"]
    g["contrast"], g["saturation"] = clamp(g["contrast"], 0.7, 1.5), clamp(g["saturation"], 0.0, 2.0)
    g["brightness"], g["gamma"] = clamp(g["brightness"], -0.2, 0.2), clamp(g["gamma"], 0.7, 1.4)
    g["warmth"] = clamp(g["warmth"], -0.3, 0.3)
    s["punch"]["scale"] = clamp(s["punch"]["scale"], 1.0, 1.4)
    s["punch"]["bump"] = clamp(s["punch"].get("bump") or 0, 0.0, 0.12)
    if s["punch"].get("mode") not in ("punch", "smooth"):
        s["punch"]["mode"] = "punch"
    if g.get("look") not in LOOKS:
        g["look"] = ""
    f = s["fx"]
    f["cut_flash"], f["grain"] = clamp(f.get("cut_flash") or 0, 0.0, 0.3), int(clamp(f.get("grain") or 0, 0, 30))
    f["letterbox"], f["glow"] = clamp(f.get("letterbox") or 0, 0.0, 0.15), clamp(f.get("glow") or 0, 0.0, 0.5)
    f["vhs"], f["sharpen"] = int(clamp(f.get("vhs") or 0, 0, 8)), clamp(f.get("sharpen") or 0, 0.0, 1.5)
    f["fade_out"] = clamp(f.get("fade_out") or 0, 0.0, 1.5)
    s["outro"]["seconds"] = clamp(s["outro"].get("seconds") or 1.8, 0.8, 4.0)
    s["outro"]["text"] = str(s["outro"].get("text") or "")[:40]
    c = s["captions"]
    c["size"], c["words"] = clamp(c["size"], 36, 140), int(clamp(c["words"], 1, 6))
    c["y"], c["weight"] = clamp(c["y"], 0.2, 0.85), int(clamp(c["weight"], 400, 900))
    if c.get("anim") not in CAPTION_ANIMS:
        c["anim"] = "pop"
    if c["anim"] == "tek":
        c["words"] = 1
    s["title"]["y"] = clamp(s["title"]["y"], 0.08, 0.5)
    s["pacing"]["max_pause"] = clamp(s["pacing"]["max_pause"], 0.15, 3.0)
    if s["progress"]["position"] not in ("top", "bottom"):
        s["progress"]["position"] = "bottom"
    if s["frame"]["mode"] not in ("blur", "crop", "fit"):
        s["frame"]["mode"] = "blur"
    return s


# ----------------------------------------------------------------------------
# Yazı tipi: değişken Montserrat'tan sabit kalınlık (libass değişken fontun varsayılanı olan Thin'i kullanır)
# ----------------------------------------------------------------------------

def font_file(weight: int) -> Path:
    weight = int(round(weight / 100) * 100)
    dest = FONT_CACHE / f"RFStudio-{weight}.ttf"
    if dest.exists():
        return dest
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ImportError as exc:
        raise StageError("fonttools kurulu değil (pip install fonttools)") from exc
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    font = instantiateVariableFont(TTFont(str(FONT_VF)), {"wght": weight})
    for rec in font["name"].names:  # her kalınlık ayrı aile adıyla: ASS'te adla seçilir
        if rec.nameID in (1, 16):
            rec.string = f"{FONT_FAMILY} {weight}"
        elif rec.nameID in (4, 6):
            rec.string = f"{FONT_FAMILY} {weight}".replace(" ", "" if rec.nameID == 6 else " ")
        elif rec.nameID in (2, 17):
            rec.string = "Regular"
    font.save(str(dest))
    return dest


# ----------------------------------------------------------------------------
# Kesim planı
# ----------------------------------------------------------------------------

FILLER = re.compile(r"^(ı+h?|e{2,}h?|a{2,}h?|[ıe]+m+|h+m+|ö{2,}|ı+ğ+)$")


def drop_fillers(words: list[dict]) -> list[dict]:
    """Dolgu seslerini ("ııı", "eee", "hmm") çıkarır; önceki kelime `cut_after` ile işaretlenir ki o aralık kesilsin."""
    out: list[dict] = []
    for w in words:
        core = str(w.get("word", "")).strip(" .,!?;:…\"'-").lower()
        if FILLER.match(core):
            if out:
                out[-1] = {**out[-1], "cut_after": True}
            continue
        out.append(w)
    return out


def plan_pieces(words: list[dict], start: float, end: float, style: dict) -> list[tuple[float, float]]:
    """Konuşmadaki duraksamaları (max_pause'tan uzun) keser; ama keep_gaps saniyeden uzun konuşmasız bölümleri
    KORUR — bunlar bilinçli görüntülerdir (fotoğraf, ara görüntü, müzikli sahne), "boşluk" değil."""
    mp, pad = style["pacing"]["max_pause"], style["pacing"]["pad"]
    keep = float(style["pacing"].get("keep_gaps", 4.0))
    ws = [w for w in words if w["end"] > start and w["start"] < end]
    if not ws:
        return [(start, end)]
    pieces: list[list[float]] = []
    lead = ws[0]["start"] - start
    cur = [start if lead >= keep else max(start, ws[0]["start"] - pad), None]
    for a, b in zip(ws, ws[1:]):
        gap = b["start"] - a["end"]
        if mp < gap < keep or (a.get("cut_after") and 0.2 <= gap < keep):
            cur[1] = min(end, a["end"] + pad)
            pieces.append(cur)
            cur = [max(start, b["start"] - pad), None]
    tail = end - ws[-1]["end"]
    cur[1] = end if tail >= keep else min(end, ws[-1]["end"] + pad + 0.25)
    pieces.append(cur)
    merged: list[list[float]] = []
    for p in pieces:  # çok kısa parçaları komşuyla birleştir
        if merged and (p[0] - merged[-1][1] < 0.05 or p[1] - p[0] < 0.35):
            merged[-1][1] = p[1]
        else:
            merged.append(p)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a > 0.05]


def remap_words(words: list[dict], pieces: list[tuple[float, float]]) -> list[dict]:
    """Kaynak zamanlı kelimeleri kesilmiş çıktının zaman çizelgesine taşır."""
    out, off = [], 0.0
    for a, b in pieces:
        for w in words:
            if w["start"] >= a - 0.02 and w["start"] < b:
                s = off + max(0.0, w["start"] - a)
                e = off + min(b, w["end"]) - a
                out.append({"word": w["word"], "start": s, "end": max(e, s + 0.08)})
        off += b - a
    return out


def select_expr(pieces: list[tuple[float, float]], base: float) -> str:
    return "+".join(f"between(t\\,{a - base:.3f}\\,{b - base:.3f})" for a, b in pieces)


# ----------------------------------------------------------------------------
# ASS altyazı
# ----------------------------------------------------------------------------

def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


_EM: dict[int, float] = {}


def ass_em(weight: int) -> float:
    """libass'ta Fontsize satır yüksekliğidir (usWinAscent+usWinDescent); harf ölçümü için em oranını verir."""
    weight = int(round(weight / 100) * 100)
    if weight not in _EM:
        from fontTools.ttLib import TTFont
        f = TTFont(str(font_file(weight)))
        os2, upm = f["OS/2"], f["head"].unitsPerEm
        tall = (os2.usWinAscent + os2.usWinDescent) or (f["hhea"].ascent - f["hhea"].descent)
        _EM[weight] = upm / tall
    return _EM[weight]


def word_boxes(texts: list[str], weight: int, size: float, W: int) -> list[tuple[float, float]]:
    """Ortalanmış tek satırda her kelimenin (sol, sağ) x konumu — konuşulan kelimenin arkasına kutu çizmek için."""
    font = ImageFont.truetype(str(font_file(weight)), max(8, int(round(size * ass_em(weight)))))
    x0 = W / 2 - font.getlength(" ".join(texts)) / 2
    out = []
    for i, t in enumerate(texts):
        left = x0 + font.getlength(" ".join(texts[:i]) + (" " if i else ""))
        out.append((left, left + font.getlength(t)))
    return out


def caption_groups(words: list[dict], style: dict, W: int, k: float) -> list[list[dict]]:
    c = style["captions"]
    font = ImageFont.truetype(str(font_file(c["weight"])), int(c["size"] * k))
    max_w = W * 0.84
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        text = " ".join(x["word"] for x in cur + [w])
        if c["uppercase"]:
            text = tr_upper(text)
        too_wide = font.getlength(text) > max_w
        gap = cur and w["start"] - cur[-1]["end"] > 0.6
        ends_sentence = cur and cur[-1]["word"].rstrip()[-1:] in ".?!"
        if cur and (len(cur) >= c["words"] or too_wide or gap or ends_sentence):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[dict], title: str | None, style: dict, W: int, H: int, total: float) -> tuple[str, list]:
    k = min(W, H) / 1080
    if W > H:  # yatay çıktı: altyazı alt üçte bire, başlık üste (dikey oranlar yatayda görüntünün ortasına düşer)
        style = merge(style, {"captions": {"y": max(style["captions"]["y"], 0.8)},
                              "title": {"y": min(style["title"]["y"], 0.14)}})
    c, t = style["captions"], style["title"]
    cap_font = f"{FONT_FAMILY} {int(round(c['weight'] / 100) * 100)}"
    title_font = f"{FONT_FAMILY} {int(round(t['weight'] / 100) * 100)}"
    border = 3 if c["box"] else 1
    cap_outline = _ass_color(c["box_color"] if c["box"] else c["outline_color"])
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{cap_font},{int(c['size'] * k)},{_ass_color(c['color'])},&H000000FF,{cap_outline},"
        f"&H96000000,0,0,0,0,100,100,0,0,{border},{c['outline'] * k:.1f},{c['shadow'] * k:.1f},5,40,40,0,1",
        f"Style: Title,{title_font},{int(t['size'] * k)},{_ass_color(t['fg'])},&H000000FF,{_ass_color(t['bg'])},"
        f"&H64000000,0,0,0,0,100,100,0,0,3,{18 * k:.1f},0,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    srt = []
    if t["enabled"] and title:
        txt = tr_upper(title) if t["uppercase"] else title
        dur = min(float(t["seconds"]), total)
        anim = "{\\fad(120,200)\\fscx70\\fscy70\\t(0,160,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(dur)},Title,,0,0,0,,{anim}{{\\pos({W // 2},{int(H * t['y'])})}}"
                     f"{_esc(txt)}")
    o = style.get("outro") or {}
    if o.get("enabled") and o.get("text") and total > 3:   # bitiş kartı: son saniyelerde ortada büyüyerek girer
        txt = tr_upper(o["text"]) if t["uppercase"] else o["text"]
        st = max(0.0, total - float(o["seconds"]))
        anim = "{\\fad(120,0)\\fscx60\\fscy60\\t(0,180,\\fscx108\\fscy108)\\t(180,300,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 2,{_ts(st)},{_ts(total)},Title,,0,0,0,,{anim}{{\\pos({W // 2},{int(H * 0.46)})}}"
                     f"{_esc(txt)}")
    if c["enabled"] and words:
        groups = caption_groups(words, style, W, k)
        hl = _ass_color(c["highlight"])
        base = _ass_color(c["color"])
        kw = _ass_color(c["keyword"]) if c.get("keyword") else ""
        anim_mode = c.get("anim", "pop")
        size = int(c["size"] * k)
        em = size * ass_em(c["weight"])
        y = int(H * c["y"])
        for gi, g in enumerate(groups):
            g_end = g[-1]["end"] + 0.15
            if gi + 1 < len(groups):
                g_end = min(g_end + 0.4, groups[gi + 1][0]["start"])
            srt.append((g[0]["start"], g_end, " ".join(w["word"] for w in g)))
            for wi, w in enumerate(g):
                s = w["start"]
                e = g[wi + 1]["start"] if wi + 1 < len(g) else g_end
                if e - s < 0.02:
                    continue
                parts = []
                texts = [_esc(tr_upper(x["word"]) if c["uppercase"] else x["word"]) for x in g]
                for wj, word in enumerate(texts):
                    active = wj == wi
                    color = hl if active and anim_mode != "kutu" else base
                    if kw and not active and is_emphasis(g[wj]["word"]):
                        color = kw          # sayılar ve vurgu kelimeleri hep renkli kalır
                    tag = f"\\c{color}"
                    if anim_mode == "daktilo":   # henüz söylenmemiş kelimeler görünmez (yer tutar)
                        tag += "\\alpha&HFF&" if wj > wi else "\\alpha&H00&"
                    if anim_mode in ("bounce", "tek"):   # konuşulan kelime zıplayarak gelir
                        tag += "\\fscx118\\fscy118\\t(0,110,\\fscx100\\fscy100)" if active else "\\fscx100\\fscy100"
                    parts.append(f"{{{tag}}}{word}")
                if anim_mode == "kutu":   # konuşulan kelimenin arkasında yuvarlak köşeli renkli kutu
                    x1, x2 = word_boxes(texts, c["weight"], size, W)[wi]
                    r = em * 0.16
                    bx1, bx2 = x1 - em * 0.10, x2 + em * 0.10
                    by1, by2 = y - em * 0.62, y + em * 0.52
                    lines.append(
                        f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{{\\an7\\pos(0,0)\\bord{r:.1f}\\shad0\\1c{hl}\\3c{hl}"
                        f"\\fscx100\\fscy100\\p1}}m {bx1:.0f} {by1:.0f} l {bx2:.0f} {by1:.0f} {bx2:.0f} {by2:.0f} "
                        f"{bx1:.0f} {by2:.0f}{{\\p0}}")
                pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if c["pop"] and wi == 0 \
                    and anim_mode in ("pop", "daktilo") else ""
                lines.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{pop}{{\\pos({W // 2},{y})}}"
                             + " ".join(parts))
    return "\n".join(lines) + "\n", srt


def write_srt(entries: list, dest: Path) -> Path:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    dest.write_text("\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(entries, 1)),
                    encoding="utf-8")
    return dest


# ----------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------

def target_size(src_w: int, src_h: int, aspect: str) -> tuple[int, int]:
    if aspect == "original":
        if src_w >= src_h:
            return 1920, int(round(1920 * src_h / src_w / 2)) * 2
        return int(round(1920 * src_w / src_h / 2)) * 2, 1920
    return 1080, 1920


EMPH_STOP = {"gerçekten", "aslında", "yani", "şimdi", "bunu", "şunu", "onların", "bizim", "sizin"}


def is_emphasis(word: str) -> bool:
    """Vurgu kelimesi: sayı, ünlemli ya da uzun (≥8 harf) kelime."""
    t = str(word); core = t.strip(".,!?;:…\"'").lower()
    if core in EMPH_STOP:
        return False
    return any(ch.isdigit() for ch in t) or t.endswith("!") or len(core) >= 8


def emphasis_times(words: list[dict], min_gap: float = 2.5) -> list[float]:
    """Vurgu anları: sayılar, ünlemli ve uzun (≥8 harf) kelimeler; aralarında en az min_gap sn."""
    out: list[float] = []
    for w in words:
        if is_emphasis(w.get("word", "")) and (not out or w["start"] - out[-1] >= min_gap):
            out.append(float(w["start"]))
    return out


def zoom_plan(pieces_out: list[tuple[float, float]], words: list[dict], style: dict) -> list[tuple[float, float, float]]:
    """Kısa video kurgusunun 'görüntü 2-3 sn'de bir değişsin' kuralı: kesimlerde sırayla zoom (punch), kesim olmayan uzun
    parçalar `interrupt` sn'de bir bölünür, vurgu kelimelerinde 0,45 sn'lik ek yakınlaşma. Dönen: (başla, bitir, zoom)."""
    p = style["punch"]
    if not p.get("enabled"):
        return []
    z, inter, emph = float(p["scale"]), float(p.get("interrupt", 2.8)), float(p.get("emphasis", 1.08))
    base, k = [], 0
    for a, b in pieces_out:
        n = max(1, math.ceil((b - a) / inter - 1e-6)) if inter > 0 else 1
        for j in range(n):
            base.append((a + (b - a) * j / n, a + (b - a) * (j + 1) / n, z if k % 2 else 1.0)); k += 1
    em = [(t, t + 0.45) for t in emphasis_times(words)] if emph > 1.0 else []
    pts = sorted({x for a, b, _ in base for x in (a, b)} | {x for a, b in em for x in (a, b)})
    segs: list[tuple[float, float, float]] = []
    for a, b in zip(pts, pts[1:]):
        if b - a < 1e-3:
            continue
        m = (a + b) / 2
        v = next((zz for x, y, zz in base if x <= m < y), 1.0)
        if any(x <= m < y for x, y in em):
            v = min(1.4, v * emph)
        if segs and abs(segs[-1][2] - v) < 1e-6 and abs(segs[-1][1] - a) < 1e-6:
            segs[-1] = (segs[-1][0], b, v)
        else:
            segs.append((a, b, v))
    return [sg for sg in segs if sg[2] > 1.0001]


def cut_times(pieces_out: list[tuple[float, float]], min_gap: float = 0.0, limit: int = 60) -> list[float]:
    """Çıktı zaman çizelgesindeki kesim anları (ilk parçanın başı hariç), aralarında en az min_gap sn."""
    out: list[float] = []
    for a, _b in pieces_out[1:]:
        if not out or a - out[-1] >= min_gap:
            out.append(float(a))
    return out[:limit]


def zoom_expr(plan: list[tuple[float, float, float]], pieces_out: list[tuple[float, float]], style: dict) -> str:
    """zoompan `z` ifadesi: plan parçaları (ani ya da parça boyunca yavaş yakınlaşma) + kesimlerde kısa zoom darbesi."""
    p = style["punch"]
    if not p.get("enabled"):
        return ""
    terms = []
    for a, b, v in plan:
        t = f"between(it\\,{a:.3f}\\,{b - 0.001:.3f})*{v - 1:.3f}"
        if p.get("mode") == "smooth" and b - a > 0.6:   # CapCut "yavaş yakınlaş": parça boyunca 1.0 → v
            t += f"*(it-{a:.3f})/{b - a:.3f}"
        terms.append(t)
    bump = float(p.get("bump") or 0)
    if bump > 0:
        terms += [f"between(it\\,{c:.3f}\\,{c + 0.2:.3f})*{bump:.3f}*(1-(it-{c:.3f})/0.2)" for c in cut_times(pieces_out)]
    return "min(1.5\\,1+" + "+".join(terms) + ")" if terms else ""


def video_filter(style: dict, W: int, H: int, pieces_out: list[tuple[float, float]], total: float,
                 select: str, fps: int, hdr: bool = False, words: list[dict] | None = None) -> str:
    fr, g = style["frame"]["mode"], style["grade"]
    from .studio import HDR_TO_SDR
    tone = (HDR_TO_SDR + ",") if hdr else ""  # iPhone HDR: soluk/gri görünmesin
    chain = [f"[0:v]{tone}fps={fps},select='{select}',setpts=N/{fps}/TB,setsar=1"]
    if fr == "blur":
        graph = (f"{chain[0]},split[a][b];"
                 f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40,"
                 f"eq=brightness=-0.08:saturation=1.1[bg];"
                 f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2[f0]")
    elif fr == "crop":
        graph = f"{chain[0]},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[f0]"
    else:
        graph = f"{chain[0]},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[f0]"
    post = []
    fx = style.get("fx") or {}
    zexpr = zoom_expr(zoom_plan(pieces_out, words or [], style), pieces_out, style)
    if zexpr:
        post.append(f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
                    f"s={W}x{H}:fps={fps}")
    bright = f"{g['brightness']:.3f}"
    flashes = cut_times(pieces_out, 1.5) if fx.get("cut_flash", 0) > 0 else []
    if flashes:   # kesimde kısa beyaz parlama (0,12 sn'de söner; en sık 1,5 sn'de bir)
        bright = "'" + bright + "+" + "+".join(
            f"between(t\\,{c:.3f}\\,{c + 0.12:.3f})*{fx['cut_flash']:.2f}*(1-(t-{c:.3f})/0.12)" for c in flashes) + "'"
    post.append(f"eq=contrast={g['contrast']:.3f}:saturation={g['saturation']:.3f}:"
                f"brightness={bright}:gamma={g['gamma']:.3f}" + (":eval=frame" if flashes else ""))
    if abs(g["warmth"]) > 0.005:
        w = g["warmth"]
        post.append(f"colorbalance=rm={w:.3f}:bm={-w:.3f}:rh={w / 2:.3f}:bh={-w / 2:.3f}")
    if LOOKS.get(g.get("look") or ""):
        post.append(LOOKS[g["look"]])
    if fx.get("sharpen", 0) > 0:
        post.append(f"unsharp=5:5:{fx['sharpen']:.2f}:5:5:0")
    mid = ""
    if fx.get("glow", 0) > 0:   # parıltı: bulanık kopya "screen" ile üstüne (RGB'de; YUV'de renk kayar)
        graph += (f";[f0]{','.join(post)},format=gbrp,split[ga][gb];[gb]gblur=sigma=22[gc];"
                  f"[ga][gc]blend=all_mode=screen:all_opacity={fx['glow']:.2f},format=yuv420p[fg]")
        post, mid = [], "fg"
    if fx.get("vhs", 0) > 0:
        post.append(f"rgbashift=rh={-int(fx['vhs'])}:bh={int(fx['vhs'])},format=yuv420p")
    if fx.get("grain", 0) > 0:
        post.append(f"noise=alls={int(fx['grain'])}:allf=t")
    if g["vignette"]:
        post.append("vignette=PI/5")
    if fx.get("letterbox", 0) > 0:
        r = fx["letterbox"]
        post.append(f"drawbox=x=0:y=0:w=iw:h=ih*{r:.3f}:color=black:t=fill,"
                    f"drawbox=x=0:y=ih-ih*{r:.3f}:w=iw:h=ih*{r:.3f}:color=black:t=fill")
    post.append("ass=subs.ass:fontsdir=fonts")
    if style["flash"]["enabled"]:
        post.append("fade=in:st=0:d=0.25:color=white")
    if fx.get("fade_out", 0) > 0 and total > 4:
        post.append(f"fade=out:st={total - fx['fade_out']:.3f}:d={fx['fade_out']:.3f}")
    graph += f";[{mid or 'f0'}]{','.join(post)}[f1]"
    if style["progress"]["enabled"]:
        p = style["progress"]
        h = max(4, int(p["height"] * min(W, H) / 1080))
        graph += (f";color=c={p['color']}:s={W}x{h}:r={fps}[bar];"
                  f"[f1][bar]overlay=x='-W+W*t/{max(total, 0.1):.3f}':y={0 if p['position'] == 'top' else f'H-{h}'}:"
                  f"shortest=1,format=yuv420p[v]")
    else:
        graph += ";[f1]format=yuv420p[v]"
    return graph


def render_clip(src: Path, window: tuple[float, float], words: list[dict], title: str | None, style: dict,
                work: Path, dest: Path, cfg: Config, aspect: str = "9:16", music: bool | None = None,
                enhance_voice: bool | str = True) -> dict:
    """Bir pencereyi stile göre düzenleyip dest'e yazar. Dönen: süre, parçalar, srt girdileri."""
    style = full_style(style)
    work.mkdir(parents=True, exist_ok=True)
    from .studio import probe
    pinfo = probe(src)  # döndürme etiketi ve HDR hesaba katılır
    has_audio = pinfo["audio"]
    W, H = target_size(pinfo["width"], pinfo["height"], aspect)
    fps = int(cfg.get_path("output.fps", 30))
    start, end = window
    if style["pacing"].get("fillers"):
        words = drop_fillers(words)
    pieces = plan_pieces(words, start, end, style)
    total = sum(b - a for a, b in pieces)
    out_pieces, off = [], 0.0
    for a, b in pieces:
        out_pieces.append((off, off + b - a))
        off += b - a
    w_out = remap_words(words, pieces)
    ass, srt = build_ass(w_out, title, style, W, H, total)
    (work / "subs.ass").write_text(ass, encoding="utf-8")
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    for wgt in {style["captions"]["weight"], style["title"]["weight"]}:
        f = font_file(wgt)
        shutil.copy(f, fonts / f.name)
    sel = select_expr(pieces, start)
    # Kaynağın yalnızca bu penceresi okunur (uzun videolarda hızlı)
    seek = ["-ss", f"{start:.3f}", "-t", f"{end - start + 0.5:.3f}", "-i", str(src.resolve())]

    # --- ses
    voice = work / "voice.wav"
    if has_audio:
        raw = work / "voice_raw.wav"
        run(["ffmpeg", "-y", "-v", "error", *seek, "-vn", "-af", f"aselect='{sel}',asetpts=N/SR/TB", "-ar", "48000",
             "-ac", "2", raw.name], cwd=work)
        if enhance_voice:  # gürültü/uğultu/yankı azaltma + netlik + seviye dengeleme (audiofx)
            from .audiofx import enhance
            strength = enhance_voice if isinstance(enhance_voice, str) else "orta"
            try:
                enhance(raw, voice, strength, normalize=False, channels=2)
            except StageError as exc:
                L.warning("ses iyileştirilemedi, özgün ses kullanılıyor: %s", exc)
                raw.replace(voice)
        else:
            raw.replace(voice)
    else:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}", "-i",
             "anullsrc=r=48000:cl=stereo", voice.name], cwd=work)
    sfx_info = None
    if style["sfx"].get("enabled"):
        try:
            voice, sfx_info = _add_sfx(voice, style["sfx"], out_pieces, total, work)
        except Exception as exc:  # noqa: BLE001 — efekt bulunamazsa video efektsiz üretilir
            L.warning("geçiş sesi eklenemedi: %s", exc)
    mix_src = voice
    use_music = style["music"]["enabled"] if music is None else music
    music_info = None
    if use_music:
        try:
            music_info = pick_music(cfg, [style["music"].get("mood") or "upbeat", "background"], work, total, set())
        except Exception as exc:  # noqa: BLE001 — müzik bulunamazsa video müziksiz üretilir
            L.warning("müzik bulunamadı: %s", exc)
        if music_info:
            gain = float(style["music"]["gain_db"])
            run(["ffmpeg", "-y", "-v", "error", "-i", voice.name, "-stream_loop", "-1", "-i",
                 str(Path(music_info["path"]).resolve()), "-filter_complex",
                 f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain}dB,"
                 f"afade=t=in:d=0.8,afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5[m];"
                 f"[0:a]asplit[v1][v2];[m][v1]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[d];"
                 f"[v2][d]amix=inputs=2:duration=first:normalize=0[o]",
                 "-map", "[o]", "-t", f"{total:.3f}", "-ar", "48000", "mix_raw.wav"], cwd=work)
            mix_src = work / "mix_raw.wav"
    audio = loudnorm_two_pass(mix_src, work / "mix.wav", cfg)

    # --- görüntü
    graph = video_filter(style, W, H, out_pieces, total, sel, fps, hdr=pinfo.get("hdr", False), words=w_out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(audio.resolve()), "-filter_complex", graph,
         "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", cfg.get_path("output.preset", "medium"),
         "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(dest.resolve())], cwd=work, timeout=None)
    return {"duration": round(total, 2), "pieces": len(pieces), "cut_seconds": round(end - start - total, 1),
            "srt": srt, "size": [W, H], "music": (music_info or {}).get("title"), "sfx": sfx_info}


_SFX_CACHE: dict[str, dict] = {}


def _add_sfx(voice: Path, cfg_sfx: dict, pieces: list, total: float, work: Path) -> tuple[Path, dict | None]:
    """Kütüphaneden (Openverse, CC0/CC BY) kısa bir geçiş sesi bulur ve kesim noktalarına yerleştirir."""
    from . import library
    q = str(cfg_sfx.get("query") or "whoosh")[:60]
    item = _SFX_CACHE.get(q)
    if not item:
        res = [r for r in library.search("sfx", q)["results"] if (r.get("duration") or 9) <= 3.5]
        res.sort(key=lambda r: (not r["license"].startswith(("CC0", "Kamu")), r.get("duration") or 9))
        if not res:
            return voice, None
        item = {**library.fetch(res[0]["id"]), "query": q}
        _SFX_CACHE[q] = item
    gap = float(cfg_sfx.get("min_gap", 2.5))
    times, last = [], -gap
    for a, _b in pieces[1:]:
        if a - last >= gap and a < total - 0.5:
            times.append(max(0.0, a - 0.12))   # efekt kesimden hemen önce başlar
            last = a
    if not times:
        times = [0.05]
    times = times[:40]
    n = len(times)
    gain = float(cfg_sfx.get("gain_db", -9))
    parts = [f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain}dB,asplit={n}" +
             "".join(f"[s{i}]" for i in range(n))]
    parts += [f"[s{i}]adelay={int(t * 1000)}|{int(t * 1000)}[d{i}]" for i, t in enumerate(times)]
    parts.append("[0:a]" + "".join(f"[d{i}]" for i in range(n)) + f"amix=inputs={n + 1}:duration=first:normalize=0[o]")
    out = work / "voice_sfx.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", voice.name, "-i", str((ROOT / item["output"]).resolve()),
         "-filter_complex", ";".join(parts), "-map", "[o]", "-ar", "48000", out.name], cwd=work)
    return out, {"title": item["name"], "credit": item["credit"], "count": n}
