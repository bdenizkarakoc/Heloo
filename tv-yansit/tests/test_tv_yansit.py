"""TV Yansıt hızlı testleri: python -m pytest tv-yansit/tests -q"""
import json
import time
import socket
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
    p = tv.ts_komutu("ffmpeg", tv.AYARLAR["gecikme"], "libx264", "pipe", kaynak="test", ses_oran=44100)
    assert "pipe:0" in p and "44100" in p and "f32le" in p
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
        assert app.kumanda_acik is True                                          # varsayılan: açık
        assert gonder("/api/ayar", {"kumanda_acik": False})[1]["kumanda_acik"] is False
        assert gonder(f"/{app.pin}/girdi", [{"t": "kd", "k": 13}])[0] == 403   # kapalıyken izin yok
        kayit.kayit.clear()
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
        sayfa = urllib.request.urlopen(f"{taban}/", timeout=5).read().decode()
        assert "4 haneli kodu" in sayfa and "Kapat" not in sayfa   # TV: panel değil, kod giriş sayfası
        assert kod(f"/{app.pin}") == 200
        yanlis = "0000" if app.pin != "0000" else "1111"
        for _ in range(tv.YANLIS_PIN_SINIRI):
            kod(f"/{yanlis}")
        assert kod(f"/{app.pin}") == 403            # artık doğru PIN de engelli
    finally:
        srv.shutdown()


