"""Bilgisayar sesini yakalama — TV'ye ses gitsin diye.

Öncelik sırası:
  1) WASAPI geri döngü (loopback): Windows'un hoparlöre giden sesini doğrudan alır. Stereo Karışımı ya da ek
     sürücü GEREKMEZ. (ctypes ile COM; yalnızca Windows)
  2) Stereo Karışımı / sanal kablo (ffmpeg dshow)
  3) Test: 440 Hz ton (Windows dışı / --kaynak test)

Çıkış her zaman 48 kHz, 2 kanal, 32 bit float (f32le) parçalar; her parçanın sıra numarası vardır.
Ses çalmazken WASAPI veri vermez; araya sessizlik eklenir ki DLNA akışı ve TV'deki zamanlama kopmasın.
"""
from __future__ import annotations

import array
import ctypes
import os
import subprocess
import sys
import threading
import time
from collections import deque

WINDOWS = os.name == "nt"
ORAN = 48000
KANAL = 2
BAYT_KARE = 4 * KANAL           # f32 stereo bir örnek çifti
PENCERESIZ = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if WINDOWS else 0


def stereo_f32(veri: bytes, kanal: int, bicim: str) -> bytes:
    """Herhangi kanal sayısı (1, 2, 5.1, 7.1) ve f32/s16 → stereo f32. C hızında (memoryview dilimleme)."""
    if bicim == "s16":
        h = array.array("h")
        h.frombytes(veri[: len(veri) - len(veri) % 2])
        f = array.array("f", (v / 32768.0 for v in h))
    else:
        f = array.array("f")
        f.frombytes(veri[: len(veri) - len(veri) % 4])
    if kanal == 2:
        return f.tobytes()
    n = len(f) // kanal
    cikis = array.array("f", bytes(n * 2 * 4))
    if kanal == 1:
        cikis[0::2] = f[:n]
        cikis[1::2] = f[:n]
    else:
        cikis[0::2] = f[0:n * kanal:kanal]
        cikis[1::2] = f[1:n * kanal:kanal]
    return cikis.tobytes()


