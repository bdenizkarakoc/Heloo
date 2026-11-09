"""TV Yansıt hızlı testleri: python -m pytest tv-yansit/tests -q"""
import json
import shutil
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tv_yansit as tv  # noqa: E402


def test_miracast_cozumle():
    assert tv.miracast_cozumle("    Kablosuz Ekran Desteklenir: Hayır (Grafik Sürücüsü: Evet, Wi-Fi Sürücüsü: Hayır)") is False
    assert tv.miracast_cozumle("    Wireless Display Supported: Yes (Graphics Driver: Yes, Wi-Fi Driver: Yes)") is True
    assert tv.miracast_cozumle("There is no wireless interface on the system.") is None


def test_ses_aygiti_sec():
    cikti = '[dshow] "Mikrofon (Realtek)" (audio)\n[dshow] "Stereo Karışımı (Realtek(R) Audio)" (audio)\n'
    assert tv.ses_aygiti_sec(cikti) == "Stereo Karışımı (Realtek(R) Audio)"
    assert tv.ses_aygiti_sec('"Mikrofon" (audio)') is None


def test_jpeg_kareleri():
    t = bytearray(b"cop\xff\xd8AAA\xff\xd9\xff\xd8BB\xff\xd9\xff\xd8yar")
    assert tv.jpeg_kareleri(t) == [b"\xff\xd8AAA\xff\xd9", b"\xff\xd8BB\xff\xd9"]
    assert bytes(t) == b"\xff\xd8yar"


ACIKLAMA = """<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<friendlyName>[TV] Salon</friendlyName><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType><controlURL>/rc</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType><controlURL>/upnp/control/AVTransport1</controlURL></service>
</serviceList></device></root>"""


def test_aciklama_cozumle():
    d = tv.aciklama_cozumle(ACIKLAMA, "http://192.168.1.40:9197/dmr")
    assert d["ad"] == "[TV] Salon"
    assert d["kontrol"] == "http://192.168.1.40:9197/upnp/control/AVTransport1"
    assert d["ip"] == "192.168.1.40"


def test_didl_kacis():
    x = tv.didl("http://1.2.3.4:8765/1234/ekran.ts?a=1&b=2")
    assert "&amp;b=2" in x and "video/mpeg" in x


def test_vdf_gidis_donus_ve_kisayol():
    eski = tv.vdf_yaz({"shortcuts": {"0": {"appid": 0x80001234, "AppName": "Oyun", "Exe": '"C:\\o.exe"',
                                           "LastPlayTime": 5, "tags": {"0": "favorite"}}}})
    assert eski.endswith(b"\x08\x08")
    assert tv.vdf_yaz(tv.vdf_oku(eski)) == eski
    kayit = tv.kisayol_kaydi('"C:\\py\\pythonw.exe"', '"C:\\tv"', '"C:\\tv\\tv_yansit.py" --steam')
    yeni = tv.kisayol_ekle(eski, kayit)
    d = tv.vdf_oku(yeni)["shortcuts"]
    assert d["0"]["AppName"] == "Oyun" and d["1"]["AppName"] == tv.UYGULAMA_ADI
    assert d["1"]["appid"] & 0x80000000
    # ikinci kez eklemek çoğaltmaz
    assert len(tv.vdf_oku(tv.kisayol_ekle(yeni, kayit))["shortcuts"]) == 2
    # boş dosyadan
    assert tv.vdf_oku(tv.kisayol_ekle(b"", kayit))["shortcuts"]["0"]["AppName"] == tv.UYGULAMA_ADI


def test_ts_komutu_ayarlar():
    for ad, ayar in tv.AYARLAR.items():
        c = tv.ts_komutu("ffmpeg", ayar, "h264_nvenc", "Stereo Mix", kaynak="test")
        assert c[-1] == "pipe:1" and "mpegts" in c and "aac" in c
        assert f"scale=-2:{ayar['yukseklik']}:flags={ayar.get('olcek', 'lanczos')},format=yuv420p" in c
        assert "-bf" in c and "-muxpreload" in c
    assert "-an" in tv.ts_komutu("ffmpeg", tv.AYARLAR["uzak"], "libx264", None, kaynak="test")
    m = tv.mjpeg_komutu("ffmpeg", tv.AYARLAR["gecikme"], kaynak="test")
    assert "yuvj420p" in m and "-r" not in m          # küçük kare, kare çoğaltma yok


