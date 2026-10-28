---
name: reels-production
description: Otonom Türkçe Reels/TikTok/Shorts videosu üretir — konu seçimi, web araştırması, kaynaklı senaryo, Türkçe seslendirme, kelime vurgulu altyazı, görsel/video temini, HyperFrames ile hareketli kurgu, müzik/efekt, kalite kontrolü ve dışa aktarım. "Video üret", "reels hazırla", "yeni içerik", "kategori X için video" gibi isteklerde kullanılır.
---

# Reels üretim akışı (Claude Code ajanı için)

Çalışma klasörü: `reels-factory/`. Bütün komutlar bu klasörden çalıştırılır.
Senaryo biçimi ve yazım kuralları: [script-format.md](script-format.md) — senaryo yazmadan önce oku.

Bu akışta **dil modeli adımı (konu, araştırma, senaryo) sensin**. Geri kalan her şeyi
`scripts/factory.py` yapar ve her adımı `projects/<görev>/job.json` içine kaydeder.

## 0. Ortam (oturum başına bir kez)

```bash
python scripts/factory.py doctor
```

"Durum: HAZIR" değilse README.md → Kurulum. Doctor'ın "YOK" dediği hizmeti varmış gibi
kullanma; kullanıcıya hangi yöntemin kullanılamadığını ve yerine ne yapıldığını açıkça söyle.

## 1. Görev ve brif

```bash
python scripts/factory.py new --manual [--category bilim-uzay] [--topic "isteğe bağlı konu"]
```

`--manual`: senaryoyu sen yazacaksın (aksi halde komut, Claude API'yi veya kurulu Claude Code'u
arka planda çağırır). Kategori verilmezse sistem, ayarlardaki ağırlıklara göre en az kullanılan kategoriyi seçer.
`projects/<görev>/brief.json` dosyasını oku: ton, hedef kitle, örnek konular, **daha önce işlenen
başlıklar** (tekrarlama), hedef süre ve görsel sağlayıcı sırası. `format` alanındaki **anlatım biçimine** uy
(liste, karşılaştırma, hikâye...) ve `recent_titles_all` konularından farklı bir alt konu/açı seç (`variety_rule`).
Görünümü (renk, yazı tipi, altyazı, efekt) sistem tasarım temasıyla otomatik değiştirir; senaryoya yazma.

## 2. Konu ve araştırma

- Konu verilmemişse kategoriye uygun, merak uyandıran, daha önce işlenmemiş bir konu seç.
- WebSearch / WebFetch ile araştır. Birincil ve güvenilir kaynakları tercih et (resmî kurumlar,
  akademik kaynaklar, köklü yayınlar). Her sayıyı en az bir birincil kaynakta doğrula; kaynaklar
  çelişiyorsa ayrıntıyı ya açıkla ya da kullanma.
- Yanlış anlaşılmaya açık noktaları not et ve senaryoda doğru ifade et.

## 3. Senaryo

`projects/<görev>/script.json` dosyasını [script-format.md](script-format.md)'ye göre yaz:
hook (0–3 sn) → setup → body → payoff → outro; 5–10 sahne; `sources` ve `facts` zorunlu.

**Kanca (YouTube agent skill, `skills/youtube-agent/yt-script`):** `hooks.json`'daki 21 kalıptan 5 farklı açılış
cümlesi yaz ve puanla; en yükseğini ilk sahneye koy. Başlık ile ilk sahnenin `headline`'ı (kapak) aynı kelimeleri
tekrar etmesin.

```bash
python scripts/factory.py hook "kanca 1" "kanca 2" "kanca 3" "kanca 4" "kanca 5"
python scripts/factory.py title "<başlık>" --thumb "<ilk sahne headline>"
python scripts/factory.py validate <görev>
```

Hata kalmayana kadar düzelt (`UYARI` satırları üretimi durdurmaz ama kanca/başlık uyarısını ciddiye al). Tahmini süre 30–60 sn olmalı.

## 4. Görseller

Varsayılan sıra kategoriden gelir (ör. `agent_media → ai_video → ai_image → nasa → pexels → openverse`).
Anahtarı olmayan sağlayıcılar sessizce atlanır; hiçbiri sonuç vermezse sahne hareketli grafikle üretilir.

Otomatik seçim metin tabanlıdır; **sonucu mutlaka gözle denetle**:

```bash
python scripts/factory.py candidates <görev> <sahne> [--query "farklı sorgu"]
```

`projects/<görev>/qc/candidates_<sahne>.jpg` görüntüsünü Read ile aç; uygun adayı
`visual.pick: "nasa:3"` ile seç. Çok panelli görsellerde `crop`, uzay/obje fotoğraflarında
`fit: "contain"` + `align`, kapanışta açılış görseline dönmek için `reuse` kullan.
İçinde yazı, filigran, insan kalabalığı veya konuyla ilgisiz öğe olan görselleri seçme.

**Video klipler:** `visuals.prefer_video` açıkken fotoğraf sahnelerinde önce ilgili stok/arşiv video klip denenir
(Pexels/Pixabay anahtarı varsa onlar, yoksa NASA video arşivi; arşiv klipleri yazı/konuşan kişi için Claude
denetiminden geçer). Bir sahnede kesin video istiyorsan `visual.kind: "video"`; klibin başlangıcı `visual.start` (sn).
`candidates` çıktısında klipler de görünür; yazı, filigran veya konuşan kişi içeren klibi seçme.

