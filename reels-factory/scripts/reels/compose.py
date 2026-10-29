"""HyperFrames kompozisyonu: sahne yerleşimlerini ölçer, HTML/GSAP üretir, render eder.

Metinler gerçek font dosyasıyla (Pillow) ölçülür; böylece her yazı, platform arayüzlerinin
kapattığı alanların dışında ve taşmadan konumlandırılır. Ölçüm burada, tarayıcıda değil yapılır.
"""
from __future__ import annotations

import os
import random
import shutil
import zlib
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import ImageFont

from . import log
from .config import Config, ROOT
from .util import StageError, norm_word, run, tr_upper, words_of

L = log.get("compose")
W, H = 1080, 1920
MOVES = ["push", "panl", "pull", "up", "panr"]
WHOOSHES = ["whoosh-short", "whoosh"]
CAPTION_WS = 0.22  # altyazı kelime aralığı (em) — kalın kontur kelimeleri birbirine yapıştırmasın


# ----------------------------------------------------------------------------
# Metin ölçümü
# ----------------------------------------------------------------------------

class TextFitError(StageError):
    pass


@lru_cache(maxsize=256)
def _font(path: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_axes([weight])
    except (OSError, AttributeError):
        pass
    return f


class Measurer:
    SAFETY = 1.04  # tarayıcı ile Pillow arasındaki küçük ölçüm farkları için pay

    def __init__(self, font_path: Path):
        self.path = str(font_path)
        self._memo: dict[tuple, float] = {}

    def width(self, text: str, size: int, weight: int = 900, ls_em: float = 0.0, ws_em: float = 0.0) -> float:
        key = (text, size, weight, ls_em, ws_em)
        if key not in self._memo:
            f = _font(self.path, size, weight)
            self._memo[key] = f.getlength(text) + ls_em * size * len(text) + ws_em * size * text.count(" ")
        return self._memo[key]

    def balanced(self, words: list[str], n: int, size: int, weight: int, ls: float,
                 ws: float) -> tuple[float, list[list[str]]] | None:
        """Kelimeleri n satıra, en uzun satırı en kısa olacak şekilde böler (virgülde bölmeyi tercih eder)."""
        from itertools import combinations
        if n > len(words):
            return None
        best: tuple[float, list[list[str]]] | None = None
        for cuts in combinations(range(1, len(words)), n - 1):
            idx = (0, *cuts, len(words))
            lines = [words[idx[i]:idx[i + 1]] for i in range(n)]
            widest = max(self.width(" ".join(l), size, weight, ls, ws) for l in lines)
            bonus = sum(0.04 * widest for l in lines[:-1] if l[-1].endswith((",", ";", ":", "—")))
            score = widest - bonus
            if best is None or score < best[0]:
                best = (score, lines)
        if best is None:
            return None
        widest = max(self.width(" ".join(l), size, weight, ls, ws) for l in best[1])
        return widest, best[1]

    def fit(self, words: list[str], max_w: float, sizes: tuple[int, int], max_lines: int,
            weight: int = 900, ls: float = 0.0, step: int = 2, ws: float = 0.0,
            line_penalty: float = 0.1) -> tuple[int, list[list[str]]]:
        """En okunaklı (büyük punto, az satır, dengeli) yerleşimi seçer."""
        hi, lo = sizes
        best: tuple[float, int, list[list[str]]] | None = None
        for size in range(hi, lo - 1, -step):
            for n in range(1, max_lines + 1):
                res = self.balanced(words, n, size, weight, ls, ws)
                if res and res[0] * self.SAFETY <= max_w:
                    score = size * (1 - line_penalty * (n - 1))
                    if best is None or score > best[0]:
                        best = (score, size, res[1])
                    break
        if best is None:
            raise TextFitError(f"metin sığmıyor ({lo}px, {max_lines} satır): {' '.join(words)[:60]}")
        return best[1], best[2]


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------

def rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def fmt_number(v: float, decimals: int = 0) -> str:
    s = f"{abs(v):,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("-" if v < 0 else "") + s


def find_cue(words: list[dict], cue: str | None, voice_local: float, after: float = -1.0) -> float | None:
    if not cue:
        return None
    nc = norm_word(str(cue))
    for w in words:
        nw = norm_word(w["text"])
        t = voice_local + w["start"]
        if t <= after or not nw:
            continue
        if nw == nc or nw.startswith(nc) or (len(nc) > 3 and nc in nw):
            return t
    return None


class SceneBuilder:
    """Bir sahnenin şablon verisini, metin kutularını ve ses efekti olaylarını üretir."""

    def __init__(self, cfg: Config, measurer: Measurer, script: dict):
        self.cfg = cfg
        self.m = measurer
        self.script = script
        sz = cfg.get_path("safe_zone", {})
        self.top = sz.get("top", 200)
        self.rail_top = sz.get("rail_top", 820)
        self.mx = sz.get("margin_x", 72)
        self.rmx = sz.get("rail_margin_x", 124)
        self.content_bottom = sz.get("content_bottom", 1100)
        self.overlap = float(cfg.get_path("render.transition_overlap", 0.4))
        self.colors = cfg.get_path("brand.colors", {})
        self.boxes: list[dict] = []  # güvenli alan denetimi için bütün metin kutuları

    def max_w(self, y_bottom: float) -> float:
        return W - 2 * (self.rmx if y_bottom > self.rail_top else self.mx)

    def block(self, bid: str, text: str, y: float, sizes: tuple[int, int], max_lines: int, weight: int,
              ls: float = 0.0, upper: bool = True, highlight: set[str] | None = None,
              hl_class: str = "hl", mode: str = "blur", t: float = 0.0, stagger: float = 0.06,
              line_gap: float = 1.06, max_bottom: float | None = None) -> dict:
        raw = words_of(text)
        disp = [tr_upper(w) if upper else w for w in raw]
        max_bottom = max_bottom or self.content_bottom
        size, lines = None, None
        for zone_w in (W - 2 * self.mx, W - 2 * self.rmx):
            try:
                size, lines = self.m.fit(disp, zone_w, sizes, max_lines, weight, ls)
            except TextFitError:
                # sığmayan yazı videoyu durdurmasın: önce bir satır daha, sonra biraz daha küçük punto dene
                hi, lo = sizes
                for extra, low in ((1, lo), (1, int(lo * 0.8)), (2, int(lo * 0.7))):
                    try:
                        size, lines = self.m.fit(disp, zone_w, (hi, max(24, low)), max_lines + extra, weight, ls)
                        L.info("%s: yazı sığmadı, %d satır / %dpx ile yerleştirildi", bid, len(lines), size)
                        break
                    except TextFitError:
                        continue
                else:
                    raise
            bottom = y + size * (len(lines) - 1) * line_gap + size
            if bottom <= self.rail_top or zone_w == W - 2 * self.rmx:
                break
        bottom = y + size * (len(lines) - 1) * line_gap + size
        if bottom > max_bottom:
            raise TextFitError(f"{bid}: metin alt sınırı aşıyor ({bottom:.0f} > {max_bottom})")
        hl = {norm_word(h) for h in (highlight or set()) if norm_word(h)}
        out_lines, ids, n = [], [], 0
        for li, line in enumerate(lines):
            ly = round(y + li * size * line_gap)
            wl = []
            for wtxt in line:
                wid = f"{bid}w{n}"
                is_hl = norm_word(raw[n]) in hl or any(h and h in norm_word(raw[n]) for h in hl if len(h) > 3)
                wl.append({"id": wid, "text": wtxt, "hl": hl_class if is_hl else None})
                ids.append(wid)
                n += 1
            lw = self.m.width(" ".join(line), size, weight, ls)
            self.boxes.append({"id": bid, "x0": (W - lw) / 2, "x1": (W + lw) / 2, "y0": ly, "y1": ly + size})
            out_lines.append({"id": f"{bid}l{li}", "y": ly, "words": wl})
        return {"tpl": {"lines": out_lines, "size": size, "weight": weight, "ls": ls},
                "js": {"words": ids, "lines": [l["id"] for l in out_lines], "mode": mode, "t": round(t, 3),
                       "stagger": stagger, "pops": []},
                "bottom": bottom, "size": size, "hl_ids": [w["id"] for l in out_lines for w in l["words"] if w["hl"]]}

    def chip(self, cid: str, text: str, y: float, size: int, t: float, style: str = "chip") -> dict:
        disp = tr_upper(text)
        w = self.m.width(disp, size, 800, 0.08) + 60
        if w > W - 2 * self.mx:
            raise TextFitError(f"{cid}: etiket çok uzun: {text}")
        self.boxes.append({"id": cid, "x0": (W - w) / 2, "x1": (W + w) / 2, "y0": y, "y1": y + size + 31})
        return {"tpl": {"id": cid, "text": disp, "y": round(y), "size": size, "style": style},
                "js": {"id": cid, "t": round(t, 3), "static": False}, "bottom": y + size + 31}

    # ------------------------------------------------------------------
    def build(self, idx: int, sc: dict, row: dict, vmeta: dict, media: dict | None,
              enter: str, exit_kind: str | None, category: dict) -> tuple[dict, list[dict]]:
        sid = sc["id"]
        layout = sc["layout"]
        ons = sc.get("on_screen") or {}
        dur = row["duration"]
        vl = row["voice_local"]
        vdur = vmeta["duration"]
        words = vmeta["words"]
        t0 = 0.05 if enter == "cut" else self.overlap * 0.7
        highlight = set(ons.get("highlight") or []) | set(sc.get("emphasis") or [])
        seed = zlib.crc32(sid.encode()) + idx
        rng = random.Random(seed)
        sfx: list[dict] = []
        abs0 = row["start"]

        chips, blocks = [], []
        stat = None
        compare: list[dict] = []
        items: list[dict] = []
        tpl_extra: dict = {}

        # ---------------- arka plan ----------------
        has_media = media is not None
        graphic_layout = layout in ("stat", "compare", "list", "outro")
        bg = {"type": "graphic", "fit": "cover", "dim": False}
        if has_media:
            explicit = sc["visual"].get("fit") in ("cover", "contain", "card")
            bg = {"type": media["kind"], "src": media["file"], "bgsrc": media["bg"],
                  "fit": media.get("fit", "cover"),
                  "dim": graphic_layout and media["kind"] == "photo" and not explicit,
                  "pos": {"top": "0%", "center": "50%", "bottom": "100%"}.get(sc["visual"].get("align", "center"), "50%")}
            if bg["fit"] == "card" and layout != "photo":
                bg["fit"] = "cover"  # kart kutusu yalnızca photo yerleşiminde tanımlı
            if bg["dim"]:
                bg["fit"] = "cover"
            elif graphic_layout:
                bg["sharp_dark"] = True  # grafik sahnesinde keskin görsel: daha koyu gölge
        if bg["type"] == "graphic":
            move = {"s0": 1.0, "s1": 1.0, "x0": 0, "x1": 0, "y0": 0, "y1": 0}
        elif bg["fit"] in ("card", "contain") or bg.get("dim"):
            move = {"s0": 1.0, "s1": 1.08, "x0": 0, "x1": 0, "y0": 0, "y1": 0}
        else:
            kind = sc["visual"].get("move") or MOVES[idx % len(MOVES)]
            move = {
                "push": {"s0": 1.0, "s1": 1.14, "x0": 0, "x1": 0, "y0": 0, "y1": 0},
                "pull": {"s0": 1.16, "s1": 1.02, "x0": 0, "x1": 0, "y0": 0, "y1": 0},
                "panl": {"s0": 1.18, "s1": 1.18, "x0": 60, "x1": -60, "y0": 0, "y1": 0},
                "panr": {"s0": 1.18, "s1": 1.18, "x0": -60, "x1": 60, "y0": 0, "y1": 0},
                "up": {"s0": 1.16, "s1": 1.16, "x0": 0, "x1": 0, "y0": 70, "y1": -70},
            }.get(kind, {"s0": 1.0, "s1": 1.14, "x0": 0, "x1": 0, "y0": 0, "y1": 0})

        blobs, dots = [], []
        if bg.get("fit") == "contain" and bg["type"] == "photo":
            aspect = media["w"] / max(1, media["h"])
            cw, ch = W, round(W / aspect)
            if ch > H * 0.8:
                ch = round(H * 0.8)
                cw = round(ch * aspect)
            align = sc["visual"].get("align", "center")
            cy = {"top": 260, "bottom": H - ch - 40}.get(align, (H - ch) // 2)
            tpl_extra["contain"] = {"x": (W - cw) // 2, "y": max(0, cy), "w": cw, "h": ch}
            for _ in range(40):
                dots.append({"x": rng.randint(0, W), "y": rng.randint(0, H), "r": rng.choice([2, 2, 3, 4]),
                             "a": round(rng.uniform(0.15, 0.6), 2), "rise": rng.randint(30, 110)})
        if bg["type"] == "graphic":
            palette = [rgba(self.colors["accent"], 0.30), rgba(self.colors["accent2"], 0.30), "rgba(124,92,255,0.26)"]
            for i in range(3):
                r = rng.randint(900, 1300)
                blobs.append({"x": rng.randint(-500, 700), "y": rng.randint(-300, 1500), "r": r,
                              "color": palette[(i + idx) % 3], "dx": rng.randint(-140, 140),
                              "dy": rng.randint(-140, 140)})
            for _ in range(46):
                dots.append({"x": rng.randint(0, W), "y": rng.randint(0, H), "r": rng.choice([2, 3, 3, 4, 5]),
                             "a": round(rng.uniform(0.15, 0.7), 2), "rise": rng.randint(40, 170)})

        shade = {"top": 0.5, "bottom": 0.7, "all": 0.08}
        if bg["type"] == "graphic":
            shade = {"top": 0.25, "bottom": 0.55, "all": 0.0}
        elif bg.get("dim"):
            shade = {"top": 0.55, "bottom": 0.75, "all": 0.35}
        elif bg.get("sharp_dark"):
            shade = {"top": 0.6, "bottom": 0.78, "all": 0.5}
        elif layout == "fact":
            shade = {"top": 0.6, "bottom": 0.8, "all": 0.42}

        # ---------------- yerleşimler ----------------
        if layout == "hook":
            kicker = ons.get("kicker") or category.get("kicker") or ""
            y = 300
            if kicker:
                c = self.chip(f"{sid}-k", kicker, y, 34, 0.15)
                chips.append(c)
                y = c["bottom"] + 44
            b = self.block(f"{sid}-h", ons["headline"], y, (132, 76), 4, 900, -0.01,
                           highlight=highlight, mode="punch", t=0.0)
            for i, wid in enumerate(b["hl_ids"]):
                b["js"]["pops"].append({"id": wid, "t": round(0.35 + i * 0.14, 3)})
            if b["hl_ids"]:
                sfx.append({"name": "pop", "time": abs0 + 0.35, "gain_db": -6})
            blocks.append(b)
            shade = {"top": 0.62, "bottom": 0.72, "all": 0.12} if has_media else shade

        elif layout == "photo":
            y = 280
            if ons.get("label"):
                c = self.chip(f"{sid}-k", ons["label"], y, 34, t0 + 0.05)
                chips.append(c)
                y = c["bottom"] + 36
            if ons.get("headline"):
                b = self.block(f"{sid}-h", ons["headline"], y, (84, 54), 3, 850, -0.005,
                               highlight=highlight, mode="blur", t=t0 + 0.2, stagger=0.06)
                blocks.append(b)
                y = b["bottom"] + 50
                shade["top"] = 0.72
            if has_media and bg["fit"] == "card":
                top = max(y + 10, 420)
                avail = self.content_bottom - top
                cw = W - 2 * self.mx
                ch = min(avail, cw * media["h"] / max(1, media["w"]))
                ch = max(min(avail, 480), ch)
                tpl_extra["card"] = {"x": self.mx, "y": round(top + (avail - ch) / 2), "w": cw, "h": round(ch)}

        elif layout == "stat":
            y = 300
            if ons.get("label"):
                b = self.block(f"{sid}-l", ons["label"], y, (60, 40), 2, 800, 0.02, highlight=highlight,
                               mode="blur", t=t0 + 0.1, stagger=0.05)
                blocks.append(b)
                y = b["bottom"] + 70
            value = float(ons["value"])
            dec = int(ons.get("decimals", 0 if value == int(value) else 1))
            prefix, suffix = ons.get("prefix", ""), ons.get("suffix", "")
            final = prefix + fmt_number(value, dec) + suffix
            nsize, _ = self.m.fit([final + "0"], W - 2 * self.mx, (300, 120), 1, 900, 0.0, step=6)
            num_y = y
            self.boxes.append({"id": f"{sid}-num", "x0": (W - self.m.width(final, nsize)) / 2,
                               "x1": (W + self.m.width(final, nsize)) / 2, "y0": num_y, "y1": num_y + nsize})
            cue_t = (find_cue(words, ons.get("cue"), vl) or find_cue(words, fmt_number(value, dec), vl)
                     or find_cue(words, str(int(value)), vl) or vl + 0.4)
            count = 1.2 if abs(value) >= 10 else 0.8
            st = max(t0 + 0.35, cue_t + 0.15 - count)  # sayaç, sayı söylenirken hedefe ulaşır
            unit_y = num_y + nsize * 0.98 + 34
            u = self.block(f"{sid}-u", ons["unit"], unit_y, (72, 44), 2, 900, 0.04, highlight=set(),
                           mode="rise", t=st + count * 0.5, stagger=0.06)
            blocks.append(u)
            bar_y = u["bottom"] + 46
            stat = {"tpl": {"y": round(num_y), "size": nsize, "start_text": prefix + fmt_number(0, dec) + suffix,
                            "bar": {"x": self.rmx, "y": round(bar_y), "w": W - 2 * self.rmx, "h": 16}},
                    "js": {"t": round(st, 3), "value": value, "decimals": dec, "prefix": prefix,
                           "suffix": suffix, "count_dur": count}}
            if ons.get("note"):
                nb = self.block(f"{sid}-n", ons["note"], bar_y + 56, (44, 32), 2, 700, 0.0, upper=False,
                                highlight=highlight, mode="blur", t=st + count + 0.2, stagger=0.04)
                blocks.append(nb)
            sfx.append({"name": "pop", "time": abs0 + st + count, "gain_db": -3})

        elif layout == "compare":
            y = 300
            if ons.get("title"):
                b = self.block(f"{sid}-t", ons["title"], y, (68, 44), 2, 900, 0.0, highlight=highlight,
                               mode="blur", t=t0 + 0.1, stagger=0.05)
                blocks.append(b)
                y = b["bottom"] + 80
            its = ons["items"]
            vmax = max(float(i["value"]) for i in its) or 1.0
            cues = ons.get("cues") or []
            x, w = self.rmx, W - 2 * self.rmx
            label_size, val_size, bar_h = 48, 56, 60

            def _disp(it):
                v = float(it["value"])
                return it.get("display") or (fmt_number(v, int(it.get("decimals", 0 if v == int(v) else 1))) + it.get("suffix", ""))

            def _fits(size):
                return all(self.m.width(tr_upper(it["label"]), size, 800) + self.m.width(_disp(it), val_size, 900) + 40 <= w
                           for it in its)
            while label_size > 30 and not _fits(label_size):  # uzun etiket: durmak yerine bütün etiketleri birlikte küçült
                label_size -= 2
            last_t = t0
            for i, it in enumerate(its):
                v = float(it["value"])
                dec = int(it.get("decimals", 0 if v == int(v) else 1))
                suffix = it.get("suffix", "")
                display = _disp(it)
                label = tr_upper(it["label"])
                while self.m.width(label, label_size, 800) + self.m.width(display, val_size, 900) + 40 > w and " " in label:
                    label = label.rsplit(" ", 1)[0].rstrip(",:;") + "…"   # en küçük boyutta da sığmazsa son kelimeleri kısalt
                    if label.count(" ") == 0:
                        break
                if self.m.width(label, label_size, 800) + self.m.width(display, val_size, 900) + 40 > w:
                    raise TextFitError(f"{sid}: karşılaştırma etiketi çok uzun: {it['label']}")
                cue_t = (find_cue(words, cues[i] if i < len(cues) else None, vl, last_t - vl - 0.01)
                         or find_cue(words, display.split()[0], vl, last_t + 0.05)
                         or find_cue(words, it["label"].split()[0], vl, last_t + 0.05))
                t = max(t0 + 0.35 + i * 0.5, (cue_t - 0.15) if cue_t else t0 + 0.4 + i * 1.1)
                last_t = t
                row_y = y + i * 210
                compare.append({
                    "tpl": {"id": f"{sid}-c{i}", "x": x, "w": w, "label": label, "label_y": round(row_y),
                            "label_size": label_size, "val_y": round(row_y - 6), "val_size": val_size,
                            "bar_y": round(row_y + 74), "bar_h": bar_h, "fill_w": round(w * v / vmax),
                            "color": self.colors["accent"] if i % 2 == 0 else self.colors["accent2"],
                            "start_text": fmt_number(0, dec) + suffix},
                    "js": {"id": f"{sid}-c{i}", "t": round(t, 3), "value": v, "decimals": dec,
                           "suffix": suffix, "display": display}})
                self.boxes.append({"id": f"{sid}-c{i}", "x0": x, "x1": x + w, "y0": row_y - 6,
                                   "y1": row_y + 74 + bar_h})
                sfx.append({"name": "pop", "time": abs0 + t + 0.9, "gain_db": -6})
            bottom = y + (len(its) - 1) * 210 + 74 + bar_h
            if ons.get("note"):
                nb = self.block(f"{sid}-n", ons["note"], bottom + 50, (84, 50), 1, 900, 0.02,
                                highlight=highlight, hl_class="hl", mode="rise", t=last_t + 1.1, stagger=0.08)
                blocks.append(nb)

        elif layout == "list":
            y = 300
            if ons.get("title"):
                b = self.block(f"{sid}-t", ons["title"], y, (68, 44), 2, 900, 0.0, highlight=highlight,
                               mode="blur", t=t0 + 0.1, stagger=0.05)
                blocks.append(b)
                y = b["bottom"] + 60
            texts = ons["items"]
            cues = ons.get("cues") or []
            x, w = self.rmx, W - 2 * self.rmx
            # Kart yüksekliği: varsayılan 132 px; alan yetmezse 100 px'e kadar küçülür
            gap = 22
            h = int(min(132, (self.content_bottom - y - gap * (len(texts) - 1)) / max(1, len(texts))))
            if h < 100:
                raise TextFitError(f"{sid}: liste alanı taşıyor ({len(texts)} madde)")
            last_t = t0
            for i, txt in enumerate(texts):
                size, _ = self.m.fit([txt], w - 160, (46, 30), 1, 750, 0.0)
                cue_t = find_cue(words, cues[i] if i < len(cues) else txt.split()[0], vl, last_t + 0.05)
                even = vl + (i + 0.2) * vdur / (len(texts) + 0.2)
                t = max(t0 + 0.3 + i * 0.35, (cue_t - 0.2) if cue_t else even)
                last_t = t
                iy = y + i * (h + gap)
                if iy + h > self.content_bottom:
                    raise TextFitError(f"{sid}: liste alanı taşıyor")
                items.append({"tpl": {"id": f"{sid}-i{i}", "x": x, "y": round(iy), "w": w, "h": h,
                                      "text": txt, "size": size},
                              "js": {"id": f"{sid}-i{i}", "t": round(t, 3)}})
                self.boxes.append({"id": f"{sid}-i{i}", "x0": x, "x1": x + w, "y0": iy, "y1": iy + h})
                sfx.append({"name": "pop", "time": abs0 + t + 0.05, "gain_db": -7})

        elif layout == "fact":
            y = 300
            if ons.get("label"):
                c = self.chip(f"{sid}-k", ons["label"], 280, 34, t0 + 0.05)
                chips.append(c)
                y = c["bottom"] + 60
            probe = self.block(f"{sid}-h", ons["headline"], y, (96, 54), 5, 850, -0.005, upper=False,
                               highlight=highlight, mode="blur", t=t0 + 0.15, stagger=0.05)
            avail_top, avail_bot = y, self.content_bottom - 20
            used = probe["bottom"] - y
            yc = max(y, avail_top + (avail_bot - avail_top - used) / 2)
            self.boxes = [bx for bx in self.boxes if bx["id"] != f"{sid}-h"]
            b = self.block(f"{sid}-h", ons["headline"], yc, (96, 54), 5, 850, -0.005, upper=False,
                           highlight=highlight, mode="blur", t=t0 + 0.15, stagger=0.05)
            blocks.append(b)

        elif layout == "outro":
            b = self.block(f"{sid}-h", ons["headline"], 430, (104, 60), 4, 900, -0.01,
                           highlight=highlight, mode="rise", t=t0 + 0.1, stagger=0.07)
            blocks.append(b)
            cta = ons.get("cta") or self.cfg.get_path("brand.cta", "")
            if cta:
                ct = max(t0 + 0.9, vl + vdur * 0.45)
                c = self.chip(f"{sid}-cta", cta, b["bottom"] + 90, 40, ct)
                chips.append(c)
                sfx.append({"name": "pop", "time": abs0 + ct + 0.1, "gain_db": -4})
                handle = self.cfg.get_path("brand.handle", "")
                if handle:
                    h2 = self.chip(f"{sid}-hd", handle, c["bottom"] + 30, 32, ct + 0.25, style="ghost")
                    chips.append(h2)

        # ---------------- geçiş efektleri ----------------
        if idx > 0 and enter != "cut" and sc.get("role") != "payoff":
            sfx.append({"name": WHOOSHES[idx % 2], "time": abs0 - 0.05, "gain_db": -2})

        js = {
            "id": sid, "W": W, "H": H, "dur": dur, "overlap": self.overlap, "enter": enter,
            "exit": exit_kind, "exit_at": row["exit_at"], "t0": t0, "move": move,
            "card": "card" in tpl_extra, "blobs": [{"dx": b["dx"], "dy": b["dy"]} for b in blobs],
            "dots": [{"rise": p["rise"]} for p in dots],
            "chips": [c["js"] for c in chips], "blocks": [b["js"] for b in blocks],
            "stat": stat["js"] if stat else None,
            "compare": [c["js"] for c in compare], "items": [i["js"] for i in items],
        }
        d = {
            "id": sid, "dur": dur, "enter": enter, "bg": bg, "blobs": blobs, "dots": dots,
            "shade_top": shade["top"], "shade_bottom": shade["bottom"], "shade_all": shade["all"],
            "chips": [c["tpl"] for c in chips], "blocks": [b["tpl"] for b in blocks],
            "stat": stat["tpl"] if stat else None, "compare": [c["tpl"] for c in compare],
            "list_items": [i["tpl"] for i in items], "js": js, **tpl_extra,
        }
        return d, sfx


# ----------------------------------------------------------------------------
# Altyazı yerleşimi
# ----------------------------------------------------------------------------

def layout_captions(groups: list[dict], m: Measurer, cfg: Config) -> tuple[list[dict], list[dict], list[dict]]:
    sz = cfg.get_path("safe_zone", {})
    center = (sz.get("caption_top", 1130) + sz.get("caption_bottom", 1330)) / 2
    max_w = W - 2 * sz.get("rail_margin_x", 124)
    hi = int(cfg.get_path("captions.font_size", 78))
    lo = int(cfg.get_path("captions.min_font_size", 52))
    tpl, js, boxes = [], [], []
    for g in groups:
        texts = [w["text"] for w in g["words"]]
        stroke_pad = 0.3 * hi
        size, lines = m.fit(texts, max_w - stroke_pad, (hi, lo), 2, 900, 0.01, ws=CAPTION_WS)
        lh = size * 1.12
        top = center - (len(lines) * lh - (lh - size)) / 2
        n = 0
        out_lines = []
        jw = []
        # konuşulan kelime büyür (pop); uzun kelimede büyüme yandaki boşluğu yutmasın ("415TERAVATSAAT")
        gap = m.width("x x", size, 900, 0.01, CAPTION_WS) - 2 * m.width("x", size, 900, 0.01, CAPTION_WS)
        for li, line in enumerate(lines):
            ly = round(top + li * lh)
            ws = []
            for _ in line:
                w = g["words"][n]
                wid = f"{g['id']}w{n}"
                pop = 1.14 if w["emph"] else 1.08
                if len(line) > 1:
                    ww = max(1.0, m.width(w["text"], size, 900, 0.01, CAPTION_WS))
                    pop = round(max(1.02, min(pop, 1 + 0.7 * gap / ww)), 3)
                ws.append({"id": wid, "text": w["text"], "emph": w["emph"]})
                jw.append({"id": wid, "start": w["start"], "end": w["end"], "emph": w["emph"], "pop": pop})
                n += 1
            out_lines.append({"y": ly, "words": ws})
            lw = m.width(" ".join(line), size, 900, 0.01, CAPTION_WS)
            boxes.append({"id": g["id"], "x0": (W - lw) / 2, "x1": (W + lw) / 2, "y0": ly, "y1": ly + size,
                          "caption": True})
        tpl.append({"id": g["id"], "size": size, "lines": out_lines})
        js.append({"id": g["id"], "start": g["start"], "end": g["end"], "words": jw})
    return tpl, js, boxes


def check_safe_zones(boxes: list[dict], cfg: Config) -> list[str]:
    sz = cfg.get_path("safe_zone", {})
    probs = []
    for b in boxes:
        if b["y0"] < sz.get("top", 200) - 1:
            probs.append(f"{b['id']}: üst güvenli alanın içinde (y={b['y0']:.0f})")
        limit = sz.get("text_bottom", 1330) if b.get("caption") else sz.get("content_bottom", 1100)
        if b["y1"] > limit + 1:
            probs.append(f"{b['id']}: alt sınırı aşıyor (y={b['y1']:.0f} > {limit})")
        margin = sz.get("rail_margin_x", 124) if b["y1"] > sz.get("rail_top", 820) else sz.get("margin_x", 72)
        if b["x0"] < margin - 2 or b["x1"] > W - margin + 2:
            probs.append(f"{b['id']}: yatay güvenli alan dışında ({b['x0']:.0f}-{b['x1']:.0f})")
    return probs


# ----------------------------------------------------------------------------
# Proje üretimi ve render
# ----------------------------------------------------------------------------

def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(ROOT / "assets" / "templates")),
                       undefined=StrictUndefined, autoescape=True, trim_blocks=False, lstrip_blocks=False)


def build_project(job_dir: Path, script: dict, timeline: dict, voice: dict[str, dict],
                  media: dict[str, dict | None], groups: list[dict], category: dict,
                  cfg: Config) -> dict:
    comp = job_dir / "composition"
    if comp.exists():
        shutil.rmtree(comp)
    (comp / "compositions").mkdir(parents=True)
    (comp / "assets" / "media").mkdir(parents=True)
    (comp / "assets" / "fonts").mkdir(parents=True)
    (comp / "assets" / "vendor").mkdir(parents=True)

    font = cfg.path(cfg.get_path("brand.font_file"))
    shutil.copy(font, comp / "assets" / "fonts" / "brand.ttf")
    gsap = ROOT / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap.exists():
        raise StageError("GSAP bulunamadı: reels-factory klasöründe `npm install` çalıştırın")
    shutil.copy(gsap, comp / "assets" / "vendor" / "gsap.min.js")
    for sid, meta in media.items():
        if not meta:
            continue
        for key in ("file", "bg"):
            src = job_dir / "visuals" / meta[key]
            if src.exists():
                shutil.copy(src, comp / "assets" / "media" / meta[key])

    m = Measurer(font)
    env = _env()
    brand = cfg.get_path("brand")
    builder = SceneBuilder(cfg, m, script)
    rows = {r["id"]: r for r in timeline["scenes"]}
    scenes = script["scenes"]
    sfx: list[dict] = []
    host_rows = []
    for i, sc in enumerate(scenes):
        enter = sc.get("transition", "cut") if i > 0 else "cut"
        exit_kind = scenes[i + 1].get("transition", "cut") if i + 1 < len(scenes) else None
        d, ev = builder.build(i, sc, rows[sc["id"]], voice[sc["id"]], media.get(sc["id"]), enter,
                              exit_kind, category)
        sfx += ev
        html = env.get_template("scene.html.j2").render(d=d, brand=brand, W=W, H=H)
        (comp / "compositions" / f"{sc['id']}.html").write_text(html, encoding="utf-8")
        host_rows.append({"id": sc["id"], "start": rows[sc["id"]]["start"], "duration": rows[sc["id"]]["duration"]})
        if sc.get("role") == "payoff" and not any(e["name"] == "riser" for e in sfx) and i > 0:
            t = rows[sc["id"]]["start"]
            sfx.append({"name": "riser", "time": t, "align": "end", "trim_tail": 2.2, "gain_db": -4})
            sfx.append({"name": "impact-bass-1", "time": t, "gain_db": -3})

    cap_tpl, cap_js, cap_boxes = layout_captions(groups, m, cfg) if groups else ([], [], [])
    sz = cfg.get_path("safe_zone", {})
    if groups:
        html = env.get_template("captions.html.j2").render(
            groups=cap_tpl, groups_js=cap_js, brand=brand, W=W, H=H,
            center_y=(sz.get("caption_top", 1130) + sz.get("caption_bottom", 1330)) / 2,
            stroke=round(0.15 * int(cfg.get_path("captions.font_size", 78))), word_spacing=CAPTION_WS)
        (comp / "compositions" / "captions.html").write_text(html, encoding="utf-8")
    html = env.get_template("overlay.html.j2").render(
        brand=brand, W=W, H=H, total=timeline["total"], margin=sz.get("margin_x", 72), bar_y=176,
        handle=cfg.get_path("brand.handle", ""))
    (comp / "compositions" / "overlay.html").write_text(html, encoding="utf-8")
    html = env.get_template("index.html.j2").render(
        title=script.get("title", ""), scenes=host_rows, total=timeline["total"], brand=brand, W=W, H=H,
        fps=cfg.get_path("output.fps", 30), captions=bool(groups))
    (comp / "index.html").write_text(html, encoding="utf-8")

    zone_problems = check_safe_zones(builder.boxes + cap_boxes, cfg)
    sfx.sort(key=lambda e: e["time"])
    return {"dir": str(comp), "sfx": sfx, "safe_zone_problems": zone_problems,
            "text_boxes": len(builder.boxes) + len(cap_boxes)}


def hyperframes_bin() -> Path:
    name = "hyperframes.cmd" if os.name == "nt" else "hyperframes"  # Windows'ta npm .cmd sarmalayıcı üretir
    b = ROOT / "node_modules" / ".bin" / name
    if not b.exists():
        raise StageError("HyperFrames bulunamadı: reels-factory klasöründe `npm install` çalıştırın")
    return b


def _env_vars() -> dict:
    env = dict(os.environ)
    env.setdefault("DO_NOT_TRACK", "1")
    return env


def lint(comp_dir: Path) -> dict:
    import json
    proc = run([hyperframes_bin(), "lint", ".", "--json"], cwd=comp_dir, check=False, timeout=300, env=_env_vars())
    try:
        start = proc.stdout.index("{")
        return json.loads(proc.stdout[start:])
    except (ValueError, json.JSONDecodeError):
        return {"errorCount": 0 if proc.returncode == 0 else 1, "raw": (proc.stdout + proc.stderr)[-2000:]}


def render(comp_dir: Path, out: Path, cfg: Config, workers: int | None = None, quality: str | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [hyperframes_bin(), "render", "-o", str(out), "-q", quality or cfg.get_path("render.quality", "standard"),
           "-w", str(workers or cfg.get_path("render.workers", 4)), "-f", str(cfg.get_path("output.fps", 30)),
           "--crf", str(cfg.get_path("output.crf", 18)), "--quiet"]
    run(cmd, cwd=comp_dir, timeout=cfg.get_path("render.timeout_sec", 1800), env=_env_vars())
    if not out.exists() or out.stat().st_size < 10_000:
        raise StageError("render çıktı üretmedi")
    return out
