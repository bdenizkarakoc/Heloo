"""TV Yansıt — bilgisayar ekranını televizyona yansıtır (Miracast desteklemeyen bilgisayarlar için).

İki yol (ikisi de ev ağı / modem üzerinden çalışır, Wi-Fi Direct değil → menzil modemin menzili kadar):
  1) DLNA: TV'yi ağda bulur, ekran görüntüsünü H.264 (NVIDIA/Intel/AMD donanım kodlayıcısı varsa onunla)
     canlı yayın olarak gönderir ve TV'de kendiliğinden oynatır. Ses varsa (Stereo Karışımı) sesi de gider.
  2) TV tarayıcısı: TV'nin internet tarayıcısında http://<bilgisayar-ip>:<port>/<PIN> adresi açılır;
     görüntü düşük gecikmeli MJPEG olarak gelir (bağlantı zayıflarsa kare atlar, donmaz).
Ek olarak: bilgisayar Miracast destekliyorsa Windows'un "Kablosuz ekrana bağlan" (Win+K) paneli açılır.

Kalite: yansıtma başlarken Lossless Scaling (Steam) kendiliğinden açılabilir.
Steam: "Steam'e ekle" ile bu uygulama Steam kütüphanesine Steam dışı oyun olarak eklenir (Big Picture'dan açılır).

Yalnızca standart Python kitaplığı + ffmpeg kullanır.
    python tv_yansit.py            # paneli tarayıcıda açar
    python tv_yansit.py --ara      # ağdaki TV'leri listeler
"""
from __future__ import annotations

import argparse
import binascii
import json
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KOK = Path(__file__).resolve().parent
UYGULAMA_ADI = "TV Yansıt"
VARSAYILAN_PORT = 8765
LOSSLESS_STEAM_ID = 993090  # Lossless Scaling (Steam mağazası)
WINDOWS = os.name == "nt"
PENCERESIZ = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if WINDOWS else 0

# Kalite ayarları. "uzak": zayıf/uzak Wi-Fi için düşük bit hızı + sık anahtar kare (kopmadan hızlı toparlar).
AYARLAR = {
    "kalite": {"ad": "Yüksek kalite (1080p 30)", "yukseklik": 1080, "fps": 30, "bitrate": 15, "mjpeg_q": 3},
    "akici": {"ad": "Akıcı (1080p 60, oyun)", "yukseklik": 1080, "fps": 60, "bitrate": 20, "mjpeg_q": 4},
    "uzak": {"ad": "Uzak menzil (720p, zayıf Wi-Fi)", "yukseklik": 720, "fps": 30, "bitrate": 5, "mjpeg_q": 7},
    "4k": {"ad": "4K (2160p 30, güçlü ağ)", "yukseklik": 2160, "fps": 30, "bitrate": 35, "mjpeg_q": 3},
}


# ---------------------------------------------------------------------------- yardımcılar

def calistir(cmd: list[str], zaman: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=zaman, creationflags=PENCERESIZ)


