"""Kahvehane Böcekleri — "Gülme Krizi": özgün 2D çizgi kısa (karakterler, mekân, müzik bu dosyada üretilir).
Kullanım (reels-factory klasöründen): python cizgi/kahvehane_bocekleri.py <çıktı klasörü>   (reels-factory venv'i)"""
import math, subprocess, sys, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RF / "scripts"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else RF / "output" / "cizgi" / Path(__file__).stem); OUT.mkdir(parents=True, exist_ok=True)
W, H, FPS, SR = 1080, 1920, 30, 48000
INK = (30, 20, 16, 255)
FONT, TITLE = str(RF / "assets/fonts/Poppins-ExtraBold.ttf"), str(RF / "assets/fonts/ArchivoBlack-Regular.ttf")
SFX = RF / "node_modules/hyperframes/dist/skills/media-use/audio/assets/sfx"
rng = np.random.default_rng(12)
VOICE = {"Cemil": ("tr-TR-AhmetNeural", "+22Hz"), "Kenan": ("tr-TR-AhmetNeural", "-12Hz")}
COLOR = {"Cemil": (90, 180, 80), "Kenan": (170, 170, 185)}

# (sahne, ön boşluk, [(konuşan, metin)], son boşluk, olaylar)
SHOTS = [
    ("dusus", 2.4, [], 0.1, ["whoosh-short@0.95", "thud@1.35", "ting@1.5"]),
    ("yerde", 0.1, [("Kenan", "Oğlum ayağını kaldırsana, sandalye mi seni oturtuyor?")], 0.3, []),
    ("gulme", 0.1, [("Cemil", "Hahaha... Kenan... sandalye... beni devirdi... hahaha!")], 0.2, ["laugh@0.0"]),
    ("bogulma", 0.2, [("Cemil", "Öhö... öhö... öhöö...")], 0.2, ["cough@0.0", "cough@1.0", "cough@1.9"]),
    ("bogulma2", 0.1, [("Kenan", "Öl lan orospu çocuğu! Gülmeyi de mi beceremiyorsun?")], 0.2, ["cough@0.6", "cough@1.8", "sip@0.0"]),
    ("saplak", 2.8, [], 0.0, ["whoosh@0.3", "slap@0.55", "pop@0.7", "plop@1.9"]),
    ("final", 0.2, [("Cemil", "Sen beni sevmesen o şaplağı atmazdın.")], 0.3, ["laugh@1.9"]),
    ("final", 0.1, [("Kenan", "Atmasaydım çayıma bir cenaze daha karışacaktı. Kalk lan, tavla bekliyor.")], 0.6, ["dice@3.0"]),
    ("jenerik", 4.5, [], 0.0, ["chime@0.4"]),
]


def tts_all():
    from reels import tts
    from reels.config import load_config
    from reels.util import load_audio
    cfg, vdir, lines, n = load_config(), OUT / "voice", [], 0
    vdir.mkdir(exist_ok=True)
    for shot in SHOTS:
        for spk, text in shot[2]:
            sid = f"l{n:02d}"
            if not (vdir / f"{sid}.wav").exists():
                v, p = VOICE[spk]
                tts.synthesize_scene({"id": sid, "narration": text, "edge_voice": v, "edge_pitch": p}, vdir, cfg)
            lines.append({"speaker": spk, "text": text, "audio": load_audio(vdir / f"{sid}.wav", SR, 1).astype(np.float32)})
            n += 1
    return lines


