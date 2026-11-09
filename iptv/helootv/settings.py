"""Ayarlar: en iyi varsayılanlar + JSON dosyası (bozuk/eksik değerler varsayılana döner)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

# Varsayılanlar "en iyi" deneyim içindir: RTX VSR ile 4K, düşük gecikme, canlıya yetişme, otomatik yeniden bağlanma.
DEFAULTS: dict[str, Any] = {
    "video": {
        "rtx_vsr": True,          # NVIDIA RTX Video Super Resolution (mpv d3d11vpp scaling-mode=nvidia)
        "vsr_target": "2160",     # 2160 (4K) | 1440 | screen (ekran çözünürlüğü)
        "rtx_hdr": False,         # NVIDIA RTX Video HDR (SDR→HDR; Windows HDR açık olmalı)
        "deinterlace": "auto",    # auto (yalnız geçmeli kareler) | yes | no — Windows'ta GPU (d3d11vpp)
        "deband": True,           # IPTV sıkıştırmasındaki renk bantlarını yumuşatır
        "hq_scaling": True,       # VSR'nin yetmediği yerde ewa_lanczossharp
        "smooth_vod": True,       # film/dizide display-resample + interpolasyon (takılmasız akış)
        "hwdec": "auto",          # auto: Windows'ta d3d11va (VSR için şart), diğerlerinde auto
    },
    "latency": {
        "mode": "low",            # ultra | low | balanced | stable
        "chase": True,            # canlıya yetişme: tampon büyürse hafif hızlanıp gecikmeyi geri alır
        "live_format": "ts",      # Xtream canlı yayın biçimi: ts (en düşük gecikme) | m3u8
    },
    "audio": {
        "prefer": "tr",           # tr: Türkçe ses (dublaj) öncelikli | original: özgün dil
        "normalize": False,       # ses seviyesi dengeleme (yalnız film/dizi; canlıda gecikme eklemez)
        "spdif": False,           # AC3/E-AC3/DTS'yi amfiye aktar (passthrough)
        "volume": 100,
    },
    "subtitles": {
        "prefer": "tr",           # tr | off
        "size": 44,
    },
    "network": {
        "user_agent": "VLC/3.0.21 LibVLC/3.0.21",
        "timeout": 15,
        "reconnect": True,
        "tls_verify": True,
    },
    "ui": {
        "resume_last_channel": True,
        "auto_next_episode": True,
        "hide_adult": True,
        "translate_groups": True,
        "epg_shift_hours": 0.0,
        "auto_refresh_hours": 12,
        "last_channel": None,     # [source_id, item_id]
        "last_tab": "live",
    },
}

CHOICES: dict[tuple[str, str], tuple] = {
    ("video", "vsr_target"): ("2160", "1440", "screen"),
    ("video", "deinterlace"): ("auto", "yes", "no"),
    ("video", "hwdec"): ("auto", "d3d11va", "nvdec", "auto-copy", "no"),
    ("latency", "mode"): ("ultra", "low", "balanced", "stable"),
    ("latency", "live_format"): ("ts", "m3u8"),
    ("audio", "prefer"): ("tr", "original"),
    ("subtitles", "prefer"): ("tr", "off"),
}

RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("audio", "volume"): (0, 150),
    ("subtitles", "size"): (20, 90),
    ("network", "timeout"): (3, 120),
    ("ui", "epg_shift_hours"): (-14, 14),
    ("ui", "auto_refresh_hours"): (0, 168),
}


def _sanitize(merged: dict) -> dict:
    for section, defaults in DEFAULTS.items():
        sec = merged.setdefault(section, {})
        if not isinstance(sec, dict):
            merged[section] = sec = copy.deepcopy(defaults)
        for key, default in defaults.items():
            val = sec.get(key, default)
            if (section, key) in CHOICES and val not in CHOICES[(section, key)]:
                val = default
            elif isinstance(default, bool):
                val = val if isinstance(val, bool) else default
            elif isinstance(default, (int, float)) and not isinstance(default, bool):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    val = default
                lo_hi = RANGES.get((section, key))
                if lo_hi:
                    val = min(max(val, lo_hi[0]), lo_hi[1])
                val = type(default)(val)
            elif isinstance(default, str) and not isinstance(val, str):
                val = default
            sec[key] = val
    return merged


def merged_defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def load_settings(path: Path) -> dict:
    data: dict = {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    merged = merged_defaults()
    for section, values in data.items():
        if section in merged and isinstance(values, dict):
            merged[section].update(values)
    return _sanitize(merged)


def save_settings(settings: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_sanitize(copy.deepcopy(settings)), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
