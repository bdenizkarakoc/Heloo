"""Video Stüdyosu: referans videodan stil öğrenme ve kullanıcının kendi videosunu o stille düzenleme.

1) Stil öğren: referans videonun kesim hızı, renkleri, hareketi, konuşma/müzik yapısı ölçülür; kareler
   Claude'a (bilgisayardaki Claude Code veya Claude API) gösterilip altyazı/başlık/efekt stili çıkarılır.
   Kullanıcı stile bir ad verir → studio/styles/<ad>.json.
2) Videomu düzenle: video (herhangi bir uzunluk) yazıya dökülür; ya en iyi anlar kısa kliplere ayrılır ya da
   tamamı düzenlenir. Boşluklar kesilir, stil uygulanır. İsteğe bağlı iyileştirme turunda Claude çıktının
   karelerini referansla karşılaştırıp stili düzeltir ve klip yeniden üretilir; iyileşen stil kaydedilir.

Claude yoksa ölçümlere dayalı kurallar kullanılır ve bu durum projeye not edilir.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import log, qc
from .config import ROOT, Config, load_config
from .llm import _client, available, claude_cli, extract_json, resolve_provider
from .studio_render import DEFAULT_STYLE, full_style, render_clip, write_srt
from .util import StageError, ffprobe, load_audio, read_json, run, slugify, write_json

L = log.get("studio")
BASE = ROOT / "studio"
UPLOADS, STYLES, PROJECTS = BASE / "uploads", BASE / "styles", BASE / "projects"
BUILTIN_STYLES = ROOT / "assets" / "styles"
OUT = ROOT / "output" / "studio"
FONT = ROOT / "assets" / "fonts" / "Montserrat-VariableFont_wght.ttf"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".3gp", ".mts", ".m2ts", ".ts", ".wmv", ".flv"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".amr", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff"}
ANALYZE_SECONDS = 180  # referansın ilk 3 dakikası stil için yeterli


def plain(obj):
    """numpy sayı/bool türlerini JSON'a uygun Python türlerine çevirir."""
    return json.loads(json.dumps(obj, default=lambda x: x.item() if hasattr(x, "item") else str(x)))


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Projeler
# ----------------------------------------------------------------------------

def new_project(kind: str, source: Path | None, options: dict | None = None, url: str | None = None) -> dict:
    pid = f"st-{dt.datetime.now():%Y%m%d-%H%M%S}-{kind[:3]}"
    d = PROJECTS / pid
    d.mkdir(parents=True, exist_ok=True)
    proj = {"id": pid, "kind": kind, "source": str(source.relative_to(ROOT)) if source else None,
            "source_name": source.name if source else url, "url": url,
            "options": options or {}, "status": "queued", "stage": "sırada", "created": now(), "notes": []}
    write_json(d / "project.json", proj)
    return proj


def load_project(pid: str) -> dict:
    p = PROJECTS / pid / "project.json"
    if not p.exists():
        raise StageError(f"proje yok: {pid}")
    return read_json(p)


def save_project(proj: dict) -> None:
    proj["updated"] = now()
    write_json(PROJECTS / proj["id"] / "project.json", proj)


def set_stage(proj: dict, stage: str) -> None:
    proj["stage"] = stage
    L.info("[%s] %s", proj["id"], stage)
    save_project(proj)


def list_projects(limit: int = 30) -> list[dict]:
    items = [read_json(p) for p in PROJECTS.glob("*/project.json")]
    return sorted(items, key=lambda p: p.get("created", ""), reverse=True)[:limit]


# ----------------------------------------------------------------------------
# Stiller
# ----------------------------------------------------------------------------

def list_styles() -> list[dict]:
    out = []
    for folder, builtin in ((BUILTIN_STYLES, True), (STYLES, False)):
        for f in sorted(folder.glob("*.json")) if folder.exists() else []:
            s = read_json(f, {}) or {}
            out.append({"slug": f.stem, "name": s.get("name", f.stem), "description": s.get("description", ""),
                        "builtin": builtin, "version": s.get("version", 1), "effects": s.get("effects", []),
                        "reference_sheet": s.get("reference_sheet")})
    return out


def get_style(slug: str) -> dict:
    for folder in (STYLES, BUILTIN_STYLES):
        f = folder / f"{slug}.json"
        if f.exists():
            return read_json(f)
    if slug in ("", "fabrika", None):
        return dict(DEFAULT_STYLE)
    raise StageError(f"stil bulunamadı: {slug}")


def save_style(style: dict, name: str, slug: str | None = None, backup: bool = False) -> dict:
    slug = slug or slugify(name, 40)
    STYLES.mkdir(parents=True, exist_ok=True)
    dest = STYLES / f"{slug}.json"
    if backup and dest.exists():  # iyileştirmeden önceki sürüm saklanır (kullanıcının stili kaybolmaz)
        old = read_json(dest)
        shutil.copy(dest, STYLES / f"{slug}.v{old.get('version', 1)}.json.bak")
    style = {**style, "name": name, "slug": slug, "updated": now()}
    write_json(dest, style)
    return style


# ----------------------------------------------------------------------------
# Claude (bilgisayardaki Claude Code veya API) — görsel destekli JSON yanıt
# ----------------------------------------------------------------------------

def ai_mode(cfg: Config) -> str:
    p = resolve_provider(cfg)
    return p if p in ("anthropic", "claude_cli") else "none"