def test_kurulum_parcalari():
    kok = Path(tv.__file__).resolve().parent
    ico = (kok / "tv-yansit.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00"                  # geçerli ICO başlığı
    kur = (kok / "kur.ps1").read_bytes()
    assert kur.startswith(b"\xef\xbb\xbf")                   # PowerShell 5.1 Türkçe için UTF-8 BOM
    assert kur.count(b"\r\n") == kur.count(b"\n")              # Windows satır sonu (CRLF)
    assert not kur.startswith(b"\xef\xbb\xbf" * 2)           # çift BOM: ilk satır yorum sayılmaz, hata verir
    for dosya in ("tv_yansit.py", "girdi.py", "ses.py", "sertifika.py", "lg.py", "panel.html", "tv.html", "tv-yansit.ico"):
        assert dosya.encode() in kur and (kok / dosya).exists()
    assert isinstance(tv.kurulum_ayari(), dict)


def test_acik_kopya_yoksa_false():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        bos_port = s.getsockname()[1]
    assert tv.acik_kopya_paneli(bos_port) is False


def test_baska_uygulamanin_portunu_kullanmaz(monkeypatch):
    """Reels Fabrikası 127.0.0.1:<port>'ta açıkken TV Yansıt o portu almamalı, paneli de oraya açmamalı."""
    class Baska(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            govde = b"<html>Reels Fabrikasi</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)

    baska = ThreadingHTTPServer(("127.0.0.1", 0), Baska)
    threading.Thread(target=baska.serve_forever, daemon=True).start()
    acilan = []
    monkeypatch.setattr(tv.webbrowser, "open", acilan.append)
    port = baska.server_port
    app = tv.Uygulama(port, kaynak="test")
    srv = None
    try:
        assert tv.port_dolu(port) and not tv.tv_yansit_portu(port)
        assert tv.acik_kopya_paneli(port) is False and acilan == []      # Reels'i "açık kopya" sanmaz
        srv = tv.sunucu_baslat(app)
        assert app.port != port                                          # dolu portu atladı
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        assert tv.tv_yansit_portu(app.port)
        assert tv.acik_kopya_paneli(port) is True
        assert acilan == [f"http://127.0.0.1:{app.port}/"]               # kendi panelini açar
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        baska.shutdown()


def test_ses_yakala_test_tonu_ve_istek_yanit():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg yok")
    import ses
    y = ses.SesYakala(ffmpeg="ffmpeg", test=True)
    try:
        assert y.baslat() and y.kaynak == "test"
        no, veri = y.parcalar_sonra(0, bekle=2)
        assert no >= 1 and len(veri) % 8 == 0                 # stereo f32 kareler
        no2, veri2 = y.parcalar_sonra(no, bekle=2)
        assert no2 > no and veri2                               # yalnızca yeni parçalar
        no3, _ = y.parcalar_sonra(no2 + 10_000, bekle=0.1)      # sayaç ileride: sıfırlanır, takılmaz
        assert no3 >= no2
    finally:
        y.durdur()


def test_stereo_f32_donusum():
    import array
    import ses
    f = array.array("f", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]).tobytes()     # 3 kanal, 2 kare
    out = array.array("f"); out.frombytes(ses.stereo_f32(f, 3, "f32"))
    assert [round(v, 2) for v in out] == [0.1, 0.2, 0.4, 0.5]
    mono = array.array("f", [0.5, -0.5]).tobytes()
    out = array.array("f"); out.frombytes(ses.stereo_f32(mono, 1, "f32"))
    assert [round(v, 2) for v in out] == [0.5, 0.5, -0.5, -0.5]
    s16 = array.array("h", [16384, -16384]).tobytes()
    out = array.array("f"); out.frombytes(ses.stereo_f32(s16, 2, "s16"))
    assert [round(v, 2) for v in out] == [0.5, -0.5]


def test_ayni_portta_http_ve_https(monkeypatch, tmp_path):
    """LG webOS gibi tarayıcılar adresi https:// ile açar: aynı port ikisine de yanıt vermeli."""
    import ssl
    monkeypatch.setattr(tv, "VERI", tmp_path)
    app = tv.Uygulama(tv.VARSAYILAN_PORT + 300, kaynak="test")
    srv = tv.sunucu_baslat(app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert srv.ssl_ctx is not None and (tmp_path / "sertifika.pem").exists()
        duz = urllib.request.urlopen(f"http://127.0.0.1:{app.port}/{app.pin}", timeout=10).read()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE               # kendinden imzalı (TV'de "Devam et")
        guvenli = urllib.request.urlopen(f"https://127.0.0.1:{app.port}/{app.pin}", timeout=10, context=ctx).read()
        assert duz == guvenli and b"canli.mjpg" in guvenli
        # sertifika ikinci açılışta yeniden üretilmez (TV'nin "Devam et" kararı geçerli kalsın)
        ilk = (tmp_path / "sertifika.pem").read_bytes()
        assert tv.sertifika.ssl_baglami(tmp_path, []) is not None
        assert (tmp_path / "sertifika.pem").read_bytes() == ilk
    finally:
        srv.shutdown()
        srv.server_close()


def test_iki_istek_ayni_kareyi_almaz():
    y = tv.Yayin("mjpeg")
    gonderilen: dict = {}
    with y.kilit:
        y.son_kare, y.kare_no = b"k1", 1
    assert y.yeni_kare(0, istemci="tv", gonderilen=gonderilen)[0] == 1
    # aynı TV'nin ikinci isteği (n=0 ile) aynı kareyi almaz, yenisini bekler
    assert y.yeni_kare(0, bekle=0.05, istemci="tv", gonderilen=gonderilen)[1] is None
    assert y.yeni_kare(0, bekle=0.05, istemci="baska-tv", gonderilen=gonderilen)[0] == 1   # başka TV alır
    def yeni():
        with y.kilit:
            y.son_kare, y.kare_no = b"k2", 2
            y.kilit.notify_all()
    threading.Timer(0.05, yeni).start()
    assert y.yeni_kare(0, bekle=2, istemci="tv", gonderilen=gonderilen)[:2] == (2, b"k2")


def test_kod_kalici_ve_yenilenir(monkeypatch, tmp_path):
    monkeypatch.setattr(tv, "VERI", tmp_path)
    ilk = tv.kalici_pin()
    assert len(ilk) == 4 and ilk.isdigit()
    assert tv.kalici_pin() == ilk                       # yeniden açılışta aynı kod (TV hatırlar)
    for _ in range(5):
        yeni = tv.kalici_pin(yeni=True)
        if yeni != ilk:
            break
    assert yeni != ilk and tv.kalici_pin() == yeni


def test_lg_tvde_ac_sahte_tv(tmp_path):
    """Sahte LG TV (WebSocket): izin kaydı → anahtar saklanır → sayfa açma isteği doğru adresle gelir."""
    import base64, hashlib, socket as sk, struct
    import lg
    sunucu = sk.socket()
    sunucu.bind(("127.0.0.1", 0))
    sunucu.listen(1)
    port = sunucu.getsockname()[1]
    gelen = []

    def oku(c):
        b1, b2 = c.recv(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", c.recv(2))[0]
        maske = c.recv(4)
        veri = b""
        while len(veri) < n:
            veri += c.recv(n - len(veri))
        return json.loads(bytes(b ^ maske[i % 4] for i, b in enumerate(veri)))

    def yaz(c, d):
        v = json.dumps(d).encode()
        c.sendall(bytes([0x81, len(v)]) + v if len(v) < 126 else bytes([0x81, 126]) + struct.pack(">H", len(v)) + v)

    def tv_taklidi():
        c, _ = sunucu.accept()
        istek = b""
        while b"\r\n\r\n" not in istek:
            istek += c.recv(1024)
        anahtar = [l.split(b": ")[1] for l in istek.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
        kabul = base64.b64encode(hashlib.sha1(anahtar + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Accept: " + kabul + b"\r\n\r\n")
        kayit = oku(c)
        gelen.append(kayit)
        yaz(c, {"type": "response", "id": "kayit", "payload": {"pairingType": "PROMPT"}})
        yaz(c, {"type": "registered", "id": "kayit", "payload": {"client-key": "ANAHTAR123"}})
        gelen.append(oku(c))
        yaz(c, {"type": "response", "id": "ac", "payload": {"returnValue": True}})
        c.close()

    threading.Thread(target=tv_taklidi, daemon=True).start()
    dosya = tmp_path / "lg.json"
    sonuc = lg.tvde_ac("127.0.0.1", "http://192.168.1.16:8780/2391", dosya, bekle=5, portlar=((port, False),))
    sunucu.close()
    assert "açıldı" in sonuc
    assert gelen[0]["type"] == "register" and gelen[0]["payload"]["pairingType"] == "PROMPT"
    assert gelen[1]["uri"] == "ssap://system.launcher/open"
    assert gelen[1]["payload"]["target"] == "http://192.168.1.16:8780/2391"
    assert json.loads(dosya.read_text())["127.0.0.1"] == "ANAHTAR123"   # ikinci sefer izin sorulmaz
    assert lg.kayit_mesaji("ANAHTAR123")["payload"]["client-key"] == "ANAHTAR123"


def test_tv_durumu_ve_otomatik_hafif_ayar(monkeypatch, tmp_path):
    monkeypatch.setattr(tv, "VERI", tmp_path)
    app = tv.Uygulama(0, kaynak="test")
    monkeypatch.setattr(app, "mjpeg_baslat", lambda: None)
    srv = tv.ThreadingHTTPServer(("127.0.0.1", 0), tv.sunucu_kur(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def bildir(d):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/{app.pin}/tvdurum",
                                         data=json.dumps(d).encode(), method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        bildir({"fps": 58, "ms": 12, "ses": "kilitli", "sesKB": 0})
        d = app.durum()["tv"]
        assert d["fps"] == 58 and d["ses"] == "kilitli"
        assert app.ayar_adi == "gecikme"
        for _ in range(3):                       # TV yavaş: 3 bildirim üst üste < 40 fps
            bildir({"fps": 25, "ms": 40, "ses": "çalıyor"})
        assert app.ayar_adi == "ultra" and "Ultra" in app.mesaj
        app.ayar_adi, app.otomatik_kalite = "gecikme", False
        for _ in range(3):
            bildir({"fps": 25})
        assert app.ayar_adi == "gecikme"         # otomatik kapalıysa dokunmaz
    finally:
        srv.shutdown()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg yok")
def test_video_flv_ayristirma_ve_akis(monkeypatch, tmp_path):
    """Gerçek ffmpeg çıktısı: önce yapılandırma (avcC), sonra anahtar kare, sonra ara kareler; TV'ye itilir."""
    import struct
    monkeypatch.setattr(tv, "VERI", tmp_path)
    app = tv.Uygulama(tv.VARSAYILAN_PORT + 400, kaynak="test")
    app.lossless_otomatik = False
    srv = tv.sunucu_baslat(app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{app.port}/{app.pin}/video", timeout=20)
        tampon, kayit, bitis = b"", [], time.time() + 3
        while time.time() < bitis and len(kayit) < 20:
            tampon += r.read1(65536)
            while len(tampon) >= 11:
                tur, n, no, _ = struct.unpack(">BIIH", tampon[:11])
                if len(tampon) < 11 + n:
                    break
                kayit.append((tur, tampon[11:11 + n]))
                tampon = tampon[11 + n:]
        r.close()
        assert kayit[0][0] == 0 and kayit[0][1][0] == 1            # avcC (configurationVersion 1)
        assert kayit[1][0] == 1                                     # ilk kare anahtar kare
        assert any(t == 2 for t, _ in kayit)                        # ara kareler de geliyor
        assert int.from_bytes(kayit[1][1][:4], "big") > 0           # AVCC (uzunluk önekli NAL)
    finally:
        app.durdur()
        srv.shutdown()
        srv.server_close()


def test_video_abone_geride_kalinca_anahtar_kareye_atlar():
    a = tv.VideoAbone()
    a.ekle((1, 0, b"ara", 0))                    # anahtar kare beklerken ara kare atılır
    assert a.kuyruk == []
    a.ekle((2, 1, b"anahtar", 0))
    assert a.kuyruk[0] == ("cfg",) and a.kuyruk[1][0] == 2
    for i in range(3, 3 + tv.VideoAbone.SINIR):  # TV okumuyor: kuyruk dolar
        a.ekle((i, 0, b"x", 0))
    assert a.anahtar_bekle and a.kuyruk == []    # boşaltıldı, sonraki anahtar kare bekleniyor (gecikme birikmez)
    kayit = tv.video_kayitlari([("cfg",), (7, 1, b"abc", 10.0)], b"\x01cfg", simdi=10.05)
    assert kayit[:1] == b"\x00" and kayit[11:15] == b"\x01cfg"
    assert kayit[15:16] == b"\x01" and int.from_bytes(kayit[24:26], "big") == 50
