"""Stüdyo render motoru: kullanıcının videosunu bir stile göre düzenler (yalnızca ffmpeg + libass).

Bir klip = kaynağın bir penceresi. Pencere içinde konuşma boşlukları kesilir (jump cut), görüntü 9:16'ya
(veya kaynağın oranına) çerçevelenir, renk düzenlenir, kesimlerde zoom "punch" uygulanır, kelime vurgulu
altyazılar + açılış başlığı (ASS) ve ilerleme çubuğu eklenir; ses isteğe bağlı müzikle kısılarak
(sidechain) karıştırılır ve -14 LUFS'a normalize edilir.
"""
from __future__ import annotations

import copy
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
    "pacing": {"max_pause": 0.45, "pad": 0.10},
    "frame": {"mode": "blur"},
    "grade": {"contrast": 1.06, "saturation": 1.15, "brightness": 0.0, "gamma": 1.0, "warmth": 0.0,
              "vignette": True},
    "punch": {"enabled": True, "scale": 1.12},
    "captions": {"enabled": True, "weight": 900, "size": 78, "uppercase": True, "color": "#FFFFFF",
                 "highlight": "#FFD23F", "outline": 7, "outline_color": "#000000", "shadow": 2, "box": False,
                 "box_color": "#000000", "words": 3, "y": 0.64, "pop": True},
    "title": {"enabled": True, "seconds": 3.0, "size": 70, "weight": 900, "uppercase": True,
              "fg": "#111111", "bg": "#FFD23F", "y": 0.17},
    "progress": {"enabled": True, "color": "#FFD23F", "height": 10, "position": "bottom"},
    "flash": {"enabled": True},
    "music": {"enabled": False, "gain_db": -18, "mood": "upbeat"},
}


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
    c = s["captions"]
    c["size"], c["words"] = clamp(c["size"], 36, 140), int(clamp(c["words"], 1, 6))
    c["y"], c["weight"] = clamp(c["y"], 0.2, 0.85), int(clamp(c["weight"], 400, 900))
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

def plan_pieces(words: list[dict], start: float, end: float, style: dict) -> list[tuple[float, float]]:
    """Pencere içindeki konuşmayı tutar, max_pause'tan uzun boşlukları keser."""
    mp, pad = style["pacing"]["max_pause"], style["pacing"]["pad"]
    ws = [w for w in words if w["end"] > start and w["start"] < end]
    if not ws:
        return [(start, end)]
    pieces: list[list[float]] = []
    cur = [max(start, ws[0]["start"] - pad), None]
    for a, b in zip(ws, ws[1:]):
        if b["start"] - a["end"] > mp:
            cur[1] = min(end, a["end"] + pad)
            pieces.append(cur)
            cur = [max(start, b["start"] - pad), None]
    cur[1] = min(end, ws[-1]["end"] + pad + 0.25)
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
    if c["enabled"] and words:
        groups = caption_groups(words, style, W, k)
        hl = _ass_color(c["highlight"])
        base = _ass_color(c["color"])
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
                for wj, x in enumerate(g):
                    word = tr_upper(x["word"]) if c["uppercase"] else x["word"]
                    color = hl if wj == wi else base
                    parts.append(f"{{\\c{color}}}{_esc(word)}")
                pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if c["pop"] and wi == 0 else ""
                lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{pop}{{\\pos({W // 2},{y})}}"
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


def video_filter(style: dict, W: int, H: int, pieces_out: list[tuple[float, float]], total: float,
                 select: str, fps: int) -> str:
    fr, g = style["frame"]["mode"], style["grade"]
    chain = [f"[0:v]fps={fps},select='{select}',setpts=N/{fps}/TB,setsar=1"]
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
    if style["punch"]["enabled"] and len(pieces_out) > 1:
        z = style["punch"]["scale"]
        zoomed = "+".join(f"between(it\\,{a:.3f}\\,{b - 0.001:.3f})" for i, (a, b) in enumerate(pieces_out) if i % 2)
        post.append(f"zoompan=z='if({zoomed}\\,{z}\\,1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
                    f"s={W}x{H}:fps={fps}")
    post.append(f"eq=contrast={g['contrast']:.3f}:saturation={g['saturation']:.3f}:"
                f"brightness={g['brightness']:.3f}:gamma={g['gamma']:.3f}")
    if abs(g["warmth"]) > 0.005:
        w = g["warmth"]
        post.append(f"colorbalance=rm={w:.3f}:bm={-w:.3f}:rh={w / 2:.3f}:bh={-w / 2:.3f}")
    if g["vignette"]:
        post.append("vignette=PI/5")
    post.append("ass=subs.ass:fontsdir=fonts")
    if style["flash"]["enabled"]:
        post.append("fade=in:st=0:d=0.25:color=white")
    graph += f";[f0]{','.join(post)}[f1]"
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
                enhance_voice: bool = True) -> dict:
    """Bir pencereyi stile göre düzenleyip dest'e yazar. Dönen: süre, parçalar, srt girdileri."""
    style = full_style(style)
    work.mkdir(parents=True, exist_ok=True)
    info = ffprobe(src)
    vs = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if not vs:
        raise StageError("videoda görüntü akışı yok")
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    W, H = target_size(int(vs["width"]), int(vs["height"]), aspect)
    fps = int(cfg.get_path("output.fps", 30))
    start, end = window
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
        from .voice import ENHANCE_CORE
        af = f"aselect='{sel}',asetpts=N/SR/TB" + (f",{ENHANCE_CORE}" if enhance_voice else "")
        run(["ffmpeg", "-y", "-v", "error", *seek, "-vn", "-af", af, "-ar", "48000", "-ac", "2", voice.name], cwd=work)
    else:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{total:.3f}", "-i",
             "anullsrc=r=48000:cl=stereo", voice.name], cwd=work)
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
    graph = video_filter(style, W, H, out_pieces, total, sel, fps)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(audio.resolve()), "-filter_complex", graph,
         "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", cfg.get_path("output.preset", "medium"),
         "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(dest.resolve())], cwd=work, timeout=None)
    return {"duration": round(total, 2), "pieces": len(pieces), "cut_seconds": round(end - start - total, 1),
            "srt": srt, "size": [W, H], "music": (music_info or {}).get("title")}
