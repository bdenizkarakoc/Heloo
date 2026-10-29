"""Fotoğraflarım: kullanıcının fotoğraf kutusu ve fotoğraflardan video.

Kutu `Masaüstü\\kesim\\Fotoğraflarım` klasörüdür (Kesim'in Montaja at / Hazır klasörlerinin yanı): fotoğraflar
oraya Gezgin'den sürüklenebilir ya da Fabrika (`/photos`) ve Kesim (🏭 Fabrika sekmesi) üzerinden eklenir.
Klasördeki dosyalar asla silinmez veya üzerine yazılmaz; video üretirken seçilenlerin kopyası `studio/uploads`
klasörüne alınır.

İki üretim biçimi:
- montaj: müzikli, geçişli fotoğraf montajı (Kesim/stüdyo hattı, öğrenilen stil; `istek` sihirbazın serbest metni)
- anlatim: seslendirmeli, altyazılı video (Fabrika hattı; `istek` ne anlatılacağı, fotoğraflar sahnelerde kullanılır)
"""
from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path

from . import log
from .config import ROOT

L = log.get("photos")
PHOTOS_NAME = "Fotoğraflarım"
THUMBS = ROOT / "studio" / "cache" / "photo_thumbs"


def photo_dir() -> Path:
    from .kesim import kesim_dir
    d = kesim_dir() / PHOTOS_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve(rel: str) -> Path | None:
    base = photo_dir().resolve()
    p = (base / str(rel)).resolve()
    return p if base in p.parents and p.is_file() else None


def list_photos(limit: int = 400) -> list[dict]:
    from .studio import IMAGE_EXT
    base = photo_dir()
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT
             and not any(part.startswith(".") for part in p.relative_to(base).parts)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.relative_to(base).as_posix(), "size": p.stat().st_size, "mtime": p.stat().st_mtime}
            for p in files[:limit]]


def thumb(rel: str, size: int = 320) -> Path | None:
    """Küçük JPG önizleme (HEIC dahil, EXIF yönüne göre döndürülmüş); önbelleğe alınır."""
    src = _resolve(rel)
    if not src:
        return None
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:16]
    dest = THUMBS / f"{key}-{size}.jpg"
    if dest.exists():
        return dest
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    THUMBS.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((size, size))
        im.save(dest, quality=80)
    return dest


def thumb_data(rel: str) -> str:
    t = thumb(rel, 200)
    return "data:image/jpeg;base64," + base64.b64encode(t.read_bytes()).decode() if t else ""


def add_uploads(names: list[str]) -> list[str]:
    """Yüklenen dosyaları (studio/uploads) kutuya taşır; aynı adlı dosya varsa yeni ad verir (üzerine yazmaz)."""
    from .studio import IMAGE_EXT, UPLOADS
    base, added = photo_dir(), []
    for n in names:
        src = UPLOADS / Path(str(n)).name
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
            continue
        stem = src.stem.split("-", 2)[-1] if src.stem[:8].isdigit() else src.stem   # yükleme zaman damgasını at
        dest, i = base / f"{stem}{src.suffix.lower()}", 2
        while dest.exists():
            dest, i = base / f"{stem}-{i}{src.suffix.lower()}", i + 1
        shutil.move(str(src), dest)
        added.append(dest.name)
    L.info("Fotoğraflarım: %d fotoğraf eklendi", len(added))
    return added


def to_uploads(rels: list[str]) -> list[Path]:
    """Seçilen fotoğrafların kopyasını yükleme klasörüne alır (seçim sırasıyla)."""
    from .studio import UPLOADS, safe_upload_name
    UPLOADS.mkdir(parents=True, exist_ok=True)
    out = []
    for i, rel in enumerate(rels):
        src = _resolve(rel)
        if not src:
            continue
        dest = UPLOADS / f"{i:03d}-{safe_upload_name(src.name)}"
        shutil.copy2(src, dest)
        out.append(dest)
    return out


def make_video(rels: list[str], mode: str, istek: str, enqueue, ref: str | None = None) -> dict:
    """Fotoğraflardan video işini kuyruğa ekler. mode: montaj | anlatim. ref: "şunun aynısı" bağlantısı (montajda
    referansın kesim zamanları, geçişleri ve yazıları birebir uygulanır)."""
    istek = (istek or "").strip()[:2000]
    if mode == "anlatim" and not istek:
        raise ValueError("anlatımlı video için ne anlatılacağını yazın (ör. “Kapadokya gezimiz, balonlar”)")
    files = to_uploads(rels[:60])
    if not files:
        raise ValueError("önce fotoğraf seçin")
    if mode == "anlatim":
        task = enqueue("new", category=None, topic=istek if len(istek) <= 80 else None,
                       text=istek if len(istek) > 80 else None, draw=False, source="elle", kesim=True,
                       media=[f.name for f in files])
        L.info("Fotoğraflardan anlatımlı video: %d fotoğraf", len(files))
        return {"mode": "anlatim", "task": task, "count": len(files)}
    from . import kesim
    answers = {"serbest": istek} if istek else {}
    if ref:
        answers["reference"] = {"url": ref.strip(), "mode": "birebir"}
    proj = kesim.start(files, enqueue, answers or None)
    return {"mode": "montaj", "project": proj["id"], "options": proj.get("options", {}), "count": len(files)}


def open_folder() -> str:
    import os
    import sys
    d = photo_dir()
    if sys.platform.startswith("win"):
        os.startfile(d)  # noqa: S606 — kullanıcının kendi klasörünü Gezgin'de açar
    return str(d)
