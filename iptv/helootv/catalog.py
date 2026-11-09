"""Kaynak yenileme (M3U / Xtream → SQLite), EPG içe aktarma ve oynatma adresi çözümleme."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import epg as epgmod
from .m3u import M3UPlaylist, parse_m3u, xtream_from_m3u_url
from .netutil import NetError, http_download, http_get, open_binary_maybe_gzip
from .store import Item, Store
from .textnorm import is_adult, translate_group
from .xtream import XtreamClient, XtreamError, to_float, to_int, year_from

Progress = Callable[[str], None]
FREE_TR_PLAYLIST = "https://iptv-org.github.io/iptv/countries/tr.m3u"


class RefreshError(Exception):
    pass


def _noop(_msg: str) -> None:
    pass


def stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:16]


def client_for(source: dict, settings: dict | None = None) -> XtreamClient:
    net = (settings or {}).get("network", {})
    return XtreamClient(source["url"], source["username"], source["password"],
                        user_agent=source.get("user_agent") or net.get("user_agent"),
                        timeout=max(20, net.get("timeout", 15)), verify=net.get("tls_verify", True))


# ---------------------------------------------------------------------- M3U

def load_m3u_text(source: dict, settings: dict | None = None) -> str:
    url = (source.get("url") or "").strip()
    net = (settings or {}).get("network", {})
    if url.startswith(("http://", "https://")):
        data = http_get(url, user_agent=source.get("user_agent") or net.get("user_agent"),
                        timeout=max(30, net.get("timeout", 15)), verify=net.get("tls_verify", True))
    else:
        path = Path(url.removeprefix("file://")).expanduser()
        if not path.is_file():
            raise RefreshError(f"Dosya bulunamadı: {path}")
        data = path.read_bytes()
        if data[:2] == b"\x1f\x8b":
            import gzip
            data = gzip.decompress(data)
    text = data.decode("utf-8", "replace")
    if "#EXTINF" not in text and not text.lstrip().startswith("#EXTM3U"):
        raise RefreshError("Geçerli bir M3U listesi değil (#EXTM3U/#EXTINF bulunamadı).")
    return text


def import_m3u(store: Store, source: dict, pl: M3UPlaylist, translate: bool = True) -> dict:
    sid = source["id"]
    cats: dict[str, dict[str, tuple]] = {"live": {}, "movie": {}, "series": {}}
    items: dict[str, list[tuple]] = {"live": [], "movie": [], "series": []}
    series_rows: dict[str, dict] = {}
    episodes: list[tuple] = []
    for idx, e in enumerate(pl.entries, start=1):
        group = e.group.strip() or "Diğer"
        shown = translate_group(group) if translate else group
        cat_id = stable_id(e.kind, group)
        adult = 1 if is_adult(group, e.name) else 0
        if cat_id not in cats[e.kind]:
            cats[e.kind][cat_id] = (cat_id, shown, len(cats[e.kind]), adult)
        headers = {k: v for k, v in e.headers.items() if v}
        if e.kind == "live":
            extra = {"headers": headers} if headers else {}
            catch = {k: (e.attrs.get(k) or pl.header.get(k))
                     for k in ("catchup", "catchup-type", "catchup-source", "catchup-days")
                     if e.attrs.get(k) or pl.header.get(k)}
            if catch:
                extra["catchup"] = catch
            if e.drm:
                extra["drm"] = True
            days = to_int(e.attrs.get("catchup-days") or e.attrs.get("tvg-rec") or (pl.header.get("catchup-days")), 0)
            if not days and (catch.get("catchup") or pl.header.get("catchup")):
                days = 1
            items["live"].append((stable_id(e.url), idx, e.name, cat_id, e.logo, e.url, e.tvg_id or e.tvg_name, "",
                                  None, "", 0, days, adult, json.dumps(extra, ensure_ascii=False)))
        elif e.kind == "movie":
            extra = {"headers": headers} if headers else {}
            items["movie"].append((stable_id(e.url), idx, e.name, cat_id, e.logo, e.url, "", "", None,
                                   year_from(e.name), 0, 0, adult, json.dumps(extra, ensure_ascii=False)))
        else:
            series_name = e.series or e.name
            ser_id = stable_id(series_name.lower(), group)
            if ser_id not in series_rows:
                series_rows[ser_id] = {"name": series_name, "cat": cat_id, "logo": e.logo, "num": idx, "adult": adult}
            elif not series_rows[ser_id]["logo"] and e.logo:
                series_rows[ser_id]["logo"] = e.logo
            ep_extra = {"logo": e.logo}
            if headers:
                ep_extra["headers"] = headers
            episodes.append((ser_id, stable_id(e.url), e.season or 1, e.episode or 0, e.name, e.url, "",
                             json.dumps(ep_extra, ensure_ascii=False)))
    for ser_id, s in series_rows.items():
        items["series"].append((ser_id, s["num"], s["name"], s["cat"], s["logo"], "", "", "", None, year_from(s["name"]),
                                0, 0, s["adult"], "{}"))
    counts = {}
    for kind in ("live", "movie", "series"):
        counts[kind] = store.replace_catalog(sid, kind, cats[kind].values(), items[kind],
                                             episodes if kind == "series" else None)
    return counts


# ---------------------------------------------------------------------- Xtream

def _xtream_categories(client: XtreamClient, kind: str) -> dict[str, tuple]:
    cats = {}
    for i, c in enumerate(client.categories(kind)):
        cid = str(c.get("category_id", "")).strip()
        if not cid:
            continue
        name = (c.get("category_name") or "Kategori").strip()
        adult = 1 if (str(c.get("is_adult", "0")) == "1" or is_adult(name)) else 0
        cats[cid] = (cid, name, i, adult)
    return cats


def import_xtream(store: Store, source: dict, client: XtreamClient, progress: Progress = _noop) -> dict:
    sid = source["id"]
    counts = {}
    for kind, label in (("live", "canlı kanallar"), ("movie", "filmler"), ("series", "diziler")):
        progress(f"{source['name']}: {label} alınıyor…")
        cats = _xtream_categories(client, kind)
        rows = []
        for i, s in enumerate(client.streams(kind), start=1):
            if kind == "series":
                item_id = str(s.get("series_id") or "")
                logo = s.get("cover") or ""
                added = to_int(s.get("last_modified")) or to_int(s.get("added"))
                extra = {k: v for k, v in (("plot", (s.get("plot") or "")[:700]), ("genre", s.get("genre") or ""),
                                           ("release", s.get("releaseDate") or s.get("release_date") or ""),
                                           ("cast", (s.get("cast") or "")[:300])) if v}
                bd = s.get("backdrop_path")
                if isinstance(bd, list) and bd:
                    extra["backdrop"] = bd[0]
                year = year_from(s.get("releaseDate"), s.get("release_date"), s.get("year"), s.get("name"))
            else:
                item_id = str(s.get("stream_id") or "")
                logo = s.get("stream_icon") or ""
                added = to_int(s.get("added"))
                extra = {}
                year = year_from(s.get("year"), s.get("name")) if kind == "movie" else ""
            if not item_id:
                continue
            name = (s.get("name") or s.get("title") or "").strip() or f"#{item_id}"
            cat_id = str(s.get("category_id") if s.get("category_id") is not None else "")
            if cat_id not in cats:
                if "" not in cats:
                    cats[""] = ("", "Diğer", 10**6, 0)
                cat_id = ""
            adult = 1 if (cats[cat_id][3] or str(s.get("is_adult", "0")) == "1") else 0
            if kind == "live":
                archive = to_int(s.get("tv_archive_duration")) if str(s.get("tv_archive", "0")) == "1" else 0
                rows.append((item_id, to_int(s.get("num"), i), name, cat_id, logo, "", s.get("epg_channel_id") or "",
                             "", None, "", added, archive, adult, "{}"))
            else:
                rating = to_float(s.get("rating"))
                ext = (s.get("container_extension") or "").lstrip(".")
                rows.append((item_id, to_int(s.get("num"), i), name, cat_id, logo, "", "", ext, rating, year, added,
                             0, adult, json.dumps(extra, ensure_ascii=False) if extra else "{}"))
        counts[kind] = store.replace_catalog(sid, kind, cats.values(), rows)
    return counts


# ---------------------------------------------------------------------- yenileme

def refresh_source(store: Store, source: dict, settings: dict | None = None, progress: Progress = _noop) -> dict:
    """Kaynağı indirip kataloğu yeniler. Hata olursa eski katalog korunur, sources.last_error yazılır."""
    translate = (settings or {}).get("ui", {}).get("translate_groups", True)
    try:
        if source["kind"] == "xtream":
            client = client_for(source, settings)
            progress(f"{source['name']}: hesap doğrulanıyor…")
            auth = client.authenticate()
            info = dict(source.get("info") or {})
            info["account"] = XtreamClient.account_summary(auth)
            counts = import_xtream(store, source, client, progress)
            info["counts"] = counts
            store.update_source(source["id"], last_refresh=time.time(), last_error="", info=info)
        else:
            progress(f"{source['name']}: liste indiriliyor…")
            text = load_m3u_text(source, settings)
            progress(f"{source['name']}: liste işleniyor…")
            pl = parse_m3u(text)
            counts = import_m3u(store, source, pl, translate=translate)
            info = dict(source.get("info") or {})
            info["counts"] = counts
            if pl.epg_urls:
                info["epg_auto"] = pl.epg_urls[0]
            if pl.header.get("tvg-shift"):
                info["tvg_shift"] = to_float(pl.header.get("tvg-shift"), 0.0)
            store.update_source(source["id"], last_refresh=time.time(), last_error="", info=info)
        store.map_epg_ids(source["id"])
        return counts
    except (XtreamError, NetError, RefreshError) as e:
        store.update_source(source["id"], last_error=str(e))
        raise RefreshError(str(e)) from e


def epg_url_for(source: dict, settings: dict | None = None) -> str:
    if source.get("epg_url"):
        return source["epg_url"]
    if source["kind"] == "xtream":
        try:
            return client_for(source, settings).xmltv_url()
        except XtreamError:
            return ""
    return (source.get("info") or {}).get("epg_auto", "")


def refresh_epg(store: Store, source: dict, settings: dict | None = None, progress: Progress = _noop) -> tuple[int, int]:
    url = epg_url_for(source, settings)
    if not url:
        return (0, 0)
    net = (settings or {}).get("network", {})
    shift = float((settings or {}).get("ui", {}).get("epg_shift_hours", 0.0) or 0.0)
    shift += float((source.get("info") or {}).get("tvg_shift", 0.0) or 0.0)
    progress(f"{source['name']}: yayın akışı (EPG) indiriliyor…")
    with tempfile.TemporaryDirectory(prefix="helootv-epg-") as td:
        path = Path(td) / "epg.xml"
        if url.startswith(("http://", "https://")):
            try:
                http_download(url, path, user_agent=source.get("user_agent") or net.get("user_agent"),
                              timeout=max(60, net.get("timeout", 15)), verify=net.get("tls_verify", True))
            except NetError as e:
                raise RefreshError(f"EPG indirilemedi: {e}") from e
        else:
            src = Path(url.removeprefix("file://")).expanduser()
            if not src.is_file():
                raise RefreshError(f"EPG dosyası bulunamadı: {src}")
            path = src
        progress(f"{source['name']}: yayın akışı işleniyor…")
        try:
            with open_binary_maybe_gzip(path) as f:
                n_prog, n_chan = store.replace_epg(source["id"], epgmod.iter_xmltv(f, shift_hours=shift))
        except Exception as e:  # bozuk XML
            raise RefreshError(f"EPG okunamadı: {e}") from e
    store.map_epg_ids(source["id"])
    store.update_source(source["id"], last_epg=time.time())
    return n_prog, n_chan


def add_free_turkish_channels(store: Store) -> int:
    for s in store.list_sources():
        if s["url"] == FREE_TR_PLAYLIST:
            return s["id"]
    return store.add_source(name="Ücretsiz Türk kanalları (iptv-org)", kind="m3u", url=FREE_TR_PLAYLIST)


def source_from_m3u_url(url: str) -> dict:
    """get.php?username=..&password=.. biçimindeki M3U bağlantısını Xtream kaynağına çevirir (film/dizi detayları için)."""
    xt = xtream_from_m3u_url(url)
    if xt:
        return {"kind": "xtream", "url": xt[0], "username": xt[1], "password": xt[2]}
    return {"kind": "m3u", "url": url}


# ---------------------------------------------------------------------- oynatma adresi

def play_url(store: Store, item: Item, settings: dict | None = None, source: dict | None = None) -> str:
    source = source or store.get_source(item.source_id) or {}
    if item.url:
        return item.url
    if source.get("kind") != "xtream":
        return ""
    client = client_for(source, settings)
    if item.kind == "live":
        fmt = (settings or {}).get("latency", {}).get("live_format", "ts")
        formats = ((source.get("info") or {}).get("account") or {}).get("formats") or []
        if formats and fmt not in formats:
            fmt = "m3u8" if "m3u8" in formats else formats[0]
        return client.live_url(item.item_id, fmt)
    if item.kind == "movie":
        return client.movie_url(item.item_id, item.ext)
    return ""


def item_headers(item_or_extra, source: dict | None = None) -> dict:
    extra = item_or_extra.extra_dict() if isinstance(item_or_extra, Item) else dict(item_or_extra or {})
    headers = dict(extra.get("headers") or {})
    if source and source.get("user_agent") and not headers.get("user_agent"):
        headers["user_agent"] = source["user_agent"]
    return headers
