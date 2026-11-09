# Heloo

Bu depo "Otonom AI Reels Fabrikası"nı içerir; proje `reels-factory/` klasöründedir.

@reels-factory/CLAUDE.md

`premiere-pro-mcp/` klasöründe Adobe Premiere Pro MCP sunucusu (v1.25.0, MIT, değiştirilmemiş üçüncü taraf kodu)
bulunur; o klasörde çalışırken `premiere-pro-mcp/AGENTS.md` kurallarını izle.

`kesim-kaynak/` kullanıcının Kesim + SelfEdit kaynağıdır (özgün hâli); Fabrika bağlantılı sürüm `reels-factory/kesim-app/` altındadır.

`iptv/` Heloo TV IPTV oynatıcısıdır (PySide6 + libmpv; RTX VSR `d3d11vpp scaling-mode=nvidia`). O klasörde çalışırken
`iptv/CLAUDE.md` kurallarını izle; testler `cd iptv && python -m pytest tests -q`.
