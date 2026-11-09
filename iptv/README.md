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

## Her görüntü 4K: kendi videolarınız, fotoğraflar, bağlantılar

Yalnız IPTV değil, **her görüntü** aynı zincirden geçer (RTX VSR ile 4K; olmadığı yerde yapay zekâ büyütücü):

- **📂 Aç → Video ya da fotoğraf aç** (Ctrl+O), klasör seçerseniz içindekiler sırayla (Sonraki/Önceki tuşları).
- **Sürükle-bırak:** dosyayı, klasörü ya da bağlantıyı pencereye (video alanı dahil) bırakın.
- **Sağ tık → Gönder → Heloo TV (4K)** ya da **Birlikte aç → Heloo TV (4K)** (kurulum ekler). Uygulama açıksa
  dosya aynı pencerede açılır.
- **Bağlantı aç** (Ctrl+U): YouTube, Instagram, TikTok, Vimeo … (yt-dlp en yüksek kaliteyi seçer), m3u8/mp4/ts.
- Kaldığınız yer hatırlanır; son açılanlar 📂 menüsünde ve Favoriler → Geçmiş'te.

**Görüntü iyileştirme sırası:** RTX VSR (NVIDIA, 4K'ya; dikey video ekranın yüksekliğine) → VSR'nin büyütmediği her
durumda (fotoğraf, sürücüde VSR kapalı, RTX olmayan kart) **yapay zekâ büyütücü**: FSRCNNX (canlı çekim) ya da ArtCNN
(çizgi film), GitHub'dan indirilir → ewa_lanczossharp + deband. Sürücü VSR'yi reddederse uygulama bunu günlükten
anlayıp kendiliğinden yapay zekâ büyütücüye geçer.

**📂 Aç → 4K olarak kaydet** (Ctrl+E): videoyu/fotoğrafı dosya olarak 4K'ya çıkarır (dikey video 2160×3840).
RTX VSR yalnız oynatırken çalıştığı için kayıtta FFmpeg + libplacebo (Vulkan, ekran kartında) + yapay zekâ modeli +
ewa_lanczossharp + deband kullanılır, video NVIDIA NVENC (HEVC) ile kodlanır; ses korunur. Çıktı:
`<ad> (4K).mp4` / `.png`, kaynağın yanına ya da seçtiğiniz klasöre.

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

Uygulama genelinde: **Ctrl+F** ara, **F5** yenile, **Ctrl+↑/↓** kanal, **Ctrl+1…5** sekmeler, **Ctrl+D** favori,
**Ctrl+P** görüntü ayarları.

**İleri / geri sarma:** film, dizi ve dosyalarda alt çubukta ilerleme çubuğu (sürükleyin ya da tıklayın), geçen/toplam
süre ve **−1 dk / −10 / +10 / +1 dk** düğmeleri vardır. Canlı yayında çubuk gizlenir; ←/→ zaman kaydırma yapar.

## Kayıt, zamanlanmış kayıt, hatırlatıcı, mini oynatıcı

TiviMate / IPTVnator / OTT Navigator'daki özelliklerin karşılıkları:

- **⏺ Kaydet (Ctrl+R)**: oynayan canlı yayını, filmi ya da geri izlemeyi kaydeder. FFmpeg akışı yeniden kodlamadan
  (`-c copy`) MPEG-TS'ye yazar: işlemci yükü ve kalite kaybı yok, kayıt kesilse de dosya oynatılır. Kayıt sürerken
  düğme kırmızıdır ve süreyi gösterir. Kayıtlar: `Videolar\Heloo TV Kayıtlar` (Ayarlar'dan değiştirilebilir).
- **Zamanlanmış kayıt**: yayın akışında bir programa sağ tık → "⏺ Bu programı kaydet". Kayıt 1 dk önce başlar,
  program bitiminden 2 dk sonra biter; uygulama açık olmalıdır. Programın yanında ⏺ işareti görünür.
- **Hatırlatıcı**: sağ tık → "🔔 Başlayınca hatırlat": program başlamadan 1 dk önce bildirim ve "Kanalı aç".
- **⧉ Resim içinde resim (Ctrl+M)**: yalnız video, her zaman üstte, ekranın sağ altında küçük pencere; başka bir işle
  uğraşırken izlemek için. Esc ya da çift tık: geri döner.
- Oynatıcı çubuğu iki satıra bölündü (sarma düğmeleri ilerleme çubuğunun yanında; ses ve pencere düğmeleri başlık
  satırında): pencerenin en küçük genişliği 2157 → 1328 piksel (1366 px dizüstü ekrana sığar).

## Altyazı ve ses izi

Alt çubuktaki **💬 Altyazı** menüsü:

- **İz seçimi**: videodaki ve yanındaki (`film.tr.srt`) altyazılar dili ile listelenir; "Kapalı" ile kapatılır.
- **Dosyadan altyazı ekle**: `.srt .ass .ssa .vtt .sub .sup`.
- **İnternetten altyazı bul (OpenSubtitles)**: başlıktan ad, sezon ve bölüm (S02E05) çıkarılır; Türkçe/İngilizce
  sonuçlar indirme sayısına göre sıralanır, çift tıkla eklenir. [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers)
  adresinden **ücretsiz API anahtarı** gerekir (Ayarlar → Ses ve altyazı ya da pencerenin kendisi).
- **Yapay zekâ ile altyazı (konuşmadan)**: oyunlardaki canlı altyazı araçları gibi, altyazısı olmayan videonun
  konuşmasını [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (OpenAI Whisper, MIT) ile yazıya döker.
  İzlenen yerden başlar, ses 40 sn'lik parçalar halinde işlenir; ilk satırlar birkaç saniyede gelir, ilerledikçe
  dolar. NVIDIA kartta CUDA ile (yoksa işlemcide) çalışır. İlk kullanımda "Kur" ile bir kez indirilir (~200 MB +
  model: base/small/medium/large-v3-turbo). İsterseniz konuşmayı İngilizceye çevirerek yazar. Canlı yayında yoktur.
- **Zamanlama**: altyazıyı 0,5/0,1 sn erken/geç gösterme. **Görünüm**: büyüt/küçült, kalın kenarlı yazı ya da yarı
  saydam kutu, beyaz/sarı, yukarı/aşağı taşı.

**🔈 Ses** menüsü ses izlerini (dublaj/özgün, kanal sayısı) listeler ve ses gecikmesini ayarlar. Altyazılar kalın,
3 px kenarlı ve gölgeli yazılır (4K'da ve açık sahnelerde okunaklı); ekran yazıları (OSD) de büyütüldü.

## Her zaman iyileştirme (canlı yayın dahil)

Görüntü iyileştirme kaynak türüne bakmaz: canlı yayın, geri izleme, film, dizi, kendi dosyalarınız ve bağlantılar
aynı zincirden geçer — gürültü azaltma → RTX VSR ile 4K (yoksa yapay zekâ büyütücü) → keskinlik → bant yumuşatma
(+ isteğe bağlı RTX HDR ve Lossless Scaling kare üretimi). Hepsi gecikme eklemeyen GPU/tek kare işlemleridir, bu yüzden
canlı yayının düşük gecikmesi korunur. Oynatıcı çubuğundaki yeşil **✦** etiketi o anda çalışan iyileştirmeleri her
zaman gösterir (ör. `✦ RTX VSR 576p→2160p · Gürültü azaltma · Keskinlik · Bant yumuşatma`). RTX VSR sürücüde
kapalıysa ya da kart desteklemiyorsa Heloo TV kendiliğinden yapay zekâ büyütücüye geçer; iyileştirme kesilmez.

## AMD (ve Intel) ekran kartları

NVIDIA olmayan kartlarda RTX VSR yoktur; mpv'nin `d3d11vpp` filtresi yalnız NVIDIA ve Intel'in video yükseltmesini
açabilir (AMD'nin video yükseltmesi sürücüde Windows medya hattına bağlıdır, mpv'ye açık değildir). Heloo TV
açılışta kartı tanır (`Win32_VideoController`) ve AMD/Intel kartta:

- Büyütmeyi **AMD FidelityFX Super Resolution (FSR 1.0.2)** ile yapar: AMD'nin MIT lisanslı kodu, mpv'ye
  [agyild](https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5) tarafından uyarlanmış hali; pakette gelir
  (`helootv/glsl/fsr.glsl`), indirme gerekmez. Tek karelik bir GPU işlemidir → canlı yayına gecikme eklemez.
- Keskinlik AMD CAS tarzı shader'ımızla, gürültü azaltma ve deband her kartta aynıdır; deinterlace yine GPU'da.
- Yeşil etiket `✦ AMD FSR büyütme · Gürültü azaltma · Keskinlik · Bant yumuşatma` gösterir; üst çubukta kart adı
  ve "AMD FSR" yazar. Ayarlar → Görüntü → "AMD / Intel ekran kartında AMD FSR ile büyüt" ile kapatılabilir.
- Akıcılık için: **AMD Software (Adrenalin) → Oyun → Grafik → AMD Fluid Motion Frames** (AFMF; RX 6000/7000/9000)
  ya da Lossless Scaling. AFMF kullanırken Ayarlar → "Film/dizide akıcı oynatma"yı kapatın.
- FSR, hiçbir yapay zekâ modeli indirilemediğinde her kartta yedek büyütücüdür; böylece iyileştirme hiç kesilmez.

## Akıcılık için yapılanlar (görüntü iyileştirme)

- **RTX VSR hedefi = ekran çözünürlüğü** (varsayılan): 1080p ekranda 720p → 1080p, 4K ekranda/TV'de 4K. Eskiden
  her kaynak 4K üretilip 1080p ekranda geri küçültülüyordu: aynı görüntü için kat kat GPU yükü ve kare atlama.
  "Her zaman 4K" ayarda seçilebilir. Eski ayar dosyaları bir kez kendiliğinden güncellenir.
- **Gürültü azaltma yalnız SD (orta) ve 720p'de (hafif)**; 1080p'de RTX VSR'nin kendi kusur temizliği yeter. Kareler
  yalnız gürültü azaltılan kaynakta belleğe kopyalanır; HD'de GPU'da kalır (kopya 1080p50'de kare atlatıyordu).
- **Geçmeli yayınlar (576i)**: gürültü azaltmadan önce `bwdif` ile alan hızında (50 fps) deinterlace — eskiden
  alanlar karışıp tarak/bulanıklık oluyordu. Geçmeli bilgisi kanal başına bir kez öğrenilir (filtre açılıp kapanmaz).
- **Çift keskinlik yok**: RTX VSR ya da AMD FSR (kendi RCAS'ı) büyütürken CAS yarı güçte.
- Pencereye küçültmede hafif `mitchell` filtresi (ağır `ewa_*` yalnız büyütmede).
- Lossless Scaling varsayılan olarak **tam ekranda** açılır (pencere kipinde listelerle birlikte bütün pencereyi
  büyütüyordu).

## Görüntü ayarları ve karıncalanma

**🎨 Görüntü** menüsü / **Ctrl+P** penceresi oynayan görüntüye anında uygulanır ve kaydedilir:

| Ayar | Ne yapar |
|---|---|
| Hazır ayarlar | **Doğal**, **Canlı**, **Sinema**, **Spor** (güçlü keskinlik), **Karıncalı yayın** (güçlü gürültü azaltma + deband) |
| Parlaklık, kontrast, doygunluk, gama, ton | −100…100 (mpv; GPU'da, gecikmesiz) |
| Karıncalanma azaltma | `hqdn3d` (FFmpeg): uzamsal + zamansal gürültü azaltma. Zamansal kısım yalnız **önceki** kareyi kullanır → gecikme eklemez. *Otomatik*: ≤576p orta, 720p hafif, 1080p ve üstü kapalı (RTX VSR temizler); elle her çözünürlükte açılabilir |
| Keskinlik | AMD FidelityFX **CAS** tarzı uyarlanır keskinleştirme (kendi GLSL shader'ımız, `helootv/glsl/cas.glsl`); kenarları bulanıklaştırmadan netleştirir, aşırı keskinlik halesi yapmaz |
| Renk bandı yumuşatma | deband 0–3 (gökyüzü/gölge geçişlerindeki basamaklar) |
| Düşük kaliteli yayında güçlendir | ≤576p kaynakta deband en az "orta", keskinlik +0,15 |

Gürültü azaltma, RTX VSR'den **önce** uygulanır (VSR temiz kareyi büyütür). Bu yüzden açıkken Windows'ta çözme
`d3d11va-copy` olur (kare işlemciye kopyalanır, filtrelenir ve GPU'ya geri yüklenir); 1080p50'de bile modern bir
işlemcide sorunsuzdur. "Kapalı"da sıfır kopya `d3d11va`'ya döner.

## Lossless Scaling ile kare üretimi (isteğe bağlı)

[Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/) (THS) Steam'de satılan, kapalı
kaynaklı bir Windows uygulamasıdır; GitHub'da resmi deposu yoktur ve Heloo TV onu içermez. Bilgisayarınızda
kuruluysa Heloo TV onunla birlikte çalışır:

- **Her zaman (varsayılan)**: bir yayın/film/dizi/dosya oynamaya başlayınca (canlı yayın dahil) kare üretimi
  kendiliğinden açılır ve açık kalır. Program kapalıysa Steam üzerinden başlatılır; kısayol yalnız Heloo TV
  penceresi öndeyken gönderilir (başka pencere öndeyse Heloo TV öne gelene kadar bekler).
- **Görüntü menüsü → ⚡ Lossless Scaling** ya da **Ctrl+G**: elle aç/kapat.
- **Ayarlar → Lossless Scaling**: kip (Her zaman / Yalnız tam ekranda / Elle), kısayol, program yolu (boşsa bütün
  Steam kütüphaneleri `libraryfolders.vdf` üzerinden aranır). Lossless Scaling'in kendi "Auto scale" profilini
  kullanıyorsanız kipi **Elle** yapın (iki taraf aynı anda kısayola basarsa birbirini kapatır).
- Açıkken mpv'nin kendi interpolasyonu (film/dizide "akıcı oynatma") kapatılır; iki kare üretimi üst üste
  titreme yapar. Kapanınca geri gelir.

Lossless Scaling'de önerilen ayar: **Ölçekleme türü: Kapalı** (4K büyütmeyi RTX VSR yapıyor; ikisi birlikte
görüntüyü bozar), **Kare üretimi: LSFG 3, ×2** (25/30 fps yayın → 50/60 fps), **Max frame latency: 1**, yakalama
**WGC**. Kare üretimi yaklaşık bir kare (~20–40 ms) gecikme ekler; en düşük gecikme gereken maçlarda kapalı
tutabilirsiniz. Lossless Scaling'in kısayolunu değiştirdiyseniz Heloo TV ayarlarında da aynısını yazın.

## LG televizyonda izleme

1. **En iyi yol: bilgisayardan HDMI ile** (RTX VSR / RTX HDR yalnız bilgisayardaki NVIDIA kartta çalışır).
   - HDMI 2.1 kabloyla LG'ye bağlayın; Windows'ta **Ekran → 3840×2160, 60 Hz** (OLED/QNED'de 120 Hz) seçin.
   - LG'de girişi **PC** olarak adlandırın (Giriş simgesi → PC) ya da **Oyun Optimize Edici**'yi açın: gecikme azalır,
     renkler 4:4:4 olur, TV'nin kendi işleme adımları VSR'nin üstüne bir şey eklemez.
   - **Ayarlar → Genel → Cihazlar → HDMI Ayarları → HDMI Ultra HD Deep Colour** bu giriş için açık olmalı (4K 60 Hz + HDR).
   - RTX HDR için Windows'ta **Ekran → HDR kullan** açık; Heloo TV'de Ayarlar → RTX Video HDR.
   - Heloo TV'de **⛶ Tam ekran** (F). Kumandayla kullanmak için Windows'a Bluetooth/USB kablosuz klavye-fare ya da
     "air mouse" kumanda bağlayın; ↑/↓ kanal, ←/→ sarma, Enter bilgi, Boşluk duraklat.
2. **Kablosuz (aynı Wi-Fi)**: Windows **Win+K → LG TV** (Miracast) görüntüyü yansıtır ama sıkıştırır ve gecikme
   ekler; VSR'nin kazandırdığı netliğin bir kısmı kaybolur. DLNA "Cihaza yayınla" ise videoyu TV'nin kendi oynatıcısına
   gönderir, VSR hiç uygulanmaz.
3. **Bilgisayarsız**: Heloo TV Windows uygulamasıdır, LG webOS'a kurulmaz. TV'de aynı Xtream/M3U hesabını LG Content
   Store'daki bir IPTV oynatıcıyla açabilirsiniz; o zaman büyütmeyi TV'nin kendi işlemcisi (α / AI Picture) yapar.

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
| **Akıllı (önerilen, varsayılan)** | Kendini ayarlar: iyi bağlantıda ~1 sn tampon; takılan kanalda tampon o kanal için büyür (en çok 6 sn) ve hatırlanır; 1 dk sorunsuz geçince küçülür ve gecikme %4 hızla (fark edilmez) geri alınır. Ölçüm: sorunsuz bağlantıda gecikme 3,2 → **1,3 sn**. |
| **Ultra düşük** | ~1 sn tampon, `fflags=+nobuffer`, HLS'de canlı kenardan 2 parça geride. Kablolu ve çok iyi internet ister. |
| **Düşük** | ~1,5 sn tampon, HLS'de 3 parça geride. İyi internet ister. |
| **Dengeli** | TiviMate/IPTV Smarters gibi sabit ~3 sn tampon: dalgalanmada donmaz, gecikme biraz daha fazla. |
| **Kararlı** | Açılışta 3 sn tampon; zayıf/kablosuz bağlantılar için. |

**Donmaya karşı (IPTV uygulamalarının yaptığı gibi):**

- **Otomatik yeniden bağlanma:** HTTP canlı yayında FFmpeg `reconnect_streamed` ile bağlantı koparsa anında yeniden
  bağlanır; oynatıcı 15 sn beklemez.
- **Bekçi:** görüntü 6 sn ilerlemezse, tampon boşken 4 sn hiç veri gelmezse (bağlantı ölü) ya da tampon 10 sn boş
  kalırsa yayın kendiliğinden yeniden açılır (en çok 20 sn'de bir; duraklatılmışsa ya da kanal henüz açılmadıysa asla).
- **Kendini ayarlayan tampon:** takılan kanalda tampon payı 1 sn büyür (en çok 6 sn), 3 dk sorunsuz geçince azalır.
- **Aşırı yük koruması:** bilgisayar sürekli kare atlıyorsa (sn'de 3'ten fazla) iyileştirme bu oturum için bir kademe
  hafifletilir: önce gürültü azaltma, sonra RTX VSR/yapay zekâ kapanır. Ayar değişince yeniden denenir.
- **Canlıya yetişme varsayılan olarak kapalı** (gecikme sabit kalır, hiç hızlanma/atlama olmaz). Açılırsa yalnız
  gecikme 8 sn boyunca sınırı aşınca %4 hızlanır; ileri atlama yalnız 25 sn'nin üstünde, dakikada en çok bir kez.

Gerçek libmpv ile benzetim (eski → yeni sürüm, 60 sn):

| Sorun | En uzun donma | Toplam donma |
|---|---|---|
| Sağlayıcı yayını kesti (bağlantı açık, veri yok) | 13,8 sn → **4,8 sn** | 15,4 → **5,2 sn** |
| Bağlantı 15 sn'de bir kopuyor | 2,0 sn → **0,4 sn** | 4,0 → **0,5 sn** |
| 1–2,5 sn'lik dalgalanmalar | 1,0 sn → **0,4 sn** | 1,8 → **0,4 sn** |

Eski ayar dosyaları bir kez güncellenir: "Düşük" kip → "Dengeli", canlıya yetişme kapalı. Xtream'de canlı yayınlar
varsayılan olarak MPEG-TS (`.ts`) açılır. Kanal geçişi tek mpv örneğinde `loadfile` ile yapılır.

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
| [igv/FSRCNN-TensorFlow](https://github.com/igv/FSRCNN-TensorFlow) (FSRCNNX), [Artoriuz/ArtCNN](https://github.com/Artoriuz/ArtCNN) (MIT) | Yapay zekâ büyütücü shader'ları (oynatma yedeği + 4K kayıt) |
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
    weburl.py              bağlantı aç (yt-dlp), shaders.py yapay zekâ modelleri, upscale.py 4K kayıt
    selftest.py            RTX VSR testi (d3d11vpp + sürücü yanıtı)
  tests/                   pytest (gerçek libmpv ile başsız oynatma ve offscreen arayüz testleri dahil)
```

Testler: `python -m pytest tests -q` (Linux'ta `libmpv2`, `ffmpeg`, `7z` varsa hepsi çalışır). GitHub Actions
(`.github/workflows/iptv-tests.yml`) her gönderimde Linux'ta testleri; Windows'ta GitHub'dan gerçek mpv indirmeyi,
`d3d11vpp` RTX seçeneklerinin (`scaling-mode=nvidia`, `nvidia-true-hdr`) varlığını, aynı testleri ve mpv'nin gerçek
bir Qt penceresine Direct3D 11 ile gömülerek oynatmasını sınar.
