"""Hoparlör ses ayarı (ekolayzır): Logitech Z607 ve diğer hoparlörler için bas/tiz, müzik türü hazırları, kanal düzeyi.

Logitech, Z607 için bilgisayarda ekolayzır programı sunmaz (kumanda/ön panel yalnızca ses, kaynak ve bas düzeyi).
Bu yüzden ayar Windows'ta bütün sisteme uygulanan ücretsiz, açık kaynak **Equalizer APO** ile yapılır:
`<APO>/config/heloo-hoparlor.txt` dosyasına her hoparlör için ayrı bir blok yazılır (`Device: {uç nokta GUID}`) ve
`config.txt` bu dosyayı `Include:` ile bir kez içeri alır. Equalizer APO dosya değişince sesi anında günceller;
bilgisayarda hangi hoparlör seçiliyse onun ayarı çalışır.

Ayarlar `studio/hoparlor/ayarlar.json` dosyasında. Sayfa: `app/hoparlor.html` (`/hoparlor`), CLI: `factory.py hoparlor`.
"""
from __future__ import annotations

import cmath
import json
import math
import os
import subprocess
from pathlib import Path

from .config import ROOT

STATE = ROOT / "studio" / "hoparlor" / "ayarlar.json"
APO_FILE = "heloo-hoparlor.txt"
APO_INCLUDE = f"Include: {APO_FILE}"
APO_URL = "https://sourceforge.net/projects/equalizerapo/"
FS = 48000.0

BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
BAND_Q = 1.41          # bir oktav genişliğinde tepe süzgeci
LIMIT = 12.0           # tek bir sürgü en çok ±12 dB