def yerel_ip() -> str:
    """Modeme çıkan arayüzün IP'si (paket gönderilmez)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ffmpeg_yolu() -> str | None:
    bul = shutil.which("ffmpeg")
    if bul:
        return bul
    for aday in (KOK / "ffmpeg.exe", KOK / "ffmpeg" / "bin" / "ffmpeg.exe", Path("C:/ffmpeg/bin/ffmpeg.exe")):
        if aday.exists():
            return str(aday)
    return None


def surec_calisiyor_mu(exe: str) -> bool:
    if not WINDOWS:
        return False
    try:
        out = calistir(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"]).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return exe.lower() in out.lower()


# ---------------------------------------------------------------------------- Miracast (yol 0)

def miracast_destegi() -> bool | None:
    """netsh çıktısındaki "Kablosuz Ekran Desteklenir / Wireless Display Supported" satırı. Bilinmiyorsa None."""
    if not WINDOWS:
        return None
    try:
        out = calistir(["netsh", "wlan", "show", "drivers"]).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return miracast_cozumle(out)


def miracast_cozumle(netsh_cikti: str) -> bool | None:
    for satir in netsh_cikti.splitlines():
        s = satir.lower()
        if "wireless display" in s or "kablosuz ekran" in s:
            ilk = (s.split(":", 1)[-1].split() or [""])[0]  # "Hayır (Grafik Sürücüsü: Evet …)" → "hayır"
            if ilk in ("yes", "evet"):
                return True
            if ilk in ("no", "hayır", "hayir"):
                return False
    return None


def miracast_paneli() -> None:
    """Win+K: Windows 'Yansıt / Kablosuz ekrana bağlan' paneli."""
    if not WINDOWS:
        raise RuntimeError("Yalnızca Windows'ta")
    import ctypes
    u = ctypes.windll.user32
    VK_LWIN, VK_K, UP = 0x5B, 0x4B, 0x0002
    u.keybd_event(VK_LWIN, 0, 0, 0)
    u.keybd_event(VK_K, 0, 0, 0)
    u.keybd_event(VK_K, 0, UP, 0)
    u.keybd_event(VK_LWIN, 0, UP, 0)


# ---------------------------------------------------------------------------- Steam + Lossless Scaling

def steam_klasoru() -> Path | None:
    if WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                p = Path(winreg.QueryValueEx(k, "SteamPath")[0])
                if p.exists():
                    return p
        except OSError:
            pass
        for p in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
            if p.exists():
                return p
    p = Path.home() / ".steam" / "steam"
    return p if p.exists() else None


def steam_kutuphaneleri(steam: Path) -> list[Path]:
    yollar = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p not in yollar:
                yollar.append(p)
    return yollar


def lossless_exe() -> Path | None:
    steam = steam_klasoru()
    if not steam:
        return None
    for kut in steam_kutuphaneleri(steam):
        exe = kut / "steamapps" / "common" / "Lossless Scaling" / "LosslessScaling.exe"
        if exe.exists():
            return exe
    return None


def lossless_ac() -> str:
    """Lossless Scaling'i açar (zaten açıksa dokunmaz). Dönen metin kullanıcıya gösterilir."""
    if surec_calisiyor_mu("LosslessScaling.exe"):
        return "Lossless Scaling zaten açık."
    if not WINDOWS:
        return "Lossless Scaling yalnızca Windows'ta açılır."
    exe = lossless_exe()
    if exe:
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        return "Lossless Scaling açıldı."
    os.startfile(f"steam://rungameid/{LOSSLESS_STEAM_ID}")  # noqa: S606 — Steam'e açtır
    return "Lossless Scaling Steam üzerinden açılıyor (yüklü değilse Steam mağaza sayfası gelir)."


# --- Steam ikili VDF (userdata/<id>/config/shortcuts.vdf) -------------------

class U64(int):
    """VDF'te 64 bit tamsayı (tip 0x07); geri yazarken aynı tipte kalsın."""


def vdf_oku(veri: bytes) -> dict:
    def metin(i: int) -> tuple[str, int]:
        j = veri.index(b"\x00", i)
        return veri[i:j].decode("utf-8", errors="replace"), j + 1

    def harita(i: int) -> tuple[dict, int]:
        d: dict = {}
        while i < len(veri):
            tip = veri[i]
            i += 1
            if tip == 0x08:
                return d, i
            ad, i = metin(i)
            if tip == 0x00:
                d[ad], i = harita(i)
            elif tip == 0x01:
                d[ad], i = metin(i)
            elif tip == 0x02:
                d[ad] = struct.unpack_from("<I", veri, i)[0]
                i += 4
            elif tip == 0x07:
                d[ad] = U64(struct.unpack_from("<Q", veri, i)[0])
                i += 8
            else:
                raise ValueError(f"Bilinmeyen VDF tipi {tip:#x}")
        return d, i

    return harita(0)[0] if veri else {}


def vdf_yaz(d: dict) -> bytes:
    out = bytearray()
    for ad, v in d.items():
        a = ad.encode("utf-8") + b"\x00"
        if isinstance(v, dict):
            out += b"\x00" + a + vdf_yaz(v)
        elif isinstance(v, U64):
            out += b"\x07" + a + struct.pack("<Q", int(v))
        elif isinstance(v, int):
            out += b"\x02" + a + struct.pack("<I", v & 0xFFFFFFFF)
        else:
            out += b"\x01" + a + str(v).encode("utf-8") + b"\x00"
    return bytes(out + b"\x08")


