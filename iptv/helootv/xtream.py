"""Xtream Codes API istemcisi (player_api.php): hesap, kategoriler, canlı/film/dizi listeleri, EPG, akış adresleri."""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Callable
from urllib.parse import quote, urlencode, urlsplit

from . import epg
from .netutil import NetError, http_get


class XtreamError(Exception):
    """Kullanıcıya gösterilebilir Xtream hatası."""


def normalize_server(server: str) -> str:
    s = (server or "").strip()
    if not s:
        raise XtreamError("Sunucu adresi boş.")
    if not re.match(r"^https?://", s, re.I):
        s = "http://" + s
    parts = urlsplit(s)
    path = re.sub(r"/(player_api|get|xmltv|panel_api)\.php.*$", "", parts.path, flags=re.I).rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc}{path}"


def _as_list(obj) -> list:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        # bazı paneller {"0": {...}, "1": {...}} döndürür
        vals = list(obj.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return vals
    return []


def to_int(v, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def to_float(v, default: float | None = None) -> float | None:
    try:
        f = float(v)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def parse_duration(v) -> int:
    """'01:45:30' / '105 min' / 6330 → saniye."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    m = re.match(r"^(\d+):(\d{1,2})(?::(\d{1,2}))?$", s)
    if m:
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return h * 3600 + mi * 60 + se if m.group(3) is not None else h * 60 + mi
    m = re.match(r"^(\d+)\s*(min|dk|m)\b", s, re.I)
    if m:
        return int(m.group(1)) * 60
    return to_int(s)


def year_from(*values) -> str:
    for v in values:
        if not v:
            continue
        m = re.search(r"\b(19[2-9]\d|20[0-4]\d)\b", str(v))
        if m:
            return m.group(1)
    return ""


class XtreamClient:
    def __init__(self, server: str, username: str, password: str, *, user_agent: str | None = None,
                 timeout: float = 25, verify: bool = True, getter: Callable[[str], bytes] | None = None):
        self.server = normalize_server(server)
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        if not self.username or not self.password:
            raise XtreamError("Kullanıcı adı ve şifre gerekli.")
        self.user_agent = user_agent
        self.timeout = timeout
        self.verify = verify
        self._getter = getter

    # ------------------------------------------------------------------ HTTP
    def _fetch(self, url: str) -> bytes:
        if self._getter:
            return self._getter(url)
        try:
            return http_get(url, user_agent=self.user_agent, timeout=self.timeout, verify=self.verify)
        except NetError as e:
            raise XtreamError(f"Sunucuya ulaşılamadı: {e}") from e

    def api(self, action: str | None = None, **params):
        q = {"username": self.username, "password": self.password}
        if action:
            q["action"] = action
        q.update({k: v for k, v in params.items() if v is not None})
        data = self._fetch(f"{self.server}/player_api.php?{urlencode(q)}")
        text = data.decode("utf-8", "replace").strip()
        if not text:
            return [] if action else {}
        try:
            return json.loads(text)
        except ValueError as e:
            raise XtreamError("Sunucu geçerli bir Xtream API yanıtı vermedi (adres doğru mu?).") from e

    # ------------------------------------------------------------------ hesap
    def authenticate(self) -> dict:
        obj = self.api()
        if not isinstance(obj, dict) or not isinstance(obj.get("user_info"), dict):
            raise XtreamError("Sunucu geçerli bir Xtream API yanıtı vermedi (adres doğru mu?).")
        ui = obj["user_info"]
        if str(ui.get("auth", "1")) in ("0", "False", "false"):
            raise XtreamError("Kullanıcı adı veya şifre hatalı.")
        status = str(ui.get("status") or "Active")
        if status.lower() not in ("active", "aktif"):
            raise XtreamError(f"Hesap kullanılamıyor (durum: {status}).")
        return obj

    @staticmethod
    def account_summary(auth: dict) -> dict:
        ui = (auth or {}).get("user_info") or {}
        si = (auth or {}).get("server_info") or {}
        exp = to_int(ui.get("exp_date"), 0)
        return {
            "status": ui.get("status") or "",
            "expires": exp or None,
            "max_connections": to_int(ui.get("max_connections"), 0),
            "active_connections": to_int(ui.get("active_cons"), 0),
            "trial": str(ui.get("is_trial", "0")) == "1",
            "formats": [str(f) for f in (ui.get("allowed_output_formats") or [])],
            "timezone": si.get("timezone") or "",
            "server_time": to_int(si.get("timestamp_now"), 0) or None,
        }

    # ------------------------------------------------------------------ listeler
    def categories(self, kind: str) -> list[dict]:
        action = {"live": "get_live_categories", "movie": "get_vod_categories", "series": "get_series_categories"}[kind]
        return _as_list(self.api(action))

    def streams(self, kind: str, category_id: str | None = None) -> list[dict]:
        action = {"live": "get_live_streams", "movie": "get_vod_streams", "series": "get_series"}[kind]
        return _as_list(self.api(action, category_id=category_id))

    def vod_info(self, vod_id: str) -> dict:
        obj = self.api("get_vod_info", vod_id=vod_id)
        if not isinstance(obj, dict):
            return {}
        info = obj.get("info") if isinstance(obj.get("info"), dict) else {}
        md = obj.get("movie_data") if isinstance(obj.get("movie_data"), dict) else {}
        backdrops = info.get("backdrop_path") or []
        if isinstance(backdrops, str):
            backdrops = [backdrops]
        return {
            "title": info.get("name") or md.get("name") or "",
            "plot": info.get("plot") or info.get("description") or "",
            "genre": info.get("genre") or "",
            "director": info.get("director") or "",
            "cast": info.get("cast") or info.get("actors") or "",
            "release": info.get("releasedate") or info.get("release_date") or "",
            "year": year_from(info.get("releasedate"), info.get("release_date"), md.get("name")),
            "duration": to_int(info.get("duration_secs")) or parse_duration(info.get("duration")),
            "rating": to_float(info.get("rating")),
            "poster": info.get("movie_image") or info.get("cover_big") or "",
            "backdrop": next((b for b in backdrops if isinstance(b, str) and b), ""),
            "trailer": info.get("youtube_trailer") or "",
            "ext": md.get("container_extension") or "",
            "video": info.get("video") if isinstance(info.get("video"), dict) else {},
            "audio": info.get("audio") if isinstance(info.get("audio"), dict) else {},
        }

    def series_info(self, series_id: str) -> dict:
        obj = self.api("get_series_info", series_id=series_id)
        if not isinstance(obj, dict):
            return {"info": {}, "episodes": [], "seasons": []}
        info = obj.get("info") if isinstance(obj.get("info"), dict) else {}
        raw = obj.get("episodes") or {}
        groups: list[tuple[str | None, list]] = []
        if isinstance(raw, dict):
            groups = [(k, v) for k, v in raw.items() if isinstance(v, list)]
        elif isinstance(raw, list):
            for v in raw:
                if isinstance(v, list):
                    groups.append((None, v))
                elif isinstance(v, dict):
                    groups.append((None, [v]))
        episodes = []
        for season_key, eps in groups:
            for ep in eps:
                if not isinstance(ep, dict) or ep.get("id") in (None, ""):
                    continue
                einfo = ep.get("info") if isinstance(ep.get("info"), dict) else {}
                num = to_int(ep.get("episode_num"), 0)
                season = to_int(ep.get("season"), 0) or to_int(season_key, 1)
                episodes.append({
                    "id": str(ep["id"]),
                    "season": season,
                    "episode": num,
                    "title": (ep.get("title") or "").strip() or f"{num}. Bölüm",
                    "ext": (ep.get("container_extension") or "mp4").lstrip("."),
                    "duration": to_int(einfo.get("duration_secs")) or parse_duration(einfo.get("duration")),
                    "plot": einfo.get("plot") or "",
                    "image": einfo.get("movie_image") or einfo.get("cover_big") or "",
                    "rating": to_float(einfo.get("rating")),
                    "air_date": einfo.get("releasedate") or einfo.get("air_date") or "",
                })
        episodes.sort(key=lambda e: (e["season"], e["episode"], e["title"]))
        seasons = _as_list(obj.get("seasons"))
        return {"info": info, "episodes": episodes, "seasons": seasons}

    def short_epg(self, stream_id: str, limit: int | None = 12) -> list[dict]:
        return epg.parse_xtream_listings(self.api("get_short_epg", stream_id=stream_id, limit=limit))

    def full_epg(self, stream_id: str) -> list[dict]:
        """Kanalın tüm EPG'si (geçmiş dahil, arşiv bilgisiyle)."""
        return epg.parse_xtream_listings(self.api("get_simple_data_table", stream_id=stream_id))

    # ------------------------------------------------------------------ adresler
    @property
    def _auth_path(self) -> str:
        return f"{quote(self.username, safe='')}/{quote(self.password, safe='')}"

    def live_url(self, stream_id: str, fmt: str = "ts") -> str:
        return f"{self.server}/live/{self._auth_path}/{stream_id}.{fmt or 'ts'}"

    def movie_url(self, stream_id: str, ext: str | None) -> str:
        return f"{self.server}/movie/{self._auth_path}/{stream_id}.{(ext or 'mp4').lstrip('.')}"

    def episode_url(self, episode_id: str, ext: str | None) -> str:
        return f"{self.server}/series/{self._auth_path}/{episode_id}.{(ext or 'mp4').lstrip('.')}"

    def timeshift_url(self, stream_id: str, start_utc: int, duration_min: int, tz_name: str | None = None,
                      fmt: str = "ts") -> str:
        """Geri izleme (catch-up). Başlangıç saati sunucunun saat diliminde yazılır."""
        start = dt.datetime.fromtimestamp(int(start_utc), tz=dt.timezone.utc)
        tz = None
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tz_name)
            except Exception:  # tzdata yoksa ya da ad geçersizse yerel saate düş
                tz = None
        local = start.astimezone(tz) if tz else start.astimezone()
        return (f"{self.server}/timeshift/{self._auth_path}/{max(1, int(duration_min))}/"
                f"{local:%Y-%m-%d:%H-%M}/{stream_id}.{fmt or 'ts'}")

    def xmltv_url(self) -> str:
        return f"{self.server}/xmltv.php?{urlencode({'username': self.username, 'password': self.password})}"

    def m3u_url(self) -> str:
        q = urlencode({"username": self.username, "password": self.password, "type": "m3u_plus", "output": "ts"})
        return f"{self.server}/get.php?{q}"
