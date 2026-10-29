"""Kalite kontrolü ve otomatik düzeltmeler.

Her kontrol {name, ok, severity, detail} döndürür. severity: error (yayına engel) | warn.
Otomatik düzeltilebilenler (format, loudness, A/V süresi) düzeltilip yeniden ölçülür.
"""
from __future__ import annotations

import difflib
import re
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import log
from .audio import loudness, loudnorm_two_pass
from .config import Config
from .util import ffprobe, norm_word, run

L = log.get("qc")


def _check(name: str, ok: bool, detail: str = "", severity: str = "error", **extra) -> dict:
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail, **extra}


def probe_checks(path: Path, cfg: Config, expected_total: float) -> tuple[list[dict], dict]:
    info = ffprobe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    res = []
    res.append(_check("dosya_aciliyor", v is not None, "video akışı bulundu" if v else "video akışı yok"))
    if not v:
        return res, info
    W, H = cfg.get_path("output.width", 1080), cfg.get_path("output.height", 1920)
    res.append(_check("cozunurluk", (v["width"], v["height"]) == (W, H), f"{v['width']}x{v['height']}", fix="reencode"))
    res.append(_check("dikey_format", v["height"] > v["width"], f"{v['width']}x{v['height']}"))
    fps = float(Fraction(v.get("r_frame_rate", "0/1")))
    res.append(_check("kare_hizi", abs(fps - cfg.get_path("output.fps", 30)) < 0.01, f"{fps:.3f} fps", fix="reencode"))
    res.append(_check("video_codec", v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p",
                      f"{v.get('codec_name')} {v.get('pix_fmt')}", fix="reencode"))
    res.append(_check("ses_var", a is not None, a.get("codec_name", "") if a else "ses akışı yok"))
    if a:
        res.append(_check("ses_codec", a.get("codec_name") == "aac" and int(a.get("sample_rate", 0)) == 48000,
                          f"{a.get('codec_name')} {a.get('sample_rate')} Hz {a.get('channels')} kanal", fix="remux"))
        vd = float(v.get("duration") or info["format"]["duration"])
        ad = float(a.get("duration") or info["format"]["duration"])
        drift = abs(vd - ad)
        res.append(_check("av_sure_uyumu", drift <= cfg.get_path("qc.max_av_drift", 0.12),
                          f"video {vd:.2f} sn / ses {ad:.2f} sn (fark {drift:.3f})", fix="remux"))
    dur = float(info["format"]["duration"])
    res.append(_check("toplam_sure_beklenen", abs(dur - expected_total) < 0.25,
                      f"{dur:.2f} sn (beklenen {expected_total:.2f})"))
    dmin, dmax = cfg.get_path("output.duration.min", 30), cfg.get_path("output.duration.max", 60)
    hard = cfg.get_path("output.duration.hard_max", 90)
    sev = "error" if dur > hard or dur < dmin * 0.8 else "warn"
    res.append(_check("sure_araligi", dmin <= dur <= dmax, f"{dur:.1f} sn (hedef {dmin}-{dmax})", severity=sev))
    return res, info


def decode_check(path: Path) -> dict:
    proc = run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], check=False, quiet=True)
    errs = [l for l in proc.stderr.splitlines() if l.strip()]
    return _check("bozuk_kare_yok", proc.returncode == 0 and not errs,
                  "çözümleme temiz" if not errs else "; ".join(errs[:3]))


