"""Türkçe seslendirme ve kelime zamanlamaları.

Sağlayıcı zinciri settings.yaml → tts.provider_chain ile belirlenir:
  edge        : Microsoft Edge "Sesli Oku" nöral sesleri (anahtarsız; kelime sınırlarını verir)
  elevenlabs  : ELEVENLABS_API_KEY gerekir; karakter hizalaması verir
  piper       : çevrimdışı; Türkçe sesi CC BY-NC-SA (ticari olmayan) — yalnızca allow_noncommercial: true iken
  my_voice    : kullanıcının kendi sesi (Sesim). Klon motoru kuruluysa (ekran kartı, Chatterbox) bütün sahneler
                prepare_scenes ile tek seferde okunur; yoksa edge + kNN-VC dönüşümü.

Her sahne için: voice/<sahne>.wav (48 kHz mono) + voice/<sahne>.json (kelime zamanları).
"""
from __future__ import annotations

import asyncio
import base64
import wave
from pathlib import Path

import numpy as np

from . import log
from .config import Config, secret
from .util import (StageError, TransientError, env_ca_bundle, load_audio, norm_word, retry,
                   syllables, words_of, write_json, write_wav)

L = log.get("tts")
SR = 48000


# ----------------------------------------------------------------------------
# Sağlayıcılar: (wav_path, ham kelime zamanları [{text,start,end}] veya None)
# ----------------------------------------------------------------------------

def _edge_synth(text: str, voice: str, rate: str, pitch: str, mp3_path: Path) -> list[dict]:
    import edge_tts
    import edge_tts.communicate as ec

    ca = env_ca_bundle()
    if ca and not getattr(ec, "_rf_ca_loaded", False):
        # Kurumsal proxy/CA kullanılan ortamlarda doğrulamayı kapatmadan CA eklenir.
        ec._SSL_CTX.load_verify_locations(ca)
        ec._rf_ca_loaded = True

    async def go() -> list[dict]:
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        audio = bytearray()
        marks: list[dict] = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                marks.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
        if not audio:
            raise StageError("edge-tts ses döndürmedi")
        mp3_path.write_bytes(bytes(audio))
        return marks

    try:
        return asyncio.run(go())
    except StageError:
        raise
    except Exception as exc:  # aiohttp/ws hataları
        name = type(exc).__name__
        if name in ("NoAudioReceived",):
            raise StageError(f"edge-tts: {voice} ses döndürmedi") from exc
        raise TransientError(f"edge-tts {name}: {exc}") from exc


def synth_edge(text: str, out_dir: Path, sid: str, cfg: Config) -> tuple[Path, list[dict], str]:
    ecfg = dict(cfg.get_path("tts.edge", {}))
    voices = list(ecfg.get("voices", ["tr-TR-EmelNeural"]))
    try:  # Sesim → etkin ses tarzı: öğrenilen hız, perde ve ses (tını kopyalanmaz)
        from .voice import active_style
        st = active_style()
    except Exception:  # noqa: BLE001
        st = None
    if st and st.get("edge"):
        e = st["edge"]
        ecfg.update(rate=e.get("rate", ecfg.get("rate")), pitch=e.get("pitch", ecfg.get("pitch")))
        voices = [e["voice"]] + [v for v in voices if v != e.get("voice")]
    last: Exception | None = None
    for voice in voices:
        mp3 = out_dir / f"{sid}.edge.mp3"
        try:
            marks = retry(attempts=cfg.get_path("retry.attempts", 3),
                          backoff=cfg.get_path("retry.backoff", 2.0))(_edge_synth)(
                text, voice, ecfg.get("rate", "+0%"), ecfg.get("pitch", "+0Hz"), mp3)
            return mp3, marks, f"edge:{voice}"
        except (StageError, TransientError) as exc:
            L.warning("edge-tts %s başarısız: %s", voice, exc)
            last = exc
    raise StageError(f"edge-tts kullanılamadı: {last}")


def synth_elevenlabs(text: str, out_dir: Path, sid: str, cfg: Config) -> tuple[Path, list[dict], str]:
    key = secret("ELEVENLABS_API_KEY")
    ecfg = cfg.get_path("tts.elevenlabs", {})
    if not key or not ecfg.get("voice_id"):
        raise StageError("ElevenLabs yapılandırılmamış (ELEVENLABS_API_KEY ve tts.elevenlabs.voice_id)")
    from .util import http_json
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ecfg['voice_id']}/with-timestamps"
    data = retry(cfg.get_path("retry.attempts", 3), cfg.get_path("retry.backoff", 2.0))(http_json)(
        "POST", url, headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"text": text, "model_id": ecfg.get("model_id", "eleven_multilingual_v2")}, timeout=180)
    mp3 = out_dir / f"{sid}.eleven.mp3"
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("alignment") or {}
    marks: list[dict] = []
    cur, cs, ce = "", None, None
    for ch, s, e in zip(al.get("characters", []), al.get("character_start_times_seconds", []),
                        al.get("character_end_times_seconds", [])):
        if ch.isspace():
            if cur:
                marks.append({"text": cur, "start": cs, "end": ce})
            cur, cs = "", None
            continue
        if cs is None:
            cs = s
        cur += ch
        ce = e
    if cur:
        marks.append({"text": cur, "start": cs, "end": ce})
    return mp3, marks, f"elevenlabs:{ecfg['voice_id']}"


