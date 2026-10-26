"""Müzik, ses efektleri ve miksaj.

Telif güvenliği:
  * library    : assets/music/ içindeki, licenses.yaml'da lisansı kayıtlı parçalar
  * openverse  : yalnızca CC0 / CC BY lisanslı müzik; atıf bilgisi credits.json'a yazılır
  * procedural : bu sistemin ürettiği ambiyans (telif sorunu yoktur)
Efektler: HyperFrames paketiyle gelen Pixabay lisanslı kütüphane veya assets/sfx/.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import yaml

from . import log
from .config import Config, ROOT
from .util import (StageError, TransientError, db_to_gain, download, http_json, load_audio, retry,
                   run, write_wav)

L = log.get("audio")
SR = 48000
AUDIO_EXT = (".mp3", ".wav", ".ogg", ".m4a", ".flac")


# ----------------------------------------------------------------------------
# Ölçüm
# ----------------------------------------------------------------------------

def loudness(path: Path) -> dict:
    """ffmpeg loudnorm ile entegre loudness (LUFS), true peak ve LRA ölçümü."""
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], quiet=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        raise StageError("loudness ölçülemedi")
    d = json.loads(m.group(0))
    return {k: float(v) for k, v in d.items() if k.startswith("input_") or k == "target_offset"}


def lufs_of_array(data: np.ndarray, tmp: Path) -> float:
    write_wav(tmp, data, SR)
    val = loudness(tmp)["input_i"]
    tmp.unlink(missing_ok=True)
    return val


def gain_to_lufs(data: np.ndarray, target: float, tmp: Path) -> np.ndarray:
    cur = lufs_of_array(data, tmp)
    if not np.isfinite(cur) or cur < -70:
        return data
    return data * db_to_gain(target - cur)


# ----------------------------------------------------------------------------
# Seslendirme izi
# ----------------------------------------------------------------------------

def build_voice_track(script: dict, timeline: dict, voice_dir: Path, work: Path, cfg: Config) -> Path:
    total = timeline["total"]
    buf = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for row in timeline["scenes"]:
        clip = load_audio(voice_dir / f"{row['id']}.wav", SR, 1)
        i0 = int(row["voice_start"] * SR)
        buf[i0:i0 + len(clip)] += clip[: max(0, len(buf) - i0)]
    buf = buf[: int(total * SR)]
    raw = write_wav(work / "voice_raw.wav", buf, SR)
    # Hafif temizlik: düşük frekans gürültüsünü kes, dinamikleri yumuşat.
    proc = work / "voice_proc.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af",
         "highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=1.5",
         "-ar", str(SR), "-ac", "1", proc])
    data = load_audio(proc, SR, 1)[: int(total * SR)]
    data = gain_to_lufs(data, float(cfg.get_path("audio.voice_lufs", -16)), work / "_tmp.wav")
    return write_wav(work / "voice.wav", data, SR)


# ----------------------------------------------------------------------------
# Müzik sağlayıcıları
# ----------------------------------------------------------------------------

def _music_library(cfg: Config, queries: list[str], work: Path, used: set[str]) -> dict | None:
    folder = ROOT / "assets" / "music"
    lic_file = folder / "licenses.yaml"
    if not lic_file.exists():
        return None
    entries = (yaml.safe_load(lic_file.read_text(encoding="utf-8")) or {}).get("tracks", [])
    allowed = set(cfg.get_path("music.license_allow", ["cc0", "by"])) | {"owned", "licensed", "royalty-free"}
    cands = []
    for e in entries:
        f = folder / str(e.get("file", ""))
        if not f.exists() or str(e.get("license", "")).lower() not in allowed:
            continue
        moods = " ".join(e.get("mood", [])).lower()
        score = sum(1 for q in queries for w in q.lower().split() if w in moods)
        cands.append((score, f.name in used, f, e))
    if not cands:
        return None
    cands.sort(key=lambda x: (-x[0], x[1]))
    _, _, f, e = cands[0]
    return {"path": f, "provider": "library", "title": e.get("title", f.stem),
            "license": e.get("license"), "credit": e.get("credit", ""), "source": e.get("source", "")}


def _looks_vocal(path: Path) -> bool:
    """faster-whisper kuruluysa şarkı sözü/konuşma içeren parçaları eler."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return False
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(load_audio(path, 16000, 1)[16000 * 20: 16000 * 60], vad_filter=True,
                                   beam_size=1)
        words = 0
        for s in segs:
            if s.no_speech_prob < 0.5 and s.avg_logprob > -0.8:
                words += len(s.text.split())
        return words >= 6
    except Exception as exc:  # model indirilemezse kontrolü atla
        L.debug("vokal kontrolü atlandı: %s", exc)
        return False


