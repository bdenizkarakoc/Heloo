# Otonom AI Reels Fabrikası

Belirlenen içerik kategorilerinde **konu seçen, araştıran, kaynaklı senaryo yazan, Türkçe seslendiren,
kelime vurgulu altyazı ekleyen, görsel/video temin eden, HyperFrames ile hareketli kurgu yapan,
müzik ve efekt ekleyen, kalite kontrolünden geçiren** ve paylaşıma hazır dikey video üreten modüler bir sistem.

```
KONU → ARAŞTIRMA → SENARYO → SES → ALTYAZI → GÖRSEL → MÜZİK → KURGU → RENDER → MİKS → KALİTE KONTROL → ÇIKTI
```

Varsayılan çıktı: **1080×1920, 9:16, 30 fps, MP4 (H.264 + AAC 48 kHz), −14 LUFS**, 30–60 sn
(Instagram Reels, TikTok, YouTube Shorts).

---

## Ne yapabiliyor, ne yapamıyor (dürüst durum)

`python scripts/factory.py doctor` hangi yöntemlerin o anda gerçekten kullanılabildiğini gösterir.
Anahtarı olmayan bir hizmet **asla varmış gibi kullanılmaz**; yerine alternatif yöntem uygulanır ve
görevin uyarılarına yazılır.

| Adım | Anahtarsız (varsayılan) | İsteğe bağlı (anahtar/hesap ile) |
|---|---|---|
| Konu + araştırma + senaryo | Claude Code oturumu (`skills/reels-production/SKILL.md`) | Claude API ile tam otonom (`ANTHROPIC_API_KEY`) |
| Seslendirme (Türkçe) | edge-tts nöral sesler (`tr-TR-EmelNeural`, `tr-TR-AhmetNeural`) + kelime zamanları | ElevenLabs (`ELEVENLABS_API_KEY`) |
| Görseller | NASA görsel kütüphanesi (kamu malı), Openverse (CC0 / kamu malı / CC BY) | Pexels foto/video, OpenAI görsel üretimi, Replicate görsel/video modelleri |
| Hareket | Fotoğraf + kamera hareketleri (push/pull/pan), geçişler, hareketli grafikler (sayaç, karşılaştırma çubukları, listeler, kinetik tipografi) | Gerçek AI video klipleri (Replicate modeli veya ajanın ürettiği klipler) |
| Müzik | Openverse CC0 / CC BY (atıf otomatik), prosedürel ambiyans | Kendi lisanslı kütüphaneniz (`assets/music/licenses.yaml`) |
| Efektler | HyperFrames paketindeki Pixabay lisanslı 21 efekt | `assets/sfx/` |
| Kurgu/render | HyperFrames + GSAP (HTML → MP4) | — |
| Kalite kontrol | ffprobe/ffmpeg analizleri + faster-whisper ile konuşma tanıma | — |

**Önemli:** Bu kurulumda yapay zekâ ile *gerçek video klip üretimi* için yapılandırılmış bir hizmet
yoktur. Video sahneleri; lisanslı fotoğraflar üzerinde kamera hareketleri, sahne geçişleri ve
hareketli grafiklerle üretilir. Bir video üretim hizmeti bağlandığında (Replicate modeli veya Claude Code
oturumundaki bir üretim aracı → `projects/<görev>/media/<sahne>.mp4`) klipler otomatik kullanılır.
OpenAI/Replicate/Pexels/ElevenLabs bağdaştırıcıları yazılmıştır ancak anahtar olmadığı için bu
ortamda **canlı test edilmemiştir**.

---

## Kurulum

Gereksinimler: Python 3.10+, Node.js 22+, FFmpeg (libx264), ~1 GB disk (render tarayıcısı + modeller).

```bash
cd reels-factory
bash scripts/setup.sh
```

Betik şunları yapar: `pip install -r requirements.txt`, `npm install` (HyperFrames 0.8.201 + GSAP 3.14.2),
`npx hyperframes browser ensure` (Chrome Headless Shell), HyperFrames telemetrisini kapatır,
`.env.example` → `.env` kopyalar ve `doctor` çalıştırır.

