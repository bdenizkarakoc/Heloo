# script.json — senaryo biçimi ve yazım kuralları

Bu dosya hem Claude Code ajanı (SKILL.md akışı) hem de tam otonom mod (`scripts/reels/llm.py`)
tarafından kullanılır. Doğrulayıcı: `python scripts/factory.py validate <görev>`.

## Anlatı yapısı (30–60 sn)

| Bölüm | Süre | Görev |
|---|---|---|
| hook | 0–3 sn | Tek, çarpıcı cümle. İlk kare kapak gibi çalışır: başlık daha ilk karede ekranda. |
| setup | 3–10 sn | Konuyu/problemi tanıt; izleyicinin "neden önemli?" sorusunu yanıtla. |
| body | 10–40 sn | Ana bilgi; her sahne yeni bir bilgi veya görsel değer getirir. |
| payoff | son bölüm | Şaşırtıcı bilgi / dönüm noktası. Senaryoda **bir** sahne `role: "payoff"` olur (yükselen efekt + vuruş sesi buraya gelir). |
| outro | son 4–7 sn | Sonuç + kısa çağrı (takip et). |

Süreye göre oranları uyarlayın. 5–10 sahne, sahne başına 1–2 cümle (≈ 2–8 sn).
Türkçe TTS hızı ≈ 2,3 kelime/sn; 45 sn ≈ 100–110 kelime.

## Doğruluk kuralları (zorunlu)

- Her sayısal/olgusal iddia `sources` içindeki güvenilir bir kaynağa dayanır (resmî kurum, akademik
  kaynak, köklü yayın). Uydurma bilgi, yanıltıcı başlık, gerçekmiş gibi sunulan kurgu yok.
- Tartışmalı/yanlış anlaşılmaya açık ayrıntıyı ya açıklayın ya da kullanmayın
  (ör. "Venüs'te gün" → yıldız günü 243 gün, güneş günü ≈117 gün; ikisini karıştırmayın).
- `facts` listesine iddiaları ve kaynak indekslerini yazın (izlenebilirlik).

## Seslendirme metni (narration)

- Konuşma dilinde, doğal ve akıcı Türkçe; kısa cümleler. Her sahne noktalama ile biter.
- Sembol yazmayın: `°C` → "santigrat derece", `&` → "ve", `/` → "bölü". Sayıları rakamla yazmak
  sorun değildir (TTS doğru okur: "243" → "iki yüz kırk üç"). Kısaltmaları açın.
- Ekrandaki yazı ile seslendirme birebir aynı olmak zorunda değil; ekran yazısı özet/vurgu olmalı.

## Biçim

```json
{
  "title": "Video başlığı (dosya adı buradan üretilir)",
  "category": "settings.yaml'daki kategori kimliği",
  "summary": "Bir cümlelik özet",
  "music": {"queries": ["ambient space", "cinematic ambient"]},
  "scenes": [ { ...sahne... } ],
  "sources": [{"title": "...", "publisher": "...", "url": "https://..."}],
  "facts": [{"claim": "...", "source": 0}],
  "post": {"caption": "Paylaşım açıklaması", "hashtags": ["uzay", "bilim"]}
}
```

### Sahne

```json
{
  "id": "s1",
  "role": "hook | setup | body | payoff | outro",
  "layout": "hook | photo | stat | compare | list | fact | outro",
  "narration": "Seslendirme metni.",
  "on_screen": { ...layout'a göre... },
  "visual": { ...görsel... },
  "emphasis": ["altyazıda", "vurgulanacak", "kelimeler"],
  "transition": "zoom | whip | iris | wipe | cut",
  "captions": true
}
```

İlk sahne her zaman `layout: "hook"`. Geçişleri çeşitlendirin (3–4 farklı tür); en fazla üçte biri `cut`.

### Yerleşimler (`layout`) ve `on_screen`

| layout | on_screen alanları | Ne zaman |
|---|---|---|
| `hook` | `headline` (≤42 karakter, zorunlu), `kicker` (kısa etiket), `highlight` [kelimeler] | Açılış |
| `photo` | `label` (etiket), `headline` (≤48), `highlight` | Görselin anlattığı sahneler |
| `stat` | `value` (sayı, zorunlu), `unit` (zorunlu), `label`, `prefix`, `suffix`, `decimals`, `cue` (sayının söylendiği kelime), `note` | Tek bir çarpıcı sayı; sayaç, sayı söylenirken hedefe ulaşır |
| `compare` | `items`: 2–3 × `{label, value, suffix?, display?}` (zorunlu), `title`, `cues` [her öğe için tetik kelimesi], `note` (ör. "Gün > Yıl") | İki/üç değeri çubuklarla karşılaştırma |
| `list` | `items`: 2–4 kısa madde (zorunlu, ≤28 karakter), `title`, `cues` | Madde madde bilgi |
| `fact` | `headline` (≤90, zorunlu), `label`, `highlight` | Vurgulu tek cümlelik bilgi kartı |
| `outro` | `headline` (≤60, zorunlu), `highlight`, `cta` | Kapanış + takip çağrısı |

Ekran yazıları kısa tutulur; sığmazsa kompozitör puntoyu küçültür, yine sığmazsa hata verir.

### Görsel (`visual`)

| alan | açıklama |
|---|---|
| `kind` | `photo` (fotoğraf + kamera hareketi), `video` (hareketli klip), `graphic` (yalnızca hareketli grafik) |
| `query` | İngilizce arama sorgusu (NASA / Openverse / Pexels). Somut olun: "Venus Mariner 10". |
| `prompt` | İngilizce üretim istemi (AI görsel/video sağlayıcısı tanımlıysa kullanılır). |
| `providers` | Bu sahne için sağlayıcı sırası (kategori varsayılanını ezer). |
| `pick` | `"nasa:3"` — `factory.py candidates` çıktısındaki aday. |
| `skip` | Kullanılmayacak kaynak URL'leri. |
| `crop` | `[x0, y0, x1, y1]` (0–1 kesirleri) — ör. çok panelli görselden tek panel. |
| `fit` | `auto` (varsayılan), `cover` (tam ekran, kamera hareketi), `card` (kart), `contain` (kesmeden, yumuşak kenarlı; uzay/obje fotoğrafları için ideal). |
| `align` | `contain` için `top`, `center`, `bottom`. |
| `move` | `cover` için kamera: `push`, `pull`, `panl`, `panr`, `up`. |
| `reuse` | Önceki bir sahnenin görselini bilinçli tekrar (ör. kapanışta açılışa dönüş): `"s1"`. |
| `url` + `license` (+ `credit`) | Lisansı bilinen belirli bir görsel/video. Lisans yoksa kullanılmaz. |

Ajanın ürettiği/indirdiği medya: `projects/<görev>/media/<sahne>.(jpg|png|mp4…)` + isteğe bağlı
`<sahne>.json` (`{"provider", "title", "license", "credit", "source"}`); `agent_media` sağlayıcısı
bunu her şeyden önce kullanır.

## Kontrol listesi

- [ ] Hook ilk cümlede merak uyandırıyor ve doğru.
- [ ] Her sahne yeni bilgi/görsel değer getiriyor; tekrar yok.
- [ ] Bütün sayılar kaynaklarla aynı; yuvarlamalar "yaklaşık" ile belirtilmiş.
- [ ] Seslendirmede sembol/kısaltma yok; cümleler noktalama ile bitiyor.
- [ ] `validate` hatasız; tahmini süre 30–60 sn.
