"""Kesim: kullanıcının masaüstündeki video programını (Kesim.exe) fabrikaya bağlar.

Programın içi bilinmediği için bağlantı genel tutulur:
- bulma: ayardaki yol ya da Masaüstü\\kesim\\Kesim.exe (OneDrive masaüstü dahil)
- inceleme: paketleme türü (PyInstaller/Electron/.NET...), klasördeki dosyalar, varsa komut satırı yardımı
- açma: bir videoyu Kesim'de açar (Kesim.exe <dosya>)
- toplama: Kesim'in kaydettiği yeni videoları `output/kesim/` altına kopyalar (özgün dosyaya dokunmaz)
- öğrenme: yeni Kesim videosundan stil çıkarıp "Kesim" stilini günceller; stüdyo bu stille düzenler
- montaj (sade Kesim): dosyaları Kesim penceresine (`/kesim`) ya da Masaüstü\\kesim\\Montaja at klasörüne bırak;
  fabrika her şeyi yapar (birleştirme, boşluk kesme, 9:16, altyazı, renk, ses iyileştirme, müzik) ve sonucu
  Masaüstü\\kesim\\Hazır klasörüne koyar. Fabrikanın öğrendiği en güncel stil ve kendini geliştirme turları
  otomatik kullanılır; böylece öğrenilen her şey Kesim'e geçer.

Ayarlar `config/kesim.json` (kullanıcıya özel, depoya girmez).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import log
from .config import ROOT
from .util import read_json, slugify, write_json


def now() -> str:
    import datetime as dt
    return dt.datetime.now().isoformat(timespec="seconds")

L = log.get("kesim")
WIN = sys.platform.startswith("win")
CONF = ROOT / "config" / "kesim.json"
OUT = ROOT / "output" / "kesim"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
SKIP_DIRS = {"_internal", "node_modules", "resources", "locales", "lib", "bin", "__pycache__", "runtimes"}
INBOX_NAME, READY_NAME = "Montaja at", "Hazır"
MEDIA_EXT = VIDEO_EXT | {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".mts", ".3gp"}
SETTLE_SEC = 20  # klasöre bırakılan dosyalar bu kadar süre değişmezse tek montaj olarak işlenir


def settings() -> dict:
    s = read_json(CONF, {}) or {}
    s.setdefault("path", "")
    s.setdefault("output_dir", "")
    s.setdefault("watch", True)        # yeni Kesim videolarını otomatik topla
    s.setdefault("learn", True)        # topladığın videodan "Kesim" stilini güncelle
    s.setdefault("imported", {})       # kaynak yol -> {mtime, file}
    s.setdefault("style", "")          # boş: fabrikanın en güncel öğrendiği stil
    s.setdefault("mode", "auto")       # auto (kısa ise tamamı, uzunsa en iyi anlar) / full / clips
    s.setdefault("music", True)
    s.setdefault("inbox_done", {})     # klasöre bırakılıp işlenen dosyalar -> mtime
    return s


def save_settings(data: dict) -> dict:
    s = settings()
    for k in ("path", "output_dir", "style"):
        if k in data:
            s[k] = str(data[k] or "").strip().strip('"')
    if data.get("mode") in ("auto", "full", "clips"):
        s["mode"] = data["mode"]
    for k in ("watch", "learn", "music"):
        if k in data:
            s[k] = bool(data[k])
    write_json(CONF, s)
    return status()


def _desktops() -> list[Path]:
    home = Path.home()
    out = [home / "Desktop", home / "Masaüstü"]
    for od in [os.environ.get("OneDrive", "")] + [str(p) for p in home.glob("OneDrive*")]:
        if od:
            out += [Path(od) / "Desktop", Path(od) / "Masaüstü"]
    return out


def find_exe() -> Path | None:
    s = settings()
    if s["path"] and Path(s["path"]).is_file():
        return Path(s["path"])
    for d in _desktops():
        for cand in (d / "kesim" / "Kesim.exe", d / "Kesim" / "Kesim.exe", d / "Kesim.exe"):
            if cand.is_file():
                return cand
    return None


def watch_dirs(exe: Path | None = None) -> list[Path]:
    """Kesim çıktılarının aranacağı klasörler: ayardaki çıktı klasörü + programın kendi klasörü."""
    exe = exe or find_exe()
    s = settings()
    dirs = [Path(s["output_dir"])] if s["output_dir"] else []
    if exe:
        dirs.append(exe.parent)
    return [d for d in dirs if d.is_dir()]


def _videos(d: Path, depth: int = 3):
    try:
        for p in d.iterdir():
            if p.is_dir() and depth > 0 and p.name.lower() not in SKIP_DIRS and not p.name.startswith(".") \
                    and p.name not in (INBOX_NAME, READY_NAME):
                yield from _videos(p, depth - 1)
            elif p.suffix.lower() in VIDEO_EXT:
                yield p
    except OSError:
        return


def _kind(exe: Path) -> str:
    """Paketleme türünü tahmin eder (yalnızca okur, çalıştırmaz)."""
    d = exe.parent
    if (d / "resources" / "app.asar").exists():
        return "Electron"
    if (d / "_internal").is_dir() and any((d / "_internal").glob("python3*.dll")):
        return "PyInstaller (Python, klasör)"
    try:
        with exe.open("rb") as fh:
            head = fh.read(4 << 20)
            fh.seek(max(0, exe.stat().st_size - (4 << 20)))
            tail = fh.read()
    except OSError:
        return "bilinmiyor"
    blob = head + tail
    if b"MEI\x0c\x0b\x0a\x0b\x0e" in blob or b"pyi-runtime" in blob or b"_MEIPASS" in blob:
        return "PyInstaller (Python, tek dosya)"
    if b"__nuitka" in blob.lower() or b"nuitka" in blob.lower():
        return "Nuitka (Python)"
    if b"mscoree.dll" in blob or b"_CorExeMain" in blob:
        return ".NET"
    if b"tauri" in blob.lower():
        return "Tauri"
    if b"Qt5Core" in blob or b"Qt6Core" in blob:
        return "Qt (C++)"
    return "yerel Windows programı"


def probe(try_help: bool = False) -> dict:
    """Kesim'i inceler. try_help=True ise --help ile en fazla 8 sn çalıştırılır (pencere açılırsa kapatılır)."""
    exe = find_exe()
    if not exe:
        return {"found": False}
    info = {"found": True, "path": str(exe), "kind": _kind(exe), "size_mb": round(exe.stat().st_size / 1e6, 1),
            "files": sorted(p.name for p in exe.parent.iterdir())[:60], "help": None, "at": now()}
    if try_help:
        for flag in ("--help", "-h", "/?"):
            try:
                p = subprocess.run([str(exe), flag], cwd=exe.parent, capture_output=True, timeout=8,  # noqa: S603
                                   encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
                text = (p.stdout or p.stderr or "").strip()
            except subprocess.TimeoutExpired:
                text = ""  # pencereli program: bayrağı yok saydı, kapatıldı
            except OSError as exc:
                text = f"çalıştırılamadı: {exc}"
            if text:
                info["help"] = {"flag": flag, "text": text[:4000]}
                break
    s = settings()
    s["probe"] = info
    write_json(CONF, s)
    return info


def open_in_kesim(video: Path) -> dict:
    exe = find_exe()
    if not exe:
        return {"ok": False, "error": "Kesim.exe bulunamadı — yolunu Stüdyo → Kesim kartına yazın"}
    if not video.is_file():
        return {"ok": False, "error": "video bulunamadı"}
    # Kesim'in kendi penceresi görünmeli (genel penceresiz ayarı burada geçerli değil)
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if WIN else 0
    subprocess.Popen([str(exe), str(video)], cwd=exe.parent, creationflags=flags)  # noqa: S603
    s = settings()
    s["last_open"] = {"video": str(video), "at": time.time()}
    write_json(CONF, s)
    L.info("Kesim'de açıldı: %s", video.name)
    return {"ok": True}


def collect() -> list[dict]:
    """Kesim klasörlerindeki yeni/değişen videoları output/kesim/ altına kopyalar; eklenenleri döndürür."""
    exe = find_exe()
    s = settings()
    if not exe and not s["output_dir"]:
        return []
    OUT.mkdir(parents=True, exist_ok=True)
    new = []
    for src in (v for d in watch_dirs(exe) for v in _videos(d)):
        try:
            st = src.stat()
        except OSError:
            continue
        if time.time() - st.st_mtime < 20:  # Kesim hâlâ yazıyor olabilir
            continue
        key = str(src)
        if s["imported"].get(key, {}).get("mtime") == int(st.st_mtime):
            continue
        dest = OUT / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(src.stem, 50)}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        rec = {"mtime": int(st.st_mtime), "file": dest.relative_to(ROOT).as_posix(), "source": key, "at": now()}
        s["imported"][key] = rec
        new.append(rec)
        L.info("Kesim videosu alındı: %s", src.name)
    if new:
        write_json(CONF, s)
    return new


