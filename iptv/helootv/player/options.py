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
# chase: (hedef, üst sınır) sn tampon. Takılmayı önleyen asıl şey tampondur: IPTV sunucuları ve ev interneti
# saniyelik dalgalanır; 1 sn'den küçük tampon her dalgada donma yapar. fflags=nobuffer ve video-latency-hacks zaman
# damgası sapmasına ve kare atlamaya yol açtığı için yalnız "ultra" kipte açıktır.
LATENCY_MODES: dict[str, dict] = {
    "auto": {
        "label": "Akıllı (önerilen)",
        "desc": "Bağlantıya göre kendini ayarlar: iyi bağlantıda ~1 sn gecikme, takılan kanalda tamponu büyütür, "
                "düzelince fark edilmeden (%4 hız) yeniden canlıya yaklaşır. Kanalları ayrı ayrı hatırlar.",
        "audio-buffer": "0.1", "cache-pause": "yes", "cache-pause-wait": "1", "cache-pause-initial": "no",
        "probe-info": "nostreams", "analyzeduration": "1", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -2, "stream-buffer-size": "128KiB", "curl-buffer-size": "2MiB", "chase": (1.0, 2.5),
        "adaptive": True,
    },
    "ultra": {
        "label": "Ultra düşük gecikme",
        "desc": "En hızlı kanal açılışı, en az tampon. Kablolu ve çok iyi internet ister; dalgalanırsa takılabilir.",
        "audio-buffer": "0.05", "cache-pause": "yes", "cache-pause-wait": "0.5", "cache-pause-initial": "no",
        "probe-info": "nostreams", "analyzeduration": "0.5", "nobuffer": True, "latency-hacks": "yes",
        "hls-start": -2, "stream-buffer-size": "64KiB", "curl-buffer-size": "1MiB", "chase": (1.0, 3.0),
    },
    "low": {
        "label": "Düşük gecikme",
        "desc": "Canlıya yakın: ~1,5 sn tampon, takılma olursa tamponu kendiliğinden büyütür. İyi internet ister.",
        "audio-buffer": "0.1", "cache-pause": "yes", "cache-pause-wait": "1", "cache-pause-initial": "no",
        "probe-info": "nostreams", "analyzeduration": "1", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -3, "stream-buffer-size": "128KiB", "curl-buffer-size": "2MiB", "chase": (1.5, 5.0),
    },
    "balanced": {
        "label": "Dengeli",
        "desc": "TiviMate/Smarters gibi ~3 sn tampon: kanal hızlı açılır, dalgalanmada donmaz.",
        "audio-buffer": "0.2", "cache-pause": "yes", "cache-pause-wait": "3", "cache-pause-initial": "no",
        "probe-info": "auto", "analyzeduration": "1", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -3, "stream-buffer-size": "128KiB", "curl-buffer-size": "4MiB", "chase": (3.0, 9.0),
    },
    "stable": {
        "label": "Kararlı (zayıf internet)",
        "desc": "Açılışta 3 sn tampon doldurur; zayıf ya da kablosuz bağlantıda en az takılma.",
        "audio-buffer": "0.25", "cache-pause": "yes", "cache-pause-wait": "3", "cache-pause-initial": "yes",
        "probe-info": "auto", "analyzeduration": "3", "nobuffer": False, "latency-hacks": "no",
        "hls-start": -3, "stream-buffer-size": "128KiB", "curl-buffer-size": "4MiB", "chase": (6.0, 18.0),
    },
}

LAVF_RECONNECT = "reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_delay_max=4"

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