class SesYakala:
    """Tek yakalayıcı, birçok okuyucu (TV tarayıcısı, DLNA kodlayıcısı)."""

    def __init__(self, ffmpeg: str | None = None, dshow_aygit: str | None = None, test: bool = False):
        self.ffmpeg = ffmpeg
        self.dshow_aygit = dshow_aygit
        self.test = test
        self.kilit = threading.Condition()
        self.parcalar: deque[tuple[int, bytes]] = deque(maxlen=400)   # ~4 sn
        self.no = 0
        self.calisiyor = False
        self.oran = ORAN          # gerçek örnekleme hızı (WASAPI aygıtınınki; 44100 olabilir)
        self.kaynak = ""          # "WASAPI" | "Stereo Karışımı: …" | "test"
        self.hata = ""
        self.son_istek = 0.0
        self._son_veri = 0.0
        self._surec: subprocess.Popen | None = None

    # ------------------------------------------------------------- yayınlama
    def _ekle(self, veri: bytes) -> None:
        if not veri:
            return
        with self.kilit:
            self.no += 1
            self.parcalar.append((self.no, veri))
            self._son_veri = time.time()
            self.kilit.notify_all()

    def _sessizlik_doldur(self, simdi: float) -> None:
        """Veri gelmeyen süreyi sessizlikle doldur (en çok 100 ms'lik parçalar)."""
        bosluk = simdi - self._son_veri
        if self._son_veri and bosluk > 0.03:
            kare = int(min(bosluk, 0.1) * self.oran)
            self._ekle(bytes(kare * BAYT_KARE))
            self._son_veri = simdi

    def parcalar_sonra(self, gorulen: int, bekle: float = 1.0, en_az: int = 1) -> tuple[int, bytes]:
        """'gorulen'den sonraki bütün parçalar (birleşik). Yeni parça yoksa 'bekle' sn bekler."""
        self.son_istek = time.time()
        with self.kilit:
            if gorulen <= 0:                         # yeni dinleyici: birikmiş eski sesi değil, şimdiyi çal
                gorulen = max(0, self.no - 1)
            if gorulen > self.no or (self.parcalar and gorulen < self.parcalar[0][0] - 1):
                gorulen = max(0, self.no - 2)        # çok gerideyse: yalnız en yeniler (gecikme birikmesin)
            bitis = time.time() + bekle
            while self.no - gorulen < en_az:
                kalan = bitis - time.time()
                if kalan <= 0 or not self.kilit.wait(kalan):
                    break
            veri = b"".join(v for n, v in self.parcalar if n > gorulen)
            return self.no, veri

    # ------------------------------------------------------------- başlat / durdur
    def baslat(self) -> bool:
        if self.calisiyor:
            return True
        self.calisiyor = True
        self.hata = ""
        self._son_veri = 0.0
        hazir = threading.Event()
        threading.Thread(target=self._calis, args=(hazir,), daemon=True).start()
        hazir.wait(5)
        return self.calisiyor

    def durdur(self) -> None:
        self.calisiyor = False
        p, self._surec = self._surec, None
        if p and p.poll() is None:
            p.terminate()

    def _calis(self, hazir: threading.Event) -> None:
        try:
            if WINDOWS and not self.test:
                try:
                    self.kaynak = "Windows ses çıkışı (WASAPI)"
                    self._wasapi(hazir)
                    return
                except Exception as e:  # noqa: BLE001 — sürücü/COM hatası: yedeğe geç
                    self.hata = f"WASAPI: {e}"
                    if not self.calisiyor:
                        return
            if self.ffmpeg and (self.test or self.dshow_aygit):
                self._ffmpeg(hazir)
                return
            self.kaynak = ""
            self.hata = self.hata or "Ses yakalanamadı"
            self.calisiyor = False
        finally:
            hazir.set()

    def _ffmpeg(self, hazir: threading.Event) -> None:
        self.oran = ORAN
        if self.test:
            self.kaynak = "test"
            giris = ["-re", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={ORAN}"]
        else:
            self.kaynak = f"Stereo Karışımı: {self.dshow_aygit}"
            giris = ["-f", "dshow", "-audio_buffer_size", "20", "-i", f"audio={self.dshow_aygit}"]
        komut = ([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer"] + giris +
                 ["-ac", "2", "-ar", str(ORAN), "-f", "f32le", "-flush_packets", "1", "pipe:1"])
        p = self._surec = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           stdin=subprocess.DEVNULL, creationflags=PENCERESIZ, bufsize=0)
        hazir.set()
        parca = ORAN // 100 * BAYT_KARE      # 10 ms
        artik = b""
        while self.calisiyor:
            veri = p.stdout.read(parca)
            if not veri:
                break
            veri = artik + veri
            tam = len(veri) - len(veri) % BAYT_KARE
            artik = veri[tam:]
            self._ekle(veri[:tam])
        self.calisiyor = False

    # ------------------------------------------------------------- WASAPI geri döngü (ctypes COM)
    def _wasapi(self, hazir: threading.Event) -> None:
        ole32 = ctypes.windll.ole32

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                        ("Data4", ctypes.c_ubyte * 8)]

        def guid(metin: str) -> GUID:
            g = GUID()
            hr = ole32.CLSIDFromString(ctypes.c_wchar_p(metin), ctypes.byref(g))
            if hr:
                raise OSError(f"GUID {metin}: {hr & 0xFFFFFFFF:#x}")
            return g

        def yontem(nesne: ctypes.c_void_p, sira: int, *argtypes):
            vtablo = ctypes.cast(nesne, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
            fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtablo[sira])

            def cagir(*a):
                hr = fn(nesne, *a)
                if hr < 0:
                    raise OSError(f"COM hatası {hr & 0xFFFFFFFF:#x}")
                return hr
            return cagir

        def birak(nesne) -> None:
            if nesne and nesne.value:
                yontem(nesne, 2)()

        ole32.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
        numarator, aygit, istemci, yakalayici = (ctypes.c_void_p() for _ in range(4))
        bicim_ptr = ctypes.c_void_p()
        try:
            hr = ole32.CoCreateInstance(ctypes.byref(guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, 23,
                                        ctypes.byref(guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")),
                                        ctypes.byref(numarator))
            if hr:
                raise OSError(f"MMDeviceEnumerator {hr & 0xFFFFFFFF:#x}")
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eConsole=0)
            yontem(numarator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                0, 0, ctypes.byref(aygit))
            # IMMDevice::Activate(IID_IAudioClient, CLSCTX_ALL, NULL, &istemci)
            yontem(aygit, 3, ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                   ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(guid("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")), 23, None, ctypes.byref(istemci))
            # IAudioClient::GetMixFormat
            yontem(istemci, 8, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(bicim_ptr))
            ham = ctypes.string_at(bicim_ptr.value, 40)
            etiket = int.from_bytes(ham[0:2], "little")
            kanal = int.from_bytes(ham[2:4], "little")
            oran = int.from_bytes(ham[4:8], "little")
            blok = int.from_bytes(ham[12:14], "little")
            bit = int.from_bytes(ham[14:16], "little")
            alt = int.from_bytes(ham[24:28], "little") if etiket == 0xFFFE else etiket
            if alt == 3 and bit == 32:
                bicim = "f32"
            elif alt == 1 and bit == 16:
                bicim = "s16"
            else:
                raise OSError(f"Desteklenmeyen ses biçimi ({alt}, {bit} bit)")
            # Initialize(SHARED, LOOPBACK, 200 ms, 0, bicim, NULL)
            yontem(istemci, 3, ctypes.c_int, ctypes.c_uint32, ctypes.c_longlong, ctypes.c_longlong,
                   ctypes.c_void_p, ctypes.c_void_p)(0, 0x00020000, 2_000_000, 0, bicim_ptr, None)
            # GetService(IID_IAudioCaptureClient)
            yontem(istemci, 14, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(guid("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")), ctypes.byref(yakalayici))
            paket_boyu = yontem(yakalayici, 5, ctypes.POINTER(ctypes.c_uint32))
            al = yontem(yakalayici, 3, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
                        ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p)
            serbest = yontem(yakalayici, 4, ctypes.c_uint32)
            yontem(istemci, 10)()   # Start
            self._son_veri = time.time()
            hazir.set()
            self.oran = oran
            n, veri_ptr, kare, bayrak = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_uint32(), ctypes.c_uint32()
            while self.calisiyor:
                time.sleep(0.005)
                while True:
                    paket_boyu(ctypes.byref(n))
                    if not n.value:
                        break
                    al(ctypes.byref(veri_ptr), ctypes.byref(kare), ctypes.byref(bayrak), None, None)
                    boy = kare.value * blok
                    veri = bytes(boy) if bayrak.value & 0x2 else ctypes.string_at(veri_ptr.value, boy)
                    serbest(kare.value)
                    self._ekle(stereo_f32(veri, kanal, bicim))
                self._sessizlik_doldur(time.time())
            yontem(istemci, 11)()   # Stop
        finally:
            for nesne in (yakalayici, istemci, aygit, numarator):
                try:
                    birak(nesne)
                except OSError:
                    pass
            if bicim_ptr.value:
                ole32.CoTaskMemFree(bicim_ptr)
            ole32.CoUninitialize()


if __name__ == "__main__":   # elle deneme: python ses.py → 3 sn yakalar, kaç bayt geldiğini yazar
    y = SesYakala(test="--test" in sys.argv, ffmpeg="ffmpeg")
    print("başladı:", y.baslat(), y.kaynak, y.hata)
    time.sleep(3)
    print("parça:", y.no, "bayt:", sum(len(v) for _, v in y.parcalar))
    y.durdur()
