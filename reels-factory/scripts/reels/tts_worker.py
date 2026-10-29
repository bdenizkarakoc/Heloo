"""Kendi sesinle seslendirme motoru (ayrı Python ortamında, ekran kartında çalışır).

`studio/cache/venv-tts` içindeki Python ile çalıştırılır (torch CUDA + Chatterbox Multilingual, MIT lisanslı;
Türkçe dahil 23 dil, birkaç saniyelik örnekten ses kopyalama). Ana ortamın paketlerine dokunmaz; bu dosya
yalnızca standart kütüphane + o ortamdaki paketleri kullanır.

    python tts_worker.py iş.json      iş: {"ref": "örnek.wav", "items": [{"text": "...", "out": "x.wav"}],
                                           "exaggeration": 0.5, "cfg_weight": 0.5, "check": true}
Her öğe için out (.wav, 24 kHz) ve out.json ({"words": [{"text","start","end"}], "wer": .., "tries": ..}) yazar.
Her cümle Whisper ile geri dinlenir; okunuşu metinden çok sapan cümle (en çok 2 kez) yeniden üretilir.
Sayılar, yüzde ve birimler okunmadan önce Türkçe yazıya çevrilir.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "studio" / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# --------------------------------------------------------------------------- Türkçe metin normalleştirme
ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
GROUPS = ["", "bin", "milyon", "milyar", "trilyon"]
UNITS = {"km": "kilometre", "m": "metre", "cm": "santimetre", "mm": "milimetre", "kg": "kilogram", "g": "gram",
         "twh": "teravatsaat", "gwh": "gigavatsaat", "mwh": "megavatsaat", "kwh": "kilovatsaat", "mw": "megavat",
         "gw": "gigavat", "kw": "kilovat", "km/s": "kilometre bölü saniye", "km/sa": "kilometre bölü saat",
         "°c": "derece", "°": "derece", "tl": "lira", "$": "dolar", "€": "avro", "mb": "megabayt", "gb": "gigabayt",
         "tb": "terabayt", "ms": "milisaniye", "sn": "saniye", "dk": "dakika"}


def _three(n: int) -> list[str]:
    h, t, o = n // 100, n // 10 % 10, n % 10
    out = []
    if h:
        out += ([] if h == 1 else [ONES[h]]) + ["yüz"]
    if t:
        out.append(TENS[t])
    if o:
        out.append(ONES[o])
    return out


def say_int(n: int) -> str:
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + say_int(-n)
    words, g = [], 0
    while n:
        part = n % 1000
        if part:
            w = _three(part)
            if g == 1 and part == 1:
                w = []                      # "bir bin" değil "bin"
            words = w + ([GROUPS[g]] if g else []) + words
        n //= 1000
        g += 1
    return " ".join(words)


def ordinal(n: int) -> str:
    w = say_int(n)
    v = next((c for c in reversed(w) if c in "aeıioöuü"), "e")
    suf = {"a": "ıncı", "ı": "ıncı", "e": "inci", "i": "inci", "o": "uncu", "u": "uncu", "ö": "üncü", "ü": "üncü"}[v]
    return w + (suf[1:] if w[-1] in "aeıioöuü" else suf)


def say_number(s: str) -> str:
    s = s.strip()
    neg = s.startswith("-")
    s = s.lstrip("-+")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):   # 1.200.000 / 1.200,5
        s = s.replace(".", "")
    if "," in s:
        a, b = s.split(",", 1)
        txt = f"{say_int(int(a or 0))} virgül " + (say_int(int(b)) if not b.startswith("0") else " ".join(say_int(int(c)) for c in b))
    elif re.fullmatch(r"\d+\.\d+", s):                  # 4.5 (İngilizce ondalık)
        a, b = s.split(".")
        txt = f"{say_int(int(a))} nokta {say_int(int(b))}"
    else:
        txt = say_int(int(s))
    return ("eksi " if neg else "") + txt


NUM = r"(?:(?<![\w])-)?(?:\d[\d.,]*\d|\d)"


def normalize_tr(text: str) -> str:
    t = unicodedata.normalize("NFC", text)
    t = t.replace("’", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    t = re.sub(rf"%\s*({NUM})", lambda m: "yüzde " + say_number(m.group(1)), t)
    t = re.sub(rf"({NUM})\s*%", lambda m: "yüzde " + say_number(m.group(1)), t)
    t = re.sub(rf"({NUM})\s*-\s*({NUM})", lambda m: f"{m.group(1)} ile {m.group(2)}", t)   # 30-60 → 30 ile 60
    units = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
    t = re.sub(rf"({NUM})\s*({units})(?![\wçğıöşü])", lambda m: f"{m.group(1)} {UNITS[m.group(2).lower()]}", t, flags=re.I)
    # sayı + kesme işareti ekleri (2030'da → iki bin otuzda): ek olduğu gibi sona yapışır
    t = re.sub(rf"({NUM})'([a-zçğıöşü]+)", lambda m: say_number(m.group(1)) + m.group(2), t)
    t = re.sub(r"(\d+)\.(?=\s+[a-zçğıöşü])", lambda m: ordinal(int(m.group(1))), t)  # 3. bölüm → üçüncü bölüm
    t = re.sub(NUM, lambda m: say_number(m.group(0)), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def sentences(text: str, max_chars: int = 220) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        while len(p) > max_chars:                       # çok uzun cümleyi virgülden böl
            cut = p.rfind(",", 0, max_chars)
            cut = cut if cut > 40 else p.rfind(" ", 0, max_chars)
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out


def _norm(w: str) -> str:
    w = unicodedata.normalize("NFC", w).lower().replace("i̇", "i")
    return re.sub(r"[^\wçğıöşü]", "", w)


def wer(ref: str, hyp: str) -> float:
    r, h = [_norm(x) for x in ref.split() if _norm(x)], [_norm(x) for x in hyp.split() if _norm(x)]
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)


# --------------------------------------------------------------------------- modeller
_TTS = None
_ASR = None


def tts():
    global _TTS
    if _TTS is None:
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _TTS = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    return _TTS


def asr():
    global _ASR
    if _ASR is None:
        import torch  # noqa: F401 — CUDA kitaplıklarını (cuDNN/cuBLAS) yükler; ctranslate2 onları kullanır
        from faster_whisper import WhisperModel
        try:
            _ASR = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16",
                                download_root=str(ROOT / "studio" / "cache" / "whisper"))
        except Exception:  # noqa: BLE001 — ekran kartı yoksa
            _ASR = WhisperModel("small", device="cpu", compute_type="int8",
                                download_root=str(ROOT / "studio" / "cache" / "whisper"))
    return _ASR


def transcribe(wav: str, prompt: str = "") -> tuple[str, list[dict]]:
    import librosa
    audio, _ = librosa.load(wav, sr=16000, mono=True)   # dosyayı PyAV yerine librosa okur (sürüm uyuşmazlığı)
    segs, _ = asr().transcribe(audio, language="tr", word_timestamps=True, beam_size=5, vad_filter=False,
                               initial_prompt=prompt[:200] or None, condition_on_previous_text=False)
    words, text = [], []
    for s in segs:
        text.append(s.text)
        for w in s.words or []:
            words.append({"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
    return " ".join(text).strip(), words


# --------------------------------------------------------------------------- iş
def synth_item(text: str, out: Path, ref: str, opts: dict, check: bool) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    m = tts()
    sr = m.sr
    pieces, gap = [], np.zeros(int(sr * 0.18), dtype=np.float32)
    spoken = []
    worst, tries_total = 0.0, 0
    for sent in sentences(normalize_tr(text)):
        best = None
        for attempt in range(3 if check else 1):
            torch.manual_seed(1234 + attempt * 77)
            wav = m.generate(sent, language_id="tr", audio_prompt_path=ref,
                             exaggeration=float(opts.get("exaggeration", 0.5)),
                             cfg_weight=float(opts.get("cfg_weight", 0.5)),
                             temperature=float(opts.get("temperature", 0.8)))
            a = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
            tries_total += 1
            if not check:
                best = (0.0, a)
                break
            tmp = out.with_suffix(".chk.wav")
            sf.write(tmp, a, sr)
            heard, _ = transcribe(str(tmp))
            tmp.unlink(missing_ok=True)
            e = wer(sent, heard)
            if best is None or e < best[0]:
                best = (e, a)
            if e <= 0.12:
                break
        worst = max(worst, best[0])
        # cümle başı/sonundaki sessizliği kırp
        a = best[1]
        idx = np.where(np.abs(a) > 0.01)[0]
        if len(idx):
            a = a[max(0, idx[0] - int(sr * 0.04)): idx[-1] + int(sr * 0.08)]
        pieces += [a, gap]
        spoken.append(sent)
    audio = np.concatenate(pieces[:-1]) if pieces else np.zeros(sr, dtype=np.float32)
    peak = float(np.max(np.abs(audio)) or 1.0)
    audio = (audio / peak * 0.89).astype(np.float32)
    sf.write(out, audio, sr)
    heard, words = transcribe(str(out), " ".join(spoken))
    meta = {"words": words, "heard": heard, "spoken": " ".join(spoken), "wer": round(wer(" ".join(spoken), heard), 3),
            "worst_sentence_wer": round(worst, 3), "tries": tries_total, "sr": sr}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        import torch
        print(json.dumps({"cuda": torch.cuda.is_available(), "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--asr":   # python tts_worker.py --asr ses.wav [ipucu]
        text, words = transcribe(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
        print(json.dumps({"text": text, "words": words}, ensure_ascii=False))
        return 0
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    t0 = time.time()
    res = []
    for it in job["items"]:
        out = Path(it["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = synth_item(it["text"], out, job["ref"], job, bool(job.get("check", True)))
        res.append({"out": str(out), "wer": meta["wer"], "tries": meta["tries"]})
        print(json.dumps({"done": str(out), "wer": meta["wer"]}, ensure_ascii=False), flush=True)
    print(json.dumps({"ok": True, "items": res, "seconds": round(time.time() - t0, 1)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
