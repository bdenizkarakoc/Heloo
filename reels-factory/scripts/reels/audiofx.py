"""Konuşma sesi iyileştirme (video sesi ve ses kayıtları için ortak).

Adımlar (her biri ölçüme göre uyarlanır, gereksizse atlanır):
  1. Analiz: gürültü tabanı, şebeke uğultusu (50/60 Hz ve harmonikleri), kırpılma (clipping), konuşma seviyesi.
  2. Onarım: kırpılma varsa adeclip, tıkırtı için adeclick, uğultu varsa yalnızca o frekanslara dar çentik.
  3. Gürültü azaltma: uyarlamalı spektral kapı (numpy). Her frekans bandının gürültü düzeyi kaydın en sessiz
     bölümlerinden öğrenilir; konuşma bölgeleri korunur, gürültü yalnızca belirlenen oranda bastırılır (yapay
     "robot" sesini önlemek için yumuşak maske ve zaman/frekansta yumuşatma). Gürültü yoksa dokunulmaz.
  4. Ton: 80 Hz altı kesilir, hafif çamur azaltma ve netlik (EQ), sibilans yumuşatma.
  5. Seviye: speechnorm ile cümleler arası seviye dengelenir, yumuşak kompresör, sınırlayıcı ve iki geçişli
     loudnorm (konuşma için -16 LUFS veya istenen hedef).

Güç: hafif / orta / güçlü (gürültü bastırma oranı ve dengeleme miktarı).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import log
from .util import StageError, load_audio, run, write_wav

L = log.get("audiofx")
SR = 48000

STRENGTH = {  # gürültü bastırma (dB), maske yumuşaklığı, speechnorm genişlemesi
    "hafif": {"reduce_db": 10, "thresh": 1.5, "expansion": 2.0, "comp_ratio": 2.0},
    "orta": {"reduce_db": 16, "thresh": 1.25, "expansion": 3.0, "comp_ratio": 2.5},
    "güçlü": {"reduce_db": 24, "thresh": 1.0, "expansion": 4.0, "comp_ratio": 3.0},
}


# ----------------------------------------------------------------------------
# Analiz
# ----------------------------------------------------------------------------

def _stft(x: np.ndarray, n: int = 2048, hop: int = 512) -> np.ndarray:
    win = np.hanning(n).astype(np.float32)
    pad = np.pad(x, (n // 2, n // 2 + n))
    frames = 1 + (len(pad) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.fft.rfft(pad[idx] * win, axis=1)


def _istft(S: np.ndarray, length: int, n: int = 2048, hop: int = 512) -> np.ndarray:
    win = np.hanning(n).astype(np.float32)
    frames = np.fft.irfft(S, n=n, axis=1) * win
    out = np.zeros(hop * (len(frames) - 1) + n, dtype=np.float64)
    norm = np.zeros_like(out)
    for i, f in enumerate(frames):
        out[i * hop:i * hop + n] += f
        norm[i * hop:i * hop + n] += win ** 2
    out /= np.maximum(norm, 1e-8)
    return out[n // 2:n // 2 + length].astype(np.float32)


def analyze(x: np.ndarray, sr: int = SR) -> dict:
    hop = int(sr * 0.02)
    n = len(x) // hop
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    floor = float(np.percentile(db, 10))
    speech = float(np.percentile(db, 90))
    clip = float((np.abs(x) > 0.985).mean())
    # uğultu: 50/60 Hz ve harmoniklerinin komşu bantlara göre belirginliği
    spec = np.abs(np.fft.rfft(x[: sr * 30] * np.hanning(min(len(x), sr * 30))))
    freqs = np.fft.rfftfreq(min(len(x), sr * 30), 1 / sr)
    hum = None
    for base in (50, 60):
        ratios = []
        for h in (1, 2, 3):
            f = base * h
            band = (freqs > f - 1.5) & (freqs < f + 1.5)
            near = ((freqs > f - 12) & (freqs < f - 4)) | ((freqs > f + 4) & (freqs < f + 12))
            if band.any() and near.any():
                ratios.append(float(20 * np.log10(spec[band].max() / (np.median(spec[near]) + 1e-9) + 1e-9)))
        if ratios and max(ratios) > 15:
            hum = {"base": base, "prominence_db": round(max(ratios), 1)}
            break
    return {"noise_floor_db": round(floor, 1), "speech_db": round(speech, 1), "snr_db": round(speech - floor, 1),
            "clipping": round(clip, 5), "hum": hum}


# ----------------------------------------------------------------------------
# Spektral kapı
# ----------------------------------------------------------------------------

def _noise_profile(x: np.ndarray, oversub: float, chunk: int) -> np.ndarray | None:
    """Gürültü gücü (frekans başına): kaydın en sessiz çerçevelerinden, uzun kayıtta parça parça."""
    powers, energies = [], []
    for i in range(0, len(x), chunk):
        P = np.abs(_stft(x[i:i + chunk])).astype(np.float32) ** 2
        powers.append(P)
        energies.append(10 * np.log10(P.mean(axis=1) + 1e-12))
    e = np.concatenate(energies)
    cut = np.percentile(e, 12)
    sel = [P[en <= cut] for P, en in zip(powers, energies)]
    q = np.concatenate([p for p in sel if len(p)]) if any(len(p) for p in sel) else None
    if q is None or len(q) < 5:
        return None
    return q.mean(axis=0) * oversub + 1e-12


def wiener_denoise(x: np.ndarray, sr: int, reduce_db: float, oversub: float = 1.5, alpha: float = 0.98,
                   chunk_sec: float = 60.0) -> np.ndarray:
    """Karar yönlendirmeli (decision-directed, Ephraim-Malah) Wiener gürültü azaltma.

    Gürültü gücü her frekans için kaydın en sessiz çerçevelerinden öğrenilir; her çerçevede önceki çerçevenin
    temiz tahminiyle a-priori SNR hesaplanır ve G = SNR/(1+SNR) kazancı uygulanır. Alt sınır (reduce_db)
    gürültüyü tamamen silmez; bu, "su altı/robot" artefaktını önler ve doğal bir arka plan bırakır.
    Uzun kayıtlar (20+ dk) 60 sn'lik örtüşen parçalarla işlenir (bellek sınırlı kalır)."""
    chunk = int(sr * chunk_sec)
    N = _noise_profile(x, oversub, chunk)
    if N is None:
        return x
    gmin = 10 ** (-reduce_db / 20)
    from numpy.lib.stride_tricks import sliding_window_view as sw

    def run_chunk(seg: np.ndarray) -> np.ndarray:
        S = _stft(seg)
        P = np.abs(S) ** 2
        G = np.empty(P.shape, dtype=np.float32)
        prev = np.zeros(P.shape[1])
        for t in range(P.shape[0]):
            post = P[t] / N
            prio = alpha * prev / N + (1 - alpha) * np.maximum(post - 1, 0)
            g = np.maximum(prio / (1 + prio), gmin)
            G[t] = g
            prev = (g ** 2) * P[t]
        G = sw(np.pad(G, ((0, 0), (1, 1)), mode="edge"), 3, axis=1).mean(axis=-1)  # müzikal gürültüye karşı
        return _istft(S * G, len(seg))

    if len(x) <= chunk * 1.5:
        return run_chunk(x)
    ov = sr  # 1 sn örtüşme, doğrusal geçiş
    out = np.zeros(len(x), dtype=np.float32)
    weight = np.zeros(len(x), dtype=np.float32)
    for i in range(0, len(x), chunk):
        a, b = max(0, i - ov), min(len(x), i + chunk + ov)
        y = run_chunk(x[a:b])
        w = np.ones(b - a, dtype=np.float32)
        if a > 0:
            w[:2 * ov] = np.linspace(0, 1, 2 * ov)
        if b < len(x):
            w[-2 * ov:] = np.minimum(w[-2 * ov:], np.linspace(1, 0, 2 * ov))
        out[a:b] += y * w
        weight[a:b] += w
    return out / np.maximum(weight, 1e-6)


