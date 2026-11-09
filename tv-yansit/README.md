# TV Yansıt

Bilgisayar ekranını televizyona yansıtır. Bilgisayar Miracast'i (Windows "Kablosuz ekrana bağlan") desteklemese de
çalışır, çünkü görüntüyü Wi-Fi Direct yerine **ev modemi üzerinden** gönderir. Bu yüzden menzil modemin
menzili kadardır: TV başka odada olsa da olur.

## Kurulum (Windows)

**Uygulama olarak (önerilen):** PowerShell'de depo klasöründen şunu çalıştırın:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tv-yansit\kur.ps1
```

Ya da `kur.ps1`'in içeriğini PowerShell'e yapıştırın. Uygulama `%LOCALAPPDATA%\Programs\TV Yansit` klasörüne,
kendi Python'u ve kendi `TV Yansit.exe` dosyasıyla kurulur. Bilgisayardaki Python'a bağlı değildir. Başlat menüsünde
ve Masaüstünde simgesiyle görünür, görev çubuğuna sabitlenebilir. **Ayarlar → Uygulamalar → TV Yansıt → Kaldır**
ile tamamen kaldırılır. Güvenlik duvarı izni için Windows bir kez yönetici onayı ister. Gerçek Xbox kolu için
önce `$OyunKolu = $true` yazıp sonra kur.ps1'in içeriğini yapıştırın. Aynı komut güncelleme için de kullanılır.

**Elle:**

1. Python 3.10 veya üstü (python.org, kurarken "Add to PATH" işaretli olsun).
2. `TV Yansit.bat` dosyasına çift tıklayın. ffmpeg yoksa `winget` ile kendisi kurar, sonra bir kez daha açın.
3. Windows Güvenlik Duvarı sorarsa **Özel ağlar** için izin verin. Yoksa TV bilgisayara bağlanamaz.

Panel tarayıcıda açılır (`http://127.0.0.1:8780/`).

## Yansıtmanın iki yolu

