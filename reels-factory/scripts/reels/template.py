"""Birebir şablon ("şunun aynısı"): referans videonun kurgusunu çıkarır, kullanıcının medyasına aynen uygular.

CapCut'taki "şablonu kullan" gibi çalışır. Referanstan ölçülenler:
- kesimler: her çekimin başlangıç/bitişi (kare farkı + renk histogramı; yumuşak geçişler dahil)
- geçişler: sert kesim / yumuşak geçiş (dissolve) / beyaz flaş / karartma
- çekim başına kamera hareketi: yakınlaşma, uzaklaşma, kaydırma (ölçek araması + faz korelasyonu)
- renk: parlaklık, doygunluk, kontrast, sıcaklık · müzik temposu (BPM) ve vuruşlar
- ekrandaki yazılar (Claude görsel analizi): metin, konum, boyut, renk, kutu, büyük harf, animasyon; müzik havası
Uygulama: çekim sayısı ve süreleri aynen korunur, medya sırayla çekimlere yerleşir (azsa başa döner), aynı
hareket/geçiş/renk/yazılar uygulanır, lisanslı bir müzik referansın temposuna (BPM) eşitlenir. Referansın kendi
müziği ve görüntüleri kullanılmaz (telif); yalnızca kurgu yapısı örnek alınır.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from . import log
from .config import ROOT, Config, load_config
from .util import StageError, run, write_json

L = log.get("template")
W, H, FPS = 1080, 1920, 30
XFADE = {"cut": None, "fade": "fade", "flash": "fadewhite", "black": "fadeblack", "zoom": "zoomin",
         "slide": "slideleft", "wipe": "wipeleft", "circle": "circleopen", "blur": "hblur"}


# ----------------------------------------------------------------------------
# Ölçüm
# ----------------------------------------------------------------------------

def _gray_frames(src: Path, fps: int, w: int = 72, h: int = 128, limit: float = 180) -> np.ndarray:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-t", f"{limit}", "-i", str(src), "-vf",
                           f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=disable,format=gray",
                           "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(proc.stdout, dtype=np.uint8)
    return a[: len(a) // (w * h) * (w * h)].reshape(-1, h, w).astype(np.float32) / 255.0


def _hist(f: np.ndarray) -> np.ndarray:
    h, _ = np.histogram(f, bins=16, range=(0, 1))
    return h / max(1, h.sum())


def detect_shots(src: Path, duration: float) -> tuple[list[dict], list[dict]]:
    """Çekimler [{start, end}] ve kesim noktalarındaki geçişler [{t, type, dur}]."""
    fps = 30 if duration <= 120 else 15
    fr = _gray_frames(src, fps)
    n = len(fr)
    if n < 3:
        return [{"start": 0.0, "end": duration}], []
    diff = np.concatenate([[0], np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))])
    hists = np.array([_hist(f) for f in fr])
    hd = np.concatenate([[0], 0.5 * np.abs(hists[1:] - hists[:-1]).sum(axis=1)])
    lum = fr.mean(axis=(1, 2))
    med = float(np.median(diff[1:])) + 1e-4
    cuts: list[dict] = []
    for i in range(1, n - 1):
        hard = (diff[i] > max(0.09, 4 * med) and hd[i] > 0.18) or hd[i] > 0.42
        if hard and diff[i] >= diff[i - 1] and diff[i] >= diff[i + 1]:
            cuts.append({"i": i, "type": "cut"})
    # yumuşak geçiş (dissolve) ve karartma/flaş: tek karede sıçrama yok ama birkaç karede tamamen değişiyor
    k = max(3, fps // 5)
    for i in range(k, n - k):
        if any(abs(i - c["i"]) < fps * 0.5 for c in cuts):
            continue
        far = 0.5 * np.abs(hists[i + k] - hists[i - k]).sum()
        if far > 0.45 and diff[i - k:i + k].max() < max(0.09, 4 * med) and diff[i - k:i + k].mean() > 2 * med:
            cuts.append({"i": i, "type": "fade"})
    cuts.sort(key=lambda c: c["i"])
    for c in cuts:   # geçiş türü: karenin parlaklığı çok düştüyse karartma, çok arttıysa flaş
        i = c["i"]
        if c["type"] == "cut":
            win = diff[max(1, i - k):min(n, i + k + 1)]
            if (win > max(2.5 * med, 0.12 * diff[i])).sum() >= 5:   # değişim tek kareye değil birçok kareye yayılmış
                c["type"] = "fade"
        win = lum[max(0, i - k):min(n, i + k)]
        before, after = lum[max(0, i - 2 * k)], lum[min(n - 1, i + 2 * k)]
        if win.min() < 0.05 and before > 0.12 and after > 0.12:
            c["type"] = "black"
        elif win.max() > 0.93 and before < 0.8 and after < 0.8:
            c["type"] = "flash"
        c["t"] = round(i / fps, 3)
        c["dur"] = 0.0 if c["type"] == "cut" else round(min(0.5, 2 * k / fps), 2)
    # çok kısa çekimleri birleştir (en az 0.2 sn)
    merged, last = [], 0.0
    for c in cuts:
        if c["t"] - last >= 0.2 and duration - c["t"] >= 0.2:
            merged.append({"t": c["t"], "type": c["type"], "dur": c["dur"]})
            last = c["t"]
    bounds = [0.0] + [c["t"] for c in merged] + [round(duration, 3)]
    shots = [{"start": bounds[i], "end": bounds[i + 1]} for i in range(len(bounds) - 1)]
    return shots, merged


def _frame(src: Path, t: float, w: int = 180, h: int = 320) -> np.ndarray:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(src), "-frames:v", "1", "-vf",
                           f"scale={w}:{h}:force_original_aspect_ratio=disable,format=gray", "-f", "rawvideo", "-"],
                          capture_output=True)
    a = np.frombuffer(proc.stdout, dtype=np.uint8)
    return a[: w * h].reshape(h, w).astype(np.float32) / 255.0 if len(a) >= w * h else np.zeros((h, w), np.float32)


def _phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    if c.max() < 6 * c.mean() + 1e-9:     # belirgin tepe yok (gürültü/desen): kaydırma yok say
        return 0.0, 0.0
    y, x = np.unravel_index(np.argmax(c), c.shape)
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return -x / a.shape[1], -y / a.shape[0]


def shot_motion(src: Path, shot: dict) -> dict:
    """Çekimdeki kamera hareketi: ölçek (yakınlaşma/uzaklaşma) ve kaydırma, çekim boyunca toplam değer."""
    d = shot["end"] - shot["start"]
    if d < 0.6:
        return {"type": "static", "zoom": 1.0, "dx": 0.0, "dy": 0.0}
    t0, t1 = shot["start"] + 0.15 * d, shot["end"] - 0.15 * d
    a, b = _frame(src, t0), _frame(src, t1)
    h, w = a.shape
    best = (1e9, 1.0)
    errs: dict[float, float] = {}
    pil = Image.fromarray((a * 255).astype(np.uint8))
    for s in np.linspace(0.86, 1.18, 33):
        big = np.asarray(pil.resize((int(w * s), int(h * s)), Image.BILINEAR), dtype=np.float32) / 255.0
        y0, x0 = (big.shape[0] - h) // 2, (big.shape[1] - w) // 2
        if s >= 1:
            cand = big[y0:y0 + h, x0:x0 + w]
            ref = b
        else:   # uzaklaşma: b'nin ortası a'nın küçültülmüş hâliyle karşılaştırılır
            hh, ww = big.shape
            yy, xx = (h - hh) // 2, (w - ww) // 2
            cand, ref = big, b[yy:yy + hh, xx:xx + ww]
        m = 0.1
        cy, cx = int(cand.shape[0] * m), int(cand.shape[1] * m)
        err = float(np.mean((cand[cy:-cy, cx:-cx] - ref[cy:-cy, cx:-cx]) ** 2))
        errs[round(float(s), 3)] = err
        if err < best[0]:
            best = (err, float(s))
    z = best[1]
    e1 = errs.get(1.0, min(errs.values(), key=lambda v: v))
    if e1 <= 0 or best[0] > 0.8 * e1:       # ölçek değişimi hatayı en az %20 azaltmıyorsa yakınlaşma yok
        z = 1.0
    if float(np.std(a)) < 0.03 or float(np.mean((a - b) ** 2)) > 0.08:   # düz renk ya da tamamen değişen içerik
        return {"type": "static", "zoom": 1.0, "dx": 0.0, "dy": 0.0}
    dx, dy = _phase_shift(a, b)
    span = max(0.1, t1 - t0)
    z_total = 1 + (z - 1) * d / span                       # çekimin tamamına göre
    dx_t, dy_t = dx * d / span, dy * d / span
    kind = "zoom_in" if z_total > 1.03 else "zoom_out" if z_total < 0.97 else (
        "pan" if abs(dx_t) > 0.04 or abs(dy_t) > 0.04 else "static")
    return {"type": kind, "zoom": round(z_total, 3), "dx": round(float(np.clip(dx_t, -0.3, 0.3)), 3),
            "dy": round(float(np.clip(dy_t, -0.3, 0.3)), 3)}


def tempo(wav: Path) -> dict:
    """Müzik temposu (BPM) ve vuruş zamanları: spektral akı + otokorelasyon (numpy)."""
    from .util import load_audio
    sr = 22050
    a = load_audio(wav, sr, 1)
    if len(a) < sr * 3:
        return {"bpm": 0, "beats": []}
    hop, nfft = 512, 2048
    n = 1 + (len(a) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(a[idx] * np.hanning(nfft), axis=1))
    spec = np.log1p(spec)
    flux = np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fr = sr / hop
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    lo, hi = int(fr * 60 / 180), int(fr * 60 / 70)
    lag = lo + int(np.argmax(ac[lo:hi]))
    if 1 <= lag < len(ac) - 1:   # parabolik ara değer: kare (23 ms) altı hassasiyet
        y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
        den = y0 - 2 * y1 + y2
        flag = lag + (0.5 * (y0 - y2) / den if den else 0.0)
    else:
        flag = float(lag)
    bpm = 60 * fr / flag
    phase = max(range(lag), key=lambda p: flux[p::lag].sum())
    beats = [round((p + 1) / fr, 3) for p in range(phase, len(flux), lag)]
    return {"bpm": round(float(bpm), 1), "beats": beats}


def _color(frames: list[Path]) -> dict:
    from .studio import color_metrics
    return color_metrics(frames)


TEXT_PROMPT = """Bu kareler bir kısa dikey videonun (Reels/TikTok) her çekiminden birer tanedir (etiket: çekim no, saniye).
Videonun kurgusunu birebir kopyalamak için ekrandaki YAZILARI ve görünüşünü çıkar (konuşma altyazısı dahil).
Her yazı için: "shot" (çekim no, 1'den), "text" (aynen, Türkçe karakterlerle), "y" (dikey konum 0=üst..1=alt; yazının
ortası), "x" (0..1, genelde 0.5), "size" (yazı yüksekliği / kare yüksekliği; ör. 0.035), "color" (#RRGGBB),
"outline" (true/false), "box" (kutu rengi #RRGGBB ya da null), "upper" (hepsi büyük harf mi), "weight" (400-900),
"anim" (none|fade|pop|slide|typewriter), "role" (title|caption|label|cta).
Ayrıca: "captions_word_by_word" (konuşma altyazısı kelime kelime mi beliriyor), "music_query" (benzer müziği bulmak
için 2-4 İngilizce kelime: tür + hava), "mood" (Türkçe 2-3 kelime), "summary" (kurgunun bir cümlelik tarifi),
"shot_types" (her çekim için kısa tarif listesi: ör. "yakın plan yüz", "manzara").
Yalnızca JSON: {"texts": [...], "captions_word_by_word": false, "music_query": "...", "mood": "...", "summary": "...",
"shot_types": [...]}"""


def analyze(src: Path, work: Path, cfg: Config | None = None, ai: bool = True) -> dict:
    """Referans videodan birebir şablon çıkarır → work/template.json."""
    from .studio import ask_ai, ai_mode, grab, probe, sample_frames, sheet, transcribe
    cfg = cfg or load_config()
    src, work = Path(src).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    dur = min(float(info["duration"]), 180.0)
    shots, trans = detect_shots(src, dur)
    for sh in shots:
        sh.update(dur=round(sh["end"] - sh["start"], 3), motion=shot_motion(src, sh))
    frames = sample_frames(src, work / "frames", dur, fps=1.0)
    tpl = {"source": str(src), "duration": round(dur, 3), "size": [info.get("width"), info.get("height")],
           "shots": shots, "transitions": trans, "color": _color(frames[:60]) if frames else {}}
    if info.get("audio"):
        wav = work / "ref_audio.wav"
        run(["ffmpeg", "-y", "-v", "error", "-t", f"{dur}", "-i", src, "-vn", "-ac", "1", "-ar", "22050", wav])
        tpl["music"] = tempo(wav)
        words = transcribe(src, work, cfg, limit=dur)
        tpl["speech"] = {"words": len(words), "coverage": round(sum(w["end"] - w["start"] for w in words) / max(dur, 1), 2)}
    # ekrandaki yazılar: her çekimden bir kare → Claude
    keyshots = shots if len(shots) <= 24 else [shots[int(i * len(shots) / 24)] for i in range(24)]
    tiles = []
    for i, sh in enumerate(keyshots):
        no = shots.index(sh) + 1
        t = sh["start"] + min(sh["dur"] * 0.6, max(0.05, sh["dur"] - 0.1))
        f = grab(src, t, work / f"shot{no:02d}.jpg", 640)
        tiles.append((f, f"{no} · {sh['start']:.1f}s"))
    if tiles:
        tpl["sheet"] = str(sheet(tiles, work / "template_sheet.jpg", cols=6, tile_w=200).relative_to(ROOT))
    if ai and tiles and ai_mode(cfg) != "none":
        res = ask_ai(cfg, TEXT_PROMPT, [t[0] for t in tiles], work / "template_ai.json", timeout=600)
        if isinstance(res, dict):
            tpl.update(texts=[x for x in res.get("texts") or [] if isinstance(x, dict) and x.get("text")],
                       music_query=res.get("music_query"), mood=res.get("mood"), summary=res.get("summary"),
                       shot_types=res.get("shot_types"), captions_word_by_word=res.get("captions_word_by_word"))
            tpl["analysis_by"] = "claude"
    tpl.setdefault("analysis_by", "ölçüm")
    write_json(work / "template.json", tpl)
    L.info("Şablon: %d çekim, %d geçiş (%s), %d yazı, BPM %s", len(shots), len(trans),
           ", ".join(sorted({t["type"] for t in trans})) or "-", len(tpl.get("texts") or []),
           (tpl.get("music") or {}).get("bpm"))
    return tpl


def describe(tpl: dict) -> str:
    sh = tpl["shots"]
    avg = sum(s["dur"] for s in sh) / max(1, len(sh))
    kinds = {}
    for t in tpl.get("transitions", []):
        kinds[t["type"]] = kinds.get(t["type"], 0) + 1
    mot = {}
    for s in sh:
        mot[s["motion"]["type"]] = mot.get(s["motion"]["type"], 0) + 1
    tr = {"cut": "sert kesim", "fade": "yumuşak geçiş", "flash": "beyaz flaş", "black": "karartma"}
    mt = {"zoom_in": "yakınlaşma", "zoom_out": "uzaklaşma", "pan": "kaydırma", "static": "sabit"}
    parts = [f"{len(sh)} çekim, ortalama {avg:.2f} sn, toplam {tpl['duration']:.1f} sn",
             "geçişler: " + ", ".join(f"{v} {tr.get(k, k)}" for k, v in kinds.items()) if kinds else "geçiş yok",
             "hareket: " + ", ".join(f"{v} {mt.get(k, k)}" for k, v in mot.items())]
    if (tpl.get("music") or {}).get("bpm"):
        parts.append(f"müzik ≈ {tpl['music']['bpm']:.0f} BPM")
    if tpl.get("texts"):
        parts.append(f"{len(tpl['texts'])} ekran yazısı")
    return " · ".join(parts)


# ----------------------------------------------------------------------------
# Uygulama
# ----------------------------------------------------------------------------

def _shot_clip(media: Path, kind: str, dur: float, motion: dict, offset: float, dest: Path) -> None:
    """Tek çekim: 1080x1920, tam süre; fotoğrafa referansın kamera hareketi, videoya o hareket + kırpma."""
    frames = max(1, int(round(dur * FPS)))
    z1 = float(np.clip(motion.get("zoom", 1.0), 0.8, 1.35))
    dx, dy = float(motion.get("dx", 0)), float(motion.get("dy", 0))
    base = 1.0 if z1 >= 1 else 1 / z1           # uzaklaşma: büyükten başla
    end = base * z1
    if motion.get("type") in ("static", None) and kind == "image":
        base, end = 1.0, 1.04                    # fotoğraf hiç durmasın: çok hafif yakınlaşma
    zexpr = f"{base:.4f}+({end - base:.4f})*on/{frames}"
    # kaydırma: merkezden dx/dy kadar (kare genişliği oranında) yavaşça kay
    xexpr = f"iw/2-(iw/zoom/2)+({dx:.4f})*iw*(on/{frames}-0.5)*0.5"
    yexpr = f"ih/2-(ih/zoom/2)+({dy:.4f})*ih*(on/{frames}-0.5)*0.5"
    cover = f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2}"
    zp = f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d={1 if kind == 'video' else frames}:s={W}x{H}:fps={FPS}"
    if kind == "image":
        from .studio import normalize_image
        src = normalize_image(media) if media.suffix.lower() not in (".jpg", ".jpeg") else media
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{dur:.3f}", "-i", src, "-vf",
             f"{cover},{zp},setsar=1,format=yuv420p", "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "17", "-r", str(FPS), "-an", dest])
    else:
        zv = (f"zoompan=z='{base:.4f}+({end - base:.4f})*on/{frames}':x='{xexpr}':y='{yexpr}':d=1:s={W}x{H}:fps={FPS}"
              if motion.get("type") not in ("static", None) else f"scale={W}:{H}")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{offset:.3f}", "-i", media, "-t", f"{dur:.3f}", "-vf",
             f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{zv},setsar=1,format=yuv420p",
             "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-an", dest])


def _ass(texts: list[dict], shots: list[dict], work: Path) -> Path | None:
    from .studio_render import FONT_FAMILY, _ass_color, font_file
    from .util import tr_upper
    if not texts:
        return None
    # aynı yazı ardışık çekimlerde sürüyorsa tek olay
    events: list[dict] = []
    for t in sorted(texts, key=lambda x: int(x.get("shot", 1))):
        i = max(1, min(len(shots), int(t.get("shot", 1)))) - 1
        a, b = shots[i]["start"], shots[i]["end"]
        if events and events[-1]["text"] == t["text"] and abs(events[-1]["end"] - a) < 0.05:
            events[-1]["end"] = b
            continue
        events.append({**t, "start": a, "end": b})
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    weights = sorted({int(round(int(e.get("weight") or 800) / 100) * 100) for e in events})
    for wgt in weights:
        f = font_file(wgt)
        shutil.copy(f, fonts / f.name)
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
            "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding"]
    for wgt in weights:
        head.append(f"Style: O{wgt},{FONT_FAMILY} {wgt},60,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,4,1,5,60,60,0,1")
        head.append(f"Style: B{wgt},{FONT_FAMILY} {wgt},60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,14,0,5,60,60,0,1")
    head += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    def ts(x: float) -> str:
        return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"
    lines = []
    for e in events:
        wgt = int(round(int(e.get("weight") or 800) / 100) * 100)
        # Claude büyük harf yüksekliğini verir; libass puntoyu satır yüksekliği sayar: Montserrat büyük harfi ≈ 0.58 satır
        size = int(np.clip(float(e.get("size") or 0.035), 0.015, 0.12) * H / 0.58)
        x = int(np.clip(float(e.get("x") or 0.5), 0.1, 0.9) * W)
        y = int(np.clip(float(e.get("y") or 0.5), 0.06, 0.94) * H)
        txt = tr_upper(e["text"]) if e.get("upper") else e["text"]
        txt = txt.replace("\n", "\\N").replace("{", "(").replace("}", ")")
        st = ("B" if e.get("box") else "O") + str(wgt)
        tags = f"\\an5\\pos({x},{y})\\fs{size}\\c{_ass_color(e.get('color') or '#FFFFFF')}"
        if e.get("box"):
            tags += f"\\3c{_ass_color(e['box'])}"
        elif not e.get("outline", True):
            tags += "\\bord0\\shad1"
        anim = e.get("anim") or "fade"
        if anim == "pop":
            tags += "\\fscx60\\fscy60\\t(0,140,\\fscx100\\fscy100)\\fad(60,120)"
        elif anim == "slide":
            tags += f"\\move({x},{y + 60},{x},{y},0,180)\\fad(80,120)"
        elif anim != "none":
            tags += "\\fad(150,150)"
        lines.append(f"Dialogue: 1,{ts(e['start'])},{ts(e['end'])},{st},,0,0,0,,{{{tags}}}{txt}")
    ass = work / "texts.ass"
    ass.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    return ass


def _grade(ref: dict, mine: dict) -> str:
    """Referansın renk havasına yaklaştıran eq/colorbalance zinciri (kullanıcı medyasının ölçümüne göre)."""
    if not ref or not mine:
        return ""
    # yarı güçte: fotoğrafların doğal rengi bozulmadan referansın havasına yaklaşılır
    sat = float(np.clip(((ref.get("saturation", 0.3) + 0.05) / (mine.get("saturation", 0.3) + 0.05)) ** 0.5, 0.8, 1.3))
    con = float(np.clip(((ref.get("contrast", 0.2) + 0.05) / (mine.get("contrast", 0.2) + 0.05)) ** 0.5, 0.85, 1.2))
    bri = float(np.clip((ref.get("brightness", 0.45) - mine.get("brightness", 0.45)) * 0.7, -0.12, 0.12))
    warm = float(np.clip((ref.get("warmth", 0) - mine.get("warmth", 0)) * 0.6, -0.15, 0.15))
    f = f"eq=saturation={sat:.3f}:contrast={con:.3f}:brightness={bri:.3f}"
    if abs(warm) > 0.01:
        f += f",colorbalance=rm={warm:.3f}:bm={-warm:.3f}:rh={warm / 2:.3f}:bh={-warm / 2:.3f}"
    return f


def _adapt_texts(tpl: dict, istek: str, cfg: Config, work: Path) -> list[dict]:
    """Yazıları kullanıcının konusuna uyarlar (aynı sayıda, benzer uzunlukta, aynı rol/konum)."""
    from .studio import ai_mode, ask_ai
    texts = tpl.get("texts") or []
    if not texts or not istek or ai_mode(cfg) == "none":
        return texts
    prompt = ("Bir videonun ekran yazılarını kullanıcının kendi konusuna uyarla. Her yazının uzunluğu ve tonu aynı "
              "kalsın (kalıp birebir), yalnızca içerik kullanıcının konusuna dönsün. Türkçe yaz.\n"
              f"Kullanıcının konusu/isteği: «{istek}»\nYazılar (sırayla): " +
              json.dumps([t["text"] for t in texts], ensure_ascii=False) +
              '\nBiçim: {"texts": ["...", "..."]} — aynı sayıda öğe.')
    res = ask_ai(cfg, prompt, [], work / "template_texts.json", timeout=240)
    new = (res or {}).get("texts") if isinstance(res, dict) else None
    if isinstance(new, list) and len(new) == len(texts):
        return [{**t, "text": str(n)} for t, n in zip(texts, new)]
    return texts


def render(tpl: dict, media: list[Path], dest: Path, work: Path, opts: dict | None = None) -> dict:
    """Şablonu kullanıcının medyasına uygular. opts: {text_mode: aynen|uyarla|yok, istek, music: path|None|False}"""
    from .studio import color_metrics, media_info, normalize_image, sample_frames
    opts = opts or {}
    cfg = load_config()
    work, dest = Path(work).resolve(), Path(dest).resolve()
    media = [Path(m).resolve() for m in media]
    work.mkdir(parents=True, exist_ok=True)
    shots, trans = tpl["shots"], {round(t["t"], 3): t for t in tpl.get("transitions", [])}
    infos = [(m, media_info(m)) for m in media]
    infos = [(m, i) for m, i in infos if i["kind"] in ("image", "video")]
    if not infos:
        raise StageError("şablon için fotoğraf/video yok")
    # çekim sınırları ve geçiş süreleri
    cuts = [s["end"] for s in shots[:-1]]
    tdur = [max(float(trans.get(round(c, 3), {}).get("dur") or 0), 1 / FPS) for c in cuts]   # sert kesim = 1 kare
    ttyp = [trans.get(round(c, 3), {}).get("type", "cut") for c in cuts]
    parts, offsets = [], {}
    for i, sh in enumerate(shots):
        m, inf = infos[i % len(infos)]
        lead = tdur[i - 1] / 2 if i > 0 else 0.0
        tail = tdur[i] / 2 if i < len(cuts) else 0.0
        d = sh["dur"] + lead + tail
        off = 0.0
        if inf["kind"] == "video":   # aynı video birden çok çekimde: farklı bölümlerinden
            used = offsets.get(str(m), 0.0)
            off = used if used + d <= inf["duration"] else 0.0
            offsets[str(m)] = off + d
        part = work / f"shot{i:03d}.mp4"
        _shot_clip(m, inf["kind"], d, sh.get("motion") or {}, off, part)
        parts.append((part, d))
    # birleştir: geçişler xfade ile (sert kesim = 1 kare), zamanlar referansla aynı
    graph, last, acc = [], "[n0]", parts[0][1]
    inputs = []
    for k, (p, _) in enumerate(parts):
        inputs += ["-i", str(p)]
        graph.append(f"[{k}:v]settb=AVTB,fps={FPS},setpts=PTS-STARTPTS[n{k}]")   # xfade aynı zaman tabanı ister
    if len(parts) == 1:
        graph.append("[n0]null[vcat]")
    for k in range(1, len(parts)):
        td = tdur[k - 1]
        kind = XFADE.get(ttyp[k - 1]) or "fade"
        off = cuts[k - 1] - tdur[k - 1] / 2
        out = f"[x{k}]" if k < len(parts) - 1 else "[vcat]"
        graph.append(f"{last}[n{k}]xfade=transition={kind}:duration={td:.3f}:offset={max(0.0, off):.3f}{out}")
        last = out
        acc += parts[k][1] - td
    # renk + yazılar
    probe_frames = []   # kullanıcı medyasının renk ölçümü: her çekimden bir kare
    for k, (pp, d) in enumerate(parts[:24]):
        fp = work / f"mf{k:02d}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{d / 2:.2f}", "-i", pp, "-frames:v", "1", "-vf", "scale=192:-2", fp])
        probe_frames.append(fp)
    mine = color_metrics(probe_frames) if probe_frames else {}
    post = [x for x in [_grade(tpl.get("color") or {}, mine)] if x]
    texts = []
    mode = opts.get("text_mode") or ("uyarla" if opts.get("istek") else "aynen")
    if mode != "yok":
        texts = _adapt_texts(tpl, opts.get("istek") or "", cfg, work) if mode == "uyarla" else (tpl.get("texts") or [])
    ass = _ass(texts, shots, work)
    if ass:
        post.append("ass=texts.ass:fontsdir=fonts")
    graph.append(f"[vcat]{','.join(post) if post else 'null'},format=yuv420p[vout]")
    silent = work / "video.mp4"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph), "-map", "[vout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS), "-t", f"{tpl['duration']:.3f}", silent.name],
        cwd=work)
    # müzik: kullanıcınınki ya da lisanslı bir parça; referansın temposuna eşitlenir
    music_note = None
    mpath = opts.get("music")
    if mpath is None:
        try:
            from .audio import pick_music
            q = [tpl.get("music_query") or "upbeat pop instrumental"]
            res = pick_music(cfg, q, work, tpl["duration"], set())
            mpath = res and res.get("path")
            music_note = res and f"{res.get('title')} — {res.get('credit') or res.get('license')}"
        except Exception as exc:  # noqa: BLE001
            L.warning("şablon müziği bulunamadı: %s", exc)
            mpath = None
    if mpath:
        mpath = Path(mpath)
        af = []
        ref_bpm = float((tpl.get("music") or {}).get("bpm") or 0)
        if ref_bpm:
            mwav = work / "m.wav"
            run(["ffmpeg", "-y", "-v", "error", "-t", "60", "-i", mpath, "-ac", "1", "-ar", "22050", mwav])
            mb = tempo(mwav)["bpm"]
            if mb:
                cands = [ref_bpm / mb, ref_bpm / (2 * mb), 2 * ref_bpm / mb]
                f = min(cands, key=lambda x: abs(x - 1))
                if 0.85 <= f <= 1.15 and abs(f - 1) > 0.01:
                    af.append(f"atempo={f:.4f}")
                    music_note = (music_note or "müzik") + f" · tempo {mb:.0f}→{ref_bpm:.0f} BPM"
        af += [f"afade=t=out:st={max(0, tpl['duration'] - 1.2):.2f}:d=1.2", "loudnorm=I=-14:TP=-1.5:LRA=11"]
        run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-stream_loop", "-1", "-i", mpath, "-filter_complex",
             f"[1:a]{','.join(af)}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-shortest", "-movflags", "+faststart", dest])
    else:   # müzik yok: platformlar ses akışı bekler → sessiz ses akışı
        run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v",
             "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart", dest])
    L.info("Şablon uygulandı: %s (%d çekim, %d medya)", dest.name, len(shots), len(infos))
    return {"output": dest, "duration": tpl["duration"], "shots": len(shots), "media": len(infos),
            "texts": len(texts), "music": music_note}