def load_sfx(name):
    t = lambda s: np.arange(int(s * SR)) / SR  # noqa: E731
    if name == "thud":
        x = t(0.5); return (np.sin(2 * np.pi * 60 * x) * np.exp(-x * 8) * 0.9 + rng.standard_normal(len(x)) * np.exp(-x * 28) * 0.35).astype(np.float32)
    if name == "ting":  # sallanan çay bardağı
        x = t(0.8); return (0.25 * (np.sin(2 * np.pi * 2350 * x) + 0.6 * np.sin(2 * np.pi * 3510 * x)) * np.exp(-x * 5)).astype(np.float32)
    if name == "slap":
        x = t(0.25); return (rng.standard_normal(len(x)) * np.exp(-x * 45) * 0.9).astype(np.float32)
    if name == "plop":
        x = t(0.35); f = 900 * np.exp(-x * 12) + 200
        return (0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 9)).astype(np.float32)
    if name == "sip":
        x = t(0.6); return (rng.standard_normal(len(x)) * 0.12 * np.sin(np.pi * x / 0.6) ** 2).astype(np.float32)
    if name == "cough":  # boğuk öksürük
        x = t(0.35); n = rng.standard_normal(len(x))
        lp = np.convolve(n, np.ones(25) / 25, mode="same")
        return (lp * 2.2 * np.exp(-x * 10) * (1 + 0.5 * np.sin(2 * np.pi * 140 * x))).astype(np.float32)
    if name == "laugh":  # arka planda kısa kıkırtı: yükselip alçalan tonlar
        out = []
        for k in range(5):
            x = t(0.12); f = 520 + 60 * (k % 2)
            out += [0.18 * np.sin(2 * np.pi * f * x) * np.sin(np.pi * x / 0.12), np.zeros(int(0.06 * SR))]
        return np.concatenate(out).astype(np.float32)
    if name == "dice":  # tavla zarı
        out = []
        for k in range(4):
            x = t(0.05); out += [rng.standard_normal(len(x)) * np.exp(-x * 80) * 0.5, np.zeros(int((0.07 + 0.03 * k) * SR))]
        return np.concatenate(out).astype(np.float32)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SFX / f"{name}.mp3"), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def music(total, quiet, end_at):
    """Özgün kahvehane ezgisi: hicaz havasında kısa, oynak saz benzeri notalar + darbuka hissi."""
    t = np.arange(int(total * SR)) / SR
    beat = 60 / 132; notes = [62, 63, 66, 67, 69, 67, 66, 63]  # D hicaz
    m = np.zeros_like(t)
    for i in range(int(total / beat) + 1):
        s, e = int(i * beat * SR), min(len(t), int((i + 1) * beat * SR))
        if s >= len(t):
            break
        seg = t[s:e] - t[s]; f = 440 * 2 ** ((notes[i % 8] - 69) / 12)
        m[s:e] += 0.22 * (np.sin(2 * np.pi * f * seg) + 0.4 * np.sin(4 * np.pi * f * seg)) * np.exp(-seg * 7)
        if i % 2 == 0:
            m[s:e] += 0.25 * np.sin(2 * np.pi * 85 * seg * np.exp(-seg * 6)) * np.exp(-seg * 12)  # düm
        else:
            m[s:e] += 0.09 * rng.standard_normal(len(seg)) * np.exp(-seg * 35)  # tek
    g = np.full_like(t, 0.45)
    for a, b in quiet:
        g[int(a * SR):int(b * SR)] = 0.16
    g[int(end_at * SR):] = 0.9
    k = int(0.3 * SR)
    return (m * np.convolve(g, np.ones(k) / k, mode="same")).astype(np.float32)


# ------------------------------------------------------------------ çizim
def font(s, p=FONT):
    return ImageFont.truetype(p, s)


def cv(w=1200, h=2000):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); return im, ImageDraw.Draw(im)


BUG = (150, 92, 48)  # böcek kabuğu