| | Yol 1: DLNA | Yol 2: TV tarayıcısı |
|---|---|---|
| Ne yapılır | Panelde **TV'leri ara**, TV'yi seçin, **TV'ye gönder**'e basın | TV'nin internet tarayıcısına paneldeki adresi yazın (ör. `http://192.168.1.5:8780/4821`) |
| Ses | TV'den gelir | TV'den gelir (~60 ms gecikme) |
| Gecikme | 1-3 sn (TV'nin oynatıcısı kendi tamponunu tutar; film ve dizi için) | En düşük: genellikle 30-80 ms (masaüstü ve oyun için) |
| Görüntü | H.264, ekran kartının donanım kodlayıcısıyla (NVIDIA, Intel, AMD) | MJPEG. Bağlantı zayıflayınca kare atlar, gecikme birikmez |

### Modem yoksa: bilgisayarın kendi Wi-Fi'si
Panelde **Bilgisayarın Wi-Fi'sini aç**'a basın. Windows "Mobil etkin nokta" açılır ve bilgisayar kendi Wi-Fi
ağını yayınlar. Panelde gösterilen ağ adını ve şifreyi TV'nin Wi-Fi ayarlarına girin, ardından Yol 1 ya da Yol 2'yi
kullanın. Bu ağda bilgisayarın adresi `192.168.137.1` olur ve TV tarayıcısı adresi panelde ayrıca gösterilir.
Bant seçimi: **2,4 GHz** daha uzağa ulaşır (önerilen), **5 GHz** daha hızlıdır ama menzili kısadır. Düğme hata
verirse **Windows ayarlarını aç** ile etkin noktayı elle açın; bunun için bilgisayarda Wi-Fi kartı olmalı.

Bilgisayar Miracast destekliyorsa panelde **Yansıt panelini aç (Win+K)** düğmesi de işe yarar.

### TV'yi bağlamak (Yol 2)
- **LG TV:** Panelde TV'yi seçin ya da IP adresini yazın (TV'de Ayarlar → Ağ'da yazar), **TV'de aç**'a basın.
  İlk seferde TV'de izin sorusu çıkar; kumandayla **Kabul et**'e basın. TV'nin tarayıcısı sayfayı kendisi açar.
  Sonraki seferlerde soru çıkmaz.
- **Her TV:** TV'nin tarayıcısında panelde yazan kısa adresi yazın (ör. `192.168.1.16:8780`). Açılan sayfada
  panelde görünen **4 haneli kodu** kumandanın rakam tuşlarıyla girin. Kod her açılışta değişmez; TV'nin tarayıcı
  geçmişinden tekrar açabilirsiniz. Paneldeki **Yeni kod** düğmesi kodu değiştirir.
- Bağlantı zaten doğrudandır: bilgisayar ve TV aynı Wi-Fi'de konuşur, internete çıkılmaz.

### TV'de "Bu web sayfası kullanılamıyor" çıkarsa
- Adresi **http://** ile başlayarak, panelde yazdığı gibi eksiksiz yazın (ör. `http://192.168.1.16:8780/2391`).
- LG gibi bazı TV'ler adresi kendiliğinden **https://** ile açar. Uygulama aynı portta https'yi de destekler ama
  sertifika bu bilgisayarın kendisine ait olduğu için TV "bağlantı gizli değil" uyarısı gösterebilir. Böyle olursa
  **Gelişmiş → Devam et**'i seçin; bu bir kez yeterlidir.
- Bilgisayar ile TV aynı Wi-Fi'de olmalı. Panelin açık olduğundan emin olun (TV Yansıt penceresi).

### Ses
Bilgisayarın sesi, Windows'un ses çıkışından doğrudan yakalanır (WASAPI). Stereo Karışımı ya da ek sürücü
gerekmez. Yakalanamazsa Stereo Karışımı ya da VB-Audio "CABLE Output" denenir. Ses iki yolda da TV'den çıkar. TV
tarayıcısı ilk açılışta izin isterse ekranda "Ses için Tamam'a basın" yazar.

## TV'den kumanda: klavye, fare, oyun kolu

TV'ye takılı (USB ya da Bluetooth) klavye, fare ve oyun kolu, TV kumandasının ok, Tamam ve Geri tuşları
bilgisayarı yönetir. Bu özellik **Yol 2 (TV tarayıcısı)** ile çalışır. DLNA'da TV'nin oynatıcısı tuşları iletmez.

1. Kumanda varsayılan olarak açıktır. İsterseniz paneldeki **TV'den kumandayı aç** kutusuyla kapatabilirsiniz.
2. TV tarayıcısında adresi açın. Sağ üstte "Kumanda açık" yazar. İlk tıklama yalnızca tam ekran yapar.

| TV'de | Bilgisayarda |
|---|---|
| Fare / sihirli kumanda imleci | Fare (görüntüde nereye tıklarsanız bilgisayarda orası) |
| Klavye | Klavye. Harfler gerçek tuş olarak gider, oyunlarda W/A/S/D basılı tutulabilir. Ş, ğ, ü gibi harfler aynen yazılır |
| TV kumandası, **fare modu** (varsayılan) | Oklar imleci yürütür (basılı tutunca hızlanır), Tamam sol tık, Yeşil sağ tık |
| TV kumandası, **ok tuşu modu** | Ok tuşları, Enter; Geri Esc'tir; Oynat/Duraklat medya tuşlarıdır |
| Modu değiştirmek | **Kırmızı** tuş ya da **Tamam'a uzun basmak** (gerçek fare/klavye kullanılınca kendiliğinden ok tuşu moduna geçer) |
| Oyun kolu | Aşağıya bakın |

**Oyun kolu iki şekilde çalışır:**
- **Gerçek Xbox kolu olarak (oyunlar için önerilen):** ViGEmBus sürücüsünü kurun
  (github.com/nefarius/ViGEmBus/releases), ardından `python -m pip install vgamepad` çalıştırın ve uygulamayı yeniden
  açın. Bilgisayarda bir Xbox 360 kolu belirir; Steam, Big Picture ve oyunlar onu doğrudan tanır. 4 kola kadar desteklenir.
- **Kurulum olmadan:** Kol fare ve klavye gibi çalışır. Sol çubuk fareyi, sağ çubuk kaydırmayı yönetir. A sol tık,
  X sağ tık, B Esc, Y Enter'dır. Yön tuşları ok tuşlarına, LB/RB Page Up/Down'a, Back Tab'a, Start Windows tuşuna karşılık gelir.

Notlar: TV tarayıcısının oyun kolunu tanıması tarayıcıya bağlıdır (çoğu yeni Samsung, LG ve Android TV tanır).
Windows, yönetici olarak açılmış pencerelere başka programın tuş göndermesine izin vermez. Bu pencereleri
kumandayla kullanmak için TV Yansıt'ı da yönetici olarak açın. Basılı kalan tuşlar, TV sayfası kapanınca ya da
kumanda kapatılınca bırakılır. Aynı ağdaki bir cihaz PIN'i 30 kez yanlış girerse engellenir.

## Gecikme

**Gerçek video (H.264):** TV'nin tarayıcısı destekliyorsa (yeni LG, Samsung ve Android TV'lerin çoğu), görüntü JPEG
resimleri yerine gerçek video olarak gider. Bilgisayarın ekran kartı kodlar, TV kendi video çipiyle çözer. JPEG'e göre
yaklaşık 5 kat az veri gider ve gecikme düşer. Kareler hazır olur olmaz itilir. TV geride kalırsa bir sonraki anahtar
kareye atlar (en fazla yarım saniyede bir anahtar kare gelir), böylece gecikme birikmez. Tarayıcılar bunu yalnızca
**https://** ile açılan sayfada izin verir. TV http:// ile açtıysa panel "https:// ile açın" der. TV'nin sol üstünde
"H.264" yazıyorsa bu yol çalışıyordur. TV desteklemiyorsa uygulama kendiliğinden JPEG yöntemine döner.


