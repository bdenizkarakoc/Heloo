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
  `play_options(external_framegen=True)` mpv interpolasyonunu kapatır. Varsayılan kip `manual`: yalnız Heloo TV kısayoluyla
  (`lossless.app_shortcut`, Ctrl+Z; QShortcut + mpv input.conf `script-message helootv lossless`) açılır/kapanır;
  tam ekran kendiliğinden açmaz (ayar göçü v5). LS kısayolu yalnız Heloo TV öndeyken gönderilir.
- İyileştirme her kaynakta (canlı dahil) çalışır; çubuktaki etiket `opt.enhancement_summary` (engine.status
  `enhance`). Canlı yayına gecikme ekleyen bir iyileştirme (çok kareli filtre, interpolasyon) ekleme.
- Kart üreticisi `gpu.query_gpus` (nvidia-smi, yoksa Win32_VideoController) → `settings.video.gpu_vendor`.
  AMD/Intel'de `shaders.pick` AMD FSR (`helootv/glsl/fsr.glsl`, MIT, pakette) seçer; FSR her zaman son yedektir.
- Donma koruması: canlı HTTP'de `opt.LAVF_RECONNECT` (stream-lavf-o), `engine._watchdog` (dondu 6 sn / ölü bağlantı
  4 sn: tampon dolmuyor / boş tampon 10 sn → `_schedule_retry`), `engine._watch_drops` (kare atlama → `lighten`
  kademesi, `_effective_settings`). Varsayılan kip `auto` (Akıllı: `adaptive`, kanal başına `_extra_mem`, 60 sn'de pay azalır, yetişme hep açık;
  ayar göçü v4), chase ayarı kapalı.
- Canlı tampon: `engine._chase` takılmada `_extra` payını büyütür (cache-pause-wait de), %4 hızlanma yalnız
  `CHASE_SUSTAIN` sn sürekli aşımda, ileri atlama yalnız ≥`JUMP_MIN` sn. `fflags=nobuffer`/latency-hacks yalnız ultra.
  hwdec kopyası yalnız gürültü azaltılan kaynakta (`engine._ensure_hwdec`); geçmeli bilgisi kanal başına yapışkan.
  Ayar göçleri `settings._migrate` (`meta.version`).