def kisayol_kaydi(exe: str, baslangic: str, secenekler: str, simge: str = "") -> dict:
    appid = (binascii.crc32((exe + UYGULAMA_ADI).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000
    return {"appid": appid, "AppName": UYGULAMA_ADI, "Exe": exe, "StartDir": baslangic, "icon": simge,
            "ShortcutPath": "", "LaunchOptions": secenekler, "IsHidden": 0, "AllowDesktopConfig": 1,
            "AllowOverlay": 1, "OpenVR": 0, "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0,
            "LastPlayTime": 0, "FlatpakAppID": "", "tags": {}}


def kisayol_ekle(veri: bytes, kayit: dict) -> bytes:
    """shortcuts.vdf içeriğine kaydı ekler; aynı adlı kayıt varsa günceller."""
    kok = vdf_oku(veri) if veri else {}
    liste = kok.setdefault("shortcuts", {})
    for k, v in liste.items():
        if isinstance(v, dict) and (v.get("AppName") or v.get("appname")) == UYGULAMA_ADI:
            liste[k] = kayit
            break
    else:
        liste[str(len(liste))] = kayit
    return vdf_yaz(kok)


def steame_ekle() -> str:
    """Bu uygulamayı Steam kütüphanesine 'Steam dışı oyun' olarak ekler (yedek alır)."""
    steam = steam_klasoru()
    if not steam or not (steam / "userdata").exists():
        return "Steam bulunamadı. Steam'de: Oyunlar → Steam dışı bir oyunu kütüphaneme ekle → 'TV Yansit.bat'."
    if surec_calisiyor_mu("steam.exe"):
        return "Önce Steam'i tamamen kapatın (sağ alttaki simge → Çıkış), sonra yeniden 'Steam'e ekle'ye basın."
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = f'"{pyw if pyw.exists() else py}"'
    betik = KOK / "tv_yansit.py"
    eklenen = 0
    for kul in (steam / "userdata").iterdir():
        if not kul.is_dir() or not kul.name.isdigit() or kul.name == "0":
            continue
        dosya = kul / "config" / "shortcuts.vdf"
        dosya.parent.mkdir(parents=True, exist_ok=True)
        eski = dosya.read_bytes() if dosya.exists() else b""
        if eski:
            shutil.copy2(dosya, dosya.with_name(f"shortcuts.vdf.yedek-{time.strftime('%Y%m%d-%H%M%S')}"))
        kayit = kisayol_kaydi(exe, f'"{KOK}"', f'"{betik}" --steam')
        dosya.write_bytes(kisayol_ekle(eski, kayit))
        eklenen += 1
    if not eklenen:
        return "Steam'e hiç giriş yapılmamış görünüyor (userdata boş)."
    return f"Steam kütüphanesine '{UYGULAMA_ADI}' eklendi. Steam'i açınca Kütüphane'de görünür."


# ---------------------------------------------------------------------------- DLNA (yol 1)

SSDP_ADRES = ("239.255.255.250", 1900)
ST_LISTESI = ("urn:schemas-upnp-org:device:MediaRenderer:1", "urn:schemas-upnp-org:service:AVTransport:1")


def _etiket(e: ET.Element) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _bul(e: ET.Element, ad: str) -> ET.Element | None:
    for c in e.iter():
        if _etiket(c) == ad:
            return c
    return None


def aciklama_cozumle(xml_metin: str, konum: str) -> dict | None:
    """UPnP aygıt açıklamasından ad + AVTransport denetim adresi."""
    kok = ET.fromstring(xml_metin)
    taban = _bul(kok, "URLBase")
    taban_url = (taban.text or "").strip() if taban is not None and taban.text else konum
    ad_e = _bul(kok, "friendlyName")
    for s in kok.iter():
        if _etiket(s) != "service":
            continue
        alan = {_etiket(c): (c.text or "").strip() for c in s}
        if "AVTransport" in alan.get("serviceType", ""):
            return {"ad": (ad_e.text or "TV").strip() if ad_e is not None else "TV",
                    "kontrol": urllib.parse.urljoin(taban_url, alan.get("controlURL", "")),
                    "servis": alan["serviceType"], "konum": konum,
                    "ip": urllib.parse.urlparse(konum).hostname or ""}
    return None


def tv_ara(sure: float = 3.0, ip: str | None = None) -> list[dict]:
    ip = ip or yerel_ip()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    except OSError:
        pass
    s.settimeout(0.4)
    for st in ST_LISTESI:
        msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
               f"MX: 2\r\nST: {st}\r\n\r\n").encode()
        for _ in range(2):
            try:
                s.sendto(msg, SSDP_ADRES)
            except OSError:
                pass
    konumlar: set[str] = set()
    bitis = time.time() + sure
    while time.time() < bitis:
        try:
            veri, _ = s.recvfrom(65507)
        except (socket.timeout, OSError):
            continue
        m = re.search(rb"(?im)^location:\s*(\S+)", veri)
        if m:
            konumlar.add(m.group(1).decode(errors="replace"))
    s.close()
    tvler, gorulen = [], set()
    for konum in sorted(konumlar):
        try:
            with urllib.request.urlopen(konum, timeout=3) as r:
                tv = aciklama_cozumle(r.read().decode("utf-8", errors="replace"), konum)
        except Exception:  # noqa: BLE001 — bozuk aygıtı atla
            continue
        if tv and tv["kontrol"] not in gorulen:
            gorulen.add(tv["kontrol"])
            tvler.append(tv)
    return tvler


DLNA_OZELLIK = "DLNA.ORG_OP=00;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def didl(url: str, baslik: str = "Bilgisayar ekranı") -> str:
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            f'<item id="0" parentID="-1" restricted="1"><dc:title>{escape(baslik)}</dc:title>'
            '<upnp:class>object.item.videoItem</upnp:class>'
            f'<res protocolInfo="http-get:*:video/mpeg:{DLNA_OZELLIK}">{escape(url)}</res></item></DIDL-Lite>')


