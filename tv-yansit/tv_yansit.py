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
import select
import shutil
import socket
import ssl
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
sys.path.insert(0, str(KOK))
import girdi  # noqa: E402
import ses as ses_mod  # noqa: E402
import sertifika  # noqa: E402
import lg  # noqa: E402

UYGULAMA_ADI = "TV Yansıt"
VARSAYILAN_PORT = 8780  # 8765'i Reels Fabrikası kullanır; çakışmasın
LOSSLESS_STEAM_ID = 993090  # Lossless Scaling (Steam mağazası)
WINDOWS = os.name == "nt"
PENCERESIZ = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if WINDOWS else 0

# Kalite ayarları. "uzak": zayıf/uzak Wi-Fi için düşük bit hızı + sık anahtar kare (kopmadan hızlı toparlar).
# "gecikme": en düşük gecikme (varsayılan) — küçük kareler hızlı gider, 60 fps, hızlı ölçekleme.
AYARLAR = {
    "gecikme": {"ad": "En düşük gecikme (720p 60, oyun)", "yukseklik": 720, "fps": 60, "bitrate": 8,
                "mjpeg_q": 6, "olcek": "bilinear"},
    "ultra": {"ad": "Ultra düşük gecikme (540p 60, yavaş TV / zayıf Wi-Fi)", "yukseklik": 540, "fps": 60,
              "bitrate": 5, "mjpeg_q": 7, "olcek": "bilinear"},
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


def yerel_ipler() -> list[str]:
    """Bilgisayarın bütün IPv4 adresleri (modem ağı, kendi Wi-Fi erişim noktası 192.168.137.1 …)."""
    ipler = [yerel_ip()]
    try:
        ipler += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    sonuc = []
    for ip in ipler:
        if ip not in sonuc and not ip.startswith(("127.", "169.254.")):
            sonuc.append(ip)
    return sonuc or ["127.0.0.1"]


def ayni_agdaki_ip(hedef: str, ipler: list[str]) -> str:
    """TV'nin ulaşabileceği yerel IP: TV ile aynı /24 ağdaki adres, yoksa ilk adres."""
    onek = hedef.rsplit(".", 1)[0] + "."
    for ip in ipler:
        if ip.startswith(onek):
            return ip
    return ipler[0]


VERI = KOK / "veri"                          # https sertifikası vb. (kaldırınca klasörle birlikte silinir)
KURULU_EXE = KOK.parent / "TV Yansit.exe"  # kur.ps1 ile kurulmuş uygulama: <klasör>/TV Yansit.exe + app/


def kurulum_ayari() -> dict:
    """kur.ps1'in yazdığı ayar.json (ör. ffmpeg'in tam yolu; Başlat menüsünden açılınca PATH eski olabilir)."""
    try:
        return json.loads((KOK / "ayar.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def ffmpeg_yolu() -> str | None:
    ayarli = kurulum_ayari().get("ffmpeg")
    if ayarli and Path(ayarli).exists():
        return ayarli
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
    if KURULU_EXE.exists():  # kurulu uygulama: Steam doğrudan TV Yansit.exe'yi açar (simgesiyle)
        exe, baslangic, secenekler, simge = f'"{KURULU_EXE}"', f'"{KURULU_EXE.parent}"', "--steam", str(KURULU_EXE)
    else:
        py = Path(sys.executable)
        pyw = py.with_name("pythonw.exe")
        exe, baslangic = f'"{pyw if pyw.exists() else py}"', f'"{KOK}"'
        secenekler, simge = f'"{KOK / "tv_yansit.py"}" --steam', ""
    eklenen = 0
    for kul in (steam / "userdata").iterdir():
        if not kul.is_dir() or not kul.name.isdigit() or kul.name == "0":
            continue
        dosya = kul / "config" / "shortcuts.vdf"
        dosya.parent.mkdir(parents=True, exist_ok=True)
        eski = dosya.read_bytes() if dosya.exists() else b""
        if eski:
            shutil.copy2(dosya, dosya.with_name(f"shortcuts.vdf.yedek-{time.strftime('%Y%m%d-%H%M%S')}"))
        kayit = kisayol_kaydi(exe, baslangic, secenekler, simge)
        dosya.write_bytes(kisayol_ekle(eski, kayit))
        eklenen += 1
    if not eklenen:
        return "Steam'e hiç giriş yapılmamış görünüyor (userdata boş)."
    return f"Steam kütüphanesine '{UYGULAMA_ADI}' eklendi. Steam'i açınca Kütüphane'de görünür."


# ---------------------------------------------------------------------------- Wi-Fi erişim noktası (modemsiz)

# Windows "Mobil etkin nokta": bilgisayar kendi Wi-Fi ağını açar, TV ona bağlanır (modem gerekmez).
# Bilgisayarın adresi bu ağda 192.168.137.1 olur; DLNA ve TV tarayıcısı aynen çalışır.
HOTSPOT_PS = r"""
$ErrorActionPreference = 'Stop'
$islem = '__ISLEM__'; $bant = '__BANT__'
function Cik($d) { $d | ConvertTo-Json -Compress; exit 0 }
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $m1 = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
  $asOp = ($m1 | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $asAct = ($m1 | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
  function Bekle($op, $tip) { $t = $asOp.MakeGenericMethod($tip).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
  function BekleE($op) { $t = $asAct.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
  $NI = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
  $TM = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
  $sonuc = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
  $prof = $NI::GetInternetConnectionProfile()
  if ($null -eq $prof) { $prof = @($NI::GetConnectionProfiles())[0] }
  if ($null -eq $prof) { Cik @{ hata = 'Ağ bağlantısı yok' } }
  $m = $TM::CreateFromConnectionProfile($prof)
  if ($islem -eq 'baslat') {
    if ($bant -ne '') {
      try { $c = $m.GetCurrentAccessPointConfiguration(); $c.Band = $bant; BekleE ($m.ConfigureAccessPointAsync($c)) } catch { }
    }
    if ($m.TetheringOperationalState -ne 'On') {
      $r = Bekle ($m.StartTetheringAsync()) $sonuc
      if ($r.Status -ne 'Success') { Cik @{ hata = [string]$r.Status + ' ' + $r.AdditionalErrorMessage } }
    }
  } elseif ($islem -eq 'durdur') {
    if ($m.TetheringOperationalState -eq 'On') { $null = Bekle ($m.StopTetheringAsync()) $sonuc }
  }
  $c = $m.GetCurrentAccessPointConfiguration()
  $b = ''; try { $b = [string]$c.Band } catch { }
  Cik @{ acik = ([string]$m.TetheringOperationalState -eq 'On'); ag = $c.Ssid; sifre = $c.Passphrase; bant = $b;
         bagli = $m.ClientCount }
} catch { Cik @{ hata = $_.Exception.Message } }
"""

HOTSPOT_BANTLARI = {"": "", "uzak": "TwoPointFourGigahertz", "hizli": "FiveGigahertz"}


def hotspot(islem: str = "durum", bant: str = "") -> dict:
    """islem: durum | baslat | durdur. bant: '' (otomatik), 'uzak' (2,4 GHz, daha uzağa), 'hizli' (5 GHz)."""
    if not WINDOWS:
        return {"hata": "Yalnızca Windows'ta"}
    betik = HOTSPOT_PS.replace("__ISLEM__", islem).replace("__BANT__", HOTSPOT_BANTLARI.get(bant, ""))
    try:
        p = calistir(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", betik], zaman=40)
    except (OSError, subprocess.SubprocessError) as e:
        return {"hata": str(e)}
    return hotspot_cozumle(p.stdout)


def hotspot_cozumle(cikti: str) -> dict:
    for satir in reversed(cikti.strip().splitlines()):
        satir = satir.strip()
        if satir.startswith("{"):
            try:
                return json.loads(satir)
            except ValueError:
                break
    return {"hata": (cikti.strip()[-200:] or "PowerShell yanıt vermedi")}


def hotspot_ayarlari() -> None:
    os.startfile("ms-settings:network-mobilehotspot")  # noqa: S606


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


def tv_ara(sure: float = 3.0, ipler: list[str] | None = None) -> list[dict]:
    """Bütün ağlarda (modem Wi-Fi'si, kablo, bilgisayarın kendi erişim noktası) DLNA TV arar."""
    soketler = []
    for ip in ipler or yerel_ipler():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
        except OSError:
            pass
        s.setblocking(False)
        for st in ST_LISTESI:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {st}\r\n\r\n").encode()
            for _ in range(2):
                try:
                    s.sendto(msg, SSDP_ADRES)
                except OSError:
                    pass
        soketler.append(s)
    konumlar: set[str] = set()
    bitis = time.time() + sure
    while time.time() < bitis:
        hazir, _, _ = select.select(soketler, [], [], 0.3)
        for s in hazir:
            try:
                veri, _ = s.recvfrom(65507)
            except OSError:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", veri)
            if m:
                konumlar.add(m.group(1).decode(errors="replace"))
    for s in soketler:
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


_ddagrab_onbellek: bool | None = None


def ddagrab_var(ffmpeg: str) -> bool:
    """Masaüstü Çoğaltma (ddagrab, ffmpeg 6+): ekranı ekran kartından kopyalar; gdigrab'dan çok daha hızlı."""
    global _ddagrab_onbellek
    if _ddagrab_onbellek is None:
        _ddagrab_onbellek = False
        if WINDOWS:
            try:
                p = calistir([ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                              "ddagrab=output_idx=0:framerate=5", "-frames:v", "1", "-f", "null", "-"], zaman=15)
                _ddagrab_onbellek = p.returncode == 0
            except (OSError, subprocess.SubprocessError):
                pass
    return _ddagrab_onbellek


# Girişte tampon yok: kodlayıcı yetişemezse kareler birikmez (gecikme saniyelerce büyümez), atlanır.
DUSUK_GECIKME_GIRIS = ["-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "32", "-analyzeduration", "0"]


def yakalama_girdisi(fps: int, kaynak: str, ffmpeg: str = "ffmpeg") -> tuple[list[str], str]:
    """(ffmpeg giriş argümanları, filtre öneki)."""
    if kaynak == "test" or not WINDOWS:
        return ["-re", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={fps}"], ""
    if kaynak == "ana" and ddagrab_var(ffmpeg):
        return (DUSUK_GECIKME_GIRIS + ["-f", "lavfi", "-i", f"ddagrab=output_idx=0:framerate={fps}:draw_mouse=1"],
                "hwdownload,format=bgra,")
    g = DUSUK_GECIKME_GIRIS + ["-thread_queue_size", "4", "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "1"]
    boyut = ana_ekran_boyutu()
    if boyut and kaynak == "ana":
        g += ["-offset_x", "0", "-offset_y", "0", "-video_size", f"{boyut[0]}x{boyut[1]}"]
    return g + ["-i", "desktop"], ""


def ts_komutu(ffmpeg: str, ayar: dict, enc: str, ses: str | None, kaynak: str = "ana",
              ses_oran: int = 48000) -> list[str]:
    """DLNA için canlı MPEG-TS (H.264 + AAC) → stdout. ses="pipe": bilgisayar sesi stdin'den (f32le stereo)."""
    fps, br, h = ayar["fps"], ayar["bitrate"], ayar["yukseklik"]
    g = fps  # saniyede bir anahtar kare: TV bağlanınca en geç 1 sn'de görüntü
    giris, onek = yakalama_girdisi(fps, kaynak, ffmpeg)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"] + giris
    if ses == "pipe":
        cmd += ["-thread_queue_size", "64", "-f", "f32le", "-ar", str(ses_oran), "-ac", "2", "-i", "pipe:0"]
    elif ses:
        cmd += ["-thread_queue_size", "16", "-f", "dshow", "-audio_buffer_size", "20", "-i", f"audio={ses}"]
    olcek = ayar.get("olcek", "lanczos")
    cmd += ["-vf", f"{onek}scale=-2:{h}:flags={olcek},format=yuv420p", "-c:v", enc]
    # Küçük VBV tamponu (~yarım saniye): kod çözücü daha az bekler
    oran = ["-b:v", f"{br}M", "-maxrate", f"{br}M", "-bufsize", f"{max(1, br // 2)}M"]
    if enc == "h264_nvenc":
        cmd += ["-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0", "-rc", "cbr"] + oran + ["-bf", "0"]
    elif enc == "h264_qsv":
        cmd += ["-preset", "veryfast", "-look_ahead", "0", "-async_depth", "1"] + oran + ["-bf", "0"]
    elif enc == "h264_amf":
        cmd += ["-usage", "ultralowlatency", "-quality", "speed", "-rc", "cbr"] + oran + ["-bf", "0"]
    else:
        cmd += ["-preset", "ultrafast" if fps >= 60 else "superfast", "-tune", "zerolatency"] + oran
    cmd += ["-profile:v", "high", "-level", "5.1" if h > 1080 else "4.2", "-g", str(g), "-r", str(fps)]
    cmd += (["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if ses else ["-an"])
    return cmd + ["-f", "mpegts", "-muxdelay", "0", "-muxpreload", "0", "-flush_packets", "1", "pipe:1"]


def mjpeg_komutu(ffmpeg: str, ayar: dict, kaynak: str = "ana") -> list[str]:
    """TV tarayıcısı için JPEG kare akışı → stdout."""
    fps = ayar["fps"]
    h = min(ayar["yukseklik"], 1080)  # TV tarayıcıları 4K JPEG'i akıcı çözemez
    giris, onek = yakalama_girdisi(fps, kaynak, ffmpeg)
    olcek = ayar.get("olcek", "lanczos")
    # yuvj420p: 4:4:4'e göre ~2 kat küçük kare → ağda ve TV'de çözmede daha hızlı. Kare çoğaltma yok.
    return ([ffmpeg, "-hide_banner", "-loglevel", "error"] + giris +
            ["-vf", f"{onek}scale=-2:{h}:flags={olcek}", "-pix_fmt", "yuvj420p", "-c:v", "mjpeg",
             "-q:v", str(ayar["mjpeg_q"]), "-an", "-flush_packets", "1", "-f", "image2pipe", "pipe:1"])


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
        self.kare_zamani = 0.0
        self.kare_no = 0
        self.son_izleyici = time.time()
        self.hata = ""
        self.komut: list[str] = []

    def baslat(self, komut: list[str], ses_kaynagi=None) -> None:
        with self.kilit:
            if self.surec and self.surec.poll() is None and komut == self.komut:
                return
        self.durdur()
        self.komut = komut
        self.hata = ""
        self.surec = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.PIPE if ses_kaynagi else subprocess.DEVNULL,
                                      creationflags=PENCERESIZ, bufsize=0)
        if ses_kaynagi:
            threading.Thread(target=self._ses_besle, args=(self.surec, ses_kaynagi), daemon=True).start()
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

    @staticmethod
    def _ses_besle(p: subprocess.Popen, kaynak) -> None:
        """Bilgisayar sesini ffmpeg'e (DLNA kodlayıcısı) aktarır."""
        no = 0
        try:
            while p.poll() is None:
                no, veri = kaynak.parcalar_sonra(no, bekle=0.5)
                if veri:
                    p.stdin.write(veri)
        except (OSError, ValueError):
            pass

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
                        self.kare_zamani = time.time()
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

    def yeni_kare(self, gorulen: int, bekle: float = 5.0, istemci: str | None = None,
                  gonderilen: dict | None = None) -> tuple[int, bytes | None, float]:
        """İstek-yanıt modu: TV bir kare ister, 'gorulen'den yeni olan en son kare gelir. Arada hiç kare
        birikmez; gecikme = yakalama + kodlama + tek karenin aktarımı. TV aynı anda iki istek bekletir
        (kare hazır olur olmaz gider); 'gonderilen' ile aynı kare o TV'ye iki kez gönderilmez."""
        with self.kilit:
            if gorulen > self.kare_no:  # uygulama yeniden başladı: sayaç sıfırlandı
                gorulen = -1
            bitis = time.time() + bekle
            while True:
                esik = gorulen
                if gonderilen is not None and istemci:
                    esik = max(gorulen, min(gonderilen.get(istemci, -1), self.kare_no))
                if self.kare_no > esik and self.son_kare is not None:
                    break
                kalan = bitis - time.time()
                if kalan <= 0 or not self.kilit.wait(kalan):
                    return self.kare_no, None, 0.0
            if gonderilen is not None and istemci:
                if len(gonderilen) > 50:
                    gonderilen.clear()
                gonderilen[istemci] = self.kare_no
            return self.kare_no, self.son_kare, self.kare_zamani

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

def kalici_pin(yeni: bool = False) -> str:
    """4 haneli kod. Her açılışta değişmez (TV bir kez öğrenir, tarayıcı geçmişinden açılır); 'Yeni kod' değiştirir."""
    dosya = VERI / "kod.txt"
    if not yeni:
        try:
            kod = dosya.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"\d{4}", kod):
                return kod
        except OSError:
            pass
    kod = f"{random.SystemRandom().randint(1000, 9999)}"
    try:
        VERI.mkdir(parents=True, exist_ok=True)
        dosya.write_text(kod, encoding="utf-8")
    except OSError:
        pass
    return kod


GIRIS_SAYFASI = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TV Yansıt</title>
<style>html,body{margin:0;height:100%;background:#0f1115;color:#e8eaf0;font-family:sans-serif}
main{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center}
h1{font-size:44px;margin:0 0 12px}p{font-size:26px;color:#9aa0ad;margin:8px}
#kod{display:flex;gap:18px;margin:34px 0}#kod div{width:90px;height:110px;border-radius:14px;background:#181b22;
border:3px solid #333a48;font:700 64px/110px monospace;color:#fff}#kod div.d{border-color:#4f8cff}
#m{font-size:28px;min-height:36px;color:#ff6b6b}</style></head><body><main>
<h1>TV Yansıt</h1><p>Bilgisayardaki panelde yazan 4 haneli kodu kumandanın rakam tuşlarıyla girin</p>
<div id="kod"><div></div><div></div><div></div><div></div></div><p id="m"></p></main>
<script>
var kod='', kutular=document.getElementById('kod').children, m=document.getElementById('m');
function ciz(){for(var i=0;i<4;i++){kutular[i].textContent=kod.charAt(i)||'';kutular[i].className=i===kod.length?'d':'';}}
function dene(){var x=new XMLHttpRequest();x.open('GET','/'+kod,true);x.onload=function(){
 if(x.status===200){location.href='/'+kod;}else{m.textContent=x.status===403?'Çok fazla yanlış deneme: bilgisayardaki paneli açın':'Kod yanlış, tekrar deneyin';kod='';ciz();}};
 x.onerror=function(){m.textContent='Bilgisayara ulaşılamadı';};x.send();}
document.addEventListener('keydown',function(e){var k=e.keyCode||e.which,r=-1;
 if(k>=48&&k<=57)r=k-48;else if(k>=96&&k<=105)r=k-96;
 if(r>=0&&kod.length<4){kod+=r;m.textContent='';ciz();if(kod.length===4)dene();e.preventDefault();}
 else if((k===8||k===37||k===461)&&kod.length){kod=kod.slice(0,-1);ciz();e.preventDefault();}},false);
ciz();
</script></body></html>"""


class Uygulama:
    def __init__(self, port: int, kaynak: str = "ana"):
        self.port = port
        self.kaynak = kaynak
        self.pin = kalici_pin()
        self.ffmpeg = ffmpeg_yolu()
        self.ts = Yayin("ts")
        self.mjpeg = Yayin("mjpeg")
        self.ayar_adi = "gecikme"
        self.tvler: list[dict] = []
        self.aktif_tv: dict | None = None
        self.lossless_otomatik = True
        self.mesaj = ""
        self._ses: str | None | bool = False  # False = henüz bakılmadı
        self.miracast = miracast_destegi()
        self.hotspot: dict = {}
        self.kumanda_acik = True  # TV'den klavye/fare/oyun kolu/kumanda (PIN'li); panelden kapatılabilir
        self.ses_y: ses_mod.SesYakala | None = None
        self.kumanda: girdi.Kumanda | None = None
        self.kumanda_son = 0.0
        self.kare_istek = 0.0
        self.gonderilen_kareler: dict[str, int] = {}
        self.yanlis_pin: dict[str, int] = {}
        threading.Thread(target=self._bekci, daemon=True).start()

    @property
    def ip(self) -> str:
        return yerel_ip()

    def tv_adresi(self, ip: str | None = None) -> str:
        return f"http://{ip or self.ip}:{self.port}/{self.pin}"

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

    def ses_yakalayici(self) -> "ses_mod.SesYakala | None":
        """Bilgisayar sesi: WASAPI (ek ayar gerekmez) → Stereo Karışımı → yok. Çalışıyorsa döndürür."""
        if self.ses_y is None:
            self.ses_y = ses_mod.SesYakala(ffmpeg=self.ffmpeg, dshow_aygit=self.ses() if WINDOWS else None,
                                           test=self.kaynak == "test")
        return self.ses_y if self.ses_y.baslat() else None

    def ts_baslat(self) -> None:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg bulunamadı (README: kurulum).")
        ayar = AYARLAR[self.ayar_adi]
        y = self.ses_yakalayici()
        komut = ts_komutu(self.ffmpeg, ayar, kodlayici(self.ffmpeg), "pipe" if y else None, self.kaynak,
                          y.oran if y else 48000)
        self.ts.baslat(komut, ses_kaynagi=y)

    def mjpeg_baslat(self) -> None:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg bulunamadı (README: kurulum).")
        self.mjpeg.baslat(mjpeg_komutu(self.ffmpeg, AYARLAR[self.ayar_adi], self.kaynak))

    def dlna_gonder(self, tv: dict) -> None:
        self._lossless()
        self.ts_baslat()
        self.aktif_tv = tv
        ip = ayni_agdaki_ip(tv["ip"], yerel_ipler())  # TV bilgisayarın Wi-Fi'sindeyse 192.168.137.1
        tv_oynat(tv, f"{self.tv_adresi(ip)}/ekran.ts")

    def durdur(self) -> None:
        if self.aktif_tv:
            try:
                tv_durdur(self.aktif_tv)
            except Exception:  # noqa: BLE001
                pass
        self.aktif_tv = None
        self.ts.durdur()
        self.mjpeg.durdur()
        if self.ses_y:
            self.ses_y.durdur()

    def kumanda_uygula(self, olaylar: list) -> int:
        if self.kumanda is None:
            self.kumanda = girdi.Kumanda(tum_ekranlar=self.kaynak == "tum")
        self.kumanda_son = time.time()
        return self.kumanda.uygula(olaylar)

    def kumanda_ayarla(self, acik: bool) -> None:
        self.kumanda_acik = acik
        if not acik and self.kumanda:
            self.kumanda.uygula([{"t": "birak"}])

    def _bekci(self) -> None:
        """İzleyicisi kalmayan yayını durdurur (bilgisayar boşuna kodlama yapmasın)."""
        while True:
            time.sleep(5)
            for y in (self.ts, self.mjpeg):
                if y.calisiyor() and not y.izleyiciler and not y.bagli and time.time() - y.son_izleyici > 15:
                    y.durdur()
            s = self.ses_y
            if s and s.calisiyor and not self.ts.calisiyor() and time.time() - s.son_istek > 20:
                s.durdur()

    def durum(self) -> dict:
        return {"uygulama": UYGULAMA_ADI, "kisa_adres": f"{self.ip}:{self.port}", "ip": self.ip, "port": self.port, "pin": self.pin, "tv_adresi": self.tv_adresi(),
                "tv_adresleri": [self.tv_adresi(ip) for ip in yerel_ipler()], "hotspot": self.hotspot,
                "ffmpeg": bool(self.ffmpeg), "kodlayici": _kodlayici_onbellek, "ses": (self.ses_y.kaynak if self.ses_y and self.ses_y.calisiyor else None),
                "ses_hata": self.ses_y.hata if self.ses_y else "",
                "miracast": self.miracast, "ayar": self.ayar_adi,
                "ayarlar": {k: v["ad"] for k, v in AYARLAR.items()},
                "tvler": [{"ad": t["ad"], "ip": t["ip"]} for t in self.tvler],
                "aktif_tv": self.aktif_tv["ad"] if self.aktif_tv else None,
                "dlna_yayin": self.ts.calisiyor(), "tarayici_yayin": self.mjpeg.calisiyor(),
                "tarayici_izleyici": self.mjpeg.bagli or time.time() - self.kare_istek < 5,
                "lossless_otomatik": self.lossless_otomatik, "lossless_yuklu": bool(lossless_exe()),
                "steam": bool(steam_klasoru()), "mesaj": self.mesaj,
                "hata": self.ts.hata or self.mjpeg.hata, "windows": WINDOWS,
                "kumanda_acik": self.kumanda_acik, "kumanda_bagli": time.time() - self.kumanda_son < 10,
                "sanal_kol": girdi.vgamepad_var() if self.kumanda is None else self.kumanda.sanal_kol}


def tv_sayfasi(app: "Uygulama") -> bytes:
    p = f"/{app.pin}"
    sanal = app.kumanda.sanal_kol if app.kumanda else girdi.vgamepad_var()
    html = (KOK / "tv.html").read_text(encoding="utf-8")
    html = (html.replace("__AKIS__", f"{p}/canli.mjpg").replace("__KARE__", f"{p}/kare.jpg")
            .replace("__SES__", f"{p}/ses")
            .replace("__GIRDI__", f"{p}/girdi"))
    return html.replace("__KUMANDA__", "true").replace("__SANALKOL__", "true" if sanal else "false").encode("utf-8")

YANLIS_PIN_SINIRI = 30


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
                try:
                    self.wfile.write(govde)
                except (ConnectionError, OSError):  # TV sayfayı kapattı
                    self.close_connection = True

        def _json(self, veri, kod: int = 200) -> None:
            self._gonder(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            yol = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
            p = f"/{app.pin}"
            if yol == "/":
                if not self._yerel():   # TV: yalnızca adres yazıldı → kod sorulur
                    if self._engelli():
                        return self._gonder(403, b"", "text/plain")
                    return self._gonder(200, GIRIS_SAYFASI.encode("utf-8"), "text/html; charset=utf-8")
                return self._gonder(200, (KOK / "panel.html").read_bytes(), "text/html; charset=utf-8")
            if yol == "/api/durum" and self._yerel():
                return self._json(app.durum())
            if self._engelli():
                return self._gonder(403, b"", "text/plain")
            if yol == p:
                return self._gonder(200, tv_sayfasi(app), "text/html; charset=utf-8")
            if yol == f"{p}/kare.jpg":
                return self._kare()
            if yol == f"{p}/ses":
                return self._ses()
            if yol == f"{p}/canli.mjpg":
                return self._mjpeg()
            if yol == f"{p}/ekran.ts":
                return self._ts()
            self._yanlis()
            self._gonder(404, "Bulunamadı — TV'de adresin sonundaki PIN'i kontrol edin.".encode(), "text/plain; charset=utf-8")

        def _engelli(self) -> bool:
            """PIN tahmin eden cihazı engeller (4 haneli PIN'i denemeyle bulmasın)."""
            return not self._yerel() and app.yanlis_pin.get(self.client_address[0], 0) >= YANLIS_PIN_SINIRI

        def _yanlis(self) -> None:
            if not self._yerel():
                ip = self.client_address[0]
                app.yanlis_pin[ip] = app.yanlis_pin.get(ip, 0) + 1

        def _girdi(self):
            uzunluk = min(int(self.headers.get("Content-Length") or 0), 256 * 1024)
            govde = self.rfile.read(uzunluk)
            if not app.kumanda_acik:
                return self._json({"hata": "Kumanda kapalı: bilgisayardaki panelden açın."}, 403)
            try:
                olaylar = json.loads(govde or b"[]")
            except ValueError:
                return self._json({"hata": "bozuk istek"}, 400)
            self._json({"n": app.kumanda_uygula(olaylar)})

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

        def _ses(self):
            """Bilgisayar sesi (f32le stereo), istek-yanıt: son istekten bu yana gelen parçalar."""
            try:
                gorulen = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("n", ["0"])[0])
            except ValueError:
                gorulen = 0
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            y = app.ses_yakalayici()
            if not y:
                return self._gonder(204, b"", "application/octet-stream", {"X-Ses": "yok"})
            no, veri = y.parcalar_sonra(gorulen, bekle=0.5, en_az=2)   # ~20 ms'lik paketler
            self._gonder(200, veri, "application/octet-stream",
                         {"X-Ses-No": str(no), "X-Oran": str(y.oran), "X-Kanal": "2"})

        def _kare(self):
            """Tek kare (istek-yanıt). X-Kare: kare numarası, X-Yas: kare ne kadar bekledi (ms)."""
            try:
                gorulen = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("n", ["0"])[0])
            except ValueError:
                gorulen = 0
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if not app.mjpeg.calisiyor():
                app._lossless()
            try:
                app.mjpeg_baslat()
            except RuntimeError as e:
                return self._gonder(503, str(e).encode(), "text/plain; charset=utf-8")
            app.kare_istek = app.mjpeg.son_izleyici = bas = time.time()
            istemci = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("c", [""])[0])[:16]
            no, kare, zaman = app.mjpeg.yeni_kare(gorulen, istemci=istemci, gonderilen=app.gonderilen_kareler)
            bekleme = int((time.time() - bas) * 1000)
            if kare is None:
                return self._gonder(204, b"", "image/jpeg", {"X-Kare": str(no)})
            yas = max(0, int((time.time() - zaman) * 1000))
            self._gonder(200, kare, "image/jpeg", {"X-Kare": str(no), "X-Yas": str(yas), "X-Bekleme": str(bekleme)})

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
            if urllib.parse.urlparse(self.path).path == f"/{app.pin}/girdi" and not self._engelli():
                return self._girdi()
            if not self._yerel():
                self._yanlis()
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
                if "kumanda_acik" in veri and bool(veri["kumanda_acik"]) != app.kumanda_acik:
                    app.kumanda_ayarla(bool(veri["kumanda_acik"]))
                    app.mesaj = ("TV'den kumanda açık: TV'ye bağlı klavye, fare ve oyun kolu bilgisayarı yönetir."
                                 if app.kumanda_acik else "TV'den kumanda kapatıldı.")
                if yol == "/api/ara":
                    app.tvler = tv_ara()
                    app.mesaj = f"{len(app.tvler)} TV bulundu." if app.tvler else \
                        "TV bulunamadı: TV açık mı, bilgisayarla aynı Wi-Fi'de mi (modem ya da bilgisayarın Wi-Fi'si), TV'de DLNA/'Ekran paylaşımı' açık mı?"
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
                elif yol == "/api/wifi":
                    islem = veri.get("islem", "durum")
                    if islem == "ayarlar":
                        hotspot_ayarlari()
                        app.mesaj = "Windows 'Mobil etkin nokta' ayarları açıldı."
                    else:
                        app.hotspot = hotspot(islem, veri.get("bant", ""))
                        h = app.hotspot
                        if h.get("hata"):
                            app.mesaj = ("Wi-Fi erişim noktası açılamadı: " + h["hata"] +
                                         " — 'Windows ayarlarını aç' ile elle açmayı deneyin.")
                        elif h.get("acik"):
                            app.mesaj = (f"Bilgisayarın Wi-Fi'si açık: TV'yi '{h.get('ag')}' ağına bağlayın "
                                         f"(şifre: {h.get('sifre')}), sonra 'TV'leri ara'.")
                        else:
                            app.mesaj = "Bilgisayarın Wi-Fi erişim noktası kapalı."
                elif yol == "/api/lg":
                    ip = str(veri.get("ip") or "").strip()
                    if not ip and str(veri.get("tv", "")).isdigit() and int(veri["tv"]) < len(app.tvler):
                        ip = app.tvler[int(veri["tv"])]["ip"]
                    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
                        raise RuntimeError("Önce TV'leri arayıp LG TV'yi seçin ya da TV'nin IP adresini yazın.")
                    adres = app.tv_adresi(ayni_agdaki_ip(ip, yerel_ipler()))
                    app.mesaj = lg.tvde_ac(ip, adres, VERI / "lg.json")
                elif yol == "/api/yeni-kod":
                    app.pin = kalici_pin(yeni=True)
                    app.yanlis_pin.clear()
                    app.mesaj = f"Yeni kod: {app.pin}. TV'de yeniden girin."
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


class OzelSunucu(ThreadingHTTPServer):
    """Portu başka programla paylaşmaz. Windows'ta SO_REUSEADDR başka bir uygulamanın portunu 'ele geçirmeye'
    izin verir (ör. 127.0.0.1:8765'te Reels Fabrikası varken 0.0.0.0:8765 açılabiliyor ve tarayıcı yine
    Reels Fabrikası'na gidiyordu); bu yüzden kapalı ve Windows'ta SO_EXCLUSIVEADDRUSE açık."""
    allow_reuse_address = False
    daemon_threads = True
    ssl_ctx = None   # https için (aynı port): ilk bayt TLS el sıkışmasıysa bağlantı TLS'e sarılır

    def finish_request(self, request, client_address):
        if self.ssl_ctx is not None:
            try:
                request.settimeout(5)
                ilk = request.recv(1, socket.MSG_PEEK)
                request.settimeout(None)
            except OSError:
                return
            if ilk == b"\x16":   # TLS ClientHello → https
                try:
                    request = self.ssl_ctx.wrap_socket(request, server_side=True)
                except (OSError, ssl.SSLError):
                    return     # TV sertifikayı reddetti (uyarıda "Devam"a basılmadı)
                try:
                    return super().finish_request(request, client_address)
                finally:
                    try:
                        request.close()
                    except OSError:
                        pass
        return super().finish_request(request, client_address)

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError, ssl.SSLError)):  # TV sayfayı kapattı: sessiz geç
            super().handle_error(request, client_address)

    def server_bind(self):
        if WINDOWS and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def port_dolu(port: int) -> bool:
    """Bu bilgisayarda o portu dinleyen herhangi bir program var mı (yalnız 127.0.0.1'e bağlı olsa bile)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def sunucu_baslat(app: Uygulama) -> ThreadingHTTPServer:
    for port in range(app.port, app.port + 20):
        if port_dolu(port):
            continue
        try:
            srv = OzelSunucu(("0.0.0.0", port), sunucu_kur(app))
        except OSError:
            continue
        srv.ssl_ctx = sertifika.ssl_baglami(VERI, yerel_ipler())
        app.port = port
        return srv
    raise SystemExit("Boş port bulunamadı.")


def tv_yansit_portu(port: int) -> bool:
    """O portta gerçekten TV Yansıt mı çalışıyor (başka bir uygulama değil)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/durum", timeout=1) as r:
            return json.loads(r.read()).get("uygulama") == UYGULAMA_ADI
    except (OSError, ValueError, AttributeError):
        return False


def acik_kopya_paneli(port: int) -> bool:
    """Uygulama zaten açıksa ikinci kopyayı başlatmaz, açık olanın panelini gösterir."""
    for p in range(port, port + 20):
        if port_dolu(p) and tv_yansit_portu(p):
            webbrowser.open(f"http://127.0.0.1:{p}/")
            return True
    return False


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
    if not a.acma and acik_kopya_paneli(a.port):
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