def black_frames(path: Path, cfg: Config) -> dict:
    d = cfg.get_path("qc.black_min_duration", 0.25)
    proc = run(["ffmpeg", "-hide_banner", "-i", path, "-vf", f"blackdetect=d={d}:pix_th=0.06", "-an",
                "-f", "null", "-"], check=False, quiet=True)
    spans = [(float(a), float(b)) for a, b in
             re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", proc.stderr)]
    return _check("siyah_ekran_yok", not spans,
                  "yok" if not spans else ", ".join(f"{a:.2f}-{b:.2f} sn" for a, b in spans), spans=spans)


def frozen_frames(path: Path, cfg: Config) -> dict:
    d = cfg.get_path("qc.freeze_min_duration", 3.0)
    proc = run(["ffmpeg", "-hide_banner", "-i", path, "-vf", f"freezedetect=n=0.0015:d={d}", "-an",
                "-f", "null", "-"], check=False, quiet=True)
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", proc.stderr)]
    durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", proc.stderr)]
    spans = list(zip(starts, durs))
    return _check("hareketsiz_bolum_yok", not spans,
                  "her sahnede hareket var" if not spans else
                  ", ".join(f"{s:.1f} sn'den itibaren {d:.1f} sn" for s, d in spans), severity="warn")


def silence_gaps(path: Path, cfg: Config, total: float) -> dict:
    mx = cfg.get_path("qc.silence_max", 1.2)
    proc = run(["ffmpeg", "-hide_banner", "-i", path, "-af", f"silencedetect=noise=-45dB:d={mx}", "-vn",
                "-f", "null", "-"], check=False, quiet=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    gaps = [s for s in starts if 0.5 < s < total - 2.5]
    return _check("gereksiz_sessizlik_yok", not gaps,
                  "yok" if not gaps else ", ".join(f"{s:.1f} sn" for s in gaps), severity="warn")


def loudness_check(path: Path, cfg: Config) -> dict:
    try:
        m = loudness(path)
        if float(m["input_i"]) < -70:
            raise ValueError
    except Exception:  # noqa: BLE001 — ses akışı yok ya da tamamen sessiz (müziksiz montaj)
        return _check("ses_seviyesi", True, "sessiz video (müzik/konuşma yok)", severity="warn")
    target = cfg.get_path("audio.target_lufs", -14)
    tol = cfg.get_path("qc.loudness_tolerance", 1.5)
    tp_max = cfg.get_path("audio.true_peak", -1.5) + 0.5
    ok = abs(m["input_i"] - target) <= tol and m["input_tp"] <= tp_max
    return _check("ses_seviyesi", ok, f"{m['input_i']:.1f} LUFS (hedef {target}), true peak {m['input_tp']:.1f} dBTP",
                  fix="loudness", lufs=m["input_i"], tp=m["input_tp"])


def ending_check(timeline: dict, words_abs: list[dict], total: float) -> dict:
    last_end = max(w["end"] for w in words_abs) if words_abs else 0
    margin = total - last_end
    return _check("son_bolum_tam", margin >= 0.8,
                  f"son kelime {last_end:.2f} sn'de bitiyor; video {total:.2f} sn (pay {margin:.2f} sn)")


def asr_checks(path: Path, script: dict, words_abs: list[dict], cfg: Config, work: Path) -> list[dict]:
    """Konuşma tanıma ile anlaşılırlık (WER) ve altyazı-ses senkronu."""
    if not cfg.get_path("qc.asr_check", True):
        return []
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [_check("anlasilirlik_asr", True, "faster-whisper kurulu değil; atlandı", severity="warn",
                       skipped=True)]
    wav = work / "qc_audio.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", wav])
    try:
        from .studio import whisper_model   # önbellekli; kart varsa kartta
        model, _gpu = whisper_model(cfg)
        from .util import load_audio
        segs, _ = model.transcribe(load_audio(wav, 16000, 1), language="tr", word_timestamps=True,
                                   beam_size=5, vad_filter=True)
        asr = [{"text": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in (s.words or [])]
    except Exception as exc:  # model indirilemezse vb.
        return [_check("anlasilirlik_asr", True, f"ASR çalıştırılamadı: {exc}", severity="warn", skipped=True)]
    ref = [norm_word(w["text"]) for w in words_abs if norm_word(w["text"])]
    hyp = [norm_word(w["text"]) for w in asr if norm_word(w["text"])]
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    wer = 1 - matched / max(1, len(ref))
    # Eşleşen kelimelerde altyazı başlangıcı ile ASR başlangıcı arasındaki fark
    ref_words = [w for w in words_abs if norm_word(w["text"])]
    hyp_words = [w for w in asr if norm_word(w["text"])]
    offsets = []
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            offsets.append(abs(ref_words[blk.a + k]["start"] - hyp_words[blk.b + k]["start"]))
    offsets.sort()
    med = offsets[len(offsets) // 2] if offsets else 0.0
    p90 = offsets[int(len(offsets) * 0.9)] if offsets else 0.0
    max_wer = cfg.get_path("qc.max_wer", 0.25)
    max_off = cfg.get_path("qc.max_caption_offset", 0.35)
    (work / "asr.txt").write_text(" ".join(w["text"] for w in asr), encoding="utf-8")
    return [
        _check("anlasilirlik_asr", wer <= max_wer,
               f"kelime eşleşme hatası (WER≈) {wer:.0%} — {len(hyp)}/{len(ref)} kelime tanındı", severity="warn",
               wer=round(wer, 3)),
        _check("altyazi_ses_senkronu", med <= max_off,
               f"medyan sapma {med * 1000:.0f} ms, %90: {p90 * 1000:.0f} ms ({len(offsets)} kelime)",
               severity="warn", median_offset=round(med, 3)),
    ]


def contact_sheet(path: Path, dest: Path, every: float, total: float, font_path: Path) -> Path:
    """Her N saniyede bir kare: görsel inceleme (senaryo uyumu, okunabilirlik) için."""
    frames_dir = dest.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for f in frames_dir.glob("*.jpg"):
        f.unlink()
    times = [round(t, 2) for t in frange(0.1, total - 0.05, every)] + [round(total - 0.1, 2)]
    for i, t in enumerate(times):
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", path, "-frames:v", "1", "-vf", "scale=270:480",
             frames_dir / f"f{i:03d}.jpg"])
    files = sorted(frames_dir.glob("*.jpg"))
    cols = 8
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 270, rows * 510), (14, 16, 22))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(font_path), 22)
    except OSError:
        font = ImageFont.load_default()
    for i, (f, t) in enumerate(zip(files, times)):
        x, y = (i % cols) * 270, (i // cols) * 510
        with Image.open(f) as im:
            sheet.paste(im, (x, y))
        draw.text((x + 8, y + 484), f"{t:.1f} sn", fill=(255, 210, 63), font=font)
    sheet.save(dest, quality=85)
    return dest


def frange(a: float, b: float, step: float):
    t = a
    while t < b:
        yield t
        t += step


# ----------------------------------------------------------------------------
# Otomatik düzeltmeler
# ----------------------------------------------------------------------------

def fix_reencode(path: Path, cfg: Config) -> Path:
    tmp = path.with_name(path.stem + "_fix.mp4")
    W, H, fps = cfg.get_path("output.width"), cfg.get_path("output.height"), cfg.get_path("output.fps")
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf",
         f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps}",
         "-c:v", "libx264", "-preset", cfg.get_path("output.preset", "medium"), "-crf",
         str(cfg.get_path("output.crf", 18)), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a",
         cfg.get_path("output.audio_bitrate", "192k"), "-ar", "48000", "-ac", "2", "-movflags", "+faststart", tmp])
    tmp.replace(path)
    return path