def test_yeni_kare_istek_yanit():
    y = tv.Yayin("mjpeg")
    assert y.yeni_kare(0, bekle=0.05)[1] is None              # kare yok → boş döner, takılmaz
    with y.kilit:
        y.son_kare, y.kare_no, y.kare_zamani = b"\xff\xd8A\xff\xd9", 5, 1.0
    assert y.yeni_kare(0)[:2] == (5, b"\xff\xd8A\xff\xd9")
    assert y.yeni_kare(5, bekle=0.05)[1] is None              # aynı kareyi tekrar göndermez
    assert y.yeni_kare(900, bekle=0.05)[0] == 5               # sayaç sıfırlandıysa en son kare gelir
    threading.Timer(0.05, lambda: (setattr(y, "kare_no", 6), setattr(y, "son_kare", b"yeni"),
                                   y.kilit.acquire(), y.kilit.notify_all(), y.kilit.release())).start()
    assert y.yeni_kare(5, bekle=2)[:2] == (6, b"yeni")        # yeni kare gelince hemen döner


def test_ayni_agdaki_ip():
    ipler = ["192.168.1.20", "192.168.137.1"]
    assert tv.ayni_agdaki_ip("192.168.137.45", ipler) == "192.168.137.1"
    assert tv.ayni_agdaki_ip("192.168.1.40", ipler) == "192.168.1.20"
    assert tv.ayni_agdaki_ip("10.0.0.5", ipler) == "192.168.1.20"


def test_hotspot_cozumle():
    d = tv.hotspot_cozumle('uyarı\n{"acik":true,"ag":"MASAUSTU 1234","sifre":"abc12345","bant":"TwoPointFourGigahertz","bagli":1}\n')
    assert d["acik"] is True and d["ag"] == "MASAUSTU 1234"
    assert "hata" in tv.hotspot_cozumle("")
    assert "__ISLEM__" in tv.HOTSPOT_PS and tv.HOTSPOT_BANTLARI["uzak"] == "TwoPointFourGigahertz"


def test_yerel_ipler():
    ipler = tv.yerel_ipler()
    assert ipler and all(not ip.startswith("127.") for ip in ipler if ip != "127.0.0.1")


class SahteTV(BaseHTTPRequestHandler):
    eylemler: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        govde = self.rfile.read(int(self.headers["Content-Length"])).decode()
        SahteTV.eylemler.append((self.headers["SOAPAction"], govde))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def test_tv_oynat_soap():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SahteTV)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        hedef = {"kontrol": f"http://127.0.0.1:{srv.server_port}/c", "servis": "urn:schemas-upnp-org:service:AVTransport:1"}
        tv.tv_oynat(hedef, "http://10.0.0.2:8765/1234/ekran.ts")
        eylem = [a.split("#")[1].strip('"') for a, _ in SahteTV.eylemler]
        assert eylem == ["Stop", "SetAVTransportURI", "Play"]
        assert "&lt;DIDL-Lite" in SahteTV.eylemler[1][1]
    finally:
        srv.shutdown()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg yok")
def test_uctan_uca_akislar():
    app = tv.Uygulama(0, kaynak="test")
    app.ayar_adi = "uzak"
    app.lossless_otomatik = False
    srv = tv.ThreadingHTTPServer(("127.0.0.1", 0), tv.sunucu_kur(app))
    app.port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    taban = f"http://127.0.0.1:{app.port}"
    try:
        durum = json.load(urllib.request.urlopen(taban + "/api/durum", timeout=5))
        assert durum["pin"] == app.pin
        assert b"canli.mjpg" in urllib.request.urlopen(f"{taban}/{app.pin}", timeout=5).read()
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{taban}/0000", timeout=5)
        # MJPEG: en az bir tam JPEG kare
        r = urllib.request.urlopen(f"{taban}/{app.pin}/canli.mjpg", timeout=20)
        veri = b""
        while b"\xff\xd9" not in veri:
            veri += r.read(4096)
        r.close()
        assert b"\xff\xd8" in veri and b"Content-Type: image/jpeg" in veri
        # MPEG-TS: 0x47 eşleme baytı
        r = urllib.request.urlopen(f"{taban}/{app.pin}/ekran.ts", timeout=30)
        assert r.headers["transferMode.dlna.org"] == "Streaming"
        ts = r.read(188 * 50)
        r.close()
        assert ts[0] == 0x47 and ts[188] == 0x47
    finally:
        app.durdur()
        srv.shutdown()


