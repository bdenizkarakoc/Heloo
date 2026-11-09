"""Windows duman testi: Direct3D 11 + d3d11vpp ölçekleme (RTX VSR'nin kullandığı yol) gerçekten çalışıyor mu?

NVIDIA kartı olmayan makinede (ör. GitHub Actions) WARP yazılım aygıtıyla filtre zinciri denenir; NVIDIA RTX'te
sürücü aynı çağrıda VSR uygular. Kullanım: python -m helootv.selftest [--warp]
"""
from __future__ import annotations

import sys
import time

from . import paths


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths.prepare_libmpv_search_path()
    import mpv

    logs: list[str] = []
    opts = {"vo": "gpu-next", "gpu_api": "d3d11", "hwdec": "d3d11va", "ao": "null", "osc": "no",
            "geometry": "640x360", "keep_open": "yes"}
    if "--warp" in argv:
        opts["d3d11_warp"] = "yes"
        opts["hwdec"] = "no"
    m = mpv.MPV(log_handler=lambda lvl, pre, txt: logs.append(f"[{lvl}] {pre}: {txt.strip()}"), loglevel="v", **opts)
    print("mpv:", m.mpv_version)
    m["vf"] = "@helootv:d3d11vpp=scale=1.5:scaling-mode=nvidia:deint=yes:interlaced-only=yes:mode=adaptive"
    m.play("av://lavfi:testsrc2=size=1280x720:rate=25:duration=4")
    out = None
    end = time.time() + 20
    while time.time() < end:
        vop = m._get_property("video-out-params")
        if isinstance(vop, dict) and vop.get("w"):
            out = (vop.get("w"), vop.get("h"))
            if out != (1280, 720):
                break
        time.sleep(0.2)
    m.terminate()
    for line in logs:
        if any(k in line for k in ("d3d11vpp", "NVIDIA", "Super Resolution", "video processor", "Disabling filter")):
            print(line)
    print("video-out-params:", out)
    if out == (1920, 1080):
        print("BAŞARILI: d3d11vpp 1280×720 → 1920×1080 ölçekledi (NVIDIA RTX'te bu adımda VSR uygulanır).")
        return 0
    print("UYARI: d3d11vpp ölçekleme doğrulanamadı (bu makinede D3D11 video işlemcisi yok olabilir).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
