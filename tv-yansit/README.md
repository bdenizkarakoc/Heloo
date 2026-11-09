# TV Yansıt

Bilgisayar ekranını televizyona yansıtır. Bilgisayar Miracast'i (Windows "Kablosuz ekrana bağlan") desteklemese de
çalışır, çünkü görüntüyü Wi-Fi Direct yerine **ev modemi üzerinden** gönderir. Bu yüzden menzil modemin
menzili kadardır: TV başka odada olsa da olur.

## Kurulum (Windows)

1. Python 3.10 veya üstü (python.org, kurarken "Add to PATH" işaretli olsun).
2. `TV Yansit.bat` dosyasına çift tıklayın. ffmpeg yoksa `winget` ile kendisi kurar, sonra bir kez daha açın.
3. Windows Güvenlik Duvarı sorarsa **Özel ağlar** için izin verin. Yoksa TV bilgisayara bağlanamaz.

Panel tarayıcıda açılır (`http://127.0.0.1:8765/`).

## Yansıtmanın iki yolu

| | Yol 1: DLNA | Yol 2: TV tarayıcısı |
|---|---|---|
| Ne yapılır | Panelde **TV'leri ara**, TV'yi seçin, **TV'ye gönder**'e basın | TV'nin internet tarayıcısına paneldeki adresi yazın (ör. `http://192.168.1.5:8765/4821`) |
| Ses | TV'den gelir (Stereo Karışımı açıksa) | Bilgisayardan gelir |
| Gecikme | 2-5 sn (film ve dizi için uygun) | Yaklaşık 0,2-0,5 sn (masaüstü ve oyun için) |
| Görüntü | H.264, ekran kartının donanım kodlayıcısıyla (NVIDIA, Intel, AMD) | MJPEG. Bağlantı zayıflayınca kare atlar, gecikme birikmez |

### Modem yoksa: bilgisayarın kendi Wi-Fi'si
Panelde **Bilgisayarın Wi-Fi'sini aç**'a basın. Windows "Mobil etkin nokta" açılır ve bilgisayar kendi Wi-Fi
ağını yayınlar. Panelde gösterilen ağ adını ve şifreyi TV'nin Wi-Fi ayarlarına girin, ardından Yol 1 ya da Yol 2'yi
kullanın. Bu ağda bilgisayarın adresi `192.168.137.1` olur ve TV tarayıcısı adresi panelde ayrıca gösterilir.
Bant seçimi: **2,4 GHz** daha uzağa ulaşır (önerilen), **5 GHz** daha hızlıdır ama menzili kısadır. Düğme hata
verirse **Windows ayarlarını aç** ile etkin noktayı elle açın; bunun için bilgisayarda Wi-Fi kartı olmalı.

Bilgisayar Miracast destekliyorsa panelde **Yansıt panelini aç (Win+K)** düğmesi de işe yarar.

### TV'den ses almak için (Yol 1)
Ses → Kayıt cihazları → **Stereo Karışımı**'na sağ tıklayıp Etkinleştir'i seçin. Listede yoksa "Devre dışı
cihazları göster"i açın. Hiç yoksa ücretsiz VB-Audio Virtual Cable kurun; "CABLE Output" da tanınır.

## Kalite ve menzil

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
