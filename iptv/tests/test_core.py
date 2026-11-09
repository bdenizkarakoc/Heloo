"""Çekirdek: M3U ayrıştırma, Xtream istemcisi, EPG, SQLite katalog ve ayarlar."""
import base64
import json

import pytest

from conftest import DATA
from helootv import catalog, epg, m3u, settings as settings_mod
from helootv.store import Store
from helootv.textnorm import is_adult, match_key, norm, translate_group
from helootv.xtream import XtreamClient, XtreamError, normalize_server, parse_duration


# ---------------------------------------------------------------- metin

def test_norm_turkish():
    assert norm("İSTANBUL Şehir Çağrı ÖĞÜ") == "istanbul sehir cagri ogu"
    assert match_key("TR: TRT 1 HD (1080p)") == "trt1"
    assert match_key("ATV  FHD") == "atv"
    assert translate_group("Animation;Kids") == "Animasyon, Çocuk"
    assert is_adult("XXX Adult") and is_adult("+18 Gece") and not is_adult("Spor")


# ---------------------------------------------------------------- M3U

def test_parse_m3u_sample():
    pl = m3u.parse_m3u((DATA / "sample.m3u").read_text(encoding="utf-8"))
    assert pl.epg_urls == ["http://epg.example.com/guide.xml.gz"]
    by_name = {e.name: e for e in pl.entries}
    trt = by_name["TRT 1 HD"]
    assert trt.kind == "live" and trt.tvg_id == "TRT1.tr" and trt.group == "Ulusal, HD"
    atv = by_name["ATV"]
    assert atv.headers["user_agent"].startswith("Mozilla/5.0") and "KHTML, like Gecko" in atv.headers["user_agent"]
    assert atv.headers["referrer"] == "https://www.atv.com.tr/"
    # grup adı "Movies" olsa da canlı yayın bağlantısı canlı kalır (iptv-org film kanalları)
    assert by_name["Film Kanalı (720p)"].kind == "live"
    radyo = by_name["Radyo|Spor"]
    assert radyo.url == "http://example.com/radyo.mp3" and radyo.group == "Radyo"
    assert radyo.headers == {"user_agent": "KodiUA", "referrer": "https://ref.example/"}
    film = by_name["Başlangıç (2010)"]
    assert film.kind == "movie"
    osman = by_name["Kuruluş Osman S02 E05"]
    assert (osman.kind, osman.series, osman.season, osman.episode) == ("series", "Kuruluş Osman", 2, 5)
    yali = by_name["Yalı Çapkını 2. Sezon 14. Bölüm"]
    assert (yali.kind, yali.series, yali.season, yali.episode) == ("series", "Yalı Çapkını", 2, 14)
    assert by_name["DRM Kanal"].drm
    assert pl.counts() == {"live": 6, "movie": 1, "series": 3}


def test_series_patterns():
    assert m3u.parse_series("Dark S01E10") == ("Dark", 1, 10)
    assert m3u.parse_series("The.Office.s3e02.1080p") == ("The.Office", 3, 2)
    assert m3u.parse_series("Ezel 1x05") == ("Ezel", 1, 5)
    assert m3u.parse_series("Avlu 12. Bölüm") == ("Avlu", 1, 12)
    assert m3u.parse_series("Sadece Film 2019") is None


def test_xtream_from_m3u_url():
    assert m3u.xtream_from_m3u_url("http://h.tv:8080/get.php?username=a&password=b&type=m3u_plus") == (
        "http://h.tv:8080", "a", "b")
    assert m3u.xtream_from_m3u_url("http://h.tv/list.m3u") is None


# ---------------------------------------------------------------- Xtream

