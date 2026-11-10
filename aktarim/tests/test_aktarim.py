import io
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aktarim  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return aktarim.Store(tmp_path)


def test_device_detection():
    assert aktarim.device_from_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)") == "iPhone"
    assert aktarim.device_from_ua("Mozilla/5.0 (Linux; Android 14; SM-S921B)") == "Samsung"
    assert aktarim.device_from_ua("Mozilla/5.0 (Linux; Android 14; Pixel 8)") == "Android"
    assert aktarim.device_from_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "Bilgisayar"


def test_safe_name():
    assert aktarim.safe_name("../../etc/passwd") == "passwd"
    assert aktarim.safe_name("C:\\a\\b:c?.txt") == "b_c_.txt"
    assert aktarim.safe_name("") == "dosya"


def test_add_delete_restore_purge(store):
    data = b"merhaba" * 100
    it = store.add_file_stream("foto.jpg", io.BytesIO(data), len(data), "iPhone")
    assert store.path_of(it).read_bytes() == data
    assert it["mime"] == "image/jpeg"
    store.soft_delete(it["id"], 7)
    lst = store.listing()
    assert not lst["items"] and lst["bin"][0]["retention_days"] == 7
    store.restore(it["id"])
    assert store.listing()["items"][0]["id"] == it["id"]
    store.soft_delete(it["id"], 14)
    assert store.purge_expired(now=time.time() + 13 * aktarim.DAY) == 0
    assert store.purge_expired(now=time.time() + 15 * aktarim.DAY) == 1
    assert not store.path_of(it).exists() and not store.items


def test_bad_retention_and_partial_upload(store):
    t = store.add_text("not", "Samsung")
    with pytest.raises(ValueError):
        store.soft_delete(t["id"], 3)
    with pytest.raises(IOError):
        store.add_file_stream("x.bin", io.BytesIO(b"abc"), 10, "iPhone")
    assert not list(store.files.glob("*.part"))


def test_persistence(tmp_path):
    s = aktarim.Store(tmp_path)
    t = s.add_text("kalıcı", "iPhone")
    s2 = aktarim.Store(tmp_path)
    assert s2.get(t["id"])["text"] == "kalıcı"
    assert s2.cfg["token"] == s.cfg["token"]


def test_http_roundtrip(store):
    srv = aktarim.make_server(store, host="127.0.0.1", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    key = {"X-Aktarim-Key": store.cfg["token"]}
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/items")
        assert e.value.code == 401
        body = b"\x00\x01" * 5000
        req = urllib.request.Request(base + "/api/upload", data=body, method="POST", headers={
            **key, "X-Filename": "belge%20%C3%A7.pdf", "Content-Type": "application/pdf",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)"})
        it = json.loads(urllib.request.urlopen(req).read())
        assert it["name"] == "belge ç.pdf" and it["source"] == "iPhone"
        req = urllib.request.Request(base + f"/api/file/{it['id']}", headers={**key, "Range": "bytes=10-19"})
        r = urllib.request.urlopen(req)
        assert r.status == 206 and r.read() == body[10:20]
        req = urllib.request.Request(base + "/api/delete", data=json.dumps({"id": it["id"], "days": 30}).encode(),
                                     method="POST", headers={**key, "Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["retention_days"] == 30
        r = urllib.request.urlopen(base + f"/?k={store.cfg['token']}")
        assert "aktarim=" in r.headers["Set-Cookie"]
    finally:
        srv.shutdown()
        srv.server_close()


PS1 = Path(__file__).resolve().parents[1] / "Aktarim.ps1"


def test_powershell_script_encoding_and_routes():
    raw = PS1.read_bytes()
    # Windows PowerShell 5.1 BOM'suz UTF-8'i ANSI okur; Türkçe metin bozulmasın
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    app = (PS1.parent / "web" / "app.js").read_text("utf-8")
    import re
    for route in set(re.findall(r'"(/api/[a-z-]+)"', app)):
        assert f"'{route}'" in text, route
    assert "PositionalBinding = $false" in text
    # kaba sözdizimi denetimi: süslü parantezler dengeli
    code = re.sub(r"'[^'\r\n]*'", "''", text)
    assert code.count("{") == code.count("}")
