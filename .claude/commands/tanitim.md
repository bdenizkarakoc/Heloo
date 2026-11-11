---
description: Ürün tanıtım videosu (Video-Shotcraft becerisi: çekim tarifleri + Remotion şablonu)
argument-hint: "<ürün / site / uygulama ve ne anlatılacağı>"
---
Video-Shotcraft (Apache-2.0, `reels-factory/araclar/shotcraft/`) becerisiyle tanıtım videosu yap.

İstek: $ARGUMENTS

1. `reels-factory/araclar/shotcraft/SKILL.md` yoksa önce kur: `python scripts/factory.py araclar kur shotcraft`
   (`reels-factory` klasöründen).
2. `araclar/shotcraft/SKILL.md` ve `references/pipeline.md` akışını izle; çekimleri `references/shots/` kartlarından seç.
3. Fabrika kuralları önceliklidir: Türkçe metin, dikey 1080×1920 / 30 fps, yalnızca lisansı kayıtlı medya ve müzik,
   yayın yalnızca onay kuyruğuna. Çalışmayı `araclar/shotcraft/` içinde değil, kopyaladığın şablonla
   `reels-factory/projects/<ad>/` altında yap.
4. Bitince videoyu ve bir kare tablosunu kullanıcıya göster.
