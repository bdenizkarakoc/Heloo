"""TV'den kumanda: TV'ye bağlı klavye, fare, oyun kolu ve TV kumandası → bilgisayar.

TV tarayıcısındaki sayfa (tv.html) tuş/fare/oyun kolu olaylarını toplu hâlde gönderir; burada Windows'a gerçek
girdi olarak verilir (SendInput). Oyun kolu: ViGEmBus + `vgamepad` kuruluysa bilgisayarda gerçek bir Xbox 360
kolu belirir (oyunlar ve Steam doğrudan tanır); yoksa sayfa kolu fare/klavyeye çevirir.

Olay biçimi (JSON listesi):
  {"t":"ma","x":0..1,"y":0..1}   fare mutlak konum (yansıtılan ekrana göre)
  {"t":"mr","dx":px,"dy":px}      fare göreli hareket
  {"t":"md"|"mu","b":0|1|2}       fare tuşu bas/bırak (sol/orta/sağ)
  {"t":"mw","d":±120}             tekerlek
  {"t":"kd"|"ku","k":keyCode}     tuş bas/bırak (tarayıcı keyCode = Windows sanal tuş kodu)
  {"t":"c","c":"ş"}               yazı karakteri (Türkçe dahil, klavye düzeninden bağımsız)
  {"t":"pad","i":0,"b":[17 sayı],"a":[4 sayı]}   oyun kolu durumu (W3C standart düzen)
  {"t":"birak"}                   basılı kalan her şeyi bırak (sayfa kapanırken)
"""
from __future__ import annotations

import ctypes
import os
import threading

WINDOWS = os.name == "nt"

# TV kumandalarının tarayıcıdaki özel tuş kodları → Windows sanal tuşları
TV_TUSLARI = {
    461: 0x1B, 10009: 0x1B,            # Geri (LG webOS, Samsung Tizen) → Esc
    10252: 0xB3, 415: 0xB3, 19: 0xB3,  # Oynat/Duraklat → medya oynat/duraklat
    413: 0xB2,                         # Durdur
    417: 0xB0, 412: 0xB1,              # İleri / geri sar → sonraki / önceki parça
}
GENIS_TUSLAR = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90,
                0xA3, 0xA5, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}
EN_FAZLA_OLAY = 300


def sanal_tus(kod) -> int | None:
    try:
        kod = int(kod)
    except (TypeError, ValueError):
        return None
    kod = TV_TUSLARI.get(kod, kod)
    return kod if 0 < kod < 0xFF else None


# ---------------------------------------------------------------------------- Windows SendInput

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class _GIRDI_BIRLIK(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _GIRDI_BIRLIK)]


MOVE, LDOWN, LUP, RDOWN, RUP, MDOWN, MUP, WHEEL, VIRTUALDESK, ABSOLUTE = (
    0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0800, 0x4000, 0x8000)
K_EXT, K_UP, K_UNICODE = 0x0001, 0x0002, 0x0004
FARE_TUSLARI = {0: (LDOWN, LUP), 1: (MDOWN, MUP), 2: (RDOWN, RUP)}


class WindowsGirdi:
    """Girdileri Windows'a verir. Yönetici olarak çalışan pencerelere (UAC) Windows izin vermez."""

    def __init__(self, tum_ekranlar: bool = False):
        self.u = ctypes.windll.user32
        self.tum = tum_ekranlar

    def _gonder(self, *girdiler: INPUT) -> None:
        dizi = (INPUT * len(girdiler))(*girdiler)
        self.u.SendInput(len(girdiler), dizi, ctypes.sizeof(INPUT))

    def _fare(self, bayrak: int, dx: int = 0, dy: int = 0, veri: int = 0) -> INPUT:
        return INPUT(type=0, u=_GIRDI_BIRLIK(mi=MOUSEINPUT(dx, dy, veri & 0xFFFFFFFF, bayrak, 0, 0)))

    def fare_mutlak(self, x: float, y: float) -> None:
        b = MOVE | ABSOLUTE | (VIRTUALDESK if self.tum else 0)
        self._gonder(self._fare(b, round(x * 65535), round(y * 65535)))

    def fare_goreli(self, dx: int, dy: int) -> None:
        self._gonder(self._fare(MOVE, dx, dy))

    def fare_tus(self, b: int, bas: bool) -> None:
        self._gonder(self._fare(FARE_TUSLARI[b][0 if bas else 1]))

    def tekerlek(self, d: int) -> None:
        self._gonder(self._fare(WHEEL, veri=d))

    def tus(self, vk: int, bas: bool) -> None:
        tarama = self.u.MapVirtualKeyW(vk, 0)
        b = (K_EXT if vk in GENIS_TUSLAR else 0) | (0 if bas else K_UP)
        self._gonder(INPUT(type=1, u=_GIRDI_BIRLIK(ki=KEYBDINPUT(vk, tarama, b, 0, 0))))

    def karakter(self, c: str) -> None:
        birimler = c.encode("utf-16-le")
        girdiler = []
        for i in range(0, len(birimler), 2):
            kod = int.from_bytes(birimler[i:i + 2], "little")
            for bayrak in (K_UNICODE, K_UNICODE | K_UP):
                girdiler.append(INPUT(type=1, u=_GIRDI_BIRLIK(ki=KEYBDINPUT(0, kod, bayrak, 0, 0))))
        self._gonder(*girdiler)


