"""Burak & Kaan — özgün 2D çizgi kısa film (karakterler, mekânlar, müzik bu dosyada üretilir).
Kullanım (reels-factory klasöründen): python cizgi/burak_ve_kaan.py <çıktı klasörü>   (reels-factory venv'i; seslendirme fabrikanın tts modülüyle)"""
import json, math, subprocess, sys, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RF / "scripts"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else RF / "output" / "cizgi" / Path(__file__).stem); OUT.mkdir(parents=True, exist_ok=True)
W, H, FPS, SR = 1080, 1920, 30, 48000
INK = (26, 18, 30, 255)
FONT = str(RF / "assets/fonts/Poppins-ExtraBold.ttf")
TITLE = str(RF / "assets/fonts/ArchivoBlack-Regular.ttf")
SFX = RF / "node_modules/hyperframes/dist/skills/media-use/audio/assets/sfx"
rng = np.random.default_rng(9)

# ------------------------------------------------------------------ senaryo (kullanıcının diyalogları)
VOICE = {"Burak": ("tr-TR-AhmetNeural", "-14Hz"), "Kaan": ("tr-TR-AhmetNeural", "+28Hz"),
         "Kraliçe": ("tr-TR-EmelNeural", "-6Hz")}
COLOR = {"Burak": (255, 140, 50), "Kaan": (90, 220, 130), "Kraliçe": (255, 105, 190)}
SHOTS = [  # (sahne, ön boşluk sn, [satırlar], son boşluk sn, olaylar)
    ("garaj", 2.2, [], 0.2, ["clank@0.3", "clank@0.9", "clank@1.5"]),
    ("garaj", 0.2, [("Burak", "Bak Kaan, amına koyim, şu lehim makinesini düzgün tutmazsan evreni değil, ananın amını tersten görürüz. Anladın mı beni velet?")], 0.4, []),
    ("garaj", 0.1, [("Kaan", "Amca sal gerçekten, yeter! Dün gece, sadece beş dakikalık bir boyut arası kaçamak yapacağız dedin; uzaylı mafya tarafından sikiliyorduk az kalsın! Üç gün boyunca çöl gezegeninde kaktüs suyu içtik!")], 0.4, []),
    ("garaj", 0.1, [("Burak", "Abartma lan kerhane kaçağı! Adamlar misafirperverdi, sadece bi böbreğini armağan etmeni istediler, o kadar. Hadi bin gemiye, portalı açıyorum.")], 0.3, []),
    ("portal", 3.6, [], 0.0, ["riser@0.0", "whoosh-cinematic@2.4", "glitch-1@2.9"]),
    ("gezegen", 2.6, [], 0.0, ["whoosh@0.2", "sparkle@1.2"]),
    ("kokpit", 0.3, [("Kaan", "Burası neresi amca? Her yerde seks şop tabelası var amk, n'oluyor burada?")], 0.3, []),
    ("kokpit", 0.1, [("Burak", "Siktir... Koordinatları yanlış girmişiz. Burası Hedonizm Dokuz galaksisi. Buradaki heriflerin her şeyi, amına koyim, fetiş üzerine kurulu. Sakın ha kimseyle göz teması kurma, yoksa seni sabaha kadar köle yapıp... Neyse, duymak istemezsin.")], 0.3, ["typing@0.2"]),
    ("kralice", 1.2, [("Kraliçe", "Aga beyler! Vergi yerine hepiniz striptiz yapacaksınız, yoksa atomunuza kadar sikeriz!")], 0.3, ["impact-bass-1@0.0"]),
    ("kokpit_alarm", 0.1, [("Burak", "Siktir git lan lağım faresi! Kaan, bas gaza amına koyim, bas!")], 0.2, ["error@0.0"]),
    ("kovalamaca", 0.6, [("Kaan", "Ölüyoruz! Amca sıçtık, cidden sıçtık!")], 0.2, ["laser@0.2", "laser@0.7", "laser@1.3", "laser@1.9", "laser@2.6"]),
    ("kovalamaca", 0.1, [("Burak", "Korkma lan korkak tavuk! Hayatın kuralı budur: ya herkesin amına koyarsın, ya da onlar senin. Bak şimdi...")], 0.4, ["laser@0.5", "laser@1.6", "pop@3.0", "laser@3.4"]),
    ("patlama", 3.4, [], 0.0, ["boom@0.15", "impact-bass-2@0.15"]),
    ("dusus", 2.6, [], 0.0, ["whoosh-short@0.0", "glitch-2@0.4", "thud@1.5"]),
    ("garaj_son", 0.6, [("Kaan", "Yemin ediyorum, bir daha seninle hiçbir yere gelmeyeceğim.")], 0.4, []),
    ("garaj_son", 0.1, [("Burak", "Kes sesini ve şu birayı getir Kaan. Yarın sabah Andromeda'da kaçak böbrek ticareti yapacağız, erken kalkıcaz.")], 0.6, ["can@0.2"]),
    ("jenerik", 7.0, [], 0.0, []),
]


