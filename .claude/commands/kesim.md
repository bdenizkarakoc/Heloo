---
description: Kesim ile video/fotoğraf montajı (Masaüstü\kesim\Hazır'a teslim)
argument-hint: "<dosyalar> [istek: enerjik, lo-fi, 30 sn ...]"
---
`reels-factory/` klasöründen Kesim ile montaj yap (Adobe Premiere değil).

İstek: $ARGUMENTS

- Dosya yollarını ve tarif edilen tarzı ayır: `python scripts/factory.py kesim <dosyalar...> --istek "<tarz>"`.
  Dosya verilmediyse `Masaüstü\kesim\Montaja at` klasöründekileri kullan.
- Kesim açıksa `kesim_editor*` MCP araçlarıyla düzenle (geri alınabilir).
- Kullanıcının `Masaüstü\kesim` klasöründeki mevcut dosyalarına dokunma. Bitince çıktı yolunu bildir.
