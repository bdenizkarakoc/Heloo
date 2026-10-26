"""Sahne görselleri: yapay zekâ üretimi, lisanslı stok/kamu malı kaynaklar veya ajanın sağladığı medya.

Sağlayıcılar (kategori ya da sahne bazında sıralanır):
  agent_media : projects/<görev>/media/<sahne>.(jpg|png|webp|mp4|mov|webm) — ajan veya kullanıcı koyar
                (ör. Claude Code oturumu Higgsfield/başka bir araçla ürettiği klibi buraya kaydeder)
  url         : senaryoda visual.url + visual.license verilmişse
  ai_video    : Replicate video modeli (REPLICATE_API_TOKEN + visuals.replicate.video_model)
  ai_image    : OpenAI görsel üretimi (OPENAI_API_KEY) veya Replicate görsel modeli
  nasa        : NASA Image and Video Library (anahtarsız; çoğunlukla kamu malı)
  pexels      : Pexels foto/video (PEXELS_API_KEY; ücretsiz ticari kullanım)
  openverse   : Openverse (anahtarsız; yalnızca CC0 / kamu malı / CC BY)
Hiçbiri sonuç vermezse sahne, hareketli grafik arka planıyla üretilir (layout şablonu).
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import log
from .config import Config, ROOT, secret
from .util import StageError, TransientError, download, http_json, media_duration, retry, run

L = log.get("visuals")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
W, H = 1080, 1920
Image.MAX_IMAGE_PIXELS = 250_000_000  # NASA/arşiv görselleri çok büyük olabilir (ör. 14000x9000)
THIRD_PARTY = re.compile(r"\b(esa|jaxa|isas|getty|reuters|associated press|courtesy of|used with permission|"
                         r"copyright)\b|©", re.I)


def license_mode(cfg: Config) -> str:
    """strict: yalnızca kullanım izni doğrulanmış medya. any: lisans kontrolü yok (kullanıcı sorumluluğunda)."""
    return "any" if str(cfg.get_path("visuals.license_mode", "strict")).lower() == "any" else "strict"


def _norm(text: str) -> str:
    from .util import tr_lower
    t = tr_lower(text or "")
    t = t.translate(str.maketrans("çğıöşüâîû_-", "cgiosuaiu  "))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def verify_subject(c: dict, subject: str) -> tuple[bool, str]:
    """Görselin konu kişiyi/varlığı gösterdiğini METİN üzerinden doğrular (yüz tanıma yapılmaz).

    Geçerli kanıtlar: kişinin Vikipedi maddesinin ana görseli olması ya da adın tamamının
    görselin başlığında, açıklamasında veya dosya adında geçmesi.
    """
    if c.get("lead"):
        return True, f"'{c.get('article')}' Vikipedi maddesinin ana görseli"
    phrase = " ".join(t for t in _norm(subject).split() if t)
    blob = " " + " ".join(_norm(" ".join(str(c.get(k) or "") for k in ("title", "desc", "file"))).split()) + " "
    if phrase and f" {phrase} " in blob:  # ad bitişik geçmeli ("Işın Karaca by Cem ..." eşleşmez)
        return True, "adı görselin başlığında/açıklamasında geçiyor"
    return False, "görsel metninde kişinin adı yok"


class Budget:
    def __init__(self, cfg: Config, state: dict):
        self.cfg = cfg
        self.state = state.setdefault("budget_used", {"ai_images": 0, "ai_videos": 0})

    def take(self, kind: str) -> bool:
        limit = {"ai_images": self.cfg.get_path("budget.max_ai_images_per_video", 8),
                 "ai_videos": self.cfg.get_path("budget.max_ai_video_clips_per_video", 4)}[kind]
        if self.state[kind] >= limit:
            L.warning("maliyet sınırı: %s (%d) doldu", kind, limit)
            return False
        self.state[kind] += 1
        return True


# ----------------------------------------------------------------------------
# Sağlayıcılar → aday listesi
# ----------------------------------------------------------------------------

def _agent_media(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    folder = job_dir / "media"
    for ext in IMG_EXT + VID_EXT + (".svg",):
        f = folder / f"{scene['id']}{ext}"
        if f.exists():
            meta = {}
            side = folder / f"{scene['id']}.json"
            if side.exists():
                import json
                meta = json.loads(side.read_text(encoding="utf-8"))
            return [{"path": str(f), "provider": meta.get("provider", "agent_media"),
                     "kind": "video" if ext in VID_EXT else "photo",
                     "title": meta.get("title", f.name), "license": meta.get("license", "agent-supplied"),
                     "credit": meta.get("credit", ""), "source": meta.get("source", "")}]
    return []


def _url(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    vis = scene["visual"]
    if not vis.get("url"):
        return []
    if not vis.get("license"):
        L.warning("%s: visual.url için visual.license belirtilmemiş; kullanılmadı", scene["id"])
        return []
    kind = "video" if vis["url"].lower().split("?")[0].endswith(VID_EXT) else "photo"
    return [{"url": vis["url"], "provider": "url", "kind": kind, "title": vis.get("title", ""),
             "license": vis["license"], "credit": vis.get("credit", ""), "source": vis["url"]}]


def _nasa(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    q = scene["visual"].get("query")
    if not q:
        return []
    data = retry(3, 2.0)(http_json)("GET", "https://images-api.nasa.gov/search",
                                     params={"q": q, "media_type": "image", "page_size": 25})
    out = []
    for it in data.get("collection", {}).get("items", []):
        d = (it.get("data") or [{}])[0]
        links = {l["href"].rsplit("~", 1)[-1].split(".")[0]: l for l in it.get("links", []) if "~" in l.get("href", "")}
        pick = None
        for key in ("orig", "large"):
            l = links.get(key)
            if l and l["href"].lower().endswith((".jpg", ".jpeg", ".png")) and (l.get("size") or 0) < 30e6:
                pick = l
                break
        if not pick:
            continue
        credit = d.get("secondary_creator") or d.get("photographer") or f"NASA/{d.get('center', '')}".rstrip("/")
        # NASA kütüphanesindeki ortak kurum (ESA, JAXA vb.) ve telif ibareli görseller kamu malı değildir.
        third = THIRD_PARTY.search(f"{credit} {d.get('description', '')} {d.get('title', '')}")
        if third and license_mode(cfg) == "strict":
            continue
        out.append({"url": pick["href"], "w": pick.get("width"), "h": pick.get("height"), "provider": "nasa",
                    "kind": "photo", "title": d.get("title", ""), "license": "Kamu malı — NASA medya kullanım yönergeleri",
                    "credit": credit, "source": f"https://images.nasa.gov/details/{d.get('nasa_id')}",
                    "thumb": links.get("thumb", {}).get("href"),
                    "desc": " ".join(d.get("keywords") or []) + " " + (d.get("description") or "")[:300]})
    return out


# Konuşan kişi, röportaj, basın toplantısı gibi arka plan videosu olarak uygun olmayan NASA videoları
VIDEO_OFFTOPIC = re.compile(r"\b(asked|scientist|interview|explains?|briefing|conference|live|q&a|press|talk|"
                            r"webinar|podcast|update|news|media|panel|town hall|event|ceremony|horizontal video)\b", re.I)


def _nasa_video(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    """NASA video arşivi (kamu malı, anahtarsız). Konuşma/röportaj videoları elenir."""
    q = scene["visual"].get("query")
    if not q or scene["visual"].get("kind") != "video":
        return []
    words = q.split()
    found = []
    for sub in dict.fromkeys([q, " ".join(words[:2]), words[0]]):  # ayrıntılı sorgu boş dönerse kısalt
        data = retry(3, 2.0)(http_json)("GET", "https://images-api.nasa.gov/search",
                                         params={"q": sub, "media_type": "video", "page_size": 30})
        found = data.get("collection", {}).get("items", [])
        if found:
            break
    items = []
    for it in found:
        d = (it.get("data") or [{}])[0]
        title = d.get("title", "")
        if VIDEO_OFFTOPIC.search(title) or not it.get("href"):
            continue
        credit = d.get("secondary_creator") or f"NASA/{d.get('center', '')}".rstrip("/")
        if THIRD_PARTY.search(f"{credit} {d.get('description', '')}") and license_mode(cfg) == "strict":
            continue
        items.append({"provider": "nasa", "kind": "video", "title": title, "href": it["href"],
                      "license": "Kamu malı — NASA medya kullanım yönergeleri", "credit": credit,
                      "source": f"https://images.nasa.gov/details/{d.get('nasa_id')}",
                      "desc": " ".join(d.get("keywords") or []) + " " + (d.get("description") or "")[:300]})
    out = []
    for c in rank(items, q)[:6]:  # dosya listesi yalnızca en ilgili birkaç video için alınır
        try:
            files = retry(2, 2.0)(http_json)("GET", c.pop("href").replace(" ", "%20"))
        except (StageError, TransientError):
            continue
        mp4 = {f.rsplit("~", 1)[-1].split(".")[0]: f for f in files if f.lower().endswith(".mp4") and "~" in f}
        url = mp4.get("medium") or mp4.get("small") or mp4.get("mobile")
        if url:
            out.append({**c, "url": url.replace("http://", "https://").replace(" ", "%20"), "w": 1280, "h": 720})
    return out


def _pixabay(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    """Pixabay foto/video (PIXABAY_API_KEY; ücretsiz, ticari kullanım serbest)."""
    key = secret("PIXABAY_API_KEY")
    q = scene["visual"].get("query")
    if not key or not q:
        return []
    out = []
    if scene["visual"].get("kind") == "video":
        data = retry(3, 2.0)(http_json)("GET", "https://pixabay.com/api/videos/",
                                         params={"key": key, "q": q[:100], "per_page": 20, "safesearch": "true"})
        for v in data.get("hits", []):
            f = (v.get("videos") or {}).get("large") or (v.get("videos") or {}).get("medium") or {}
            if f.get("url"):
                out.append({"url": f["url"], "w": f.get("width"), "h": f.get("height"), "provider": "pixabay",
                            "kind": "video", "title": v.get("tags", ""), "license": "Pixabay Content License",
                            "credit": f"Video: {v.get('user', '')} / Pixabay", "source": v.get("pageURL", "")})
    data = retry(3, 2.0)(http_json)("GET", "https://pixabay.com/api/",
                                     params={"key": key, "q": q[:100], "per_page": 20, "image_type": "photo",
                                             "safesearch": "true"})
    for p in data.get("hits", []):
        out.append({"url": p.get("largeImageURL"), "w": p.get("imageWidth"), "h": p.get("imageHeight"),
                    "thumb": p.get("previewURL"), "provider": "pixabay", "kind": "photo", "title": p.get("tags", ""),
                    "license": "Pixabay Content License", "credit": f"Foto: {p.get('user', '')} / Pixabay",
                    "source": p.get("pageURL", "")})
    return out


def _openverse(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    q = scene["visual"].get("query")
    if not q:
        return []
    lic = ",".join(cfg.get_path("visuals.license_allow", ["cc0", "pdm", "by"]))
    strict = license_mode(cfg) == "strict"
    params = {"q": q, "page_size": 20, "mature": "false"}
    if strict:
        params["license"] = lic
    data = retry(3, 2.0)(http_json)("GET", "https://api.openverse.org/v1/images/", params=params)
    out = []
    for r in data.get("results", []):
        if strict and r.get("license") not in lic.split(","):
            continue
        out.append({"url": r["url"], "w": r.get("width"), "h": r.get("height"), "provider": "openverse",
                    "kind": "photo", "title": r.get("title", ""),
                    "license": f"{r.get('license', '').upper()} {r.get('license_version') or ''}".strip(),
                    "credit": r.get("attribution") or r.get("creator") or "",
                    "source": r.get("foreign_landing_url") or r["url"], "thumb": r.get("thumbnail")})
    return out


FREE_LICENSE = re.compile(r"^(cc0|public domain|pd\b|pd-|cc[ -]by(?![ -]?(sa|nc|nd))[ -]?\d)", re.I)
SKIP_FILES = re.compile(r"(logo|flag|bayrak|icon|ikon|signature|imza|map|harita|\.svg$|commons-|wiki|symbol|sembol)", re.I)


def _wiki_api(lang: str, params: dict) -> dict:
    return retry(3, 2.0)(http_json)("GET", f"https://{lang}.wikipedia.org/w/api.php",
                                    params={"format": "json", "formatversion": 2, **params})


def _wikipedia(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    """Kişi/varlık için Vikipedi maddesindeki görseller (lisans bilgisi Commons/yerel wiki'den okunur)."""
    subject = scene["visual"].get("subject")
    if not subject:
        return []
    strict = license_mode(cfg) == "strict"
    out: list[dict] = []
    for lang in cfg.get_path("visuals.wikipedia_langs", ["tr", "en"]):
        hits = _wiki_api(lang, {"action": "query", "list": "search", "srsearch": subject, "srlimit": 1})
        found = hits.get("query", {}).get("search", [])
        if not found:
            continue
        article = found[0]["title"]
        lead = _wiki_api(lang, {"action": "query", "titles": article, "prop": "pageimages", "piprop": "name"})
        lead_name = ((lead.get("query", {}).get("pages") or [{}])[0]).get("pageimage", "")
        data = _wiki_api(lang, {"action": "query", "titles": article, "generator": "images", "gimlimit": 50,
                                "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600})
        for page in data.get("query", {}).get("pages", []) or []:
            info = (page.get("imageinfo") or [{}])[0]
            name = page.get("title", "").split(":", 1)[-1]
            if not info or info.get("mime") not in ("image/jpeg", "image/png") or SKIP_FILES.search(name):
                continue
            meta = info.get("extmetadata") or {}
            lic = re.sub("<[^>]+>", "", (meta.get("LicenseShortName") or {}).get("value", "")).strip()
            if strict and not FREE_LICENSE.search(lic):
                continue
            desc = re.sub("<[^>]+>", " ", (meta.get("ImageDescription") or {}).get("value", ""))
            artist = re.sub("<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
            out.append({"url": info.get("thumburl") or info.get("url"), "w": info.get("thumbwidth") or info.get("width"),
                        "h": info.get("thumbheight") or info.get("height"), "provider": f"wikipedia:{lang}",
                        "kind": "photo", "title": name, "file": name, "desc": desc[:300], "article": article,
                        "lead": name.replace(" ", "_") == lead_name.replace(" ", "_"),
                        "license": lic or "lisans bilgisi yok", "credit": artist,
                        "source": info.get("descriptionurl") or info.get("url")})
        if out:
            break
    out.sort(key=lambda c: not c["lead"])
    return out


def _pexels(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    key = secret("PEXELS_API_KEY")
    q = scene["visual"].get("query")
    if not key or not q:
        return []
    hdr = {"Authorization": key}
    orient = cfg.get_path("visuals.pexels.orientation", "portrait")
    out = []
    if scene["visual"].get("kind") == "video":
        data = retry(3, 2.0)(http_json)("GET", "https://api.pexels.com/videos/search", headers=hdr,
                                         params={"query": q, "orientation": orient, "per_page": 10})
        for v in data.get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("height")]
            files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
            if files:
                f = files[0]
                out.append({"url": f["link"], "w": f.get("width"), "h": f.get("height"), "provider": "pexels",
                            "kind": "video", "title": v.get("url", ""), "license": "Pexels License",
                            "credit": f"Video: {v.get('user', {}).get('name', '')} / Pexels",
                            "source": v.get("url", "")})
    data = retry(3, 2.0)(http_json)("GET", "https://api.pexels.com/v1/search", headers=hdr,
                                     params={"query": q, "orientation": orient, "per_page": 10})
    for p in data.get("photos", []):
        out.append({"url": p["src"]["original"], "w": p.get("width"), "h": p.get("height"),
                    "thumb": p["src"].get("medium"), "provider": "pexels", "kind": "photo", "title": p.get("alt", ""),
                    "license": "Pexels License", "credit": f"Foto: {p.get('photographer', '')} / Pexels",
                    "source": p.get("url", "")})
    return out


def _ai_image(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    prompt = scene["visual"].get("prompt")
    if not prompt:
        return []
    style = ", vertical 9:16 composition, cinematic lighting, highly detailed, no text, no watermark"
    if secret("OPENAI_API_KEY"):
        if not budget.take("ai_images"):
            return []
        ocfg = cfg.get_path("visuals.openai", {})
        data = retry(2, 3.0)(http_json)(
            "POST", "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {secret('OPENAI_API_KEY')}"},
            json={"model": ocfg.get("model", "gpt-image-1"), "prompt": prompt + style,
                  "size": ocfg.get("size", "1024x1536"), "quality": ocfg.get("quality", "medium"), "n": 1},
            timeout=300)
        b64 = data["data"][0].get("b64_json")
        dest = job_dir / "visuals" / f"{scene['id']}_ai.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if b64:
            dest.write_bytes(base64.b64decode(b64))
        else:
            download(data["data"][0]["url"], dest)
        return [{"path": str(dest), "provider": "ai_image:openai", "kind": "photo", "title": prompt[:80],
                 "license": "AI üretimi (OpenAI kullanım koşulları)", "credit": "", "source": "generated"}]
    hf_model = cfg.get_path("visuals.huggingface.image_model", "black-forest-labs/FLUX.1-schnell")
    if secret("HF_TOKEN") and hf_model:
        # Hugging Face Inference (ücretsiz hesapta küçük aylık kota); FLUX.1-schnell Apache-2.0: ticari kullanım serbest
        if not budget.take("ai_images"):
            return []
        import requests
        try:
            r = requests.post(f"https://router.huggingface.co/hf-inference/models/{hf_model}", timeout=180,
                              headers={"Authorization": f"Bearer {secret('HF_TOKEN')}", "Accept": "image/jpeg"},
                              json={"inputs": prompt + style, "parameters": {"width": 768, "height": 1344}})
        except requests.RequestException as exc:
            raise TransientError(f"Hugging Face: {type(exc).__name__}") from exc
        if r.status_code == 402:
            L.warning("Hugging Face aylık ücretsiz kotası doldu; AI görsel atlandı")
        elif r.status_code >= 400 or not r.headers.get("content-type", "").startswith("image/"):
            L.warning("Hugging Face görsel üretemedi (%s): %s", r.status_code, r.text[:200])
        else:
            dest = job_dir / "visuals" / f"{scene['id']}_ai.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return [{"path": str(dest), "provider": f"ai_image:hf:{hf_model}", "kind": "photo", "title": prompt[:80],
                     "license": "AI üretimi (FLUX.1-schnell, Apache-2.0)", "credit": "", "source": "generated"}]
    model = cfg.get_path("visuals.replicate.image_model")
    if secret("REPLICATE_API_TOKEN") and model:
        if not budget.take("ai_images"):
            return []
        url = _replicate_run(model, {"prompt": prompt + style, "aspect_ratio": "9:16"}, cfg)
        return [{"url": url, "provider": f"ai_image:replicate:{model}", "kind": "photo", "title": prompt[:80],
                 "license": "AI üretimi (model lisansına bakın)", "credit": "", "source": "generated"}]
    return []


def _ai_video(scene: dict, job_dir: Path, cfg: Config, budget: Budget) -> list[dict]:
    prompt = scene["visual"].get("prompt")
    model = cfg.get_path("visuals.replicate.video_model")
    if not prompt or not model or not secret("REPLICATE_API_TOKEN") or scene["visual"].get("kind") != "video":
        return []
    if not budget.take("ai_videos"):
        return []
    full = prompt + ", vertical 9:16, cinematic, smooth camera motion, no text, no watermark"
    try:
        url = _replicate_run(model, {"prompt": full, "aspect_ratio": "9:16"}, cfg, timeout=900)
    except StageError as exc:  # model aspect_ratio girdisini tanımıyorsa yalnızca prompt ile dene
        if "aspect" not in str(exc).lower() and "422" not in str(exc):
            raise
        url = _replicate_run(model, {"prompt": full}, cfg, timeout=900)
    return [{"url": url, "provider": f"ai_video:replicate:{model}", "kind": "video", "title": prompt[:80],
             "license": "AI üretimi (model lisansına bakın)", "credit": "", "source": "generated"}]


def _replicate_run(model: str, inputs: dict, cfg: Config, timeout: int = 300) -> str:
    """Replicate HTTP API: tahmin oluşturur, tamamlanana kadar bekler ve çıktı URL'sini döndürür."""
    hdr = {"Authorization": f"Bearer {secret('REPLICATE_API_TOKEN')}", "Prefer": "wait"}
    pred = retry(2, 3.0)(http_json)("POST", f"https://api.replicate.com/v1/models/{model}/predictions",
                                     headers=hdr, json={"input": inputs}, timeout=120)
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > timeout:
            raise StageError(f"Replicate zaman aşımı: {model}")
        time.sleep(4)
        pred = retry(3, 2.0)(http_json)("GET", pred["urls"]["get"], headers=hdr)
    if pred["status"] != "succeeded":
        raise StageError(f"Replicate {model}: {pred.get('error')}")
    out = pred.get("output")
    return out[0] if isinstance(out, list) else out


SEARCH_PROVIDERS = {"nasa", "nasa_video", "openverse", "pexels", "pixabay", "wikipedia"}
VIDEO_PROVIDERS = ["pexels", "pixabay", "nasa_video", "ai_video"]  # gerçek klip önce; AI video yalnızca yedek
# Konudan çok "etkinlik/insan" fotoğrafı olduğunu düşündüren kelimeler (otomatik seçimde geri plana itilir)
OFFTOPIC = re.compile(r"\b(viewing|visitors?|students?|people|crowd|team|briefing|conference|press|award|"
                      r"ceremony|workshop|event|portrait|poster|logo|diagram|chart|graph|illustration of the team|"
                      r"engineers?|technicians?|celebrat\w*)\b", re.I)


def relevance(c: dict, query: str) -> float:
    terms = {t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2}
    title = (c.get("title") or "").lower()
    text = title + " " + (c.get("desc") or "").lower()
    return sum(2.0 for t in terms if t in title) + sum(0.5 for t in terms if t in text)


def rank(cands: list[dict], query: str) -> list[dict]:
    """Arama sonuçlarını sorgu kelimeleriyle örtüşmeye göre sıralar; etkinlik/insan fotoğraflarını cezalandırır."""
    terms = {t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2}

    def score(item: tuple[int, dict]) -> tuple[float, int]:
        i, c = item
        title = (c.get("title") or "").lower()
        text = title + " " + (c.get("desc") or "").lower()
        sc = sum(2.0 for t in terms if t in title) + sum(0.5 for t in terms if t in text)
        if OFFTOPIC.search(title):
            sc -= 4.0
        if c.get("w") and c.get("h") and min(c["w"], c["h"]) >= 1400:
            sc += 0.5
        return (-sc, i)

    return [c for _, c in sorted(enumerate(cands), key=score)]


def _parse_pick(pick) -> tuple[str | None, int | None]:
    if pick is None:
        return None, None
    if isinstance(pick, int):
        return None, pick
    name, _, idx = str(pick).partition(":")
    return (name or None), (int(idx) if idx.strip().isdigit() else None)


def search_candidates(scene: dict, job_dir: Path, cfg: Config, providers: list[str], limit: int = 12) -> dict:
    """Ücretsiz arama sağlayıcılarından sıralanmış aday listesi (ajan incelemesi için)."""
    budget = Budget(cfg, {})
    out = {}
    for name in providers:
        if name not in SEARCH_PROVIDERS:
            continue
        try:
            cands = PROVIDERS[name](scene, job_dir, cfg, budget)
        except (StageError, TransientError, KeyError) as exc:
            L.warning("%s: %s", name, exc)
            continue
        out[name] = rank(cands, scene["visual"].get("query", ""))[:limit]
    return out


PROVIDERS = {
    "agent_media": _agent_media, "url": _url, "ai_video": _ai_video, "ai_image": _ai_image,
    "nasa": _nasa, "nasa_video": _nasa_video, "pexels": _pexels, "pixabay": _pixabay, "openverse": _openverse,
    "wikipedia": _wikipedia,
}


# ----------------------------------------------------------------------------
# Seçim, indirme ve ön işleme
# ----------------------------------------------------------------------------

def _dhash(img: Image.Image) -> int:
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
    return bits


def _similar(a: int, b: int) -> bool:
    return bin(a ^ b).count("1") <= 6


def prepare_image(src: Path, dest_dir: Path, sid: str, crop: list | None = None) -> dict:
    img = Image.open(src)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if crop and len(crop) == 4:  # [x0, y0, x1, y1] — 0..1 kesirleri (ör. çok panelli görselden tek panel)
        cw, ch = img.size
        x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in crop)
        img = img.crop((int(x0 * cw), int(y0 * ch), int(x1 * cw), int(y1 * ch)))
    w, h = img.size
    scale = min(1.0, 2400 / max(w, h))
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    main = dest_dir / f"{sid}.jpg"
    img.save(main, quality=90)
    # Bulanık, karartılmış arka plan (kart yerleşimi ve grafik sahneleri için)
    bg = ImageOps.fit(img, (int(W * 1.15), int(H * 1.15)), Image.LANCZOS)
    bg = bg.resize((bg.width // 4, bg.height // 4)).filter(ImageFilter.GaussianBlur(10))
    bg = bg.resize((int(W * 1.15), int(H * 1.15)), Image.LANCZOS)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (8, 10, 18)), 0.45)
    bg.save(dest_dir / f"{sid}_bg.jpg", quality=85)
    return {"file": main.name, "bg": f"{sid}_bg.jpg", "w": img.width, "h": img.height,
            "hash": _dhash(img), "kind": "photo"}


def prepare_video(src: Path, dest_dir: Path, sid: str, seconds: float, start: float | None = None) -> dict:
    """Klibi sahne süresine getirir: uzun videolarda giriş/jenerik atlanır, kısa klip döngülenir."""
    dest = dest_dir / f"{sid}.mp4"
    try:
        total = media_duration(src)
    except (StageError, ValueError, KeyError):
        total = 0.0
    if start is None:
        start = total * 0.2 if total > seconds * 3 else 0.0
    start = max(0.0, min(start, max(0.0, total - seconds - 0.5))) if total else 0.0
    run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", src,
         "-t", f"{seconds + 1.0:.2f}", "-an",
         "-vf", "scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)',fps=30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dest])
    frame = dest_dir / f"{sid}_poster.jpg"
    run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", dest, "-frames:v", "1", frame])
    info = prepare_image(frame, dest_dir, f"{sid}_poster")
    with Image.open(frame) as im:
        w, h = im.size
    return {"file": dest.name, "bg": info["bg"], "w": w, "h": h, "hash": info["hash"], "kind": "video"}


def vet_clip(clip: Path, query: str, cfg: Config) -> tuple[bool, str]:
    """Belgesel/arşiv klipleri için Claude görsel denetimi: üzerine yazılmış metin, logo, konuşan kişi veya
    konu dışı içerik varsa klip kullanılmaz. Claude yoksa (False) — denetlenemeyen arşiv klibi kullanılmaz."""
    from .studio import ai_mode, ask_ai
    if ai_mode(cfg) == "none":
        return False, "Claude yok: arşiv klibi denetlenemedi"
    total = media_duration(clip)
    frames = []
    for i, t in enumerate((total * 0.15, total * 0.5, total * 0.85)):
        f = clip.with_name(f"{clip.stem}_vet{i}.jpg")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=-2:360", f])
        frames.append(f)
    sheet = clip.with_name(f"{clip.stem}_vet.jpg")
    ims = [Image.open(f).convert("RGB") for f in frames]
    out = Image.new("RGB", (sum(im.width for im in ims) + 20, max(im.height for im in ims)), (0, 0, 0))
    x = 0
    for im in ims:
        out.paste(im, (x, 0))
        x += im.width + 10
    out.save(sheet, quality=85)
    res = ask_ai(cfg, f"Bu üç kare, '{query}' konulu bir videoda arka plan klibi olarak kullanılacak bir videodan. "
                      "Kullanılabilir mi? Kullanılamaz sayılır: üzerinde yazı/altyazı/başlık/logo/filigran varsa, "
                      "kameraya konuşan kişi veya röportaj varsa, konuyla ilgisizse. "
                      'Yalnızca JSON: {"ok": true/false, "reason": "kısa Türkçe"}', [sheet],
                 clip.with_name(f"{clip.stem}_vet.json"), timeout=300)
    for f in frames:
        f.unlink(missing_ok=True)
    if not res:
        return False, "denetim yanıtı alınamadı"
    return bool(res.get("ok")), str(res.get("reason", ""))


def choose_fit(meta: dict, scene: dict) -> str:
    fit = scene["visual"].get("fit", "auto")
    if fit in ("cover", "card", "contain"):
        return fit
    aspect = meta["w"] / max(1, meta["h"])
    if aspect <= 1.05 or scene["layout"] == "hook":
        return "cover"
    return "card"


def fetch_scene_visual(scene: dict, job_dir: Path, cfg: Config, providers: list[str], used: dict,
                       budget: Budget, seconds: float) -> dict | None:
    """Sahne için ilk uygun görseli bulur; bulamazsa None (grafik arka plana düşülür).

    visuals.prefer_video açıksa fotoğraf sahnelerinde önce konuyla yeterince ilgili bir video klip aranır."""
    vis = scene["visual"]
    if (cfg.get_path("visuals.prefer_video", False) and vis.get("kind") == "photo" and vis.get("query")
            and not vis.get("subject") and not vis.get("pick") and not vis.get("providers")):
        trial = {**scene, "visual": {**vis, "kind": "video", "providers": VIDEO_PROVIDERS,
                                     "min_relevance": float(cfg.get_path("visuals.video_min_relevance", 2.0))}}
        meta = _fetch(trial, job_dir, cfg, providers, used, budget, seconds)
        if meta:
            return meta
    return _fetch(scene, job_dir, cfg, providers, used, budget, seconds)


def _fetch(scene: dict, job_dir: Path, cfg: Config, providers: list[str], used: dict,
           budget: Budget, seconds: float) -> dict | None:
    if scene["visual"].get("kind") == "graphic" and not scene["visual"].get("query") \
            and not scene["visual"].get("prompt"):
        return None
    min_side = cfg.get_path("visuals.min_short_side", 720)
    out_dir = job_dir / "visuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    skip = set(scene["visual"].get("skip", []))
    pick_provider, pick_index = _parse_pick(scene["visual"].get("pick"))
    order = scene["visual"].get("providers") or providers
    if pick_provider:
        order = [pick_provider] + [p for p in order if p != pick_provider]
    for name in order:
        fn = PROVIDERS.get(name)
        if fn is None:
            continue
        try:
            cands = fn(scene, job_dir, cfg, budget)
        except (StageError, TransientError, KeyError) as exc:
            L.warning("%s: sağlayıcı %s başarısız: %s", scene["id"], name, exc)
            continue
        if name in SEARCH_PROVIDERS:
            cands = rank(cands, scene["visual"].get("query", ""))
        if pick_index is not None and name == order[0] and 0 <= pick_index < len(cands):
            cands = [cands[pick_index]] + [c for i, c in enumerate(cands) if i != pick_index]
        for idx, c in enumerate(cands[: cfg.get_path("visuals.candidates_per_scene", 6) * 2]):
            src_id = c.get("url") or c.get("path")
            if src_id in used["sources"] or src_id in skip:
                continue
            subject = scene["visual"].get("subject")
            if subject and SKIP_FILES.search(f"{c.get('title', '')} {c.get('file', '')}"):
                continue  # imza, logo, bayrak, harita vb. kişi görseli değildir
            verified, why = (True, "") if not subject or name not in SEARCH_PROVIDERS else verify_subject(c, subject)
            if not verified:
                L.info("%s: '%s' doğrulanamadı (%s), atlandı", scene["id"], c.get("title", "")[:50], why)
                continue
            c["verified"] = why
            if scene["visual"].get("min_relevance") and name in SEARCH_PROVIDERS and \
                    relevance(c, scene["visual"].get("query", "")) < scene["visual"]["min_relevance"]:
                continue  # otomatik video denemesi: konuyla ilgisi zayıf klip yerine fotoğrafa dönülür
            if c.get("w") and c.get("h") and min(c["w"], c["h"]) < min_side:
                continue
            try:
                if c.get("path"):
                    raw = Path(c["path"])
                    if raw.suffix.lower() == ".svg":  # ajanın çizdiği vektör illüstrasyon → PNG
                        png = out_dir / f"{scene['id']}_svg.png"
                        run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-frames:v", "1", png])
                        raw = png
                else:
                    ext = Path(c["url"].split("?")[0]).suffix.lower() or (".mp4" if c["kind"] == "video" else ".jpg")
                    raw = retry(3, 2.0)(download)(c["url"], out_dir / f"{scene['id']}_raw{ext}", max_mb=150)
                if c["kind"] == "video" or raw.suffix.lower() in VID_EXT:
                    meta = prepare_video(raw, out_dir, scene["id"], seconds, scene["visual"].get("start"))
                else:
                    meta = prepare_image(raw, out_dir, scene["id"], scene["visual"].get("crop"))
            except (StageError, TransientError, OSError) as exc:
                L.warning("%s: aday indirilemedi/işlenemedi (%s): %s", scene["id"], name, exc)
                continue
            if min(meta["w"], meta["h"]) < min_side and c["provider"] != "agent_media":
                continue
            if name == "nasa_video":  # arşiv klipleri sıklıkla yazı/jenerik içerir: görsel denetim şart
                vetted = scene["visual"].setdefault("_vetted", 0)
                if vetted >= 2:
                    continue
                scene["visual"]["_vetted"] = vetted + 1
                ok, why = vet_clip(out_dir / meta["file"], scene["visual"].get("query", ""), cfg)
                L.info("%s: arşiv klibi '%s' denetimi: %s (%s)", scene["id"], c.get("title", "")[:40],
                       "uygun" if ok else "uygun değil", why)
                if not ok:
                    continue
            if any(_similar(meta["hash"], h) for h in used["hashes"]):
                L.info("%s: önceki sahneyle aynı görünen görsel atlandı", scene["id"])
                continue
            used["sources"].add(src_id)
            used["hashes"].append(meta["hash"])
            meta.update({k: c.get(k, "") for k in ("provider", "title", "license", "credit", "source", "verified")})
            # Kendi ürettiğimiz (ajan çizimi / AI üretimi) içerikler lisans riski taşımaz
            own = name in ("agent_media", "ai_image", "ai_video") and c.get("license") != "agent-supplied"
            meta["license_checked"] = license_mode(cfg) == "strict" or own
            meta["candidate_index"] = idx
            meta["fit"] = choose_fit(meta, scene)
            meta.pop("hash", None)
            return meta
    return None


def contact_sheet(items: list[tuple[str, Path | None, str]], dest: Path, font_path: Path) -> Path:
    """Seçilen görselleri sahne adı ve kaynağıyla tek bir inceleme görüntüsünde toplar."""
    tw, th = 360, 640
    cols = min(5, max(1, len(items)))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 70)), (16, 18, 26))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(font_path), 20)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, path, sub) in enumerate(items):
        x, y = (i % cols) * tw, (i // cols) * (th + 70)
        if path and path.exists():
            with Image.open(path) as im:
                sheet.paste(ImageOps.fit(im.convert("RGB"), (tw - 8, th - 8)), (x + 4, y + 4))
        else:
            draw.rectangle([x + 4, y + 4, x + tw - 4, y + th - 4], outline=(90, 90, 110), width=2)
            draw.text((x + 20, y + th // 2), "grafik arka plan", fill=(150, 150, 170), font=font)
        draw.text((x + 8, y + th + 6), label[:30], fill=(255, 210, 63), font=font)
        draw.text((x + 8, y + th + 34), sub[:34], fill=(200, 205, 220), font=font)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=85)
    return dest


def candidates_sheet(found: dict, dest: Path, font_path: Path) -> Path:
    """Aday küçük resimlerini 'sağlayıcı:sıra' etiketleriyle tek görüntüde toplar."""
    items = []
    tmp = dest.parent / "_thumbs"
    tmp.mkdir(parents=True, exist_ok=True)
    for name, cands in found.items():
        for i, c in enumerate(cands):
            path = None
            for url in [u for u in (c.get("thumb"), c.get("url")) if u]:
                try:
                    path = download(url, tmp / f"{name}_{i}.img", max_mb=25)
                    with Image.open(path) as im:
                        im.verify()
                    break
                except Exception:  # noqa: BLE001 — erişilemeyen küçük resim inceleme sayfasını engellemesin
                    path = None
            items.append((f"{name}:{i}  {c.get('w') or '?'}x{c.get('h') or '?'}", path, c.get("title", "")))
    return contact_sheet(items, dest, font_path)