def bug_head(d, cx, cy, r, face, mouth, expr, antenna_curl=False):
    lw = 16
    # antenler
    if antenna_curl:  # Kenan: burma bıyık gibi kıvrık
        for sgn in (-1, 1):
            d.arc((cx + sgn * 40 - 120, cy - r - 260, cx + sgn * 40 + 120, cy - r - 20), 200 if sgn < 0 else -20, 340 if sgn < 0 else 160, fill=INK, width=12)
    else:
        for sgn in (-1, 1):
            tip = (cx + sgn * 190, cy - r - (250 if expr != "choke" else 300))
            d.line((cx + sgn * 50, cy - r + 30, tip[0], tip[1]), fill=INK, width=12)
            d.ellipse((tip[0] - 16, tip[1] - 16, tip[0] + 16, tip[1] + 16), fill=INK)
    d.ellipse((cx - r, cy - r, cx + r, cy + r * 0.95), fill=face, outline=INK, width=lw)
    # gözler
    for sgn in (-1, 1):
        ex = cx + sgn * r * 0.4; ey = cy - r * 0.15
        if expr in ("laugh",):
            d.arc((ex - 55, ey - 30, ex + 55, ey + 40), 200, 340, fill=INK, width=14)
            if expr == "laugh":
                d.ellipse((ex - 12, ey + 40, ex + 8, ey + 70), fill=(120, 200, 255))  # gülme yaşı
        elif expr == "choke":
            d.ellipse((ex - 62, ey - 62, ex + 62, ey + 62), fill=(255, 255, 255), outline=INK, width=12)
            d.ellipse((ex - 12, ey - 12, ex + 12, ey + 12), fill=INK)
        else:
            d.ellipse((ex - 55, ey - 50, ex + 55, ey + 50), fill=(255, 255, 255), outline=INK, width=12)
            d.ellipse((ex - 20 + sgn * 6, ey - 16, ex + 20 + sgn * 6, ey + 24), fill=INK)
            if expr == "annoyed":
                d.chord((ex - 55, ey - 50, ex + 55, ey + 50), 180, 360, fill=face, outline=INK, width=12)
    if expr == "annoyed":
        d.line((cx - r * 0.65, cy - r * 0.55, cx - r * 0.15, cy - r * 0.45), fill=INK, width=16)
        d.line((cx + r * 0.15, cy - r * 0.45, cx + r * 0.65, cy - r * 0.55), fill=INK, width=16)
    my = cy + r * 0.45
    if expr == "choke":
        d.ellipse((cx - 50, my - 30, cx + 50, my + 50), fill=(70, 10, 20), outline=INK, width=10)
        d.ellipse((cx - 22, my + 10, cx + 22, my + 70), fill=(230, 90, 110), outline=INK, width=6)  # dil
    elif mouth or expr == "laugh":
        d.chord((cx - 85, my - 45, cx + 85, my + 85), 0, 180, fill=(70, 10, 20), outline=INK, width=10)
    else:
        d.arc((cx - 60, my - 30, cx + 60, my + 30), 20 if expr != "annoyed" else 200, 160 if expr != "annoyed" else 340, fill=INK, width=12)


def cemil(mouth, expr="normal", choke=0.0):
    """Tombul, yeşil kasketli, ekose gömlekli böcek. choke 0..1: yüz maviye döner."""
    im, d = cv(); lw = 16
    face = tuple(int(BUG[k] * (1 - choke) + (70, 110, 200)[k] * choke) for k in range(3))
    for x in (440, 640):  # bacaklar
        d.rounded_rectangle((x, 1480, x + 120, 1880), 50, fill=(60, 60, 90), outline=INK, width=lw)
        d.ellipse((x - 40, 1840, x + 160, 1950), fill=(90, 50, 30), outline=INK, width=lw)
    d.ellipse((330, 900, 870, 1580), fill=(70, 150, 70), outline=INK, width=lw)  # tombul gövde, ekose
    for k in range(6):
        d.line((360 + k * 90, 930, 360 + k * 90, 1560), fill=(40, 110, 50), width=12)
        d.line((350, 980 + k * 100, 850, 980 + k * 100), fill=(230, 210, 80), width=6)
    d.ellipse((330, 900, 870, 1580), outline=INK, width=lw)
    for x0, x1 in ((210, 350), (850, 990)):  # 4 kol (böcek!)
        for yy in (980, 1200):
            d.rounded_rectangle((x0, yy, x1, yy + 70), 35, fill=(70, 150, 70), outline=INK, width=12)
            d.ellipse((x0 - 30 if x0 < 600 else x1 - 40, yy - 10, (x0 - 30 if x0 < 600 else x1 - 40) + 70, yy + 80), fill=face, outline=INK, width=10)
    bug_head(d, 600, 620, 270, face, mouth, expr)
    d.chord((350, 300, 850, 620), 180, 360, fill=(50, 130, 60), outline=INK, width=lw)  # kasket
    d.polygon([(560, 470), (900, 470), (860, 520), (560, 520)], fill=(40, 110, 50), outline=INK)
    return im


