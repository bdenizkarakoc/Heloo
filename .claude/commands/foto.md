---
description: Fotoğraflarım klasöründen müzikli montaj ya da anlatımlı video
argument-hint: "[--son N | adlar] [istek] [anlat: ne anlatsın]"
---
`reels-factory/` klasöründen Fotoğraflarım (`Masaüstü\kesim\Fotoğraflarım`) ile video yap.

İstek: $ARGUMENTS

- Önce `python scripts/factory.py foto --list` ile fotoğrafları gör.
- Müzikli montaj: `python scripts/factory.py foto <adlar>|--son N --istek "<tarz>"`.
  Anlatımlı video istenirse `--anlat "<ne anlatsın>"`.
- Fotoğrafları asla silme ya da üzerine yazma. Bitince çıktı yolunu bildir.