**Gerçek kişiler:** Sahne bir kişiyi göstermeliyse `visual.subject` ver; `wikipedia` sağlayıcısı kişinin
maddesindeki görselleri, diğerleri adın geçtiği sonuçları getirir. Yüzden kişi tanımlama yapma;
doğrulama yalnızca metin kanıtıyla (madde ana görseli / başlık-açıklamada ad) yapılır. Başka tanınmış
kişileri gösteren görselleri kullanma. `visuals.license_mode: any` ise lisans denetlenmez; bunu
kullanıcıya yayın öncesi telif riski olarak raporla.

**Yapay zekâ ile görsel/video üretimi:** Oturumda bir üretim aracı varsa (ör. Higgsfield MCP) ve
kullanıcı maliyeti onayladıysa, sahnenin `visual.prompt` istemiyle üret, dosyayı
`projects/<görev>/media/<sahne>.mp4` (veya `.jpg`) olarak kaydet ve yanına lisans/atıf bilgisiyle
`<sahne>.json` yaz. Kredi/ücret harcayan çağrıları **kullanıcı onayı olmadan yapma**; bakiye
yetersizse bunu söyle ve ücretsiz yönteme geç.

## 4b. Kullanıcı metninden video ve kendi çizimlerin

`new --manual --text-file <dosya> [--draw]`: brief.json → `user_text` videonun temelidir. Metni incele,
iddialarını web'de doğrula, yanlış/abartılı ifadeleri düzelt (düzeltmeleri `facts`'e not et), anlamı ve
tonu koruyarak senaryoya çevir.

`--draw` (brief → `draw_visuals: true`): her fotoğraf sahnesi için `projects/<görev>/media/<sahne>.svg`
yaz — özgün, sahneyle uyumlu illüstrasyon (`viewBox="0 0 1080 1920"`, gradyan/katman/ışık; **içinde yazı yok**).
Yerleşim: üst bölge (y<600) başlık için, y=1130–1330 altyazı bandı için sade kalsın; ana öğe
y=620–1100 ve x=150–930 içinde. Yanına `<sahne>.json`: `{"provider":"agent_svg","title":"…","license":"özgün çizim (Claude)"}`;
sahnenin `visual`'ı `{"kind":"photo","providers":["agent_media"],"fit":"cover"}`. Gerçek kişileri çizerek
taklit etme. Üretimden önce SVG'leri `ffmpeg -i x.svg x.png` ile görüntüleyip Read ile kontrol et.

## 5. Üretim

```bash
python scripts/factory.py produce <görev>
```

Adımlar: voice → captions → visuals → music → compose → render → mix → qc → export.
Tamamlanan adımlar atlanır; `script.json` değişirse ses adımından itibaren yeniden üretilir.
Belirli bir adımdan yeniden başlatmak için: `--from compose`. Durum: `python scripts/factory.py status <görev>`.

## 6. Kalite kontrolü (otomatik + görsel)

Otomatik QC: çözünürlük/fps/codec, ses akışı, A/V süresi, bozuk kare, siyah ekran, hareketsiz bölüm,
sessizlik, loudness (−14 LUFS), kapanış payı, güvenli alanlar, konuşma tanıma ile anlaşılırlık (WER) ve
altyazı-ses senkronu. Format/loudness/süre hataları otomatik düzeltilir; siyah kare bulunursa ilgili
sahneler grafik arka planla yeniden üretilir. QC'den geçemeyen video **asla** "tamamlandı" sayılmaz.

Ardından **gözle denetle** (Read ile aç):
- `projects/<görev>/qc/contact_sheet.jpg` — görüntüler senaryoyla uyumlu mu, yazılar okunaklı mı,
  boş/çirkin kare var mı?
- `projects/<görev>/qc/report.json` — uyarılar.

Sorun varsa script.json'u düzelt (görsel seçimi, metin) ve `produce` komutunu yeniden çalıştır.

## 7. Teslim

Çıktılar `output/` altında: `videos/<tarih>-<slug>.mp4`, `thumbnails/…jpg`, `captions/…srt` ve
`captions/…txt` (paylaşım metni + kaynaklar + lisans atıfları). Kullanıcıya şunları raporla:
video yolu, süre, QC özeti (geçen/uyarı), kullanılan sağlayıcılar, atıf gerektiren içerikler ve
kullanılamayan hizmetler (ör. "AI video üretimi yapılandırılmamış; fotoğraf + kamera hareketi kullanıldı").

## Kurallar

- API anahtarlarını koda, senaryoya veya loglara yazma; yalnızca `.env`.
- Kullanıcı dosyalarını (assets/music, projects, output) izinsiz silme/üzerine yazma.
- Yalnızca kullanım izni olan medya: NASA (kamu malı; ESA/JAXA gibi ortak kurum görselleri hariç),
  Openverse CC0/kamu malı/CC BY (atıfla), Pexels lisansı, kullanıcının `assets/music/licenses.yaml`
  ile kayıtlı parçaları. Piper Türkçe sesi ticari olmayan lisanslıdır; varsayılan kapalıdır.
- Gerçek video üretimi kullanılamıyorsa bunu açıkça belirt; alternatif (fotoğraf + kamera hareketi +
  hareketli grafik) kullanıldığını raporla.