def kenan(mouth, expr="annoyed", arm="cay"):
    """Uzun, ince, gri yelekli, kıvrık antenli (burma bıyık) böcek."""
    im, d = cv(); lw = 16
    for x in (480, 640):
        d.rounded_rectangle((x, 1420, x + 90, 1890), 40, fill=(50, 40, 40), outline=INK, width=lw)
        d.ellipse((x - 40, 1850, x + 130, 1950), fill=(20, 20, 20), outline=INK, width=lw)
    d.rounded_rectangle((430, 880, 770, 1470), 90, fill=(240, 236, 226), outline=INK, width=lw)  # beyaz gömlek
    d.polygon([(440, 900), (600, 1200), (760, 900), (770, 1460), (430, 1460)], fill=(120, 124, 134), outline=INK)  # gri yelek
    for y in (1250, 1330, 1410):
        d.ellipse((585, y, 615, y + 30), fill=(40, 40, 40))
    d.rounded_rectangle((300, 920, 440, 1300), 60, fill=(240, 236, 226), outline=INK, width=lw)
    d.ellipse((300, 1270, 440, 1390), fill=BUG, outline=INK, width=lw)
    if arm == "cay":  # elinde ince belli çay bardağı
        d.rounded_rectangle((760, 920, 900, 1180), 60, fill=(240, 236, 226), outline=INK, width=lw)
        d.ellipse((780, 1150, 900, 1260), fill=BUG, outline=INK, width=lw)
        d.polygon([(800, 990), (880, 990), (860, 1060), (875, 1150), (805, 1150), (820, 1060)], fill=(180, 60, 30, 230), outline=INK)
    elif arm == "saplak":  # kaldırılmış el
        d.rounded_rectangle((760, 560, 900, 960), 60, fill=(240, 236, 226), outline=INK, width=lw)
        d.ellipse((750, 470, 910, 610), fill=BUG, outline=INK, width=lw)
    else:
        d.rounded_rectangle((760, 920, 900, 1300), 60, fill=(240, 236, 226), outline=INK, width=lw)
        d.ellipse((760, 1270, 900, 1390), fill=BUG, outline=INK, width=lw)
    bug_head(d, 600, 640, 230, BUG, mouth, expr, antenna_curl=True)
    return im


def card(im, h):
    return im.resize((int(im.width * h / im.height), h), Image.LANCZOS)