def spectral_gate(x: np.ndarray, sr: int, reduce_db: float, thresh: float) -> np.ndarray:
    S = _stft(x)
    mag = np.abs(S)
    db = 20 * np.log10(mag + 1e-10)
    # gürültü profili: her bandın en sessiz %15'lik çerçevelerinin ortalaması ve yayılımı
    frame_energy = db.mean(axis=1)
    quiet = frame_energy <= np.percentile(frame_energy, 15)
    if quiet.sum() < 5:
        return x
    mu = db[quiet].mean(axis=0)
    sd = db[quiet].std(axis=0)
    threshold = mu + thresh * sd + 3.0
    # yumuşak maske: eşiğin altı bastırılır, üstü korunur; sigmoid geçiş
    soft = 1 / (1 + np.exp(-(db - threshold) / 2.0))
    # zaman (5 çerçeve) ve frekans (3 bant) yumuşatma — "su damlası" artefaktlarını engeller
    from numpy.lib.stride_tricks import sliding_window_view as sw
    k_t, k_f = 5, 3
    padded = np.pad(soft, ((k_t // 2, k_t // 2), (k_f // 2, k_f // 2)), mode="edge")
    soft = sw(padded, (k_t, k_f)).mean(axis=(-1, -2))
    floor_gain = 10 ** (-reduce_db / 20)
    gain = floor_gain + (1 - floor_gain) * soft
    return _istft(S * gain, len(x))


# ----------------------------------------------------------------------------
# Ana işlev
# ----------------------------------------------------------------------------

def _loudness(path: Path) -> dict:
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            check=False, quiet=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        raise StageError("ses seviyesi ölçülemedi")
    return json.loads(m.group(0))


def enhance(src: Path, dest: Path, strength: str = "orta", target_lufs: float = -16.0, sr: int = SR,
            normalize: bool = True, channels: int = 1) -> dict:
    """src (ses veya video) → dest (wav, mono, sr). Yapılanların raporunu döndürür."""
    cfg = STRENGTH.get(strength, STRENGTH["orta"])
    work = dest.with_suffix(".fx")
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "raw.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", str(sr), raw])
    x = load_audio(raw, sr, 1)
    if len(x) < sr * 0.3:
        raise StageError("ses çok kısa veya yok")
    info = analyze(x, sr)
    steps = []

    # 1) onarım + uğultu
    pre = ["highpass=f=70:p=2"]
    if info["clipping"] > 0.0005:
        pre.append("adeclip")
        steps.append("kırpılma onarımı")
    pre.append("adeclick=w=55:o=75")
    if info["hum"]:
        b = info["hum"]["base"]
        pre += [f"bandreject=f={b * h}:width_type=q:w=30" for h in (1, 2, 3, 4)]
        steps.append(f"{b} Hz uğultu temizlendi")
    stage1 = work / "s1.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", ",".join(pre), "-ar", str(sr), stage1])
    x = load_audio(stage1, sr, 1)

    # 2) gürültü azaltma (gürültü belirginse)
    if info["snr_db"] < 45:
        x = wiener_denoise(x, sr, cfg["reduce_db"])
        steps.append(f"gürültü azaltma ({strength}, gürültü tabanı {info['noise_floor_db']} dB)")
    stage2 = write_wav(work / "s2.wav", x, sr)

    # 3) ton + seviye dengeleme
    tone = ["equalizer=f=250:t=q:w=1.2:g=-2", "equalizer=f=3500:t=q:w=1.4:g=2.5",
            "equalizer=f=9000:t=h:w=2000:g=1", "deesser=i=0.3:m=0.5:f=0.5"]
    level = [f"speechnorm=e={cfg['expansion']}:r=0.0005:l=1:p=0.9",
             f"acompressor=threshold=-20dB:ratio={cfg['comp_ratio']}:attack=10:release=150:makeup=1.5:knee=4",
             "alimiter=limit=0.89:attack=3:release=60:level=false:latency=1"]
    stage3 = work / "s3.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", stage2, "-af", ",".join(tone + level), "-ar", str(sr), stage3])
    steps.append("netlik EQ + seviye dengeleme")

    # 4) iki geçişli loudness
    if normalize:
        m = _loudness(stage3)
        flt = (f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
               f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
               "linear=true")
        run(["ffmpeg", "-y", "-v", "error", "-i", stage3, "-af", flt, "-ar", str(sr), "-ac", str(channels), dest])
        steps.append(f"ses seviyesi {target_lufs} LUFS")
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", stage3, "-ac", str(channels), "-ar", str(sr), dest])
    for f in work.glob("*.wav"):
        f.unlink(missing_ok=True)
    work.rmdir()
    return {"analysis": info, "steps": steps, "strength": strength}


def enhance_media(src: Path, dest: Path, strength: str = "orta", target_lufs: float = -14.0) -> dict:
    """Ses veya video dosyasının sesini iyileştirir. Video ise görüntü aynen korunur (yeniden kodlanmaz)."""
    from .util import ffprobe
    info = ffprobe(src)
    has_video = any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1
                    for s in info["streams"])
    if not any(s.get("codec_type") == "audio" for s in info["streams"]):
        raise StageError("dosyada ses yok")
    wav = dest.with_suffix(".enh.wav")
    rep = enhance(src, wav, strength, target_lufs)
    if has_video:
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-i", wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", "-shortest", dest])
        wav.unlink(missing_ok=True)
    elif dest.suffix.lower() == ".wav":
        wav.replace(dest)
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-c:a", "libmp3lame" if dest.suffix.lower() == ".mp3" else "aac",
             "-b:a", "192k", dest])
        wav.unlink(missing_ok=True)
    rep["video"] = has_video
    return rep