# ---------------------------------------------------------------------------- TV'den kumanda
import girdi  # noqa: E402


def test_kumanda_olaylari():
    kayit = girdi.KayitGirdi()
    k = girdi.Kumanda(girdi=kayit)
    n = k.uygula([
        {"t": "ma", "x": 0.5, "y": 2},          # 1'e sıkıştırılır
        {"t": "md", "b": 0}, {"t": "mu", "b": 0},
        {"t": "mw", "d": -120},
        {"t": "kd", "k": 461}, {"t": "ku", "k": 461},   # LG kumanda Geri → Esc
        {"t": "c", "c": "ş"},
        {"t": "kd", "k": 99999}, {"t": "c", "c": "uzun metin"}, {"t": "md", "b": 7}, {"t": "??"}, "bozuk",
    ])
    assert n == 7
    assert kayit.kayit == [("ma", 0.5, 1.0), ("md", 0), ("mu", 0), ("mw", -120),
                           ("kd", 0x1B), ("ku", 0x1B), ("c", "ş")]


def test_kumanda_birak_basili_kalani_birakir():
    kayit = girdi.KayitGirdi()
    k = girdi.Kumanda(girdi=kayit)
    k.uygula([{"t": "kd", "k": 16}, {"t": "md", "b": 2}, {"t": "birak"}])
    assert ("ku", 16) in kayit.kayit and ("mu", 2) in kayit.kayit
    assert not k.basili_tuslar and not k.basili_fare


def test_kumanda_sunucu_izin_ve_pin_engeli():
    app = tv.Uygulama(0, kaynak="test")
    kayit = girdi.KayitGirdi()
    app.kumanda = girdi.Kumanda(girdi=kayit)
    srv = tv.ThreadingHTTPServer(("127.0.0.1", 0), tv.sunucu_kur(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    taban = f"http://127.0.0.1:{srv.server_port}"

    def gonder(yol, veri):
        req = urllib.request.Request(taban + yol, data=json.dumps(veri).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, None

    try:
        sayfa = urllib.request.urlopen(f"{taban}/{app.pin}", timeout=5).read().decode()
        assert f"/{app.pin}/girdi" in sayfa and "__" not in sayfa.split("<script>")[1].split("var g")[0]
        assert gonder(f"/{app.pin}/girdi", [{"t": "kd", "k": 13}])[0] == 403   # kapalıyken izin yok
        assert gonder("/api/ayar", {"kumanda_acik": True})[1]["kumanda_acik"] is True
        kod, cevap = gonder(f"/{app.pin}/girdi", [{"t": "kd", "k": 13}, {"t": "ku", "k": 13}])
        assert kod == 200 and cevap["n"] == 2 and kayit.kayit == [("kd", 13), ("ku", 13)]
        gonder("/api/ayar", {"kumanda_acik": False})
        assert gonder(f"/{app.pin}/girdi", [{"t": "kd", "k": 13}])[0] == 403
    finally:
        srv.shutdown()


def test_pin_tahmini_engellenir():
    app = tv.Uygulama(0, kaynak="test")
    isleyici = tv.sunucu_kur(app)
    isleyici._yerel = lambda self: False      # başka cihazdan geliyormuş gibi
    srv = tv.ThreadingHTTPServer(("127.0.0.1", 0), isleyici)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    taban = f"http://127.0.0.1:{srv.server_port}"

    def kod(yol):
        try:
            return urllib.request.urlopen(taban + yol, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        assert kod("/") == 404                      # panel yalnızca bilgisayardan
        assert kod(f"/{app.pin}") == 200
        yanlis = "0000" if app.pin != "0000" else "1111"
        for _ in range(tv.YANLIS_PIN_SINIRI):
            kod(f"/{yanlis}")
        assert kod(f"/{app.pin}") == 403            # artık doğru PIN de engelli
    finally:
        srv.shutdown()
