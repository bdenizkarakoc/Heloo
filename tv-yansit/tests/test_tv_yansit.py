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
        assert f"scale=-2:{ayar['yukseklik']}:flags=lanczos,format=yuv420p" in c
    assert "-an" in tv.ts_komutu("ffmpeg", tv.AYARLAR["uzak"], "libx264", None, kaynak="test")


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
