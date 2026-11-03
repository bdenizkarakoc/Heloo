---
description: "Şunun gibi yap": bağlantıdaki/örnek videonun tarzıyla montaj
argument-hint: "<Instagram/TikTok/YouTube bağlantısı | referans video> [dosyalar] [istek]"
---
`reels-factory/` klasöründen referansın tarzıyla Kesim montajı yap.

İstek: $ARGUMENTS

- `python scripts/factory.py kesim <dosyalar...> --ref <bağlantı|video> [--istek "..."]`.
- Referansın kendi görüntüsü ve müziği kullanılmaz; yalnızca tarzı (kesim temposu, geçiş, renk, yazı) ve aynı tempoda lisanslı müzik.
- Bitince çıktı yolunu ve referanstan neyin alındığını kısaca bildir.