def resolve_hwdec(settings: dict, platform: str = sys.platform, need_copy: bool = False) -> str:
    """need_copy: bu kaynakta işlemci filtresi (gürültü azaltma) var → kareler belleğe kopyalanır. Yalnız gerektiğinde
    (SD/720p'de); HD/1080p'de kopya yok, kareler GPU'da kalır (kopya 1080p50'de kare atlamaya yol açıyordu)."""
    v = settings["video"]["hwdec"]
    if v == "auto" and need_copy and is_windows(platform):
        return "d3d11va-copy,d3d11va"
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
        "hwdec": resolve_hwdec(settings, platform),
        "hwdec-codecs": "all",           # varsayılan liste MPEG-2'yi içermez; IPTV'deki SD kanallar için gerekli
        "dither-depth": "auto",
        "target-colorspace-hint": "yes" if v["rtx_hdr"] else "auto",
        "cursor-autohide": "1000",
        "cursor-autohide-fs-only": "no",
        "osd-duration": "1800",
        "osd-font-size": "38",
        ("osd-outline-size", "osd-border-size"): "2.6",
        "osd-bold": "yes",
        "osd-on-seek": "msg-bar",
        "volume-max": "150",
        "alang": TR_AUDIO if a["prefer"] == "tr" else "",
        "audio-spdif": "ac3,eac3,dts,dts-hd,truehd" if a["spdif"] else "",
        "audio-pitch-correction": "yes",  # canlıya yetişirken hızlanmada ses perdesi değişmez
        "sid": "auto" if s["prefer"] == "tr" else "no",
        "slang": TR_SUBS if s["prefer"] == "tr" else "",
        # Türkçe dublajda altyazıyı (zorunlu olanlar hariç) açma; mpv < 0.38 "forced" bilmez → "no"
        "subs-with-matching-audio": Choices(("forced", "no")),
        # okunaklı altyazı: kalın yazı, belirgin kenar + yumuşak gölge ya da yarı saydam kutu
        "sub-font-size": str(s["size"]),
        "sub-bold": "yes",
        "sub-color": "#FFFFE45C" if s.get("color") == "yellow" else "#FFFFFFFF",
        ("sub-outline-size", "sub-border-size"): "1.2" if s.get("style") == "box" else "3.0",
        "sub-shadow-offset": "0" if s.get("style") == "box" else "1.5",
        "sub-blur": "0.2",
        "sub-margin-y": "48",
        "sub-border-style": Choices(("background-box", "opaque-box")) if s.get("style") == "box"
        else Choices(("outline-and-shadow",)),
        "sub-back-color": "#99000000",
        "sub-ass-override": Choices(("scale", "yes")),
        "network-timeout": str(n["timeout"]),
        "tls-verify": "yes" if n["tls_verify"] else "no",
        "user-agent": n["user_agent"],
        "script-opts": ("osc-layout=bottombar,osc-seekbarstyle=bar,osc-hidetimeout=1600,osc-deadzonesize=0.5,"
                        "osc-idlescreen=no,osc-windowcontrols=no"),
    }
    # RTX VSR'nin büyütmediği her durumda (fotoğraf, sürücüde VSR kapalı, NVIDIA olmayan kart) yapay zekâ ile
    # 2 kat büyütme; shader yalnız mpv'nin kendisi ≥1,3 kat büyüttüğünde devreye girer (VSR 4K verince çalışmaz)
    shader = shaders.resolve(shaders.pick(settings))
    sharp = shaders.SHARPNESS.get(v.get("sharpen", "light"), 0.3)
    o["glsl-shaders"] = ([str(shader)] if shader else []) + ([str(shaders.CAS)] if sharp > 0 else [])
    o["glsl-shader-opts"] = f"cas_sharpness={sharp:g}"
    # video alanına bırakılan dosyaları mpv kendisi açmasın; dropped-files ile uygulama açar (aynı 4K zinciri)
    o[("input-builtin-drag-and-drop", "drag-and-drop")] = "no"
    o.update(picture_options(settings))
    if v["hq_scaling"]:
        # high-quality profilinin karşılığı (VSR'nin olmadığı ya da yetmediği büyütme için)
        o.update({"scale": "ewa_lanczossharp", "scale-antiring": "0.6", "hdr-peak-percentile": "99.995",
                  "hdr-contrast-recovery": "0.30"})
    else:
        o.update({"scale": "lanczos", "scale-antiring": "0"})
    # küçültme (VSR/FSR çıktısı pencereden büyükse) için hafif ve keskin filtre; ewa_* küçültmede GPU'yu boşa yorar
    o["dscale"] = "mitchell"
    o["correct-downscaling"] = "yes"
    if win:
        o["osd-font"] = "Segoe UI Semibold"
        o["sub-font"] = "Segoe UI Semibold"
        o["deinterlace"] = "no"          # Windows'ta deinterlace d3d11vpp (GPU) filtresinde yapılır
    else:
        o["deinterlace"] = Choices(("auto", "no")) if v["deinterlace"] == "auto" else v["deinterlace"]
    return o


