# YouTube agent skills (vendored)

Kaynak: https://github.com/Jakeschincariol/youtube-agent-skill (commit a2feb21), MIT lisansı — `LICENSE`.
Dosyalar değiştirilmeden alındı. Türkçe uyarlama (kanca puanı, başlık denetimi) ve sisteme bağlama
`scripts/reels/yt_tools.py` içindedir; bu klasördeki araçlar İngilizce kelime listeleriyle çalışır.

| beceri | sistemde kullanımı |
|---|---|
| yt-script / hookscore.py | senaryo yazımında 5 kanca + puan; `rf hook`; validate ve QC uyarısı |
| yt-package / title.py | başlık + kapak yazısı denetimi; `rf title`; Yayın sayfası |
| yt-edit / deadair.py | Stüdyo: boşluk/dolgu/tekrar kesim listesi (EDL); `rf edl` |
| yt-chapters / chapters.py | Stüdyo uzun video: YouTube bölümleri; `rf chapters` |
| yt-shorts | Stüdyo klip seçimi ilkeleri (yeni ilk cümle, ekran yazısı, döngü) |
| yt-seo, yt-comment, yt-plan, yt-retention, yt-viral, yt-audit | Claude Code becerisi olarak (`/yt-...`) |
