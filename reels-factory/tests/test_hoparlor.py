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


def test_preamp_prevents_clipping():
    an = h.analyse({**h.default_settings("bas"), "tiz": 4}, "z607")
    assert an["preamp"] <= -max(an["curve"][3:]) + 0.01
    assert an["preamp"] < 0


def test_z607_protects_deep_bass_and_laptop_limits():
    flt = h.filters({**h.default_settings("bas")}, "z607")
    assert ("HP", 35.0, 0.0, 0.71) in flt
    assert not any(t == "PK" and f == 31 for t, f, g, q in flt)          # 31 Hz yükseltilmez
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
    assert "Filter: ON PK Fc 2000 Hz Gain 2.0 dB Q 1.41" in cfg


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