**Windows — tek komutla her şey** (PowerShell'e yapıştırın; kurulum ve güncelleme aynı komut):

```powershell
irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/autonomous-ai-reels-factory-x82681/reels-factory/scripts/install-all.ps1 | iex
```

`scripts/install-all.ps1`: eksikse Git/Python/FFmpeg/Node.js'i winget ile kurar → kodu `Belgeler\Heloo` altına indirir
(varsa günceller) → Python/Node paketleri, render tarayıcısı, ses motoru (PyTorch CPU) → Claude Code (kurulum +
tarayıcıda giriş) → masaüstü kısayolları ve Windows açılışında başlatma → uygulamayı açar. `.env`, videolar,
sesler ve kanallar korunur. Seçenekler komuttan önce: `$env:RF_DIR="C:\Reels"`, `$env:RF_NO_VOICE=1`,
`$env:RF_NO_CLAUDE=1`.

Elle kurulum:

```bash
python3 -m pip install -r requirements.txt
npm install
npx hyperframes browser ensure
cp .env.example .env      # isteğe bağlı anahtarlar
python3 scripts/factory.py doctor
```

İlk kalite kontrolünde faster-whisper `small` modelini (~460 MB) Hugging Face'ten indirir.
İstemiyorsanız `config/settings.yaml → qc.asr_check: false`.

### API anahtarları (isteğe bağlı)

Yalnızca `.env` dosyasına yazın (git'e eklenmez, loglarda maskelenir):

| Değişken | Ne açar |
|---|---|
| `ANTHROPIC_API_KEY` | Tam otonom mod: Claude (`claude-opus-5-5`) web araştırması + senaryo (`llm.provider: anthropic`) |
| `ELEVENLABS_API_KEY` | ElevenLabs seslendirme (+ `tts.elevenlabs.voice_id`) |
| `PEXELS_API_KEY` | Pexels stok fotoğraf/video |
| `OPENAI_API_KEY` | OpenAI görsel üretimi (`gpt-image-1`) |
| `REPLICATE_API_TOKEN` | Replicate görsel/video modelleri (`visuals.replicate.image_model` / `video_model`) |

---

## Uygulama (kontrol paneli + otomatik mod)

```bash
python app/server.py --open        # Windows: start-app.bat  ·  macOS/Linux: ./start-app.sh
```

Tarayıcıda `http://127.0.0.1:8765/` açılır (yalnızca bu bilgisayardan erişilir). Panelden konu/kategori
girip **Üret** dersiniz; ilerleme ve log canlı izlenir, biten videolar oynatılır ve indirilir.
**Otomatik mod** açıkken uygulama belirlediğiniz aralıkla (ör. her 6 saatte, günde en fazla 4) kendi
kendine konu seçer, araştırır, senaryo yazar ve video üretir; görevler sırayla işlenir.

Senaryo adımı için şunlardan biri gerekir (uygulama otomatik seçer, `llm.provider: auto`):
1. `.env` → `ANTHROPIC_API_KEY` (Claude API), veya
2. bilgisayarda kurulu ve giriş yapılmış **Claude Code** (`claude` komutu; ayrı anahtar gerekmez).

**Claude Code'u panelden kurmak:** "Claude Code" kartındaki **Claude Code'u kur ve bağla** düğmesi
(Windows) bir pencere açar, resmî yükleyiciyle (`irm https://claude.ai/install.ps1 | iex`) kurar, PATH'e
ekler ve `claude auth login` ile tarayıcıda girişi başlatır (Pro/Max hesabı gerekir). Giriş bitince kart
"bağlı" olur ve **Üret**/otomatik mod senaryoları Claude Code ile yazar. **Bağlantıyı test et** kısa bir
istekle uçtan uca dener; **Claude Code'u aç** bu klasörde etkileşimli oturum açar (masaüstünde
"Claude Code (Reels)" kısayolu da oluşturulur). Elle: `scripts\install-claude.ps1` · macOS/Linux:
`bash scripts/install-claude.sh`.

Windows'ta `scripts\setup.ps1` sonunda masaüstüne **Reels Fabrikasi** kısayolu oluşturulur ve uygulama
Windows açılışında arka planda başlar (otomatik modun çalışması için). Sonradan kurmak/kaldırmak:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1 -Startup   # kısayol + açılışta başlat
powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1 -Remove    # kaldır
```

Bilgisayar uykudayken veya kapalıyken üretim yapılmaz; açıldığında zamanı geçmiş üretim ilk fırsatta başlar.

**Buluttan gelenler:** Uygulama açılışta ve 30 dakikada bir GitHub'daki `reels-videos` dalını `git fetch`
ile kontrol eder; bulutta üretilen yeni videoları (kapak, paylaşım metni, altyazıyla) `output/cloud/<tarih>/`
klasörüne indirir ve panelde "Buluttan gelenler" bölümünde gösterir ("Şimdi kontrol et" ile hemen).
Masaüstündeki **Reels Videolari** kısayolu bu klasörü açar. Var olan dosyaların üzerine yazılmaz.

Güncelleme (yeni sürümü çeker, uygulamayı yeniden başlatır, kısayolları yeniler):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1
```

## Video Stüdyosu (kendi videonu düzenle)

Panelin üstündeki **🎬 Stüdyo** bağlantısı (`http://127.0.0.1:8765/studio`):

1. **Stil öğret:** Beğendiğin bir Reels'i yükle ya da bağlantısını yapıştır (Instagram/TikTok/YouTube; yt-dlp ile
   yalnızca stil incelemesi için indirilir — gizli/girişli içerik indirilemez, o zaman dosyayı kaydedip yükle). Kesim hızı, renk (parlaklık/kontrast/doygunluk/sıcaklık),
   hareket, baskın vurgu renkleri, konuşma ve müzik ölçülür; kareler Claude'a gösterilip altyazı, başlık,
   ilerleme çubuğu ve efekt stili çıkarılır. Sistem "Bu stile ne isim verelim?" diye sorar; ad verip kaydedersin
   (`studio/styles/<ad>.json`). Claude bağlı değilse stil yalnızca ölçümlerden çıkarılır (sayfada belirtilir).
