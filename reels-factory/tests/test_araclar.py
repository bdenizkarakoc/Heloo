"""Araçlar: kayıt tutarlı olmalı; kurulum fabrikanın ortamına ve deposuna dokunmamalı (ağ yok)."""
import re
import subprocess
import sys

from reels import araclar

from conftest import ROOT


def test_registry_is_complete():
    ports = [t["port"] for t in araclar.TOOLS.values() if t["port"]]
    assert len(ports) == len(set(ports)) and 8765 not in ports          # fabrika uygulamasının kapısıyla çakışmasın
    for name, t in araclar.TOOLS.items():
        assert t["repo"].startswith("https://github.com/"), name
        assert re.fullmatch(r"[0-9a-f]{40}", t["surum"]), name           # sabit, denetlenmiş sürüm
        assert t["lisans"] and t["ne"] and t["kullan"] and t["kur"], name
        assert set(t["gerek"]) <= set(araclar.INSTALL_HINT), name
        assert bool(t["calistir"]) == bool(t["port"]), name


def test_installs_stay_out_of_factory_env_and_repo():
    for name, t in araclar.TOOLS.items():
        for _sub, argv in t["kur"]:
            assert argv[0] in ("uv", "npm", "bun"), (name, argv)         # kabuk komutu ve fabrika Python'u yok
            if argv[:3] == ["uv", "pip", "install"]:
                assert "{py}" in argv, name                              # aracın kendi .venv'ine
        if t["calistir"] and "--server.address=127.0.0.1" not in t["calistir"][1]:
            assert "0.0.0.0" not in " ".join(t["calistir"][1]), name
    assert "araclar/" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert str(araclar.venv_python("vimax")).startswith(str(ROOT / "araclar" / "vimax"))


def test_unknown_and_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(araclar, "DIR", tmp_path)
    monkeypatch.setattr(araclar, "STATE", tmp_path / "durum.json")
    assert not araclar.install("yok")["ok"]
    assert not araclar.start("yok")["ok"]
    assert "Önce kur" in araclar.start("toonflow")["message"]
    assert not araclar.start("do-mpc")["ok"]                              # kitaplık: arayüzü yok
    rows = araclar.status(probe=False)
    assert [r["name"] for r in rows] == list(araclar.TOOLS) and not any(r["installed"] for r in rows)
    assert araclar.log_tail("../../.env") == ""


def test_missing_program_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(araclar, "DIR", tmp_path)
    monkeypatch.setattr(araclar, "STATE", tmp_path / "durum.json")
    monkeypatch.setattr(araclar, "_exe", lambda cmd: None if cmd == "bun" else "/bin/" + cmd)
    r = araclar.install("toonflow")
    assert not r["ok"] and "bun" in r["message"] and not (tmp_path / "toonflow").exists()


def test_cli_lists_tools():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "factory.py"), "araclar"], capture_output=True,
                       text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    for name in araclar.TOOLS:
        assert name in r.stdout


def test_standalone_app_serves_only_local_requests():
    """Ayrı uygulama (app/araclar_app.py): sayfa + durum verir; başka siteden gelen isteği reddeder."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    sys.path.insert(0, str(ROOT / "app"))
    import araclar_app
    srv = ThreadingHTTPServer(("127.0.0.1", 0), araclar_app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert b"<title>Ara" in urllib.request.urlopen(base + "/", timeout=5).read()
        rows = json.loads(urllib.request.urlopen(base + "/api/araclar", timeout=20).read())
        assert [r["name"] for r in rows] == list(araclar.TOOLS)

        def post(headers):
            req = urllib.request.Request(base + "/api/araclar/kur", data=b'{"name": "yok"}', headers=headers)
            try:
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as exc:
                return exc.code
        assert post({"Content-Type": "application/json"}) == 200                      # bilinmeyen araç: yalnızca mesaj döner
        assert post({"Content-Type": "application/json", "Origin": "https://kotu.example"}) == 400
        assert post({"Content-Type": "application/json", "Host": "kotu.example"}) == 400
        assert post({"Content-Type": "text/plain"}) == 400
    finally:
        srv.shutdown()