def soap(tv: dict, eylem: str, govde: str) -> str:
    zarf = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{eylem} xmlns:u="{tv["servis"]}"><InstanceID>0</InstanceID>{govde}</u:{eylem}>'
            '</s:Body></s:Envelope>')
    req = urllib.request.Request(tv["kontrol"], data=zarf.encode("utf-8"), method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{tv["servis"]}#{eylem}"'})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read().decode("utf-8", errors="replace")


def tv_oynat(tv: dict, url: str) -> None:
    try:
        soap(tv, "Stop", "")
    except Exception:  # noqa: BLE001 — oynatmıyorsa hata verir
        pass
    soap(tv, "SetAVTransportURI",
         f"<CurrentURI>{escape(url)}</CurrentURI><CurrentURIMetaData>{escape(didl(url))}</CurrentURIMetaData>")
    time.sleep(0.5)
    soap(tv, "Play", "<Speed>1</Speed>")


def tv_durdur(tv: dict) -> None:
    soap(tv, "Stop", "")


# ---------------------------------------------------------------------------- ekran kodlama

_kodlayici_onbellek: str | None = None


def kodlayici(ffmpeg: str) -> str:
    """Donanım kodlayıcısı (NVIDIA → Intel → AMD) çalışıyorsa onu, yoksa libx264."""
    global _kodlayici_onbellek
    if _kodlayici_onbellek:
        return _kodlayici_onbellek
    secilen = "libx264"
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            p = calistir([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=0.2",
                          "-c:v", enc, "-f", "null", "-"], zaman=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0:
            secilen = enc
            break
    _kodlayici_onbellek = secilen
    return secilen


def ses_aygiti(ffmpeg: str) -> str | None:
    """Bilgisayar sesini yakalayan DirectShow aygıtı (Stereo Karışımı / Stereo Mix / sanal yakalayıcı)."""
    if not WINDOWS:
        return None
    try:
        err = calistir([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]).stderr
    except (OSError, subprocess.SubprocessError):
        return None
    return ses_aygiti_sec(err)


def ses_aygiti_sec(dshow_cikti: str) -> str | None:
    for ad in re.findall(r'"([^"]+)"\s*\(audio\)', dshow_cikti):
        if re.search(r"stereo mix|stereo karışımı|stereo karisimi|what u hear|virtual-audio-capturer|"
                     r"cable output", ad, re.I):
            return ad
    return None


def ana_ekran_boyutu() -> tuple[int, int] | None:
    if not WINDOWS:
        return None
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def yakalama_girdisi(fps: int, kaynak: str) -> list[str]:
    if kaynak == "test" or not WINDOWS:
        return ["-re", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={fps}"]
    g = ["-thread_queue_size", "512", "-rtbufsize", "200M", "-f", "gdigrab", "-framerate", str(fps),
         "-draw_mouse", "1"]
    boyut = ana_ekran_boyutu()
    if boyut and kaynak == "ana":
        g += ["-offset_x", "0", "-offset_y", "0", "-video_size", f"{boyut[0]}x{boyut[1]}"]
    return g + ["-i", "desktop"]


def ts_komutu(ffmpeg: str, ayar: dict, enc: str, ses: str | None, kaynak: str = "ana") -> list[str]:
    """DLNA için canlı MPEG-TS (H.264 + AAC) → stdout."""
    fps, br, h = ayar["fps"], ayar["bitrate"], ayar["yukseklik"]
    g = fps if ayar is AYARLAR["uzak"] or h <= 720 else fps * 2  # uzak menzil: saniyede bir anahtar kare
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"] + yakalama_girdisi(fps, kaynak)
    if ses:
        cmd += ["-thread_queue_size", "512", "-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={ses}"]
    cmd += ["-vf", f"scale=-2:{h}:flags=lanczos,format=yuv420p", "-c:v", enc]
    oran = ["-b:v", f"{br}M", "-maxrate", f"{br}M", "-bufsize", f"{br}M"]
    if enc == "h264_nvenc":
        cmd += ["-preset", "p4", "-tune", "ll", "-rc", "cbr"] + oran + ["-bf", "0"]
    elif enc == "h264_qsv":
        cmd += ["-preset", "faster", "-look_ahead", "0"] + oran
    elif enc == "h264_amf":
        cmd += ["-usage", "lowlatency", "-quality", "balanced", "-rc", "cbr"] + oran
    else:
        cmd += ["-preset", "veryfast", "-tune", "zerolatency"] + oran
    cmd += ["-profile:v", "high", "-level", "5.1" if h > 1080 else "4.2", "-g", str(g), "-r", str(fps)]
    cmd += (["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if ses else ["-an"])
    return cmd + ["-f", "mpegts", "-muxdelay", "0", "-flush_packets", "1", "pipe:1"]


def mjpeg_komutu(ffmpeg: str, ayar: dict, kaynak: str = "ana") -> list[str]:
    """TV tarayıcısı için JPEG kare akışı → stdout."""
    fps = min(ayar["fps"], 30)
    h = min(ayar["yukseklik"], 1080)  # TV tarayıcıları 4K JPEG'i akıcı çözemez
    return ([ffmpeg, "-hide_banner", "-loglevel", "error"] + yakalama_girdisi(fps, kaynak) +
            ["-vf", f"scale=-2:{h}:flags=lanczos", "-c:v", "mjpeg", "-q:v", str(ayar["mjpeg_q"]),
             "-r", str(fps), "-an", "-f", "image2pipe", "pipe:1"])


def jpeg_kareleri(tampon: bytearray) -> list[bytes]:
    """Tampondaki tam JPEG karelerini (FFD8…FFD9) ayırıp döndürür; kalanı tamponda bırakır."""
    kareler = []
    while True:
        bas = tampon.find(b"\xff\xd8")
        if bas < 0:
            tampon.clear()
            return kareler
        son = tampon.find(b"\xff\xd9", bas + 2)
        if son < 0:
            del tampon[:bas]
            return kareler
        kareler.append(bytes(tampon[bas:son + 2]))
        del tampon[:son + 2]


class Yayin:
    """Tek ffmpeg süreci → birçok izleyici. İzleyici kalmayınca 15 sn sonra kendiliğinden durur."""

    def __init__(self, tur: str):
        self.tur = tur  # "ts" | "mjpeg"
        self.kilit = threading.Condition()
        self.surec: subprocess.Popen | None = None
        self.izleyiciler: list[list] = []  # ts: her izleyiciye parça kuyruğu
        self.bagli = 0  # mjpeg: bağlı tarayıcı sayısı
        self.son_kare: bytes | None = None
        self.kare_no = 0
        self.son_izleyici = time.time()
        self.hata = ""
        self.komut: list[str] = []

    def baslat(self, komut: list[str]) -> None:
        with self.kilit:
            if self.surec and self.surec.poll() is None and komut == self.komut:
                return
        self.durdur()
        self.komut = komut
        self.hata = ""
        self.surec = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, creationflags=PENCERESIZ, bufsize=0)
        threading.Thread(target=self._oku, args=(self.surec,), daemon=True).start()
        threading.Thread(target=self._hata_oku, args=(self.surec,), daemon=True).start()

    def calisiyor(self) -> bool:
        return bool(self.surec and self.surec.poll() is None)

    def durdur(self) -> None:
        p, self.surec = self.surec, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        with self.kilit:
            self.kilit.notify_all()

    def _hata_oku(self, p: subprocess.Popen) -> None:
        for satir in iter(p.stderr.readline, b""):
            self.hata = satir.decode("utf-8", errors="replace").strip()[-300:]

    def _oku(self, p: subprocess.Popen) -> None:
        tampon = bytearray()
        while True:
            parca = p.stdout.read(65536)
            if not parca:
                break
            if self.tur == "ts":
                with self.kilit:
                    for kuyruk in list(self.izleyiciler):
                        if len(kuyruk) > 400:  # ~25 MB geride kalan izleyici: bağlantısını kes
                            self.izleyiciler.remove(kuyruk)
                            kuyruk.append(None)
                        else:
                            kuyruk.append(parca)
                    self.kilit.notify_all()
            else:
                tampon += parca
                for kare in jpeg_kareleri(tampon):
                    with self.kilit:
                        self.son_kare = kare
                        self.kare_no += 1
                        self.kilit.notify_all()
            if self.izleyiciler or self.bagli:
                self.son_izleyici = time.time()
        with self.kilit:
            for kuyruk in self.izleyiciler:
                kuyruk.append(None)
            self.kilit.notify_all()

    # --- izleyici tarafı
    def ts_akisi(self):
        kuyruk: list = []
        with self.kilit:
            self.izleyiciler.append(kuyruk)
        try:
            while True:
                with self.kilit:
                    while not kuyruk:
                        if not self.kilit.wait(10):
                            return
                    parcalar, kuyruk[:] = list(kuyruk), []
                for parca in parcalar:
                    if parca is None:
                        return
                    yield parca
        finally:
            with self.kilit:
                if kuyruk in self.izleyiciler:
                    self.izleyiciler.remove(kuyruk)
            self.son_izleyici = time.time()

    def kare_akisi(self):
        """En son kare: yavaş bağlantıda eski kareleri atlar (gecikme birikmez)."""
        gorulen = -1
        while True:
            with self.kilit:
                while self.kare_no == gorulen:
                    if not self.kilit.wait(10):
                        return
                gorulen, kare = self.kare_no, self.son_kare
            if kare:
                yield kare


# ---------------------------------------------------------------------------- uygulama durumu + sunucu

class Uygulama:
    def __init__(self, port: int, kaynak: str = "ana"):
        self.port = port
        self.kaynak = kaynak
        self.pin = f"{random.SystemRandom().randint(1000, 9999)}"
        self.ffmpeg = ffmpeg_yolu()
        self.ts = Yayin("ts")
        self.mjpeg = Yayin("mjpeg")
        self.ayar_adi = "kalite"
        self.tvler: list[dict] = []
        self.aktif_tv: dict | None = None
        self.lossless_otomatik = True
        self.mesaj = ""
        self._ses: str | None | bool = False  # False = henüz bakılmadı
        self.miracast = miracast_destegi()
        threading.Thread(target=self._bekci, daemon=True).start()

    @property
    def ip(self) -> str:
        return yerel_ip()

    def tv_adresi(self) -> str:
        return f"http://{self.ip}:{self.port}/{self.pin}"

    def ses(self) -> str | None:
        if self._ses is False:
            self._ses = ses_aygiti(self.ffmpeg) if self.ffmpeg else None
        return self._ses or None

    def _lossless(self) -> None:
        if self.lossless_otomatik:
            try:
                self.mesaj = lossless_ac()
            except OSError as e:
                self.mesaj = f"Lossless Scaling açılamadı: {e}"

    def ts_baslat(self) -> None:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg bulunamadı (README: kurulum).")
        ayar = AYARLAR[self.ayar_adi]
        self.ts.baslat(ts_komutu(self.ffmpeg, ayar, kodlayici(self.ffmpeg), self.ses(), self.kaynak))

    def mjpeg_baslat(self) -> None:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg bulunamadı (README: kurulum).")
        self.mjpeg.baslat(mjpeg_komutu(self.ffmpeg, AYARLAR[self.ayar_adi], self.kaynak))

    def dlna_gonder(self, tv: dict) -> None:
        self._lossless()
        self.ts_baslat()
        self.aktif_tv = tv
        tv_oynat(tv, f"http://{self.ip}:{self.port}/{self.pin}/ekran.ts")

    def durdur(self) -> None:
        if self.aktif_tv:
            try:
                tv_durdur(self.aktif_tv)
            except Exception:  # noqa: BLE001
                pass
        self.aktif_tv = None
        self.ts.durdur()
        self.mjpeg.durdur()

    def _bekci(self) -> None:
        """İzleyicisi kalmayan yayını durdurur (bilgisayar boşuna kodlama yapmasın)."""
        while True:
            time.sleep(5)
            for y in (self.ts, self.mjpeg):
                if y.calisiyor() and not y.izleyiciler and not y.bagli and time.time() - y.son_izleyici > 15:
                    y.durdur()

    def durum(self) -> dict:
        return {"ip": self.ip, "port": self.port, "pin": self.pin, "tv_adresi": self.tv_adresi(),
                "ffmpeg": bool(self.ffmpeg), "kodlayici": _kodlayici_onbellek, "ses": self._ses or None,
                "miracast": self.miracast, "ayar": self.ayar_adi,
                "ayarlar": {k: v["ad"] for k, v in AYARLAR.items()},
                "tvler": [{"ad": t["ad"], "ip": t["ip"]} for t in self.tvler],
                "aktif_tv": self.aktif_tv["ad"] if self.aktif_tv else None,
                "dlna_yayin": self.ts.calisiyor(), "tarayici_yayin": self.mjpeg.calisiyor(),
                "tarayici_izleyici": self.mjpeg.bagli,
                "lossless_otomatik": self.lossless_otomatik, "lossless_yuklu": bool(lossless_exe()),
                "steam": bool(steam_klasoru()), "mesaj": self.mesaj,
                "hata": self.ts.hata or self.mjpeg.hata, "windows": WINDOWS}


TV_SAYFASI = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TV Yansıt</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
img{position:fixed;inset:0;width:100%;height:100%;object-fit:contain}
#b{position:fixed;left:0;right:0;bottom:8%;color:#fff;font:28px sans-serif;text-align:center}</style>
</head><body><img id="g" src="__AKIS__" alt=""><div id="b">Bağlanıyor…</div>
<script>
var g=document.getElementById('g'),b=document.getElementById('b');
g.onload=function(){b.style.display='none'};
g.onerror=function(){b.style.display='block';b.textContent='Bağlantı koptu, yeniden deneniyor…';
 setTimeout(function(){g.src='__AKIS__?t='+(+new Date())},2000)};
document.body.onclick=function(){var e=document.documentElement;(e.requestFullscreen||e.webkitRequestFullscreen||function(){}).call(e)};
</script></body></html>"""


def sunucu_kur(app: Uygulama) -> type[BaseHTTPRequestHandler]:
    class Isleyici(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "TVYansit/1.0"

        def log_message(self, *a):  # sessiz
            pass

        def _yerel(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _gonder(self, kod: int, govde: bytes, tur: str, ek: dict | None = None) -> None:
            self.send_response(kod)
            self.send_header("Content-Type", tur)
            self.send_header("Content-Length", str(len(govde)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (ek or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(govde)

        def _json(self, veri, kod: int = 200) -> None:
            self._gonder(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            yol = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            p = f"/{app.pin}"
            if yol == "/":
                if not self._yerel():
                    return self._gonder(404, b"", "text/plain")
                return self._gonder(200, (KOK / "panel.html").read_bytes(), "text/html; charset=utf-8")
            if yol == "/api/durum" and self._yerel():
                return self._json(app.durum())
            if yol == p:
                html = TV_SAYFASI.replace("__AKIS__", f"{p}/canli.mjpg")
                return self._gonder(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if yol == f"{p}/canli.mjpg":
                return self._mjpeg()
            if yol == f"{p}/ekran.ts":
                return self._ts()
            self._gonder(404, "Bulunamadı — TV'de adresin sonundaki PIN'i kontrol edin.".encode(), "text/plain; charset=utf-8")

        def _ts(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mpeg")
            self.send_header("transferMode.dlna.org", "Streaming")
            self.send_header("contentFeatures.dlna.org", DLNA_OZELLIK)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return
            try:
                app.ts_baslat()
                for parca in app.ts.ts_akisi():
                    self.wfile.write(parca)
            except (ConnectionError, OSError, RuntimeError):
                pass

        def _mjpeg(self):
            sinir = "kare"
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={sinir}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return
            app.mjpeg.bagli += 1
            try:
                if not app.mjpeg.calisiyor():
                    app._lossless()
                app.mjpeg_baslat()
                for kare in app.mjpeg.kare_akisi():
                    self.wfile.write(f"--{sinir}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(kare)}\r\n\r\n".encode())
                    self.wfile.write(kare + b"\r\n")
            except (ConnectionError, OSError, RuntimeError):
                pass
            finally:
                app.mjpeg.bagli -= 1
                app.mjpeg.son_izleyici = time.time()

        def do_POST(self):
            if not self._yerel():
                return self._gonder(403, b"", "text/plain")
            uzunluk = int(self.headers.get("Content-Length") or 0)
            try:
                veri = json.loads(self.rfile.read(uzunluk) or b"{}")
            except ValueError:
                veri = {}
            yol = urllib.parse.urlparse(self.path).path
            try:
                if veri.get("ayar") in AYARLAR:
                    app.ayar_adi = veri["ayar"]
                if "lossless_otomatik" in veri:
                    app.lossless_otomatik = bool(veri["lossless_otomatik"])
                if yol == "/api/ara":
                    app.tvler = tv_ara()
                    app.mesaj = f"{len(app.tvler)} TV bulundu." if app.tvler else \
                        "TV bulunamadı: TV açık mı, aynı modeme bağlı mı, TV'de DLNA/'Ekran paylaşımı' açık mı?"
                elif yol == "/api/gonder":
                    i = int(veri.get("tv", 0))
                    if not 0 <= i < len(app.tvler):
                        raise RuntimeError("Önce TV arayın ve listeden seçin.")
                    app.dlna_gonder(app.tvler[i])
                    app.mesaj = f"{app.tvler[i]['ad']} ekranına gönderildi (ilk görüntü 2-5 sn sürebilir)."
                elif yol == "/api/durdur":
                    app.durdur()
                    app.mesaj = "Yansıtma durduruldu."
                elif yol == "/api/miracast":
                    miracast_paneli()
                    app.mesaj = "Windows 'Yansıt' paneli açıldı; listeden TV'nizi seçin."
                elif yol == "/api/lossless":
                    app.mesaj = lossless_ac()
                elif yol == "/api/steam":
                    app.mesaj = steame_ekle()
                elif yol != "/api/ayar":
                    return self._json({"hata": "bilinmeyen istek"}, 404)
            except Exception as e:  # noqa: BLE001 — paneli göster
                app.mesaj = f"Hata: {e}"
            self._json(app.durum())

    return Isleyici


def sunucu_baslat(app: Uygulama) -> ThreadingHTTPServer:
    for port in range(app.port, app.port + 20):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), sunucu_kur(app))
        except OSError:
            continue
        app.port = port
        srv.daemon_threads = True
        return srv
    raise SystemExit("Boş port bulunamadı.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bilgisayar ekranını TV'ye yansıt (DLNA + TV tarayıcısı).")
    ap.add_argument("--port", type=int, default=VARSAYILAN_PORT)
    ap.add_argument("--ara", action="store_true", help="ağdaki TV'leri listele ve çık")
    ap.add_argument("--kaynak", choices=["ana", "tum", "test"], default="ana",
                    help="ana ekran, bütün ekranlar ya da test görüntüsü")
    ap.add_argument("--acma", action="store_true", help="paneli tarayıcıda açma")
    ap.add_argument("--steam", action="store_true", help="Steam'den başlatıldı (paneli aç)")
    a = ap.parse_args(argv)
    if a.ara:
        tvler = tv_ara()
        for t in tvler:
            print(f"{t['ad']}  ({t['ip']})")
        if not tvler:
            print("TV bulunamadı.")
        return 0
    app = Uygulama(a.port, a.kaynak)
    srv = sunucu_baslat(app)
    print(f"{UYGULAMA_ADI} çalışıyor → panel: http://127.0.0.1:{app.port}/   TV tarayıcısı: {app.tv_adresi()}")
    if not app.ffmpeg:
        print("UYARI: ffmpeg bulunamadı; README'deki kurulum adımına bakın.")
    if not a.acma:
        threading.Timer(0.6, webbrowser.open, args=(f"http://127.0.0.1:{app.port}/",)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.durdur()
    return 0


if __name__ == "__main__":
    sys.exit(main())