def items(limit: int = 30) -> list[dict]:
    recs = sorted(settings()["imported"].values(), key=lambda r: r.get("at", ""), reverse=True)
    return [r for r in recs if (ROOT / r["file"]).is_file()][:limit]


def status() -> dict:
    exe = find_exe()
    s = settings()
    home = kesim_dir()
    return {"found": bool(exe), "path": str(exe) if exe else "", "configured_path": s["path"],
            "output_dir": s["output_dir"], "watch": s["watch"], "learn": s["learn"], "music": s["music"],
            "mode": s["mode"], "style": s["style"], "default_style": default_style(),
            "learned": s.get("learned"), "inbox": str(home / INBOX_NAME), "ready": str(home / READY_NAME),
            "watch_dirs": [str(d) for d in watch_dirs(exe)], "probe": s.get("probe"), "items": items()}


def learn(video_rel: str) -> dict:
    """Kesim videosundan stil öğrenir ve "Kesim" stilini günceller (eski sürüm .bak olarak kalır)."""
    from . import studio
    src = ROOT / video_rel
    proj = studio.new_project("analyze", src, {})
    studio.run_analyze(proj["id"])
    saved = studio.save_from_analysis(proj["id"], "Kesim", backup=True)
    s = settings()
    s["learned"] = {"slug": saved.get("slug", "kesim"), "from": video_rel, "at": now(),
                    "version": saved.get("version", 1)}
    write_json(CONF, s)
    L.info("✔ Kesim stili güncellendi (%s)", Path(video_rel).name)
    return saved