def play_options(settings: dict, kind: str, url: str, headers: dict | None = None,
                 external_framegen: bool = False) -> dict:
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
    if kind in ("live", "catchup") and url.lower().startswith(("http://", "https://")):
        # bağlantı koparsa FFmpeg hemen yeniden bağlanır (oynatıcı 15 sn beklemez, akış kaldığı yerden sürer)
        o["stream-lavf-o"] = LAVF_RECONNECT
    if kind == "live":
        m = LATENCY_MODES[settings["latency"]["mode"]]
        lavf = []
        if m["nobuffer"]:
            lavf.append("fflags=+nobuffer")
        if is_hls(url):
            lavf.append(f"live_start_index={m['hls-start']}")
        o.update({
            "demuxer-max-bytes": "96MiB",
            # geri sarma tamponu: "hep canlı"da canlıda geri sarma yok → küçük (uzun maçta bellek şişmesin);
            # zaman kaydırma açıksa ~10 dk HD
            "demuxer-max-back-bytes": "32MiB" if settings.get("controls", {}).get("stay_live", True) else "256MiB",
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
    if external_framegen:
        # Lossless Scaling kare üretiyor: mpv kendi ara karesini üretmesin (ikisi birlikte titreme yapar)
        o["video-sync"] = "audio"
        o["interpolation"] = "no"
    return o


def chase_targets(settings: dict, hls_target_duration: float | None = None,
                  extra: float = 0.0) -> tuple[float, float]:
    """(hedef, üst sınır) sn. HLS'de tampon parça parça dolduğu için eşikler parça süresinin katlarıdır:
    hedef ≥ 1,2 parça, üst sınır ≥ 3 parça (aksi halde her parça arasında arabelleğe alma olurdu).
    extra: takılma oldukça motorun kendiliğinden eklediği güvenlik payı (sn)."""
    target, limit = LATENCY_MODES[settings["latency"]["mode"]]["chase"]
    if hls_target_duration:
        target = max(target, 1.2 * hls_target_duration)
        limit = max(limit, 3.0 * hls_target_duration)
    return target + extra, limit + 2 * extra


def _is_hdr_source(vp: dict) -> bool:
    gamma = str(vp.get("gamma") or vp.get("transfer") or "").lower()
    return gamma in ("pq", "hlg", "st2084", "arib-std-b67")


def vsr_plan(settings: dict, vp: dict | None, screen: tuple[int, int] | None = None,
             platform: str = sys.platform, vsr_available: bool = True, kind: str | None = None) -> dict:
    """Kaynak çözünürlüğüne göre d3d11vpp filtresi: RTX VSR ile hedef kutuya (4K) büyütme + GPU deinterlace + RTX HDR.

    vp: mpv `video-params` (w, h, dw, dh, gamma ...). Dönüş: {"vf", "scale", "out", "deint", "hdr", "reason"}.
    """
    v = settings["video"]
    plan = {"vf": "", "scale": None, "out": None, "deint": False, "hdr": False, "reason": "", "denoise": None}
    dn = denoise_strength(settings, vp)
    interlaced = bool((vp or {}).get("interlaced"))
    if dn and kind != "image":
        # gürültü VSR'den ÖNCE temizlenir: VSR karıncalanmayı değil temiz görüntüyü 4K'ya büyütür
        plan["denoise"] = dn
    # geçmeli (576i/1080i) kaynakta gürültü azaltma alanlar ayrılmadan uygulanırsa tarak/bulanıklık yapar:
    # önce bwdif (alan hızında, 50 fps akıcılık), sonra hqdn3d
    dn_filter = (f"@helootv-dn:lavfi=[bwdif=mode=send_field:deint=interlaced,hqdn3d={dn}]" if interlaced
                 else f"@helootv-dn:lavfi=[hqdn3d={dn}]") if plan["denoise"] else ""
    if not is_windows(platform):
        if plan["denoise"]:
            plan["vf"] = dn_filter
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
    if v["deinterlace"] != "no" and not (plan["denoise"] and interlaced):
        parts += ["deint=yes", "mode=adaptive"]
        if v["deinterlace"] == "auto":
            parts.append("interlaced-only=yes")
        plan["deint"] = True
    if v["rtx_hdr"] and not _is_hdr_source(vp):
        parts.append("nvidia-true-hdr=yes")
        plan["hdr"] = True
    if plan["denoise"] and interlaced:
        plan["deint"] = True
    chain = []
    if plan["denoise"]:
        chain.append(dn_filter)
    if parts:
        chain.append("@helootv:d3d11vpp=" + ":".join(parts))
    plan["vf"] = ",".join(chain)
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


# ---------------------------------------------------------------------- görüntü ayarları

# hqdn3d: luma uzamsal : kroma uzamsal : luma zamansal : kroma zamansal. Zamansal kısım yalnız önceki kareyi
# kullanır → gecikme eklemez; IPTV'deki karıncalanmayı (gürültü/kumlanma) ve titreşimi en etkili bunu giderir.
DENOISE = {"light": "1.5:1.5:4:4", "medium": "2.5:2:6:5", "strong": "4:3:9:7"}
PICTURE_PRESETS = {
    "natural": {"brightness": 0, "contrast": 0, "saturation": 0, "gamma": 0, "hue": 0, "denoise": "auto",
                "deband": 1, "sharpen": "light"},
    "vivid": {"brightness": 2, "contrast": 8, "saturation": 15, "gamma": 0, "hue": 0, "denoise": "auto",
              "deband": 1, "sharpen": "medium"},
    "cinema": {"brightness": -3, "contrast": 5, "saturation": -4, "gamma": 3, "hue": 0, "denoise": "light",
               "deband": 2, "sharpen": "light"},
    "sports": {"brightness": 3, "contrast": 6, "saturation": 10, "gamma": 0, "hue": 0, "denoise": "light",
               "deband": 1, "sharpen": "strong"},
    "noisy": {"brightness": 0, "contrast": 3, "saturation": 2, "gamma": 0, "hue": 0, "denoise": "strong",
              "deband": 3, "sharpen": "medium"},
}
PRESET_LABELS = {"natural": "Doğal", "vivid": "Canlı", "cinema": "Sinema", "sports": "Spor",
                 "noisy": "Karıncalı yayın", "custom": "Kendi ayarım"}
DEBAND = {0: None, 1: ("2", "35", "16", "5"), 2: ("3", "48", "20", "8"), 3: ("4", "64", "24", "12")}


def denoise_strength(settings: dict, vp: dict | None) -> str | None:
    """auto: SD'de (karıncalanmanın asıl olduğu yer) orta, 720p'de hafif; 1080p ve üstünde kapalı — orada RTX VSR'nin
    kendi sıkıştırma kusuru temizliği yeterli ve işlemci filtresi 1080p50'de kare atlatıyordu."""
    d = settings.get("picture", {}).get("denoise", "auto")
    if d == "off":
        return None
    if d != "auto":
        return DENOISE[d]
    h = int((vp or {}).get("h") or 0)
    if not h:
        return None
    return DENOISE["medium"] if h <= 576 else DENOISE["light"] if h <= 720 else None


def picture_options(settings: dict, vp: dict | None = None, vsr: bool = False) -> dict:
    """Anında değişebilen görüntü ayarları (parlaklık … deband). Düşük kaliteli kaynakta deband güçlenir.
    vsr: RTX VSR büyütüyor → VSR zaten keskinleştirir; CAS hafifletilir (aşırı keskinlik halesi olmasın)."""
    pic = settings.get("picture", {})
    o = {k: str(int(pic.get(k, 0))) for k in ("brightness", "contrast", "saturation", "gamma", "hue")}
    level = int(pic.get("deband", 1))
    if settings["video"].get("low_boost", True) and vp and int(vp.get("h") or 9999) <= 576:
        level = min(3, max(level, 2))
    vals = DEBAND.get(level)
    o["deband"] = "yes" if vals else "no"
    if vals:
        o.update(dict(zip(("deband-iterations", "deband-threshold", "deband-range", "deband-grain"), vals)))
    sharp = shaders.SHARPNESS.get(settings["video"].get("sharpen", "light"), 0.3)
    if vsr or shaders.pick(settings) == "fsr":
        # RTX VSR ve AMD FSR (RCAS) kendileri keskinleştirir: CAS yarıya (çift keskinlik halesi olmasın)
        sharp = round(sharp * 0.5, 3)
    elif settings["video"].get("low_boost", True) and vp and int(vp.get("h") or 9999) <= 576 and sharp > 0:
        sharp = min(1.0, sharp + 0.15)
    o["glsl-shader-opts"] = f"cas_sharpness={sharp:g}"
    return o


def apply_preset(settings: dict, name: str) -> None:
    p = PICTURE_PRESETS.get(name)
    if not p:
        return
    pic = settings.setdefault("picture", {})
    for k, v in p.items():
        if k == "sharpen":
            settings["video"]["sharpen"] = v
        else:
            pic[k] = v
    pic["preset"] = name


def enhancement_summary(settings: dict, plan: dict | None, vsr_active: bool, vp: dict | None,
                        platform: str = sys.platform, framegen: bool = False) -> list[str]:
    """Şu an görüntüye uygulanan iyileştirmeler (oynatıcı çubuğunda her zaman gösterilir; canlı yayın dahil)."""
    v = settings["video"]
    plan = plan or {}
    h = int((vp or {}).get("h") or 0)
    out: list[str] = []
    if vsr_active and plan.get("out"):
        out.append(f"RTX VSR {h}p→{plan['out'][1]}p" if h else "RTX VSR")
    elif h and h < 1440:
        shader = shaders.resolve(shaders.pick(settings))
        stem = shader.stem.lower() if shader else ""
        if stem == "fsr":
            out.append("AMD FSR büyütme")
        elif shader:
            out.append(f"Yapay zekâ büyütme ({'ArtCNN' if 'artcnn' in stem else 'FSRCNNX'})")
        else:
            out.append("Yüksek kaliteli büyütme")
    if plan.get("hdr"):
        out.append("RTX HDR")
    if plan.get("denoise"):
        out.append("Gürültü azaltma")
    sharp = shaders.SHARPNESS.get(v.get("sharpen", "light"), 0.3)
    if sharp > 0:
        out.append("Keskinlik")
    if int(settings.get("picture", {}).get("deband", 1)) > 0 or (h and h <= 576 and v.get("low_boost", True)):
        out.append("Bant yumuşatma")
    if framegen:
        out.append("Lossless Scaling kare üretimi")
    return out


def click_zone(x: float | None, width: float | None, kind: str | None, action: str = "zones") -> str:
    """Videoya tek tıklamanın anlamı: pause | back | forward | none.
    zones: sol üçte bir geri, sağ üçte bir ileri, orta duraklat/sürdür (fotoğrafta sarma yok)."""
    if action == "none" or kind is None:
        return "none"
    if action == "pause" or kind == "image" or not x or not width or width <= 0:
        return "none" if kind == "image" else "pause"
    f = float(x) / float(width)
    if f < 1 / 3:
        return "back"
    if f > 2 / 3:
        return "forward"
    return "pause"