def synth_piper(text: str, out_dir: Path, sid: str, cfg: Config) -> tuple[Path, list[dict] | None, str]:
    if not cfg.get_path("tts.allow_noncommercial", False):
        raise StageError("piper Türkçe sesi CC BY-NC-SA lisanslı; tts.allow_noncommercial=false")
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise StageError("piper-tts kurulu değil (pip install piper-tts)") from exc
    from .util import download
    name = cfg.get_path("tts.piper.model", "tr_TR-dfki-medium")
    cache = Path.home() / ".cache" / "reels-factory" / "piper"
    lang, rest = name.split("_", 1)[0], name
    region, speaker, quality = rest.split("-")
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{region}/{speaker}/{quality}/{name}"
    model = cache / f"{name}.onnx"
    if not model.exists():
        download(base + ".onnx", model, max_mb=200)
        download(base + ".onnx.json", cache / f"{name}.onnx.json", max_mb=5)
    voice = PiperVoice.load(model)
    wav_path = out_dir / f"{sid}.piper.wav"
    with wave.open(str(wav_path), "wb") as wf:
        voice.synthesize_wav(text, wf)
    return wav_path, None, f"piper:{name}"


def _clone_path(out_dir: Path, sid: str, text: str) -> Path:
    import hashlib
    return out_dir / f"{sid}.{hashlib.sha1(text.encode()).hexdigest()[:10]}.clone.wav"


def _my_voice_engine(cfg: Config) -> str:
    return str(cfg.get_path("tts.my_voice_engine", "auto"))


def prepare_scenes(scenes: list[dict], out_dir: Path, cfg: Config) -> None:
    """Kendi sesin klon motoruyla bütün sahneleri tek seferde okur (model bir kez yüklenir)."""
    from . import voice
    chain = cfg.get_path("tts.provider_chain", ["edge"])
    if not chain or chain[0] != "my_voice" or _my_voice_engine(cfg) == "knn":
        return
    slug = voice.active()
    if not slug or not voice.clone_available():
        return
    todo = [(sc["narration"], _clone_path(out_dir, sc["id"], sc["narration"])) for sc in scenes]
    todo = [(t, o) for t, o in todo if not o.exists()]
    if not todo:
        return
    L.info("Kendi sesinle seslendirme (klon, ekran kartı): %d sahne", len(todo))
    try:
        voice.clone_batch(slug, todo)
    except StageError as exc:   # klon çalışmazsa sahneler tek tek kNN-VC ile okunur
        L.warning("klon seslendirme başarısız, eski yönteme geçiliyor: %s", exc)


def synth_my_voice(text: str, out_dir: Path, sid: str, cfg: Config) -> tuple[Path, list[dict], str]:
    """Kullanıcının kendi sesi (uygulamadaki 'Sesim' sayfasında öğrenilen ve etkinleştirilen profil)."""
    from . import voice
    from .util import read_json
    slug = voice.active()
    if not slug:
        raise StageError("kişisel ses etkin değil")
    cp = _clone_path(out_dir, sid, text)
    if cp.exists():   # prepare_scenes klonla okudu: kelime zamanları Whisper'dan
        meta = read_json(cp.with_suffix(".json"), {}) or {}
        return cp, meta.get("words") or None, f"my_voice:{slug}:klon"
    if _my_voice_engine(cfg) == "klon":
        raise StageError("klon motoru bu sahneyi okuyamadı")
    mp3 = out_dir / f"{sid}.base.mp3"
    marks = voice.tts_raw(slug, text, mp3)
    wav = voice.convert(mp3, out_dir / f"{sid}.myvoice.wav", slug)  # aynı süre: kelime zamanları geçerli kalır
    mp3.unlink(missing_ok=True)
    return wav, marks, f"my_voice:{slug}"


PROVIDERS = {"my_voice": synth_my_voice, "edge": synth_edge, "elevenlabs": synth_elevenlabs, "piper": synth_piper}


# ----------------------------------------------------------------------------
# Kelime hizalama
# ----------------------------------------------------------------------------

def _speech_bounds(audio: np.ndarray, thresh_db: float = -42.0) -> tuple[float, float]:
    win = int(SR * 0.02)
    n = len(audio) // win
    if n == 0:
        return 0.0, len(audio) / SR
    frames = audio[: n * win].reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    voiced = np.where(db > thresh_db)[0]
    if len(voiced) == 0:
        return 0.0, len(audio) / SR
    return voiced[0] * win / SR, (voiced[-1] + 1) * win / SR


