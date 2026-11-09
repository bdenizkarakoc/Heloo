"""LG webOS TV'de sayfayı kendiliğinden açma (SSAP — LG'nin yerel ağ kumanda arayüzü).

İlk seferde TV ekranında "bu cihaza izin verilsin mi?" sorusu çıkar; kumandayla kabul edilir. TV'nin verdiği
anahtar saklanır, sonraki seferlerde soru çıkmaz. Ardından TV'nin tarayıcısı verilen adresi kendisi açar.

Yalnızca Python standart kitaplığı: WebSocket istemcisi burada (wss://<tv>:3001, eski TV'lerde ws://<tv>:3000).
"""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
from pathlib import Path

UYGULAMA = "TV Yansıt"

# LG'nin herkese açık örnek uygulama tanımı (LG Connect SDK ile gelen, açık kaynak kumanda kitaplıklarında
# kullanılan imzalı manifest). TV izin sorusunu bununla gösterir.
_IMZALI = {
    "created": "20140509",
    "appId": "com.lge.test",
    "vendorId": "com.lge",
    "localizedAppNames": {"": "LG Remote App", "ko-KR": "리모컨 앱", "zxx-XX": "ЛГ Rэмotэ AПП"},
    "localizedVendorNames": {"": "LG Electronics"},
    "permissions": ["TEST_SECURE", "CONTROL_INPUT_TEXT", "CONTROL_MOUSE_AND_KEYBOARD", "READ_INSTALLED_APPS",
                    "READ_LGE_SDX", "READ_NOTIFICATIONS", "SEARCH", "WRITE_SETTINGS", "WRITE_NOTIFICATION_ALERT",
                    "CONTROL_POWER", "READ_CURRENT_CHANNEL", "READ_RUNNING_APPS", "READ_UPDATE_INFO",
                    "UPDATE_FROM_REMOTE_APP", "READ_LGE_TV_INPUT_EVENTS", "READ_TV_CURRENT_TIME"],
    "serial": "2f930e2d2cfe083771f68e4fe7bb07",
}
_IMZA = ("eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbmctY2VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9."
         "hrVRgjCwXVvE2OOSpDZ58hR+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRyaMOv5zWSrthlf7G128q"
         "vIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4RlL48eb3lLKqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1"
         "n50cMchmcaXadJhGrOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM2DXzdKX9NmmyqzJ3o/0lkk/N97gfVRLW5hA29yeAw"
         "aCViZNCP8iC9aO0q9fQojoa7NQnAtw==")
_IZINLER = ["LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE", "TEST_OPEN", "TEST_PROTECTED", "CONTROL_AUDIO",
            "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_RECORDING",
            "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_POWER", "READ_APP_STATUS",
            "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST", "READ_NETWORK_STATE", "READ_RUNNING_APPS",
            "READ_TV_CHANNEL_LIST", "WRITE_NOTIFICATION_TOAST", "READ_POWER_STATE", "READ_COUNTRY_INFO"]


def kayit_mesaji(anahtar: str | None, imzali: bool = True) -> dict:
    manifest: dict = {"manifestVersion": 1, "appVersion": "1.1", "permissions": _IZINLER}
    if imzali:
        manifest["signed"] = _IMZALI
        manifest["signatures"] = [{"signatureVersion": 1, "signature": _IMZA}]
    yuk: dict = {"forcePairing": False, "pairingType": "PROMPT", "manifest": manifest}
    if anahtar:
        yuk["client-key"] = anahtar
    return {"type": "register", "id": "kayit", "payload": yuk}


# ---------------------------------------------------------------- en küçük WebSocket istemcisi
def cerceve(metin: str, maske: bytes | None = None) -> bytes:
    """İstemciden giden metin çerçevesi (RFC 6455: istemci çerçeveleri maskelidir)."""
    veri = metin.encode("utf-8")
    maske = maske or os.urandom(4)
    n = len(veri)
    if n < 126:
        bas = bytes([0x81, 0x80 | n])
    elif n < 65536:
        bas = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
    else:
        bas = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
    return bas + maske + bytes(b ^ maske[i % 4] for i, b in enumerate(veri))


