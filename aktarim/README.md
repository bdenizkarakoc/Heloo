# Aktarım — bilgisayar ↔ telefon

Bilgisayar ile **iPhone (iOS)** ve **Samsung / Android** telefon arasında fotoğraf, video, belge, dosya ve yazı
gönderip alır. Telefona uygulama kurmak gerekmez: telefon aynı Wi-Fi ağındaki bilgisayara tarayıcıdan bağlanır.
Arayüz iOS görünümündedir ve "Ana Ekrana Ekle" ile uygulama gibi açılır.

## Başlatma (Windows, PowerShell — kurulum gerekmez)

1. `aktarim` klasörünü bilgisayara kopyala.
2. `Aktarim.bat` dosyasına çift tıkla. Bu, `Aktarim.ps1`'i Windows'un kendi PowerShell'iyle çalıştırır
   (Python gerekmez). Ya da PowerShell'de:
   ```powershell
   cd aktarim
   powershell -ExecutionPolicy Bypass -File .\Aktarim.ps1
   ```
3. Açılan pencerede **Bağlan** sekmesindeki QR kodunu telefonun kamerasıyla okut.
4. Telefonda Safari (iPhone) / Chrome ya da Samsung Internet'te Paylaş → **Ana Ekrana Ekle**.

Telefon bağlanamazsa güvenlik duvarına izin ver: Windows ilk açılışta sorarsa **Özel ağlar**'ı işaretle, sormazsa
`.\Aktarim.ps1 -GuvenlikDuvari` (yönetici izni ister). Wi-Fi ağının Windows'ta **Özel** olarak ayarlı olması gerekir.

PowerShell seçenekleri:

| Komut | Ne yapar |
|---|---|
| `.\Aktarim.ps1` | Sunucuyu başlatır, tarayıcıyı açar |
| `.\Aktarim.ps1 -Ekle dosya.pdf Klasor` | Dosyaları/klasörleri telefona gönderir |
| `.\Aktarim.ps1 -GonderKur` | Sağ tık → Gönder → *Telefona gönder (Aktarım)* ekler |
| `.\Aktarim.ps1 -GuvenlikDuvari` | Güvenlik duvarı kuralı ekler (özel ağ) |
| `-Klasor D:\Aktarim` · `-Port 9000` · `-TarayiciAcma` | Veri klasörü, kapı, tarayıcı açmadan başlat |

Python sürümü de aynı arayüzü ve aynı veri biçimini kullanır: `Aktarim-python.bat` ya da `python3 aktarim.py`
(macOS/Linux: `Aktarim.command`).

## Kullanım

| Ne yapmak istiyorsun | Nasıl |
|---|---|
| Bilgisayardan telefona | Dosyaları/klasörleri pencereye **sürükle-bırak**, ya da Ctrl+V ile görsel/yazı yapıştır |
| Sağ tıkla gönder (Windows) | Bir kez `.\Aktarim.ps1 -GonderKur` → dosyaya sağ tık → Gönder → *Telefona gönder (Aktarım)* |
| Telefondan bilgisayara | **Gönder** sekmesi → fotoğraf/video/dosya seç, kamerayla çek ya da yazı yaz |
| Telefona kaydet | Öğeye dokun → *Fotoğraflara kaydet* / *Galeriye kaydet* / *Dosyalara indir* |
| Yazıyı/bağlantıyı al | Öğeye dokun → *Kopyala* ya da *Bağlantıyı aç* |

Yeni gelen öğeler iki saniye içinde öbür cihazda görünür. Gelen dosyalar bilgisayarda `Masaüstü\Aktarım\files`
klasöründe durur (`-Klasor` ile değiştirilebilir).

## Sonradan Sil

Silmek istediğin öğede **Sonradan sil…** → *1 hafta*, *2 hafta* ya da *1 ay* seç (ya da *Hemen kalıcı olarak sil*).
Öğe **Sonradan Sil** sekmesine taşınır; süre dolana kadar **Geri yükle** ile geri alınabilir, süresi değiştirilebilir.
Süre dolunca kendiliğinden kalıcı olarak silinir. Varsayılan süre aynı sekmeden ayarlanır.

## Güvenlik

- Sunucu yalnızca yerel ağda çalışır; internete bir şey yüklenmez.
- QR koddaki bağlantı gizli bir anahtar içerir; anahtarı olmayan cihaz hiçbir şeyi göremez.
  Anahtarı değiştirmek için `Aktarım\ayarlar.json` içindeki `token` satırını sil ve programı yeniden başlat.

## Sınırlar

- iPhone'un AirDrop'u yalnızca Apple cihazları arasında çalışır; Aktarım bunun yerine tarayıcı üzerinden çalışır.
- iPhone'da yerel ağdaki (HTTPS olmayan) sayfalarda paylaşım menüsü açılmaz; *Fotoğraflara kaydet* görseli açar,
  görsele basılı tutup **Fotoğraflara Ekle** de.
- HEIC fotoğraflar Windows tarayıcısında önizlenmez ama indirilir.

## Testler

```bash
python -m pytest aktarim/tests -q
```