2. **Videomu düzenle:** Kendi videonu yükle (birkaç saniyeden 20+ dakikaya). Birden çok video ve fotoğraf
   (JPG/PNG/iPhone HEIC) birlikte seçilebilir: sırayla tek montajda birleştirilir — fotoğraflar kamera hareketiyle
   gösterilir, dik/yatık telefon videoları doğru döndürülür, iPhone HDR videoları soluk/patlak görünmesin diye SDR'a
   çevrilir; fotoğraf bölümleri "sessiz yer" diye kesilmez. Konuşma faster-whisper ile kelime
   kelime yazıya dökülür, sonra:
   - **En iyi anlardan kısa klipler:** Claude dökümü okuyup tek başına anlaşılır, güçlü açılışlı anları seçer ve
     başlık yazar (Claude yoksa kurallarla seçilir), ya da
   - **Tamamını düzenle:** videonun tamamı.
   Her klipte konuşma boşlukları kesilir (jump cut), görüntü 9:16'ya getirilir (bulanık arka plan / kırpma /
   siyah boşluk) veya kendi oranında kalır; stile göre renk düzenleme, kesimlerde zoom, kelime vurgulu altyazı,
   açılış başlığı, ilerleme çubuğu, beyaz flaş ve isteğe bağlı (konuşmaya göre kısılan) müzik eklenir; ses
   iyileştirilir ve -14 LUFS'a normalize edilir (ayrıntı aşağıda).
4. **Sesi iyileştir:** Herhangi bir video ya da ses kaydını (mp4/mov/m4a/mp3/wav…) yükle; ses temizlenir. Videoda
   görüntüye dokunulmaz, yalnızca ses değiştirilir. Önce/sonra dinlenebilir; çıktılar `output/enhanced/`
   (özgün ses ayrıca `-ozgun.m4a` olarak saklanır). Güç: hafif / orta / güçlü.

**Ses iyileştirme zinciri** (`scripts/reels/audiofx.py`; stüdyo, Sesim ve "Sesi iyileştir" aynı zinciri kullanır):
önce kayıt ölçülür (gürültü tabanı, SNR, kırpılma, 50/60 Hz uğultu), sonra yalnızca gerekenler uygulanır —
alçak geçiren temizlik, kırpılma onarımı, tık temizliği, uğultu çentikleri, konuşmayı koruyan Wiener gürültü
azaltma (uzun kayıtlarda parça parça), konuşma EQ'su, de-esser, seviye eşitleme (uzak/yakın konuşma), kompresör,
sınırlayıcı ve iki geçişli loudnorm. Ölçümler (orta güç, eski zincire göre): elektrik uğultusu bastırma 13 → 35 dB,
fan gürültüsü 6 → 15 dB, ASR hata oranı %25 → %20; temiz kayıt bozulmaz.
3. **Kendi kendini geliştirme:** İlk klip üretildikten sonra Claude çıktının karelerini referansla karşılaştırır
   (okunabilirlik, güvenli alan, yüzleri kapatma, referansa benzerlik, senin yazdığın istekler), stili düzeltir ve
   klibi yeniden üretir; iyileşen stil yeni sürüm olarak kaydedilir (eski sürüm `.bak` olarak saklanır).

Çıktılar `output/studio/<iş>/`: video, kapak, altyazı (`.srt`) ve kare tablosu. Yüklenen videolar
`studio/uploads/` altında kalır (silinmez). Konuşma tanıma Türkçe ve otomatik olduğu için sayı/özel adlarda
hata olabilir; yayından önce altyazıları gözden geçir. Uzun videolarda yazıya dökme CPU'da birkaç dakika sürer.

## YouTube agent skill (kanca, başlık, bölümler, Shorts)

