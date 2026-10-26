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

Sıra: `library` (bu klasör) → `openverse` (yalnızca CC0 / CC BY, atıf otomatik) → `procedural`
(sistemin ürettiği sade ambiyans). Ayar: `config/settings.yaml → music`.

Müzik dosyaları git'e eklenmez (yalnızca bu README ve `licenses.yaml`).