def ask_ai(cfg: Config, prompt: str, images: list[Path], out_file: Path, timeout: int = 900) -> dict | None:
    mode = ai_mode(cfg)
    if mode == "claude_cli":
        exe = claude_cli()
        rel = [str(p.relative_to(ROOT)) for p in images]
        full = (prompt + "\n\nÖnce şu görüntüleri Read aracıyla aç ve incele:\n" + "\n".join(f"- {r}" for r in rel)
                + f"\n\nSonucu YALNIZCA geçerli JSON olarak `{out_file.relative_to(ROOT)}` dosyasına Write ile yaz."
                  " Başka dosyaya dokunma, komut çalıştırma.")
        out_file.unlink(missing_ok=True)
        try:
            proc = subprocess.run([exe, "-p", full, "--permission-mode", "acceptEdits", "--allowedTools", "Read",
                                   "Write"], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            L.warning("Claude Code zaman aşımı")
            return None
        if out_file.exists():
            try:
                return json.loads(out_file.read_text(encoding="utf-8"))
            except ValueError:
                pass
        try:
            return extract_json(proc.stdout or "")
        except StageError:
            L.warning("Claude Code geçerli JSON üretmedi: %s", (proc.stdout or proc.stderr or "")[-300:])
            return None
    if mode == "anthropic" and available():
        content = []
        for p in images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.b64encode(p.read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt + "\n\nYalnızca JSON döndür."})
        try:
            msg = _client().messages.create(model=cfg.get_path("llm.anthropic.model", "claude-opus-5-5"),
                                            max_tokens=4000, messages=[{"role": "user", "content": content}])
            data = extract_json("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
            write_json(out_file, data)
            return data
        except Exception as exc:  # noqa: BLE001
            L.warning("Claude API hatası: %s", exc)
            return None
    return None


# ----------------------------------------------------------------------------
# Ölçümler
# ----------------------------------------------------------------------------

def _rotation(v: dict) -> int:
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot and (v.get("tags") or {}).get("rotate"):
        rot = int(float(v["tags"]["rotate"]))
    return abs(rot) % 180


def probe(src: Path) -> dict:
    """Video bilgisi. Telefon videolarındaki döndürme etiketi hesaba katılır (dikey çekim dikey görünür);
    HDR (iPhone HLG/Dolby Vision, PQ) işaretlenir — render'da SDR'a ton eşlemesi yapılır."""
    info = ffprobe(src)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"
              and (s.get("disposition") or {}).get("attached_pic") != 1), None)
    if not v:
        raise StageError("dosyada video akışı yok")
    w, h = int(v["width"]), int(v["height"])
    if _rotation(v) == 90:
        w, h = h, w
    hdr = v.get("color_transfer") in ("smpte2084", "arib-std-b67") or v.get("color_primaries") == "bt2020"
    return {"duration": float(info["format"].get("duration") or 0), "width": w, "height": h, "hdr": bool(hdr),
            "audio": any(s.get("codec_type") == "audio" for s in info["streams"])}


def media_info(path: Path) -> dict:
    """Yüklenen dosyanın türü: video / audio / image (+ boyut, süre)."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        from PIL import Image, ImageOps
        try:
            import pillow_heif  # iPhone HEIC/HEIF fotoğrafları
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            return {"kind": "image", "width": im.width, "height": im.height, "duration": 0.0, "audio": False}
    info = ffprobe(path)
    streams = info["streams"]
    if any(s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") != 1 for s in streams):
        return {"kind": "video", **probe(path)}
    if any(s.get("codec_type") == "audio" for s in streams):
        return {"kind": "audio", "duration": float(info["format"].get("duration") or 0), "audio": True,
                "width": 0, "height": 0}
    raise StageError("dosya okunamadı (desteklenen: video, fotoğraf, ses)")


def normalize_image(path: Path) -> Path:
    """HEIC/WEBP/PNG vb. fotoğrafı EXIF yönüne göre döndürülmüş JPG'ye çevirir (ffmpeg her yerde okuyabilsin)."""
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    dest = path.with_suffix(".jpg") if path.suffix.lower() != ".jpg" else path.with_name(path.stem + "_n.jpg")
    with Image.open(path) as im:
        ImageOps.exif_transpose(im).convert("RGB").save(dest, quality=93)
    return dest


HDR_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
              "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def combine_sources(files: list[Path], dest: Path, photo_sec: float = 3.5) -> dict:
    """Birden çok video/fotoğrafı tek bir montaj kaynağında birleştirir (sırasıyla).

    Tuval çoğunluğun yönüne göre seçilir (dikey 1080x1920 / yatay 1920x1080); farklı oranlı parçalar bulanık
    arka planla sığdırılır. Fotoğraflar hafif yakınlaşmayla (Ken Burns) photo_sec saniyelik sahne olur. HDR
    videolar SDR'a ton eşlenir, sesi olmayan parçalara sessizlik eklenir."""
    infos = [media_info(f) for f in files]
    items = [(f, i) for f, i in zip(files, infos) if i["kind"] in ("video", "image")]
    if not items:
        raise StageError("birleştirilecek video veya fotoğraf yok")
    portrait = sum(1 for _, i in items if i["height"] >= i["width"]) >= len(items) / 2
    W, H = (1080, 1920) if portrait else (1920, 1080)
    work = dest.with_suffix(".parts")
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    for n, (f, i) in enumerate(items):
        part = work / f"p{n:03d}.mp4"
        fill = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40,"
                f"eq=brightness=-0.08[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p")
        if i["kind"] == "image":
            src = normalize_image(f) if f.suffix.lower() not in (".jpg", ".jpeg") else f
            frames = int(photo_sec * 30)
            zoom = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                    f"zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30")
            ratio = i["width"] / max(1, i["height"])
            vf = zoom if abs(ratio - W / H) < 0.15 else fill  # oranı tutmayan fotoğraf: bulanık arka planla
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{photo_sec}", "-i", src, "-f", "lavfi", "-t",
                 f"{photo_sec}", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", f"[0:v]{vf}[v]",
                 "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", part])
        else:
            pre = (HDR_TO_SDR + ",") if i.get("hdr") else ""
            audio = ["-map", "0:a:0"] if i["audio"] else ["-map", "1:a"]
            run(["ffmpeg", "-y", "-v", "error", "-i", f, "-f", "lavfi", "-t", f"{i['duration']:.3f}", "-i",
                 "anullsrc=r=48000:cl=stereo", "-filter_complex", f"[0:v]{pre}{fill}[v]", "-map", "[v]", *audio,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-ar", "48000", "-ac", "2", "-shortest", part])
        parts.append(part)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart",
         dest])
    shutil.rmtree(work, ignore_errors=True)
    return {"file": dest, "parts": len(parts), "size": [W, H]}


