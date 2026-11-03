---
description: Konuyu araştırıp Türkçe Reels videosu üret (Reels Fabrikası)
argument-hint: "<konu ya da kategori>"
---
`reels-factory/` klasöründe `skills/reels-production/SKILL.md` akışıyla bir video üret.

İstek: $ARGUMENTS

- İstek bir kategori adıysa (bilim-uzay, doga-hayvanlar, tarih, muzik-kultur, psikoloji) `--category` ile, değilse konu olarak kullan; boşsa sistem seçsin.
- `python scripts/factory.py new --manual ...` → araştır, kaynaklı `script.json` yaz → `validate` → `produce`.
- Bitince `qc/contact_sheet.jpg` dosyasına bak, sorun varsa düzelt; videonun yolunu ve kaynakları kısaca bildir.
- Yayınlama: yalnızca kanal ayarlarına göre onay kuyruğuna ekle (`/api/publish/queue`), elle yayınlama.