def _music_openverse(cfg: Config, queries: list[str], work: Path, used: set[str]) -> dict | None:
    allowed = ",".join(cfg.get_path("music.license_allow", ["cc0", "by"]))
    reject = [w.lower() for w in cfg.get_path("music.reject_title_words", [])]
    min_ms = 1000 * float(cfg.get_path("music.min_track_seconds", 40))
    for q in queries:
        try:
            data = retry(3, 2.0)(http_json)(
                "GET", "https://api.openverse.org/v1/audio/",
                params={"q": q, "license": allowed, "category": "music", "page_size": 20})
        except (StageError, TransientError) as exc:
            L.warning("Openverse müzik araması başarısız (%s): %s", q, exc)
            continue
        for r in data.get("results", []):
            title = (r.get("title") or "").lower()
            if r.get("url") in used or any(w in title for w in reject):
                continue
            if (r.get("duration") or 0) < min_ms or r.get("license") not in allowed.split(","):
                continue
            ext = (r.get("filetype") or "mp3").replace("mp32", "mp3")
            dest = work / f"music_openverse.{ext if ext in ('mp3', 'ogg', 'wav', 'flac') else 'mp3'}"
            try:
                retry(3, 2.0)(download)(r["url"], dest, max_mb=40)
            except (StageError, TransientError) as exc:
                L.warning("müzik indirilemedi: %s", exc)
                continue
            if _looks_vocal(dest):
                L.info("vokal içerdiği için elendi: %s", r.get("title"))
                continue
            return {"path": dest, "provider": "openverse", "title": r.get("title"),
                    "license": f"CC {r.get('license', '').upper()} {r.get('license_version', '')}".strip(),
                    "credit": r.get("attribution") or f"\"{r.get('title')}\" — {r.get('creator')}",
                    "source": r.get("foreign_landing_url") or r.get("url"), "url": r.get("url")}
    return None


def _music_procedural(cfg: Config, queries: list[str], work: Path, used: set[str], seconds: float) -> dict:
    """Telifsiz, yumuşak ambiyans pad'i (konuşmanın altında kalacak şekilde sade)."""
    rng = np.random.default_rng(7)
    n = int((seconds + 4) * SR)
    t = np.arange(n) / SR
    out = np.zeros((n, 2), dtype=np.float32)
    # La minör: Am - F - C - G (i - VI - III - VII)
    chords = [[57, 60, 64], [53, 57, 60], [48, 55, 60], [55, 59, 62]]
    span = 6.0

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    k = 0
    start = 0.0
    while start < seconds + 4:
        notes = chords[k % len(chords)]
        a, b = int(start * SR), min(n, int((start + span + 2.5) * SR))
        tt = t[a:b] - start
        env = np.minimum(1.0, tt / 1.6) * np.clip((span + 2.5 - tt) / 2.5, 0, 1)
        for ch, det in ((0, -0.0018), (1, 0.0018)):
            sig = np.zeros_like(tt)
            for m in notes:
                f = hz(m) * (1 + det)
                for h, amp in ((1, 1.0), (2, 0.35), (3, 0.12)):
                    sig += amp * np.sin(2 * np.pi * f * h * tt + rng.uniform(0, 6.28))
            sig += 0.6 * np.sin(2 * np.pi * hz(notes[0] - 24) * tt)  # bas
            out[a:b, ch] += (0.06 * env * sig).astype(np.float32)
        start += span
        k += 1
    trem = 0.85 + 0.15 * np.sin(2 * np.pi * 0.11 * t)
    out *= trem[:, None].astype(np.float32)
    raw = write_wav(work / "music_proc_raw.wav", out, SR)
    dest = work / "music_procedural.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af",
         "lowpass=f=2400,aecho=0.8:0.6:70|110:0.30|0.22", "-ar", str(SR), "-ac", "2", dest])
    return {"path": dest, "provider": "procedural", "title": "Prosedürel ambiyans (Reels Factory)",
            "license": "owned", "credit": "", "source": "generated"}