def scene_cuts(src: Path, limit: float) -> list[float]:
    proc = run(["ffmpeg", "-hide_banner", "-t", f"{limit}", "-i", src, "-vf",
                "select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-"], check=False, quiet=True)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def sample_frames(src: Path, dest: Path, limit: float, fps: float = 2.0) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    for f in dest.glob("*.jpg"):
        f.unlink()
    run(["ffmpeg", "-y", "-v", "error", "-t", f"{limit}", "-i", src, "-vf", f"fps={fps},scale=192:-2",
         str(dest / "s%04d.jpg")])
    return sorted(dest.glob("s*.jpg"))


def color_metrics(frames: list[Path]) -> dict:
    lum, sat, contrast, warm, motion, accents = [], [], [], [], [], []
    prev = None
    for f in frames:
        with Image.open(f) as im:
            rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
            hsv = np.asarray(im.convert("HSV"), dtype=np.float32) / 255
        y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        lum.append(y.mean())
        contrast.append(y.std())
        sat.append(hsv[..., 1].mean())
        warm.append((rgb[..., 0] - rgb[..., 2]).mean())
        if prev is not None and prev.shape == y.shape:
            motion.append(np.abs(y - prev).mean())
        prev = y
        mask = (hsv[..., 1] > 0.55) & (hsv[..., 2] > 0.55)
        if mask.any():
            accents.append(rgb[mask])
    acc = []
    if accents:
        px = np.concatenate(accents)
        hsv_px = np.asarray(Image.fromarray((px[None] * 255).astype(np.uint8)).convert("HSV"))[0] / 255
        bins = (hsv_px[:, 0] * 12).astype(int) % 12
        for b in np.argsort(-np.bincount(bins, minlength=12))[:3]:
            sel = px[bins == b]
            if len(sel) > 0.02 * len(px):
                r, g, bl = (sel.mean(axis=0) * 255).astype(int)
                acc.append({"hex": f"#{r:02X}{g:02X}{bl:02X}", "share": round(len(sel) / len(px), 3)})
    m = lambda xs: round(float(np.mean(xs)), 4) if xs else 0.0  # noqa: E731
    return {"brightness": m(lum), "contrast": m(contrast), "saturation": m(sat), "warmth": m(warm),
            "motion": m(motion), "accent_colors": acc}


def audio_metrics(src: Path, words: list[dict], limit: float) -> dict:
    try:
        a = load_audio(src, 16000, 1)[: int(limit * 16000)]
    except StageError:
        return {"energy_coverage": 0.0, "speech_coverage": 0.0, "music_likely": False, "words_per_sec": 0.0}
    hop = 800
    n = len(a) // hop
    if n == 0:
        return {"energy_coverage": 0.0, "speech_coverage": 0.0, "music_likely": False, "words_per_sec": 0.0}
    rms = np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    energy = float((20 * np.log10(rms) > -38).mean())
    dur = n * hop / 16000
    speech = sum(min(w["end"], limit) - w["start"] for w in words if w["start"] < limit)
    speech_cov = min(1.0, speech / max(dur, 0.1))
    wps = len([w for w in words if w["start"] < limit]) / max(dur, 0.1)
    return {"energy_coverage": round(energy, 3), "speech_coverage": round(speech_cov, 3),
            "music_likely": bool(energy - speech_cov > 0.25 or (speech_cov < 0.2 and energy > 0.5)
                                 or (energy > 0.95 and speech_cov < 0.9)),  # konuşma aralarında da ses: müzik yatağı
            "words_per_sec": round(wps, 2)}


def transcribe(src: Path, work: Path, cfg: Config, model: str | None = None, limit: float | None = None) -> list[dict]:
    """faster-whisper ile kelime zamanlı döküm (önbellekli)."""
    cache = work / f"words_{model or 'cfg'}_{int(limit or 0)}.json"
    if cache.exists():
        return read_json(cache)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        L.warning("faster-whisper kurulu değil: konuşma dökümü yok (altyazı ve boşluk kesme yapılamaz)")
        return []
    wav = work / "asr.wav"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000"]
    if limit:
        cmd[4:4] = ["-t", f"{limit}"]
    proc = run(cmd + [wav], check=False)
    if proc.returncode != 0 or not wav.exists():
        return []
    m = WhisperModel(model or cfg.get_path("qc.asr_model", "small"), device="cpu", compute_type="int8")
    audio = load_audio(wav, 16000, 1)  # dizi olarak ver: PyAV sürüm uyumsuzluğundan bağımsız
    segs, _ = m.transcribe(audio, language="tr", word_timestamps=True, vad_filter=True, beam_size=1)
    words = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if words and (t[:1] in "'’" or not re.search(r"\w", t)):  # "Venüs" + "'ün", tek başına noktalama
                words[-1]["word"] += t
                words[-1]["end"] = round(w.end, 3)
            elif t:
                words.append({"word": t, "start": round(w.start, 3), "end": round(w.end, 3)})
    write_json(cache, words)
    wav.unlink(missing_ok=True)
    return words