class WS:
    PORTLAR = ((3001, True), (3000, False))

    def __init__(self, ip: str, zaman: float = 5, portlar=None):
        self.sock = None
        hatalar = []
        for port, guvenli in portlar or self.PORTLAR:
            try:
                s = socket.create_connection((ip, port), timeout=zaman)
                if guvenli:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE   # TV'nin kendi sertifikası
                    try:
                        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
                    except ssl.SSLError:
                        pass
                    s = ctx.wrap_socket(s, server_hostname=ip)
                anahtar = base64.b64encode(os.urandom(16)).decode()
                s.sendall((f"GET / HTTP/1.1\r\nHost: {ip}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {anahtar}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                yanit = b""
                while b"\r\n\r\n" not in yanit:
                    parca = s.recv(1024)
                    if not parca:
                        raise OSError("bağlantı kapandı")
                    yanit += parca
                if b" 101 " not in yanit.split(b"\r\n", 1)[0]:
                    raise OSError(yanit.split(b"\r\n", 1)[0].decode(errors="replace"))
                self.sock = s
                return
            except (OSError, ssl.SSLError) as e:
                hatalar.append(f"{port}: {e}")
        raise OSError("LG TV'ye bağlanılamadı (" + "; ".join(hatalar) + ")")

    def gonder(self, veri: dict) -> None:
        self.sock.sendall(cerceve(json.dumps(veri, ensure_ascii=False)))

    def _tam(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            p = self.sock.recv(n - len(b))
            if not p:
                raise OSError("bağlantı kapandı")
            b += p
        return b

    def al(self, zaman: float) -> dict:
        self.sock.settimeout(zaman)
        while True:
            b1, b2 = self._tam(2)
            kod, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._tam(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._tam(8))[0]
            maske = self._tam(4) if b2 & 0x80 else None
            veri = self._tam(n)
            if maske:
                veri = bytes(b ^ maske[i % 4] for i, b in enumerate(veri))
            if kod == 0x8:
                raise OSError("TV bağlantıyı kapattı")
            if kod == 0x9:   # ping → pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if kod in (0x1, 0x0):
                return json.loads(veri.decode("utf-8", errors="replace"))

    def kapat(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------- eşleşme + sayfa açma
def _anahtarlar(dosya: Path) -> dict:
    try:
        return json.loads(dosya.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tvde_ac(ip: str, adres: str, anahtar_dosyasi: Path, bekle: float = 60, portlar=None) -> str:
    """LG TV'nin tarayıcısında 'adres'i açar. Gerekirse TV'de izin ister (kumandayla kabul edilir)."""
    anahtarlar = _anahtarlar(anahtar_dosyasi)
    son_hata = ""
    for imzali in (True, False):
        ws = WS(ip, portlar=portlar)
        try:
            ws.gonder(kayit_mesaji(anahtarlar.get(ip), imzali))
            bitis = time.time() + bekle
            anahtar = None
            while time.time() < bitis:
                m = ws.al(max(1.0, bitis - time.time()))
                if m.get("type") == "registered":
                    anahtar = (m.get("payload") or {}).get("client-key")
                    break
                if m.get("type") == "error":
                    son_hata = m.get("error") or "TV kaydı reddetti"
                    break
            if not anahtar:
                if son_hata:
                    continue        # imzasız tanımla bir kez daha dene
                return "TV'de çıkan izin sorusu kabul edilmedi (60 sn içinde kumandayla 'Kabul et'e basın)."
            anahtarlar[ip] = anahtar
            anahtar_dosyasi.parent.mkdir(parents=True, exist_ok=True)
            anahtar_dosyasi.write_text(json.dumps(anahtarlar), encoding="utf-8")
            ws.gonder({"type": "request", "id": "ac", "uri": "ssap://system.launcher/open",
                       "payload": {"target": adres}})
            m = ws.al(10)
            if (m.get("payload") or {}).get("returnValue") is False or m.get("type") == "error":
                ws.gonder({"type": "request", "id": "ac2", "uri": "ssap://system.launcher/launch",
                           "payload": {"id": "com.webos.app.browser", "target": adres}})
                ws.al(10)
            return f"LG TV'de açıldı: {adres}"
        except socket.timeout:
            return "TV'de çıkan izin sorusu kabul edilmedi (60 sn içinde kumandayla 'Kabul et'e basın)."
        finally:
            ws.kapat()
    return f"LG TV kaydı reddetti: {son_hata}"
