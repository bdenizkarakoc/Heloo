# Animasyon — Reels Fabrikası uyarlaması (Türkçe)

Bu klasör, Mr omi'nin MIT lisanslı **Claude Animated Shorts** becerisidir
([mromidev/claude-animated-shorts](https://github.com/mromidev/claude-animated-shorts)), çalışır hâli
[EssouliAnas/claude-animated-shorts](https://github.com/EssouliAnas/claude-animated-shorts) kopyasından alındı (`LICENSE`).
"2D karakterler renkli 3D dünyada" tarzında 55–70 sn'lik dikey hikâye kısa filmi; three.js + Remotion ile bilgisayarda
render edilir, yapay zekâ video üreticisi yoktur. Tam akış `SKILL.md`; bu dosya fabrikada ondan **farklı olan** kurallardır
ve çakışmada bu dosya geçerlidir.

## Fabrika kuralları (SKILL.md'deki "User rules" yerine)
- **Dil Türkçe.** Seslendirme fabrikanın ses zinciriyle: `python scripts/factory.py anim-ses <metin.txt> animasyon/studio/shorts/<ad>/voice`
  → `voice.wav` (48 kHz) + `words.json` (`[{w, s, e}]`). Sesim'de kendi sesin etkinse o, değilse edge-tts okur.
  Türkçe hız ≈ 2,2 kelime/sn: 55–70 sn ≈ 120–150 kelime (SKILL.md'deki 3,7 İngilizce içindir).
- **Kanca:** `python scripts/factory.py hook "..."` ile 3-5 açılış dene; en yüksek puanlı, doğru olanı kullan.
- **Doğruluk:** gerçek, şaşırtıcı ve görsel bir neden-sonuç hikâyesi; her olgu `SCRIPT.md` başında kaynağıyla.
  Şakalar da gerçek bilgiden çıkar. Uydurma yok.
- **Özgünlük:** hikâye, karakterler, çekimler ve ses her zaman bizim. Başka bir kanalın videosunu, senaryosunu,
  karakterini ya da çekimini kopyalama; tanınmış (telifli) çizgi karakterleri çizme. `references/` yalnızca ölçülmüş
  stil raporlarıdır (renk, ışık, mürekkep, kamera sayıları), içerik değil. `templates/bridge` örneği yalnızca başlangıç
  kodudur; yeni filmde dünya (`build.ts`), oyuncular (`cast.ts`) ve hikâye (`story.ts`) yeni yazılır.
- **Altyazı:** tarz gereği ekranda yazı yok (varsayılan). Kullanıcı isterse son videoya fabrikanın SRT'si eklenebilir.
- **Bayrak/kıyafet/mekân dönemine uygun** (SKILL.md "Readability traps").
- **Çıktı:** son video 1080x1920 (`--scale 1`) ya da 2K (`--scale 1.3333`), H.264/AAC 30 fps; sesi mux ettikten sonra
  `output/videos/` altına kopyala. Yayın yalnızca onay kuyruğuna (`/api/publish/queue`), elle yayın yok.

## Klasörler
| Yol | İçerik |
|---|---|
| `studio/` | Remotion + three.js projesi (`npm ci`, modeller `node scripts/get-models.mjs` ile `public/bridge/kenney/`) |
| `studio/src/videos/<ad>/` | Her kısa filmin kodu (örnek: `bridge/`); `src/Root.tsx`'e kompozisyon olarak eklenir |
| `studio/shorts/<ad>/` | `SCRIPT.md`, `voice/voice.wav` + `words.json`, `audio/` (sentez ses + müzik + miks) |
| `studio/scripts/` | Kare (still) alma, yan yana karşılaştırma, birleştirme, kare kare QA |
| `references/` | Ölçülmüş stil raporları (`STYLE_BIBLE.md`, `reports/*.md`) |

## Bilgisayarda çalıştırma (Windows)
- Kurulum: `scripts/install-all.ps1` animasyon adımını da yapar (npm paketleri + Kenney CC0 modelleri, ~15 MB).
- `REMOTION_TMP`'yi büyük bir sürücüde bir klasöre ayarla: her render paketi `public/`'i geçici klasöre kopyalar ve silmez.
- Ekran kartıyla `angle` (varsayılan) kullanılır; ekran kartı yoksa `REMOTION_GL=swangle` (yazılım, çok yavaş:
  bulutta bir kare ~45 sn ölçüldü).
- Kare kontrolü: `cd animasyon/studio` → `node scripts/bridge-stills.mjs out/<ad>/x_ 100,400 0.5 <Kompozisyon>`.
- Son render: `npx remotion render src/index.ts <Kompozisyon> out/<ad>/video.mp4 --codec h264 --crf 16`, sonra
  `ffmpeg -i video.mp4 -i mix.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k son.mp4`,
  `python scripts/short_qa.py son.mp4 out/<ad>/qa shots.json`.
