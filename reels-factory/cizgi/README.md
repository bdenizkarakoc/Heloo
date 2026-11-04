# Çizgi — kodla çizilen 2D çizgi kısa filmler

Her dosya tek başına bir bölümdür: karakterler, mekânlar, efektler ve müzik dosyanın içinde çizilir/üretilir; seslendirme
fabrikanın ses zinciriyle (`reels.tts`, karakter başına Edge sesi + perde; anahtarlar varsa ElevenLabs) yapılır.
Ağızlar konuşmanın ses seviyesine göre oynar, altyazı konuşanın adıyla gelir, sonda kapanış kartı vardır.

| Dosya | Bölüm |
|---|---|
| `burak_ve_kaan.py` | Burak & Kaan: garaj → portal → Hedonizm-9 → kovalamaca → patlama → garaj (~2 dk, +18) |
| `kahvehane_bocekleri.py` | Kahvehane Böcekleri — Gülme Krizi: düşüş, kahkaha, boğulma, şaplak (~35 sn, +18) |

Çalıştırma (reels-factory klasöründen):

```bash
python cizgi/kahvehane_bocekleri.py            # → output/cizgi/kahvehane_bocekleri/kahvehane_bocekleri.mp4
python cizgi/burak_ve_kaan.py output/deneme    # çıktı klasörü verilebilir
```

Yeni bölüm: bir dosyayı kopyala; `SHOTS` (sahne, ön boşluk, [(konuşan, replik)], son boşluk, ["efekt@sn"]), `VOICE`
(karakter → Edge sesi + perde), karakter çizim fonksiyonları ve `compose` içindeki sahne dallarını değiştir.
Karakterler özgün olmalı (tanınmış/telifli çizgi karakterleri çizilmez); küfürlü bölümler onay kuyruğuna eklenmez.