[Jakeschincariol/youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill) (MIT) değiştirilmeden
`skills/youtube-agent/` altına alındı; 11 beceri Claude Code'da `/yt-script`, `/yt-package`, `/yt-shorts`,
`/yt-seo`, `/yt-chapters`, `/yt-edit`, `/yt-retention`, `/yt-viral`, `/yt-plan`, `/yt-comment`, `/yt-audit` olarak
çalışır (Windows'ta kurulum betiği bunları `%USERPROFILE%\.claude\skills` altına kopyalar). Araçlar İngilizce
kelime listeleriyle yazıldığı için `scripts/reels/yt_tools.py` onları **Türkçeye uyarlar** (Türkçe harfler, "sen/siz"
ekleri, "neden/nasıl", "kaybet/kaçır", Türkçe dolgu sözcükleri; Türkçe eklemeli olduğu için 7-20 kelime bandı).

Sistemde kullanıldığı yerler:
- **Senaryo:** Claude 21 kanca kalıbından 5 açılış cümlesi yazar, `rf hook` ile puanlar, en iyisini seçer
  (API modunda kanca zayıfsa 5 alternatif üretilip en yüksek puanlı seçilir). `validate` zayıf kancayı ve
  başlığı tekrar eden kapağı uyarır.
- **Stüdyo:** klip seçimi yt-shorts ilkeleriyle (tam düşünceyle başlayan, içinde dönüş olan, bir cümleyle biten
  an; ekran başlığı konuşulan ilk cümleyi tekrar etmez); her klibe açılış puanı; 3 dakikadan uzun videolarda
  YouTube kurallarına uygun **bölümler** (00:00, en az 3, her biri ≥10 sn) — YouTube açıklamasına otomatik eklenir.
- **Yayın:** her video için YouTube başlık denetimi (60/40 karakter, belirsiz kelime, büyük harf).

```bash
./rf hook "kanca 1" "kanca 2"            # puan + en zayıf özellik + öneri
./rf title "Başlık" --thumb "KAPAK YAZISI"
./rf chapters altyazi.srt                # YouTube bölümleri;  --edl : boşluk/dolgu/tekrar kesim listesi
```

## Bilgi haritası (Graphify)

[Graphify](https://github.com/Graphify-Labs/graphify) (Apache-2.0/MIT, `pip install graphifyy`):
- **İçerik haritası** (panel → 🧠 Harita): üretilen videolar (anlatım, doğrulanmış bilgiler, kaynaklar), Reel notları
  ve video geçmişi bir bilgi grafiğine dönüşür (Claude Code veya Claude API ile; ayrı anahtar gerekmez).
  Etkileşimli `graph.html`, konu toplulukları, en bağlantılı kavramlar ve "Haritaya sor". Yeni video konusu
  seçilirken `brief.json → knowledge_map` ile işlenmiş kavramlar tekrarlanmaz, bağlantılı yeni konular aranır.
  Harita 24 saatten eskiyse yeni bir video üretildiğinde kendiliğinden güncellenir.
- **Kod haritası** (yapay zekâsız, yerel, saniyeler): `python -m graphify update scripts` →
  `scripts/graphify-out/GRAPH_REPORT.md`; bulut rutini kendi kendini onarmadan önce kodda bununla gezinir.

## Reel notları (Obsidian)

Stüdyo → **3 · Reel'den not çıkar**: izlediğin bir Reels'i yükle veya bağlantısını yapıştır. Konuşma yerelde
yazıya dökülür (faster-whisper), kareler ve ekrandaki yazılar Claude'a gösterilir; **özet, önemli noktalar,
ekrandaki yazılar, doğrulanacak iddialar, video fikirleri ve konuşma metni** içeren bir Markdown notu
Obsidian kasana (`<kasa>/Reels/`, kare tablosu `_kareler/` altında) yazılır; kasa ayarlanmamışsa
`output/notes/Reels/`. Notun altındaki her fikrin yanında **video üret** vardır: fikir araştırılıp kendi özgün
senaryomuza çevrilir (esinlenme, kopya değil). Var olan notların üzerine yazılmaz.

Telefonu USB/adb ile kumanda edip Instagram'da otomatik gezinme veya yorum yapma **bilerek eklenmedi**:
Instagram kullanım koşullarına aykırıdır ve hesabın kısıtlanmasına yol açabilir. Videoları sen seçersin.

## Arka plan işlemlerini durdurma

- Paneldeki **⏻ Kapat**: uygulamayı ve arka plandaki işleri (otomatik mod, bulut eşitleme, yayın zamanlayıcısı,
  Telegram) durdurur. Kısayolla yeniden açılır.
- Tamamen durdurmak ve Windows açılışında başlamasını kapatmak için PowerShell'de:

```powershell
irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/autonomous-ai-reels-factory-x82681/reels-factory/scripts/stop-app.ps1 | iex
```

Açılışta başlatmayı geri açmak: `powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1 -Startup`.

## Sesim (kendi sesinle seslendirme)

Panelin üstündeki **🎙️ Sesim** bağlantısı (`/voice`):

1. Sese bir ad ver, **"Bu ses bana ait"** onayını işaretle ve **Sohbete başla**. Uygulama sesli soru sorar
   ("Nasılsın, bugün nasıl geçti?"…), sen mikrofona cevap verirsin; sustuğunda cevabı kendisi bitirir, yazıya döker
   ve (Claude bağlıysa) cevabına uygun yeni bir soru sorar. Sona doğru farklı tonlarda birkaç cümle okumanı ister.
   Hedef ~5 dakika konuşma (en az 1 dakika); istediğin zaman durup sonra devam edebilirsin.
2. Her kayıt **iyileştirilir**: uğultu/gürültü azaltma, boğukluk azaltma, netlik, "s" sesi yumuşatma, kompresör ve
   seviye ayarı. Sağda kendi (iyileştirilmiş) kaydını dinleyebilirsin.
3. **Bitir ve sesimi öğren:** ses perden (Hz), konuşma hızın ölçülür; kNN-VC ses dönüşümü için kayıtlarından
   eşleştirme kümesi çıkarılır ve senin sesinle bir örnek cümle üretilir. İlk seferde ses motoru (PyTorch CPU,
   ~250 MB; "Ses motorunu kur" düğmesi) ve model (~1.3 GB) indirilir.
4. **Videolarda bu sesi kullan:** bundan sonra üretilen videoların seslendirmesi senin sesinle yapılır
   (`tts.provider_chain` başındaki `my_voice`). "Benim sesimle okut" kutusundan istediğin metni dinleyebilirsin.

Nasıl çalışır: metin önce Türkçe nöral sesle (edge-tts, kelime zamanlarıyla, senin konuşma hızına göre) okunur;
sonra kNN-VC (MIT lisansı, yerel, ücretsiz; `scripts/reels/knnvc/`) bu okumayı senin kayıtlarındaki ses
parçalarıyla aynı uzunlukta yeniden kurar — ses rengi ve perde senden, tonlama temel sesten gelir; kelime zamanları
korunduğu için altyazı senkronu bozulmaz. Ölçülen sonuç (1,7 dk kayıtla yapılan testte): perde hedefle aynı
(107 Hz), anlaşılırlık temel sesin %89'una karşı %78. Daha uzun ve temiz kayıt sonucu iyileştirir. Profesyonel
klonlama kalitesi (ElevenLabs gibi ücretli hizmetler) değildir; tonlama tam olarak senin tonlaman olmaz.

Kurallar: yalnızca **kendi sesini** (veya yazılı izni olan birinin sesini) kopyala. Kayıtlar ve ses profili yalnızca
bu bilgisayarda (`studio/voices/`) kalır; buluttaki otomatik üretim bu sesi kullanmaz (edge-tts kullanır).
Bazı platformlar yapay zekâ ile üretilmiş sesin etiketlenmesini ister.

## Yayın: onay, otomatik paylaşım, kanal logosu (📤 Yayın)

`/publish` sayfası üç bölümden oluşur.

**Kanallar ve hesaplar.** Kanal adı, videoya yazılacak kullanıcı adı, logo (PNG) ve konumu, onay süresi
(varsayılan 2 saat), "onay gelmezse otomatik yayınla", varsayılan platformlar ve otomatik kuyruk kaynakları
(bu bilgisayarda üretilenler / buluttan gelenler / Stüdyo klipleri). Birden çok kanal açılabilir; her videoda
kanal ve platformlar ayrı ayrı değiştirilebilir ("sadece Instagram'a paylaş, Facebook'a paylaşma" gibi).
Logo ve ad, yayından önce videonun sağ/sol üst köşesine (platform arayüzünün altına) işlenir.

| Platform | Gerekenler | Bilinen kısıt |
|---|---|---|
| Instagram (Reels) | İşletme/İçerik Üreticisi hesabı + bağlı Facebook Sayfası; Meta geliştirici uygulaması ve `instagram_content_publish` izinli belirteç | Meta uygulama incelemesi gerekebilir; kendi hesabın için geliştirme modunda çalışır |
| Facebook (Sayfa Reels) | Aynı Meta belirteci (`pages_manage_posts`) | — |
| YouTube Shorts | Google Cloud OAuth istemcisi (YouTube Data API v3), "Google ile bağlan" | Google denetiminden geçmemiş projelerin yüklemeleri **gizli** kalır |
| TikTok | TikTok geliştirici uygulaması (Content Posting API), erişim + yenileme belirteci | Denetimden (audit) geçmemiş uygulamalar yalnızca **"sadece ben"** paylaşabilir |

Belirteçler yalnızca `.env` dosyasına yazılır (uygulama geri göstermez, loglarda maskelenir).

**Onay ve yayın.** Kuyruğa giren her video: logo/ad işlenir → kitle testi yapılır → **onay bekler**. Geri sayım
görünür; **Onayla** hemen yayınlar, **Reddet** asla yayınlamaz, **Ertele** 2 saat ekler, paylaşım yazısı ve
platformlar düzenlenebilir. Süre dolunca yanıt yoksa (otomatik yayın açıksa) seçili platformlara yüklenir.
Bir platform hata verirse diğerleri yine yayınlanır; tekrar denemede yalnızca başarısız olanlar gönderilir.
**Telegram** (isteğe bağlı, Ayarlar): video + Onayla/Reddet/Ertele düğmeleri telefona gelir. Bilgisayar ve
uygulama açık olmalıdır (otomatik yayın ve Telegram dinleme uygulamada çalışır).

**Kitle testi — "Bu video nasıl?"** Yayından önce:
- **Claude paneli** (varsayılan): videonun kareleri, metni ve paylaşım yazısı Claude'a gösterilir; 10 farklı Türk
  izleyici profilinin tepkisi canlandırılır → 0-100 puan, açılış/anlaşılırlık/görsel puanları, tahmini izlenme
  oranı, örnek yorumlar, riskler (telif, hatalı bilgi…) ve öneriler.
- **MiroFish** ([github.com/666ghj/MiroFish](https://github.com/666ghj/MiroFish), AGPL-3.0): kendi bilgisayarında
  `docker compose up -d` ile çalıştırdığın MiroFish sunucusunun adresini (ör. `http://localhost:5001`) Ayarlar'a
  yaz. Video içeriği tohum belge olarak verilir, çok ajanlı sosyal medya simülasyonu çalışır, raporu buraya gelir.
  MiroFish kendi LLM ve Zep anahtarlarını ister ve çok sayıda LLM çağrısı yapar (maliyetli; `max_rounds` 10).
  Simülasyon Twitter/Reddit benzeri ortamlardadır. Bu bağlayıcı MiroFish'in arka uç kodundan yazıldı; çalışan
  bir MiroFish ile henüz denenmedi.
Her iki sonuç da **tahmindir**, gerçek izlenme verisi değildir.

## Video klipler

`visuals.prefer_video: true` iken fotoğraf sahnelerinde önce konuyla ilgili **video klip** aranır: Pexels ve
Pixabay (ücretsiz anahtar; Yayın → Ayarlar) ve anahtarsız NASA video arşivi. Klip başlığında sorgu kelimesi
geçmeli (`video_min_relevance`); NASA arşiv klipleri sıklıkla üzerine yazılmış metin, jenerik veya konuşan
kişi içerdiğinden Claude üç karesini denetler ve uygun değilse kullanılmaz (Claude yoksa arşiv klibi hiç
kullanılmaz). Uzun kliplerde giriş/jenerik atlanır, kısa klipler döngülenir. Uygun klip yoksa fotoğraf + kamera
hareketi + hareketli grafik kullanılır.

### Kendi fotoğraf/videolarınla yeni video

Panelde "Yeni video" formundaki **Kendi medyam** alanından fotoğraf, video ve müzik yükleyebilirsin. Bunlar
görevin `user_media/` klasörüne kopyalanır, senaryo yazılırken Claude'a bildirilir ve önce `visual.user` ile
işaretli sahnelere, sonra boş fotoğraf/video sahnelerine yerleştirilir (stok aramasının önüne geçer). Yüklenen
ses dosyası müzik olarak kullanılır.

### Yapay zekâ görsel ve video (isteğe bağlı)

`doctor` çıktısında `ai_gorsel: YOK` / `ai_video: YOK` görünüyorsa anahtar tanımlı değildir; o zaman gerçek
kaynaklar + kamera hareketi + hareketli grafik kullanılır. Etkinleştirmek için **📤 Yayın → Ayarlar → Yapay zekâ
görsel ve video** kartına anahtar gir:

| Anahtar | Ne açar | Maliyet |
|---|---|---|
| `HF_TOKEN` (huggingface.co → Settings → Access Tokens, "Make calls to Inference Providers" izni) | FLUX.1-schnell görsel | Ücretsiz hesapta küçük aylık kota; bitince 402 alınır ve atlanır |
| `REPLICATE_API_TOKEN` | FLUX görsel (~0,003 $) + Wan 2.2 video klip (~0,05 $ / 5 sn) | Ücretli; `budget.max_ai_images_per_video` (8) / `max_ai_video_clips_per_video` (4) ile video başına sınırlı |
| `OPENAI_API_KEY` | gpt-image görsel | Ücretli |

Yapay zekâ yalnızca gerçek kaynak bulunamayınca devreye girer (kategori `visual_providers` listesinde en sonda).

## Bulutta otomatik çalışma (Claude Code on the web)

Zamanlanmış bir bulut görevi günde iki kez (İstanbul saatiyle ~09:47 ve ~18:47) `cloud/ROUTINE.md`
dosyasını izler: kurulum → `selftest` (hata varsa kendisi onarır ve doğrulanmış düzeltmeyi gönderir) →
gelen kutundaki **konusu "Reels:" ile başlayan** e-postaları metin olarak alıp (görselleri kendisi çizerek)
video üretir → metin yoksa kendi konusunu araştırıp video üretir → videoyu GitHub `reels-videos` dalına
yükler ve bağlantısını e-postayla gönderir. Metin göndermek için kendine şu e-postayı at:

```
Konu:  Reels: Arıların dansı
Gövde: (videoya dönüşmesini istediğin metin)
```

Gövdeye `görsel: arama` yazarsan çizim yerine lisanslı/arama görselleri kullanılır.

E-posta okuma, zamanlanmış göreve Gmail bağlantısı eklenmişse çalışır (claude.ai → Routines → görev →
Connectors → Gmail). Bağlantı yoksa metinlerini GitHub'da **`reels-videos` dalındaki `inbox/` klasörüne**
`.txt` dosyası olarak ekle (GitHub mobil uygulaması/web: Add file → Create new file). İşlenen dosyalar
`inbox/done/` altına taşınır; video bağlantıları çalışma sonunda telefon bildirimiyle gelir.

## Kullanım

### A) Claude Code ile (önerilen, anahtar gerektirmez)

Claude Code'a örneğin şunu söyleyin: *"bilim-uzay kategorisinde yeni bir reels üret"*.
Ajan `skills/reels-production/SKILL.md` akışını izler: görev açar, web'de araştırır, kaynaklı
senaryo yazar, görselleri gözle denetler, üretir, QC raporunu ve kontak tablosunu inceler.

Elle aynı akış:

```bash
python scripts/factory.py new --category bilim-uzay --topic "Ay'ın Dünya'dan uzaklaşması"
# projects/<görev>/brief.json'u okuyun, araştırın ve projects/<görev>/script.json'u yazın
python scripts/factory.py validate <görev>
python scripts/factory.py candidates <görev> s1          # görsel adaylarını gözle seçmek için
python scripts/factory.py produce <görev>
python scripts/factory.py status <görev>
```

### B) Tam otonom (Claude API)

`config/settings.yaml → llm.provider: anthropic` ve `.env → ANTHROPIC_API_KEY`:

```bash
python scripts/factory.py run --count 3                  # kategori ağırlıklarına göre 3 video
python scripts/factory.py run --category tarih --count 1
```

Zamanlanmış çalıştırma (ör. her gün 09:00): `0 9 * * * cd /yol/reels-factory && python3 scripts/factory.py run >> logs/cron.log 2>&1`

Otonom modda görsel seçimi metin tabanlı sıralamaya dayanır; yayın öncesi
`projects/<görev>/qc/contact_sheet.jpg` dosyasına göz atmanız önerilir.

### Çıktılar

| Yol | İçerik |
|---|---|
| `output/videos/<tarih>-<slug>.mp4` | Son video |
| `output/thumbnails/<tarih>-<slug>.jpg` | Kapak karesi |
| `output/captions/<tarih>-<slug>.srt` | Platforma yüklenecek altyazı |
| `output/captions/<tarih>-<slug>.txt` | Paylaşım metni + hashtag + kaynaklar + lisans atıfları |
| `projects/<görev>/` | Bütün ara ürünler: script, ses, görseller, HyperFrames projesi, QC raporu |
| `logs/<görev>.log` | Görev logu (gizli bilgiler maskelenir) |

`projects/<görev>/composition/` bir HyperFrames projesidir: `npx hyperframes preview` ile
tarayıcıda açılıp elle düzenlenebilir.

---

## Üretim hattı ayrıntıları

| Adım | Ne yapar | Hata durumunda |
|---|---|---|
| script | `script.json` doğrulama: yapı, süre tahmini, yazım/noktalama, sembol, kaynak zorunluluğu | Üretim başlamaz |
| voice | Sahne başına TTS, baş/son sessizlik kırpma, sağlayıcı kelime sınırlarını senaryo kelimelerine hizalama | 3 deneme (2/4/8 sn) → sonraki ses → sonraki sağlayıcı |
| captions | Ses saattir: sahne kesimleri sesi 0,18 sn önden karşılar (J-cut), geçiş örtüşmesi; 2–3 kelimelik gruplar; SRT | — |
| visuals | Sağlayıcı zinciri, lisans filtresi (NASA ortak kurum görselleri, NC/ND/SA lisanslar elenir), çözünürlük, tekrar (dHash) kontrolü, bulanık arka plan, atıf kaydı, inceleme görüntüsü | Sonraki aday/sağlayıcı → hareketli grafik arka plan (uyarı) |
| music | Kütüphane → Openverse (vokal ayıklama: faster-whisper) → prosedürel; son 5 videoda kullanılan parça atlanır | Müziksiz devam (uyarı) |
| compose | Gerçek font ölçümüyle metin yerleşimi, güvenli alan denetimi, HyperFrames HTML + GSAP, lint | Güvenli alan/lint hatasında durur |
| render | `hyperframes render` (CRF 18) | 2 işçiyle yeniden dener |
| mix | Konuşma işleme (high-pass + kompresör, −16 LUFS), müzik ducking (−15 dB), efekt yerleşimi, iki geçişli loudnorm (−14 LUFS, −1,5 dBTP), mux | — |
| qc | Aşağıdaki kontroller + otomatik düzeltmeler | Siyah karede ilgili sahneler grafikle yeniden üretilir; geçemezse görev `failed` |
| export | `output/` dosyaları, geçmiş kaydı (konu/müzik tekrarını önler) | — |

### Kalite kontrolleri

Dosya açılıyor mu · çözünürlük 1080×1920 · dikey · 30 fps · H.264/yuv420p · AAC 48 kHz ·
A/V süre farkı ≤ 0,12 sn · beklenen süre · hedef süre aralığı · loudness −14 ±1,5 LUFS ve true peak ·
bozuk kare (tam çözümleme) · siyah ekran · hareketsiz bölüm · gereksiz sessizlik · son bölüm payı ·
güvenli alanlar · **konuşma tanıma ile anlaşılırlık (WER)** · **altyazı-ses senkron sapması** ·
kontak tablosu (görsel-senaryo uyumunun gözle denetimi için).

Otomatik düzeltmeler: yeniden kodlama (format/fps/codec), loudness yeniden normalizasyonu, ses/video
süre eşitleme, siyah kare kaynağı olan sahnelerin grafikle yeniden üretimi.

### Güvenli alanlar (1080×1920)

Üst 200 px'e yazı konmaz; 1330 px altı yalnızca dekor (açıklama, kullanıcı adı); 820 px altında
sağdaki buton sütunu nedeniyle metin 124 px kenar boşluğuyla ortalanır; altyazı bandı 1130–1330 px.
Bütün metin kutuları ölçülür ve QC'de raporlanır (`config/settings.yaml → safe_zone`).

---

## Yapılandırma

Tüm ayarlar `config/settings.yaml` içindedir: çıktı formatı, güvenli alanlar, marka renkleri/font,
**kategoriler** (ton, hedef kitle, örnek konular, görsel sağlayıcı sırası, müzik sorguları, ağırlık),
TTS sesleri/hızı, altyazı stili, müzik/efekt seviyeleri, loudness hedefleri, QC eşikleri,
**maliyet sınırları** (`budget.*`: video başına AI görsel/klip ve LLM çağrısı üst sınırları) ve
yeniden deneme politikası.

Yeni kategori eklemek için `categories:` altına bir blok ekleyin.

---

## Dosya yapısı

```
reels-factory/
├── CLAUDE.md                     # Claude Code proje rehberi
├── README.md
├── config/settings.yaml          # bütün ayarlar (gizli bilgi yok)
├── skills/reels-production/
│   ├── SKILL.md                  # ajan üretim akışı
│   └── script-format.md          # senaryo biçimi ve yazım kuralları
├── scripts/
│   ├── factory.py                # CLI
│   ├── setup.sh
│   └── reels/                    # pipeline, job, tts, captions, visuals, audio, compose, qc, llm, doctor
├── assets/
│   ├── fonts/                    # Montserrat (SIL OFL)
│   ├── music/                    # kendi lisanslı müzikleriniz + licenses.yaml
│   ├── sfx/                      # isteğe bağlı kendi efektleriniz
│   └── templates/                # HyperFrames şablonları (sahne, altyazı, üst katman)
├── projects/                     # görev klasörleri (git'e eklenmez)
├── output/{videos,thumbnails,captions}
├── examples/                     # örnek üretim (senaryo, QC raporu, video)
└── logs/
```

---

## Lisans ve telif notları

> **`visuals.license_mode`** — `strict` (önerilen): yalnızca kullanım izni doğrulanmış medya.
> `any`: lisans denetlenmez (Openverse'te bütün lisanslar, Vikipedi'deki adil kullanım görselleri dahil);
> kaynaklar yine kaydedilir ve paylaşım metnine "kullanım hakkı doğrulanmadı" notu düşülür.
> **Telif riski kullanıcıdadır**: platformlar telif bildirimiyle videoyu kaldırabilir veya hesaba ihtar verebilir.
> Şu an bu depoda kullanıcı isteğiyle `any` açıktır.
>
> **`music.license_mode`** — aynı mantık müzik için: `any` iken `assets/music/` içindeki her dosya (sanatçı adıyla
> otomatik eşleşme, `music.file` ile belirli parça) ve Openverse'teki bütün lisanslar kullanılır. Şarkı indirme
> (YouTube/Spotify vb.) özelliği yoktur; parçaları kendiniz edinip klasöre koyarsınız. Şu an `any` açıktır.
>
> Kişi görselleri `visual.subject` ile metin üzerinden doğrulanır (Vikipedi maddesinin ana görseli veya
> adın başlık/açıklamada bitişik geçmesi); yüz tanıma kullanılmaz.

- **Görseller:** NASA görselleri genel olarak kamu malıdır (NASA medya yönergeleri; NASA logosu/
  kişilerin onay izlenimi verecek kullanımlar hariç). ESA/JAXA gibi ortak kurum ve telif ibareli
  görseller otomatik elenir. Openverse'ten yalnızca CC0, kamu malı ve CC BY; CC BY atıfları paylaşım
  metnine eklenir.
- **Müzik:** Openverse'ten yalnızca CC0 / CC BY (atıf paylaşım metninde). Ticari kanallar için kendi
  lisanslı kütüphanenizi önerilir.
- **Efektler:** HyperFrames ile gelen Pixabay Content License dosyaları (ticari kullanım serbest).
- **Seslendirme:** edge-tts, Microsoft Edge'in "Sesli Oku" hizmetini kullanır; resmî bir API değildir ve
  hizmet koşulları ticari kullanımı açıkça düzenlemez. Ticari yayınlar için aynı seslere sahip
  **Azure AI Speech** veya **ElevenLabs** gibi lisanslı bir hizmet önerilir. Piper'ın Türkçe sesi
  CC BY-NC-SA (ticari olmayan) olduğundan varsayılan olarak kapalıdır (`tts.allow_noncommercial`).
- **Font:** Montserrat — SIL Open Font License (`assets/fonts/OFL-Montserrat.txt`).
- **Araçlar:** HyperFrames (Apache-2.0), GSAP (GreenSock standart ücretsiz lisansı), FFmpeg.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Windows'ta sürekli CMD penceresi açılıp kapanıyor | Kurulum komutunu yeniden çalıştırıp güncelleyin; alt süreçler (ffmpeg, git, node, claude) artık penceresiz başlatılır. |
| `edge-tts ... CERTIFICATE_VERIFY_FAILED` | Kurumsal proxy/CA: `SSL_CERT_FILE` ortam değişkenini CA paketine yönlendirin (sistem otomatik ekler). |
| `tr-TR-AhmetNeural ses döndürmedi` | Hizmet tarafı geçici sorun; zincirdeki sonraki ses kullanılır. |
| Openverse `401 page_size` | Anonim istek sınırı (20); sistem buna uyar. Günlük 200 arama sınırı vardır. |
| Wikimedia `429` | Bazı ağlarda Wikimedia indirmeleri sınırlanır; sistem sonraki adaya geçer. `visuals.user_agent` alanına iletişim bilgisi ekleyin. |
| Render yavaş | `render.workers` (varsayılan 4); 45 sn video 4 çekirdekte ≈ 2 dk. |
| `HyperFrames bulunamadı` | `npm install` (reels-factory klasöründe). |
| Görsel alakasız | `factory.py candidates` ile inceleyin, `visual.pick`/`query`/`crop`/`fit` ile düzeltin, `produce` tekrar. |

---

## Örnek

`examples/venus-gun-yil/`: "Venüs'te Bir Gün, Bir Yıldan Uzun" — 52,7 sn, 7 sahne, NASA görselleri,
Openverse CC BY müzik, bütün QC kontrolleri geçti (WER ≈ %8–11, altyazı senkron sapması medyan ≈ 50 ms).

## Yol haritası

- Video üretim hizmeti bağlandığında sahne başına gerçek AI klipleri (bağdaştırıcı hazır).
- Otonom modda Claude görsel denetimi (kontak tablosunun model tarafından incelenmesi).
- Azure AI Speech bağdaştırıcısı (ticari lisanslı aynı nöral sesler).
- Platformlara otomatik yükleme (kullanıcı onayı ile).
