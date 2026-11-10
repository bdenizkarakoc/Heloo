"""Film/dizi bilgileri: The Movie Database (TMDB) — Türkçe açıklama, poster, puan, tür, süre, yönetmen, oyuncular.

IPTVnator'daki gibi kullanıcının kendi ücretsiz TMDB anahtarıyla (themoviedb.org/settings/api; "API Key" ya da
"API Read Access Token" ikisi de olur). Sağlayıcı (Xtream) bilgi vermediğinde ya da M3U listelerinde boşlukları
doldurur. Sonuçlar 30 gün önbellekte tutulur (bulunamayanlar da, tekrar tekrar sorulmasın). Qt'ye bağımlı değildir.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, paths
from .netutil import _context, describe_error
from .subs_online import clean_title

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
UA = f"HelooTV v{__version__}"
TTL = 30 * 86400
_lock = threading.Lock()


class TmdbError(Exception):
    pass


def _cache_path() -> Path:
    return paths.cache_dir() / "tmdb.json"


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    p = _cache_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _call(key: str, path: str, params: dict) -> dict:
    params = dict(params)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if key.count(".") >= 2 or len(key) > 60:          # v4 "Read Access Token" (JWT)
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15,
                                    context=_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        msg = describe_error(e)
        if "401" in msg:
            msg += " — TMDB anahtarını kontrol edin (themoviedb.org/settings/api)"
        raise TmdbError(msg) from e


def split_title(title: str) -> tuple[str, str]:
    """'Esaretin Bedeli (1994) [TR]' → ('Esaretin Bedeli', '1994')."""
    m = re.search(r"\b(19[2-9]\d|20[0-4]\d)\b", title or "")
    t = re.sub(r"\[[^\]]*\]|\{[^}]*\}", " ", title or "")                       # [TR], {4K} etiketleri
    t = re.sub(r"^\s*(TR|EN|DE|FR|4K|UHD|FHD|HD)\s*[:|\-]\s*", "", t, flags=re.I)   # "TR: Film" önekleri
    query = clean_title(t)[0]
    return query.strip(" -[]()"), (m.group(1) if m else "")


def _pick(results: list, title: str, year: str, kind: str) -> dict | None:
    if not results:
        return None
    date_key = "release_date" if kind == "movie" else "first_air_date"
    name_key = "title" if kind == "movie" else "name"
    want = title.casefold()

    def score(r):
        s = float(r.get("popularity") or 0) / 1000
        names = {str(r.get(name_key) or "").casefold(), str(r.get("original_" + name_key) or "").casefold()}
        if want in names:
            s += 2
        if year and str(r.get(date_key) or "").startswith(year):
            s += 3
        return s
    return max(results, key=score)


def lookup(key: str, kind: str, title: str, year: str = "", language: str = "tr-TR") -> dict | None:
    """kind: movie | tv. Dönüş: {title, year, plot, poster, rating, genre, director, cast, duration, tmdb_id} ya da None."""
    if not key:
        raise TmdbError("TMDB anahtarı yok (Ayarlar → Ses ve altyazı → TMDB anahtarı).")
    query, y = split_title(title)
    year = year or y
    if not query:
        return None
    ck = f"{kind}|{query.casefold()}|{year}|{language}"
    with _lock:
        cache = _load_cache()
    hit = cache.get(ck)
    if hit and time.time() - hit.get("t", 0) < TTL:
        return hit.get("v")
    params = {"query": query, "language": language, "include_adult": "false"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = year
    res = _call(key, f"/search/{kind}", params).get("results") or []
    if not res and year:                       # yıl yanlış etiketlenmiş olabilir
        params.pop("year", None)
        params.pop("first_air_date_year", None)
        res = _call(key, f"/search/{kind}", params).get("results") or []
    best = _pick(res, query, year, kind)
    value = None
    if best:
        d = _call(key, f"/{kind}/{best['id']}", {"language": language, "append_to_response": "credits"})
        plot = d.get("overview") or ""
        if not plot and language != "en-US":    # Türkçe açıklama yoksa İngilizcesi
            plot = _call(key, f"/{kind}/{best['id']}", {"language": "en-US"}).get("overview") or ""
        credits = d.get("credits") or {}
        crew = credits.get("crew") or []
        director = ", ".join(c["name"] for c in crew if c.get("job") == "Director")[:80]
        if kind == "tv" and not director:
            director = ", ".join(c.get("name", "") for c in (d.get("created_by") or []))[:80]
        runtime = d.get("runtime") or ((d.get("episode_run_time") or [0])[0] if kind == "tv" else 0)
        date = d.get("release_date") or d.get("first_air_date") or ""
        value = {
            "tmdb_id": d.get("id"),
            "title": d.get("title") or d.get("name") or query,
            "year": date[:4],
            "plot": plot,
            "poster": f"{IMG}{d['poster_path']}" if d.get("poster_path") else "",
            "backdrop": f"{IMG}{d['backdrop_path']}" if d.get("backdrop_path") else "",
            "rating": round(float(d.get("vote_average") or 0), 1),
            "genre": ", ".join(g.get("name", "") for g in (d.get("genres") or [])[:3]),
            "director": director,
            "cast": ", ".join(c.get("name", "") for c in (credits.get("cast") or [])[:6]),
            "duration": int(runtime or 0) * 60,
        }
    with _lock:
        cache = _load_cache()
        cache[ck] = {"t": time.time(), "v": value}
        if len(cache) > 5000:                  # en eski kayıtları at
            for k in sorted(cache, key=lambda k: cache[k].get("t", 0))[:1000]:
                cache.pop(k, None)
        _save_cache(cache)
    return value


def merge(info: dict, extra: dict | None) -> dict:
    """Sağlayıcı bilgisindeki boşlukları TMDB ile doldurur (sağlayıcınınki varsa o kalır)."""
    if not extra:
        return info
    out = dict(info)
    for k in ("plot", "genre", "director", "cast", "year", "rating", "duration", "poster"):
        if not out.get(k) and extra.get(k):
            out[k] = extra[k]
    out["tmdb"] = True
    return out
