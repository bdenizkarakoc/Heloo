/* Fabrika sayfalarının (/, /kesim, /photos) ortak /komutları. komut.js'ten sonra yüklenir.
 *   fabrikaKomutlari({ kesim: true, ref: (url, istek) => …, foto: (mode, istek) => … }) → komut listesi
 * Sayfa kendi davranışını verirse (ör. /kesim sayfasında /ref bir sonraki bırakılan dosyalara uygulanır) onu kullanır,
 * vermezse ilgili sayfaya gider. */
(function () {
  "use strict";
  const post = async (p, body) => {
    const r = await (await fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })).json();
    if (r && r.error) throw new Error(r.error);
    return r;
  };
  const go = (p) => { location.href = p; return "Açılıyor…"; };
  const q = (o) => "?" + new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
  const URL_RE = /https?:\/\/\S+/i;

  window.fabrikaKomutlari = function (page = {}) {
    const list = [
      { name: "video", args: "<konu>", needArgs: true, desc: "Konuyu araştırıp video üret", run: async (a) => {
        await post("/api/new", { topic: a.length <= 80 ? a : "", text: a.length > 80 ? a : "", count: 1, kesim: !!page.kesim });
        return "Video üretimi sıraya alındı. Bitince " + (page.kesim ? "Hazır klasörüne konur." : "listede görünür."); } },
      { name: "metin", args: "<metnin>", needArgs: true, desc: "Kendi metninden video (incelenir, doğrulanır)", run: async (a) => {
        await post("/api/new", { text: a, count: 1, kesim: !!page.kesim }); return "Metinden video sıraya alındı."; } },
      { name: "foto", alias: ["fotograf"], args: "[istek]", desc: "Fotoğraflarından müzikli montaj", run: (a) => page.foto ? page.foto("montaj", a) : go("/photos" + q({ istek: a })) },
      { name: "anlat", args: "<ne anlatsın>", desc: "Fotoğraflarından seslendirmeli, altyazılı video", run: (a) => page.foto ? page.foto("anlatim", a) : go("/photos" + q({ mode: "anlatim", istek: a })) },
      { name: "fotolar", desc: "Fotoğraflarım klasörünü aç (fotoğrafları buraya at)", run: async () => "Klasör: " + (await post("/api/photos/open")).path },
      { name: "kesim", alias: ["montaj"], args: "[istek]", desc: "Kesim: video/fotoğraf bırak → montaj", run: (a) => page.kesimIstek ? page.kesimIstek(a) : go("/kesim" + q({ istek: a })) },
      { name: "ref", alias: ["benzet", "gibi"], args: "<bağlantı> [istek]", needArgs: true, desc: "Şunun gibi yap: bağlantıdaki videonun tarzıyla montaj", run: (a) => {
        const u = (a.match(URL_RE) || [""])[0];
        if (!u) throw new Error("Instagram/TikTok/YouTube bağlantısı yaz.");
        const rest = a.replace(u, "").trim();
        return page.ref ? page.ref(u, rest) : go("/kesim" + q({ ref: u, istek: rest })); } },
      { name: "not", args: "<bağlantı>", needArgs: true, desc: "Reel'den Obsidian notu (döküm + fikirler)", run: async (a) => {
        await post("/api/notes/create", { url: a.trim() }); return "Not çıkarma sıraya alındı (🎬 Stüdyo → Notlar)."; } },
      { name: "kanca", args: "<ilk cümle>", needArgs: true, desc: "Açılış cümlesinin kanca puanı", run: async (a) => {
        const r = await post("/api/tools/hook", { text: a });
        return `Kanca puanı ${r.verdict}/100 (${r.band_tr}) · kalıp: ${r.formula}\nEn zayıf: ${r.weakest} → ${r.fix}`; } },
      { name: "baslik", args: "<başlık> [| kapak yazısı]", needArgs: true, desc: "Başlık + kapak yazısı denetimi", run: async (a) => {
        const [t, th] = a.split("|").map((x) => x.trim());
        const r = await post("/api/tools/title", { title: t, thumb: th || null });
        return [`“${r.title}” · ${r.chars} karakter · puan ${r.score}/100`, ...r.issues_tr.map((x) => "✖ " + x), ...r.good.map((x) => "✔ " + x)].join("\n"); } },
      { name: "otomatik", args: "aç | kapat", needArgs: true, desc: "Otomatik modu aç/kapat", run: async (a) => {
        const on = /^(a[cç]|on|evet|1)/i.test(a.trim());
        const r = await post("/api/auto", { enabled: on });
        return on ? `Otomatik mod açık · her ${r.interval_hours} saatte bir, günde en çok ${r.daily_max}` : "Otomatik mod kapalı."; } },
      { name: "durum", desc: "Fabrika şu an ne yapıyor", run: async () => {
        const s = await (await fetch("/api/status")).json();
        const c = s.current;
        return [c ? `Çalışıyor: ${c.topic || c.kind} (${c.job || "hazırlanıyor"})` : "Boşta.",
          `Sırada: ${(s.pending || []).length}`, s.claude_limit || ""].filter(Boolean).join("\n"); } },
      { name: "kur", alias: ["videokur"], desc: "Video Kur: görsel, senaryo, ses, altyazı ve kurguyu ayrı ayrı ver", run: () => go("/kur") },
      { name: "sesim", alias: ["ses"], desc: "Sesim: kendi sesinle seslendirme (aç/kapat, dene)", run: () => go("/voice") },
      { name: "yayin", desc: "Yayın sayfası (onay kuyruğu)", run: () => go("/publish") },
      { name: "studyo", desc: "Stüdyo: kendi videonu düzenle, stil öğret", run: () => go("/studio") },
      { name: "panel", desc: "Kontrol paneli", run: () => go("/") },
    ];
    list.push({ name: "yardim", alias: ["help", "komutlar"], desc: "Bütün komutlar", run: () => FabrikaKomut.help(list) });
    return list;
  };
})();
