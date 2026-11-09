# 🔊 Hoparlör Ses Ayarı

Logitech **Z607 5.1** ve diğer hoparlörlerin için Windows ekolayzırı: bas, tiz, vokal, müzik türü hazırları
(Pop, R&B, Caz, Türkü, Arabesk, Rock, Film…), 5.1 kanal düzeyleri (subwoofer, merkez, arka) ve 10 bantlı ekolayzır.
En üstten hangi hoparlörün ayarlanacağını seçersin; her hoparlör kendi ayarını hatırlar.

Logitech, Z607 için bilgisayarda ekolayzır programı sunmuyor. Bu program ayarı ücretsiz, açık kaynak
[Equalizer APO](https://sourceforge.net/projects/equalizerapo/) ile bütün Windows sesine uygular.

## Kurulum (tek satır)

Başlat menüsüne **PowerShell** yaz, aç, şunu yapıştırıp Enter'a bas:

```powershell
irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/dazzling-fermi-49dzwq/hoparlor-app/kur.ps1 | iex
```

Kurulum programı:
1. Programı `%LOCALAPPDATA%\HoparlorSesAyari` klasörüne indirir.
2. Masaüstüne ve Başlat menüsüne **Hoparlor Ses Ayari** kısayolu koyar.
3. Equalizer APO yoksa indirip kurulumunu başlatır. Kurulumun sonunda açılan *Configurator* penceresinde
   Z607'nin bağlı olduğu çıkışı (**Hoparlörler / Speakers**) işaretle ve bilgisayarı **yeniden başlat**.
4. Programı açar.

Güncellemek için aynı satırı yeniden çalıştır. Kaldırmak için:
`powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\HoparlorSesAyari\kur.ps1" -Kaldir`
(ya da `kur.ps1` dosyasını indirip `-Kaldir` ile çalıştır).

## Kullanım

- Program açılırken bir kez yönetici izni ister (Equalizer APO klasörüne yazmak için) — **Evet** de.
- Her değişiklik anında sese uygulanır; kaydet düğmesi yok.
- Z607'de Subwoofer/Merkez/Arka sürgüleri için Windows'ta *Ses ayarları → Hoparlörler → Yapılandır → 5.1 Surround* seç.
- Kumandadaki bas düzeyini ortada bırak, ince ayarı buradan yap.
- Ayar yalnızca bilgisayardan çalan seste geçerli; telefondan Bluetooth ile çalarken uygulanmaz.

## Dosyalar

| Dosya | |
|---|---|
| `HoparlorSesAyari.ps1` | Program (WinForms penceresi). UTF-8 **BOM** ile kaydedilmeli (Windows PowerShell 5.1 Türkçe harfler). |
| `kur.ps1` | İndirme/kurulum/kaldırma (yalnız ASCII; `irm … \| iex` ile güvenli). |
| Ayarlar | `%APPDATA%\HelooHoparlor\ayarlar.json` |
| Equalizer APO dosyası | `<EqualizerAPO>\config\heloo-hoparlor.txt` (`config.txt` içinde `Include: heloo-hoparlor.txt`) |