def estimate_marks(tokens: list[str], t0: float, t1: float) -> list[dict]:
    """Sağlayıcı zamanlama vermezse: hece sayısı + noktalama duraklarıyla orantılı dağıtım."""
    weights, pauses = [], []
    for tok in tokens:
        weights.append(syllables(tok))
        pauses.append(2.5 if tok[-1:] in ".!?…" else 1.2 if tok[-1:] in ",;:" else 0.0)
    total = sum(weights) + sum(pauses[:-1]) or 1.0
    unit = (t1 - t0) / total
    out, t = [], t0
    for tok, w, p in zip(tokens, weights, pauses):
        out.append({"text": tok, "start": t, "end": t + w * unit})
        t += (w + p) * unit
    return out


def align(narration: str, marks: list[dict] | None, t0: float, t1: float) -> list[dict]:
    """Sağlayıcı kelime sınırlarını senaryodaki kelimelere (noktalama dahil) eşler."""
    tokens = words_of(narration)
    if not marks:
        return estimate_marks(tokens, t0, t1)
    result: list[dict | None] = [None] * len(tokens)
    j = 0
    for i, tok in enumerate(tokens):
        nt = norm_word(tok)
        if not nt:
            continue
        for k in range(j, min(j + 4, len(marks))):
            nm = norm_word(marks[k]["text"])
            if nm and (nm == nt or nt.startswith(nm) or nm.startswith(nt)):
                start, end = marks[k]["start"], marks[k]["end"]
                # Bir kelime birden fazla sınıra bölündüyse (ör. sayılar) birleştir.
                k2 = k
                acc = nm
                while acc != nt and k2 + 1 < len(marks) and nt.startswith(acc + norm_word(marks[k2 + 1]["text"])):
                    k2 += 1
                    acc += norm_word(marks[k2]["text"])
                    end = marks[k2]["end"]
                result[i] = {"text": tok, "start": start, "end": end}
                j = k2 + 1
                break
    # Eşleşmeyenleri komşu zamanlar arasında hece ağırlığıyla doldur.
    i = 0
    while i < len(tokens):
        if result[i] is not None:
            i += 1
            continue
        k = i
        while k < len(tokens) and result[k] is None:
            k += 1
        left = result[i - 1]["end"] if i > 0 and result[i - 1] else t0
        right = result[k]["start"] if k < len(tokens) and result[k] else t1
        est = estimate_marks(tokens[i:k], left, max(right, left + 0.05 * (k - i)))
        for n, e in enumerate(est):
            result[i + n] = e
        i = k
    return [r for r in result if r is not None]


# ----------------------------------------------------------------------------
# Sahne seslendirme
# ----------------------------------------------------------------------------

def synthesize_scene(scene: dict, out_dir: Path, cfg: Config) -> dict:
    sid, text = scene["id"], scene["narration"]
    chain = cfg.get_path("tts.provider_chain", ["edge"])
    errors = []
    for name in chain:
        fn = PROVIDERS.get(name)
        if fn is None:
            continue
        try:
            raw_path, marks, provider = fn(text, out_dir, sid, cfg)
        except (StageError, TransientError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        audio = load_audio(raw_path, SR, 1)
        s0, s1 = _speech_bounds(audio)
        if marks:
            s0 = min(s0, marks[0]["start"])
            s1 = max(s1, marks[-1]["end"])
        # Baştaki sessizliği 0.05 sn'ye indir, sondakini 0.12 sn bırak.
        cut0 = max(0.0, s0 - 0.05)
        cut1 = min(len(audio) / SR, s1 + 0.12)
        clip = audio[int(cut0 * SR): int(cut1 * SR)].copy()
        fade = int(SR * 0.01)
        if len(clip) > 2 * fade:
            clip[:fade] *= np.linspace(0, 1, fade)
            clip[-fade:] *= np.linspace(1, 0, fade)
        shifted = [{"text": m["text"], "start": m["start"] - cut0, "end": m["end"] - cut0}
                   for m in (marks or [])]
        words = align(text, shifted or None, s0 - cut0, s1 - cut0)
        wav = write_wav(out_dir / f"{sid}.wav", clip, SR)
        meta = {
            "id": sid,
            "provider": provider,
            "duration": round(len(clip) / SR, 3),
            "timing": "provider" if marks else "estimated",
            "words": [{"i": n, "text": w["text"], "start": round(w["start"], 3),
                       "end": round(w["end"], 3)} for n, w in enumerate(words)],
        }
        write_json(out_dir / f"{sid}.json", meta)
        if raw_path != wav:
            raw_path.unlink(missing_ok=True)
            if raw_path.name.endswith(".clone.wav"):
                raw_path.with_suffix(".json").unlink(missing_ok=True)
        return meta
    raise StageError(f"Sahne {sid} için hiçbir TTS sağlayıcısı çalışmadı: " + " | ".join(errors))
