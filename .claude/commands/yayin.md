---
description: Yayın durumu, onay kuyruğu ve hesap bağlantıları (Instagram/YouTube/TikTok)
argument-hint: "[durum | kur | kuyruk]"
---
`reels-factory/` Yayın sistemini (`scripts/reels/publish.py`, sayfa `/publish`) kullan.

İstek: $ARGUMENTS

- durum (varsayılan): kanalları, bağlı hesapları (`publish.connected`) ve kuyruktaki videoları özetle.
- kur: fabrika çalışmıyorsa `python app/server.py --open --page publish` ile aç; kanal ayarlarında otomatik kuyruk ve onay
  süresini kullanıcıyla belirle; Meta (Instagram/Facebook) ve Google (YouTube) bağlantı adımlarında yol göster.
  Şifreleri ve belirteçleri kullanıcı kendisi girer; sohbete yazdırma, koda yazma (yalnızca `.env`).
- Asla elle yayınlama ve reddedilen videoyu yayınlama; yalnızca kuyruğa ekle.
