# Bulut rutini — otomatik Reels üretimi ve teslimi

Bu dosyayı zamanlanmış bulut oturumu (Claude Code on the web) her çalışmada baştan sona izler.
Kullanıcı: biridaldc@gmail.com · Depo: bdenizkarakoc/Heloo · Kod dalı: `claude/autonomous-ai-reels-factory-x82681`
· Teslim dalı: `reels-videos` (yalnızca `scripts/deliver.sh` yazar).

## 0. Hazırlık
```bash
git fetch origin claude/autonomous-ai-reels-factory-x82681
git checkout -B claude/autonomous-ai-reels-factory-x82681 origin/claude/autonomous-ai-reels-factory-x82681
cd reels-factory && bash scripts/cloud-setup.sh
```

## 1. Kendi kendini denetle ve onar
`python3 scripts/factory.py selftest` çalıştır.
- Başarısızsa `logs/selftest.json` ve ilgili logları incele, hatanın kök nedenini bul ve **en küçük** kod
  düzeltmesini yap. `selftest` tekrar başarılı olursa düzeltmeyi kod dalına commit edip push et
  (`git push -u origin claude/autonomous-ai-reels-factory-x82681`). Testleri atlama, devre dışı bırakma.
- Onaramıyorsan kullanıcıya hatayı anlatan kısa bir e-posta gönder (konu: "Reels Fabrikası: hata") ve dur.
- Dış hizmet kesintisi (ör. edge-tts, Openverse geçici hata) kod hatası değildir; bir kez yeniden dene, sürerse raporla.

## 2. Kullanıcının metinleri (gelen kutusu)
Gmail'de `from:biridaldc@gmail.com subject:Reels: is:unread newer_than:14d` ara (en fazla 2 ileti).
Her biri için:
1. Metin = e-postanın gövdesi (konudaki "Reels:" sonrası konu ipucudur).
2. `python3 scripts/factory.py new --manual --draw --text-file <metin dosyası> [--topic "<konu>"]`
   (gövde "görsel: arama" içeriyorsa `--draw` kullanma; o zaman lisanslı/arama görselleri kullanılır).
3. `skills/reels-production/SKILL.md` akışını uygula: metni incele ve web'de doğrula, yanlışları düzelt
   (facts'e not et), anlamı koru, senaryoyu yaz, `validate` et. `--draw` ise her fotoğraf sahnesi için
   `projects/<görev>/media/<sahne>.svg` illüstrasyonunu çiz (kurallar SKILL.md'de).
4. `produce`, ardından `qc/contact_sheet.jpg`'i Read ile denetle; sorun varsa düzeltip yeniden üret.
5. Teslim et (adım 4) ve e-postayı **aynı konuya yanıt** olarak gönder; ileti okundu yapılsın
   (UNREAD etiketini kaldır).

## 3. Otomatik video
Gelen kutusunda metin yoksa (veya metinlerden sonra süre kalıyorsa) 1 otomatik video üret:
`python3 scripts/factory.py new --manual` (kategori ağırlıklara göre seçilir; `brief.json`'daki geçmiş
başlıkları tekrarlama) → SKILL.md akışı (araştırma, kaynaklı senaryo, görsel denetimi) → `produce` → denetim.

## 4. Teslim
```bash
bash scripts/deliver.sh output/videos/<slug>.mp4 output/thumbnails/<slug>.jpg output/captions/<slug>.txt output/captions/<slug>.srt
```
Yazdırılan GitHub bağlantısını kullanıcıya e-postayla gönder (Gmail, alıcı: biridaldc@gmail.com,
konu: "Yeni Reels: <başlık>"). Gövdede: bağlantı, süre, QC özeti (geçen/uyarı), paylaşım metni (txt
içeriği) ve "kullanım hakkı doğrulanmadı" uyarıları varsa bunlar. Video ekleme; yalnızca bağlantı.

## Kurallar
- Ücretli API/kredi harcama (ör. Higgsfield) yok; `.env` anahtarı yoksa ücretsiz yöntemler kullanılır.
- Kod dalına yalnızca `selftest` ile doğrulanmış düzeltmeler gönderilir; `reels-videos` dalına yalnızca `deliver.sh`.
- Gerçek kişileri yüz tanımayla tanımlama; kişi görselleri metin kanıtıyla doğrulanır (SKILL.md).
- Uydurma bilgi yok; doğrulanamayan iddia senaryoya girmez.
- Sonunda kısa bir özet yaz: üretilen videolar, bağlantılar, yapılan düzeltmeler, sorunlar.