def sheet(frames: list[tuple[Path, str]], dest: Path, cols: int = 6, tile_w: int = 240) -> Path:
    ims = []
    for f, label in frames:
        with Image.open(f) as im:
            im = im.convert("RGB")
            ims.append((im.resize((tile_w, int(im.height * tile_w / im.width))), label))
    th = max(i.height for i, _ in ims) + 30
    rows = (len(ims) + cols - 1) // cols
    out = Image.new("RGB", (cols * tile_w, rows * th), (14, 16, 22))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype(str(FONT), 18)
    except OSError:
        font = ImageFont.load_default()
    for i, (im, label) in enumerate(ims):
        x, y = (i % cols) * tile_w, (i // cols) * th
        out.paste(im, (x, y))
        draw.text((x + 6, y + im.height + 5), label, fill=(255, 210, 63), font=font)
    out.save(dest, quality=88)
    return dest


def grab(src: Path, t: float, dest: Path, height: int = 960) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf",
         f"scale=-2:{height}", dest])
    return dest


# ----------------------------------------------------------------------------
# 1) Stil öğren
# ----------------------------------------------------------------------------

STYLE_SCHEMA_DOC = """Stil JSON alanları (yalnızca bunları kullan):
pacing.max_pause (sn; konuşma boşluğu bundan uzunsa kesilir: hızlı kurgu 0.25-0.4, sakin 0.8-1.5)
frame.mode ("blur": yatay video bulanık arka planla dikey; "crop": ortadan kırp; "fit": siyah boşluk)
grade.contrast (0.7-1.5), grade.saturation (0-2), grade.brightness (-0.2..0.2), grade.gamma (0.7-1.4),
grade.warmth (-0.3 soğuk .. 0.3 sıcak), grade.vignette (bool)
punch.enabled (kesimlerde ani zoom), punch.scale (1.0-1.4)
captions.enabled, captions.weight (400-900), captions.size (1080 genişlikte px, 40-130), captions.uppercase,
captions.color, captions.highlight (konuşulan kelimenin rengi), captions.outline (px), captions.outline_color,
captions.shadow, captions.box (yazı arkasında kutu), captions.box_color, captions.words (ekranda aynı anda 1-6 kelime),
captions.y (dikey konum 0-1, ekran yüksekliği oranı), captions.pop (grup girişinde büyüme animasyonu)
title.enabled (ilk saniyelerde büyük başlık), title.seconds, title.size, title.weight, title.uppercase,
title.fg (yazı rengi), title.bg (kutu rengi), title.y (0-1)
progress.enabled (ilerleme çubuğu), progress.position ("top" | "bottom"), progress.color, progress.height
flash.enabled (başta beyaz flaş geçişi)
music.enabled (arka plan müziği ekle), music.gain_db (-30..-10), music.mood (ör. "upbeat", "calm", "epic")
Renkler "#RRGGBB"."""


def heuristic_style(metrics: dict) -> dict:
    s = json.loads(json.dumps(DEFAULT_STYLE))
    shot = metrics["avg_shot_sec"]
    s["pacing"]["max_pause"] = 0.3 if shot < 2 else 0.45 if shot < 4 else 0.8
    s["punch"]["enabled"] = shot < 4.5
    c = metrics["color"]
    s["grade"]["saturation"] = round(min(1.5, max(0.8, 1 + (c["saturation"] - 0.30) * 1.2)), 2)
    s["grade"]["contrast"] = round(min(1.3, max(0.9, 1 + (c["contrast"] - 0.22) * 1.5)), 2)
    s["grade"]["warmth"] = round(min(0.2, max(-0.2, c["warmth"] * 0.5)), 2)
    if c["accent_colors"]:
        s["captions"]["highlight"] = c["accent_colors"][0]["hex"]
        s["title"]["bg"] = c["accent_colors"][0]["hex"]
    a = metrics["audio"]
    s["music"]["enabled"] = bool(a["music_likely"])
    s["captions"]["enabled"] = a["speech_coverage"] > 0.15
    s["captions"]["words"] = 2 if a["words_per_sec"] > 3.2 else 3
    return s


