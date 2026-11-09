"""mpv seçenekleri — NVIDIA RTX Video Super Resolution (4K), RTX Video HDR, gecikme kipleri ve kalite ayarları.

Kaynaklar (GitHub, mpv-player/mpv):
  * video/filter/vf_d3d11vpp.c — `scale`, `scaling-mode=nvidia` (RTX VSR, mpv ≥ 0.39), `nvidia-true-hdr`
    (RTX Video HDR, ≥ 0.40; 0.42'den beri yalnız SDR kaynakta), `deint`, `interlaced-only`, `mode`.
    Filtre kodlanmış kareyi `scale` katsayısıyla büyütür; NVIDIA sürücüsü bu sırada VSR uygular.
  * etc/builtin.conf `[low-latency]` profili — ultra düşük gecikme kipinin temeli.
  * FFmpeg hls demuxer `live_start_index` — HLS'de canlı kenara kaç parça uzaktan başlanacağı.
"""
from __future__ import annotations

import sys
from urllib.parse import urlsplit

from .. import shaders

TARGET_BOXES = {"2160": (3840, 2160), "1440": (2560, 1440)}
MAX_VSR_SCALE = 6.0      # 360p → 2160p
MIN_VSR_SCALE = 1.1      # bundan küçük büyütmede VSR anlamsız

# Canlı yayın gecikme kipleri. chase = (hedef tampon sn, üst sınır sn): tampon üst sınırı aşarsa oynatma hafifçe
# hızlanır (ses perdesi korunur), çok büyürse tampon içinde ileri atlanır → gecikme kendiliğinden geri alınır.
LATENCY_MODES: dict[str, dict] = {
    "ultra": {
        "label": "Ultra düşük gecikme",
        "desc": "mpv low-latency profili: tampon yok, en hızlı kanal açılışı. İnternet dalgalanırsa takılabilir.",
        "audio-buffer": "0", "cache-pause": "no", "cache-pause-wait": "0.2", "cache-pause-initial": "no",
        "probe-info": "nostreams", "analyzeduration": "0.1", "nobuffer": True, "latency-hacks": "yes",
        "hls-start": -1, "stream-buffer-size": "4KiB", "curl-buffer-size": "256KiB", "chase": (0.35, 1.0),
    },
    "low": {
        "label": "Düşük gecikme (önerilen)",
        "desc": "Hızlı kanal geçişi ve canlıya yakın yayın; kısa kopmalarda 0,4 sn tamponla toparlanır.",
        "audio-buffer": "0.05", "cache-pause": "yes", "cache-pause-wait": "0.4", "cache-pause-initial": "no",
        "probe-info": "nostreams", "analyzeduration": "0.5", "nobuffer": True, "latency-hacks": "yes",
        "hls-start": -2, "stream-buffer-size": "64KiB", "curl-buffer-size": "1MiB", "chase": (0.8, 2.0),
    },
    "balanced": {
        "label": "Dengeli",
        "desc": "Biraz daha tampon; çoğu bağlantıda takılmasız.",
        "audio-buffer": "0.2", "cache-pause": "yes", "cache-pause-wait": "1", "cache-pause-initial": "no",
        "probe-info": "auto", "analyzeduration": "1", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -3, "stream-buffer-size": "128KiB", "curl-buffer-size": "4MiB", "chase": (2.0, 5.0),
    },
    "stable": {
        "label": "Kararlı (zayıf internet)",
        "desc": "Açılışta 3 sn tampon doldurur; zayıf ya da kablosuz bağlantıda en az takılma.",
        "audio-buffer": "0.25", "cache-pause": "yes", "cache-pause-wait": "3", "cache-pause-initial": "yes",
        "probe-info": "auto", "analyzeduration": "3", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -3, "stream-buffer-size": "128KiB", "curl-buffer-size": "4MiB", "chase": (6.0, 18.0),
    },
}

TR_AUDIO = "tur,tr,tr-TR,turkish,türkçe,eng,en"


class Choices(tuple):
    """Sırayla denenecek değerler (eski mpv sürümü yeni değeri tanımazsa bir sonrakine düşülür)."""
TR_SUBS = "tur,tr,tr-TR,turkish,türkçe"


def is_windows(platform: str = sys.platform) -> bool:
    return platform.startswith("win")


