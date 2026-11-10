# Aktarım — bilgisayar ↔ telefon

Bilgisayar ile **iPhone (iOS)** ve **Samsung / Android** telefon arasında fotoğraf, video, belge, dosya ve yazı
gönderip alır. Telefona uygulama kurmak gerekmez: telefon aynı Wi-Fi ağındaki bilgisayara tarayıcıdan bağlanır.
Arayüz iOS görünümündedir ve "Ana Ekrana Ekle" ile uygulama gibi açılır.

## Başlatma

1. Bilgisayarda Python 3.9+ kurulu olsun (Windows: python.org, kurulumda **Add to PATH** işaretli).
2. Windows'ta `Aktarim.bat` dosyasına çift tıkla (macOS/Linux: `Aktarim.command` ya da `python3 aktarim.py`).
3. Açılan pencerede **Bağlan** sekmesindeki QR kodunu telefonun kamerasıyla okut.
4. Telefonda Safari (iPhone) / Chrome ya da Samsung Internet'te Paylaş → **Ana Ekrana Ekle**.

Windows güvenlik duvarı ilk açılışta izin sorarsa **Özel ağlar** için izin ver.

## Kullanım

| Ne yapmak istiyorsun | Nasıl |
|---|---|
| Bilgisayardan telefona | Dosyaları/klasörleri pencereye **sürükle-bırak**, ya da Ctrl+V ile görsel/yazı yapıştır |
| Sağ tıkla gönder (Windows) | Bir kez `python aktarim.py gonder-kur` → dosyaya sağ tık → Gönder → *Telefona gönder (Aktarım)* |
| Telefondan bilgisayara | **Gönder** sekmesi → fotoğraf/video/dosya seç, kamerayla çek ya da yazı yaz |
| Telefona kaydet | Öğeye dokun → *Fotoğraflara kaydet* / *Galeriye kaydet* / *Dosyalara indir* |
| Yazıyı/bağlantıyı al | Öğeye dokun → *Kopyala* ya da *Bağlantıyı aç* |

Yeni gelen öğeler iki saniye içinde öbür cihazda görünür. Gelen dosyalar bilgisayarda `Masaüstü\Aktarım\files`
klasöründe durur (`--dir` ile değiştirilebilir).

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
