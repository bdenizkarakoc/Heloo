# Müzik kütüphanesi

Buraya **kullanım hakkına sahip olduğunuz** müzik dosyalarını koyun ve her birini `licenses.yaml`
içine kaydedin. Kayıtlı olmayan dosyalar kullanılmaz (telif güvenliği).

```yaml
tracks:
  - file: sakin-uzay.mp3
    title: "Sakin Uzay"
    license: owned          # owned | licensed | royalty-free | cc0 | by
    credit: ""              # CC BY ise atıf metni (paylaşım metnine eklenir)
    source: "https://..."   # satın alma / lisans sayfası
    mood: [ambient, space, calm]
```

**`music.license_mode: any` iken** (şu anki ayar) bu klasördeki **her** ses dosyası kayıt olmadan da
kullanılır. Dosya adında sanatçı/konu adı geçen parçalar (ör. `Cem Karaca - Islak Islak.mp3`) o konudaki
videolarda otomatik öne alınır; belirli bir parça için senaryoya `"music": {"file": "dosya-adı.mp3"}` yazın.
Sözlü şarkılar anlatım sırasında daha derine kısılır (`music.vocal_duck_gain_db`). Kullanım hakkı
doğrulanmayan parçalar paylaşım metninde belirtilir; telif riski kullanıcıdadır (platformlar sesi
kapatabilir veya videoyu kaldırabilir).

Sıra: `library` (bu klasör) → `openverse` (yalnızca CC0 / CC BY, atıf otomatik) → `procedural`
(sistemin ürettiği sade ambiyans). Ayar: `config/settings.yaml → music`.

Müzik dosyaları git'e eklenmez (yalnızca bu README ve `licenses.yaml`).