def pick_music(cfg: Config, queries: list[str], work: Path, seconds: float, used: set[str]) -> dict | None:
    for name in cfg.get_path("music.provider_chain", ["library", "openverse", "procedural"]):
        try:
            if name == "library":
                res = _music_library(cfg, queries, work, used)
            elif name == "openverse":
                res = _music_openverse(cfg, queries, work, used)
            elif name == "procedural":
                res = _music_procedural(cfg, queries, work, used, seconds)
            else:
                continue
        except (StageError, TransientError) as exc:
            L.warning("müzik sağlayıcısı %s başarısız: %s", name, exc)
            continue
        if res:
            return res
    return None


def _strong_offset(data: np.ndarray) -> float:
    """Sessiz/zayıf girişi atlayıp parçanın dolu bir bölümünden başla."""
    mono = data.mean(axis=1) if data.ndim > 1 else data
    win = SR
    n = len(mono) // win
    if n < 4:
        return 0.0
    rms = np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
    target = 0.7 * np.median(rms)
    limit = int(n * 0.35)
    for i in range(limit):
        if rms[i] >= target and rms[i:i + 3].min() >= 0.5 * target:
            return float(i)
    return 0.0


def build_music_bed(music: dict, voice_wav: Path, total: float, work: Path, cfg: Config) -> Path:
    data = load_audio(Path(music["path"]), SR, 2)
    off = _strong_offset(data)
    music["offset"] = off
    data = data[int(off * SR):]
    need = int(total * SR)
    xf = int(2.0 * SR)
    while len(data) < need:  # kısa parçayı çapraz geçişle döngüle
        if len(data) <= 2 * xf:
            data = np.concatenate([data, data])
            continue
        ramp = np.linspace(0, 1, xf)[:, None]
        joined = data[-xf:] * (1 - ramp) + data[:xf] * ramp
        data = np.concatenate([data[:-xf], joined, data[xf:]])
    data = data[:need].astype(np.float32)
    data = gain_to_lufs(data, float(cfg.get_path("audio.voice_lufs", -16)), work / "_tmp.wav")

    # Konuşmaya göre otomatik kısma (ducking) zarfı
    voice = load_audio(voice_wav, SR, 1)[:need]
    hop = int(SR * 0.01)
    frames = len(voice) // hop
    rms = np.sqrt((voice[: frames * hop].reshape(frames, hop) ** 2).mean(axis=1) + 1e-12)
    active = 20 * np.log10(rms) > -40
    pre, post = 12, 30  # 0.12 sn önce kıs, 0.30 sn sonra aç
    act = active.copy()
    for i in np.where(active)[0]:
        act[max(0, i - pre): i + post] = True
    bed_db = float(cfg.get_path("music.bed_gain_db", -8))
    duck_db = float(cfg.get_path("music.duck_gain_db", -17))
    target_db = np.where(act, duck_db, bed_db)
    g = np.empty(frames)
    cur = bed_db
    for i in range(frames):
        coef = 0.25 if target_db[i] < cur else 0.03   # hızlı kıs, yavaş aç
        cur += (target_db[i] - cur) * coef
        g[i] = cur
    gain = np.repeat(10 ** (g / 20), hop)
    gain = np.pad(gain, (0, max(0, need - len(gain))), mode="edge")[:need]
    data *= gain[:, None].astype(np.float32)
    fi, fo = float(cfg.get_path("music.fade_in", 0.8)), float(cfg.get_path("music.fade_out", 1.6))
    data[: int(fi * SR)] *= np.linspace(0, 1, int(fi * SR))[:, None]
    data[-int(fo * SR):] *= np.linspace(1, 0, int(fo * SR))[:, None]
    return write_wav(work / "music_bed.wav", data, SR)


