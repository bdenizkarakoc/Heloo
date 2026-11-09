"""RTX VSR testi: Direct3D 11 + d3d11vpp ölçekleme gerçekten çalışıyor mu, NVIDIA sürücüsü VSR'yi açtı mı?

1280×720 deneme görüntüsü küçük bir mpv penceresinde ×3 (→ 3840×2160) ölçeklenir; mpv'nin ayrıntılı günlüğünden
sürücünün yanıtı okunur ("NVIDIA RTX Super Resolution enabled." / "Failed to enable …").

    python -m helootv.selftest           # bu bilgisayarın ekran kartıyla
    python -m helootv.selftest --hdr     # RTX Video HDR'yi de dene (HDR ekran gerekir)
Uygulamada: Ayarlar → Sistem → "RTX VSR'yi test et".
"""
from __future__ import annotations

import sys
import time

from . import paths


def run(hdr: bool = False, warp: bool = False, timeout: float = 20.0) -> dict:
    paths.prepare_libmpv_search_path()
    import mpv

    logs: list[str] = []
    opts = {"vo": "gpu-next", "gpu_api": "d3d11", "hwdec": "d3d11va", "ao": "null", "osc": "no",
            "geometry": "480x270", "keep_open": "yes", "title": "Heloo TV — RTX VSR testi", "ontop": "yes"}
    if warp:
        opts["d3d11_warp"] = "yes"
        opts["hwdec"] = "no"
    m = mpv.MPV(log_handler=lambda lvl, pre, txt: logs.append(f"[{lvl}] {pre}: {txt.strip()}"), loglevel="v", **opts)
    vf = "@helootv:d3d11vpp=scale=3:scaling-mode=nvidia" + (":nvidia-true-hdr=yes" if hdr else "")
    result = {"version": str(m.mpv_version), "vf": vf, "out": None, "scaled": False, "vsr": "unknown",
              "hdr": "unknown" if hdr else "skipped", "log": []}
    try:
        m["vf"] = vf
        m.play("av://lavfi:testsrc2=size=1280x720:rate=25:duration=6")
        end = time.time() + timeout
        while time.time() < end:
            vop = m._get_property("video-out-params")
            if isinstance(vop, dict) and vop.get("w"):
                result["out"] = (vop.get("w"), vop.get("h"))
                if result["out"] != (1280, 720):
                    time.sleep(1.0)  # sürücünün VSR/HDR yanıtı günlüğe düşsün
                    break
            if any("Creating filter 'd3d11vpp' failed" in line for line in logs):
                break
            time.sleep(0.2)
    finally:
        m.terminate()
    for line in logs:
        if "NVIDIA RTX Super Resolution enabled" in line:
            result["vsr"] = "enabled"
        elif "Failed to enable NVIDIA RTX Super Resolution" in line:
            result["vsr"] = "failed"
        elif "NVIDIA RTX Video HDR enabled" in line:
            result["hdr"] = "enabled"
        elif "NVIDIA RTX Video HDR not supported" in line or "Failed to enable NVIDIA RTX Video HDR" in line:
            result["hdr"] = "failed"
        if any(k in line for k in ("d3d11vpp", "NVIDIA", "Super Resolution", "Disabling filter", "user_filter")):
            result["log"].append(line)
    result["scaled"] = result["out"] == (3840, 2160)
    return result


def summary(r: dict) -> str:
    lines = [f"mpv: {r['version']}"]
    if r["scaled"]:
        lines.append("✔ Direct3D 11 video işlemcisi çalışıyor: 1280×720 → 3840×2160 (d3d11vpp).")
    else:
        lines.append(f"✖ d3d11vpp ölçeklemesi çalışmadı (çıkış: {r['out']}). Ekran kartı sürücüsünü güncelleyin; "
                     "Ayarlar → Görüntü → Donanım çözme 'Otomatik' olmalı.")
    lines.append({
        "enabled": "✔ NVIDIA sürücüsü RTX Video Super Resolution'ı ETKİNLEŞTİRDİ.",
        "failed": "✖ NVIDIA sürücüsü RTX VSR'yi reddetti: NVIDIA App → Sistem → Video → RTX Video Enhancement → "
                  "Super Resolution'ı açın (RTX 20/30/40/50 ve güncel sürücü gerekir).",
        "unknown": "? Sürücü RTX VSR yanıtı vermedi (NVIDIA RTX kart değil ya da sürücü eski olabilir).",
    }[r["vsr"]])
    if r["hdr"] != "skipped":
        lines.append({"enabled": "✔ RTX Video HDR etkin.",
                      "failed": "✖ RTX Video HDR kullanılamadı (Windows HDR ve NVIDIA App'te HDR açık olmalı).",
                      "unknown": "? RTX Video HDR yanıtı yok."}[r["hdr"]])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths.ensure_utf8_stdio()
    r = run(hdr="--hdr" in argv, warp="--warp" in argv)
    for line in r["log"]:
        print(line)
    print(summary(r))
    return 0 if (r["scaled"] and r["vsr"] == "enabled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
