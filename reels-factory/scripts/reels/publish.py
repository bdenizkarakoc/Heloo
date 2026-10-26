"""Yayın: kanallar (logo + ad), onay kuyruğu, süre dolunca otomatik yayın ve platform bağlantıları.

Akış: video hazır → kanalın logosu/adı videoya işlenir → kitle testi (isteğe bağlı) → "onay bekliyor"
(varsayılan 2 saat; panelde ve Telegram'da Onayla/Reddet) → onaylanınca hemen, yanıt gelmezse süre dolunca seçilen
platformlara yüklenir. Reddedilen video yayınlanmaz.

Platformlar (hepsi kullanıcının kendi geliştirici uygulaması/anahtarlarıyla; anahtarlar yalnızca .env'de):
  youtube   : YouTube Data API v3, OAuth (Shorts). Doğrulanmamış (audit edilmemiş) Google projelerinden yüklenen
              videolar Google tarafından "gizli" kalır.
  instagram : Instagram Graph API (İşletme/İçerik Üreticisi hesabı + Facebook Sayfası), Reels yükleme.
  facebook  : Facebook Sayfası Reels (Graph API video_reels).
  tiktok    : TikTok Content Posting API. Denetimden (audit) geçmemiş uygulamalar yalnızca "yalnızca ben" gizlilikle
              paylaşabilir.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import shutil
import threading
import time
from pathlib import Path

import requests

from . import log
from .config import ROOT, Config, load_config, secret, set_secret
from .util import StageError, ffprobe, read_json, run, slugify, write_json

L = log.get("publish")
CHANNELS = ROOT / "channels"
QUEUE = ROOT / "publish" / "queue"
PLATFORMS = ("instagram", "facebook", "youtube", "tiktok")
GRAPH = "https://graph.facebook.com/v23.0"
LOCK = threading.RLock()


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def env_key(slug: str, what: str) -> str:
    return f"RF_{slugify(slug, 30).upper().replace('-', '_')}_{what}"


# ----------------------------------------------------------------------------
# Kanallar
# ----------------------------------------------------------------------------

DEFAULT_CHANNEL = {
    "name": "", "handle": "", "logo": None, "logo_pos": "top-right", "show_name": True,
    "targets": ["instagram", "facebook", "youtube", "tiktok"], "approval_hours": 2.0, "auto_publish": True,
    "auto_queue": {"local": False, "cloud": False, "studio": False},
    "caption_suffix": "", "accounts": {"instagram": {}, "facebook": {}, "youtube": {"privacy": "public"},
                                       "tiktok": {"privacy": "SELF_ONLY"}},
}


def channels() -> list[dict]:
    out = []
    for f in sorted(CHANNELS.glob("*/channel.json")) if CHANNELS.exists() else []:
        c = {**DEFAULT_CHANNEL, **read_json(f)}
        c["connected"] = {p: connected(c, p) for p in PLATFORMS}
        out.append(c)
    return out


def get_channel(slug: str) -> dict:
    f = CHANNELS / slug / "channel.json"
    if not f.exists():
        raise StageError(f"kanal yok: {slug}")
    return {**DEFAULT_CHANNEL, **read_json(f)}


def default_channel() -> dict | None:
    cs = channels()
    marked = [c for c in cs if c.get("default")]
    return (marked or cs or [None])[0]


def save_channel(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise StageError("kanal adı gerekli")
    slug = data.get("slug") or slugify(name, 30)
    d = CHANNELS / slug
    d.mkdir(parents=True, exist_ok=True)
    old = read_json(d / "channel.json") or {}
    c = {**DEFAULT_CHANNEL, **old}
    for k in ("name", "handle", "logo_pos", "show_name", "targets", "approval_hours", "auto_publish", "auto_queue",
              "caption_suffix", "default"):
        if k in data:
            c[k] = data[k]
    for p, acc in (data.get("accounts") or {}).items():
        if p in PLATFORMS and isinstance(acc, dict):  # gizli olmayan alanlar (sayfa/hesap kimliği, gizlilik)
            c["accounts"][p] = {**c["accounts"].get(p, {}),
                                **{k: v for k, v in acc.items() if "token" not in k.lower() and "secret" not in k}}
    c["targets"] = [t for t in c["targets"] if t in PLATFORMS]
    c["approval_hours"] = max(0.0, min(72.0, float(c["approval_hours"])))
    c.update(slug=slug, name=name)
    if c.get("default"):
        for other in channels():
            if other["slug"] != slug and other.get("default"):
                o = read_json(CHANNELS / other["slug"] / "channel.json")
                o["default"] = False
                write_json(CHANNELS / other["slug"] / "channel.json", o)
    write_json(d / "channel.json", c)
    return c


def save_logo(slug: str, data: bytes) -> str:
    d = CHANNELS / slug
    if not d.exists():
        raise StageError("önce kanalı kaydedin")
    raw = d / "logo_upload"
    raw.write_bytes(data)
    run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-frames:v", "1", "-vf", "scale='min(512,iw)':-2", d / "logo.png"])
    raw.unlink(missing_ok=True)
    c = read_json(d / "channel.json")
    c["logo"] = "logo.png"
    write_json(d / "channel.json", c)
    return f"channels/{slug}/logo.png"


def connected(c: dict, platform: str) -> bool:
    acc = c["accounts"].get(platform, {})
    if platform == "instagram":
        return bool(acc.get("ig_user_id") and secret(env_key(c["slug"], "META_TOKEN")))
    if platform == "facebook":
        return bool(acc.get("page_id") and secret(env_key(c["slug"], "META_TOKEN")))
    if platform == "youtube":
        return bool(secret(env_key(c["slug"], "YT_REFRESH_TOKEN")) and secret("YOUTUBE_CLIENT_SECRET"))
    if platform == "tiktok":
        return bool(secret(env_key(c["slug"], "TIKTOK_TOKEN")))
    return False


# ----------------------------------------------------------------------------
# Logo + kanal adı damgası
# ----------------------------------------------------------------------------

def brand_video(src: Path, c: dict, dest: Path) -> Path:
    """Kanalın logosunu ve adını videoya işler (platform arayüzüyle çakışmayan üst köşe)."""
    from .studio_render import font_file
    work = dest.parent / (dest.stem + "_brand")
    work.mkdir(parents=True, exist_ok=True)
    info = ffprobe(src)
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    W, H = int(v["width"]), int(v["height"])
    k = min(W, H) / 1080
    logo = CHANNELS / c["slug"] / (c.get("logo") or "logo.png")
    has_logo = bool(c.get("logo")) and logo.exists()
    label = (c.get("handle") or c.get("name") or "").strip() if c.get("show_name", True) else ""
    if not has_logo and not label:
        shutil.copy(src, dest)
        return dest
    right = c.get("logo_pos", "top-right") != "top-left"
    lh = int(72 * k)                   # logo yüksekliği
    m = int(48 * k)                    # kenar boşluğu
    y = int(H * 0.108) if H > W else m  # dikeyde üstteki platform arayüzünün (ilk ~200 px) hemen altı
    inputs, graph, last = ["-i", str(src.resolve())], "", "0:v"
    if has_logo:
        shutil.copy(logo, work / "logo.png")
        inputs += ["-i", "logo.png"]
        x = f"W-w-{m}" if right else f"{m}"
        graph += (f"[1:v]scale=-2:{lh},format=rgba,colorchannelmixer=aa=0.92[lg];"
                  f"[{last}][lg]overlay=x={x}:y={y}[b1];")
        last = "b1"
    if label:
        shutil.copy(font_file(800), work / "brand.ttf")
        (work / "label.txt").write_text(label, encoding="utf-8")
        fs = int(28 * k)
        ty = f"{y}+({lh}-th)/2" if has_logo else f"{y}"   # logonun yanında, aynı satırda
        gap = (lh + int(14 * k)) if has_logo else 0
        x = f"w-tw-{m + gap}" if right else f"{m + gap}"
        graph += (f"[{last}]drawtext=fontfile=brand.ttf:textfile=label.txt:fontsize={fs}:fontcolor=white:"
                  f"borderw={max(2, int(3 * k))}:bordercolor=black@0.7:x={x}:y={ty}[b2];")
        last = "b2"
    graph = graph.rstrip(";")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-movflags", "+faststart", str(dest.resolve())], cwd=work)
    shutil.rmtree(work, ignore_errors=True)
    return dest


# ----------------------------------------------------------------------------
# Kuyruk
# ----------------------------------------------------------------------------

def _path(pid: str) -> Path:
    return QUEUE / pid / "item.json"


def load(pid: str) -> dict:
    p = _path(pid)
    if not p.exists():
        raise StageError(f"yayın kaydı yok: {pid}")
    return read_json(p)


def save(item: dict) -> dict:
    with LOCK:
        item["updated"] = iso(now())
        write_json(_path(item["id"]), item)
    return item


def items(limit: int = 60) -> list[dict]:
    out = [read_json(p) for p in QUEUE.glob("*/item.json")] if QUEUE.exists() else []
    return sorted(out, key=lambda i: i.get("created", ""), reverse=True)[:limit]


def find_by_video(video: str) -> dict | None:
    return next((i for i in items(500) if i.get("source_video") == video), None)


def enqueue(video: Path, title: str, caption: str, text: str = "", channel: str | None = None,
            targets: list[str] | None = None, source: str = "elle", sheet: Path | None = None) -> dict:
    """Videoyu onay kuyruğuna ekler, kanal damgasını uygular. Aynı video ikinci kez eklenmez."""
    rel = str(video.resolve().relative_to(ROOT))
    old = find_by_video(rel)
    if old:
        return old
    c = get_channel(channel) if channel else default_channel()
    if not c:
        raise StageError("önce bir kanal oluşturun (Yayın → Kanallar)")
    pid = f"pub-{dt.datetime.now():%Y%m%d-%H%M%S}-{slugify(title, 24)}"
    d = QUEUE / pid
    d.mkdir(parents=True, exist_ok=True)
    branded = brand_video(video, c, d / "video.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", branded, "-frames:v", "1", "-vf", "scale=540:-2",
         d / "cover.jpg"])
    if sheet and sheet.exists():
        shutil.copy(sheet, d / "sheet.jpg")
    else:
        from .qc import contact_sheet
        total = float(ffprobe(branded)["format"]["duration"])
        contact_sheet(branded, d / "sheet.jpg", max(1.0, total / 16), total,
                      ROOT / "assets" / "fonts" / "Montserrat-VariableFont_wght.ttf")
    hours = float(c.get("approval_hours", 2))
    suffix = c.get("caption_suffix") or ""
    item = {"id": pid, "title": title[:100], "caption": (caption + ("\n\n" + suffix if suffix else "")).strip(),
            "text": text[:4000], "channel": c["slug"], "channel_name": c["name"],
            "targets": [t for t in (targets or c["targets"]) if t in PLATFORMS],
            "source": source, "source_video": rel, "video": str(branded.relative_to(ROOT)),
            "cover": str((d / "cover.jpg").relative_to(ROOT)), "sheet": str((d / "sheet.jpg").relative_to(ROOT)),
            "status": "pending", "created": iso(now()), "deadline": iso(now() + dt.timedelta(hours=hours)),
            "auto_publish": bool(c.get("auto_publish", True)), "results": {}, "history": []}
    save(item)
    L.info("Onay kuyruğuna eklendi: %s → %s (son onay %s)", title, ", ".join(item["targets"]), item["deadline"])
    return item


def act(pid: str, action: str, by: str = "panel", **kw) -> dict:
    """approve | reject | snooze | update"""
    with LOCK:
        it = load(pid)
        if it["status"] in ("published", "publishing") and action != "update":
            raise StageError("bu video zaten yayınlandı/yayınlanıyor")
        if action == "approve":
            it["status"] = "approved"
        elif action == "reject":
            it["status"] = "rejected"
        elif action == "snooze":
            it["deadline"] = iso(max(now(), dt.datetime.fromisoformat(it["deadline"])) +
                                 dt.timedelta(hours=float(kw.get("hours", 2))))
            it["status"] = "pending"
        elif action == "update":
            for k in ("caption", "title", "targets"):
                if k in kw and kw[k] is not None:
                    it[k] = [t for t in kw[k] if t in PLATFORMS] if k == "targets" else str(kw[k])[:2200]
            if kw.get("channel") and kw["channel"] != it["channel"]:
                c = get_channel(kw["channel"])
                brand_video(ROOT / it["source_video"], c, ROOT / it["video"])
                it.update(channel=c["slug"], channel_name=c["name"])
        it["history"].append({"at": iso(now()), "action": action, "by": by})
        return save(it)


def due() -> list[dict]:
    """Yayınlanacaklar: onaylananlar ve süresi dolup otomatik yayın açık olanlar."""
    out = []
    for it in items(500):
        if it["status"] == "approved":
            out.append(it)
        elif it["status"] == "pending" and it.get("auto_publish") and now() >= dt.datetime.fromisoformat(it["deadline"]):
            out.append(it)
    return out


def publish_item(pid: str) -> dict:
    with LOCK:
        it = load(pid)
        if it["status"] not in ("pending", "approved", "failed", "partial"):
            return it
        reason = "onaylandı" if it["status"] == "approved" else "onay süresi doldu, otomatik"
        it["status"] = "publishing"
        save(it)
    c = get_channel(it["channel"])
    video = ROOT / it["video"]
    results = dict(it.get("results") or {})
    for p in it["targets"]:
        if results.get(p, {}).get("status") == "published":
            continue
        try:
            if not connected(c, p):
                raise StageError("hesap bağlı değil")
            res = ADAPTERS[p](c, video, it)
            results[p] = {"status": "published", **res, "at": iso(now())}
            L.info("✔ %s yayınlandı (%s): %s", p, reason, res.get("url", ""))
        except Exception as exc:  # noqa: BLE001 — bir platformun hatası diğerlerini durdurmaz
            results[p] = {"status": "failed", "error": str(exc)[:400], "at": iso(now())}
            L.warning("✖ %s yayınlanamadı: %s", p, exc)
    ok = [p for p in it["targets"] if results.get(p, {}).get("status") == "published"]
    it = load(pid)
    it.update(results=results, published_reason=reason,
              status="published" if len(ok) == len(it["targets"]) and ok else "partial" if ok else "failed")
    it["history"].append({"at": iso(now()), "action": "publish", "by": reason})
    return save(it)


# ----------------------------------------------------------------------------
# Platform bağdaştırıcıları
# ----------------------------------------------------------------------------

def _caption(it: dict, limit: int) -> str:
    return (it.get("caption") or it.get("title") or "")[:limit]


def _graph(method: str, path: str, token: str, **kw) -> dict:
    r = requests.request(method, f"{GRAPH}/{path.lstrip('/')}", params={**kw.pop("params", {}),
                                                                        "access_token": token}, timeout=120, **kw)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise StageError(f"Meta API: {(data.get('error') or {}).get('message', r.status_code)}")
    return data


def _rupload(url: str, token: str, video: Path) -> dict:
    size = video.stat().st_size
    with open(video, "rb") as fh:
        r = requests.post(url, headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                          data=fh, timeout=1800)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise StageError(f"Meta yükleme hatası: {data or r.status_code}")
    return data


def up_instagram(c: dict, video: Path, it: dict) -> dict:
    token = secret(env_key(c["slug"], "META_TOKEN"))
    ig = c["accounts"]["instagram"]["ig_user_id"]
    cont = _graph("POST", f"{ig}/media", token, params={"media_type": "REELS", "upload_type": "resumable",
                                                        "caption": _caption(it, 2200), "share_to_feed": "true"})
    _rupload(cont["uri"], token, video)
    for _ in range(90):  # Instagram videoyu işlerken bekle (en fazla ~15 dk)
        st = _graph("GET", cont["id"], token, params={"fields": "status_code,status"})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise StageError(f"Instagram videoyu işleyemedi: {st.get('status')}")
        time.sleep(10)
    else:
        raise StageError("Instagram işleme zaman aşımı")
    pub = _graph("POST", f"{ig}/media_publish", token, params={"creation_id": cont["id"]})
    link = _graph("GET", pub["id"], token, params={"fields": "permalink"}).get("permalink", "")
    return {"id": pub["id"], "url": link}


def up_facebook(c: dict, video: Path, it: dict) -> dict:
    token = secret(env_key(c["slug"], "META_TOKEN"))
    page = c["accounts"]["facebook"]["page_id"]
    start = _graph("POST", f"{page}/video_reels", token, params={"upload_phase": "start"})
    _rupload(start["upload_url"], token, video)
    _graph("POST", f"{page}/video_reels", token, params={"upload_phase": "finish", "video_id": start["video_id"],
                                                         "video_state": "PUBLISHED",
                                                         "description": _caption(it, 2200)})
    return {"id": start["video_id"], "url": f"https://www.facebook.com/reel/{start['video_id']}"}


def _yt_access(c: dict) -> str:
    r = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": secret("YOUTUBE_CLIENT_ID") or "", "client_secret": secret("YOUTUBE_CLIENT_SECRET") or "",
        "refresh_token": secret(env_key(c["slug"], "YT_REFRESH_TOKEN")) or "", "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise StageError(f"YouTube oturumu yenilenemedi: {r.json().get('error_description', r.status_code)}")
    return r.json()["access_token"]


def up_youtube(c: dict, video: Path, it: dict) -> dict:
    token = _yt_access(c)
    title = (it.get("title") or "Video")[:95]
    desc = _caption(it, 4800)
    if "#shorts" not in desc.lower():
        desc += "\n\n#Shorts"
    meta = {"snippet": {"title": title, "description": desc, "categoryId": "27", "defaultLanguage": "tr"},
            "status": {"privacyStatus": c["accounts"]["youtube"].get("privacy", "public"),
                       "selfDeclaredMadeForKids": False}}
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos",
                      params={"uploadType": "resumable", "part": "snippet,status"}, timeout=60,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                               "X-Upload-Content-Type": "video/mp4",
                               "X-Upload-Content-Length": str(video.stat().st_size)}, data=json.dumps(meta))
    if r.status_code >= 400:
        raise StageError(f"YouTube: {r.text[:300]}")
    with open(video, "rb") as fh:
        up = requests.put(r.headers["Location"], data=fh, timeout=3600,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
    if up.status_code >= 400:
        raise StageError(f"YouTube yükleme: {up.text[:300]}")
    vid = up.json()["id"]
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}",
            "privacy": up.json().get("status", {}).get("privacyStatus")}


def _tiktok_token(c: dict) -> str:
    """Erişim belirteci 24 saatte dolar; yenileme belirteci varsa yenilenir."""
    refresh = secret(env_key(c["slug"], "TIKTOK_REFRESH_TOKEN"))
    if refresh and secret("TIKTOK_CLIENT_KEY") and secret("TIKTOK_CLIENT_SECRET"):
        r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=60, data={
            "client_key": secret("TIKTOK_CLIENT_KEY"), "client_secret": secret("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token", "refresh_token": refresh})
        data = r.json() if r.content else {}
        if data.get("access_token"):
            set_secret(env_key(c["slug"], "TIKTOK_TOKEN"), data["access_token"])
            if data.get("refresh_token"):
                set_secret(env_key(c["slug"], "TIKTOK_REFRESH_TOKEN"), data["refresh_token"])
            return data["access_token"]
    tok = secret(env_key(c["slug"], "TIKTOK_TOKEN"))
    if not tok:
        raise StageError("TikTok belirteci yok")
    return tok


def up_tiktok(c: dict, video: Path, it: dict) -> dict:
    token = _tiktok_token(c)
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    info = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=hdr,
                         timeout=60).json()
    opts = (info.get("data") or {}).get("privacy_level_options") or ["SELF_ONLY"]
    want = c["accounts"]["tiktok"].get("privacy", "SELF_ONLY")
    privacy = want if want in opts else opts[0]
    size = video.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    count = max(1, size // chunk) if size > chunk else 1
    init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=hdr, timeout=60,
                         data=json.dumps({"post_info": {"title": _caption(it, 2000), "privacy_level": privacy,
                                                        "disable_comment": False, "disable_duet": False,
                                                        "disable_stitch": False},
                                          "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                                          "chunk_size": chunk, "total_chunk_count": count}})).json()
    if (init.get("error") or {}).get("code") not in (None, "ok"):
        raise StageError(f"TikTok: {init['error'].get('code')}: {init['error'].get('message')}")
    url, pub = init["data"]["upload_url"], init["data"]["publish_id"]
    with open(video, "rb") as fh:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            fh.seek(start)
            body = fh.read(end - start + 1)
            r = requests.put(url, data=body, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code >= 400:
                raise StageError(f"TikTok yükleme: {r.status_code}")
    for _ in range(60):
        st = requests.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers=hdr, timeout=60,
                           data=json.dumps({"publish_id": pub})).json().get("data", {})
        if st.get("status") == "PUBLISH_COMPLETE":
            break
        if st.get("status") == "FAILED":
            raise StageError(f"TikTok yayınlayamadı: {st.get('fail_reason')}")
        time.sleep(10)
    return {"id": pub, "url": "", "privacy": privacy}


ADAPTERS = {"instagram": up_instagram, "facebook": up_facebook, "youtube": up_youtube, "tiktok": up_tiktok}


# ----------------------------------------------------------------------------
# Hesap bağlama yardımcıları
# ----------------------------------------------------------------------------

def meta_pages(user_token: str) -> list[dict]:
    """Meta kullanıcı belirteciyle yönetilen sayfaları ve bağlı Instagram hesaplarını listeler."""
    data = _graph("GET", "me/accounts", user_token,
                  params={"fields": "name,id,access_token,instagram_business_account{id,username}", "limit": 50})
    return [{"page_id": p["id"], "page_name": p.get("name"), "page_token": p.get("access_token"),
             "ig_user_id": (p.get("instagram_business_account") or {}).get("id"),
             "ig_username": (p.get("instagram_business_account") or {}).get("username")} for p in data.get("data", [])]


def connect_meta(slug: str, user_token: str, page_id: str) -> dict:
    page = next((p for p in meta_pages(user_token) if p["page_id"] == page_id), None)
    if not page:
        raise StageError("sayfa bulunamadı")
    set_secret(env_key(slug, "META_TOKEN"), page["page_token"])
    c = read_json(CHANNELS / slug / "channel.json")
    c["accounts"]["facebook"] = {**c["accounts"].get("facebook", {}), "page_id": page["page_id"],
                                 "page_name": page["page_name"]}
    if page.get("ig_user_id"):
        c["accounts"]["instagram"] = {**c["accounts"].get("instagram", {}), "ig_user_id": page["ig_user_id"],
                                      "ig_username": page["ig_username"]}
    write_json(CHANNELS / slug / "channel.json", c)
    return {"page": page["page_name"], "instagram": page.get("ig_username")}


YT_SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def youtube_auth_url(slug: str, redirect: str) -> str:
    from urllib.parse import urlencode
    if not secret("YOUTUBE_CLIENT_ID") or not secret("YOUTUBE_CLIENT_SECRET"):
        raise StageError("önce YouTube OAuth istemci kimliği ve gizli anahtarını girin")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": secret("YOUTUBE_CLIENT_ID"), "redirect_uri": redirect, "response_type": "code",
        "scope": YT_SCOPE, "access_type": "offline", "prompt": "consent", "state": slug})


def youtube_callback(slug: str, code: str, redirect: str) -> dict:
    r = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "code": code, "client_id": secret("YOUTUBE_CLIENT_ID"), "client_secret": secret("YOUTUBE_CLIENT_SECRET"),
        "redirect_uri": redirect, "grant_type": "authorization_code"})
    data = r.json()
    if not data.get("refresh_token"):
        raise StageError(f"YouTube bağlantısı alınamadı: {data.get('error_description') or data.get('error')}")
    set_secret(env_key(slug, "YT_REFRESH_TOKEN"), data["refresh_token"])
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {data['access_token']}"}, timeout=60).json()
    title = ((ch.get("items") or [{}])[0].get("snippet") or {}).get("title", "")
    c = read_json(CHANNELS / slug / "channel.json")
    c["accounts"]["youtube"] = {**c["accounts"].get("youtube", {}), "channel_title": title}
    write_json(CHANNELS / slug / "channel.json", c)
    return {"channel": title}


# ----------------------------------------------------------------------------
# Telegram: onay bildirimi ve düğmeler (isteğe bağlı; TELEGRAM_BOT_TOKEN)
# ----------------------------------------------------------------------------

def _tg(method: str, **kw) -> dict:
    tok = secret("TELEGRAM_BOT_TOKEN")
    if not tok:
        raise StageError("Telegram botu bağlı değil")
    r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", timeout=120, **kw)
    data = r.json() if r.content else {}
    if not data.get("ok"):
        raise StageError(f"Telegram: {data.get('description', r.status_code)}")
    return data.get("result")


def tg_chat() -> str | None:
    return secret("TELEGRAM_CHAT_ID") or None


def tg_notify(it: dict) -> None:
    chat = tg_chat()
    if not chat:
        return
    left = dt.datetime.fromisoformat(it["deadline"]) - now()
    mins = max(0, int(left.total_seconds() // 60))
    text = (f"🎬 {it['title']}\nKanal: {it['channel_name']} → {', '.join(it['targets'])}\n"
            + (f"⏳ {mins // 60} sa {mins % 60} dk içinde yanıt vermezsen otomatik yayınlanacak.\n"
               if it.get("auto_publish") else "Onay verene kadar yayınlanmayacak.\n")
            + (f"🔮 Kitle testi: {it['audience']['score']}/100 — {it['audience'].get('verdict', '')}\n"
               if (it.get("audience") or {}).get("score") is not None else "")
            + f"\n{(it.get('caption') or '')[:600]}")
    kb = {"inline_keyboard": [[{"text": "✅ Onayla, şimdi yayınla", "callback_data": f"ok:{it['id']}"},
                               {"text": "❌ Reddet", "callback_data": f"no:{it['id']}"}],
                              [{"text": "⏰ 2 saat ertele", "callback_data": f"later:{it['id']}"}]]}
    video = ROOT / it["video"]
    try:
        if video.stat().st_size < 48 * 1024 * 1024:
            with open(video, "rb") as fh:
                _tg("sendVideo", data={"chat_id": chat, "caption": text[:1000], "supports_streaming": "true",
                                       "reply_markup": json.dumps(kb)}, files={"video": fh})
        else:
            _tg("sendMessage", data={"chat_id": chat, "text": text, "reply_markup": json.dumps(kb)})
    except Exception as exc:  # noqa: BLE001
        L.warning("Telegram bildirimi gönderilemedi: %s", exc)


def tg_poll(offset: int) -> int:
    """Düğme yanıtlarını ve /start mesajını işler; yeni offset döndürür."""
    ups = _tg("getUpdates", data={"offset": offset, "timeout": 0,
                                  "allowed_updates": json.dumps(["message", "callback_query"])}) or []
    chat = tg_chat()
    for u in ups:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message")
        if msg and not chat and (msg.get("text") or "").startswith("/start"):
            chat = str(msg["chat"]["id"])
            set_secret("TELEGRAM_CHAT_ID", chat)
            _tg("sendMessage", data={"chat_id": chat, "text": "Reels Fabrikası bağlandı ✅ Onay bekleyen videolar "
                                                              "buraya gelecek."})
        cb = u.get("callback_query")
        if cb and chat and str(cb["message"]["chat"]["id"]) == chat:
            kind, _, pid = cb.get("data", "").partition(":")
            try:
                act(pid, {"ok": "approve", "no": "reject", "later": "snooze"}[kind], by="telegram")
                note = {"ok": "Onaylandı, yayınlanıyor…", "no": "Reddedildi, yayınlanmayacak.",
                        "later": "2 saat ertelendi."}[kind]
            except Exception as exc:  # noqa: BLE001
                note = f"Yapılamadı: {exc}"
            _tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": note[:190]})
            _tg("sendMessage", data={"chat_id": chat, "text": note})
    return offset


APP_STATE = ROOT / "config" / "app.json"


def settings() -> dict:
    """Kullanıcının uygulamadan değiştirdiği yayın ayarları (config/app.json → publish)."""
    return {"audience_auto": "claude", "mirofish_url": "", **((read_json(APP_STATE, {}) or {}).get("publish") or {})}


def save_settings(data: dict) -> dict:
    state = read_json(APP_STATE, {}) or {}
    cur = settings()
    if data.get("audience_auto") in ("claude", "mirofish", "off"):
        cur["audience_auto"] = data["audience_auto"]
    if "mirofish_url" in data:
        url = str(data["mirofish_url"] or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise StageError("MiroFish adresi http:// ile başlamalı")
        cur["mirofish_url"] = url
    state["publish"] = cur
    write_json(APP_STATE, state)
    return cur


def status_summary() -> dict:
    return {"telegram": {"bot": bool(secret("TELEGRAM_BOT_TOKEN")), "chat": bool(tg_chat())},
            "youtube_client": bool(secret("YOUTUBE_CLIENT_ID") and secret("YOUTUBE_CLIENT_SECRET")),
            "tiktok_client": bool(secret("TIKTOK_CLIENT_KEY") and secret("TIKTOK_CLIENT_SECRET")),
            "stock": {"pexels": bool(secret("PEXELS_API_KEY")), "pixabay": bool(secret("PIXABAY_API_KEY"))},
            **settings()}


def ceil_minutes(it: dict) -> int:
    return max(0, math.ceil((dt.datetime.fromisoformat(it["deadline"]) - now()).total_seconds() / 60))
