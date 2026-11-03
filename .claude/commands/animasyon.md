---
description: Çizgi-3D animasyon kısa film (2D karakterler 3D dünyada, three.js + Remotion) — Türkçe, özgün hikâye
argument-hint: "<gerçek, şaşırtıcı bir hikâye/konu>"
---
`reels-factory/animasyon/` becerisiyle Türkçe animasyon kısa film yap.

Konu: $ARGUMENTS

1. Önce `reels-factory/animasyon/TURKCE.md` (fabrika kuralları, öncelikli), sonra `reels-factory/animasyon/SKILL.md` (akış) oku.
2. Konu ve olgular → `animasyon/studio/shorts/<ad>/SCRIPT.md` (kaynaklarıyla), Türkçe senaryo ~120-150 kelime;
   kancayı `python scripts/factory.py hook` ile seç. Senaryoyu kullanıcıya göster, onay gelince gerisini kendin yürüt.
3. Ses: `python scripts/factory.py anim-ses <SCRIPT metni> animasyon/studio/shorts/<ad>/voice`.
4. `templates`/`src/videos/bridge`'den başlayıp yeni dünya, oyuncular ve çekim planı yaz; kareleri al, bak, düzelt; sesi
   (sfx + müzik + miks) üret; son render + mux + QA.
5. Son videoyu `output/videos/` altına koy, kullanıcıya gönder; yayın yalnızca onay kuyruğuna.
Hikâye, karakterler ve ses özgün olmalı; başka bir kanalın içeriğini ya da tanınmış çizgi karakterleri kopyalama.
