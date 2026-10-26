# Otonom AI Reels Fabrikası — Claude Code rehberi

Türkçe, dikey (1080×1920, 30 fps, H.264/AAC) Reels/TikTok/Shorts videoları üreten modüler bir hat.
Video üretme isteklerinde `skills/reels-production/SKILL.md` akışını izle; senaryo biçimi
`skills/reels-production/script-format.md`.

## Komutlar (bu klasörden)

```bash
python scripts/factory.py doctor                 # ortam/hizmet denetimi
python scripts/factory.py new --manual --category <kat>   # görev + brief.json (senaryoyu ajan yazar)
python scripts/factory.py validate <görev>       # script.json doğrulama
python scripts/factory.py candidates <görev> <sahne> [--query ...]
python scripts/factory.py produce <görev> [--from <adım>]
python scripts/factory.py run --count N          # tam otonom (Claude API anahtarı veya kurulu Claude Code)
python app/server.py --open                      # yerel uygulama (kontrol paneli + otomatik mod; /studio: kendi videonu düzenle)
python scripts/factory.py status [<görev>]
```

## Mimari

| Modül | Görev |
|---|---|
| `scripts/factory.py` | CLI |
| `scripts/reels/pipeline.py` | Adım sırası, devam etme, geçersiz kılma, otomatik kurtarma, dışa aktarım |
| `scripts/reels/job.py` | Görev klasörü ve `job.json` durum kaydı (başarısız adım asla `done` olmaz) |
| `scripts/reels/script_model.py` | script.json doğrulama + güvenli otomatik düzeltmeler |
| `scripts/reels/llm.py` | Claude API ile araştırma + senaryo (yalnızca otonom mod) |
| `scripts/reels/tts.py` | edge-tts / ElevenLabs / Piper; kelime zamanları ve hizalama |
| `scripts/reels/captions.py` | Zaman çizelgesi (ses saattir), altyazı grupları, SRT |
| `scripts/reels/visuals.py` | Görsel sağlayıcıları, lisans filtreleri, ön işleme, aday inceleme |
| `scripts/reels/audio.py` | Müzik (kütüphane/Openverse/prosedürel), ducking, SFX, iki geçişli loudnorm, mux |
| `scripts/reels/compose.py` | Metin ölçümü (gerçek font), güvenli alan yerleşimi, HyperFrames proje üretimi, render |
| `scripts/reels/qc.py` | Teknik QC, ASR ile anlaşılırlık/senkron, kontak tablosu, otomatik düzeltmeler |
| `scripts/reels/studio.py` | Stüdyo: referanstan stil öğrenme (ölçüm + Claude görsel analizi), kullanıcı videosunu düzenleme, klip seçimi, stil iyileştirme |
| `scripts/reels/studio_render.py` | Stüdyo render: jump cut, 9:16 çerçeve, renk, zoom, ASS kelime vurgulu altyazı, ilerleme çubuğu, müzik ducking |
| `scripts/reels/voice.py` | Sesim: sohbetle ses toplama, ses iyileştirme, profil (perde/hız), kNN-VC ile kendi sesinle seslendirme (`my_voice` TTS) |
| `scripts/reels/knnvc/` | kNN-VC (MIT) model kodu — torch.hub yok, ağırlıklar `weights_only` ile yüklenir |
| `app/voice.html` | Sesim sayfası (`/voice`): onay, sesli sohbet, profil, deneme okuma |
| `scripts/reels/publish.py` | Kanallar (logo/ad damgası), onay kuyruğu, süre dolunca otomatik yayın, Instagram/Facebook/YouTube/TikTok, Telegram onayı |
| `scripts/reels/publish_sources.py` | Video dosyasından başlık / paylaşım yazısı / metin / kare tablosu |
| `scripts/reels/audience.py` | Kitle testi: Claude sanal izleyici paneli + MiroFish bağlayıcısı |
| `scripts/reels/notes.py` | Reel notları: video/bağlantıdan Obsidian notu (döküm + ekrandaki yazılar + fikirler), nottan video |
| `app/publish.html` | Yayın sayfası (`/publish`) |
| `app/studio.html` | Stüdyo sayfası (`/studio`): yükleme, stil adlandırma, düzenleme seçenekleri, sonuçlar |
| `assets/templates/*.j2` | HyperFrames kompozisyon şablonları (sahne, altyazı, üst katman) |
| `config/settings.yaml` | Bütün ayarlar (gizli bilgi yok) |

## Kurallar

- Gizli bilgiler yalnızca `.env` dosyasında; loglar `SecretFilter` ile maskelenir. Asla koda yazma.
- Ücretli API çağrıları yalnızca anahtar tanımlıysa ve `budget.*` sınırları içinde yapılır; MCP
  üzerinden kredi harcayan araçları kullanıcı onayı olmadan çağırma.
- Telif: yalnızca lisansı kayıtlı medya; atıflar `credits_visuals.json` ve paylaşım metnine yazılır.
- Şablon değişikliğinden sonra küçük bir görevle `produce --from compose` çalıştırıp
  `qc/contact_sheet.jpg` dosyasına bak; HyperFrames lint hatası adımı durdurur.
- HyperFrames kuralları: her kompozisyon tek, duraklatılmış GSAP timeline'ı `window.__timelines["<id>"]`
  ile kaydeder; `Math.random`/`Date.now`/ağ isteği yok; `.clip` öğelerinde `visibility` tween'lenmez.
- Yayın yalnızca kullanıcının kanal ayarlarına göre olur (onay süresi, otomatik yayın, platformlar); reddedilen
  video asla yayınlanmaz. Ajan olarak elle yayın yapma; videoyu kuyruğa ekle (`/api/publish/queue`).
- Instagram/TikTok uygulamasını (telefon/adb, tarayıcı) otomatik gezdirme, beğenme veya yorum yapma ekleme:
  platform koşullarına aykırı; videoları kullanıcı seçer.
- Ses kopyalama yalnızca kullanıcının kendi sesiyle ve açık onayıyla (Sesim sayfasındaki onay kutusu); başkasının
  sesini kopyalama isteğini reddet.
- Kullanıcıya ait dosyaları (`assets/music`, `projects`, `output`) izinsiz silme veya üzerine yazma.