# Müzik türü hazırları (10 bant, dB). Yaygın ekolayzır uygulamalarındaki (Windows Media Player, Spotify, Poweramp,
# Wavelet) eğrilerin ılımlı hâli; türkü/arabesk bağlama ve vokal bölgesini (1–4 kHz) öne alır.
PRESETS: dict[str, dict] = {
    "duz":       {"ad": "Düz",          "b": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
    "pop":       {"ad": "Pop",          "b": [-1, 1, 3, 4, 2, 0, -1, 0, 1, 2]},
    "rock":      {"ad": "Rock",         "b": [4, 3, 2, 0, -1, -1, 1, 3, 4, 4]},
    "rnb":       {"ad": "R&B",          "b": [3, 6, 5, 1, -2, -1, 1, 2, 3, 3]},
    "hiphop":    {"ad": "Hip-hop / Rap", "b": [5, 5, 3, 1, -1, -1, 1, 0, 1, 2]},
    "caz":       {"ad": "Caz",          "b": [3, 2, 1, 2, -1, -1, 0, 1, 2, 3]},
    "klasik":    {"ad": "Klasik",       "b": [3, 2, 1, 0, -1, -1, 0, 1, 2, 3]},
    "turku":     {"ad": "Türkü / Halk", "b": [0, 1, 1, 0, 1, 2, 3, 3, 2, 1]},
    "arabesk":   {"ad": "Arabesk",      "b": [1, 2, 2, 0, 0, 1, 2, 2, 1, 1]},
    "elektronik": {"ad": "Elektronik",  "b": [5, 4, 1, 0, -2, 0, 1, 2, 4, 5]},
    "akustik":   {"ad": "Akustik",      "b": [2, 1, 1, 1, 2, 1, 2, 2, 2, 1]},
    "bas":       {"ad": "Bol bas",      "b": [7, 6, 4, 2, 0, 0, 0, 0, 0, 0]},
    "film":      {"ad": "Film / Dizi",  "b": [4, 3, 1, 0, 0, 1, 2, 1, 2, 2], "merkez": 3},
    "konusma":   {"ad": "Konuşma / Podcast", "b": [-4, -3, -1, 0, 2, 3, 4, 3, 1, 0], "merkez": 2},
    "oyun":      {"ad": "Oyun",         "b": [3, 2, 0, -1, 0, 1, 3, 3, 2, 1]},
    "gece":      {"ad": "Gece (kısık ses)", "b": [-4, -3, -2, 0, 1, 2, 2, 1, 0, -1]},
}

# Hoparlör türleri: koruma için alçak kesim (hp) ve en çok yükseltme. Hoparlörün çalamadığı derin bası yükseltmek
# yalnızca bozulma/tıkırtı getirir; bu bantlar 0'ın üstüne çıkmaz.
KINDS: dict[str, dict] = {
    "z607":      {"ad": "Logitech Z607 5.1", "hp": 35, "max": 10, "kanal": "5.1"},
    "masaustu":  {"ad": "Masaüstü hoparlör (2.0/2.1)", "hp": 45, "max": 9, "kanal": "2.1"},
    "soundbar":  {"ad": "Soundbar", "hp": 45, "max": 9, "kanal": "2.1"},
    "bluetooth": {"ad": "Taşınabilir Bluetooth hoparlör", "hp": 70, "max": 8, "kanal": "2.0"},
    "laptop":    {"ad": "Dizüstü dahili hoparlör", "hp": 150, "max": 6, "kanal": "2.0"},
    "kulaklik":  {"ad": "Kulaklık", "hp": 0, "max": 10, "kanal": "2.0"},
}

TIPS = {
    "z607": [
        "Z607'de bilgisayar ekolayzırı yok; kumandada/ön panelde ses, kaynak (Bluetooth, AUX, RCA, FM, USB/SD) ve bas düzeyi var. "
        "Kumandadaki bas düzeyini ortada bırakıp ince ayarı buradan yap; ikisini birden sonuna açmak bası boğuklaştırır.",
        "Bu ayarlar bilgisayardan çalan sese uygulanır (kablo ya da bilgisayarın Bluetooth'u). Telefondan Z607'ye "
        "Bluetooth ile çalarken telefonun kendi ekolayzırını kullan.",
        "5.1 için Windows'ta Ses ayarları → Hoparlörler → Yapılandır → 5.1 Surround seç; sonra Subwoofer / Merkez / Arka sürgüleri çalışır.",
        "Subwoofer'ı duvardan 20-30 cm uzağa, yere koy; köşe bası abartır, arka hoparlörleri kulak hizasının biraz üstüne yerleştir.",
    ],
    "laptop": ["Dahili hoparlör 150 Hz altını çalamaz; bas yerine 'Vokal' ve 'Orta'yı biraz açmak sesi daha dolu duyurur."],
    "bluetooth": ["Telefondan doğrudan çalıyorsan bu ayarlar uygulanmaz; yalnızca bilgisayara bağlıyken çalışır."],
}

SIMPLE = {  # sade sürgüler: (süzgeç türü, merkez frekans, Q)
    "bas": ("LSC", 105.0, 0.71),
    "orta": ("PK", 900.0, 0.7),
    "vokal": ("PK", 3000.0, 1.0),
    "tiz": ("HSC", 8000.0, 0.71),
}
CHANNELS = {"sub": "SUB", "merkez": "C", "arka": "RL RR SL SR"}


# ---------------------------------------------------------------- ayarlar
def default_settings(preset: str = "duz") -> dict:
    p = PRESETS.get(preset, PRESETS["duz"])
    return {"acik": True, "preset": preset, "bands": list(p["b"]), "bas": 0.0, "orta": 0.0, "vokal": 0.0, "tiz": 0.0,
            "yukseklik": 0.0, "sub": 0.0, "merkez": float(p.get("merkez", 0)), "arka": 0.0}


def default_state() -> dict:
    return {"active": "z607", "speakers": [
        {"id": "z607", "ad": "Logitech Z607", "kind": "z607", "device": "", "device_ad": "", "settings": default_settings()}]}


def load_state() -> dict:
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(st, dict) and st.get("speakers"):
            return st
    except (OSError, ValueError):
        pass
    return default_state()


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE)


def _num(v, lo: float = -LIMIT, hi: float = LIMIT) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return round(min(hi, max(lo, x)), 1) if math.isfinite(x) else 0.0


def clean_settings(s: dict | None) -> dict:
    s = dict(s or {})
    out = default_settings(s.get("preset") if s.get("preset") in PRESETS else "duz")
    out["preset"] = s.get("preset") if s.get("preset") in PRESETS or s.get("preset") == "ozel" else out["preset"]
    out["acik"] = bool(s.get("acik", True))
    b = s.get("bands")
    if isinstance(b, list) and len(b) == len(BANDS):
        out["bands"] = [_num(x) for x in b]
    for k in ("bas", "orta", "vokal", "tiz", "sub", "merkez", "arka"):
        if k in s:
            out[k] = _num(s[k])
    out["yukseklik"] = _num(s.get("yukseklik", 0), -20, 6)
    return out