def is_hls(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    low = (parts.path + "?" + parts.query).lower()
    return ".m3u8" in low or "/hls/" in low or "format=m3u8" in low or low.endswith("/m3u8")


def resolve_hwdec(settings: dict, platform: str = sys.platform) -> str:
    v = settings["video"]["hwdec"]
    if v == "auto":
        # Windows: d3d11va (sıfır kopya D3D11 kareleri) → d3d11vpp/RTX VSR doğrudan GPU'da çalışır.
        # Desteklenmeyen kodlayıcıda yazılım çözmeye düşer; d3d11vpp yazılım karelerini kendisi GPU'ya yükler.
        return "d3d11va" if is_windows(platform) else "auto"
    return v


def create_options(settings: dict, *, wid: int | None = None, input_conf: str | None = None,
                   headless: bool = False, platform: str = sys.platform) -> dict:
    """mpv başlatılırken verilmesi gereken (sonradan değişmeyen) seçenekler. Hepsi mpv ≥ 0.35'te vardır."""
    o = {
        "idle": "yes",
        "keep-open": "no",
        "ytdl": "no",                    # IPTV adreslerinde yt-dlp kancası açılışı yavaşlatır
        "osc": "no" if headless else "yes",
        "input-default-bindings": "yes",
        "input-vo-keyboard": "yes",
        "hwdec": resolve_hwdec(settings, platform),
        "vo": "null" if headless else "gpu-next",
        "audio-display": "no",
        "osd-playing-msg": "",
        "volume": str(settings["audio"]["volume"]),
    }
    if is_windows(platform) and not headless:
        o["gpu-api"] = "d3d11"           # d3d11vpp ve RTX VSR için Direct3D 11 bağlamı şart
    if input_conf:
        o["input-conf"] = str(input_conf)
    # Pencereye gömme en sonda: önceki bir seçenek reddedilirse yarım kalan mpv çekirdeği pencereye bağlanmaz
    o["force-window"] = "yes" if (wid is not None and not headless) else "no"
    if wid is not None:
        o["wid"] = str(int(wid))
    return o


def quality_options(settings: dict, platform: str = sys.platform) -> dict:
    """Başlatmadan sonra (ayar değişince yeniden) uygulanan seçenekler. Değer bir demetse ilk desteklenen ad kullanılır."""
    v, a, s, n = settings["video"], settings["audio"], settings["subtitles"], settings["network"]
    win = is_windows(platform)
    o: dict = {
        "hwdec-codecs": "all",           # varsayılan liste MPEG-2'yi içermez; IPTV'deki SD kanallar için gerekli
        "deband": "yes" if v["deband"] else "no",
        "dither-depth": "auto",
        "target-colorspace-hint": "yes" if v["rtx_hdr"] else "auto",
        "cursor-autohide": "1000",
        "cursor-autohide-fs-only": "no",
        "osd-duration": "1800",
        "osd-font-size": "34",
        "osd-on-seek": "msg-bar",
        "volume-max": "150",
        "alang": TR_AUDIO if a["prefer"] == "tr" else "",
        "audio-spdif": "ac3,eac3,dts,dts-hd,truehd" if a["spdif"] else "",
        "audio-pitch-correction": "yes",  # canlıya yetişirken hızlanmada ses perdesi değişmez
        "sid": "auto" if s["prefer"] == "tr" else "no",
        "slang": TR_SUBS if s["prefer"] == "tr" else "",
        # Türkçe dublajda altyazıyı (zorunlu olanlar hariç) açma; mpv < 0.38 "forced" bilmez → "no"
        "subs-with-matching-audio": Choices(("forced", "no")),
        "sub-font-size": str(s["size"]),
        ("sub-outline-size", "sub-border-size"): "2.4",
        "sub-shadow-offset": "1",
        "network-timeout": str(n["timeout"]),
        "tls-verify": "yes" if n["tls_verify"] else "no",
        "user-agent": n["user_agent"],
        "script-opts": ("osc-layout=bottombar,osc-seekbarstyle=bar,osc-hidetimeout=1600,osc-deadzonesize=0.5,"
                        "osc-idlescreen=no,osc-windowcontrols=no"),
    }
    # RTX VSR'nin büyütmediği her durumda (fotoğraf, sürücüde VSR kapalı, NVIDIA olmayan kart) yapay zekâ ile
    # 2 kat büyütme; shader yalnız mpv'nin kendisi ≥1,3 kat büyüttüğünde devreye girer (VSR 4K verince çalışmaz)
    shader = shaders.resolve(v.get("ai_upscaler", "fsrcnnx"))
    o["glsl-shaders"] = [str(shader)] if shader else []
    # video alanına bırakılan dosyaları mpv kendisi açmasın; dropped-files ile uygulama açar (aynı 4K zinciri)
    o[("input-builtin-drag-and-drop", "drag-and-drop")] = "no"
    if v["deband"]:
        o.update({"deband-iterations": "2", "deband-threshold": "35", "deband-range": "16", "deband-grain": "5"})
    if v["hq_scaling"]:
        # high-quality profilinin karşılığı (VSR'nin olmadığı ya da yetmediği büyütme için)
        o.update({"scale": "ewa_lanczossharp", "scale-antiring": "0.6", "hdr-peak-percentile": "99.995",
                  "hdr-contrast-recovery": "0.30"})
    else:
        o.update({"scale": "lanczos", "scale-antiring": "0"})
    if win:
        o["osd-font"] = "Segoe UI Semibold"
        o["sub-font"] = "Segoe UI Semibold"
        o["deinterlace"] = "no"          # Windows'ta deinterlace d3d11vpp (GPU) filtresinde yapılır
    else:
        o["deinterlace"] = Choices(("auto", "no")) if v["deinterlace"] == "auto" else v["deinterlace"]
    return o


def play_options(settings: dict, kind: str, url: str, headers: dict | None = None) -> dict:
    """Her loadfile'dan hemen önce ayarlanır. kind: live | catchup | movie | episode | file | image | url."""
    headers = headers or {}
    net = settings["network"]
    fields = []
    if headers.get("origin"):
        fields.append(f"Origin: {headers['origin']}")
    for k, val in (headers.get("extra") or {}).items():
        if val and k.lower() not in ("user-agent", "referer", "referrer", "origin"):
            fields.append(f"{k}: {val}")
    o: dict = {
        "user-agent": headers.get("user_agent") or net["user_agent"],
        "referrer": headers.get("referrer") or "",
        "http-header-fields": fields,
        "hls-bitrate": "max",            # 4K/1080p varyantı varsa en yükseğini seç
        "image-display-duration": "inf" if kind == "image" else "5",
        "cache": "yes",
        "demuxer-seekable-cache": "yes",  # canlıda duraklat/geri sar (tampon içinde)
    }
    if kind == "live":
        m = LATENCY_MODES[settings["latency"]["mode"]]
        lavf = []
        if m["nobuffer"]:
            lavf.append("fflags=+nobuffer")
        if is_hls(url):
            lavf.append(f"live_start_index={m['hls-start']}")
        o.update({
            "demuxer-max-bytes": "96MiB",
            "demuxer-max-back-bytes": "256MiB",
            "cache-pause": m["cache-pause"],
            "cache-pause-wait": m["cache-pause-wait"],
            "cache-pause-initial": m["cache-pause-initial"],
            "audio-buffer": m["audio-buffer"],
            "demuxer-lavf-probe-info": m["probe-info"],
            "demuxer-lavf-analyzeduration": m["analyzeduration"],
            "demuxer-lavf-o": ",".join(lavf),
            "video-latency-hacks": m["latency-hacks"],
            "stream-buffer-size": m["stream-buffer-size"],
            "curl-buffer-size": m["curl-buffer-size"],
            "video-sync": "audio",
            "interpolation": "no",
            "network-timeout": str(net["timeout"]),
            "af": "",
        })
    else:
        smooth = settings["video"]["smooth_vod"]
        o.update({
            "demuxer-max-bytes": "400MiB",
            "demuxer-max-back-bytes": "150MiB",
            "cache-pause": "yes",
            "cache-pause-wait": "1",
            "cache-pause-initial": "no",
            "audio-buffer": "0.2",
            "demuxer-lavf-probe-info": "auto",
            "demuxer-lavf-analyzeduration": "0",
            "demuxer-lavf-o": "",
            "video-latency-hacks": "no",
            "stream-buffer-size": "128KiB",
            "curl-buffer-size": "4MiB",
            "video-sync": "display-resample" if smooth else "audio",
            "interpolation": "yes" if smooth else "no",
            "tscale": "oversample",
            "network-timeout": str(max(30, net["timeout"])),
            "af": "@norm:lavfi=[dynaudnorm=f=250:g=15:p=0.95:m=8]" if settings["audio"]["normalize"] else "",
        })
    return o


def chase_targets(settings: dict, hls_target_duration: float | None = None) -> tuple[float, float]:
    """(hedef, üst sınır) sn. HLS'de tampon parça parça dolduğu için eşikler parça süresinin katlarıdır:
    hedef ≥ 1,2 parça, üst sınır ≥ 2,5 parça (aksi halde her parça arasında arabelleğe alma olurdu)."""
    target, limit = LATENCY_MODES[settings["latency"]["mode"]]["chase"]
    if hls_target_duration:
        target = max(target, 1.2 * hls_target_duration)
        limit = max(limit, 2.5 * hls_target_duration)
    return target, limit


def _is_hdr_source(vp: dict) -> bool:
    gamma = str(vp.get("gamma") or vp.get("transfer") or "").lower()
    return gamma in ("pq", "hlg", "st2084", "arib-std-b67")


def vsr_plan(settings: dict, vp: dict | None, screen: tuple[int, int] | None = None,
             platform: str = sys.platform, vsr_available: bool = True, kind: str | None = None) -> dict:
    """Kaynak çözünürlüğüne göre d3d11vpp filtresi: RTX VSR ile hedef kutuya (4K) büyütme + GPU deinterlace + RTX HDR.

    vp: mpv `video-params` (w, h, dw, dh, gamma ...). Dönüş: {"vf", "scale", "out", "deint", "hdr", "reason"}.
    """
    v = settings["video"]
    plan = {"vf": "", "scale": None, "out": None, "deint": False, "hdr": False, "reason": ""}
    if not is_windows(platform):
        plan["reason"] = "RTX VSR yalnızca Windows'ta (Direct3D 11) çalışır; yüksek kaliteli mpv ölçekleyici kullanılıyor."
        return plan
    if not vp or not vp.get("w") or not vp.get("h"):
        plan["reason"] = "Video bilgisi bekleniyor."
        return plan
    w, h = int(vp["w"]), int(vp["h"])
    dw, dh = int(vp.get("dw") or w), int(vp.get("dh") or h)
    parts: list[str] = []
    if v["rtx_vsr"] and (not vsr_available or kind == "image"):
        # VSR yok/fotoğraf: video işlemcisinin sıradan ölçeklemesi yerine mpv + yapay zekâ shader'ı büyütür
        plan["reason"] = ("Fotoğraf: yapay zekâ büyütücü + ewa_lanczossharp" if kind == "image" else
                          "RTX VSR kullanılamıyor: yapay zekâ büyütücü + ewa_lanczossharp")
    elif v["rtx_vsr"]:
        box = TARGET_BOXES.get(v["vsr_target"])
        if v["vsr_target"] == "screen" or box is None:
            box = screen if (screen and screen[0] > 0 and screen[1] > 0) else TARGET_BOXES["2160"]
        scale = min(box[0] / dw, box[1] / dh)
        if scale >= MIN_VSR_SCALE:
            scale = round(min(scale, MAX_VSR_SCALE), 4)
            plan["scale"] = scale
            ow, oh = int(w * scale), int(h * scale)
            plan["out"] = (ow + ow % 2, oh + oh % 2)
            parts += [f"scale={scale:g}", "scaling-mode=nvidia"]
            plan["reason"] = f"RTX VSR: {w}×{h} → {plan['out'][0]}×{plan['out'][1]}"
        else:
            plan["reason"] = f"Kaynak zaten hedef çözünürlükte ({w}×{h}); büyütme gerekmiyor."
    else:
        plan["reason"] = "RTX VSR kapalı (Ayarlar > Görüntü)."
    if v["deinterlace"] != "no":
        parts += ["deint=yes", "mode=adaptive"]
        if v["deinterlace"] == "auto":
            parts.append("interlaced-only=yes")
        plan["deint"] = True
    if v["rtx_hdr"] and not _is_hdr_source(vp):
        parts.append("nvidia-true-hdr=yes")
        plan["hdr"] = True
    if parts:
        plan["vf"] = "@helootv:d3d11vpp=" + ":".join(parts)
    return plan


def cli_args(opts: dict) -> list[str]:
    """Harici mpv.exe için komut satırı (aynı ayarlarla ayrı pencerede oynatma)."""
    args = []
    for k, val in opts.items():
        if isinstance(k, tuple):
            k = k[0]
        if isinstance(val, Choices):
            args.append(f"--{k}={val[0]}")
        elif isinstance(val, (list, tuple)):
            for item in val:
                args.append(f"--{k}-append={item}")
        elif val == "":
            args.append(f"--{k}=")
        else:
            args.append(f"--{k}={val}")
    return args
