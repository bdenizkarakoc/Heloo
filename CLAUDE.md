# Heloo

Bu depo "Otonom AI Reels Fabrikası"nı içerir; proje `reels-factory/` klasöründedir.

@reels-factory/CLAUDE.md

`premiere-pro-mcp/` klasöründe Adobe Premiere Pro MCP sunucusu (v1.25.0, MIT, değiştirilmemiş üçüncü taraf kodu)
bulunur; o klasörde çalışırken `premiere-pro-mcp/AGENTS.md` kurallarını izle.

`kesim-kaynak/` kullanıcının Kesim + SelfEdit kaynağıdır (özgün hâli); Fabrika bağlantılı sürüm `reels-factory/kesim-app/` altındadır.

`tv-yansit/` TV Yansıt: ekranı televizyona yansıtan bağımsız uygulama (DLNA + TV tarayıcısı, Miracast paneli,
Lossless Scaling otomatik açma, Steam'e ekleme; yalnızca standart kitaplık + ffmpeg). Testler: `python -m pytest tv-yansit/tests -q`.
