"""Supabase: üretilen videoları ve kayıtlarını buluta yükler (Storage + `reels_videos` tablosu).

`.env` → SUPABASE_URL (https://<proje>.supabase.co) + SUPABASE_SERVICE_KEY (yalnızca bu bilgisayarda; asla sayfaya
gönderilmez). Tablo ve depo kurulumu: `supabase/schema.sql` (Supabase panelinde SQL Editor'de bir kez çalıştır).
Ayar: `supabase.enabled` ve `supabase.bucket`. Yükleme başarısız olursa üretim durmaz, yalnızca uyarı yazılır.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

import requests

from . import log
from .config import ROOT, Config, secret

L = log.get("supabase")


def available(cfg: Config) -> bool:
    return bool(cfg.get_path("supabase.enabled", True) and secret("SUPABASE_URL") and secret("SUPABASE_SERVICE_KEY"))


def _hdr(extra: dict | None = None) -> dict:
    key = secret("SUPABASE_SERVICE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}", **(extra or {})}


def upload_file(path: Path, dest: str, cfg: Config) -> str:
    bucket = cfg.get_path("supabase.bucket", "reels")
    url = f"{secret('SUPABASE_URL').rstrip('/')}/storage/v1/object/{bucket}/{dest}"
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        r = requests.post(url, data=fh, timeout=1800, headers=_hdr({"Content-Type": ctype, "x-upsert": "true"}))
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase depo {r.status_code}: {r.text[:200]}")
    return dest


def record_video(job_id: str, title: str, category: str, outputs: dict, extra: dict, cfg: Config) -> dict | None:
    """Videoyu, kapağı ve paylaşım metnini yükler; `reels_videos` tablosuna (job_id'ye göre güncelleyerek) yazar."""
    if not available(cfg):
        return None
    try:
        stored = {}
        for kind in ("video", "thumbnail", "srt", "post"):
            rel = outputs.get(kind)
            if rel and (ROOT / rel).is_file():
                stored[kind] = upload_file(ROOT / rel, f"{job_id}/{Path(rel).name}", cfg)
        caption = (ROOT / outputs["post"]).read_text(encoding="utf-8") if outputs.get("post") and (ROOT / outputs["post"]).is_file() else ""
        row = {"job_id": job_id, "title": title, "category": category, "video_path": stored.get("video"),
               "thumbnail_path": stored.get("thumbnail"), "caption": caption[:5000], "meta": extra}
        r = requests.post(f"{secret('SUPABASE_URL').rstrip('/')}/rest/v1/reels_videos", json=row, timeout=60,
                          params={"on_conflict": "job_id"},
                          headers=_hdr({"Content-Type": "application/json",
                                        "Prefer": "resolution=merge-duplicates,return=minimal"}))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase tablo {r.status_code}: {r.text[:200]}")
        L.info("Supabase'e yüklendi: %s (%d dosya)", job_id, len(stored))
        return {"files": stored}
    except (requests.RequestException, RuntimeError, OSError) as exc:
        L.warning("Supabase yüklemesi yapılamadı (üretim etkilenmez): %s", exc)
        return None
