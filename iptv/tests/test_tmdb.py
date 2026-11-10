"""TMDB film/dizi bilgileri (API taklit edilir)."""
from __future__ import annotations

import pytest

from helootv import tmdb


def test_split_title():
    assert tmdb.split_title("Esaretin Bedeli (1994) [TR] 1080p") == ("Esaretin Bedeli", "1994")
    assert tmdb.split_title("TR: Kuruluş Osman S02E05") == ("Kuruluş Osman", "")
    assert tmdb.split_title("The.Matrix.1999.BluRay.mkv")[0] == "The Matrix"


def test_lookup_movie_cache_and_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    calls = []

    def fake_call(key, path, params):
        calls.append((path, dict(params)))
        if path == "/search/movie":
            if params.get("year") == "1995":          # yanlış yıl → yılsız yeniden aranır
                return {"results": []}
            return {"results": [
                {"id": 2, "title": "Başka Film", "popularity": 900, "release_date": "2001-01-01"},
                {"id": 278, "title": "Esaretin Bedeli", "original_title": "The Shawshank Redemption",
                 "popularity": 80, "release_date": "1994-09-23"}]}
        if path == "/movie/278" and params.get("language") == "tr-TR":
            return {"id": 278, "title": "Esaretin Bedeli", "overview": "", "poster_path": "/p.jpg",
                    "vote_average": 8.71, "release_date": "1994-09-23", "runtime": 142,
                    "genres": [{"name": "Dram"}, {"name": "Suç"}],
                    "credits": {"crew": [{"job": "Director", "name": "Frank Darabont"}],
                                "cast": [{"name": "Tim Robbins"}, {"name": "Morgan Freeman"}]}}
        if path == "/movie/278":
            return {"overview": "Two imprisoned men bond..."}
        raise AssertionError(path)

    monkeypatch.setattr(tmdb, "_call", fake_call)
    info = tmdb.lookup("KEY", "movie", "Esaretin Bedeli (1995)")
    assert info["tmdb_id"] == 278 and info["year"] == "1994" and info["rating"] == 8.7
    assert info["plot"] == "Two imprisoned men bond..."               # Türkçe yok → İngilizce
    assert info["poster"] == "https://image.tmdb.org/t/p/w500/p.jpg" and info["duration"] == 142 * 60
    assert info["director"] == "Frank Darabont" and info["cast"].startswith("Tim Robbins")
    assert info["genre"] == "Dram, Suç"
    n = len(calls)
    assert tmdb.lookup("KEY", "movie", "Esaretin Bedeli (1995)") == info and len(calls) == n   # önbellek
    # bulunamayan da önbelleğe girer
    monkeypatch.setattr(tmdb, "_call", lambda k, p, q: {"results": []})
    assert tmdb.lookup("KEY", "tv", "Olmayan Dizi") is None
    with pytest.raises(tmdb.TmdbError):
        tmdb.lookup("", "movie", "x")
    merged = tmdb.merge({"plot": "Sağlayıcının açıklaması", "cast": ""}, info)
    assert merged["plot"] == "Sağlayıcının açıklaması" and merged["cast"].startswith("Tim") and merged["tmdb"]


def test_auth_header_vs_query(monkeypatch):
    seen = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"results": []}'

    def fake_open(req, timeout=0, context=None):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return R()

    monkeypatch.setattr(tmdb.urllib.request, "urlopen", fake_open)
    tmdb._call("abc123", "/search/movie", {"query": "x"})
    assert "api_key=abc123" in seen["url"] and seen["auth"] is None
    jwt = "eyJhbGciOiJIUzI1NiJ9." + "a" * 80 + ".sig"
    tmdb._call(jwt, "/search/movie", {"query": "x"})
    assert "api_key" not in seen["url"] and seen["auth"] == f"Bearer {jwt}"


def test_movie_details_use_tmdb_for_m3u(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("HELOOTV_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import time

    from PySide6.QtWidgets import QApplication

    from helootv import settings as settings_mod
    from helootv.store import Item, Store
    from helootv.ui.context import AppContext
    from helootv.ui.images import ImageLoader
    from helootv.ui.pages import MoviesPage
    app = QApplication.instance() or QApplication([])
    s = settings_mod.merged_defaults()
    s["metadata"]["tmdb_key"] = "KEY"
    monkeypatch.setattr(tmdb, "lookup", lambda key, kind, title, year="": {
        "plot": "Bir banker yanlışlıkla hapse girer.", "cast": "Tim Robbins", "year": "1994", "rating": 8.7,
        "genre": "Dram", "director": "Frank Darabont", "duration": 8520, "poster": ""})
    page = MoviesPage(AppContext(Store(tmp_path / "s.db"), s, ImageLoader()))
    item = Item(source_id=99, kind="movie", item_id="1", num=0, name="Esaretin Bedeli", cat_id="", logo="",
                url="http://x/1.mkv", epg_id="", ext="", rating=0.0, year="", added=0, archive=0, adult=0, extra="")
    page.details.show_item(item)
    end = time.time() + 5
    while time.time() < end and "banker" not in page.details.plot.text():
        app.processEvents()
        time.sleep(0.02)
    d = page.details
    assert "banker" in d.plot.text() and "Frank Darabont" in d.people.text() and "TMDB" in d.people.text()
    assert "1994" in d.meta.text() and "★ 8.7" in d.meta.text()