def _slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = "".join(c if c.isalnum() else "-" for c in text.translate(tr).lower()).strip("-")
    return "-".join(p for p in s.split("-") if p)[:40] or "hoparlor"


def add_speaker(st: dict, ad: str, kind: str = "masaustu", device: str = "", device_ad: str = "") -> dict:
    ad = (ad or "").strip()[:60] or KINDS.get(kind, KINDS["masaustu"])["ad"]
    base, n, ids = _slug(ad), 2, {sp["id"] for sp in st["speakers"]}
    sid = base
    while sid in ids:
        sid, n = f"{base}-{n}", n + 1
    sp = {"id": sid, "ad": ad, "kind": kind if kind in KINDS else "masaustu", "device": _guid(device),
          "device_ad": (device_ad or "")[:120], "settings": default_settings()}
    st["speakers"].append(sp)
    st["active"] = sid
    return sp


def find(st: dict, sid: str | None) -> dict:
    for sp in st["speakers"]:
        if sp["id"] == (sid or st.get("active")):
            return sp
    return st["speakers"][0]


def _guid(s: str) -> str:
    s = (s or "").strip()
    i, j = s.rfind("{"), s.rfind("}")
    g = s[i:j + 1] if 0 <= i < j else ""
    return g if len(g) == 38 and all(c in "0123456789abcdefABCDEF-{}" for c in g) else ""


# ---------------------------------------------------------------- süzgeçler
def filters(settings: dict, kind: str) -> list[tuple[str, float, float, float]]:
    """(tür, frekans, kazanç dB, Q). Hoparlörün çalamadığı derin bantlar koruma için 0'ın üstüne çıkmaz."""
    k = KINDS.get(kind, KINDS["masaustu"])
    s = clean_settings(settings)
    mx = float(k["max"])
    out: list[tuple[str, float, float, float]] = []
    if k["hp"]:
        out.append(("HP", float(k["hp"]), 0.0, 0.71))
    for f, g in zip(BANDS, s["bands"]):
        g = min(g, mx)
        if k["hp"] and f < k["hp"] * 1.3:
            g = min(g, 0.0)
        if g:
            out.append(("PK", float(f), g, BAND_Q))
    for key, (typ, f, q) in SIMPLE.items():
        g = min(s[key], mx)
        if key == "bas" and k["hp"] >= 100:
            g = min(g, 3.0)
        if g:
            out.append((typ, f, g, q))
    return out


def _coeffs(typ: str, f: float, g: float, q: float):
    a = 10 ** (g / 40)
    w = 2 * math.pi * f / FS
    cw, sw = math.cos(w), math.sin(w)
    al = sw / (2 * q)
    if typ == "PK":
        return (1 + al * a, -2 * cw, 1 - al * a), (1 + al / a, -2 * cw, 1 - al / a)
    if typ == "HP":
        return ((1 + cw) / 2, -(1 + cw), (1 + cw) / 2), (1 + al, -2 * cw, 1 - al)
    r = 2 * math.sqrt(a) * al
    if typ == "LSC":
        return ((a * ((a + 1) - (a - 1) * cw + r), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - r)),
                ((a + 1) + (a - 1) * cw + r, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - r))
    return ((a * ((a + 1) + (a - 1) * cw + r), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - r)),
            ((a + 1) - (a - 1) * cw + r, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - r))


def response(flt: list, freqs: list[float]) -> list[float]:
    """Süzgeç zincirinin frekans yanıtı (dB)."""
    cs = [_coeffs(*x) for x in flt]
    out = []
    for f in freqs:
        z = cmath.exp(-1j * 2 * math.pi * f / FS)
        h = 1 + 0j
        for b, a in cs:
            h *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        out.append(20 * math.log10(max(abs(h), 1e-9)))
    return out


def curve_freqs(n: int = 120) -> list[float]:
    return [20 * (1000 ** (i / (n - 1))) for i in range(n)]   # 20 Hz – 20 kHz, logaritmik