class KayitGirdi:
    """Windows dışı / test: olayları yalnızca kaydeder."""

    def __init__(self, tum_ekranlar: bool = False):
        self.kayit: list[tuple] = []

    def fare_mutlak(self, x, y): self.kayit.append(("ma", round(x, 3), round(y, 3)))
    def fare_goreli(self, dx, dy): self.kayit.append(("mr", dx, dy))
    def fare_tus(self, b, bas): self.kayit.append(("md" if bas else "mu", b))
    def tekerlek(self, d): self.kayit.append(("mw", d))
    def tus(self, vk, bas): self.kayit.append(("kd" if bas else "ku", vk))
    def karakter(self, c): self.kayit.append(("c", c))


# ---------------------------------------------------------------------------- sanal Xbox kolu

# W3C standart oyun kolu düğme sırası → XUSB düğme adları
PAD_DUGMELERI = ["A", "B", "X", "Y", "LEFT_SHOULDER", "RIGHT_SHOULDER", None, None, "BACK", "START",
                 "LEFT_THUMB", "RIGHT_THUMB", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "GUIDE"]


def vgamepad_var() -> bool:
    if not WINDOWS:
        return False
    try:
        import vgamepad  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — paket ya da ViGEmBus sürücüsü yok
        return False


class SanalKollar:
    """TV'deki her oyun kolu için bilgisayarda bir sanal Xbox 360 kolu (ViGEmBus + vgamepad)."""

    def __init__(self):
        import vgamepad as vg
        self.vg = vg
        self.kollar: dict[int, object] = {}

    def guncelle(self, i: int, dugmeler: list, eksenler: list) -> None:
        vg = self.vg
        kol = self.kollar.get(i)
        if kol is None:
            kol = self.kollar[i] = vg.VX360Gamepad()
        for n, ad in enumerate(PAD_DUGMELERI):
            if ad is None or n >= len(dugmeler):
                continue
            dugme = getattr(vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{ad}")
            (kol.press_button if float(dugmeler[n]) > 0.5 else kol.release_button)(button=dugme)
        tetik = lambda n: max(0.0, min(1.0, float(dugmeler[n]))) if n < len(dugmeler) else 0.0  # noqa: E731
        kol.left_trigger_float(value_float=tetik(6))
        kol.right_trigger_float(value_float=tetik(7))
        e = [max(-1.0, min(1.0, float(v))) for v in (list(eksenler) + [0, 0, 0, 0])[:4]]
        kol.left_joystick_float(x_value_float=e[0], y_value_float=-e[1])  # tarayıcıda yukarı = -1
        kol.right_joystick_float(x_value_float=e[2], y_value_float=-e[3])
        kol.update()

    def birak(self) -> None:
        for kol in self.kollar.values():
            kol.reset()
            kol.update()


# ---------------------------------------------------------------------------- olayları uygula

class Kumanda:
    def __init__(self, tum_ekranlar: bool = False, girdi=None):
        self.girdi = girdi or (WindowsGirdi(tum_ekranlar) if WINDOWS else KayitGirdi())
        self.kilit = threading.Lock()
        self.basili_tuslar: set[int] = set()
        self.basili_fare: set[int] = set()
        self.kollar: SanalKollar | None = None
        self.sanal_kol = vgamepad_var()

    def uygula(self, olaylar: list) -> int:
        """Olayları sırayla uygular; uygulanan olay sayısını döndürür. Bozuk olayları atlar."""
        if not isinstance(olaylar, list):
            return 0
        n = 0
        with self.kilit:
            for o in olaylar[:EN_FAZLA_OLAY]:
                try:
                    n += self._tek(o)
                except (KeyError, TypeError, ValueError, OSError):
                    continue
        return n

    def _tek(self, o: dict) -> int:
        t = o.get("t") if isinstance(o, dict) else None
        g = self.girdi
        if t == "ma":
            g.fare_mutlak(min(1.0, max(0.0, float(o["x"]))), min(1.0, max(0.0, float(o["y"]))))
        elif t == "mr":
            g.fare_goreli(max(-2000, min(2000, int(o["dx"]))), max(-2000, min(2000, int(o["dy"]))))
        elif t in ("md", "mu"):
            b = int(o["b"])
            if b not in FARE_TUSLARI:
                return 0
            (self.basili_fare.add if t == "md" else self.basili_fare.discard)(b)
            g.fare_tus(b, t == "md")
        elif t == "mw":
            g.tekerlek(max(-1200, min(1200, int(o["d"]))))
        elif t in ("kd", "ku"):
            vk = sanal_tus(o["k"])
            if vk is None:
                return 0
            (self.basili_tuslar.add if t == "kd" else self.basili_tuslar.discard)(vk)
            g.tus(vk, t == "kd")
        elif t == "c":
            c = str(o["c"])
            if not 1 <= len(c) <= 2 or not c.isprintable():
                return 0
            g.karakter(c)
        elif t == "pad":
            if not self.sanal_kol:
                return 0
            if self.kollar is None:
                self.kollar = SanalKollar()
            self.kollar.guncelle(int(o.get("i", 0)) % 4, list(o.get("b", []))[:17], list(o.get("a", []))[:4])
        elif t == "birak":
            self.birak_hepsi()
        else:
            return 0
        return 1

    def birak_hepsi(self) -> None:
        for vk in list(self.basili_tuslar):
            self.girdi.tus(vk, False)
        for b in list(self.basili_fare):
            self.girdi.fare_tus(b, False)
        self.basili_tuslar.clear()
        self.basili_fare.clear()
        if self.kollar:
            self.kollar.birak()