Yol 2'de TV tek kare ister, bilgisayar en yeni kareyi gönderir. Kare gelir gelmez bir sonraki istenir ve bu
sırada gelen kare çizilir. Arada hiç kare birikmediği için ağ yavaşlarsa gecikme büyümez, yalnızca fps düşer.
Ekran, ffmpeg 6 ve sonrasında **Masaüstü Çoğaltma** (ddagrab) yöntemiyle ekran kartından kopyalanır. Bu yöntem
yoksa gdigrab kullanılır ve giriş tamponu kapalıdır. TV ekranının sol üstünde fps ve ağ gecikmesi (ms) görünür;
bu sayıya yakalama ve kodlama süresi dahil değildir. DLNA'da H.264 ultra düşük gecikme ayarıyla kodlanır
(B-kare yok, küçük tampon, saniyede bir anahtar kare). Yine de TV'nin oynatıcısı birkaç saniyelik tampon tutar, bu yüzden oyun için Yol 2'yi kullanın.

Daha da düşürmek için: Bilgisayarı kabloyla modeme bağlayın, TV'yi 5 GHz ağa alın, TV'de **Oyun modu**nu açın
(TV'nin görüntü işleme gecikmesi 50-100 ms düşer) ve Lossless Scaling'in kare üretimini kapatın (kare üretimi ek gecikme getirir).

## Kalite ve menzil

- **Ultra düşük gecikme**: 540p 60 fps. TV'nin tarayıcısı yavaşsa ya da Wi-Fi zayıfsa (sol üstte fps 60'tan düşükse).
- **En düşük gecikme** (varsayılan): 720p 60 fps. Küçük kareler ağda hızlı gider, oyun ve fare için uygundur.
- **Yüksek kalite**: 1080p 30 fps, 15 Mbit/sn
- **Akıcı**: 1080p 60 fps, oyun için
- **Uzak menzil**: 720p, 5 Mbit/sn. Saniyede bir anahtar kare gönderdiği için kopmalardan hızlı toparlanır. TV
  modemden uzaksa ya da görüntü takılıyorsa bunu seçin.
- **4K**: 2160p, güçlü ağ ister (5 GHz Wi-Fi ya da kablo)

Menzil için ipuçları: Bilgisayarı kabloyla modeme bağlamak en büyük farkı yaratır. TV'yi modemin 5 GHz ağına
bağlayın; uzaksa 2,4 GHz daha uzağa ulaşır. Gerekirse Wi-Fi tekrarlayıcı ya da mesh kullanın.

## Lossless Scaling

"Yansıtma başlarken Lossless Scaling'i kendiliğinden aç" işaretliyse yansıtma başlarken Lossless Scaling açılır
(Steam kütüphanesindeki `LosslessScaling.exe`; bulunamazsa `steam://rungameid/993090`). Açıksa tekrar açılmaz.
Ölçeklenecek oyun ya da pencere seçimi Lossless Scaling'in kendi kısayoluyla yapılır.

## Steam'den açmak

Steam'i tamamen kapatın, ardından paneldeki **Steam'e ekle**'ye basın. Uygulama her Steam hesabının
kütüphanesine "Steam dışı oyun" olarak eklenir (`TV Yansıt`); Big Picture ve Steam Link'ten de açılır.
Eklemeden önce `shortcuts.vdf` dosyasının yedeği alınır (`shortcuts.vdf.yedek-…`).
Elle eklemek isterseniz: Steam → Oyunlar → Steam dışı bir oyunu kütüphaneme ekle → `TV Yansit.bat`.

## Güvenlik

Panel ve ayarlar yalnızca bu bilgisayardan açılır. TV adresinin sonundaki 4 haneli sayı her açılışta değişir;
onu bilmeyen biri aynı ağda olsa bile ekranı göremez.

## Komut satırı

```bash
python tv_yansit.py                 # panel
python tv_yansit.py --ara           # ağdaki TV'leri listele
python tv_yansit.py --kaynak tum    # bütün monitörler (varsayılan: ana ekran)
python -m pytest tests -q           # testler (ffmpeg varsa uçtan uca akış testi de çalışır)
```
