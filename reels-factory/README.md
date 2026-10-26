# Otonom AI Reels Fabrikası

Belirlenen içerik kategorilerinde **konu seçen, araştıran, kaynaklı senaryo yazan, Türkçe seslendiren,
kelime vurgulu altyazı ekleyen, görsel/video temin eden, HyperFrames ile hareketli kurgu yapan,
müzik ve efekt ekleyen, kalite kontrolünden geçiren** ve paylaşıma hazır dikey video üreten modüler bir sistem.

```
KONU → ARAŞTIRMA → SENARYO → SES → ALTYAZI → GÖRSEL → MÜZİK → KURGU → RENDER → MİKS → KALİTE KONTROL → ÇIKTI
```

Varsayılan çıktı: **1080×1920, 9:16, 30 fps, MP4 (H.264 + AAC 48 kHz), −14 LUFS**, 30–60 sn
(Instagram Reels, TikTok, YouTube Shorts).

---

## Ne yapabiliyor, ne yapamıyor (dürüst durum)

`python scripts/factory.py doctor` hangi yöntemlerin o anda gerçekten kullanılabildiğini gösterir.
Anahtarı olmayan bir hizmet **asla varmış gibi kullanılmaz**; yerine alternatif yöntem uygulanır ve
görevin uyarılarına yazılır.

| Adım | Anahtarsız (varsayılan) | İsteğe bağlı (anahtar/hesap ile) |
|---|---|---|
| Konu + araştırma + senaryo | Claude Code oturumu (`skills/reels-production/SKILL.md`) | Claude API ile tam otonom (`ANTHROPIC_API_KEY`) |
| Seslendirme (Türkçe) | edge-tts nöral sesler (`tr-TR-EmelNeural`, `tr-TR-AhmetNeural`) + kelime zamanları | ElevenLabs (`ELEVENLABS_API_KEY`) |
| Görseller | NASA görsel kütüphanesi (kamu malı), Openverse (CC0 / kamu malı / CC BY) | Pexels foto/video, OpenAI görsel üretimi, Replicate görsel/video modelleri |
| Hareket | Fotoğraf + kamera hareketleri (push/pull/pan), geçişler, hareketli grafikler (sayaç, karşılaştırma çubukları, listeler, kinetik tipografi) | Gerçek AI video klipleri (Replicate modeli veya ajanın ürettiği klipler) |
| Müzik | Openverse CC0 / CC BY (atıf otomatik), prosedürel ambiyans | Kendi lisanslı kütüphaneniz (`assets/music/licenses.yaml`) |
| Efektler | HyperFrames paketindeki Pixabay lisanslı 21 efekt | `assets/sfx/` |
| Kurgu/render | HyperFrames + GSAP (HTML → MP4) | — |
| Kalite kontrol | ffprobe/ffmpeg analizleri + faster-whisper ile konuşma tanıma | — |

**Önemli:** Bu kurulumda yapay zekâ ile *gerçek video klip üretimi* için yapılandırılmış bir hizmet
yoktur. Video sahneleri; lisanslı fotoğraflar üzerinde kamera hareketleri, sahne geçişleri ve
hareketli grafiklerle üretilir. Bir video üretim hizmeti bağlandığında (Replicate modeli veya Claude Code
oturumundaki bir üretim aracı → `projects/<görev>/media/<sahne>.mp4`) klipler otomatik kullanılır.
OpenAI/Replicate/Pexels/ElevenLabs bağdaştırıcıları yazılmıştır ancak anahtar olmadığı için bu
ortamda **canlı test edilmemiştir**.

---

## Kurulum

Gereksinimler: Python 3.10+, Node.js 22+, FFmpeg (libx264), ~1 GB disk (render tarayıcısı + modeller).

```bash
cd reels-factory
bash scripts/setup.sh
```

Betik şunları yapar: `pip install -r requirements.txt`, `npm install` (HyperFrames 0.8.201 + GSAP 3.14.2),
`npx hyperframes browser ensure` (Chrome Headless Shell), HyperFrames telemetrisini kapatır,
`.env.example` → `.env` kopyalar ve `doctor` çalıştırır.

Windows (PowerShell):

