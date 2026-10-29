/* Kesim: "🌐 Kütüphane" sekmesi — internetten ücretsiz ses efekti, müzik, görsel, PNG ve video (CapCut'taki hazır
 * içerik paneli gibi). Arama ve indirme Reels Fabrikası üzerinden yapılır (scripts/reels/library.py): yalnızca CC0,
 * kamu malı ve CC BY; her indirmenin atfı kaydedilir ve buradan kopyalanabilir.
 * Dinamik metinler yalnızca textContent ile yazılır. */
(function () {
  "use strict";
  const FB = window.fabrika;
  const tabs = document.getElementById("leftTabs"), side = document.getElementById("sideL");
  if (!FB || !tabs || !side || typeof addMedia !== "function") return;

  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return e;
  };
  const mimeOf = (n) => /\.(mp4|m4v)$/i.test(n) ? "video/mp4" : /\.webm$/i.test(n) ? "video/webm" : /\.ogv$/i.test(n) ? "video/ogg"
    : /\.wav$/i.test(n) ? "audio/wav" : /\.mp3$/i.test(n) ? "audio/mpeg" : /\.(m4a|aac)$/i.test(n) ? "audio/mp4"
    : /\.(ogg|oga|opus)$/i.test(n) ? "audio/ogg" : /\.flac$/i.test(n) ? "audio/flac"
    : /\.png$/i.test(n) ? "image/png" : /\.jpe?g$/i.test(n) ? "image/jpeg" : /\.gif$/i.test(n) ? "image/gif" : /\.webp$/i.test(n) ? "image/webp" : "";
  const fmt = (s) => s == null ? "" : s < 60 ? `${s.toFixed(s < 10 ? 1 : 0)} sn` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const AUDIO = new Set(["sfx", "music"]);

  /* ---------- sekme ---------- */
  if (typeof TABN === "object") TABN.lib = "Lib";
  tabs.append(h("button", { "data-tab": "lib" }, "🌐 Kütüphane"));
  const panel = h("div", { class: "tabp", id: "tabLib", hidden: true });
  side.append(panel);
  const css = document.createElement("style");
  css.textContent = `
  #tabLib h2{margin:14px 0 6px} #tabLib .note{margin:4px 0}
  #tabLib input[type=search]{flex:1;min-width:0;background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px;font:inherit}
  .lb-kinds,.lb-pre{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
  .lb-row{display:flex;gap:6px;align-items:center}
  .lb-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
  .lb-card{border:1px solid var(--line);border-radius:9px;overflow:hidden;background:var(--panel2);display:flex;flex-direction:column}
  .lb-card img{width:100%;aspect-ratio:16/10;object-fit:cover;background:#0006;display:block}
  .lb-card.png img{object-fit:contain;background:repeating-conic-gradient(#8883 0 25%,transparent 0 50%) 0 0/14px 14px}
  .lb-meta{padding:5px 7px;font-size:11px;color:var(--mute);min-width:0}
  .lb-meta b{display:block;color:var(--fg);font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lb-acts{display:flex;flex-wrap:wrap;gap:4px;padding:0 7px 7px}
  .lb-acts .btn{flex:1 1 60px;min-width:0;padding:4px 6px;font-size:12px}
  #leftTabs{grid-template-columns:repeat(3,minmax(0,1fr))} #leftTabs button{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .lb-aud{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid var(--line);border-radius:9px;padding:6px 8px;margin-top:6px;background:var(--panel2)}
  .lb-aud .lb-meta{padding:0} .lb-play{width:30px;height:30px;border-radius:50%;padding:0}
  .lb-busy{opacity:.55;pointer-events:none}
  .lb-cred{font-size:11px;color:var(--mute);max-height:150px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:6px;white-space:pre-wrap}`;
  document.head.append(css);

  /* ---------- durum ---------- */
  let kinds = { sfx: "Ses efekti", music: "Müzik", image: "Görsel", png: "PNG / çıkartma", video: "Video" }, presets = {};
  let kind = "sfx", query = "", page = 1, seq = 0;
  const player = new Audio();
  player.preload = "none";
  let playing = null;

  const kindBox = h("div", { class: "lb-kinds" });
  const input = h("input", { type: "search", placeholder: "Ara (İngilizce daha çok sonuç verir: whoosh, rain…)" });
  const preBox = h("div", { class: "lb-pre" });
  const info = h("div", { class: "note" });
  const results = h("div");
  const more = h("button", { class: "btn", hidden: true, onclick: () => load(page + 1, true) }, "Daha fazla");
  const credBox = h("div", { class: "lb-cred" });

  panel.append(
    h("h2", {}, "Ücretsiz kütüphane"),
    h("p", { class: "note" }, "İnternetten telifsiz içerik: yalnızca CC0, kamu malı ve CC BY. Eklediğin her şeyin atfı aşağıda tutulur."),
    kindBox,
    h("form", { class: "lb-row", onsubmit: (e) => { e.preventDefault(); query = input.value.trim(); load(1); } },
      input, h("button", { class: "btn pri", type: "submit" }, "Ara")),
    preBox, info, results, h("div", { class: "lb-row", style: "margin-top:8px" }, more),
    h("h2", {}, "Atıflar"),
    h("p", { class: "note" }, "CC BY içeriklerde paylaşım metnine atıf yazmak zorunlu. Kopyalayıp açıklamaya yapıştır."),
    credBox,
    h("div", { class: "lb-row", style: "margin-top:6px" },
      h("button", { class: "btn", onclick: copyCredits }, "Atıfları kopyala"),
      h("button", { class: "btn", onclick: loadCredits }, "Yenile")));

  function drawKinds() {
    kindBox.replaceChildren(...Object.entries(kinds).map(([k, n]) =>
      h("button", { class: "chip" + (k === kind ? " on" : ""), onclick: () => { kind = k; query = ""; input.value = ""; drawKinds(); load(1); } }, n)));
    preBox.replaceChildren(...(presets[kind] || []).map((p) =>
      h("button", { class: "chip", onclick: () => { query = p.q; input.value = p.q; load(1); } }, p.label)));
  }

  /* ---------- arama ---------- */
  async function load(p, append = false) {
    const my = ++seq;
    page = p;
    if (!append) results.replaceChildren();
    more.hidden = true;
    info.textContent = "Aranıyor… (ilk aramada 20-40 sn sürebilir; sonuçlar bir saat önbellekte kalır)";
    try {
      const r = await FB.get(`/api/kesim/library?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(query)}&page=${p}`);
      if (my !== seq) return;
      if (r.error) throw new Error(r.error);
      query = r.q;
      if (!input.value) input.placeholder = `Örnek: ${r.q}`;
      const list = r.results || [];
      info.textContent = list.length || append ? `“${r.q}” · ${kinds[kind]}` : "Sonuç yok. Başka bir kelime dene (İngilizce daha iyi sonuç verir).";
      const grid = AUDIO.has(kind) ? results : (results.querySelector(".lb-grid") || results.appendChild(h("div", { class: "lb-grid" })));
      for (const it of list) grid.append(AUDIO.has(kind) ? audioRow(it) : card(it));
      more.hidden = list.length < 10;
    } catch (e) {
      if (my === seq) info.textContent = "Arama başarısız: " + e.message;
    }
  }

  const meta = (it) => h("div", { class: "lb-meta", title: `${it.title}\n${it.credit}\n${it.source}` },
    h("b", {}, it.title), [fmt(it.duration), it.license, it.source].filter(Boolean).join(" · "));

  function audioRow(it) {
    const play = h("button", { class: "btn lb-play", title: "Dinle" }, "▶");
    play.onclick = () => {
      if (playing === play) { player.pause(); play.textContent = "▶"; playing = null; return; }
      if (playing) playing.textContent = "▶";
      player.src = it.preview; player.currentTime = 0;
      player.play().then(() => { play.textContent = "❚❚"; playing = play; }).catch(() => toast("Önizleme çalınamadı"));
    };
    const row = h("div", { class: "lb-aud" }, play, meta(it),
      h("button", { class: "btn", title: "Oynatma çizgisine ekle", onclick: () => add(it, "audio", row) }, "+ Ekle"));
    return row;
  }
  player.onended = () => { if (playing) playing.textContent = "▶"; playing = null; };

  function card(it) {
    const c = h("div", { class: "lb-card" + (kind === "png" ? " png" : "") },
      h("img", { src: it.preview, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }), meta(it));
    const acts = h("div", { class: "lb-acts" });
    if (kind !== "png") acts.append(h("button", { class: "btn", title: "Ana zaman çizelgesine ekle", onclick: () => add(it, "main", c) }, "+ Ekle"));
    acts.append(h("button", { class: "btn", title: "Görüntünün üstüne katman olarak koy", onclick: () => add(it, "ov", c) }, kind === "png" ? "+ Katman" : "Katman"));
    c.append(acts);
    return c;
  }

  /* ---------- ekleme ---------- */
  async function add(it, where, el) {
    el.classList.add("lb-busy");
    try {
      toast(`İndiriliyor: ${it.title}`);
      const { task } = await FB.post("/api/kesim/library/fetch", { id: it.id });
      const r = await FB.wait(task);
      const data = await FB.fetch(r.output);
      const m = await addMedia(new File([data], r.name, { type: mimeOf(r.name) }));
      if (!m) throw new Error("dosya açılamadı");
      if (typeof renderBin === "function") renderBin();
      if (m.kind === "audio") addToTimeline(m, t);
      else if (where === "ov" && total) addOverlay(m, t);
      else addToTimeline(m);
      toast(`Eklendi: ${it.title} (${r.license})`);
      loadCredits();
    } catch (e) {
      toast("Eklenemedi: " + e.message, 6000);
    } finally { el.classList.remove("lb-busy"); }
  }

  /* ---------- atıflar ---------- */
  let creds = [];
  async function loadCredits() {
    try { creds = await FB.get("/api/kesim/library/credits"); } catch { creds = []; }
    credBox.textContent = creds.length ? creds.slice().reverse().map((c) => `${c.credit} — ${c.page || c.source}`).join("\n") : "Henüz bir şey eklenmedi.";
  }
  async function copyCredits() {
    const txt = creds.filter((c) => !/^(CC0|Kamu)/.test(c.license || "")).map((c) => `${c.credit} ${c.page || ""}`.trim()).join("\n");
    try { await navigator.clipboard.writeText(txt || "Atıf gerektiren içerik yok (hepsi CC0 / kamu malı)."); toast("Atıflar kopyalandı"); }
    catch { toast("Kopyalanamadı"); }
  }

  /* ---------- açılış ---------- */
  let opened = false;
  tabs.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.tab !== "lib" || opened) return;
    opened = true;
    FB.get("/api/kesim/library/presets").then((r) => { kinds = r.kinds || kinds; presets = r.presets || {}; drawKinds(); load(1); })
      .catch((e2) => { drawKinds(); info.textContent = "Fabrikaya bağlanılamadı: " + e2.message; });
    loadCredits();
  });
  drawKinds();
})();