# ----------------------------------------------------------------------------
# Sade Kesim: bırak → montaj
# ----------------------------------------------------------------------------

def kesim_dir() -> Path:
    """Masaüstündeki kesim klasörü (Kesim.exe'nin yanı; yoksa Masaüstü\\kesim)."""
    exe = find_exe()
    if exe and exe.parent.name.lower() == "kesim":
        return exe.parent
    for d in _desktops():
        if (d / "kesim").is_dir():
            return d / "kesim"
    desk = next((d for d in _desktops() if d.is_dir()), Path.home())
    return desk / "kesim"


def default_style() -> str:
    """Kesim'in stili: seçilen, yoksa fabrikanın en son öğrendiği/geliştirdiği kullanıcı stili, yoksa yerleşik."""
    from . import studio
    chosen = settings()["style"]
    if chosen and (studio.STYLES / f"{chosen}.json").exists() or chosen and (studio.BUILTIN_STYLES / f"{chosen}.json").exists():
        return chosen
    mine = [(read_json(f, {}) or {}, f.stem) for f in studio.STYLES.glob("*.json")] if studio.STYLES.exists() else []
    mine.sort(key=lambda x: str(x[0].get("updated") or x[0].get("created") or ""), reverse=True)
    return mine[0][1] if mine else "fabrika"


def edit_options(files: list[str], total_sec: float) -> dict:
    s = settings()
    mode = s["mode"] if s["mode"] != "auto" else ("full" if total_sec <= 90 else "clips")
    return {"files": files, "style": default_style(), "mode": mode, "music": s["music"], "captions": True,
            "enhance": True, "improve_rounds": 1, "kesim": True}