# ------------------------------------------------------------------ ses
def tts_all():
    from reels import tts
    from reels.config import load_config
    from reels.util import load_audio
    cfg, vdir, lines = load_config(), OUT / "voice", []
    vdir.mkdir(exist_ok=True)
    n = 0
    for shot in SHOTS:
        for spk, text in shot[2]:
            sid = f"l{n:02d}"
            if not (vdir / f"{sid}.wav").exists():
                v, p = VOICE[spk]
                tts.synthesize_scene({"id": sid, "narration": text, "edge_voice": v, "edge_pitch": p}, vdir, cfg)
            a = load_audio(vdir / f"{sid}.wav", SR, 1).astype(np.float32)
            if spk == "Kraliçe":  # megafon: bant geçiren + hafif bozulma
                a = megaphone(a)
            lines.append({"sid": sid, "speaker": spk, "text": text, "audio": a})
            n += 1
    return lines


def megaphone(a):
    f = np.fft.rfft(a); fr = np.fft.rfftfreq(len(a), 1 / SR)
    f[(fr < 450) | (fr > 3600)] *= 0.06
    y = np.fft.irfft(f, len(a))
    y = np.tanh(y * 3.2) / 2.2
    return y.astype(np.float32)


def load_sfx(name):
    if name == "laser":
        t = np.arange(int(0.28 * SR)) / SR
        f = 1800 * np.exp(-t * 9) + 220
        return (0.35 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * np.exp(-t * 8)).astype(np.float32)
    if name == "boom":
        t = np.arange(int(2.6 * SR)) / SR
        n = rng.standard_normal(len(t)).astype(np.float32)
        lp = np.convolve(n, np.ones(60) / 60, mode="same")
        return (lp * 3.0 * np.exp(-t * 1.6) + 0.6 * np.sin(2 * np.pi * 45 * t) * np.exp(-t * 2.5)).astype(np.float32)
    if name in ("clank", "thud", "can"):
        t = np.arange(int(0.45 * SR)) / SR
        if name == "clank":
            s = sum(np.sin(2 * np.pi * f * t) for f in (520, 1290, 2210)) * np.exp(-t * 14) * 0.25
        elif name == "thud":
            s = np.sin(2 * np.pi * 70 * t) * np.exp(-t * 9) * 0.9 + rng.standard_normal(len(t)) * np.exp(-t * 30) * 0.3
        else:  # bira kutusu açılışı: kısa tıslama
            s = rng.standard_normal(len(t)) * np.exp(-t * 10) * 0.25
        return s.astype(np.float32)
    p = SFX / f"{name}.mp3"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def music(total, cues):
    """Özgün absürt bilimkurgu müziği: titrek 'theremin' melodisi + bas + hafif davul; jenerikte ana tema."""
    t = np.arange(int(total * SR)) / SR
    bpm = 112; beat = 60 / bpm
    notes = [57, 60, 64, 62, 57, 65, 64, 59]  # A minör çevresi
    mel = np.zeros_like(t); bass = np.zeros_like(t); drum = np.zeros_like(t)
    for i in range(int(total / beat) + 1):
        s, e = int(i * beat * SR), min(len(t), int((i + 1) * beat * SR))
        if s >= len(t):
            break
        seg = t[s:e] - t[s]
        n = notes[(i // 2) % len(notes)] + (12 if (i // 16) % 2 else 0)
        f = 440 * 2 ** ((n - 69) / 12) * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * seg))
        mel[s:e] = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, seg * 12) * np.exp(-seg * 0.8)
        bf = 440 * 2 ** ((notes[(i // 4) % len(notes)] - 24 - 69) / 12)
        bass[s:e] = np.sign(np.sin(2 * np.pi * bf * seg)) * 0.5 * np.exp(-seg * 3)
        if i % 2 == 0:
            drum[s:e] = np.sin(2 * np.pi * 60 * seg * np.exp(-seg * 8)) * np.exp(-seg * 14)
        else:
            drum[s:e] = rng.standard_normal(len(seg)) * np.exp(-seg * 30) * 0.4
    m = 0.22 * mel + 0.16 * bass + 0.22 * drum
    gain = np.full_like(t, 0.55)
    for a, b in cues.get("quiet", []):
        gain[int(a * SR): int(b * SR)] = 0.18
    j = cues["jenerik"]
    gain[int(j * SR):] = 1.0
    k = int(0.4 * SR); gain = np.convolve(gain, np.ones(k) / k, mode="same")
    return (m * gain).astype(np.float32)


# ------------------------------------------------------------------ çizim yardımcıları
def canvas(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def font(size, path=FONT):
    return ImageFont.truetype(path, size)


def burak(mouth, expr="normal", hold="termos"):
    im, d = canvas(1200, 2000)
    lw = 16
    # bacaklar + ayakkabı
    d.rounded_rectangle((430, 1450, 560, 1900), 40, fill=(70, 58, 52), outline=INK, width=lw)
    d.rounded_rectangle((640, 1450, 770, 1900), 40, fill=(70, 58, 52), outline=INK, width=lw)
    d.ellipse((380, 1850, 600, 1960), fill=(40, 30, 30), outline=INK, width=lw)
    d.ellipse((600, 1850, 820, 1960), fill=(40, 30, 30), outline=INK, width=lw)
    # gövde: turuncu bomber ceket, içi zeytin yeşili tişört
    d.rounded_rectangle((360, 900, 840, 1520), 110, fill=(226, 118, 40), outline=INK, width=lw)
    d.polygon([(540, 905), (660, 905), (630, 1250), (570, 1250)], fill=(120, 130, 70), outline=INK)
    d.line((600, 1260, 600, 1500), fill=INK, width=8)
    # kollar
    d.rounded_rectangle((230, 950, 370, 1400), 60, fill=(226, 118, 40), outline=INK, width=lw)
    d.rounded_rectangle((830, 950, 970, 1330), 60, fill=(226, 118, 40), outline=INK, width=lw)
    d.ellipse((235, 1370, 365, 1490), fill=(240, 196, 160), outline=INK, width=lw)
    d.ellipse((835, 1300, 965, 1420), fill=(240, 196, 160), outline=INK, width=lw)
    if hold == "termos":
        d.rounded_rectangle((850, 1120, 950, 1400), 30, fill=(190, 196, 204), outline=INK, width=lw)
        d.rectangle((850, 1180, 950, 1215), fill=(120, 126, 136))
    elif hold == "bira":
        d.rounded_rectangle((860, 1180, 950, 1360), 18, fill=(60, 140, 200), outline=INK, width=lw)
        d.rectangle((860, 1230, 950, 1280), fill=(240, 240, 240))
    elif hold == "tornavida":
        d.line((900, 1360, 900, 1100), fill=(200, 60, 50), width=34); d.line((900, 1100, 900, 980), fill=(180, 180, 190), width=14)
    # kafa: kel, büyük
    d.ellipse((380, 260, 820, 780), fill=(240, 196, 160), outline=INK, width=lw)
    d.ellipse((350, 470, 420, 580), fill=(240, 196, 160), outline=INK, width=lw)
    d.ellipse((780, 470, 850, 580), fill=(240, 196, 160), outline=INK, width=lw)
    d.ellipse((470, 300, 560, 360), fill=(255, 225, 200))  # parlayan kel
    # alında güneş gözlüğü
    d.rounded_rectangle((440, 370, 585, 440), 24, fill=(30, 30, 40), outline=INK, width=10)
    d.rounded_rectangle((615, 370, 760, 440), 24, fill=(30, 30, 40), outline=INK, width=10)
    d.line((585, 400, 615, 400), fill=INK, width=10)
    # kaşlar + yarı kapalı gözler
    tilt = 30 if expr == "angry" else (-10 if expr == "laugh" else 10)
    d.line((450, 470 - tilt // 3, 570, 470 + tilt // 2), fill=(150, 150, 150), width=26)
    d.line((630, 470 + tilt // 2, 750, 470 - tilt // 3), fill=(150, 150, 150), width=26)
    for cx in (510, 690):
        d.ellipse((cx - 50, 490, cx + 50, 560), fill=(255, 255, 255), outline=INK, width=10)
        d.ellipse((cx - 16, 512, cx + 16, 548), fill=INK)
        if expr != "laugh":
            d.chord((cx - 50, 490, cx + 50, 560), 180, 360, fill=(240, 196, 160), outline=INK, width=10)  # yarı kapalı göz kapağı
    d.polygon([(600, 540), (565, 640), (640, 640)], fill=(230, 170, 135), outline=INK)  # burun
    # kocaman gri sakal
    d.chord((395, 470, 805, 960), 0, 180, fill=(196, 196, 200), outline=INK, width=lw)
    d.ellipse((470, 620, 730, 700), fill=(196, 196, 200))  # bıyık
    if mouth:
        d.ellipse((530, 680, 670, 780), fill=(80, 20, 30), outline=INK, width=10)
        d.ellipse((560, 740, 640, 775), fill=(220, 90, 100))
    else:
        d.arc((530, 660, 670, 730), 20, 160, fill=INK, width=12)
    return im


def kaan(mouth, expr="panik"):
    im, d = canvas(1200, 2000)
    lw = 16
    d.rounded_rectangle((470, 1420, 570, 1880), 40, fill=(60, 90, 160), outline=INK, width=lw)  # kot
    d.rounded_rectangle((630, 1420, 730, 1880), 40, fill=(60, 90, 160), outline=INK, width=lw)
    d.ellipse((420, 1840, 600, 1950), fill=(245, 245, 245), outline=INK, width=lw)
    d.ellipse((600, 1840, 780, 1950), fill=(245, 245, 245), outline=INK, width=lw)
    d.rounded_rectangle((400, 860, 800, 1480), 120, fill=(58, 156, 92), outline=INK, width=lw)  # yeşil kapüşonlu
    d.ellipse((470, 820, 730, 960), fill=(48, 130, 76), outline=INK, width=lw)  # kapüşon
    d.rounded_rectangle((500, 1220, 700, 1330), 40, fill=(48, 130, 76), outline=INK, width=10)  # cep
    up = expr == "panik"
    for x0, x1 in ((280, 410), (790, 920)):  # kollar: panikte yukarı
        if up:
            d.rounded_rectangle((x0, 600, x1, 960), 60, fill=(58, 156, 92), outline=INK, width=lw)
            d.ellipse((x0 + 5, 520, x1 - 5, 640), fill=(250, 214, 180), outline=INK, width=lw)
        else:
            d.rounded_rectangle((x0, 900, x1, 1350), 60, fill=(58, 156, 92), outline=INK, width=lw)
            d.ellipse((x0 + 5, 1320, x1 - 5, 1440), fill=(250, 214, 180), outline=INK, width=lw)
    d.ellipse((410, 330, 790, 860), fill=(250, 214, 180), outline=INK, width=lw)  # kafa
    for cx, cy, r in ((450, 380, 80), (530, 320, 90), (620, 300, 95), (710, 330, 85), (770, 400, 70), (420, 450, 60)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(96, 62, 40), outline=INK, width=12)  # kıvırcık saç
    for cx in (520, 680):  # iri gözlük + gözler
        d.ellipse((cx - 85, 500, cx + 85, 670), fill=(255, 255, 255), outline=INK, width=14)
        pr = 14 if up else 24
        d.ellipse((cx - pr, 585 - pr, cx + pr, 585 + pr), fill=INK)
    d.line((605, 585, 595, 585), fill=INK, width=12)
    d.line((470, 470, 570, 445 if up else 470), fill=(96, 62, 40), width=18)
    d.line((630, 445 if up else 470, 730, 470), fill=(96, 62, 40), width=18)
    if mouth:
        d.ellipse((550, 700, 650, 800), fill=(80, 20, 30), outline=INK, width=10)
    else:
        d.arc((545, 700, 655, 780), 200, 340, fill=INK, width=12) if up else d.line((560, 740, 640, 740), fill=INK, width=12)
    if up:  # ter damlaları
        for x, y in ((390, 520), (820, 470)):
            d.polygon([(x, y), (x - 22, y + 50), (x + 22, y + 50)], fill=(120, 200, 255), outline=INK)
            d.ellipse((x - 22, y + 30, x + 22, y + 74), fill=(120, 200, 255), outline=INK, width=8)
    return im


def kralice(mouth):
    im, d = canvas(1400, 2400)
    lw = 18
    d.polygon([(700, 900), (220, 2380), (1180, 2380)], fill=(28, 22, 34), outline=INK)  # gotik elbise
    for i in range(7):
        x = 300 + i * 133
        d.polygon([(x, 2380), (x + 66, 2250), (x + 133, 2380)], fill=(60, 30, 70))
    d.polygon([(470, 1000), (700, 900), (930, 1000), (980, 1150), (420, 1150)], fill=(60, 30, 70), outline=INK)  # yaka
    d.rounded_rectangle((560, 780, 840, 960), 80, fill=(255, 120, 190), outline=INK, width=lw)  # boyun
    d.ellipse((430, 260, 970, 880), fill=(255, 120, 190), outline=INK, width=lw)  # kafa
    d.polygon([(520, 300), (560, 160), (620, 280), (700, 130), (780, 280), (840, 160), (880, 300)],
              fill=(240, 200, 60), outline=INK)  # taç
    for cx in (560, 700, 840):  # üç göz
        d.ellipse((cx - 60, 470, cx + 60, 580), fill=(255, 255, 210), outline=INK, width=12)
        d.ellipse((cx - 20, 500, cx + 20, 555), fill=(140, 0, 90))
    d.line((500, 445, 900, 445), fill=INK, width=14)
    if mouth:
        d.ellipse((620, 640, 780, 790), fill=(70, 0, 40), outline=INK, width=12)
    else:
        d.arc((620, 640, 780, 760), 20, 160, fill=INK, width=14)
    # megafon
    d.polygon([(800, 700), (1260, 520), (1260, 900)], fill=(220, 220, 230), outline=INK)
    d.rectangle((760, 670, 820, 740), fill=(160, 160, 170), outline=INK, width=10)
    d.ellipse((1180, 520, 1340, 900), fill=(190, 190, 200), outline=INK, width=lw)
    return im


def gemi(scale=1.0, burn=False):
    im, d = canvas(1400, 800)
    d.ellipse((80, 300, 1320, 640), fill=(150, 160, 170), outline=INK, width=18)  # gövde
    d.ellipse((420, 120, 980, 460), fill=(150, 220, 255, 230), outline=INK, width=16)  # kokpit
    for x, y, c in ((300, 470, (190, 110, 60)), (900, 500, (120, 120, 120)), (650, 560, (200, 90, 60))):  # yamalar
        d.rectangle((x, y, x + 120, y + 60), fill=c, outline=INK, width=10)
        for dx in (12, 108):
            d.ellipse((x + dx - 6, y + 10, x + dx + 6, y + 22), fill=INK)
    for x in (260, 560, 860, 1120):
        d.ellipse((x - 30, 430, x + 30, 490), fill=(255, 230, 100), outline=INK, width=8)
    d.polygon([(80, 470), (-10, 420), (-10, 520)], fill=(255, 150, 40) if not burn else (255, 80, 30))
    return im.resize((int(1400 * scale), int(800 * scale)), Image.LANCZOS)


def card(im, h):
    """Çift çözünürlükte çizilen karakteri hedef yüksekliğe indirir."""
    return im.resize((int(im.width * h / im.height), h), Image.LANCZOS)


# ------------------------------------------------------------------ arka planlar
def bg_garaj():
    im = Image.new("RGBA", (W, H), (52, 46, 58, 255)); d = ImageDraw.Draw(im)
    d.rectangle((0, 1250, W, H), fill=(70, 66, 72)); d.line((0, 1250, W, 1250), fill=INK, width=8)
    for i in range(6):  # raflar
        y = 220 + i * 150
        d.rectangle((40, y, 420, y + 18), fill=(110, 80, 60), outline=INK, width=4)
        for j in range(4):
            x = 60 + j * 90
            c = [(200, 60, 60), (60, 150, 200), (220, 190, 60), (90, 170, 90)][(i + j) % 4]
            d.rectangle((x, y - 70, x + 60, y), fill=c, outline=INK, width=4)
    for k in range(9):  # kablolar
        x0 = 460 + k * 70
        d.arc((x0 - 200, -200, x0 + 200, 500 + 30 * (k % 3)), 20, 160, fill=[(40, 40, 40), (200, 50, 50), (60, 90, 200)][k % 3], width=10)
    for x, y in ((120, 1330), (240, 1370), (930, 1320), (1010, 1400), (60, 1500)):  # bira kutuları
        d.rounded_rectangle((x, y, x + 50, y + 90), 10, fill=(60, 140, 200), outline=INK, width=5)
        d.rectangle((x, y + 30, x + 50, y + 55), fill=(235, 235, 235))
    d.rectangle((700, 120, 1040, 360), fill=(20, 20, 26), outline=INK, width=8)  # pencere: gece
    for _ in range(20):
        x, y = 700 + rng.integers(10, 330), 120 + rng.integers(10, 230)
        d.ellipse((x, y, x + 5, y + 5), fill=(255, 255, 230))
    d.ellipse((380, 30, 700, 120), fill=(255, 240, 180, 60))  # tavan lambası ışığı
    return im


def bg_gezegen():
    im = Image.new("RGBA", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):  # pembe-mor gökyüzü
        t = y / H
        d.line((0, y, W, y), fill=(int(255 - 90 * t), int(120 - 80 * t), int(200 - 60 * t), 255))
    for cx, cy, r in ((200, 300, 160), (520, 220, 200), (880, 330, 170), (300, 520, 140), (760, 560, 150)):  # pembe bulutlar
        d.ellipse((cx - r, cy - r * 0.55, cx + r, cy + r * 0.55), fill=(255, 190, 230, 200))
    d.ellipse((780, 80, 1000, 300), fill=(120, 255, 210), outline=INK, width=8)  # yeşil ay
    signs = ["SEKS ŞOP", "KULÜP 9", "♥ ÖZEL ♥", "FETİŞ AVM", "24 SAAT", "XOXO"]
    for i in range(7):  # neon binalar
        x0 = -40 + i * 170; hgt = 500 + (i * 137) % 400
        d.rectangle((x0, H - hgt - 300, x0 + 150, H), fill=(40, 20, 60), outline=INK, width=6)
        for wy in range(H - hgt - 260, H - 320, 70):
            for wx in (x0 + 20, x0 + 80):
                d.rectangle((wx, wy, wx + 36, wy + 36), fill=[(255, 80, 200), (80, 240, 255), (255, 230, 90)][(i + wy // 70) % 3])
        s = signs[i % len(signs)]
        f = font(30)
        tw = d.textlength(s, font=f)
        d.rounded_rectangle((x0 + 75 - tw / 2 - 12, H - hgt - 360, x0 + 75 + tw / 2 + 12, H - hgt - 312), 10,
                            fill=(20, 0, 30), outline=(255, 60, 200), width=5)
        d.text((x0 + 75 - tw / 2, H - hgt - 356), s, font=f, fill=(255, 140, 230))
    glow = im.filter(ImageFilter.GaussianBlur(6))
    return Image.blend(im, glow, 0.25)


def bg_kokpit(view):
    """Kokpit içi: camdan dış görünüm (bulanık) + gösterge paneli."""
    im = view.filter(ImageFilter.GaussianBlur(10)).copy(); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 180), fill=(60, 66, 76)); d.rectangle((0, 0, 60, H), fill=(60, 66, 76)); d.rectangle((W - 60, 0, W, H), fill=(60, 66, 76))
    return im


def panel(frame, alarm=False):
    im, d = canvas(W, 600)
    d.polygon([(0, 120), (W, 120), (W, 600), (0, 600)], fill=(70, 76, 86, 255), outline=INK)
    d.rectangle((0, 120, W, 150), fill=(50, 54, 62))
    for i in range(14):
        x = 70 + i * 70; y = 220 + (i % 3) * 60
        on = (frame // 6 + i) % 3 == 0
        c = (255, 60, 60) if alarm and on else [(80, 255, 140), (255, 210, 80), (90, 180, 255)][i % 3]
        d.ellipse((x, y, x + 36, y + 36), fill=c if on or not alarm else (90, 30, 30), outline=INK, width=5)
    d.rounded_rectangle((380, 380, 700, 560), 20, fill=(20, 40, 30), outline=INK, width=8)
    d.text((410, 430), "HDN-9" if not alarm else "TEHLİKE!", font=font(54), fill=(90, 255, 150) if not alarm else (255, 80, 80))
    return im


def portal_layer(r, phase, color=(120, 255, 90)):
    im, d = canvas(W, H)
    cx, cy = W // 2, 760
    for k in range(12, 0, -1):
        rr = r * k / 12
        a = int(70 + 15 * k)
        c = tuple(int(v * (0.4 + 0.6 * k / 12)) for v in color) + (a,)
        d.ellipse((cx - rr, cy - rr * 1.1, cx + rr, cy + rr * 1.1), fill=c)
    for k in range(5):  # sarmal
        ang = phase + k * 1.25
        x, y = cx + math.cos(ang) * r * 0.6, cy + math.sin(ang) * r * 0.66
        d.ellipse((x - r * 0.12, y - r * 0.12, x + r * 0.12, y + r * 0.12), fill=(200, 255, 170, 160))
    return im.filter(ImageFilter.GaussianBlur(4))


# ------------------------------------------------------------------ zaman çizelgesi
def timeline(lines):
    shots, t, li = [], 0.0, 0
    for name, pre, ls, post, ev in SHOTS:
        s0 = t; t += pre; items = []
        for spk, text in ls:
            ln = lines[li]; li += 1
            d = len(ln["audio"]) / SR
            items.append({**ln, "t0": t, "t1": t + d}); t += d + 0.15
        t += post
        events = [(e.split("@")[0], s0 + float(e.split("@")[1])) for e in ev]
        shots.append({"name": name, "t0": s0, "t1": t, "lines": items, "events": events})
    return shots, t


def speaking(shot, t):
    for ln in shot["lines"]:
        if ln["t0"] <= t < ln["t1"]:
            i = int((t - ln["t0"]) * SR); seg = ln["audio"][max(0, i - 600): i + 600]
            return ln, float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    return None, 0.0


def wrap(text, f, width, d):
    words, out, cur = text.split(), [], ""
    for w in words:
        if d.textlength((cur + " " + w).strip(), font=f) <= width:
            cur = (cur + " " + w).strip()
        else:
            out.append(cur); cur = w
    return out + [cur]


def subtitle(frame_im, ln, t):
    """Konuşan karakterin adıyla, o an söylenen cümle parçası (en çok 2 satır)."""
    d = ImageDraw.Draw(frame_im); f = font(54); fn = font(40)
    words = ln["text"].split(); dur = ln["t1"] - ln["t0"]
    k = min(len(words), int((t - ln["t0"]) / dur * len(words)) + 1)
    lines = wrap(ln["text"], f, W - 160, d)
    idx, acc = 0, 0
    for i, l in enumerate(lines):
        acc += len(l.split())
        if acc >= k:
            idx = i; break
    show = lines[(idx // 2) * 2:(idx // 2) * 2 + 2]
    y = 1480
    d.rounded_rectangle((60, y - 70, W - 60, y + 30 + 70 * len(show)), 30, fill=(10, 6, 16, 190))
    d.text((100, y - 58), ln["speaker"].upper(), font=fn, fill=COLOR[ln["speaker"]])
    for l in show:
        tw = d.textlength(l, font=f)
        d.text(((W - tw) / 2, y), l, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
        y += 70


def compose(shots, total):
    garaj, gez = bg_garaj(), bg_gezegen()
    kok = bg_kokpit(gez)
    cache = {}

    def C(key, fn, h):
        if key not in cache:
            cache[key] = card(fn(), h)
        return cache[key]

    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                           str(OUT / "video.mp4")], stdin=subprocess.PIPE)
    nfr = int(total * FPS)
    for fi in range(nfr):
        t = fi / FPS
        sh = next(s for s in shots if s["t0"] <= t < s["t1"] + 1e-6) if t < shots[-1]["t1"] else shots[-1]
        u = (t - sh["t0"]) / max(0.01, sh["t1"] - sh["t0"])
        ln, rms = speaking(sh, t)
        talk = lambda who: ln is not None and ln["speaker"] == who and rms > 0.02 and (fi // 3) % 2 == 0  # noqa: E731
        bob = math.sin(t * 6) * 6
        n = sh["name"]; zoom, shake = 1.0 + 0.05 * u, 0
        if n in ("garaj", "garaj_son", "dusus"):
            fr = garaj.copy()
            if n == "garaj":
                fr.alpha_composite(gemi(0.62), (430, 760))
                hold = "tornavida" if sh is shots[0] else "termos"
                angry = talk("Burak") or sh is shots[0]
                fr.alpha_composite(C(f"B{int(talk('Burak'))}{angry}{hold}", lambda: burak(talk("Burak"), "angry" if angry else "normal", hold), 900), (-60, 560 + int(bob)))
                fr.alpha_composite(C(f"K{int(talk('Kaan'))}", lambda: kaan(talk("Kaan"), "panik" if talk("Kaan") else "normal"), 820), (520, 640 - int(bob)))
                if sh is shots[0] and int(t * 3) % 2 == 0:
                    shake = 10
            elif n == "dusus":
                lu = min(1, (t - sh["t0"]) / 1.5)
                if lu < 1:
                    fr.alpha_composite(portal_layer(380 * (1 - lu * 0.6), t * 5), (0, -400))
                y = int(-900 + 1600 * lu ** 2)
                bk = C("Bfall", lambda: burak(True, "laugh", "bira"), 800).rotate(25 * lu, expand=True)
                kk = C("Kfall", lambda: kaan(True, "panik"), 760).rotate(-35 * lu, expand=True)
                fr.alpha_composite(bk, (40, min(800, y)))
                fr.alpha_composite(kk, (520, min(880, y - 120)))
                if 1.45 < t - sh["t0"] < 1.8:
                    shake = 22
            else:  # garaj_son: yerde
                kk = C(f"Klie{int(talk('Kaan'))}", lambda: kaan(talk("Kaan"), "normal"), 760).rotate(80, expand=True)
                bk = C(f"Bsit{int(talk('Burak'))}", lambda: burak(talk("Burak"), "laugh", "bira"), 820)
                fr.alpha_composite(kk, (W - kk.width - 10, 1180))
                fr.alpha_composite(bk, (-40, 520 + int(bob / 2)))
        elif n == "portal":
            fr = garaj.copy()
            r = 40 + 520 * min(1, u * 1.6)
            fr.alpha_composite(portal_layer(r, t * 4), (0, 0))
            s = max(0.05, 0.62 * (1 - max(0, u - 0.55) / 0.45))
            g = gemi(s); fr.alpha_composite(g, (int(W / 2 - g.width / 2), int(1100 - 340 * max(0, u - 0.55) / 0.45 - g.height / 2)))
            zoom = 1.0 + 0.15 * u
        elif n in ("gezegen", "kralice", "kovalamaca", "patlama"):
            off = int((t * 900) % 340) if n == "kovalamaca" else 0
            fr = gez.copy() if not off else Image.new("RGBA", (W, H))
            if off:
                fr.alpha_composite(gez, (-off, 0)); fr.alpha_composite(gez.transpose(Image.FLIP_LEFT_RIGHT), (W - off, 0))
            if n == "gezegen":
                if u < 0.5:
                    fr.alpha_composite(portal_layer(300 * (1 - u * 2), t * 4), (0, 0))
                g = gemi(0.2 + 0.4 * u); fr.alpha_composite(g, (int(W / 2 - g.width / 2), int(760 + 300 * u)))
            elif n == "kralice":
                q = C(f"Q{int(talk('Kraliçe'))}", lambda: kralice(talk("Kraliçe")), 1500)
                rise = min(1, (t - sh["t0"]) / 0.8)
                fr.alpha_composite(q, (int(W / 2 - q.width / 2) - 60, int(1900 - 1550 * rise ** 0.6)))
                g = gemi(0.3); fr.alpha_composite(g, (60, 1450))
                if rise < 1:
                    shake = 14
            elif n == "kovalamaca":
                g = gemi(0.55, burn=True)
                gx, gy = int(W / 2 - g.width / 2 + math.sin(t * 3) * 60), int(900 + math.sin(t * 5) * 40)
                fr.alpha_composite(g, (gx, gy))
                d = ImageDraw.Draw(fr)
                for k in range(3):  # lazerler (sabit tohumlu)
                    ph = (t * 2.3 + k * 0.37) % 1
                    if ph < 0.25:
                        y0 = 300 + ((k * 397 + int(t * 2.3)) * 211) % 1100
                        d.line((W, y0, W * (1 - ph * 4), y0 + 80), fill=(255, 60, 80), width=18)
                        d.line((W, y0, W * (1 - ph * 4), y0 + 80), fill=(255, 220, 230), width=6)
                if any(abs(t - et) < 0.12 for nm, et in sh["events"] if nm == "laser"):
                    shake = 8
                if ln is not None:  # konuşurken kokpit içi ek görüntü: köşede yüz
                    who = ln["speaker"]
                    face = C(f"{who}cam{int(talk(who))}", lambda: (burak(talk(who), "laugh", "bira") if who == "Burak" else kaan(talk(who), "panik")), 900).crop((0, 0, 560, 560))
                    fr.alpha_composite(Image.new("RGBA", (600, 600), COLOR[who] + (255,)), (W - 630, 170))
                    fr.alpha_composite(Image.new("RGBA", (580, 580), (40, 30, 60, 255)), (W - 620, 180))
                    fr.alpha_composite(face.resize((560, 560)), (W - 610, 190))
            else:  # patlama
                p = (t - sh["t0"]) / 3.4
                d = ImageDraw.Draw(fr)
                for k in range(5):
                    rr = 2400 * min(1, p * 1.6) * (1 - k * 0.15)
                    col = [(255, 250, 220), (255, 220, 120), (255, 160, 60), (240, 100, 30), (200, 60, 20)][k]
                    d.ellipse((W / 2 - rr, 1100 - rr, W / 2 + rr, 1100 + rr), fill=col + (int(230 - k * 25),))
                fr = Image.blend(fr, Image.new("RGBA", (W, H), (255, 140, 40, 255)), min(0.55, p))
                shake = int(30 * (1 - p))
                zoom = 1.0 + 0.2 * p
        elif n in ("kokpit", "kokpit_alarm"):
            fr = kok.copy()
            alarm = n == "kokpit_alarm"
            fr.alpha_composite(C(f"Bk{int(talk('Burak'))}{alarm}", lambda: burak(talk("Burak"), "angry" if alarm else "normal", "termos"), 1100), (-90, 700 + int(bob)))
            fr.alpha_composite(C(f"Kk{int(talk('Kaan'))}", lambda: kaan(talk("Kaan"), "panik"), 1000), (430, 760 - int(bob)))
            fr.alpha_composite(panel(fi, alarm), (0, 1320))
            if alarm and (fi // 8) % 2 == 0:
                fr = Image.blend(fr, Image.new("RGBA", (W, H), (255, 0, 0, 255)), 0.18)
        else:  # jenerik
            fr = Image.new("RGBA", (W, H), (0, 0, 0, 255)); d = ImageDraw.Draw(fr)
            p = (t - sh["t0"]) / 7
            if p > 0.12:
                ft = font(150, TITLE); s = "BURAK"
                for i, (txt, col, y) in enumerate((("BURAK", (255, 140, 50), 700), ("&", (255, 255, 255), 870), ("KAAN", (90, 220, 130), 1010))):
                    f2 = font(150 if txt != "&" else 110, TITLE)
                    tw = d.textlength(txt, font=f2)
                    wob = math.sin(t * 7 + i) * 8
                    d.text(((W - tw) / 2 + wob, y), txt, font=f2, fill=col, stroke_width=6, stroke_fill=(40, 0, 60))
                fs = font(40); s2 = "Bir Reels Fabrikası çizgi filmi"
                d.text(((W - d.textlength(s2, font=fs)) / 2, 1260), s2, font=fs, fill=(200, 200, 220))
            portal = portal_layer(120 + 30 * math.sin(t * 3), t * 4, (255, 90, 200))
            fr.alpha_composite(portal, (0, -560))
        if ln is not None:
            subtitle(fr, ln, t)
        if zoom != 1.0 or shake:
            dx = int(rng.integers(-shake, shake + 1)) if shake else 0
            dy = int(rng.integers(-shake, shake + 1)) if shake else 0
            cw, ch = int(W / zoom), int(H / zoom)
            x0 = max(0, min(W - cw, (W - cw) // 2 + dx)); y0 = max(0, min(H - ch, (H - ch) // 2 + dy))
            fr = fr.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
        if t > total - 0.6:  # sona doğru kararma
            fr = Image.blend(fr.convert("RGBA"), Image.new("RGBA", (W, H), (0, 0, 0, 255)), (t - (total - 0.6)) / 0.6)
        ff.stdin.write(fr.convert("RGB").tobytes())
        if fi % 300 == 0:
            print(f"kare {fi}/{nfr}", flush=True)
    ff.stdin.close(); ff.wait()


def mix(shots, total):
    n = int(total * SR); voice = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)
    quiet = []
    for sh in shots:
        for ln in sh["lines"]:
            i = int(ln["t0"] * SR); a = ln["audio"][: n - i]
            voice[i:i + len(a)] += a; quiet.append((ln["t0"] - 0.1, ln["t1"] + 0.2))
        for name, et in sh["events"]:
            s = load_sfx(name) * (0.5 if name not in ("boom", "laser") else 0.8)
            i = int(et * SR); s = s[: max(0, n - i)]
            fx[i:i + len(s)] += s
    jen = next(s["t0"] for s in shots if s["name"] == "jenerik")
    mus = music(total, {"quiet": quiet, "jenerik": jen})[:n]
    mus = np.pad(mus, (0, n - len(mus)))
    out = voice * 1.0 + fx * 0.7 + mus * 0.8
    out = out / max(1e-6, np.max(np.abs(out))) * 0.95
    with wave.open(str(OUT / "mix_raw.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((out * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(OUT / "mix_raw.wav"), "-af",
                    "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "2", str(OUT / "mix.wav")], check=True)


def srt(shots):
    def ts(x):
        h, r = divmod(x, 3600); m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
    rows, k = [], 1
    for sh in shots:
        for ln in sh["lines"]:
            rows.append(f"{k}\n{ts(ln['t0'])} --> {ts(ln['t1'])}\n{ln['speaker']}: {ln['text']}\n"); k += 1
    (OUT / "altyazi.srt").write_text("\n".join(rows), encoding="utf-8")


if __name__ == "__main__":
    lines = tts_all()
    shots, total = timeline(lines)
    print(f"süre {total:.1f} sn, {sum(len(s['lines']) for s in shots)} replik", flush=True)
    if "--sadece-ses" in sys.argv:
        sys.exit(0)
    mix(shots, total); srt(shots)
    if "--kareler" in sys.argv:  # hızlı kontrol: birkaç kare
        sys.exit(0)
    compose(shots, total)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(OUT / "video.mp4"), "-i", str(OUT / "mix.wav"), "-map", "0:v:0",
                    "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT / "burak_ve_kaan.mp4")], check=True)
    print("bitti", OUT / "burak_ve_kaan.mp4")
