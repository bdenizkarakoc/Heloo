"""mpv (libmpv) oynatıcı denetleyicisi — arayüzden bağımsız (Qt kullanmaz; testlerde başsız çalışır).

* Tek mpv örneği açık kalır, kanal geçişi `loadfile replace` ile yapılır → en hızlı zapping.
* `video-params` değişince RTX VSR filtresi kaynağın çözünürlüğüne göre yeniden hesaplanır (720p→×3, 1080p→×2 …).
* Canlıya yetişme: tampon (demuxer-cache-duration) hedefi aşarsa ×1,08 hız, çok aşarsa tampon içinde ileri atlama.
* Canlı yayın koparsa artan beklemelerle otomatik yeniden bağlanır.
* Tuşlar mpv'de `script-message helootv <eylem>` olarak tanımlıdır; eylemler `on_event("key", ...)` ile arayüze gider.
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import hls, paths
from . import options as opt

log = logging.getLogger("helootv.player")

MAX_RETRIES = 6
SPEED_BOOST = 1.08
PIN_CACHE_SECONDS = 300


@dataclass
class PlayRequest:
    url: str
    title: str
    kind: str = "live"                 # live | catchup | movie | episode
    key: tuple | None = None           # (kaynak, tür, kimlik) — geçmiş/kaldığın yer için
    logo: str = ""
    headers: dict = field(default_factory=dict)
    start: float | None = None         # sn (kaldığın yerden devam)
    subtitle: str = ""                 # OSD'de ikinci satır (şimdi yayında / S02E05)
    meta: dict = field(default_factory=dict)


class EngineError(Exception):
    """Kullanıcıya gösterilebilir oynatıcı hatası."""


INPUT_CONF = """\
# Heloo TV — mpv tuşları. Eylemler uygulamaya "script-message helootv <eylem>" olarak gider.
UP            script-message helootv up
DOWN          script-message helootv down
CHANNEL_UP    script-message helootv next
CHANNEL_DOWN  script-message helootv prev
PGUP          script-message helootv pgup
PGDWN         script-message helootv pgdn
LEFT          script-message helootv left
RIGHT         script-message helootv right
ENTER         script-message helootv enter
KP_ENTER      script-message helootv enter
ESC           script-message helootv esc
BS            script-message helootv last
f             script-message helootv fullscreen
F11           script-message helootv fullscreen
MBTN_LEFT_DBL script-message helootv fullscreen
t             script-message helootv theater
i             script-message helootv info
e             script-message helootv epg
l             script-message helootv live
SPACE         script-message helootv pause
p             script-message helootv pause
q             script-message helootv stop
Q             script-message helootv stop
STOP          script-message helootv stop
CLOSE_WIN     ignore
ctrl+w        script-message helootv stop
NEXT          script-message helootv next
PREV          script-message helootv prev
WHEEL_UP      add volume 2
WHEEL_DOWN    add volume -2
m             cycle mute
a             cycle audio
v             cycle sub-visibility
j             cycle sub
"""
INPUT_CONF += "".join(f"{d}  script-message helootv digit {d}\nKP{d}  script-message helootv digit {d}\n"
                      for d in range(10))

_ERROR_HINTS = [
    (re.compile(r"\b403\b|forbidden", re.I), "Sunucu erişimi reddetti (HTTP 403). Hesap süresi ya da bağlantı sınırı dolmuş olabilir."),
    (re.compile(r"\b401\b|unauthori", re.I), "Yetkisiz (HTTP 401): kullanıcı adı/şifre kabul edilmedi."),
    (re.compile(r"\b404\b|not found", re.I), "Yayın bulunamadı (HTTP 404). Kanal kaldırılmış olabilir."),
    (re.compile(r"\b(429|509)\b|too many", re.I), "Sunucu çok fazla bağlantı diyor (bağlantı sınırı)."),
    (re.compile(r"\b5\d\d\b", re.I), "Sunucu hatası (HTTP 5xx)."),
    (re.compile(r"refused|failed to connect|could not connect|couldn't connect", re.I), "Sunucuya bağlanılamadı."),
    (re.compile(r"resolve|name or service|getaddrinfo", re.I), "Sunucu adı çözümlenemedi (DNS)."),
    (re.compile(r"timed? ?out|timeout", re.I), "Bağlantı zaman aşımına uğradı."),
    (re.compile(r"recognize file format|unrecognized|invalid data", re.I), "Akış biçimi tanınamadı (bağlantı yayın değil)."),
    (re.compile(r"certificate|ssl|tls", re.I), "TLS sertifika hatası (Ayarlar > Ağ > TLS doğrulamasını kapatmayı deneyin)."),
]


def describe_mpv_error(lines: list[str]) -> str:
    for line in reversed(lines):
        for rx, hint in _ERROR_HINTS:
            if rx.search(line):
                return hint
    return ""


def write_input_conf(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "input.conf"
    if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != INPUT_CONF:
        path.write_text(INPUT_CONF, encoding="utf-8")
    return path


class MpvEngine:
    def __init__(self, settings: dict, *, wid: int | None = None, headless: bool = False,
                 platform: str = sys.platform, on_event: Callable[[str, dict], None] | None = None,
                 debug: bool = False, extra_options: dict | None = None):
        self.settings = settings
        self.wid = wid
        self.headless = headless
        self.platform = platform
        self.on_event = on_event or (lambda name, data: None)
        self.debug = debug
        self.extra_options = extra_options or {}
        self.mpv = None
        self._mpvlib = None
        self.version = ""
        self.request: PlayRequest | None = None
        self._lock = threading.RLock()
        self._entry_id = None
        self._expect_entry = None
        self._gen = 0
        self._retry = 0
        self._retry_timer: threading.Timer | None = None
        self._loaded_at = 0.0
        self._user_paused = False
        self._boost = False
        self._last_jump = 0.0
        self._vp: dict | None = None
        self._screen: tuple[int, int] | None = None
        self._plan: dict = {}
        self._current_vf = None
        self._errors: collections.deque[str] = collections.deque(maxlen=20)
        self._unsupported: set[str] = set()
        self.vsr_driver_failed = False
        self.hdr_driver_failed = False
        self._pin_cache: dict[str, tuple[str, float, str]] = {}
        self._no_pin: set[str] = set()
        self._pinned_url: str | None = None
        self._pin_from_cache = False
        self._vsr_ok = True
        self._hls_td: float | None = None
        self.resolver = hls.resolve_variant
        self.td_prober = hls.probe_target_duration

    # ------------------------------------------------------------------ yaşam döngüsü
    @property
    def available(self) -> bool:
        return self.mpv is not None

    def start(self) -> None:
        paths.prepare_libmpv_search_path()
        try:
            import mpv as mpvlib  # python-mpv (jaseg/python-mpv)
        except (OSError, ImportError, AttributeError) as e:
            raise EngineError(f"libmpv yüklenemedi: {e}") from e
        self._mpvlib = mpvlib
        conf = write_input_conf(paths.data_dir())
        init = opt.create_options(self.settings, wid=self.wid, input_conf=str(conf), headless=self.headless,
                                  platform=self.platform)
        init.update(self.extra_options)
        attempts = [init, {k: v for k, v in init.items() if k not in ("vo", "gpu-api", "hwdec")}]
        last: Exception | None = None
        for o in attempts:
            try:
                self.mpv = mpvlib.MPV(log_handler=self._on_log, loglevel="v" if self.debug else "warn",
                                      **{k.replace("-", "_"): v for k, v in o.items()})
                break
            except Exception as e:  # geçersiz seçenek → sade seçeneklerle bir daha dene
                last = e
                log.warning("mpv başlatma denemesi başarısız: %s", e)
        if self.mpv is None:
            raise EngineError(f"mpv başlatılamadı: {last}")
        self.version = str(self._get("mpv-version") or "")
        self.mpv.register_event_callback(self._on_mpv_event)
        self.mpv.observe_property("video-params", self._on_video_params)
        # OSC'nin tam ekran düğmesi gömülü pencerede işe yaramaz; değişikliği arayüze iletip pencereyi biz büyütürüz
        self.mpv.observe_property("fullscreen", lambda _n, v: self._emit("fullscreen", {"value": bool(v)}))
        self.mpv.register_message_handler("helootv", self._on_script_message)
        try:  # mpv ≥ 0.42: video alanına bırakılan dosyalar
            self.mpv.observe_property("dropped-files", self._on_dropped)
        except Exception:
            pass
        self.apply_settings(self.settings)

    def shutdown(self) -> None:
        self._cancel_retry()
        m, self.mpv = self.mpv, None
        if m is not None:
            try:
                m.terminate()
            except Exception:
                pass

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        t = getattr(self.mpv, "mpv_version_tuple", None) if self.mpv else None
        if t:
            return tuple(t)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", self.version or "")
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

    # ------------------------------------------------------------------ özellik yardımcıları
    def _get(self, name: str):
        if self.mpv is None:
            return None
        try:
            return self.mpv._get_property(name)
        except Exception:
            return None

    def _set(self, name, value) -> bool:
        """Özelliği ayarlar. name bir demetse ilk desteklenen ad; value opt.Choices ise ilk kabul edilen değer."""
        if self.mpv is None:
            return False
        values = list(value) if isinstance(value, opt.Choices) else [value]
        for n in (name if isinstance(name, tuple) else (name,)):
            if n in self._unsupported:
                continue
            for v in values:
                try:
                    self.mpv._set_property(n, v)
                    return True
                except AttributeError:      # bu mpv sürümünde yok → sıradaki ad
                    self._unsupported.add(n)
                    break
                except Exception as e:      # geçersiz değer (eski sürüm) → sıradaki değer
                    log.debug("mpv %s=%r ayarlanamadı: %s", n, v, e)
            else:
                return False
        return False

    def command(self, *args) -> object:
        if self.mpv is None:
            return None
        try:
            return self.mpv.command(*[str(a) for a in args])
        except Exception as e:
            log.debug("mpv komutu başarısız %s: %s", args, e)
            return None

    def _emit(self, name: str, data: dict | None = None) -> None:
        try:
            self.on_event(name, data or {})
        except Exception:
            log.exception("olay işleyici hatası: %s", name)

    # ------------------------------------------------------------------ ayarlar
    def apply_settings(self, settings: dict) -> None:
        self.settings = settings
        for k, v in opt.quality_options(settings, self.platform).items():
            self._set(k, v)
        self._update_vf(force=True)

    def set_vsr_available(self, ok: bool) -> None:
        """Ekran kartı RTX değilse VSR denenmez (video işlemcisinin sıradan ölçeklemesi yapay zekâdan kötü)."""
        ok = bool(ok) and not self.vsr_driver_failed
        if ok != self._vsr_ok:
            self._vsr_ok = ok
            self._update_vf(force=True)

    def _on_dropped(self, _name: str, value) -> None:
        files = (value or {}).get("files") if isinstance(value, dict) else None
        if files:
            self._emit("dropped", {"files": [str(f) for f in files]})

    def set_screen(self, width: int, height: int) -> None:
        if width > 0 and height > 0 and self._screen != (width, height):
            self._screen = (width, height)
            self._update_vf()

    # ------------------------------------------------------------------ oynatma
    def play(self, req: PlayRequest) -> None:
        if self.mpv is None:
            raise EngineError("Oynatıcı hazır değil (libmpv yüklenemedi).")
        with self._lock:
            self._cancel_retry()
            self._gen += 1
            self.request = req
            self._retry = 0
            self._user_paused = False
            self._boost = False
            self._errors.clear()
            self._vp = None          # önceki kanalın çözünürlüğü/yüklenme anı yeni kanalda görünmesin
            self._loaded_at = 0.0
            self._hls_td = None
            self._start_request(req)

    def _start_request(self, req: PlayRequest) -> None:
        """HLS ise önbellekteki ya da yeni çözülen tek kalite adresiyle, değilse doğrudan açar (kilit altında)."""
        self._pin_from_cache = False
        if self._should_pin(req):
            cached = self._pin_cache.get(req.url)
            if cached and time.monotonic() - cached[1] < PIN_CACHE_SECONDS:
                self._pin_from_cache = True
                self._load(dataclasses.replace(req, url=cached[0]), pinned_label=cached[2])
            else:
                self._emit("loading", {"title": req.title, "kind": req.kind, "subtitle": req.subtitle})
                threading.Thread(target=self._resolve_and_load, args=(req, self._gen), daemon=True,
                                 name="hls-resolve").start()
        else:
            self._load(req)

    def _should_pin(self, req: PlayRequest) -> bool:
        return req.kind in ("live", "catchup") and opt.is_hls(req.url) and req.url not in self._no_pin

    def _resolve_and_load(self, req: PlayRequest, gen: int) -> None:
        """HLS ana listesinden en iyi kaliteyi seç (FFmpeg'in tüm kaliteleri yoklamasını önler → hızlı açılış)."""
        variant, info = req.url, None
        try:
            variant, info = self.resolver(req.url, req.headers, self.settings["network"]["user_agent"], timeout=3.0,
                                          verify=self.settings["network"]["tls_verify"])
        except Exception as e:  # okunamadı: mpv özgün adresi açsın
            log.debug("HLS ana liste çözülemedi (%s): %s", req.url, e)
        label = f"{info.height}p" if info is not None and info.height else ""
        with self._lock:
            if gen != self._gen or self.mpv is None:
                return
            if variant != req.url:
                self._pin_cache[req.url] = (variant, time.monotonic(), label)
                self._load(dataclasses.replace(req, url=variant), pinned_label=label)
            else:
                self._no_pin.add(req.url)  # ana liste değil: bir dahakine doğrudan aç
                self._load(req)

    def _load(self, req: PlayRequest, pinned_label: str = "") -> None:
        for k, v in opt.play_options(self.settings, req.kind, req.url, req.headers).items():
            self._set(k, v)
        self._set("force-media-title", req.title)
        self._set("audio-files", [req.meta["audio"]] if req.meta.get("audio") else [])
        self._set("speed", "1")
        self._set("pause", "no")
        file_opts = f"start={int(req.start)}" if req.start and req.start > 5 else ""
        self._loaded_at = 0.0
        self._errors.clear()
        self._vp = None
        self._pinned_url = req.url if (self.request and req.url != self.request.url) else None
        if self._pinned_url:
            log.info("HLS kalite sabitlendi %s: %s", pinned_label, req.url)
        res = self._loadfile(req.url, file_opts)
        if req.kind == "live" and opt.is_hls(req.url) and self._hls_td is None:
            threading.Thread(target=self._probe_td, args=(req, self._gen), daemon=True, name="hls-td").start()
        # loadfile, yeni kaydın kimliğini döndürür; END_FILE yalnız bu kimlikle eşleşirse işlenir (hızlı kanal
        # değiştirmede eski yayının "bitti" olayı yeni kanalı yeniden başlatmasın)
        self._expect_entry = res.get("playlist_entry_id") if isinstance(res, dict) else None
        self._emit("loading", {"title": req.title, "kind": req.kind, "subtitle": req.subtitle})

    def _probe_td(self, req: PlayRequest, gen: int) -> None:
        """Arka planda HLS parça süresini öğren (oynatmayı bekletmez)."""
        try:
            td = self.td_prober(req.url, req.headers, self.settings["network"]["user_agent"], timeout=4.0,
                                verify=self.settings["network"]["tls_verify"])
        except Exception:
            td = None
        if gen == self._gen and td:
            self._hls_td = float(td)

    def _loadfile(self, url: str, file_opts: str):
        """Adlandırılmış argümanlar: mpv 0.38'de araya giren `index` argümanından etkilenmez."""
        named = {"url": url, "flags": "replace"}
        if file_opts:
            named["options"] = file_opts
        try:
            return self.mpv.command("loadfile", **named)
        except Exception as e:
            log.debug("adlandırılmış loadfile başarısız (%s); konumsal biçim deneniyor", e)
        args = [url, "replace"] + (["-1"] if self.version_tuple >= (0, 38, 0) else []) + [file_opts]
        return self.command("loadfile", *args)

    def stop(self) -> None:
        with self._lock:
            self._cancel_retry()
            self._gen += 1
            self.request = None
            self.command("stop")
            self._emit("stopped", {})

    def _cancel_retry(self) -> None:
        t, self._retry_timer = self._retry_timer, None
        if t is not None:
            t.cancel()

    def _schedule_retry(self, delay: float) -> None:
        gen = self._gen

        def run() -> None:
            with self._lock:
                if gen != self._gen or self.request is None or self.mpv is None:
                    return
                self._start_request(self.request)

        self._cancel_retry()
        self._retry_timer = threading.Timer(delay, run)
        self._retry_timer.daemon = True
        self._retry_timer.start()

    # ------------------------------------------------------------------ mpv olayları (mpv olay iş parçacığı)
    _NOISE = re.compile(r"AVHWDeviceContext|v4l2m2m|vaapi|vdpau|cuda|vulkan|VK_ERROR|Could not open codec|"
                        r"Invalid parameter for|hwdec|d3d11va-copy|Failed to set option", re.I)

    def _on_log(self, level: str, prefix: str, text: str) -> None:
        line = f"[{prefix}] {text.strip()}"
        if "Failed to enable NVIDIA RTX Super Resolution" in text and not self.vsr_driver_failed:
            # sürücü VSR'yi reddetti: video işlemcisinin sıradan ölçeklemesi yerine mpv + yapay zekâ büyütsün
            self.vsr_driver_failed = True
            self._vsr_ok = False
            self._update_vf(force=True)
        if "NVIDIA RTX Video HDR not supported" in text or "Failed to enable NVIDIA RTX Video HDR" in text:
            self.hdr_driver_failed = True
        if level in ("error", "fatal", "warn") and not self._NOISE.search(line):
            self._errors.append(line)
        if self.debug or level in ("error", "fatal"):
            log.info("mpv %s %s", level, line)

    def _on_mpv_event(self, event) -> None:
        E = self._mpvlib.MpvEventID
        eid = event.event_id.value
        if eid == E.START_FILE:
            self._entry_id = event.data.playlist_entry_id
        elif eid == E.FILE_LOADED:
            self._loaded_at = time.monotonic()
            self._emit("file-loaded", {})
        elif eid == E.PLAYBACK_RESTART:
            self._emit("playing", {})
        elif eid == E.END_FILE:
            d = event.data
            expected = self._expect_entry if self._expect_entry is not None else self._entry_id
            if d.playlist_entry_id != expected:
                return
            if d.reason in (0, 4):  # EOF ya da hata
                self._handle_end(d.reason)
        elif eid == E.SHUTDOWN:
            self._emit("shutdown", {})

    def _handle_end(self, reason: int) -> None:
        with self._lock:
            req = self.request
            if req is None:
                return
            msg = describe_mpv_error(list(self._errors))
            if self._pinned_url and not self._loaded_at:
                # sabitlenen kalite adresi açılamadı: önbellekteyse jetonu eskimiş olabilir → bir kez yeniden çöz;
                # yeni çözülen de açılmıyorsa (CDN çerezi ana listeye bağlı vb.) bu kanalda özgün adresi kullan
                self._pin_cache.pop(req.url, None)
                if not self._pin_from_cache:
                    self._no_pin.add(req.url)
                self._pinned_url = None
                self._schedule_retry(0.05)
                return
            if req.kind == "live" and self.settings["network"]["reconnect"]:
                if self._retry < MAX_RETRIES:
                    delay = min(8.0, 0.5 * (2 ** self._retry))
                    self._retry += 1
                    self._emit("reconnecting", {"attempt": self._retry, "max": MAX_RETRIES, "delay": delay,
                                                "error": msg})
                    self._schedule_retry(delay)
                    return
                self._emit("error", {"message": msg or "Canlı yayın durdu; yeniden bağlanılamadı."})
                return
            if reason == 0:
                self._emit("ended", {"kind": req.kind, "key": req.key})
            else:
                self._emit("error", {"message": msg or "Yayın açılamadı."})

    def _on_video_params(self, _name: str, value) -> None:
        self._vp = value if isinstance(value, dict) else None
        self._update_vf()

    def _update_vf(self, force: bool = False) -> None:
        plan = opt.vsr_plan(self.settings, self._vp, self._screen, self.platform, vsr_available=self._vsr_ok,
                            kind=self.request.kind if self.request else None)
        self._plan = plan
        if self.mpv is None:
            return
        # kaynağa göre değişen görüntü ayarları (düşük kalitede güçlü deband/keskinlik)
        tuned = opt.picture_options(self.settings, self._vp)
        key = tuple(sorted(tuned.items()))
        if key != getattr(self, "_tuned_key", None):
            self._tuned_key = key
            for k, v in tuned.items():
                self._set(k, v)
        if force or plan["vf"] != self._current_vf:
            if self._vp is not None or force:
                self._current_vf = plan["vf"]
                self._set("vf", plan["vf"])
        self._emit("vsr", dict(plan))

    def _on_script_message(self, *args) -> None:
        vals = [a.decode("utf-8", "replace") if isinstance(a, bytes) else str(a) for a in args]
        if vals:
            self._emit("key", {"action": vals[0], "args": vals[1:]})

    # ------------------------------------------------------------------ denetimler
    def toggle_pause(self) -> bool:
        paused = not bool(self._get("pause"))
        self._set("pause", "yes" if paused else "no")
        if self.request and self.request.kind == "live":
            self._user_paused = True if paused else self._user_paused
            if self._boost:
                self._set("speed", "1")
                self._boost = False
        return paused

    def seek(self, seconds: float) -> None:
        if self.request and self.request.kind == "live":
            self._user_paused = True  # canlıda geri sarınca zaman kaydırma kipine geç
        self.command("seek", f"{seconds:.1f}", "relative+exact")

    def go_live(self) -> None:
        """Zaman kaydırmadan çık: tamponun sonuna (canlı kenara) git."""
        self._user_paused = False
        self._set("pause", "no")
        cache = self._get("demuxer-cache-duration")
        is_hls = "hls" in str(self._get("file-format") or "") or bool(self.request and opt.is_hls(self.request.url))
        target, _ = opt.chase_targets(self.settings, (self._hls_td or 6.0) if is_hls else None)
        if isinstance(cache, (int, float)) and cache > target + 0.5:
            self.command("seek", f"{cache - target:.2f}", "relative+exact")

    def add_volume(self, delta: int) -> None:
        self.command("add", "volume", str(delta))

    def show_text(self, text: str, ms: int = 2500) -> None:
        self.command("show-text", text, str(ms))

    def cycle(self, prop: str) -> None:
        self.command("cycle", prop)

    # ------------------------------------------------------------------ izler, sarma, altyazı, görüntü
    def tracks(self) -> list[dict]:
        out = []
        for t in self._get("track-list") or []:
            if t.get("type") in ("audio", "sub", "video"):
                out.append({"id": t.get("id"), "type": t.get("type"), "title": t.get("title") or "",
                            "lang": t.get("lang") or "", "codec": t.get("codec") or "",
                            "selected": bool(t.get("selected")), "external": bool(t.get("external")),
                            "channels": t.get("demux-channel-count") or t.get("audio-channels")})
        return out

    def set_track(self, kind: str, track_id) -> None:
        self._set({"audio": "aid", "sub": "sid", "video": "vid"}[kind], "no" if track_id is None else str(track_id))

    def seek_abs(self, seconds: float) -> None:
        self.command("seek", f"{max(0.0, seconds):.2f}", "absolute+keyframes")

    def sub_add(self, path: str, title: str = "", lang: str = "") -> None:
        args = ["sub-add", path, "select"]
        if title or lang:
            args += [title or os.path.basename(path), lang]
        self.command(*args)

    def sub_reload(self) -> None:
        self.command("sub-reload")

    def add_prop(self, name: str, delta: float) -> None:
        self.command("add", name, str(delta))

    def apply_picture(self, settings: dict) -> None:
        """Görüntü ayarları penceresinden anında: parlaklık … keskinlik ve gürültü azaltma (filtre yeniden kurulur)."""
        self.settings = settings
        self._tuned_key = None
        for k, v in opt.quality_options(settings, self.platform).items():
            if k in ("glsl-shaders", "glsl-shader-opts", "hwdec"):
                self._set(k, v)
        self._update_vf(force=True)

    def screenshot(self) -> None:
        self.command("screenshot")

    def sync_fullscreen(self, value: bool) -> None:
        if bool(self._get("fullscreen")) != value:
            self._set("fullscreen", "yes" if value else "no")

    # ------------------------------------------------------------------ durum + canlıya yetişme
    def status(self) -> dict:
        req = self.request
        g = self._get
        vp = self._vp or {}
        vop = g("video-out-params") or {}
        if not isinstance(vop, dict):
            vop = {}
        plan = self._plan or {}
        out = plan.get("out")
        vsr_active = bool(plan.get("scale") and out and vop.get("w") and abs(int(vop["w"]) - out[0]) <= 2
                          and not self.vsr_driver_failed)
        cache = g("demuxer-cache-duration")
        fmt = str(g("file-format") or "")
        return {
            "title": req.title if req else "",
            "kind": req.kind if req else "",
            "active": req is not None and not bool(g("idle-active")),
            "paused": bool(g("pause")),
            "buffering": bool(g("paused-for-cache")),
            "seeking": bool(g("seeking")),
            "pos": g("time-pos"),
            "duration": g("duration"),
            "cache": cache if isinstance(cache, (int, float)) else None,
            "w": vp.get("w"), "h": vp.get("h"),
            "out_w": vop.get("w"), "out_h": vop.get("h"),
            "fps": g("container-fps") or g("estimated-vf-fps"),
            "codec": g("video-codec-name") or g("video-format") or "",
            "hwdec": g("hwdec-current") or "",
            "audio_codec": g("audio-codec-name") or "",
            "bitrate": g("video-bitrate"),
            "dropped": g("frame-drop-count") or 0,
            "speed": g("speed") or 1.0,
            "volume": g("volume"),
            "mute": bool(g("mute")),
            "hls": "hls" in fmt or (opt.is_hls(req.url) if req else False),
            "user_paused": self._user_paused,
            "boost": self._boost,
            "vsr": plan,
            "vsr_active": vsr_active,
            "vsr_driver_failed": self.vsr_driver_failed,
            "hdr_driver_failed": self.hdr_driver_failed,
            "retry": self._retry,
        }

    def tick(self) -> dict:
        if self.mpv is None or self.request is None:
            return {}
        st = self.status()
        if self.request.kind == "live":
            self._chase(st)
        if self._loaded_at and st["active"] and time.monotonic() - self._loaded_at > 20:
            self._retry = 0
        return st

    def _chase(self, st: dict) -> None:
        enabled = self.settings["latency"]["chase"]
        hls_unknown = st["hls"] and not self._hls_td
        if (not enabled or self._user_paused or st["paused"] or st["buffering"] or st["seeking"] or hls_unknown
                or st["cache"] is None):
            if self._boost:
                self._set("speed", "1")
                self._boost = False
            return
        target, limit = opt.chase_targets(self.settings, self._hls_td if st["hls"] else None)
        cache = st["cache"]
        now = time.monotonic()
        if cache > limit * 3 and now - self._last_jump > 8:
            self._last_jump = now
            self.command("seek", f"{cache - target:.2f}", "relative+exact")
            if self._boost:
                self._set("speed", "1")
                self._boost = False
        elif cache > limit and not self._boost:
            self._set("speed", str(SPEED_BOOST))
            self._boost = True
        elif self._boost and cache <= target + 0.15:
            self._set("speed", "1")
            self._boost = False


# ---------------------------------------------------------------------- harici mpv (yedek / ayrı pencere)

def find_mpv_exe() -> str | None:
    b = paths.bin_dir()
    for name in ("mpv.exe", "mpv"):
        p = b / name
        if p.is_file():
            return str(p)
    return shutil.which("mpv")


def external_profiles(settings: dict, platform: str = sys.platform) -> str:
    """Harici mpv için kaynağın yüksekliğine göre RTX VSR ölçeği seçen koşullu profiller (mpv auto-profiles)."""
    lines = ["# Heloo TV tarafından üretildi — harici mpv için RTX VSR koşullu profilleri", ""]
    buckets = [(0, 400, 360), (400, 500, 480), (500, 620, 576), (620, 800, 720), (800, 1200, 1080), (1200, 1600, 1440)]
    for lo, hi, h in buckets:
        w = int(round(h * 16 / 9 / 2) * 2)
        plan = opt.vsr_plan(settings, {"w": w, "h": h, "dw": w, "dh": h}, None, platform)
        lines += [f"[helootv-{h}p]", f"profile-cond=height and height > {lo} and height <= {hi}",
                  "profile-restore=copy", f"vf={plan['vf']}", ""]
    return "\n".join(lines)


def launch_external(req: PlayRequest, settings: dict, platform: str = sys.platform) -> subprocess.Popen:
    exe = find_mpv_exe()
    if not exe:
        raise EngineError("mpv.exe bulunamadı. Ayarlar > Sistem > 'mpv bileşenlerini indir' ile kurun.")
    conf_dir = paths.data_dir() / "mpv-external"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "mpv.conf").write_text(external_profiles(settings, platform), encoding="utf-8")
    write_input_conf(conf_dir)
    o = {k: v for k, v in opt.create_options(settings, platform=platform).items()
         if k not in ("idle", "force-window", "osd-playing-msg", "audio-display", "input-conf")}
    o.update(opt.quality_options(settings, platform))
    o.update(opt.play_options(settings, req.kind, req.url, req.headers))
    args = [exe, f"--config-dir={conf_dir}", "--config=yes", *opt.cli_args(o), f"--force-media-title={req.title}"]
    if req.start and req.start > 5:
        args.append(f"--start={int(req.start)}")
    args += ["--", req.url]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **kwargs)