```powershell
winget install Python.Python.3.12 OpenJS.NodeJS.LTS Gyan.FFmpeg Git.Git   # yoksa; sonra terminali yeniden açın
git clone -b claude/autonomous-ai-reels-factory-x82681 https://github.com/bdenizkarakoc/Heloo.git
cd Heloo\reels-factory
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Elle kurulum:

```bash
python3 -m pip install -r requirements.txt
npm install
npx hyperframes browser ensure
cp .env.example .env      # isteğe bağlı anahtarlar
python3 scripts/factory.py doctor
```

İlk kalite kontrolünde faster-whisper `small` modelini (~460 MB) Hugging Face'ten indirir.
İstemiyorsanız `config/settings.yaml → qc.asr_check: false`.

### API anahtarları (isteğe bağlı)

Yalnızca `.env` dosyasına yazın (git'e eklenmez, loglarda maskelenir):

| Değişken | Ne açar |
|---|---|
| `ANTHROPIC_API_KEY` | Tam otonom mod: Claude (`claude-opus-5-5`) web araştırması + senaryo (`llm.provider: anthropic`) |
| `ELEVENLABS_API_KEY` | ElevenLabs seslendirme (+ `tts.elevenlabs.voice_id`) |
| `PEXELS_API_KEY` | Pexels stok fotoğraf/video |
| `OPENAI_API_KEY` | OpenAI görsel üretimi (`gpt-image-1`) |
| `REPLICATE_API_TOKEN` | Replicate görsel/video modelleri (`visuals.replicate.image_model` / `video_model`) |

---

## Kullanım

### A) Claude Code ile (önerilen, anahtar gerektirmez)

Claude Code'a örneğin şunu söyleyin: *"bilim-uzay kategorisinde yeni bir reels üret"*.
Ajan `skills/reels-production/SKILL.md` akışını izler: görev açar, web'de araştırır, kaynaklı
senaryo yazar, görselleri gözle denetler, üretir, QC raporunu ve kontak tablosunu inceler.

Elle aynı akış:

```bash
python scripts/factory.py new --category bilim-uzay --topic "Ay'ın Dünya'dan uzaklaşması"
# projects/<görev>/brief.json'u okuyun, araştırın ve projects/<görev>/script.json'u yazın
python scripts/factory.py validate <görev>
python scripts/factory.py candidates <görev> s1          # görsel adaylarını gözle seçmek için
python scripts/factory.py produce <görev>
python scripts/factory.py status <görev>
```

### B) Tam otonom (Claude API)

`config/settings.yaml → llm.provider: anthropic` ve `.env → ANTHROPIC_API_KEY`:

```bash
python scripts/factory.py run --count 3                  # kategori ağırlıklarına göre 3 video
python scripts/factory.py run --category tarih --count 1
```

Zamanlanmış çalıştırma (ör. her gün 09:00): `0 9 * * * cd /yol/reels-factory && python3 scripts/factory.py run >> logs/cron.log 2>&1`

Otonom modda görsel seçimi metin tabanlı sıralamaya dayanır; yayın öncesi
`projects/<görev>/qc/contact_sheet.jpg` dosyasına göz atmanız önerilir.

### Çıktılar

| Yol | İçerik |
|---|---|
| `output/videos/<tarih>-<slug>.mp4` | Son video |
| `output/thumbnails/<tarih>-<slug>.jpg` | Kapak karesi |
| `output/captions/<tarih>-<slug>.srt` | Platforma yüklenecek altyazı |
| `output/captions/<tarih>-<slug>.txt` | Paylaşım metni + hashtag + kaynaklar + lisans atıfları |
| `projects/<görev>/` | Bütün ara ürünler: script, ses, görseller, HyperFrames projesi, QC raporu |
| `logs/<görev>.log` | Görev logu (gizli bilgiler maskelenir) |

`projects/<görev>/composition/` bir HyperFrames projesidir: `npx hyperframes preview` ile
tarayıcıda açılıp elle düzenlenebilir.

---

## Üretim hattı ayrıntıları

| Adım | Ne yapar | Hata durumunda |
|---|---|---|
| script | `script.json` doğrulama: yapı, süre tahmini, yazım/noktalama, sembol, kaynak zorunluluğu | Üretim başlamaz |
| voice | Sahne başına TTS, baş/son sessizlik kırpma, sağlayıcı kelime sınırlarını senaryo kelimelerine hizalama | 3 deneme (2/4/8 sn) → sonraki ses → sonraki sağlayıcı |
| captions | Ses saattir: sahne kesimleri sesi 0,18 sn önden karşılar (J-cut), geçiş örtüşmesi; 2–3 kelimelik gruplar; SRT | — |
| visuals | Sağlayıcı zinciri, lisans filtresi (NASA ortak kurum görselleri, NC/ND/SA lisanslar elenir), çözünürlük, tekrar (dHash) kontrolü, bulanık arka plan, atıf kaydı, inceleme görüntüsü | Sonraki aday/sağlayıcı → hareketli grafik arka plan (uyarı) |
| music | Kütüphane → Openverse (vokal ayıklama: faster-whisper) → prosedürel; son 5 videoda kullanılan parça atlanır | Müziksiz devam (uyarı) |
| compose | Gerçek font ölçümüyle metin yerleşimi, güvenli alan denetimi, HyperFrames HTML + GSAP, lint | Güvenli alan/lint hatasında durur |
| render | `hyperframes render` (CRF 18) | 2 işçiyle yeniden dener |
| mix | Konuşma işleme (high-pass + kompresör, −16 LUFS), müzik ducking (−15 dB), efekt yerleşimi, iki geçişli loudnorm (−14 LUFS, −1,5 dBTP), mux | — |
| qc | Aşağıdaki kontroller + otomatik düzeltmeler | Siyah karede ilgili sahneler grafikle yeniden üretilir; geçemezse görev `failed` |
| export | `output/` dosyaları, geçmiş kaydı (konu/müzik tekrarını önler) | — |

### Kalite kontrolleri

Dosya açılıyor mu · çözünürlük 1080×1920 · dikey · 30 fps · H.264/yuv420p · AAC 48 kHz ·
A/V süre farkı ≤ 0,12 sn · beklenen süre · hedef süre aralığı · loudness −14 ±1,5 LUFS ve true peak ·
bozuk kare (tam çözümleme) · siyah ekran · hareketsiz bölüm · gereksiz sessizlik · son bölüm payı ·
güvenli alanlar · **konuşma tanıma ile anlaşılırlık (WER)** · **altyazı-ses senkron sapması** ·
kontak tablosu (görsel-senaryo uyumunun gözle denetimi için).

Otomatik düzeltmeler: yeniden kodlama (format/fps/codec), loudness yeniden normalizasyonu, ses/video
süre eşitleme, siyah kare kaynağı olan sahnelerin grafikle yeniden üretimi.

### Güvenli alanlar (1080×1920)

Üst 200 px'e yazı konmaz; 1330 px altı yalnızca dekor (açıklama, kullanıcı adı); 820 px altında
sağdaki buton sütunu nedeniyle metin 124 px kenar boşluğuyla ortalanır; altyazı bandı 1130–1330 px.
Bütün metin kutuları ölçülür ve QC'de raporlanır (`config/settings.yaml → safe_zone`).

---

## Yapılandırma

Tüm ayarlar `config/settings.yaml` içindedir: çıktı formatı, güvenli alanlar, marka renkleri/font,
**kategoriler** (ton, hedef kitle, örnek konular, görsel sağlayıcı sırası, müzik sorguları, ağırlık),
TTS sesleri/hızı, altyazı stili, müzik/efekt seviyeleri, loudness hedefleri, QC eşikleri,
**maliyet sınırları** (`budget.*`: video başına AI görsel/klip ve LLM çağrısı üst sınırları) ve
yeniden deneme politikası.

Yeni kategori eklemek için `categories:` altına bir blok ekleyin.

---

## Dosya yapısı

```
reels-factory/
├── CLAUDE.md                     # Claude Code proje rehberi
├── README.md
├── config/settings.yaml          # bütün ayarlar (gizli bilgi yok)
├── skills/reels-production/
│   ├── SKILL.md                  # ajan üretim akışı
│   └── script-format.md          # senaryo biçimi ve yazım kuralları
├── scripts/
│   ├── factory.py                # CLI
│   ├── setup.sh
│   └── reels/                    # pipeline, job, tts, captions, visuals, audio, compose, qc, llm, doctor
├── assets/
│   ├── fonts/                    # Montserrat (SIL OFL)
│   ├── music/                    # kendi lisanslı müzikleriniz + licenses.yaml
│   ├── sfx/                      # isteğe bağlı kendi efektleriniz
│   └── templates/                # HyperFrames şablonları (sahne, altyazı, üst katman)
├── projects/                     # görev klasörleri (git'e eklenmez)
├── output/{videos,thumbnails,captions}
├── examples/                     # örnek üretim (senaryo, QC raporu, video)
└── logs/
```

---

## Lisans ve telif notları

> **`visuals.license_mode`** — `strict` (önerilen): yalnızca kullanım izni doğrulanmış medya.
> `any`: lisans denetlenmez (Openverse'te bütün lisanslar, Vikipedi'deki adil kullanım görselleri dahil);
> kaynaklar yine kaydedilir ve paylaşım metnine "kullanım hakkı doğrulanmadı" notu düşülür.
> **Telif riski kullanıcıdadır**: platformlar telif bildirimiyle videoyu kaldırabilir veya hesaba ihtar verebilir.
> Şu an bu depoda kullanıcı isteğiyle `any` açıktır.
>
> Kişi görselleri `visual.subject` ile metin üzerinden doğrulanır (Vikipedi maddesinin ana görseli veya
> adın başlık/açıklamada bitişik geçmesi); yüz tanıma kullanılmaz.

- **Görseller:** NASA görselleri genel olarak kamu malıdır (NASA medya yönergeleri; NASA logosu/
  kişilerin onay izlenimi verecek kullanımlar hariç). ESA/JAXA gibi ortak kurum ve telif ibareli
  görseller otomatik elenir. Openverse'ten yalnızca CC0, kamu malı ve CC BY; CC BY atıfları paylaşım
  metnine eklenir.
- **Müzik:** Openverse'ten yalnızca CC0 / CC BY (atıf paylaşım metninde). Ticari kanallar için kendi
  lisanslı kütüphanenizi önerilir.
- **Efektler:** HyperFrames ile gelen Pixabay Content License dosyaları (ticari kullanım serbest).
- **Seslendirme:** edge-tts, Microsoft Edge'in "Sesli Oku" hizmetini kullanır; resmî bir API değildir ve
  hizmet koşulları ticari kullanımı açıkça düzenlemez. Ticari yayınlar için aynı seslere sahip
  **Azure AI Speech** veya **ElevenLabs** gibi lisanslı bir hizmet önerilir. Piper'ın Türkçe sesi
  CC BY-NC-SA (ticari olmayan) olduğundan varsayılan olarak kapalıdır (`tts.allow_noncommercial`).
- **Font:** Montserrat — SIL Open Font License (`assets/fonts/OFL-Montserrat.txt`).
- **Araçlar:** HyperFrames (Apache-2.0), GSAP (GreenSock standart ücretsiz lisansı), FFmpeg.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `edge-tts ... CERTIFICATE_VERIFY_FAILED` | Kurumsal proxy/CA: `SSL_CERT_FILE` ortam değişkenini CA paketine yönlendirin (sistem otomatik ekler). |
| `tr-TR-AhmetNeural ses döndürmedi` | Hizmet tarafı geçici sorun; zincirdeki sonraki ses kullanılır. |
| Openverse `401 page_size` | Anonim istek sınırı (20); sistem buna uyar. Günlük 200 arama sınırı vardır. |
| Wikimedia `429` | Bazı ağlarda Wikimedia indirmeleri sınırlanır; sistem sonraki adaya geçer. `visuals.user_agent` alanına iletişim bilgisi ekleyin. |
| Render yavaş | `render.workers` (varsayılan 4); 45 sn video 4 çekirdekte ≈ 2 dk. |
| `HyperFrames bulunamadı` | `npm install` (reels-factory klasöründe). |
| Görsel alakasız | `factory.py candidates` ile inceleyin, `visual.pick`/`query`/`crop`/`fit` ile düzeltin, `produce` tekrar. |

---

## Örnek

`examples/venus-gun-yil/`: "Venüs'te Bir Gün, Bir Yıldan Uzun" — 52,7 sn, 7 sahne, NASA görselleri,
Openverse CC BY müzik, bütün QC kontrolleri geçti (WER ≈ %8–11, altyazı senkron sapması medyan ≈ 50 ms).

## Yol haritası

- Video üretim hizmeti bağlandığında sahne başına gerçek AI klipleri (bağdaştırıcı hazır).
- Otonom modda Claude görsel denetimi (kontak tablosunun model tarafından incelenmesi).
- Azure AI Speech bağdaştırıcısı (ticari lisanslı aynı nöral sesler).
- Platformlara otomatik yükleme (kullanıcı onayı ile).
