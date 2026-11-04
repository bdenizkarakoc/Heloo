import os

from reels import config


def test_env_mixed_encodings(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_bytes("# Türkçe açıklama\nA_KEY=abc\n".encode() + "# Gİzli\r\n".encode("cp1254") + b"B_KEY=AQ.test123\r\n")
    monkeypatch.delenv("A_KEY", raising=False); monkeypatch.delenv("B_KEY", raising=False)
    config.load_dotenv(p)
    assert os.environ["A_KEY"] == "abc" and os.environ["B_KEY"] == "AQ.test123"


def test_env_utf16(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_bytes("C_KEY=x16\r\n".encode("utf-16"))
    monkeypatch.delenv("C_KEY", raising=False)
    config.load_dotenv(p)
    assert os.environ["C_KEY"] == "x16"


def test_set_secret_rewrites_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env").write_bytes("# Gİzli\r\nD_KEY=old\r\nD_KEY=dup\r\n".encode("cp1254"))
    config.set_secret("D_KEY", "new")
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert text.count("D_KEY=") == 1 and "D_KEY=new" in text and "Gİzli" in text