def download_url(url: str) -> Path:
    """Bağlantıdaki videoyu (Instagram/TikTok/YouTube vb.) yalnızca stil incelemesi için indirir (yt-dlp)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise StageError("yt-dlp kurulu değil (pip install yt-dlp)") from exc
    UPLOADS.mkdir(parents=True, exist_ok=True)
    stamp = f"{dt.datetime.now():%Y%m%d-%H%M%S}"
    opts = {"outtmpl": str(UPLOADS / f"{stamp}-link-%(id)s.%(ext)s"), "noplaylist": True, "quiet": True,
            "no_warnings": True, "format": "bv*[height<=1920]+ba/b", "merge_output_format": "mp4",
            "max_filesize": 600 * 1024 * 1024, "socket_timeout": 30}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    except Exception as exc:  # noqa: BLE001
        raise StageError("Bağlantıdaki video indirilemedi (gizli hesap/giriş gerekebilir). Videoyu cihazına kaydedip "
                         f"dosya olarak yükle. Ayrıntı: {str(exc)[:200]}") from exc
    if not path.exists():
        cands = sorted(UPLOADS.glob(f"{stamp}-link-*"))
        if not cands:
            raise StageError("indirilen dosya bulunamadı")
        path = cands[-1]
    return path


def run_analyze(pid: str) -> dict:
    cfg = load_config()
    proj = load_project(pid)
    work = PROJECTS / pid
    proj["status"] = "running"
    handler = log.attach_job_log(pid)
    try:
        if not proj.get("source") and proj.get("url"):
            set_stage(proj, "bağlantıdaki video indiriliyor")
            path = download_url(proj["url"])
            proj.update(source=str(path.relative_to(ROOT)), source_name=path.name)
            save_project(proj)
        src = ROOT / proj["source"]
        set_stage(proj, "video inceleniyor")
        info = probe(src)
        limit = min(info["duration"], ANALYZE_SECONDS)
        cuts = scene_cuts(src, limit)
        frames = sample_frames(src, work / "samples", limit)
        color = color_metrics(frames)
        set_stage(proj, "konuşma dinleniyor")
        words = transcribe(src, work, cfg, model="tiny", limit=limit) if info["audio"] else []
        audio = audio_metrics(src, words, limit) if info["audio"] else {
            "energy_coverage": 0, "speech_coverage": 0, "music_likely": False, "words_per_sec": 0}
        metrics = {"duration": round(info["duration"], 2), "analyzed_seconds": round(limit, 1),
                   "size": [info["width"], info["height"]], "cuts": len(cuts),
                   "avg_shot_sec": round(limit / (len(cuts) + 1), 2), "color": color, "audio": audio}
        metrics = plain(metrics)
        write_json(work / "metrics.json", metrics)

        set_stage(proj, "kareler hazırlanıyor")
        times = sorted({round(t, 2) for t in np.linspace(0.3, limit - 0.3, 12)} |
                       {round(c + 0.4, 2) for c in cuts[:6] if c + 0.4 < limit})
        tiles = []
        for i, t in enumerate(times[:18]):
            tiles.append((grab(src, t, work / f"k{i:02d}.jpg", 480), f"{t:.1f} sn"))
        ref_sheet = sheet(tiles, work / "reference_sheet.jpg")
        big = [grab(src, t, work / f"big{i}.jpg", 1280) for i, t in
               enumerate([limit * 0.08, limit * 0.35, limit * 0.65])]

        draft = plain(heuristic_style(metrics))
        style, name, summary, effects = draft, None, None, []
        set_stage(proj, "stil çıkarılıyor (Claude)" if ai_mode(cfg) != "none" else "stil çıkarılıyor (kurallar)")
        prompt = (
            "Bir kısa dikey video (Reels/TikTok) için referans videonun görsel stilini çıkarıyorsun. Amaç: "
            "kullanıcının kendi videosunu bu stile benzeterek otomatik düzenlemek.\n"
            "İlk görüntü zamana göre kare tablosu, diğerleri büyük karelerdir. Ölçümler:\n"
            f"{json.dumps(metrics, ensure_ascii=False)}\n\nÖlçümlere göre taslak stil:\n"
            f"{json.dumps(draft, ensure_ascii=False)}\n\n{STYLE_SCHEMA_DOC}\n\n"
            "Karelere bakarak altyazıların konumunu, yazı kalınlığını, büyük/küçük harfi, renklerini, vurgu "
            "rengini, kutu/kontur kullanımını, açılış başlığını, renk düzenlemesini ve kesim/zoom hissini belirle. "
            "Görmediğin bir şeyi uydurma; emin olmadığın alanda taslağı koru. Çıktı biçimi:\n"
            '{"style": {...tam stil...}, "name_suggestion": "2-3 kelimelik Türkçe ad", '
            '"summary_tr": "stili 1-2 cümleyle anlat", "effects": ["tespit edilen efekt 1", "..."]}')
        res = ask_ai(cfg, prompt, [ref_sheet, *big], work / "ai_style.json")
        if res and isinstance(res.get("style"), dict):
            style = full_style(res["style"])
            name, summary = res.get("name_suggestion"), res.get("summary_tr")
            effects = [str(e) for e in res.get("effects", [])][:12]
            proj["analysis_by"] = "claude" if ai_mode(cfg) == "claude_cli" else "claude_api"
        else:
            proj["analysis_by"] = "kurallar"
            proj["notes"].append("Claude kullanılamadı; stil yalnızca ölçümlerden çıkarıldı "
                                 "(altyazı görünümü varsayılan).")
            effects = describe(draft, metrics)
        proj.update(status="done", stage="tamamlandı", metrics=metrics, style=full_style(style),
                    name_suggestion=name or suggest_name(proj["source_name"]),
                    summary=summary or f"Ortalama çekim {metrics['avg_shot_sec']} sn, "
                                        f"{'müzikli' if audio['music_likely'] else 'müziksiz'}, "
                                        f"{'konuşmalı' if audio['speech_coverage'] > 0.15 else 'konuşmasız'}.",
                    effects=effects, reference_sheet=str(ref_sheet.relative_to(ROOT)))
        save_project(proj)
        return proj
    except Exception as exc:
        proj.update(status="failed", stage="hata", error=str(exc)[:600])
        save_project(proj)
        raise
    finally:
        log.detach(handler)


def describe(style: dict, metrics: dict) -> list[str]:
    out = [f"Ortalama çekim süresi {metrics['avg_shot_sec']} sn ({metrics['cuts']} kesim)"]
    if style["punch"]["enabled"]:
        out.append("Kesimlerde zoom (punch-in)")
    g = style["grade"]
    out.append(f"Renk: doygunluk ×{g['saturation']}, kontrast ×{g['contrast']}")
    if style["music"]["enabled"]:
        out.append("Arka planda müzik")
    if metrics["color"]["accent_colors"]:
        out.append(f"Baskın vurgu rengi {metrics['color']['accent_colors'][0]['hex']}")
    return out


def suggest_name(filename: str) -> str:
    stem = re.sub(r"^\d{8}-\d{6}-", "", Path(filename).stem)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return (stem[:24] or "Yeni stil").title()


def save_from_analysis(pid: str, name: str) -> dict:
    proj = load_project(pid)
    if proj.get("status") != "done" or not proj.get("style"):
        raise StageError("analiz henüz bitmedi")
    name = (name or proj.get("name_suggestion") or "Yeni stil").strip()[:60]
    slug = slugify(name, 40)
    ref_dir = STYLES / slug
    ref_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJECTS / pid / "reference_sheet.jpg", ref_dir / "reference_sheet.jpg")
    style = {**proj["style"], "description": proj.get("summary", ""), "effects": proj.get("effects", []),
             "source": proj["source_name"], "created": now(), "version": 1, "history": [],
             "reference_sheet": str((ref_dir / "reference_sheet.jpg").relative_to(ROOT))}
    saved = save_style(style, name, slug)
    proj["saved_style"] = slug
    save_project(proj)
    return saved


# ----------------------------------------------------------------------------
# 2) Videomu düzenle
# ----------------------------------------------------------------------------

def sentences(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["word"].rstrip()[-1:] in ".?!" or (nxt and nxt["start"] - w["end"] > 1.2) or len(cur) > 40:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["word"] for x in cur)})
            cur = []
    if cur:
        out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["word"] for x in cur)})
    return out


HOOK_WORDS = ("neden", "nasıl", "aslında", "ilginç", "inanılmaz", "sır", "hiç", "bilmiyor", "gerçek", "ilk", "en ",
              "şaşır", "dikkat", "önemli", "hata")


def heuristic_clips(sents: list[dict], n: int, lo: float, hi: float) -> list[dict]:
    cands = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            d = sents[j]["end"] - sents[i]["start"]
            if d > hi:
                break
            if d < lo:
                continue
            text = " ".join(s["text"] for s in sents[i:j + 1])
            words = len(text.split())
            first = sents[i]["text"].lower()
            score = words / d + 1.5 * (("?" in first) or bool(re.search(r"\d", first))) + \
                sum(0.6 for h in HOOK_WORDS if h in first) + (0.5 if sents[j]["text"].rstrip()[-1:] in ".!" else 0)
            cands.append((score, i, j))
    cands.sort(reverse=True)
    chosen: list[tuple[int, int]] = []
    for _, i, j in cands:
        if all(j < a or i > b for a, b in chosen):
            chosen.append((i, j))
        if len(chosen) >= n:
            break
    out = []
    for i, j in sorted(chosen):
        title = " ".join(sents[i]["text"].split()[:7]).rstrip(",.;:")
        out.append({"start": sents[i]["start"], "end": sents[j]["end"], "title": title, "why": "kurallar"})
    return out


def pick_clips(cfg: Config, proj: dict, sents: list[dict], n: int, lo: float, hi: float) -> list[dict]:
    if ai_mode(cfg) != "none" and sents:
        listing = "\n".join(f"[{i}] ({s['start']:.1f}-{s['end']:.1f} sn) {s['text']}" for i, s in enumerate(sents))
        notes = proj["options"].get("notes") or ""
        prompt = (
            f"Aşağıda uzun bir videonun cümle cümle dökümü var. Bundan {n} adet bağımsız kısa dikey video (Reels) "
            f"çıkarılacak; her biri {lo:.0f}-{hi:.0f} saniye olmalı ve tek başına anlaşılmalı, güçlü bir açılış "
            "cümlesiyle başlamalı ve doğal bir yerde bitmeli. Klipler çakışmasın.\n"
            + (f"Kullanıcının isteği: {notes}\n" if notes else "")
            + "Seçim ilkeleri (yt-shorts): ilk cümle önceki dakikaya ihtiyaç duymayan tam bir düşünce olsun; içinde "
              "bir dönüş olsun (iddia, sonra onu zorlayan/kanıtlayan bir şey); bir cümleyle bitsin, dağılarak değil.\n"
              "Her klip için kısa, merak uyandıran bir Türkçe başlık yaz: ilk 2 saniye ekranda kalır, bu yüzden "
              "klibin ilk cümlesindeki kelimeleri TEKRARLAMASIN (en fazla 6 kelime, videoda söylenenden "
              "fazlasını iddia etme).\nÇıktı: {\"clips\": [{\"start\": ilk_cümle_no, \"end\": son_cümle_no, "
              "\"title\": \"...\", \"why\": \"neden seçildi\"}]}\n\nDÖKÜM:\n" + listing)
        res = ask_ai(cfg, prompt, [], PROJECTS / proj["id"] / "ai_clips.json")
        clips = []
        for c in (res or {}).get("clips", []):
            try:
                i, j = int(c["start"]), int(c["end"])
                a, b = sents[i]["start"], sents[j]["end"]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if lo * 0.6 <= b - a <= hi * 1.4 and all(b <= x["start"] or a >= x["end"] for x in clips):
                clips.append({"start": a, "end": b, "title": str(c.get("title", ""))[:60],
                              "why": str(c.get("why", ""))[:200]})
        if clips:
            proj["clips_by"] = "claude"
            return sorted(clips, key=lambda c: c["start"])[:n]
        proj["notes"].append("Claude klip seçimi yapamadı; kurallarla seçildi.")
    proj["clips_by"] = "kurallar"
    return heuristic_clips(sents, n, lo, hi)


def improve_style(cfg: Config, proj: dict, style: dict, out_sheet: Path, rnd: int) -> dict | None:
    ref = style.get("reference_sheet")
    imgs = [out_sheet] + ([ROOT / ref] if ref and (ROOT / ref).exists() else [])
    notes = proj["options"].get("notes") or ""
    prompt = (
        "Bir video düzenleme stilini iyileştiriyorsun. İlk görüntü, kullanıcının videosunun bu stille düzenlenmiş "
        "halinden zamana göre kareler" + ("; ikinci görüntü stilin öğrenildiği referans videonun kareleri" if len(imgs) > 1
                                          else "") + ".\n"
        f"Şu anki stil:\n{json.dumps(style, ensure_ascii=False)}\n\n{STYLE_SCHEMA_DOC}\n\n"
        "Kontrol et: altyazılar okunuyor mu (boyut, kontrast, kontur), yüzleri/önemli öğeleri kapatıyor mu, "
        "ekran kenarına taşıyor mu, başlık güvenli alanda mı (üst %8 ve alt %20'ye yazı konmamalı), renkler doğal mı, "
        "referansa benziyor mu." + (f" Kullanıcının isteği: {notes}." if notes else "") +
        " Yalnızca gerçekten gerekli değişiklikleri yap.\nÇıktı: {\"ok\": true/false (değişiklik gerekmiyorsa true), "
        "\"changes\": {...yalnızca değişen alanlar, iç içe...}, \"reason\": \"Türkçe kısa açıklama\"}")
    res = ask_ai(cfg, prompt, imgs, PROJECTS / proj["id"] / f"ai_improve_{rnd}.json")
    if not res or res.get("ok") or not isinstance(res.get("changes"), dict) or not res["changes"]:
        if res:
            proj["notes"].append(f"İyileştirme turu {rnd}: değişiklik gerekmedi. {res.get('reason', '')}".strip())
        return None
    from .studio_render import merge
    new = full_style(merge(style, res["changes"]))
    proj["notes"].append(f"İyileştirme turu {rnd}: {res.get('reason', 'stil düzeltildi')}")
    proj.setdefault("improvements", []).append({"round": rnd, "changes": res["changes"],
                                                "reason": res.get("reason", "")})
    return new


def youtube_extras(srt_entries: list, dest: Path, duration: float) -> dict:
    """YouTube agent skill araçları: klibin ilk cümlesine kanca puanı; 3 dakikadan uzun videoda YouTube bölümleri."""
    out: dict = {}
    try:
        from .yt_tools import chapters, hook_score
    except Exception:  # noqa: BLE001
        return out
    first = ""
    for _, _, txt in srt_entries:
        first = (first + " " + txt).strip()
        if first[-1:] in ".?!" or len(first.split()) >= 20:
            break
    if first:
        h = hook_score(first)
        out["hook"] = {"text": first, "score": h["verdict"], "band": h["band_tr"], "fix": h["fix"]}
    if duration >= 180:
        ch = chapters(dest.with_suffix(".srt"))
        if ch.get("valid"):
            dest.with_suffix(".chapters.txt").write_text(ch["text"] + "\n", encoding="utf-8")
            out["chapters"] = ch["text"]
    return out


def output_sheet(video: Path, dest: Path, total: float) -> Path:
    every = max(1.0, total / 16)
    return qc.contact_sheet(video, dest, every, total, FONT)


def run_edit(pid: str) -> dict:
    cfg = load_config()
    proj = load_project(pid)
    work = PROJECTS / pid
    src = ROOT / proj["source"]
    o = proj["options"]
    proj["status"] = "running"
    handler = log.attach_job_log(pid)
    try:
        files = [UPLOADS / Path(f).name for f in (o.get("files") or []) if (UPLOADS / Path(f).name).is_file()]
        if len(files) > 1 or (files and files[0].suffix.lower() in IMAGE_EXT):
            set_stage(proj, f"{len(files)} dosya birleştiriliyor (videolar + fotoğraflar)")
            comb = combine_sources(files, UPLOADS / f"{pid}-montaj.mp4")
            src = comb["file"]
            proj.update(source=str(src.relative_to(ROOT)), source_name=f"{len(files)} dosyalık montaj")
            proj["notes"].append(f"{comb['parts']} parça tek montajda birleştirildi ({comb['size'][0]}x{comb['size'][1]}).")
            save_project(proj)
        set_stage(proj, "video inceleniyor")
        info = probe(src)
        proj["source_duration"] = round(info["duration"], 1)
        style_slug = o.get("style") or "fabrika"
        style = full_style(get_style(style_slug))
        if o.get("captions") is False:
            style["captions"]["enabled"] = False
        if o.get("frame"):
            style["frame"]["mode"] = o["frame"]
        if proj.get("source_name", "").endswith("dosyalık montaj"):
            style["pacing"]["keep_gaps"] = 2.0  # montajda konuşmasız fotoğraf/video sahneleri kesilmez
        set_stage(proj, f"konuşma yazıya dökülüyor ({info['duration'] / 60:.1f} dk video; uzun videolarda birkaç dakika sürer)")
        words = transcribe(src, work, cfg) if info["audio"] else []
        if not words:
            proj["notes"].append("Videoda konuşma bulunamadı: altyazı ve boşluk kesme yapılmadı.")
        mode = o.get("mode", "clips")
        if mode == "clips":
            lo, hi = float(o.get("min_sec", 20)), float(o.get("max_sec", 60))
            n = int(o.get("count") or 0) or max(1, min(6, int(info["duration"] // 120) or 1))
            set_stage(proj, "en iyi anlar seçiliyor" + (" (Claude)" if ai_mode(cfg) != "none" else ""))
            sents = sentences(words)
            clips = pick_clips(cfg, proj, sents, n, lo, hi) if sents else []
            if not clips:
                d = min(info["duration"], hi)
                clips = [{"start": 0.0, "end": d, "title": o.get("title") or "", "why": "konuşma yok: baştan"}]
        else:
            clips = [{"start": 0.0, "end": info["duration"], "title": o.get("title") or "", "why": "tamamı"}]
        aspect = o.get("aspect", "9:16")
        out_dir = OUT / pid
        out_dir.mkdir(parents=True, exist_ok=True)
        proj["clips"] = [{**c, "status": "pending"} for c in clips]
        save_project(proj)

        rounds = int(o.get("improve_rounds", 1)) if ai_mode(cfg) != "none" else 0
        if o.get("improve_rounds") and ai_mode(cfg) == "none":
            proj["notes"].append("Otomatik iyileştirme için Claude gerekli; atlandı.")
        for ci, clip in enumerate(proj["clips"], 1):
            stem = re.sub(r"^\d{8}-\d{6}-", "", Path(proj["source_name"]).stem)
            name = f"{ci:02d}-{slugify(clip['title'] or stem, 40)}"
            dest = out_dir / f"{name}.mp4"
            cw = work / f"clip{ci:02d}"
            set_stage(proj, f"klip {ci}/{len(clips)} düzenleniyor")
            t0 = time.time()
            res = render_clip(src, (clip["start"], clip["end"]), words, clip["title"], style, cw, dest, cfg,
                              aspect=aspect, music=o.get("music"), enhance_voice=o.get("enhance", True))
            shot = output_sheet(dest, cw / "sheet.jpg", res["duration"])
            for rnd in range(1, rounds + 1 if ci == 1 else 1):  # stil ilk klipte iyileştirilir, sonra hepsine uygulanır
                set_stage(proj, f"klip 1 inceleniyor ve stil iyileştiriliyor (tur {rnd})")
                new = improve_style(cfg, proj, style, shot, rnd)
                if not new:
                    break
                style = new
                set_stage(proj, f"klip 1 iyileştirilmiş stille yeniden üretiliyor (tur {rnd})")
                res = render_clip(src, (clip["start"], clip["end"]), words, clip["title"], style, cw, dest, cfg,
                                  aspect=aspect, music=o.get("music"), enhance_voice=o.get("enhance", True))
                shot = output_sheet(dest, cw / "sheet.jpg", res["duration"])
            if ci == 1 and proj.get("improvements") and style_slug not in ("", "fabrika") \
                    and (STYLES / f"{style_slug}.json").exists():
                old = get_style(style_slug)
                style["version"] = int(old.get("version", 1)) + 1
                style["history"] = (old.get("history") or []) + [{"date": now(), "project": pid,
                                                                  "changes": [i["reason"] for i in proj["improvements"]]}]
                save_style(style, old.get("name", style_slug), style_slug, backup=True)
                proj["notes"].append(f"Stil '{old.get('name', style_slug)}' geliştirildi → sürüm {style['version']}.")
            thumb = dest.with_suffix(".jpg")
            grab(dest, min(1.2, res["duration"] / 2), thumb, 1920)
            write_srt(res["srt"], dest.with_suffix(".srt"))
            checks = [qc.decode_check(dest), qc.black_frames(dest, cfg), qc.loudness_check(dest, cfg)]
            shutil.copy(shot, out_dir / f"{name}_sheet.jpg")
            extra = youtube_extras(res["srt"], dest, res["duration"])
            clip.update(status="done", output=str(dest.relative_to(ROOT)), thumbnail=str(thumb.relative_to(ROOT)),
                        srt=str(dest.with_suffix(".srt").relative_to(ROOT)),
                        sheet=str((out_dir / f"{name}_sheet.jpg").relative_to(ROOT)),
                        duration=res["duration"], cut_seconds=res["cut_seconds"], music=res["music"],
                        render_sec=round(time.time() - t0), qc=[{"name": c["name"], "ok": c["ok"],
                                                                  "detail": c["detail"]} for c in checks], **extra)
            save_project(proj)
        proj.update(status="done", stage="tamamlandı", style_used=style_slug)
        save_project(proj)
        return proj
    except Exception as exc:
        proj.update(status="failed", stage="hata", error=str(exc)[:800])
        save_project(proj)
        raise
    finally:
        log.detach(handler)


def safe_upload_name(name: str) -> str:
    p = Path(name or "video.mp4")
    ext = p.suffix.lower() if p.suffix.lower() in VIDEO_EXT | AUDIO_EXT | IMAGE_EXT else ".mp4"
    return f"{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(p.stem, 50)}{ext}"