def analyse(settings: dict, kind: str) -> dict:
    s = clean_settings(settings)
    flt = filters(s, kind)
    fr = curve_freqs()
    curve = response(flt, fr) if flt else [0.0] * len(fr)
    peak = max([0.0, *curve[3:]])           # 20-25 Hz zaten kesiliyor
    chans = {k: s[k] for k in CHANNELS} if KINDS.get(kind, {}).get("kanal") == "5.1" else {}
    chan_peak = max([0.0, *chans.values()])
    preamp = round(s["yukseklik"] - peak - chan_peak, 1)    # cızırtı olmasın diye en yüksek nokta kadar kıs
    return {"filters": flt, "freqs": [round(f, 1) for f in fr], "curve": [round(c, 2) for c in curve],
            "preamp": preamp, "channels": chans, "settings": s}


# ---------------------------------------------------------------- Equalizer APO
def block(sp: dict) -> str:
    kind = sp.get("kind", "masaustu")
    lines = [f"# {sp.get('ad', '')} ({KINDS.get(kind, KINDS['masaustu'])['ad']})"
             + (f" — {sp['device_ad']}" if sp.get("device_ad") else "")]
    lines.append(f"Device: {sp['device']}" if sp.get("device") else "Device: all")
    s = clean_settings(sp.get("settings"))
    if not s["acik"]:
        lines.append("# kapalı (düz ses)")
        return "\n".join(lines)
    an = analyse(s, kind)
    lines.append(f"Preamp: {an['preamp']:.1f} dB")
    for typ, f, g, q in an["filters"]:
        if typ == "HP":
            lines.append(f"Filter: ON HP Fc {f:g} Hz Q {q:.2f}")
        else:
            lines.append(f"Filter: ON {typ} Fc {f:g} Hz Gain {g:.1f} dB Q {q:.2f}")
    if any(an["channels"].values()):
        for key, ch in CHANNELS.items():
            if an["channels"].get(key):
                lines += [f"Channel: {ch}", f"Preamp: {an['channels'][key]:.1f} dB"]
        lines.append("Channel: all")
    return "\n".join(lines)


def apo_config(st: dict) -> str:
    """Bütün hoparlörlerin blokları. Aygıtı seçilmemiş hoparlör yalnızca etkinse ve tek başınaysa 'all' olarak yazılır."""
    head = ["# Heloo hoparlör ayarı — bu dosya /hoparlor sayfasından yazılır, elle değiştirme.", ""]
    with_dev = [sp for sp in st["speakers"] if sp.get("device")]
    act = find(st, st.get("active"))
    blocks = [block(sp) for sp in with_dev]
    if not act.get("device"):   # aygıt seçilmemiş: etkin hoparlörün ayarı varsayılan çıkışa
        blocks.insert(0, block(act))
    return "\n".join(head + ["\n\n".join(blocks), "", "Device: all", ""])


def apo_dir() -> Path | None:
    if os.name != "nt":
        return None
    cands = []
    try:
        import winreg
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO", 0, winreg.KEY_READ | view) as k:
                    cands.append(Path(winreg.QueryValueEx(k, "ConfigPath")[0]))
            except OSError:
                continue
    except ImportError:
        pass
    cands.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "EqualizerAPO" / "config")
    return next((c for c in cands if (c / "config.txt").exists() or c.is_dir()), None)


def apply(st: dict | None = None) -> dict:
    """Ayarı Equalizer APO'ya yaz. Dönüş: {ok, path} ya da {needs_apo} / {needs_admin}."""
    st = st or load_state()
    text = apo_config(st)
    d = apo_dir()
    if not d:
        return {"ok": False, "needs_apo": True, "url": APO_URL, "config": text,
                "msg": "Equalizer APO kurulu değil. Kur, kurulumda Z607'nin bağlı olduğu çıkışı (Hoparlörler) işaretle, "
                       "bilgisayarı yeniden başlat."}
    target, main = d / APO_FILE, d / "config.txt"
    try:
        target.write_text(text, encoding="utf-8")
        cur = main.read_text(encoding="utf-8", errors="replace") if main.exists() else ""
        if APO_INCLUDE not in cur:
            with main.open("a", encoding="utf-8") as fh:
                fh.write(("\n" if cur and not cur.endswith("\n") else "") + APO_INCLUDE + "\n")
    except PermissionError:
        return {"ok": False, "needs_admin": True, "config": text, "path": str(d),
                "msg": "Equalizer APO klasörüne yazmak için bir kez yönetici izni gerekiyor ('İzin ver')."}
    return {"ok": True, "path": str(target), "config": text}