- Kayıt: `recorder.py` (Qt'siz; `Recorder` FFmpeg `-c copy` MPEG-TS, `Scheduler` `schedule.json`, `due()` arayüzde
  15 sn'de bir). Mini oynatıcı `MainWindow._set_pip`: Windows'ta her zaman üstte `SetWindowPos` ile (pencere bayrağı
  değiştirmek pencereyi yeniden oluşturur, gömülü mpv bozulur).
- TV rehberi `ui/guide.py` (kendi çizen `GuideCanvas`, `store.epg_grid` toplu sorgu, en çok 400 kanal).
- Ebeveyn kilidi `parental.py` (`ui.pin_hash`, PBKDF2); açılışta `hide_adult` zorla açılır, sıfırlamada PIN korunur.
- Güncelleme `updater.py` (Qt'siz; `check` git fetch + rev-list, `apply` yalnız `--ff-only`, kirli/ileride ise durur).
  Açılıştaki denetim `interactive=False` (şifre penceresi açmaz); güncelleme sonrası `--restart` ile açılır (tek örnek
  denetimini atlar). Hata olayında `_loading_timer` durdurulur (hata iletisi boş videoyla örtülmesin).
- TMDB `tmdb.py` (Qt'siz; `lookup` arama+ayrıntı+önbellek `cache/tmdb.json`, `merge` yalnız boşları doldurur);
  arayüzde `_DetailsBase._tmdb` (anahtar `settings.metadata.tmdb_key`).
- Çoklu görüntü `ui/multiview.py` (hücre başına `MpvEngine`, `cell_settings` hafif; tık = `click` script-message;
  yerleşim bir kez kurulan QSplitter'lar — hücreler asla yeniden üst öğeye taşınmaz; ses `cursor_pos` yoklamasıyla).
- Kanal değişimi: her `play_live(item, reason)` `switch_log`'a yazılır ve OSD'de sebep gösterilir; ↑/↓ varsayılan ses
  (`controls.arrow_keys`), açık kanal eylemleri `ch_next/ch_prev` (düğmeler, CHANNEL_UP/DOWN), medya tuşları
  `controls.media_keys_zap`. Canlı adres çok öğeli oynatma listesiyse FILE_LOADED'da `playlist-clear`.
- Canlı "hep canlı" (`controls.stay_live`): `_toggle_pause` sürdürünce `go_live`, canlıda ←/sol tık sarmaz, canlı
  `demuxer-max-back-bytes` 32MiB. Tekrar yalnız `confirm_catchup` ile (`controls.catchup`: ask/off/direct); TEKRAR
  etiketi `set_now_playing(replay=True)`, `_back_to_live`. Testlerde lavfi canlı kaynakları `,realtime` (yoksa bellek
  sınırsız büyür, CI makinesi kapanır).
- Tam ekranda alt çubuk `_fs_bar_tick` (imleç yoklaması: altta görünür, 2,5 sn sonra gizlenir). Tık geri bildirimi
  `engine.flash` (osd-overlay, büyük simge). Ayarlar sayfasında sabit `close_btn` (kaydırmadan bağımsız) → `_close_settings`.
- Dakikaya git: `MainWindow.goto_time` + `opt.parse_goto` (G, Ctrl+J, "⏱ Git"). ←/→ `controls.seek_step` kadar sarar.
  Mini oynatıcıda `_pip_top_timer` 1 sn'de bir `_pip_keep_on_top`: küçültüldüyse SW_SHOWNOACTIVATE ile geri açar,
  TOPMOST'u yeniler (SWP_NOACTIVATE: odağı çalmaz). Yeri/boyutu `ui.pip_rect` (moveEvent/resizeEvent, `_pip_ready`);
  `_saved_pip_rect` kayıtlı yer hiçbir ekranda görünmüyorsa sağ üst köşeye düşer.
  📌 Sabitle (`pip_pin`, `set_pip_pinned`, `ui.pip_pinned`): `_lock_pip` yer (moveEvent geri taşır) + boyut kilidi,
  Esc/çift tık kapatmaz (`_pip_pinned_msg`; ⤢/Ctrl+M kapatır); sabitliyken kapanışta `ui.pip_restore` →
  açılışta `_restore_pinned_pip` (canlı/film/bölüm, kaldığı saniye) mini oynatıcıda.
- Film/dizi sunucusu HTTP Range desteklemiyorsa (`engine.linear`, `_check_linear`): VOD önbelleği diskte
  (`cache-on-disk`), sınır 6GiB'a çıkar; `seek`/`seek_abs` hedefi `cached_range()` içine sıkıştırır ve `seek-clamped`
  yayar (mpv uzak atlamayı sessizce reddederdi). YouTube tuşları: J/L ±10 sn (canlıda j=altyazı, l=canlı), K, Home.
- Videoya tık: `MainWindow._on_video_click` ANINDA uygular → `opt.click_zone` (`settings.controls`); çift tıkta (tam
  ekran) `_undo_recent_clicks` etkisini geri alır. Mini oynatıcıda `PlayerPanel.pip_bar` (Qt düğmeleri: ±10 sn,
  durdur, ses, büyüt; yalnız fare üstündeyken `_pip_bar_tick`, 1,5 sn sonra gizlenir), pencere bırakıldığı yerde
  (ilk kez sağ üst). `_update_layout` tam ekranda ve mini oynatıcıda hiçbir şey göstermez. Çubuk/mini düğmeleri `_seek_by` (canlıda "hep canlı"ya uyar).
- Video girdisi iki bağımsız yoldan: mpv bağlamaları (`click`/`dblclick` script-message) + Windows'ta fare yoklaması
  (`_mouse_poll`: GetAsyncKeyState + imleç, `_point_is_ours`); `_video_click/_video_dblclick` aynı tıklamayı bir kez
  işler. Film/dizide → ← Boşluk J K L uygulama düzeyi `eventFilter` ile odaktan bağımsız videoya gider (yazı kutusu hariç).
- HLS kalite önbelleği (`_pin_cache`) yalnız yönlendirmesiz adreslerde (`urljoin(req.url, info.uri) == variant`):
  oturum adresi önbelleğe alınırsa eski kanal görünür. Kanal geçişinde `PlayerPanel.show_loading` → "playing" olayıyla video.
- Veritabanı: `store.py` (iş parçacığı başına bağlantı, WAL). EPG ayrı dosyada (`*-epg.db`); uzun EPG içe aktarımı
  katalog/geçmiş yazmalarını bekletmez. Arayüzden uzun sorguları `ui/workers.run_task` ile arka planda çalıştır.
- Kullanıcı metinleri Türkçe. `.ps1`/`.bat` dosyaları yalnız ASCII (Windows kod sayfası sorunları).
- İçerik/telif: uygulama yalnız oynatıcıdır; korsan liste, hesap ya da adres ekleme. Ücretsiz örnek kaynak yalnızca
  iptv-org'un herkese açık listesi (kullanıcı isterse).
- Değişiklikten sonra `python -m pytest tests -q`; arayüz değişikliğinde offscreen ekran görüntüsüyle kontrol et.