def kahvehane():
    im = Image.new("RGBA", (W, H), (236, 214, 168, 255)); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 760), fill=(200, 160, 110)); d.rectangle((0, 740, W, 790), fill=(120, 78, 46))  # lambri
    for x in range(0, W, 90):
        d.line((x, 790, x, 1260), fill=(220, 196, 150), width=4)
    d.rectangle((0, 1260, W, H), fill=(150, 110, 80))
    for y in range(1260, H, 110):  # karo zemin
        for x in range(-((y // 110) % 2) * 55, W, 110):
            d.rectangle((x, y, x + 108, y + 108), fill=(170, 128, 92) if ((x // 110 + y // 110) % 2) else (140, 100, 72))
    d.rectangle((640, 120, 1000, 460), fill=(30, 40, 70), outline=INK, width=10)  # pencere: gece
    d.line((820, 120, 820, 460), fill=INK, width=8); d.line((640, 290, 1000, 290), fill=INK, width=8)
    d.ellipse((880, 160, 960, 240), fill=(250, 240, 200))
    d.ellipse((120, 140, 360, 380), fill=(250, 248, 236), outline=INK, width=10)  # duvar saati
    d.line((240, 260, 240, 180), fill=INK, width=8); d.line((240, 260, 300, 270), fill=INK, width=6)
    d.line((540, 0, 540, 170), fill=INK, width=5); d.polygon([(470, 170), (610, 170), (580, 230), (500, 230)], fill=(230, 180, 60), outline=INK)  # lamba
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(glow).ellipse((260, 120, 820, 560), fill=(255, 230, 140, 70))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40))); d = ImageDraw.Draw(im)
    # ocak köşesi: tezgâh + semaver + bardak
    d.rectangle((760, 900, W, 1300), fill=(110, 70, 40), outline=INK, width=8)
    d.rectangle((380, 600, 600, 625), fill=(110, 70, 40), outline=INK, width=6)  # raf: semaver Kenan'ın arkasında kalmasın
    d.rounded_rectangle((430, 470, 550, 600), 24, fill=(200, 200, 210), outline=INK, width=8)  # semaver
    d.polygon([(460, 470), (520, 470), (505, 430), (475, 430)], fill=(180, 180, 190), outline=INK)
    # tavla masası (önde)
    d.rectangle((90, 1180, 560, 1240), fill=(120, 70, 40), outline=INK, width=8)
    d.rectangle((150, 1240, 190, 1500), fill=(100, 60, 34)); d.rectangle((460, 1240, 500, 1500), fill=(100, 60, 34))
    d.rectangle((120, 1120, 530, 1185), fill=(170, 110, 60), outline=INK, width=6)
    for k in range(6):
        d.polygon([(140 + k * 33, 1125), (156 + k * 33, 1180), (172 + k * 33, 1125)], fill=(230, 210, 170) if k % 2 else (90, 40, 30))
    return im


def tea_glass(d, x, y, s=1.0, fill_lvl=True):
    pts = [(x - 30 * s, y), (x + 30 * s, y), (x + 18 * s, y + 50 * s), (x + 30 * s, y + 110 * s), (x - 30 * s, y + 110 * s), (x - 18 * s, y + 50 * s)]
    d.polygon(pts, fill=(185, 60, 25, 235) if fill_lvl else (230, 240, 250, 200), outline=INK)
    d.ellipse((x - 42 * s, y + 104 * s, x + 42 * s, y + 124 * s), fill=(240, 240, 240), outline=INK, width=4)


def subtitle(fr, ln, t):
    d = ImageDraw.Draw(fr); f = font(56); fn = font(40)
    words = ln["text"].split(); dur = ln["t1"] - ln["t0"]
    k = min(len(words), int((t - ln["t0"]) / max(dur, 0.1) * len(words)) + 1)
    lines, cur = [], ""
    for w in words:
        if d.textlength((cur + " " + w).strip(), font=f) <= W - 180:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    acc, idx = 0, 0
    for i, l in enumerate(lines):
        acc += len(l.split())
        if acc >= k:
            idx = i; break
    show = lines[(idx // 2) * 2:(idx // 2) * 2 + 2]
    y = 1560
    d.rounded_rectangle((50, y - 76, W - 50, y + 26 + 72 * len(show)), 30, fill=(16, 10, 8, 200))
    d.text((90, y - 64), ("CIRCIR CEMİL" if ln["speaker"] == "Cemil" else "KARA KENAN"), font=fn, fill=COLOR[ln["speaker"]])
    for l in show:
        d.text(((W - d.textlength(l, font=f)) / 2, y), l, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0)); y += 72


def timeline(lines):
    shots, t, li = [], 0.0, 0
    for name, pre, ls, post, ev in SHOTS:
        s0 = t; t += pre; items = []
        for spk, text in ls:
            ln = lines[li]; li += 1; dd = len(ln["audio"]) / SR
            items.append({**ln, "t0": t, "t1": t + dd}); t += dd + 0.15
        t += post
        shots.append({"name": name, "t0": s0, "t1": t, "lines": items,
                      "events": [(e.split("@")[0], s0 + float(e.split("@")[1])) for e in ev]})
    return shots, t


def compose(shots, total):
    bg = kahvehane(); cache = {}

    def C(key, fn, h):
        if key not in cache:
            cache[key] = card(fn(), h)
        return cache[key]

    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", str(OUT / "video.mp4")], stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        sh = next((s for s in shots if s["t0"] <= t < s["t1"]), shots[-1]); rel = t - sh["t0"]; n = sh["name"]
        ln = next((l for l in sh["lines"] if l["t0"] <= t < l["t1"]), None)
        rms = 0.0
        if ln is not None:
            i = int((t - ln["t0"]) * SR); seg = ln["audio"][max(0, i - 600): i + 600]; rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0
        talk = lambda who: ln is not None and ln["speaker"] == who and rms > 0.02 and (fi // 3) % 2 == 0  # noqa: E731
        fr = bg.copy(); d = ImageDraw.Draw(fr); zoom, shake = 1.0 + 0.04 * min(1, rel / 4), 0
        tea_glass(d, 900, 1180, 1.0, True)  # ocaktaki bardak
        bob = math.sin(t * 5) * 6
        if n == "jenerik":
            fr = Image.new("RGBA", (W, H), (20, 12, 8, 255)); d = ImageDraw.Draw(fr)
            p = min(1, rel / 0.8)
            for txt, sz, y, col in (("KAHVEHANE", 120, 720, (255, 200, 90)), ("BÖCEKLERİ", 120, 860, (120, 210, 110)), ("Gülme Krizi", 54, 1030, (230, 220, 210))):
                f2 = font(sz, TITLE if sz > 60 else FONT); wob = math.sin(t * 6 + y) * 6
                d.text(((W - d.textlength(txt, font=f2)) / 2 + wob, y), txt, font=f2, fill=col + (int(255 * p),))
            tea_glass(d, 540, 1200, 1.6, True)
        else:
            # Kenan: her sahnede sağda
            k_arm = "saplak" if n == "saplak" and 0.2 < rel < 0.75 else ("cay" if n in ("yerde", "bogulma2", "gulme", "bogulma") else "bos")
            k_expr = "annoyed"
            kk = C(f"K{int(talk('Kenan'))}{k_arm}", lambda: kenan(talk("Kenan"), k_expr, k_arm), 1000)
            kx = 600 if n != "saplak" else int(600 - 260 * min(1, max(0, rel - 0.05) / 0.3))
            fr.alpha_composite(kk, (kx, 560 + int(bob / 2)))
            # Cemil
            if n == "dusus":
                fall = min(1, max(0, rel - 0.9) / 0.45)
                ce = C("Cstand" if fall == 0 else "Cfall", lambda: cemil(False, "normal" if fall == 0 else "choke", 0), 900)
                if fall > 0:
                    ce = ce.rotate(-88 * fall ** 2, expand=True, resample=Image.BICUBIC)
                y = 640 + int(360 * fall ** 2)
                fr.alpha_composite(ce, (60 if fall == 0 else 20, min(1000, y)))
                if 1.3 < rel < 1.75:
                    shake = 22
            elif n in ("yerde", "gulme", "bogulma", "bogulma2"):
                choke = 0.0 if n in ("yerde", "gulme") else (min(1, rel / 2.5) if n == "bogulma" else 1.0)
                expr = "laugh" if n == "gulme" else ("choke" if n.startswith("bogulma") else "normal")
                key = f"Cfloor{expr}{int(talk('Cemil'))}{int(choke * 10)}"
                ce = C(key, lambda: cemil(talk("Cemil"), expr, choke), 900).rotate(-88, expand=True, resample=Image.BICUBIC)
                wig = int(math.sin(t * (22 if n != "yerde" else 2)) * (14 if n != "yerde" else 2))
                fr.alpha_composite(ce, (20 + wig, 1000))
                if n == "gulme":
                    d = ImageDraw.Draw(fr)
                    for k2 in range(3):  # "HA HA" yazıları
                        a = (t * 1.5 + k2 / 3) % 1
                        d.text((180 + k2 * 160, 1100 - int(a * 300)), "HA!", font=font(70), fill=(255, 255, 255, int(255 * (1 - a))), stroke_width=5, stroke_fill=(40, 20, 10))
                if n.startswith("bogulma"):
                    d = ImageDraw.Draw(fr)
                    for k2 in range(4):  # simit kırıntıları + ter
                        d.ellipse((560 + k2 * 25, 1300 - int(abs(math.sin(t * 9 + k2)) * 60), 575 + k2 * 25, 1315 - int(abs(math.sin(t * 9 + k2)) * 60)), fill=(210, 150, 70))
            elif n == "saplak":
                ce = C("Csit", lambda: cemil(False, "choke", 0.8 if rel < 0.55 else 0.2), 900)
                fr.alpha_composite(ce, (40, 700))
                if 0.5 < rel < 0.8:
                    shake = 18
                    d.text((330, 860), "ŞAP!", font=font(110, TITLE), fill=(255, 230, 80), stroke_width=8, stroke_fill=(150, 40, 20))
                if 0.6 < rel < 1.9:  # simit parçası yay çizerek bardağa
                    u = (rel - 0.6) / 1.3; sx = 420 + (900 - 420) * u; sy = 880 - 500 * math.sin(math.pi * u) + 300 * u
                    d.ellipse((sx - 26, sy - 18, sx + 26, sy + 18), fill=(215, 150, 70), outline=INK, width=6)
                if 1.9 <= rel < 2.5:
                    for k2 in range(6):
                        a = k2 / 6 * math.pi
                        d.ellipse((900 + math.cos(a) * 60 * (rel - 1.9) * 4 - 8, 1170 - math.sin(a) * 70 * (rel - 1.9) * 4 - 8,
                                   900 + math.cos(a) * 60 * (rel - 1.9) * 4 + 8, 1170 - math.sin(a) * 70 * (rel - 1.9) * 4 + 8), fill=(190, 70, 30))
            elif n == "final":
                ce = C(f"Cfin{int(talk('Cemil'))}", lambda: cemil(talk("Cemil"), "laugh", 0), 900)
                fr.alpha_composite(ce, (40, 700 + int(bob)))
        if ln is not None:
            subtitle(fr, ln, t)
        if zoom != 1.0 or shake:
            dx = int(rng.integers(-shake, shake + 1)) if shake else 0; dy = int(rng.integers(-shake, shake + 1)) if shake else 0
            cw, ch = int(W / zoom), int(H / zoom)
            x0 = max(0, min(W - cw, (W - cw) // 2 + dx)); y0 = max(0, min(H - ch, (H - ch) // 2 + dy))
            fr = fr.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
        ff.stdin.write(fr.convert("RGB").tobytes())
    ff.stdin.close(); ff.wait()


def mix(shots, total):
    n = int(total * SR); voice = np.zeros(n, np.float32); fx = np.zeros(n, np.float32); quiet = []
    for sh in shots:
        for ln in sh["lines"]:
            i = int(ln["t0"] * SR); a = ln["audio"][: n - i]; voice[i:i + len(a)] += a; quiet.append((ln["t0"] - 0.1, ln["t1"] + 0.2))
        for name, et in sh["events"]:
            s = load_sfx(name) * 0.6; i = int(et * SR); s = s[: max(0, n - i)]; fx[i:i + len(s)] += s
    jen = next(s["t0"] for s in shots if s["name"] == "jenerik")
    mus = music(total, quiet, jen)[:n]
    out = voice + 0.75 * fx + 0.8 * np.pad(mus, (0, n - len(mus)))
    out = out / max(1e-6, np.abs(out).max()) * 0.95
    with wave.open(str(OUT / "mix_raw.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(OUT / "mix_raw.wav"), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "2",
                    str(OUT / "mix.wav")], check=True)

    def ts(x):
        h, r = divmod(x, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
    rows = [ln for sh in shots for ln in sh["lines"]]
    (OUT / "altyazi.srt").write_text("\n".join(f"{k + 1}\n{ts(l['t0'])} --> {ts(l['t1'])}\n{l['speaker']}: {l['text']}\n" for k, l in enumerate(rows)),
                                     encoding="utf-8")


if __name__ == "__main__":
    lines = tts_all(); shots, total = timeline(lines)
    print(f"süre {total:.1f} sn", flush=True)
    mix(shots, total); compose(shots, total)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(OUT / "video.mp4"), "-i", str(OUT / "mix.wav"), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT / "kahvehane_bocekleri.mp4")], check=True)
    print("bitti", OUT / "kahvehane_bocekleri.mp4")
