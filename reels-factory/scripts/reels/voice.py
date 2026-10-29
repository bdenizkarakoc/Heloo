"""Kişisel ses: kullanıcıyla sohbet ederek sesini toplar, iyileştirir, ses profilini çıkarır ve metni onun sesiyle okur.

Akış: sohbet (uygulama soru sorar, kullanıcı mikrofonla cevaplar; ~5 dk) → her cevap gürültü azaltma/EQ/
kompresörle iyileştirilir ve yazıya dökülür → profil: ses perdesi (F0), konuşma hızı, en yakın temel Türkçe ses →
kNN-VC (MIT lisanslı, yerel, ücretsiz) ile ses rengi dönüşümü için eşleştirme kümesi.

Seslendirme (iki motor):
- klon (varsayılan, ekran kartı): Chatterbox Multilingual (MIT) metni doğrudan kullanıcının sesiyle Türkçe okur;
  kayıtlardan seçilen en temiz ~10 sn örnek kullanılır, her cümle Whisper ile geri dinlenip yanlış okunan yeniden
  üretilir. Ayrı Python ortamında çalışır (`studio/cache/venv-tts`, `tts_worker.py`).
- kNN-VC (yedek, işlemci): temel Türkçe ses (edge-tts) kullanıcının ses rengine dönüştürülür.
Yalnızca kullanıcının kendi sesi ve açık onayıyla kullanılır.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import subprocess
import threading
from pathlib import Path

import numpy as np

from . import log
from .config import ROOT, Config, load_config
from .util import StageError, load_audio, read_json, run, slugify, syllables, write_json, write_wav

L = log.get("voice")
VOICES = ROOT / "studio" / "voices"
ACTIVE = VOICES / "active.json"
SAY_CACHE = VOICES / "_say"
HOST_VOICE = "tr-TR-EmelNeural"
TARGET_SPEECH_SEC = 300
MIN_SPEECH_SEC = 60
BASE_VOICES = {"male": "tr-TR-AhmetNeural", "female": "tr-TR-EmelNeural"}

# Konuşma iyileştirme: uğultu kesme, gürültü azaltma, çamur azaltma, netlik, sibilans, kompresör
ENHANCE_CORE = ("highpass=f=70,lowpass=f=13000,afftdn=nf=-28:tn=1,"
                "equalizer=f=250:t=q:w=1:g=-1.5,equalizer=f=3200:t=q:w=1.2:g=2,deesser=i=0.35,"
                "acompressor=threshold=-21dB:ratio=3:attack=8:release=120:makeup=2")
ENHANCE = ENHANCE_CORE + ",loudnorm=I=-18:TP=-2:LRA=9"

OPENING = ("Merhaba! Ben Reels Fabrikası. Videolarını senin sesinle seslendirebilmem için sesini tanımam lazım. "
           "Biraz sohbet edelim. Nasılsın, bugün nasıl geçti?")
QUESTIONS = [
    "Ne güzel. Peki bugün seni en çok ne güldürdü?",
    "Biraz kendinden bahseder misin? Neler yapmayı seversin?",
    "Hangi şehirde yaşıyorsun, orayı bana anlatır mısın?",
    "En sevdiğin yemek ne, nasıl yapıldığını anlatır mısın?",
    "Son izlediğin film ya da dizi neydi, nasıldı?",
    "Çocukluğundan aklında kalan güzel bir anı var mı?",
    "Videolarında en çok hangi konuları anlatmak istersin?",
    "Hafta sonları genelde ne yaparsın?",
    "Bir arkadaşına beni tanıtsan ne derdin?",
    "Hayalindeki tatili anlatır mısın?",
    "Seni en çok ne heyecanlandırır?",
    "Son zamanlarda öğrendiğin ilginç bir bilgi var mı?",
    "Sabahları nasıl bir rutinin var?",
    "Müzik dinler misin? En sevdiğin şarkıyı ve neden sevdiğini anlatır mısın?",
]
READING = [
    "Şimdi şu cümleyi kendi tarzınla okur musun: Pijamalı hasta yağız şoföre çabucak güvendi.",
    "Bir de şunu okur musun: Bugün hava çok güzel, sahilde yürüyüş yapıp çay içmeyi düşünüyorum.",
    "Son olarak heyecanlı bir sesle şunu söyler misin: Merhaba arkadaşlar, bugün size inanılmaz bir şey anlatacağım!",
    "Peki şimdi soru sorar gibi okur musun: Bunu daha önce hiç duydunuz mu, sizce neden böyle?",
]


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------

def enhance(src: Path, dest: Path, sr: int = 48000, strength: str = "orta") -> Path:
    """Konuşma iyileştirme (audiofx): uğultu, gürültü (Wiener), tıkırtı/kırpılma, netlik, seviye dengeleme."""
    from .audiofx import enhance as fx
    fx(src, dest, strength, target_lufs=-18.0, sr=sr)
    return dest


def speech_seconds(wav: Path) -> float:
    a = load_audio(wav, 16000, 1)
    hop = 320
    n = len(a) // hop
    if not n:
        return 0.0
    rms = np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    return float((20 * np.log10(rms) > -38).sum() * hop / 16000)


def pitch_hz(wav: Path) -> float:
    """Sesli bölümlerde otokorelasyonla temel frekansın medyanı (70-350 Hz)."""
    a = load_audio(wav, 16000, 1)
    win, hop = 640, 320
    f0 = []
    for i in range(0, len(a) - win, hop * 2):
        x = a[i:i + win]
        if np.sqrt((x ** 2).mean()) < 0.02:
            continue
        x = x - x.mean()
        ac = np.correlate(x, x, "full")[win - 1:]
        lo, hi = int(16000 / 350), int(16000 / 70)
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.45:
            f0.append(16000 / lag)
    return float(np.median(f0)) if f0 else 0.0


def say(text: str) -> Path:
    """Sunucu sesiyle (sohbet soruları) mp3 üretir; önbellekli."""
    from .tts import _edge_synth
    SAY_CACHE.mkdir(parents=True, exist_ok=True)
    mp3 = SAY_CACHE / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".mp3")
    if not mp3.exists():
        _edge_synth(text, HOST_VOICE, "+4%", "+0Hz", mp3)
    return mp3


# ----------------------------------------------------------------------------
# Sohbet oturumu
# ----------------------------------------------------------------------------

def vdir(slug: str) -> Path:
    d = VOICES / slugify(slug, 40)
    if not d.exists():
        raise StageError(f"ses profili yok: {slug}")
    return d


def start(name: str, consent: bool) -> dict:
    if not consent:
        raise StageError("Sesin kopyalanması için bu sesin size ait olduğunu onaylamanız gerekir")
    slug = slugify(name or "benim-sesim", 40)
    d = VOICES / slug
    (d / "rec").mkdir(parents=True, exist_ok=True)
    prof = read_json(d / "profile.json") or {"slug": slug, "name": name or "Benim sesim", "created": now(),
                                              "turns": [], "speech_sec": 0.0, "status": "collecting"}
    prof.update(consent={"given": True, "at": now(), "text": "Bu ses bana ait ve kopyalanmasına izin veriyorum."})
    q = OPENING if not prof["turns"] else "Kaldığımız yerden devam edelim. " + next_question(prof, load_config())
    prof["pending_question"] = q
    write_json(d / "profile.json", prof)
    return {"slug": slug, "question": q, "speech_sec": prof["speech_sec"], "target": TARGET_SPEECH_SEC}


def next_question(prof: dict, cfg: Config) -> str:
    turns = prof["turns"]
    left = TARGET_SPEECH_SEC - prof["speech_sec"]
    used = {t["question"] for t in turns}
    if left < 75:  # sona doğru farklı tonlarda okuma: ses yelpazesini genişletir
        for r in READING:
            if r not in used:
                return r
    if turns and len(turns) % 2 == 1:
        q = ai_followup(turns, cfg)
        if q:
            return q
    pool = [q for q in QUESTIONS if q not in used] or QUESTIONS
    return random.choice(pool)


def ai_followup(turns: list[dict], cfg: Config) -> str | None:
    from .llm import _client, available, claude_cli, resolve_provider
    convo = "\n".join(f"Soru: {t['question']}\nCevap: {t.get('transcript', '')}" for t in turns[-4:])
    prompt = ("Bir kullanıcıyla sesini tanımak için samimi, kısa bir sohbet yapıyorsun. Son konuşmalar:\n" + convo +
              "\n\nCevaba doğal tepki veren ve uzun cevap gerektiren TEK bir kısa Türkçe soru yaz (en fazla 25 kelime)."
              " Kişisel/hassas bilgi (adres, sağlık, para, kimlik) sorma. Yalnızca soruyu yaz.")
    try:
        p = resolve_provider(cfg)
        if p == "anthropic" and available():
            msg = _client().messages.create(model=cfg.get_path("llm.anthropic.model", "claude-opus-5-5"),
                                            max_tokens=200, messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        elif p == "claude_cli":
            proc = subprocess.run([claude_cli(), "-p", prompt], capture_output=True, encoding="utf-8",
                                  errors="replace", timeout=40, stdin=subprocess.DEVNULL, cwd=ROOT)
            text = proc.stdout
        else:
            return None
    except Exception as exc:  # noqa: BLE001 — sohbet soru bankasıyla sürer
        L.debug("takip sorusu üretilemedi: %s", exc)
        return None
    text = " ".join(text.strip().strip('"').split())
    return text if 5 < len(text) < 220 and text.endswith("?") else None


def add_answer(slug: str, data: bytes, ext: str = "webm") -> dict:
    cfg = load_config()
    d = vdir(slug)
    prof = read_json(d / "profile.json")
    n = len(prof["turns"]) + 1
    raw = d / "rec" / f"{n:03d}_raw.{ext if ext in ('webm', 'ogg', 'wav', 'mp4', 'm4a') else 'webm'}"
    raw.write_bytes(data)
    clean = enhance(raw, d / "rec" / f"{n:03d}.wav")
    sp = speech_seconds(clean)
    transcript = ""
    if sp > 0.8:
        try:
            from .studio import transcribe
            # ekran kartı varsa büyük model (large-v3-turbo): Türkçe konuşmayı çok daha doğru anlar
            transcript = " ".join(w["word"] for w in transcribe(clean, d / "rec", cfg))
            (d / "rec" / "words_cfg_0.json").replace(d / "rec" / f"{n:03d}.words.json")
        except Exception as exc:  # noqa: BLE001
            L.warning("yazıya dökülemedi: %s", exc)
    turn = {"n": n, "question": prof.get("pending_question", ""), "file": clean.name, "speech_sec": round(sp, 1),
            "transcript": transcript}
    if sp > 0.8:
        prof["turns"].append(turn)
        prof["speech_sec"] = round(prof["speech_sec"] + sp, 1)
        q = next_question(prof, cfg)
    else:
        clean.unlink(missing_ok=True)
        q = "Seni duyamadım, mikrofon açık mı? " + (prof.get("pending_question") or OPENING)
    prof["pending_question"] = q
    write_json(d / "profile.json", prof)
    return {"transcript": transcript, "speech_sec": prof["speech_sec"], "turn_speech": round(sp, 1),
            "question": q, "target": TARGET_SPEECH_SEC, "enough": prof["speech_sec"] >= MIN_SPEECH_SEC}


# ----------------------------------------------------------------------------
# Ses dönüşümü (kNN-VC)
# ----------------------------------------------------------------------------

_MODEL = None
_LOCK = threading.Lock()

# ----------------------------------------------------------------------------
# Klon motoru (Chatterbox Multilingual, ekran kartı; ayrı Python ortamı)
# ----------------------------------------------------------------------------
CLONE_ENV = ROOT / "studio" / "cache" / "venv-tts"
CLONE_PY = CLONE_ENV / ("Scripts/python.exe" if __import__("sys").platform.startswith("win") else "bin/python")
WORKER = Path(__file__).with_name("tts_worker.py")
_CLONE_OK: dict = {}


def clone_available() -> bool:
    """Klon motoru kurulu mu (torch CUDA + chatterbox)? Sonuç önbelleğe alınır."""
    if "ok" not in _CLONE_OK:
        ok = False
        stamp = ROOT / "studio" / "cache" / "clone_ok.json"   # diskte önbellek: sunucu her açılışta motoru yüklemesin
        key = str(CLONE_PY.stat().st_mtime) if CLONE_PY.exists() else ""
        old = read_json(stamp, {}) or {}
        if key and old.get("key") == key:
            _CLONE_OK.update(ok=bool(old.get("ok")), gpu=bool(old.get("gpu")))
            return _CLONE_OK["ok"]
        if CLONE_PY.exists():
            try:
                r = subprocess.run([str(CLONE_PY), "-c", "import chatterbox.mtl_tts, torch; print(torch.cuda.is_available())"],
                                   capture_output=True, text=True, timeout=180)
                ok = r.returncode == 0
                _CLONE_OK["gpu"] = r.stdout.strip() == "True"
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        _CLONE_OK["ok"] = ok
        if key:
            write_json(stamp, {"key": key, "ok": ok, "gpu": bool(_CLONE_OK.get("gpu"))})
    return _CLONE_OK["ok"]


def clone_status() -> dict:
    ok = clone_available()
    return {"available": ok, "gpu": bool(_CLONE_OK.get("gpu")), "installed": CLONE_PY.exists(),
            "engine": "Chatterbox Multilingual (MIT) · ekran kartı" if ok and _CLONE_OK.get("gpu") else
            "Chatterbox Multilingual (işlemci, yavaş)" if ok else None}


def tune(slug: str, data: dict) -> dict:
    """Klon ayarları: duygu 0.25-1.0 (exaggeration), benzerlik 0.2-0.8 (cfg_weight; düşük = daha sakin, ağır)."""
    d = vdir(slug)
    prof = read_json(d / "profile.json")
    c = prof.get("clone") or {}
    for k, lo, hi in (("exaggeration", 0.25, 1.0), ("cfg_weight", 0.2, 0.8), ("temperature", 0.5, 1.0)):
        if data.get(k) is not None:
            c[k] = round(max(lo, min(hi, float(data[k]))), 2)
    prof["clone"] = c
    write_json(d / "profile.json", prof)
    return c


def clone_reference(slug: str, force: bool = False, turn_file: str | None = None) -> Path:
    """Kayıtlardan klon için en temiz ~10 sn'lik örneği seçer: sürekli konuşma, düşük gürültü, dengeli seviye.
    turn_file verilirse yalnızca o kayıttan seçer (Sesim sayfasında "bu kaydı örnek al")."""
    d = vdir(slug)
    dest = d / "clone_ref.wav"
    if dest.exists() and not force:
        return dest
    prof = read_json(d / "profile.json")
    best = None
    for t in prof.get("turns", []):
        if turn_file and t["file"] != Path(str(turn_file)).name:
            continue
        f = d / "rec" / t["file"]
        if not f.exists() or (t.get("speech_sec") or 0) < 6:
            continue
        a = load_audio(f, 16000, 1)
        hop = 320
        n = len(a) // hop
        if n < 300:
            continue
        db = 20 * np.log10(np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12))
        win = 500   # 10 sn
        speech = (db > -38).astype(float)
        cs = np.concatenate([[0], np.cumsum(speech)])
        for st in range(0, max(1, n - win), 25):
            ratio = (cs[min(n, st + win)] - cs[st]) / win
            seg = db[st:st + win]
            noise = float(np.percentile(seg, 10))
            level_var = float(np.std(seg[seg > -38])) if (seg > -38).any() else 99.0
            clip = float((np.abs(a[st * hop:(st + win) * hop]) > 0.98).mean())
            score = ratio * 3 - max(0.0, noise + 60) * 0.03 - level_var * 0.05 - clip * 50
            if best is None or score > best[0]:
                best = (score, f, st * hop / 16000)
    if not best:
        raise StageError("klon için yeterince uzun, temiz bir kayıt yok (en az 6 sn kesintisiz konuşma)")
    _, f, t0 = best
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.2f}", "-t", "10.5", "-i", f, "-af",
         "highpass=f=70,afftdn=nf=-30,loudnorm=I=-20:TP=-2:LRA=7", "-ar", "24000", "-ac", "1", dest])
    prof["clone_ref"] = {"file": f.name, "start": round(t0, 2), "at": now()}
    write_json(d / "profile.json", prof)
    L.info("Klon örneği seçildi: %s @ %.1f sn", f.name, t0)
    return dest


def clone_batch(slug: str, items: list[tuple[str, Path]], check: bool = True, timeout: int = 1800) -> list[dict]:
    """Metinleri kullanıcının sesiyle okur (tek seferde; model bir kez yüklenir). Her çıktı için meta (kelimeler)."""
    ref = clone_reference(slug)
    prof = read_json(vdir(slug) / "profile.json")
    tune = prof.get("clone") or {}
    jobf = vdir(slug) / "_clone_job.json"
    write_json(jobf, {"ref": str(ref), "check": check, "exaggeration": tune.get("exaggeration", 0.5),
                      "cfg_weight": tune.get("cfg_weight", 0.5), "temperature": tune.get("temperature", 0.8),
                      "items": [{"text": t, "out": str(o)} for t, o in items]})
    with _LOCK:
        r = subprocess.run([str(CLONE_PY), str(WORKER), str(jobf)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise StageError("kendi sesinle seslendirme başarısız: " + (r.stderr or r.stdout)[-500:])
    metas = [read_json(Path(o).with_suffix(".json")) or {} for _, o in items]
    target = float(tune.get("rate") or prof.get("rate_syll_sec") or 0)
    for (_, o), meta in zip(items, metas):
        _match_rate(Path(o), meta, target)
    return metas


def _match_rate(wav: Path, meta: dict, target: float) -> None:
    """Klon ses kullanıcıdan yavaş okuyorsa kullanıcının kendi konuşma hızına (hece/sn) hızlandırır (perde değişmez)."""
    words = meta.get("words") or []
    if not words or target <= 0:
        return
    dur = max(0.5, words[-1]["end"] - words[0]["start"])
    rate = sum(syllables(w["text"]) for w in words) / dur
    factor = max(1.0, min(1.22, (target * 0.92) / max(rate, 0.1)))   # %8 pay: okuma, sohbetten biraz yavaş olmalı
    if factor < 1.03:
        return
    tmp = wav.with_suffix(".tempo.wav")
    run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-af", f"atempo={factor:.3f}", tmp])
    tmp.replace(wav)
    for w in words:
        w["start"], w["end"] = round(w["start"] / factor, 3), round(w["end"] / factor, 3)
    meta.update(words=words, tempo=round(factor, 3))
    write_json(wav.with_suffix(".json"), meta)


def asr_gpu(wav: Path, prompt: str = "") -> dict | None:
    """Ekran kartıyla (large-v3-turbo) konuşma tanıma; klon ortamı yoksa None."""
    if not clone_available():
        return None
    r = subprocess.run([str(CLONE_PY), str(WORKER), "--asr", str(wav), prompt[:200]], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0:
        L.warning("GPU konuşma tanıma başarısız: %s", (r.stderr or "")[-300:])
        return None
    return json.loads(r.stdout.strip().splitlines()[-1])


TORCH_PKGS = ["torch==2.7.1", "torchaudio==2.7.1"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"


def install_engine() -> None:
    """Ses motorunu (PyTorch CPU, ~250 MB) bu Python ortamına kurar."""
    import sys
    L.info("Ses motoru kuruluyor (PyTorch CPU, ~250 MB)...")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", *TORCH_PKGS, "--index-url", TORCH_INDEX],
                          capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise StageError("PyTorch kurulamadı: " + (proc.stderr or proc.stdout)[-400:])
    L.info("Ses motoru kuruldu")


def engine_status() -> dict:
    from .knnvc import CACHE, WEIGHTS
    models = all((CACHE / n).exists() and (CACHE / n).stat().st_size == sz for n, sz in WEIGHTS.items())
    return {"engine": engine_available(), "models": models}


def engine_available() -> bool:
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        return True
    except ImportError:
        return False


def model():
    """kNN-VC (WavLM-Large + HiFi-GAN). İlk kullanımda ~1.3 GB ağırlık studio/cache/models altına indirilir."""
    global _MODEL
    if _MODEL is None:
        if not engine_available():
            raise StageError("Ses motoru kurulu değil: pip install torch torchaudio "
                             "--index-url https://download.pytorch.org/whl/cpu")
        import torch
        L.info("Ses modeli yükleniyor (ilk seferde ~1.3 GB indirilir)...")
        torch.set_num_threads(max(1, (__import__("os").cpu_count() or 2) - 1))
        from .knnvc import load
        _MODEL = load("cpu")
    return _MODEL


def _tensor(wav: Path):
    import torch
    return torch.from_numpy(load_audio(wav, 16000, 1)).unsqueeze(0)


def convert(src: Path, dest: Path, slug: str) -> Path:
    """src konuşmasını kullanıcının ses rengine çevirir (aynı süre)."""
    import torch
    d = vdir(slug)
    ms_path = d / "matching_set.pt"
    if not ms_path.exists():
        raise StageError("ses profili hazır değil (önce 'Sesimi öğren')")
    with _LOCK:
        m = model()
        matching = torch.load(ms_path, weights_only=True)
        with torch.inference_mode():
            q = m.get_features(_tensor(src))
            out = m.match(q, matching, topk=4)
    write_wav(dest, out.numpy().astype(np.float32), 16000)
    return dest


def build(slug: str, on_stage=None) -> dict:
    """Kayıtlardan profil çıkarır: referans, perde, hız, temel ses ve eşleştirme kümesi; örnek okuma üretir."""
    import torch
    cfg = load_config()
    d = vdir(slug)
    prof = read_json(d / "profile.json")
    stage = on_stage or (lambda s: L.info("[ses %s] %s", slug, s))
    if prof["speech_sec"] < MIN_SPEECH_SEC:
        raise StageError(f"en az {MIN_SPEECH_SEC} sn konuşma gerekli (şu an {prof['speech_sec']:.0f} sn)")
    prof["status"] = "building"
    prof.pop("error", None)
    write_json(d / "profile.json", prof)
    try:
        stage("kayıtlar birleştiriliyor")
        files = [d / "rec" / t["file"] for t in prof["turns"] if (d / "rec" / t["file"]).exists()]
        lst = d / "concat.txt"
        lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
        ref = d / "reference.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-af",
             "silenceremove=stop_periods=-1:stop_duration=0.6:stop_threshold=-40dB", "-ac", "1", "-ar", "48000", ref])
        f0 = pitch_hz(ref)
        words = sum(len(t.get("transcript", "").split()) for t in prof["turns"])
        sylls = sum(syllables(w) for t in prof["turns"] for w in t.get("transcript", "").split())
        rate = sylls / max(prof["speech_sec"], 1)
        gender = "male" if 0 < f0 < 160 else "female"
        stage(f"ses tonu ölçüldü: {f0:.0f} Hz ({'kalın' if gender == 'male' else 'ince'}), {rate:.1f} hece/sn")

        stage("temel ses ayarlanıyor")
        from .tts import _edge_synth
        probe_text = "Merhaba arkadaşlar, bugün size çok ilginç bir konudan bahsedeceğim, sonuna kadar izleyin."
        bases = {}
        order = [BASE_VOICES[gender]] + [v for v in BASE_VOICES.values() if v != BASE_VOICES[gender]]
        for v in order:  # her temel ses için hız/perde ayarı; hizmet kesintisinde yeniden denenir
            mp3 = d / "base_probe.mp3"
            marks = None
            for attempt in range(3):  # yalnızca kadın sesi kalırsa erkek sese dönüşüm bozuk çıkıyordu
                try:
                    marks = _edge_synth(probe_text, v, "+0%", "+0Hz", mp3)
                    break
                except Exception as exc:  # noqa: BLE001
                    L.warning("temel ses %s kullanılamadı (deneme %d): %s", v, attempt + 1, exc)
                    __import__("time").sleep(2 + 3 * attempt)
            if marks is None:
                continue
            bf0 = pitch_hz(mp3)
            dur = (marks[-1]["end"] - marks[0]["start"]) if marks else 5.0
            brate = sum(syllables(w) for w in probe_text.split()) / max(dur, 0.5)
            rate_pct = int(max(-20, min(25, round((rate / brate - 1) * 100)))) if rate > 0 else 0
            # Perde kaydırılmaz: kNN-VC perdeyi kullanıcının kayıtlarından taşır; temel seste kaydırma (ör. -80 Hz)
            # WavLM özniteliklerini bozup anlaşılırlığı %89'dan %17'ye düşürüyor (ölçüldü).
            bases[v] = {"f0": round(bf0, 1), "rate": f"{rate_pct:+d}%", "pitch": "+0Hz"}
        if not bases:
            raise StageError("temel Türkçe ses (edge-tts) kullanılamadı; internet bağlantısını kontrol edin")

        if clone_available():
            stage("klon örneği seçiliyor (en temiz 10 sn)")
            clone_reference(slug, force=True)
        stage("ses rengi öğreniliyor (ilk seferde model indirilir; birkaç dakika sürebilir)")
        m = model()
        with torch.inference_mode():
            matching = m.get_matching_set([_tensor(f) for f in files])
        torch.save(matching, d / "matching_set.pt")

        prof.update(f0=round(f0, 1), base_voice=next(iter(bases)), bases=bases, rate_syll_sec=round(rate, 2),
                    words=words, built=now(), reference_sec=round(prof["speech_sec"], 1))
        write_json(d / "profile.json", prof)

        stage("örnek okuma üretiliyor")
        sample = speak(slug, "Merhaba! Bu benim sesim, ama bu cümleyi ben okumadım. Reels Fabrikası beni dinleyip "
                             "sesimi öğrendi. Nasıl, benziyor mu?", d / "preview.wav")
        prof.update(status="ready", preview=str(sample.relative_to(ROOT)), preview_engine="klon" if clone_available() else "knn",
                    sample=str((d / "rec" / prof["turns"][0]["file"]).relative_to(ROOT)))
        write_json(d / "profile.json", prof)
        return prof
    except Exception as exc:
        prof.update(status="failed", error=str(exc)[:500])
        write_json(d / "profile.json", prof)
        raise


def tts_raw(slug: str, text: str, mp3: Path) -> list[dict]:
    """Temel sesle, kullanıcının hızı ve perdesine yakın okuma (kelime zamanlarıyla)."""
    from .tts import _edge_synth
    prof = read_json(vdir(slug) / "profile.json")
    last: Exception | None = None
    for v, b in (prof.get("bases") or {HOST_VOICE: {"rate": "+0%", "pitch": "+0Hz"}}).items():
        try:
            return _edge_synth(text, v, b["rate"], b["pitch"], mp3)
        except Exception as exc:  # noqa: BLE001 — sıradaki temel sesi dene
            last = exc
    raise StageError(f"temel ses üretilemedi: {last}")


def speak(slug: str, text: str, dest: Path, engine: str = "auto") -> Path:
    """Metni kullanıcının sesiyle okur. engine: auto (klon varsa klon) | klon | knn"""
    if engine in ("auto", "klon") and clone_available():
        raw = dest.with_suffix(".clone.wav")
        clone_batch(slug, [(text, raw)])
        enhance(raw, dest, strength="hafif")
        raw.unlink(missing_ok=True)
        raw.with_suffix(".json").unlink(missing_ok=True)
        return dest
    tmp = dest.with_suffix(".base.mp3")
    tts_raw(slug, text, tmp)
    out = convert(tmp, dest.with_suffix(".vc.wav"), slug)
    enhance(out, dest, strength="hafif")  # dönüştürülmüş ses temizdir: yalnızca ton ve seviye
    tmp.unlink(missing_ok=True)
    out.unlink(missing_ok=True)
    return dest


# ----------------------------------------------------------------------------
# Profiller
# ----------------------------------------------------------------------------

def active() -> str | None:
    a = read_json(ACTIVE) or {}
    slug = a.get("slug")
    if slug and (VOICES / slug / "matching_set.pt").exists():
        return slug
    return None


def set_active(slug: str | None) -> None:
    if slug:
        p = read_json(vdir(slug) / "profile.json")
        if p.get("status") != "ready":
            raise StageError("ses profili hazır değil")
    write_json(ACTIVE, {"slug": slug, "at": now()})


def profiles() -> list[dict]:
    act = active()
    out = []
    for f in sorted(VOICES.glob("*/profile.json")) if VOICES.exists() else []:
        p = read_json(f)
        out.append({k: p.get(k) for k in ("slug", "name", "status", "speech_sec", "f0", "base_voice", "rate_syll_sec",
                                           "preview", "sample", "error", "built", "created", "clone", "clone_ref",
                                           "preview_engine")}
                   | {"turns": len(p.get("turns", [])), "active": p.get("slug") == act, "target": TARGET_SPEECH_SEC})
    return out