def fix_loudness(path: Path, cfg: Config, work: Path) -> Path:
    src = work / "qc_fix_src.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "48000", src])
    fixed = loudnorm_two_pass(src, work / "qc_fix_norm.wav", cfg)
    tmp = path.with_name(path.stem + "_fix.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-i", fixed, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", cfg.get_path("output.audio_bitrate", "192k"), "-ar", "48000",
         "-movflags", "+faststart", "-shortest", tmp])
    tmp.replace(path)
    return path


def fix_remux(path: Path, cfg: Config, total: float) -> Path:
    tmp = path.with_name(path.stem + "_fix.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", path, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
         "-af", f"apad,atrim=0:{total:.3f}", "-c:a", "aac", "-b:a", cfg.get_path("output.audio_bitrate", "192k"),
         "-ar", "48000", "-ac", "2", "-t", f"{total:.3f}", "-movflags", "+faststart", tmp])
    tmp.replace(path)
    return path


def run_qc(path: Path, cfg: Config, timeline: dict, words_abs: list[dict], script: dict, work: Path,
           font_path: Path, zone_problems: list[str], autofix: bool = True) -> dict:
    total = timeline["total"]
    fixes: list[str] = []
    for attempt in range(3):
        checks, _ = probe_checks(path, cfg, total)
        checks.append(loudness_check(path, cfg))
        failing = {c.get("fix") for c in checks if not c["ok"] and c.get("fix")}
        if not autofix or not failing or attempt == 2:
            break
        if "reencode" in failing:
            fix_reencode(path, cfg)
            fixes.append("yeniden kodlama (çözünürlük/fps/codec)")
        if "remux" in failing:
            fix_remux(path, cfg, total)
            fixes.append("ses/video süresi eşitlendi")
        if "loudness" in failing:
            fix_loudness(path, cfg, work)
            fixes.append("loudness yeniden normalize edildi")
    checks.append(decode_check(path))
    checks.append(black_frames(path, cfg))
    checks.append(frozen_frames(path, cfg))
    checks.append(silence_gaps(path, cfg, total))
    checks.append(ending_check(timeline, words_abs, total))
    checks.append(_check("guvenli_alan", not zone_problems,
                         "bütün yazılar platform arayüzlerinin dışında" if not zone_problems
                         else "; ".join(zone_problems[:5])))
    checks += asr_checks(path, script, words_abs, cfg, work)
    sheet = contact_sheet(path, work / "contact_sheet.jpg", cfg.get_path("qc.contact_sheet_every", 2.0),
                          total, font_path)
    errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warns = [c for c in checks if not c["ok"] and c["severity"] != "error"]
    return {"passed": not errors, "errors": len(errors), "warnings": len(warns), "fixes": fixes,
            "checks": checks, "contact_sheet": str(sheet),
            "manual_review": "Kontak tablosunu inceleyin: görseller senaryoyla uyumlu mu, yazılar okunaklı mı?"}