def grant_permission() -> dict:
    """Bir kerelik yönetici izni (UAC): dosyayı oluşturur, config.txt'ye Include ekler, kullanıcılara yazma izni verir."""
    d = apo_dir()
    if not d:
        return {"ok": False, "needs_apo": True, "url": APO_URL}
    ps = ROOT / "studio" / "hoparlor" / "izin.ps1"
    ps.parent.mkdir(parents=True, exist_ok=True)
    f, m = str(d / APO_FILE).replace("'", "''"), str(d / "config.txt").replace("'", "''")
    ps.write_text("\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$f = '{f}'; $m = '{m}'",
        "if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }",
        f"if (-not (Test-Path $m) -or -not (Select-String -Path $m -SimpleMatch '{APO_INCLUDE}' -Quiet)) {{",
        f"  Add-Content -Path $m -Value '{APO_INCLUDE}' -Encoding UTF8 }}",
        "icacls $f /grant '*S-1-5-32-545:(M)' | Out-Null",   # Users grubu (dil bağımsız SID)
    ]), encoding="utf-8-sig")
    cmd = ["powershell", "-NoProfile", "-Command",
           "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
           f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{ps}\"'"]
    try:
        subprocess.run(cmd, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "msg": f"izin penceresi açılamadı: {exc}"}
    return apply()


def devices() -> list[dict]:
    """Windows ses çıkışları (ad + uç nokta GUID'i). Windows dışında boş."""
    if os.name != "nt":
        return []
    ps = ("Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object { $_.InstanceId -like '*{0.0.0.*' } | "
          "Select-Object FriendlyName,InstanceId,Status | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           timeout=30, encoding="utf-8", errors="replace")
        data = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    out = []
    for d in data if isinstance(data, list) else [data]:
        g = _guid(str(d.get("InstanceId", "")))
        if g:
            name = str(d.get("FriendlyName") or "")
            out.append({"guid": g, "ad": name, "durum": d.get("Status"),
                        "oneri": "z607" if any(w in name.lower() for w in ("logitech", "z607")) else ""})
    return out


def info() -> dict:
    st = load_state()
    d = apo_dir()
    return {"state": st, "presets": [{"id": k, "ad": v["ad"], "bands": v["b"]} for k, v in PRESETS.items()],
            "kinds": [{"id": k, **v} for k, v in KINDS.items()], "bands": BANDS, "tips": TIPS,
            "apo": {"kurulu": bool(d), "path": str(d) if d else "", "url": APO_URL, "windows": os.name == "nt"}}


def update(data: dict) -> dict:
    """Sayfadan gelen değişiklik: {speaker, settings?, preset?, ad?, kind?, device?, device_ad?, active?, apply?}."""
    st = load_state()
    sp = find(st, data.get("speaker"))
    if data.get("preset") in PRESETS:
        keep = clean_settings(sp.get("settings"))
        new = default_settings(data["preset"])
        for k in ("bas", "orta", "vokal", "tiz", "yukseklik", "sub", "arka", "acik"):
            new[k] = keep[k]          # sade sürgüler ve kanal düzeyleri hazır değişince korunur
        sp["settings"] = new
    elif isinstance(data.get("settings"), dict):
        sp["settings"] = clean_settings({**sp.get("settings", {}), **data["settings"]})
    if data.get("ad"):
        sp["ad"] = str(data["ad"]).strip()[:60]
    if data.get("kind") in KINDS:
        sp["kind"] = data["kind"]
    if "device" in data:
        sp["device"] = _guid(str(data.get("device") or ""))
        sp["device_ad"] = str(data.get("device_ad") or "")[:120]
    if data.get("active"):
        st["active"] = find(st, data["active"])["id"]
    save_state(st)
    res = {"speaker": sp, "analysis": analyse(sp["settings"], sp["kind"]), "state": st}
    if data.get("apply", True):
        res["apply"] = apply(st)
    return res


def remove_speaker(sid: str) -> dict:
    st = load_state()
    if len(st["speakers"]) > 1:
        st["speakers"] = [sp for sp in st["speakers"] if sp["id"] != sid]
        if st.get("active") == sid:
            st["active"] = st["speakers"][0]["id"]
        save_state(st)
    return {"state": st, "apply": apply(st)}