# ----------------------------------------------------------------------------
# Ses efektleri
# ----------------------------------------------------------------------------

def sfx_library(cfg: Config) -> dict[str, Path]:
    lib: dict[str, Path] = {}
    for d in cfg.get_path("sfx.library_dirs", []):
        folder = ROOT / d
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.suffix.lower() in AUDIO_EXT:
                lib.setdefault(f.stem.lower(), f)
    return lib


def build_sfx_track(events: list[dict], total: float, work: Path, cfg: Config) -> tuple[Path | None, list[dict]]:
    if not cfg.get_path("sfx.enabled", True) or not events:
        return None, []
    lib = sfx_library(cfg)
    if not lib:
        L.warning("SFX kütüphanesi bulunamadı (npm install çalıştırıldı mı?) — efektsiz devam")
        return None, []
    base_db = float(cfg.get_path("sfx.gain_db", -7))
    need = int(total * SR)
    buf = np.zeros(need, dtype=np.float32)
    placed = []
    cache: dict[str, np.ndarray] = {}
    for ev in events:
        f = lib.get(ev["name"].lower())
        if f is None:
            continue
        if ev["name"] not in cache:
            snd = load_audio(f, SR, 1)
            peak = float(np.abs(snd).max() or 1.0)
            cache[ev["name"]] = snd / peak * db_to_gain(-3)
        snd = cache[ev["name"]]
        if ev.get("trim_tail"):  # yalnızca son kısmı (ör. riser'ın tepe noktası)
            snd = snd[-int(ev["trim_tail"] * SR):].copy()
            fade = int(0.3 * SR)
            snd[:fade] *= np.linspace(0, 1, fade)
        t = float(ev["time"])
        if ev.get("align") == "end":
            t -= len(snd) / SR
        i0 = int(max(0.0, t) * SR)
        if i0 >= need:
            continue
        seg = snd[: need - i0] * db_to_gain(base_db + float(ev.get("gain_db", 0)))
        buf[i0:i0 + len(seg)] += seg
        placed.append({"name": ev["name"], "time": round(t, 3), "file": f.name})
    return write_wav(work / "sfx.wav", buf, SR), placed


# ----------------------------------------------------------------------------
# Son miks
# ----------------------------------------------------------------------------

def final_mix(voice_wav: Path, music_wav: Path | None, sfx_wav: Path | None, total: float,
              work: Path, cfg: Config) -> Path:
    need = int(total * SR)
    mix = np.zeros((need, 2), dtype=np.float32)
    v = load_audio(voice_wav, SR, 1)[:need]
    mix[: len(v)] += v[:, None]
    if music_wav:
        m = load_audio(music_wav, SR, 2)[:need]
        mix[: len(m)] += m
    if sfx_wav:
        s = load_audio(sfx_wav, SR, 1)[:need]
        mix[: len(s)] += s[:, None]
    pre = write_wav(work / "mix_pre.wav", mix, SR)
    return loudnorm_two_pass(pre, work / "mix.wav", cfg)


def loudnorm_two_pass(src: Path, dest: Path, cfg: Config) -> Path:
    I = float(cfg.get_path("audio.target_lufs", -14))
    TP = float(cfg.get_path("audio.true_peak", -1.5))
    LRA = float(cfg.get_path("audio.lra", 11))
    m = loudness(src)
    flt = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
           f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
           f"offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", flt, "-ar", str(SR), "-ac", "2", dest])
    return dest


def mux(video: Path, audio: Path, dest: Path, cfg: Config) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio, "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", cfg.get_path("output.audio_bitrate", "192k"),
         "-ar", str(cfg.get_path("output.audio_rate", 48000)), "-ac", "2",
         "-movflags", "+faststart", "-shortest", dest])
    return dest