class FakePanel:
    def __init__(self):
        self.calls = []

    def __call__(self, url: str) -> bytes:
        from urllib.parse import parse_qs, urlsplit
        self.calls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert q["username"] == "user" and q["password"] == "p@ss/1"
        action = q.get("action")
        b64 = lambda s: base64.b64encode(s.encode()).decode()
        data = {
            None: {"user_info": {"auth": 1, "status": "Active", "exp_date": "1893456000", "max_connections": "2",
                                 "active_cons": "0", "allowed_output_formats": ["m3u8", "ts"]},
                   "server_info": {"timezone": "Europe/Istanbul", "timestamp_now": 1762700000}},
            "get_live_categories": [{"category_id": "1", "category_name": "Ulusal"},
                                    {"category_id": "9", "category_name": "XXX", "is_adult": "1"}],
            "get_live_streams": [
                {"num": 1, "name": "TRT 1", "stream_id": 11, "stream_icon": "http://l/1.png", "epg_channel_id": "TRT1.tr",
                 "category_id": "1", "tv_archive": 1, "tv_archive_duration": "3"},
                {"num": 2, "name": "Kategorisiz", "stream_id": 12, "category_id": None},
                {"num": 3, "name": "Gece", "stream_id": 13, "category_id": "9"}],
            "get_vod_categories": {"0": {"category_id": "5", "category_name": "Aksiyon"}},
            "get_vod_streams": [{"num": 1, "name": "Film A (2023)", "stream_id": 101, "category_id": "5",
                                 "container_extension": "mkv", "rating": "7.5", "added": "1700000000"}],
            "get_series_categories": [{"category_id": "7", "category_name": "Yerli"}],
            "get_series": [{"num": 1, "name": "Dizi X", "series_id": 501, "cover": "http://c/x.jpg", "category_id": "7",
                            "plot": "Konu", "releaseDate": "2021-05-01", "last_modified": "1700000500"}],
            "get_series_info": {"seasons": [], "info": {"name": "Dizi X"},
                                "episodes": {"1": [{"id": "9001", "episode_num": 2, "title": "B", "container_extension": "mp4",
                                                    "info": {"duration_secs": 2700}, "season": 1},
                                                   {"id": "9000", "episode_num": 1, "title": "A", "container_extension": "mkv",
                                                    "info": []}]}},
            "get_vod_info": {"info": {"plot": "Film konusu", "duration": "01:45:30", "releasedate": "2023-01-01",
                                      "backdrop_path": ["http://b/1.jpg"]}, "movie_data": {"container_extension": "mkv"}},
            "get_short_epg": {"epg_listings": [{"title": b64("Haberler"), "description": b64("Açıklama"),
                                                "start_timestamp": "1762700000", "stop_timestamp": "1762703600"}]},
        }[action]
        return json.dumps(data).encode()


def test_xtream_client_and_import(tmp_path):
    panel = FakePanel()
    client = XtreamClient("panel.example.com:8080/", "user", "p@ss/1", getter=panel)
    assert client.server == "http://panel.example.com:8080"
    auth = client.authenticate()
    acc = XtreamClient.account_summary(auth)
    assert acc["max_connections"] == 2 and "ts" in acc["formats"] and acc["timezone"] == "Europe/Istanbul"
    assert client.live_url("11") == "http://panel.example.com:8080/live/user/p%40ss%2F1/11.ts"
    assert client.episode_url("9000", ".mkv").endswith("/series/user/p%40ss%2F1/9000.mkv")
    ts_url = client.timeshift_url("11", 1762700400, 60, "Europe/Istanbul")
    assert "/timeshift/user/p%40ss%2F1/60/" in ts_url and ts_url.endswith("/11.ts")
    info = client.series_info("501")
    assert [e["id"] for e in info["episodes"]] == ["9000", "9001"] and info["episodes"][1]["duration"] == 2700
    vod = client.vod_info("101")
    assert vod["duration"] == 6330 and vod["year"] == "2023" and vod["backdrop"] == "http://b/1.jpg"
    listings = client.short_epg("11")
    assert listings[0]["title"] == "Haberler" and listings[0]["desc"] == "Açıklama"

    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Panel", kind="xtream", url=client.server, username="user", password="p@ss/1")
    counts = catalog.import_xtream(store, store.get_source(sid), client)
    assert counts == {"live": 3, "movie": 1, "series": 1}
    cats = store.categories("live")
    assert [c["name"] for c in cats] == ["Ulusal", "Diğer"]  # yetişkin kategori gizli
    assert len(store.categories("live", hide_adult=False)) == 3
    live = store.items("live")
    assert [i.name for i in live] == ["TRT 1", "Kategorisiz"] and live[0].archive == 3
    movie = store.items("movie")[0]
    assert movie.ext == "mkv" and movie.year == "2023" and movie.rating == 7.5
    src = store.get_source(sid)
    assert catalog.play_url(store, movie, {}, src).endswith("/movie/user/p%40ss%2F1/101.mkv")
    st = settings_mod.merged_defaults()
    st["latency"]["live_format"] = "m3u8"
    assert catalog.play_url(store, live[0], st, src).endswith("/11.m3u8")


def test_xtream_errors():
    with pytest.raises(XtreamError):
        XtreamClient("x", "", "")
    bad = XtreamClient("x", "u", "p", getter=lambda url: json.dumps({"user_info": {"auth": 0}}).encode())
    with pytest.raises(XtreamError, match="hatalı"):
        bad.authenticate()
    html = XtreamClient("x", "u", "p", getter=lambda url: b"<html>nope</html>")
    with pytest.raises(XtreamError):
        html.authenticate()
    assert normalize_server("https://a.b/player_api.php?username=x") == "https://a.b"
    assert parse_duration("01:45:30") == 6330 and parse_duration("95 min") == 5700