def start(files: list[Path], enqueue) -> dict:
    """Yüklenmiş dosyalarla (studio/uploads) montaj işini kuyruğa ekler."""
    from . import studio
    names = [f.name for f in files]
    total = sum(studio.media_info(f).get("duration") or 3.5 for f in files)
    proj = studio.new_project("edit", files[0], edit_options(names, total))
    enqueue("studio_edit", project=proj["id"], topic=f"Kesim: {len(files)} dosya")
    L.info("Kesim montajı başladı: %s (%d dosya, stil: %s)", proj["id"], len(files), proj["options"]["style"])
    return proj


def deliver(proj: dict) -> list[str]:
    """Bitmiş Kesim montajının kliplerini Masaüstü\\kesim\\Hazır klasörüne kopyalar."""
    ready = kesim_dir() / READY_NAME
    ready.mkdir(parents=True, exist_ok=True)
    out = []
    for c in proj.get("clips", []):
        if c.get("output") and (ROOT / c["output"]).is_file():
            dest = ready / f"{proj['id']}-{Path(c['output']).name}"
            shutil.copy2(ROOT / c["output"], dest)
            out.append(str(dest))
    L.info("Kesim: %d video Hazır klasörüne kondu", len(out))
    return out


def to_ready(path: Path, prefix: str = "") -> str:
    """Bitmiş bir videoyu Masaüstü\\kesim\\Hazır klasörüne kopyalar."""
    ready = kesim_dir() / READY_NAME
    ready.mkdir(parents=True, exist_ok=True)
    dest = ready / f"{prefix}{path.name}"
    shutil.copy2(path, dest)
    return str(dest)


def scan_inbox(enqueue) -> dict | None:
    """Montaja at klasörüne bırakılan yeni dosyalar SETTLE_SEC boyunca değişmediyse hepsini tek montaj yapar.
    Kullanıcının dosyaları silinmez/taşınmaz; işlenenler kayıtla atlanır."""
    from . import studio
    inbox = kesim_dir() / INBOX_NAME
    inbox.mkdir(parents=True, exist_ok=True)
    s = settings()
    fresh = []
    for f in sorted(inbox.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or f.suffix.lower() not in MEDIA_EXT:
            continue
        mt = int(f.stat().st_mtime)
        if s["inbox_done"].get(f.name) == mt:
            continue
        if time.time() - f.stat().st_mtime < SETTLE_SEC:
            return None  # hâlâ kopyalanıyor ya da yenileri geliyor: bekle
        fresh.append((f, mt))
    if not fresh:
        return None
    studio.UPLOADS.mkdir(parents=True, exist_ok=True)
    ups = []
    for f, _ in fresh:
        dest = studio.UPLOADS / studio.safe_upload_name(f.name)
        shutil.copy2(f, dest)
        ups.append(dest)
    for f, mt in fresh:
        s["inbox_done"][f.name] = mt
    write_json(CONF, s)
    return start(ups, enqueue)


def tick(enqueue) -> None:
    """Uygulamanın arka plan döngüsü: klasöre bırakılanlar → montaj; eski Kesim çıktıları → stil öğrenme."""
    try:
        scan_inbox(enqueue)
    except Exception as exc:  # noqa: BLE001
        L.warning("Kesim klasörü işlenemedi: %s", exc)
    s = settings()
    if s["watch"] and find_exe():
        for rec in collect():
            if s["learn"]:
                enqueue("kesim_learn", video=rec["file"], topic=f"Kesim stilini öğren: {Path(rec['file']).name}")


def montage(paths: list[Path], on_stage=None) -> dict:
    """Komut satırı / Claude için eşzamanlı montaj: dosyaları alır, sonucu döndürür."""
    from . import studio
    studio.UPLOADS.mkdir(parents=True, exist_ok=True)
    ups = []
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(p)
        dest = studio.UPLOADS / studio.safe_upload_name(p.name)
        shutil.copy2(p, dest)
        ups.append(dest)
    holder = {}
    proj = start(ups, lambda kind, **kw: holder.update(kw))
    proj = studio.run_edit(holder["project"])
    proj["delivered"] = deliver(proj)
    return proj
