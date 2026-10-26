# SelfEdit Studio

Kendi kendini geliştirebilen bir video düzenleme uygulaması. Arka planda çalışan bir servis kullanımını izler, eksik efektleri tespit eder, yeni efekt eklentileri yazar (Claude ile veya hazır şablonlarla), bunları izole bir kopyada test eder ve sonuç güvenliyse uygulamaya ekler.

## Gereksinimler

- Python 3.10+
- FFmpeg (`ffmpeg` ve `ffprobe` PATH'te olmalı): https://ffmpeg.org
- Arayüz için Tkinter (Windows/macOS'ta Python ile gelir; Linux'ta `sudo apt install python3-tk`)
- İsteğe bağlı, Claude ile eklenti üretimi için: `pip install anthropic` ve `ANTHROPIC_API_KEY` ortam değişkeni

## Hızlı başlangıç

```bash
python -m selfedit demo demo.mp4          # örnek video üretir
python -m selfedit effects                 # mevcut efektler
python -m selfedit gui                     # masaüstü arayüzü

# komut satırıyla
python -m selfedit new proje.json --width 1280 --height 720
python -m selfedit add proje.json klip1.mp4 --start 2 --end 8
python -m selfedit fx proje.json 0 grayscale
python -m selfedit fx proje.json 0 fade in_s=1 out_s=1
python -m selfedit fx proje.json 0 text text="Merhaba" start=0.5 end=3
python -m selfedit render proje.json cikti.mp4
```

## Kendini geliştirme nasıl çalışır

```
kullanım kaydı ──► öneri üretici ──► doğrulayıcı ──► (senin onayın) ──► uygulama ──► sağlık kontrolü
 (render hataları,   Claude API ya da   1. statik kod taraması             plugins/'e      bozulursa
  bulunamayan        şablon kütüphanesi 2. izole kopyada gerçek render     yeni dosya      otomatik geri alma
  efektler, dilekler)                   3. tüm test paketi
```

- **Dilek bırak:** `python -m selfedit wish "mozaik efekti istiyorum"`. Sonraki tur bunu dikkate alır.
- **Bulunamayan efekt:** Projede olmayan bir efekt adı kullanırsan bu da kaydedilir ve öneri üreticiye girdi olur.
- **Bir tur çalıştır:** `python -m selfedit evolve` (`--offline` ile API'siz)
- **Önerileri yönet:** `python -m selfedit proposals list | show ID | approve ID | reject ID | rollback ID`

### Arka plan servisi

```bash
python -m selfedit daemon run        # sürekli çalışır (aralık: ayarlardaki interval_minutes)
python -m selfedit daemon status
python -m selfedit daemon stop
```

Bilgisayar açılınca otomatik başlatmak için:

- **Windows:** Görev Zamanlayıcı → "Oturum açıldığında" tetikleyici → eylem: `pythonw -m selfedit daemon run`, "Başlangıç" klasörü: proje klasörü.
- **macOS:** `~/Library/LaunchAgents/` altında `ProgramArguments` = `python3 -m selfedit daemon run`, `WorkingDirectory` = proje klasörü olan bir plist.
- **Linux:** `~/.config/systemd/user/selfedit.service` içinde `ExecStart=python3 -m selfedit daemon run` ve `WorkingDirectory=...`, sonra `systemctl --user enable --now selfedit`.

### Ayarlar

```bash
python -m selfedit config                  # göster
python -m selfedit config mode auto        # onaysız uygula (varsayılan: approve)
python -m selfedit config interval_minutes 30
python -m selfedit config max_per_day 4    # günlük öneri sınırı
```

| Mod | Davranış |
|---|---|
| `approve` (varsayılan) | Öneri doğrulanır ve bekler; sen `approve` dersen uygulanır. |
| `auto` | Doğrulamayı geçen öneri kendiliğinden uygulanır; sağlık kontrolü başarısızsa geri alınır. |

## Güvenlik modeli ve sınırlar

Bu bölüm önemli: motorun yaptıkları ve yapamadıkları net olsun.

- Motor yalnızca **plugins/ klasörüne yeni bir eklenti dosyası** ekleyebilir. Çekirdek kodu (`selfedit/`) değiştiremez.
- Eklenti kodu uygulanmadan önce statik olarak taranır: yalnızca `math` ve `re` import edilebilir; `open`, `eval`, `exec`, `getattr`, `__dunder__`, `class`, `lambda` ve import anında çalışan kod reddedilir.
- Doğrulama ayrı bir süreçte, geçici bir kopyada, API anahtarlarından arındırılmış ortamla, zaman aşımı ve kaynak sınırıyla çalışır.
- **Bu tam bir izolasyon değildir.** Tarama katmanlı bir önlemdir; sıkı güvenlik gerekiyorsa servisi bir konteyner veya sanal makine içinde çalıştır ve `approve` modunda kal.
- "Kendini geliştirme" şu an **efekt kütüphanesini genişletmekle** sınırlıdır. Çekirdek motoru, arayüzü veya render hattını kendiliğinden yeniden yazmaz. Bunu bilerek kapalı tuttum; denetimsiz kendi kendini yeniden yazan kod hata birikimine ve güvenlik risklerine açıktır.
- Kullanım kaydı yalnızca `data/telemetry.jsonl` dosyasında, yerelde tutulur. Claude API kullanırsan özet istatistikler (efekt adları, hata metinleri, dileklerin) API'ye gider; video içeriği gitmez.
- Hepsi `data/changelog.jsonl` dosyasına yazılır; her uygulanan değişiklik `rollback` ile geri alınabilir.

## Kendi eklentini yaz

`plugins/` içine bir `.py` dosyası at (arayüz: `selfedit/evolve/proposer.py` içindeki `INTERFACE_DOC`). Örnek: `plugins/grayscale.py`.

## Testler

```bash
python -m unittest discover -s tests -t .
```

## Bilinen sınırlar

- Tkinter arayüzü temel düzeydedir (zaman çizelgesi önizlemesi yok); derleme kontrolünden geçti ama görsel olarak denenmedi.
- Windows'ta çok uzun projelerde FFmpeg komut satırı sınırına (≈32 bin karakter) yaklaşılabilir.
- Çevrimdışı öneri kütüphanesi 10 şablonla sınırlıdır; bitince yeni öneri çıkmaz (Claude API ile sınırsız).
