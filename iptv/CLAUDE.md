# Heloo TV (iptv/) — Claude Code rehberi

Windows masaüstü IPTV oynatıcı: Canlı TV / Filmler / Diziler, Xtream Codes + M3U + XMLTV, mpv (libmpv) ile
NVIDIA RTX Video Super Resolution (4K), RTX Video HDR, düşük gecikme. Ayrıntılar: `README.md`.

## Komutlar (bu klasörden)

```bash
python -m helootv                      # uygulama (Windows: "Heloo TV.bat")
python -m helootv --debug              # mpv günlüğü dahil
python -m helootv.tools.fetch_mpv      # GitHub'dan libmpv-2.dll + mpv.exe (bin/)
python -m helootv.selftest --warp      # Windows: D3D11 + d3d11vpp duman testi
python -m pytest tests -q              # testler (libmpv2/ffmpeg/7z varsa başsız oynatma + offscreen arayüz)
```

## Kurallar

- Oynatıcı ayarları yalnızca `helootv/player/options.py`'de (saf fonksiyonlar, testli). Yeni mpv seçeneği eklerken
  eski sürümlerde yoksa `Choices((...))` ya da ad demeti kullan; `engine._set` desteklenmeyeni atlar.
- RTX VSR filtresi `vsr_plan()` ile kaynak çözünürlüğüne göre kurulur; filtre etiketi `@helootv`. Windows dışı
  sistemlerde filtre eklenmez.
- `player/engine.py` Qt'ye bağımlı değildir; olaylar `on_event(ad, veri)` ile gelir (mpv olay iş parçacığı) ve
  arayüzde `EngineBridge` sinyaliyle ana iş parçacığına aktarılır. mpv çağrılarını arayüzden doğrudan yapma,
  motor yöntemlerini kullan.
- `MpvHost` yerel penceredir (mpv `wid`); asla başka üst öğeye taşıma. Tam ekran/sinema modu diğer parçaları gizler.
- Veritabanı: `store.py` (iş parçacığı başına bağlantı, WAL). EPG ayrı dosyada (`*-epg.db`); uzun EPG içe aktarımı
  katalog/geçmiş yazmalarını bekletmez. Arayüzden uzun sorguları `ui/workers.run_task` ile arka planda çalıştır.
- Kullanıcı metinleri Türkçe. `.ps1`/`.bat` dosyaları yalnız ASCII (Windows kod sayfası sorunları).
- İçerik/telif: uygulama yalnız oynatıcıdır; korsan liste, hesap ya da adres ekleme. Ücretsiz örnek kaynak yalnızca
  iptv-org'un herkese açık listesi (kullanıcı isterse).
- Değişiklikten sonra `python -m pytest tests -q`; arayüz değişikliğinde offscreen ekran görüntüsüyle kontrol et.