# ---------------------------------------------------------------- EPG

def test_xmltv_time():
    assert epg.parse_xmltv_time("20261109180000 +0300") == epg.parse_xmltv_time("20261109150000 +0000")
    assert epg.parse_xmltv_time("20261109150000") == 1794236400
    assert epg.parse_xmltv_time("bad") is None


def test_m3u_import_epg_and_queries(tmp_path):
    store = Store(tmp_path / "t.db")
    sid = store.add_source(name="Liste", kind="m3u", url=str(DATA / "sample.m3u"))
    counts = catalog.refresh_source(store, store.get_source(sid), settings_mod.merged_defaults())
    assert counts == {"live": 6, "movie": 1, "series": 2}  # 6 canlı kayıt saklanır; yetişkin olan listede gizlenir
    src = store.get_source(sid)
    assert src["info"]["epg_auto"] == "http://epg.example.com/guide.xml.gz"
    live = store.items("live")
    assert "Gece Kanalı" not in [i.name for i in live]
    atv = next(i for i in live if i.name == "ATV")
    assert catalog.item_headers(atv)["referrer"] == "https://www.atv.com.tr/"
    trt = next(i for i in live if i.name == "TRT 1 HD")
    assert trt.archive == 1 and json.loads(trt.extra)["catchup"]["catchup"] == "shift"  # başlıktaki catchup
    series = store.items("series")
    osman = next(s for s in series if s.name == "Kuruluş Osman")
    eps = store.episodes(sid, osman.item_id)
    assert [(e["season"], e["episode"]) for e in eps] == [(2, 4), (2, 5)]
    # arama Türkçe karakterleri yok sayar
    assert [i.name for i in store.items("series", search="kurulus")] == ["Kuruluş Osman"]
    assert store.items("live", search="tr%") == []

    # EPG (yerel dosya) + ad eşleştirme: ATV'nin tvg-id'si boş, "ATV HD" görünen adıyla eşleşir
    store.update_source(sid, epg_url=str(DATA / "epg.xml"))
    n_prog, n_chan = catalog.refresh_epg(store, store.get_source(sid), settings_mod.merged_defaults())
    assert (n_prog, n_chan) == (3, 2)
    atv = store.item(sid, "live", atv.item_id)
    assert atv.epg_id == "atv.tr"
    now = epg.parse_xmltv_time("20261109183000 +0300")
    nn = store.epg_now_next([(sid, "TRT1.tr"), (sid, "atv.tr")], now=now)
    cur, nxt = nn[(sid, "TRT1.tr")]
    assert cur["title"] == "Akşam Haberleri" and nxt["title"] == "Film"
    progs = store.epg_for_channel(sid, "TRT1.tr", now - 7200, now + 7200)
    assert progs[0]["desc"] == "Günün özeti"

    # favoriler ve kaldığın yer
    assert store.toggle_favorite(trt.key) is True and store.is_favorite(trt.key)
    assert [i.name for i in store.favorites("live")] == ["TRT 1 HD"]
    film = store.items("movie")[0]
    store.save_progress(film.key, film.name, film.logo, 600, 7200)
    assert store.get_progress(film.key) == (600, 7200)
    assert store.continue_watching()[0]["item_id"] == film.item_id
    store.delete_source(sid)
    assert store.items("live") == [] and store.favorite_keys() == set()


def test_catchup_urls():
    start, stop, now = 1794236400, 1794240000, 1794246000
    assert epg.catchup_url("http://s/ch.m3u8", {"catchup": "shift"}, start, stop, now) == \
        f"http://s/ch.m3u8?utc={start}&lutc={now}"
    assert epg.catchup_url("http://s/ch/index.m3u8", {"catchup": "flussonic"}, start, stop, now) == \
        f"http://s/ch/index-{start}-3600.m3u8"
    url = epg.catchup_url("http://s/ch", {"catchup": "default", "catchup-source": "http://s/arc/{utc:YmdHMS}/{duration:60}"},
                          start, stop, now)
    assert url == "http://s/arc/20261109150000/60"
    assert epg.catchup_url("http://s/x", {}, start, stop, now) is None


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"latency": {"mode": "bogus", "chase": "evet"}, "audio": {"volume": 999},
                             "video": "bozuk"}), encoding="utf-8")
    s = settings_mod.load_settings(p)
    assert s["latency"]["mode"] == "low" and s["latency"]["chase"] is True
    assert s["audio"]["volume"] == 150 and s["video"]["rtx_vsr"] is True
    s["video"]["vsr_target"] = "1440"
    settings_mod.save_settings(s, p)
    assert settings_mod.load_settings(p)["video"]["vsr_target"] == "1440"
