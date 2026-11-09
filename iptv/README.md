# Heloo TV — NVIDIA RTX ile 4K, düşük gecikmeli IPTV oynatıcı

**Canlı TV**, **Filmler** ve **Diziler** sekmeleri olan, Windows için masaüstü IPTV uygulaması. Her yayın
**NVIDIA RTX Video Super Resolution (VSR)** ile 4K'ya (3840×2160) yükseltilir, sıkıştırma kusurları temizlenir;
canlı yayın **en düşük gecikmeyle** oynatılır.

> Heloo TV bir **oynatıcıdır**, içerik sağlamaz. Yalnızca izleme hakkınız olan IPTV aboneliğinizi (Xtream Codes),
> M3U listenizi ya da ücretsiz/yasal yayınları ekleyin.

## Özellikler

| | |
|---|---|
| **Canlı TV** | Kategoriler, kanal logoları, şimdi/sonra yayın akışı (EPG) ve ilerleme çubuğu, ⭐ favoriler, 🕘 son izlenenler, numarayla kanal açma, önceki kanala dönüş, ⟲ geri izleme (catch-up), zaman kaydırma (duraklat / geri sar / canlıya dön) |
| **Filmler** | Afiş ızgarası, puan/yıl, konu/oyuncu/süre ayrıntıları (Xtream), kaldığın yerden devam, favoriler |
| **Diziler** | Sezon/bölüm listesi, izlenen ✓ ve yarım ◔ işaretleri, kaldığın bölüm, sonraki bölüme otomatik geçiş |
| **Favoriler** | Kanal/film/dizi favorileri, "İzlemeye devam et", izleme geçmişi |
| **Kaynaklar** | Xtream Codes (player_api), M3U/M3U8 (bağlantı ya da dosya, m3u_plus), XMLTV EPG (.xml/.gz), birden çok kaynak, tek tıkla ücretsiz Türk kanalları ([iptv-org](https://github.com/iptv-org/iptv)) |
| **Görüntü** | RTX VSR ile 4K (kaynağa göre ×2 … ×6), RTX Video HDR (isteğe bağlı), GPU ile deinterlace (1080i/576i), deband, `ewa_lanczossharp`, film/dizide akıcı oynatma |
| **Gecikme** | 4 kip (Ultra / Düşük / Dengeli / Kararlı), **canlıya yetişme**, HLS'de canlı kenara yakın başlama, MPEG-TS önceliği, en hızlı kanal geçişi |
| **Dayanıklılık** | Yayın koparsa otomatik yeniden bağlanma, anlaşılır Türkçe hata iletileri (403 bağlantı sınırı, 404, zaman aşımı…) |

## Kurulum (Windows 10/11)

1. Bu depoyu indirin (ya da güncelleyin).
2. `iptv` klasöründeki **`Heloo TV.bat`** dosyasına çift tıklayın. İlk çalıştırmada kurulum kendiliğinden yapılır:
   - Python 3.10+ aranır (yoksa `winget` ile kurmayı önerir),
   - `.venv` sanal ortamına **PySide6** ve **python-mpv** kurulur,
   - GitHub'dan en güncel **mpv** indirilir (`libmpv-2.dll` + `mpv.exe`),
   - Masaüstüne ve Başlat menüsüne **Heloo TV** kısayolu eklenir.

Elle kurulum: `powershell -ExecutionPolicy Bypass -File install.ps1` (`-Force`: yeniden kur, `-NoShortcut`).
mpv'yi sonradan güncellemek: uygulamada **Ayarlar → Sistem → mpv bileşenlerini indir / güncelle**
ya da `.venv\Scripts\python -m helootv.tools.fetch_mpv --force`.

Linux/macOS: `./run.sh` (libmpv sistemden: `sudo apt install libmpv2` / `brew install mpv`). RTX VSR yalnızca
Windows'ta çalışır; diğer sistemlerde mpv'nin yüksek kaliteli ölçekleyicisi kullanılır.

## NVIDIA ayarı (bir kez)

RTX VSR için **GeForce RTX 20/30/40/50** serisi kart ve güncel sürücü gerekir (RTX 30/40: ≥ 531.18,
RTX 20: ≥ 545.84, RTX Video HDR: ≥ 551.23).

1. **NVIDIA App → Sistem → Video → RTX Video Enhancement**
   (eski sürücülerde: NVIDIA Denetim Masası → Video → Video görüntü ayarlarını yapın → RTX video geliştirme).
2. **Super Resolution: AÇIK**, kalite **Otomatik** (GPU yüküne göre ayarlanır) ya da **4** (RTX xx70 ve üstü).
3. İsteğe bağlı, HDR ekranda: **High Dynamic Range: AÇIK** + Windows Ayarlar → Ekran → **HDR kullan**, sonra
   Heloo TV → Ayarlar → **RTX Video HDR**.

Uygulamanın üst çubuğundaki yeşil rozet ("RTX 4070 · RTX VSR hazır") kartınızı ve sürücünüzü denetler.
Oynatma sırasında durum çubuğunda **● RTX VSR 1280×720 → 3840×2160** yazısı görünür. NVIDIA App'te VSR kapalıysa
"RTX VSR sürücüde kapalı" uyarısı çıkar.

**Doğrulama:** Ayarlar → Sistem → **RTX VSR'yi test et**. Küçük bir test penceresinde 720p görüntü 4K'ya ölçeklenir
ve mpv günlüğünden NVIDIA sürücüsünün yanıtı okunur: "✔ NVIDIA sürücüsü RTX Video Super Resolution'ı
ETKİNLEŞTİRDİ" ya da ne yapmanız gerektiği. Komut satırından: `.venv\Scripts\python -m helootv.selftest`.

## Kullanım

**Kaynak ekleme:** ilk açılışta karşılama ekranından ya da **Ayarlar → Kaynaklar**:
- **Xtream hesabı**: sunucu (`http://adres:port`), kullanıcı adı, şifre → "Bağlantıyı test et" hesabın bitiş tarihini
  ve bağlantı sınırını gösterir.
- **M3U listesi**: bağlantı ya da dosya. `get.php?username=…&password=…` bağlantıları otomatik olarak Xtream hesabına
  çevrilir (film/dizi ayrıntıları ve EPG daha iyi olur).
- **EPG** boşsa: Xtream'in kendi `xmltv.php`'si ya da listedeki `url-tvg` kullanılır. Listeler 12 saatte bir, EPG
  günde iki kez kendiliğinden yenilenir.

**Tuşlar** (video penceresine tıklayınca oynatıcı tuşları alır):

| Tuş | Canlı TV | Film / dizi |
|---|---|---|
| ↑ / ↓ | önceki / sonraki kanal | +60 / −60 sn |
| ← / → | 10 sn geri / ileri (zaman kaydırma) | 10 sn geri / ileri |
| PgUp / PgDn | 10 kanal geri / ileri | ±10 dk |
| 0–9, Enter | kanal numarası | %0–%90'a atla |
| Geri (⌫) | son izlenen kanala dön | — |
| Boşluk / P | duraklat (zaman kaydırma başlar) | duraklat |
| L | canlı yayına dön | — |
| F, F11, çift tık | tam ekran | tam ekran |
| Esc | tam ekrandan / sinema modundan çık | |
| T | sinema modu (listeleri gizle) | |
| I / E | bilgi (çözünürlük, VSR, gecikme) / şimdi-sonra | bilgi |
| M, tekerlek | sessiz, ses | sessiz, ses |
| A / J / V | ses izi / altyazı / altyazı aç-kapa | |
| Sağ tık | mpv menüsü (ses/altyazı izi seçimi) | |

Uygulama genelinde: **Ctrl+F** ara, **F5** yenile, **Ctrl+↑/↓** kanal, **Ctrl+1…5** sekmeler, **Ctrl+D** favori.

## Görüntü iyileştirme nasıl çalışıyor?

Oynatıcı motoru [mpv](https://github.com/mpv-player/mpv)'dir (libmpv, Direct3D 11). Kaynak çözünürlüğü belli olunca
Heloo TV mpv'nin `d3d11vpp` filtresini kurar:

```
@helootv:d3d11vpp=scale=<k>:scaling-mode=nvidia:deint=yes:mode=adaptive:interlaced-only=yes[:nvidia-true-hdr=yes]
```

`scale` kodlanmış kareyi büyütür ve `scaling-mode=nvidia` NVIDIA'nın video işlemci uzantısını açar; sürücü bu
büyütmeyi **RTX VSR** (yapay zekâ) ile yapar. Katsayı hedef kutuya (varsayılan 3840×2160) sığacak şekilde hesaplanır:

| Kaynak | Katsayı | Çıkış |
|---|---|---|
| 360p | ×6 | 3840×2160 |
| 576i/p (SD, 16:9 anamorfik) | ×3,75 | 3840×2160 görüntü |
| 720p | ×3 | 3840×2160 |
| 1080p/i | ×2 | 3840×2160 |
| 1920×800 (sinemaskop) | ×2 | 3840×1600 |
| 2160p | — | olduğu gibi |

Kanal değişince ya da yayın çözünürlüğü değişince katsayı yeniden hesaplanır. Aynı filtre geçmeli (1080i/576i)
yayınları **GPU'da** deinterlace eder; isteğe bağlı RTX Video HDR, SDR yayını HDR10'a çevirir. Donanım çözme
`d3d11va` (sıfır kopya; desteklenmeyen kodlayıcıda yazılıma düşer ve kareler GPU'ya yüklenir), `hwdec-codecs=all`
(SD kanallardaki MPEG-2 dahil). Sonrasında `gpu-next` ile deband ve `ewa_lanczossharp` uygulanır.
Hedef "Ekran çözünürlüğü" ya da "1440p" yapılabilir (daha az GPU yükü).

## Gecikme kipleri

| Kip | Ne yapar |
|---|---|
| **Ultra düşük** | mpv'nin `low-latency` profili: ses tamponu 0, önbellek beklemesi yok, `fflags=+nobuffer`, akış bilgisi taraması yok, HLS'de son parçadan başlama (`live_start_index=-1`). İnternet dalgalanırsa takılabilir. |
| **Düşük (önerilen)** | Aynı hızlı açılış; kısa kopmalarda 0,4 sn tamponla toparlanır, HLS'de canlı kenardan 2 parça geride başlar. |
| **Dengeli** | Daha çok tampon; çoğu bağlantıda takılmasız. |
| **Kararlı** | Açılışta 3 sn tampon; zayıf/kablosuz bağlantılar için. |

**Canlıya yetişme:** tampon hedefi aşarsa (ör. bir takılmadan sonra) oynatma %8 hızlanır (ses perdesi korunur) ve
gecikme kendiliğinden geri alınır; çok büyürse tampon içinde canlıya atlanır. HLS'de eşikler listenin parça süresine
(`#EXT-X-TARGETDURATION`) göre ayarlanır. Kanal geçişi tek mpv örneğinde `loadfile` ile yapılır (oynatıcı yeniden
başlatılmaz), `ytdl` kancası kapalıdır. Xtream'de canlı yayınlar varsayılan olarak MPEG-TS (`.ts`) açılır — HLS'den
daha düşük gecikme.

**HLS'de hızlı açılış (kalite sabitleme):** FFmpeg, çok kaliteli bir HLS kanalında açılışta *her* kalitenin
(1080p/720p/480p/360p) ilk parçalarını indirir. Heloo TV ana listeyi kendisi okuyup en yüksek kaliteyi (çözünürlük,
kare hızı, bit hızı) doğrudan açar. Gerçek kanallarla ölçüm: Halk TV 10,0 sn → 3,5 sn, 24 TV 8,8 sn → 3,8 sn
(yavaş bir vekil sunucu üzerinden; ev bağlantısında daha da kısa). Ayrı ses izi olan listelerde ve sabitlenen
adres açılmazsa (CDN çerezi vb.) özgün adres kullanılır.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| "Oynatıcı bileşeni (libmpv) eksik" | Ayarlar → Sistem → **mpv bileşenlerini indir** ya da `install.ps1 -Force`. |
| Durum çubuğunda "RTX VSR sürücüde kapalı" | NVIDIA App → Sistem → Video → Super Resolution'ı açın; sürücüyü güncelleyin. |
| VSR rozeti çıkmıyor | Kaynak zaten 4K olabilir; Ayarlar → Görüntü → RTX VSR açık mı? mpv ≥ 0.39 gerekir (Sistem kutusunda yazar). |
| Takılma / kare atlama | Hedefi "1440p" ya da "Ekran çözünürlüğü" yapın, NVIDIA'da VSR kalitesini "Otomatik" yapın, gecikme kipini "Dengeli" seçin. |
| "HTTP 403 — bağlantı sınırı" | Hesabın aynı anda izlenebilecek cihaz sayısı dolu; başka cihazdaki oynatmayı kapatın. Kanal hızlı değişince sunucu eski bağlantıyı geç kapatabilir — otomatik yeniden deneme bunu çözer. |
| Kanal açılmıyor ama başka oynatıcıda açılıyor | Ayarlar → Ağ → User-Agent'ı "IPTV Smarters" ya da "Kodi" yapın; Xtream biçimini HLS'ye çevirin. |
| EPG saatleri kayık | Ayarlar → Ağ ve arayüz → EPG saat kaydırma. |

Günlük: `%LOCALAPPDATA%\HelooTV\helootv.log` (`python -m helootv --debug` ile mpv ayrıntıları dahil).

## GitHub'dan kullanılanlar / araştırma

| Kaynak | Kullanım |
|---|---|
| [mpv-player/mpv](https://github.com/mpv-player/mpv) `video/filter/vf_d3d11vpp.c`, `DOCS/man/vf.rst` | RTX VSR (`scaling-mode=nvidia`, 0.39+), RTX Video HDR (`nvidia-true-hdr`, 0.40+; 0.42'de yalnız SDR), düzeltilmiş GPU deinterlace (0.42) |
| mpv `etc/builtin.conf` `[low-latency]` | Ultra düşük gecikme kipinin temeli |
| [zhongfly/mpv-winbuild](https://github.com/zhongfly/mpv-winbuild) (yedek: [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake)) | mpv master'ın günlük Windows derlemeleri; AVX2'li işlemcide x86-64-v3 seçilir |
| [ip7z/7zip](https://github.com/ip7z/7zip) | `7zr.exe`: mpv arşivleri LZMA2+BCJ2 (Python'un 7z kitaplığı açamıyor) |
| [jaseg/python-mpv](https://github.com/jaseg/python-mpv) | libmpv bağlayıcısı (pencereye gömme `wid`, olaylar, `script-message`) |
| [iptv-org/iptv](https://github.com/iptv-org/iptv) | İsteğe bağlı ücretsiz Türk kanalları listesi |
| [linuxmint/hypnotix](https://github.com/linuxmint/hypnotix), [Fredolx/open-tv](https://github.com/Fredolx/open-tv), [4gray/iptvnator](https://github.com/4gray/iptvnator) | Xtream/M3U sınıflandırma ve mpv kullanımı için incelendi (kod kopyalanmadı) |

GitHub sürüm varlıklarında SHA-256 özeti varsa indirilen dosyalar doğrulanır.

## Geliştirici

```
iptv/
  Heloo TV.bat, install.ps1, run.sh, requirements.txt
  helootv/
    app.py                 giriş (python -m helootv)
    m3u.py xtream.py epg.py   M3U/m3u_plus, Xtream Codes, XMLTV + catch-up adresleri
    store.py catalog.py    SQLite katalog (EPG ayrı dosyada), kaynak yenileme, oynatma adresi
    player/options.py      RTX VSR planı, gecikme kipleri, kalite ayarları (saf fonksiyonlar)
    player/engine.py       libmpv denetleyicisi (canlıya yetişme, yeniden bağlanma, tuşlar, harici mpv)
    ui/                    PySide6 arayüz (sayfalar, liste çizimleri, oynatıcı paneli, ayarlar)
    tools/fetch_mpv.py     GitHub'dan mpv indirici
    hls.py                 HLS ana liste çözümü (kalite sabitleme), parça süresi
    selftest.py            RTX VSR testi (d3d11vpp + sürücü yanıtı)
  tests/                   pytest (gerçek libmpv ile başsız oynatma ve offscreen arayüz testleri dahil)
```

Testler: `python -m pytest tests -q` (Linux'ta `libmpv2`, `ffmpeg`, `7z` varsa hepsi çalışır). GitHub Actions
(`.github/workflows/iptv-tests.yml`) her gönderimde Linux'ta testleri; Windows'ta GitHub'dan gerçek mpv indirmeyi,
`d3d11vpp` RTX seçeneklerinin (`scaling-mode=nvidia`, `nvidia-true-hdr`) varlığını, aynı testleri ve mpv'nin gerçek
bir Qt penceresine Direct3D 11 ile gömülerek oynatmasını sınar.
