"""Hoparlör ses ayarı: Equalizer APO dosyası, cızırtı koruması, hoparlör koruması."""
import pytest

from reels import hoparlor as h


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "STATE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(h, "apo_dir", lambda: None)


def test_presets_have_ten_bands():
    for k, p in h.PRESETS.items():
        assert len(p["b"]) == len(h.BANDS), k
        assert all(-h.LIMIT <= g <= h.LIMIT for g in p["b"])


def test_peaking_response_matches_gain():
    db = h.response([("PK", 1000.0, 6.0, 1.41)], [1000.0, 20.0])
    assert db[0] == pytest.approx(6.0, abs=0.05) and abs(db[1]) < 0.1


def test_preamp_by_power_mode():
    s = {**h.default_settings("bas"), "tiz": 4}
    safe = h.analyse({**s, "guc": "guvenli"}, "z607")
    assert safe["preamp"] <= -max(safe["curve"][3:]) + 0.01 < 0
    mid = h.analyse(s, "z607")                      # varsayılan dengeli: yarısı kadar kısar
    assert mid["settings"]["guc"] == "dengeli" and mid["preamp"] == pytest.approx(-mid["peak"] / 2, abs=0.11)
    loud = h.analyse({**s, "guc": "yuksek", "yukseklik": 4}, "z607")
    assert loud["preamp"] == 4.0                     # yüksek: hiç kısmaz, seviye +10'a kadar açılır
    assert h.clean_settings({"yukseklik": 50})["yukseklik"] == h.LEVEL_MAX


def test_graphic_eq_is_exact_at_bands_and_half_db_steps():
    s = {**h.default_settings(), "bands": [0, 0, 0, 0, 0, 2.5, 0, 0, 0, 0]}
    an = h.analyse(s, "kulaklik")
    assert h.graphic_response(an["graphic"], [1000.0, 2000.0, 707.0]) == pytest.approx([2.5, 0.0, 1.25], abs=0.01)


def test_z607_protects_deep_bass_and_laptop_limits():
    flt = h.filters({**h.default_settings("bas")}, "z607")
    assert ("HP", 35.0, 0.0, 0.71) in flt
    assert h.graphic(h.default_settings("bas"), "z607")[0] == (31.0, 0.0)   # 31 Hz yükseltilmez
    lap = h.filters({**h.default_settings("duz"), "bas": 10}, "laptop")
    assert max(g for t, f, g, q in lap if t == "LSC") <= 3


def test_apo_config_per_device_and_channels():
    st = h.default_state()
    st["speakers"][0]["settings"] = h.default_settings("film")
    st["speakers"][0]["device"] = "{12345678-1234-1234-1234-123456789abc}"
    h.add_speaker(st, "Masa", "masaustu", "SWD\\MMDEVAPI\\{0.0.0.00000000}.{abcdefab-1234-1234-1234-123456789abc}")
    st["active"] = "z607"
    cfg = h.apo_config(st)
    assert "Device: {12345678-1234-1234-1234-123456789abc}" in cfg
    assert "Device: {abcdefab-1234-1234-1234-123456789abc}" in cfg
    assert "Channel: C\nPreamp: 3.0 dB" in cfg and "Channel: all" in cfg
    assert cfg.rstrip().endswith("Device: all")
    assert "GraphicEQ: 31 0.0; 62 3.0; 125 1.0; 250 0.0; 500 0.0; 1000 1.0; 2000 2.0; 4000 1.0; 8000 2.0; 16000 2.0" in cfg


def test_update_keeps_simple_sliders_and_cleans_input():
    h.update({"speaker": "z607", "settings": {"bas": 99, "tiz": "x", "bands": [1] * 10, "preset": "ozel"}, "apply": False})
    r = h.update({"speaker": "z607", "preset": "turku"})
    s = r["speaker"]["settings"]
    assert s["bas"] == h.LIMIT and s["tiz"] == 0 and s["bands"] == h.PRESETS["turku"]["b"]
    assert r["apply"]["needs_apo"] and "Device: all" in r["apply"]["config"]


def test_off_writes_flat_block():
    st = h.default_state()
    st["speakers"][0]["settings"]["acik"] = False
    assert "Filter:" not in h.apo_config(st)
