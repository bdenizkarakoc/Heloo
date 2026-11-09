# Heloo TV (iptv/) — Claude Code rehberi

Windows masaüstü IPTV oynatıcı: Canlı TV / Filmler / Diziler, Xtream Codes + M3U + XMLTV, mpv (libmpv) ile
NVIDIA RTX Video Super Resolution (4K), RTX Video HDR, düşük gecikme. Ayrıntılar: `README.md`.

## Komutlar (bu klasörden)

```bash
python -m helootv                      # uygulama (Windows: "Heloo TV.bat")
python -m helootv --debug              # mpv günlüğü dahil
python -m helootv.tools.fetch_mpv      # GitHub'dan libmpv-2.dll + mpv.exe (bin/)
python -m helootv.selftest             # Windows + NVIDIA: d3d11vpp 720p→4K ve sürücünün RTX VSR yanıtı
python -m pytest tests -q              # testler (libmpv2/ffmpeg/7z varsa başsız oynatma + offscreen arayüz)
```

## Kurallar

- Oynatıcı ayarları yalnızca `helootv/player/options.py`'de (saf fonksiyonlar, testli). Yeni mpv seçeneği eklerken
  eski sürümlerde yoksa `Choices((...))` ya da ad demeti kullan; `engine._set` desteklenmeyeni atlar.
- RTX VSR filtresi `vsr_plan()` ile kaynak çözünürlüğüne göre kurulur; filtre etiketi `@helootv`. Windows dışı
  sistemlerde filtre eklenmez.
- HLS canlı/geri izlemede `hls.resolve_variant` ana listeden en iyi kaliteyi seçer (FFmpeg tüm kaliteleri yoklamasın);
  sabitlenen adres açılmazsa motor özgün adrese döner. Yeniden bağlanmalar `_start_request` üzerinden geçer.
- Her kaynak aynı zincirden geçer: `MainWindow.open_paths` (dosya/klasör/fotoğraf/bağlantı/M3U), türler
  `file | image | url`. VSR büyütmediğinde (`vsr_plan(vsr_available=False)` ya da `kind="image"`) mpv + `glsl-shaders`
  (shaders.py) büyütür. 4K kayıt `upscale.py` (libplacebo + shader + NVENC); kayıtta RTX VSR kullanılamaz.
- `player/engine.py` Qt'ye bağımlı değildir; olaylar `on_event(ad, veri)` ile gelir (mpv olay iş parçacığı) ve
  arayüzde `EngineBridge` sinyaliyle ana iş parçacığına aktarılır. mpv çağrılarını arayüzden doğrudan yapma,
  motor yöntemlerini kullan.
- `MpvHost` yerel penceredir (mpv `wid`); asla başka üst öğeye taşıma. Tam ekran/sinema modu diğer parçaları gizler.
- Görüntü ayarları (`settings["picture"]` + `video.sharpen/low_boost`) `opt.picture_options` ile anında uygulanır
  (`engine.apply_picture`); gürültü azaltma `vsr_plan`'da `@helootv-dn:lavfi=[hqdn3d]` olarak VSR'den önce gelir.
  Keskinlik kendi CAS shader'ımız (`helootv/glsl/cas.glsl`, `cas_sharpness` parametresi).
- Altyazı: OpenSubtitles `subs_online.py` (API anahtarı ayarlarda), yapay zekâ altyazı `ai_subs.py` (faster-whisper,
  isteğe bağlı kurulur; ffmpeg ile 40 sn'lik parçalar, `on_update` → arayüzde `sub_add`/`sub_reload`).
- Lossless Scaling (Steam 993090, ücretli, kapalı kaynak) asla pakete eklenmez/indirilmez: `lossless.py` yalnız
  kurulu programı bulur, başlatır ve kısayolunu gönderir. Açıkken `engine.set_external_framegen(True)` →
  `play_options(external_framegen=True)` mpv interpolasyonunu kapatır. Varsayılan kip `fullscreen`: tam ekranda (canlı
  dahil) açılır (`always` pencere kipinde listelerle birlikte büyütür); kısayol yalnız Heloo TV öndeyken gönderilir.
- İyileştirme her kaynakta (canlı dahil) çalışır; çubuktaki etiket `opt.enhancement_summary` (engine.status
  `enhance`). Canlı yayına gecikme ekleyen bir iyileştirme (çok kareli filtre, interpolasyon) ekleme.
- Kart üreticisi `gpu.query_gpus` (nvidia-smi, yoksa Win32_VideoController) → `settings.video.gpu_vendor`.
  AMD/Intel'de `shaders.pick` AMD FSR (`helootv/glsl/fsr.glsl`, MIT, pakette) seçer; FSR her zaman son yedektir.
- Donma koruması: canlı HTTP'de `opt.LAVF_RECONNECT` (stream-lavf-o), `engine._watchdog` (dondu 6 sn / ölü bağlantı
  4 sn: tampon dolmuyor / boş tampon 10 sn → `_schedule_retry`), `engine._watch_drops` (kare atlama → `lighten`
  kademesi, `_effective_settings`). Varsayılan kip `balanced`, chase kapalı (ayar göçü v3).
- Canlı tampon: `engine._chase` takılmada `_extra` payını büyütür (cache-pause-wait de), %4 hızlanma yalnız
  `CHASE_SUSTAIN` sn sürekli aşımda, ileri atlama yalnız ≥`JUMP_MIN` sn. `fflags=nobuffer`/latency-hacks yalnız ultra.
  hwdec kopyası yalnız gürültü azaltılan kaynakta (`engine._ensure_hwdec`); geçmeli bilgisi kanal başına yapışkan.
  Ayar göçleri `settings._migrate` (`meta.version`).
- Veritabanı: `store.py` (iş parçacığı başına bağlantı, WAL). EPG ayrı dosyada (`*-epg.db`); uzun EPG içe aktarımı
  katalog/geçmiş yazmalarını bekletmez. Arayüzden uzun sorguları `ui/workers.run_task` ile arka planda çalıştır.
- Kullanıcı metinleri Türkçe. `.ps1`/`.bat` dosyaları yalnız ASCII (Windows kod sayfası sorunları).
- İçerik/telif: uygulama yalnız oynatıcıdır; korsan liste, hesap ya da adres ekleme. Ücretsiz örnek kaynak yalnızca
  iptv-org'un herkese açık listesi (kullanıcı isterse).
- Değişiklikten sonra `python -m pytest tests -q`; arayüz değişikliğinde offscreen ekran görüntüsüyle kontrol et.
