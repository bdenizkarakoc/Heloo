/* Kesim ⇄ Reels Fabrikası: sayfa tarafı. "🏭 Fabrika" sekmesini kurar.
 * - Otomatik montaj (bırak ya da zaman çizelgesindekiyle), "şu videoyu yap", seçili klibe altyazı / ses temizleme
 * - Fabrikanın öğrendiği stili uygulama, fabrikanın Claude bağlantısıyla AI asistanı
 * - Dışa aktarılanları Masaüstü\kesim\Hazır'a kaydetme ve fabrikaya öğretme
 * - window.__fabrika: Claude/MCP kontrol kapısının çağırdığı işlevler (durum, araçlar, içe/dışa aktarma)
 * Dinamik metinler her zaman textContent ile yazılır. */
(function () {
  "use strict";
  const FB = window.fabrika;
  // multi.js: çoklu seçim, toplu ayar, geniş yakınlık, büyütülebilir çizelge · library.js: ücretsiz içerik kütüphanesi
  // quality.js: 4K/2K dışa aktarma ve video iyileştirme · wizard.js: montajdan önce “nasıl bir şey istiyorsun?”
  // komut.js: /komut menüsü ve aşağı doğru büyüyen metin kutuları
  let komutReady = Promise.resolve();
  for (const [id, src] of [["fbMulti", "fabrika/multi.js"], ["fbLib", "fabrika/library.js"], ["fbQual", "fabrika/quality.js"],
    ["fbWiz", "fabrika/wizard.js"], ["fbKomut", "fabrika/komut.js"]]) {
    if (document.getElementById(id)) continue;
    const s = document.createElement("script");
    s.id = id; s.src = src;
    if (id === "fbKomut") komutReady = new Promise((r) => { s.onload = r; s.onerror = r; });
    document.head.append(s);
  }
  const tabs = document.getElementById("leftTabs"), side = document.getElementById("sideL");
  if (!tabs || !side) return;

  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return e;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SKEY = "fabrika.ayar";
  const cfg = Object.assign({ saveToReady: true, learn: true, style: "", autoImport: true, caps: null },
    (() => { try { return JSON.parse(localStorage.getItem(SKEY) || "{}"); } catch { return {}; } })());
  const saveCfg = () => { try { localStorage.setItem(SKEY, JSON.stringify(cfg)); } catch { /* özel pencere */ } };

  /* ---------- sekme ---------- */
  if (typeof TABN === "object") TABN.fab = "Fab";
  const btn = h("button", { "data-tab": "fab" }, "🏭 Fabrika");
  tabs.append(btn);
  const panel = h("div", { class: "tabp", id: "tabFab", hidden: true });
  side.append(panel);

  const css = document.createElement("style");
  css.textContent = `
  #tabFab h2{margin:14px 0 6px} #tabFab .note{margin:4px 0}
  #tabFab textarea,#tabFab input[type=text],#tabFab select{width:100%;background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px;font:inherit}
  #tabFab textarea{min-height:58px;resize:vertical} #tabFab textarea.fk-grow{min-height:2.6em;resize:none}
  #tabFab .note{overflow-wrap:anywhere} #tabFab .fb-row .btn{max-width:100%;white-space:normal}
  .fb-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:6px}
  .fb-drop{border:2px dashed var(--line);border-radius:10px;padding:14px;text-align:center;color:var(--mute);cursor:pointer}
  .fb-drop.over,.fb-drop:hover{border-color:var(--accent);color:var(--fg)}
  .fb-job{border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:6px;background:var(--panel2);font-size:12px}
  .fb-job b{font-size:13px} .fb-pct{font:700 14px system-ui;color:var(--accent)}
  .fb-bar{height:7px;border-radius:5px;background:var(--line);overflow:hidden;margin:5px 0} .fb-fill{height:100%;width:2%;background:var(--accent);transition:width .5s}
  .fb-job.ok .fb-fill{background:var(--ok)} .fb-job.bad .fb-fill{background:var(--danger)} .fb-steps{font-size:11px;color:var(--mute);margin-top:3px;line-height:1.5} .fb-ok{color:var(--ok)} .fb-bad{color:var(--danger)}
  .fb-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--danger);margin-right:6px}
  .fb-dot.on{background:var(--ok)} .fb-chk{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--mute);margin-top:4px}
  .fb-ph{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:4px;max-height:300px;overflow:auto;margin-top:6px;border-radius:8px}
  .fb-ph-c{position:relative;aspect-ratio:1;border-radius:6px;overflow:hidden;cursor:pointer;border:2px solid transparent;background:var(--panel2)}
  .fb-ph-c img{width:100%;height:100%;object-fit:cover;display:block} .fb-ph-c.on{border-color:var(--accent)}
  .fb-ph-n{position:absolute;top:2px;left:2px;min-width:18px;height:18px;border-radius:9px;background:var(--accent);color:#000;font:700 11px/18px system-ui;text-align:center;display:none}
  .fb-ph-c.on .fb-ph-n{display:block}
  .fb-ph.over{outline:2px dashed var(--accent)}`;
  document.head.append(css);

  if (!FB) {
    panel.append(h("h2", {}, "Reels Fabrikası"), h("p", { class: "note" }, "Bu bağlantı yalnızca Kesim masaüstü uygulamasında çalışır."));
    return;
  }

  /* ---------- yardımcılar ---------- */
  const status = h("div", { class: "note" }, "Bağlanıyor…");
  const jobsBox = h("div");
  const mimeOf = (n) => /\.(mp4|m4v)$/i.test(n) ? "video/mp4" : /\.mov$/i.test(n) ? "video/quicktime" : /\.webm$/i.test(n) ? "video/webm"
    : /\.wav$/i.test(n) ? "audio/wav" : /\.(mp3)$/i.test(n) ? "audio/mpeg" : /\.(m4a|aac)$/i.test(n) ? "audio/mp4"
    : /\.png$/i.test(n) ? "image/png" : /\.jpe?g$/i.test(n) ? "image/jpeg" : "";
  const base = (p) => String(p).split(/[\\/]/).pop();
  const extOf = (m) => { const n = (m.file && m.file.name) || ""; const e = n.match(/\.[a-z0-9]+$/i); return e ? e[0] : m.kind === "image" ? ".jpg" : m.kind === "audio" ? ".wav" : ".mp4"; };

  /** Fabrika çıktısını Kesim'e alır (medya kutusuna; istenirse zaman çizelgesinin sonuna). */
  async function importRel(rel, timeline = true) {
    const data = await FB.fetch(rel);
    const name = base(rel);
    const m = await addMedia(new File([data], name, { type: mimeOf(name) }));
    if (m && timeline) addToTimeline(m);
    if (typeof renderBin === "function") renderBin();
    return m;
  }

  /** Kesim'deki bir medyayı fabrikaya yükler (dosya yolu varsa akışla, yoksa veriyle). */
  async function uploadMedia(m) {
    const p = m.file && FB.pathOf(m.file);
    if (p) return FB.uploadPath(p);
    return FB.uploadBuffer(m.name + extOf(m), await m.file.arrayBuffer());
  }

  function selectedClip() {
    const c = typeof findSel === "function" ? findSel() : null;
    if (!c || !sel || sel.k !== "clip") throw new Error("Önce zaman çizelgesinde bir klip seç.");
    return { c, m: media.get(c.mid) };
  }

  function jobCard(title) {
    const msg = h("div", { class: "note" }, "sırada…");
    const acts = h("div", { class: "fb-row" });
    const fill = h("div", { class: "fb-fill" }), pctEl = h("span", { class: "fb-pct" }, "");
    const bar = h("div", { class: "fb-bar" }, fill);
    const steps = h("div", { class: "fb-steps" });
    const card = h("div", { class: "fb-job" }, h("div", { class: "fb-row", style: "justify-content:space-between;margin:0" }, h("b", {}, title), pctEl), bar, msg, steps, acts);
    jobsBox.prepend(card);
    while (jobsBox.children.length > 8) jobsBox.lastChild.remove();
    return {
      say: (t, cls) => {
        msg.textContent = t; msg.className = "note " + (cls || "");
        if (cls === "fb-ok") { fill.style.width = "100%"; pctEl.textContent = "%100"; card.classList.add("ok"); }
        if (cls === "fb-bad") card.classList.add("bad");
      },
      /** ilerleme: {pct, eta, steps:[{name,status}]} → çubuk + yüzde + adımlar (✓ bitti · ▶ şu an · ○ bekliyor) */
      progress: (pg) => {
        if (!pg) return;
        fill.style.width = Math.max(2, pg.pct || 0) + "%"; pctEl.textContent = "%" + (pg.pct || 0);
        steps.textContent = (pg.steps || []).map((x) => ({ done: "✓", skipped: "✓", running: "▶", failed: "✖" }[x.status] || "○") + " " + x.name).join("   ");
      },
      result: (rel) => {
        acts.append(h("button", { class: "btn", onclick: () => importRel(rel).then(() => toast("Zaman çizelgesine eklendi.")).catch((e) => toast(e.message)) }, "Kesim'e al"));
      },
    };
  }

  const run = (label, fn) => async (...a) => {
    try { await fn(...a); } catch (e) { toast(`${label}: ${e.message}`, 6000); }
  };

  /* ---------- 1) otomatik montaj ---------- */
  async function montage(names, title, preset) {
    // montaj sihirbazı (wizard.js): false = iptal, {} = sormadan, aksi hâlde kullanıcının isteği; komutla gelen
    // istek (preset: /kesim, /ref) sihirbazı atlar
    const brief = preset || (window.__kesimSihirbaz ? await window.__kesimSihirbaz(names) : {});
    if (brief === false) return toast("Montaj iptal edildi.");
    const card = jobCard(title);
    const proj = await FB.post("/api/kesim/edit", { files: names, brief });
    if (proj.error) throw new Error(proj.error);
    return trackMontage(proj.id, proj.options, card);
  }

  /** Kesim/stüdyo montajını bitene kadar izler; bitince Kesim'e alır. */
  async function trackMontage(id, options, card) {
    const notes = (options && options.brief_notes) || [];
    card.say(notes.length ? `Başladı · ${notes.join(" · ")}` : `Başladı · stil: ${options && options.style}`);
    for (;;) {
      await sleep(3000);
      const st = await FB.get("/api/kesim");
      const p = (st.projects || []).find((x) => x.id === id);
      if (!p) continue;
      if (p.status === "failed") return card.say("Hata: " + (p.error || "bilinmiyor").slice(0, 300), "fb-bad");
      card.progress(p.progress);
      if (p.status !== "done") { card.say(p.stage || "çalışıyor…"); continue; }
      const outs = (p.clips || []).filter((c) => c.output).map((c) => c.output);
      card.say(`Hazır: ${outs.length} video${(p.notes || []).length ? " · " + p.notes.slice(-1)[0].slice(0, 160) : ""}`, "fb-ok");
      for (const o of outs) { card.result(o); if (cfg.autoImport) await importRel(o).catch((e) => toast(e.message)); }
      if (cfg.autoImport && outs.length) toast("Montaj Kesim'e alındı.");
      return;
    }
  }

  const drop = h("label", { class: "fb-drop" }, h("b", {}, "Video/fotoğraf bırak → otomatik montaj"), h("br"),
    "birleştirme · boşluk kesme · 9:16 · altyazı · renk · ses · müzik");
  const fin = h("input", { type: "file", multiple: true, accept: "video/*,image/*,.heic,.heif", hidden: true });
  drop.append(fin);
  const sendFiles = run("Montaj", async (files) => {
    files = [...files]; if (!files.length) return;
    const names = [];
    for (let i = 0; i < files.length; i++) {
      status.textContent = `Fabrikaya gönderiliyor ${i + 1}/${files.length}: ${files[i].name}`;
      const p = FB.pathOf(files[i]);
      names.push(p ? await FB.uploadPath(p) : await FB.uploadBuffer(files[i].name, await files[i].arrayBuffer()));
    }
    refresh();
    await montage(names, `Montaj: ${files.length} dosya`);
  });
  fin.addEventListener("change", () => { const f = [...fin.files]; fin.value = ""; sendFiles(f); });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => sendFiles(e.dataTransfer.files));

  const fromTimeline = run("Montaj", () => montageTimeline());
  async function montageTimeline(preset) {
    const ms = []; for (const c of S.clips) { const m = media.get(c.mid); if (m && !ms.includes(m)) ms.push(m); }
    if (!ms.length) throw new Error("Zaman çizelgesi boş.");
    const names = [];
    for (const m of ms) { status.textContent = `Fabrikaya gönderiliyor: ${m.name}`; names.push(await uploadMedia(m)); }
    refresh();
    await montage(names, `Montaj: zaman çizelgesindeki ${ms.length} medya`, preset);
  }

  /* ---------- 2) şu videoyu yap ---------- */
  const topic = h("textarea", { rows: 1, placeholder: "Örn: Venüs'te bir gün neden bir yıldan uzun?  ·  / yaz → komutlar" });
  const makeVideo = run("Video yap", async (text) => {
    const q = (typeof text === "string" ? text : topic.value).trim(); if (!q) return;
    if (typeof text !== "string") { topic.value = ""; topic.dispatchEvent(new Event("input")); }
    const since = Date.now() - 5000;
    const card = jobCard("Video: " + q.slice(0, 60));
    const r = await FB.post("/api/new", { topic: q, text: q.length > 80 ? q : "", kesim: true, count: 1 });
    if (r.error) throw new Error(r.error);
    card.say("Araştırma, senaryo, ses, görsel ve müzik hazırlanıyor (birkaç dakika)…");
    return trackJob(since, card);
  });

  /** Fabrika video görevini (since sonrası açılan) bitene kadar izler; bitince Kesim'e alır. */
  async function trackJob(since, card) {
    for (;;) {
      await sleep(5000);
      const jobs = await FB.get("/api/jobs");
      const j = jobs.find((x) => Date.parse(x.created || 0) >= since);
      if (!j) continue;
      const stages = Object.entries(j.stages || {});
      const cur = stages.find(([, v]) => v !== "done");
      if (j.status === "failed") return card.say("Hata: " + Object.values(j.errors || {}).join(" ").slice(0, 300), "fb-bad");
      if (j.status === "done" && j.outputs && j.outputs.video) {
        card.say(`Hazır: ${j.title || j.id}`, "fb-ok"); card.result(j.outputs.video);
        if (cfg.autoImport) { await importRel(j.outputs.video); toast("Video Kesim'e alındı."); }
        return;
      }
      card.progress(j.progress);
      const eta = j.progress && j.progress.eta ? ` · kalan ~${Math.ceil(j.progress.eta / 60)} dk` : "";
      card.say(`${j.title || "hazırlanıyor"} · şu an: ${(j.progress && j.progress.current) || (cur ? cur[0] : "")}${eta}`);
    }
  }

  /* ---------- 2b) Fotoğraflarım: fotoğraf kutusu → video ---------- */
  const phPicked = [];                       // seçim sırası = videodaki sıra
  const phCells = new Map();
  const phGrid = h("div", { class: "fb-ph" });
  const phInfo = h("div", { class: "note" }, "Fotoğraflar yükleniyor…");
  const phIstek = h("textarea", { rows: 1, placeholder: "Ne olsun? Ör: Kapadokya gezimiz, neşeli müzik, 30 sn" });
  const phIn = h("input", { type: "file", multiple: true, accept: "image/*,.heic,.heif", hidden: true });
  const phMark = () => {
    for (const [n, c] of phCells) {
      const i = phPicked.indexOf(n);
      c.classList.toggle("on", i >= 0);
      c.lastChild.textContent = i >= 0 ? String(i + 1) : "";
    }
  };
  async function loadPhotos() {
    const r = await FB.get("/api/photos?data=1");
    if (r.error) throw new Error(r.error);
    phCells.clear();
    for (const p of r.photos.slice(0, 150)) {
      const cell = h("div", { class: "fb-ph-c", title: p.name, onclick: () => {
        const i = phPicked.indexOf(p.name);
        if (i >= 0) phPicked.splice(i, 1); else phPicked.push(p.name);
        phMark();
      } }, h("img", { src: p.thumb, alt: "", loading: "lazy" }), h("span", { class: "fb-ph-n" }));
      phCells.set(p.name, cell);
    }
    for (let i = phPicked.length - 1; i >= 0; i--) if (!phCells.has(phPicked[i])) phPicked.splice(i, 1);
    phGrid.replaceChildren(...phCells.values());
    phMark();
    phInfo.textContent = r.photos.length ? `${r.photos.length} fotoğraf · tıklayarak sırayla seç · klasör: ${r.dir}`
      : `Henüz fotoğraf yok. “Fotoğraf ekle” ile seç ya da şu klasöre at: ${r.dir}`;
  }
  const addPhotos = run("Fotoğraf", async (files) => {
    files = [...files].filter((f) => /^image\//.test(f.type) || /\.(heic|heif)$/i.test(f.name));
    if (!files.length) return;
    const names = [];
    for (let i = 0; i < files.length; i++) {
      phInfo.textContent = `Ekleniyor ${i + 1}/${files.length}: ${files[i].name}`;
      const p = FB.pathOf(files[i]);
      names.push(p ? await FB.uploadPath(p) : await FB.uploadBuffer(files[i].name, await files[i].arrayBuffer()));
    }
    const r = await FB.post("/api/photos/add", { files: names });
    await loadPhotos();
    toast(`${(r.added || []).length} fotoğraf Fotoğraflarım'a eklendi.`);
  });
  phIn.addEventListener("change", () => { const f = [...phIn.files]; phIn.value = ""; addPhotos(f); });
  ["dragenter", "dragover"].forEach((ev) => phGrid.addEventListener(ev, (e) => { e.preventDefault(); phGrid.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => phGrid.addEventListener(ev, (e) => { e.preventDefault(); phGrid.classList.remove("over"); }));
  phGrid.addEventListener("drop", (e) => addPhotos(e.dataTransfer.files));

  /** Seçili fotoğraflardan video. mode: montaj (müzikli) | anlatim (seslendirmeli, altyazılı) */
  const photoVideo = run("Fotoğraftan video", async (mode, text) => {
    if (!phPicked.length) throw new Error("Önce Fotoğraflarım'dan fotoğraf seç (tıklayarak).");
    const istek = (typeof text === "string" ? text : phIstek.value).trim();
    if (mode === "anlatim" && !istek) throw new Error("Anlatımlı video için ne anlatılacağını yaz (ör. “Kapadokya gezimiz”).");
    const since = Date.now() - 5000;
    const card = jobCard(`${mode === "anlatim" ? "Anlatımlı video" : "Fotoğraf montajı"}: ${phPicked.length} fotoğraf`);
    const r = await FB.post("/api/photos/video", { photos: phPicked.slice(), mode, istek });
    if (r.error) { card.say("Hata: " + r.error, "fb-bad"); throw new Error(r.error); }
    if (typeof text !== "string") { phIstek.value = ""; phIstek.dispatchEvent(new Event("input")); }
    if (r.mode === "montaj") return trackMontage(r.project, r.options, card);
    card.say("Senaryo, seslendirme ve altyazı hazırlanıyor; fotoğrafların sahnelerde kullanılacak…");
    return trackJob(since, card);
  });

  /* ---------- 3) seçili klip: altyazı / ses ---------- */
  const capStyle = () => cfg.caps || { color: "#ffffff", uppercase: false, y: .82, size: 5.5, outline: true, box: false, box_color: "#000000", words: 3 };
  const autoCaptions = run("Altyazı", async () => {
    const { c, m } = selectedClip();
    if (m.kind === "image") throw new Error("Fotoğrafta konuşma yok.");
    const card = jobCard("Altyazı: " + m.name);
    card.say("Konuşma yazıya dökülüyor…");
    const st = capStyle();
    const { task } = await FB.post("/api/kesim/transcribe", { file: await uploadMedia(m), words: st.words || 3 });
    const segs = await FB.wait(task);
    const sp = c.speed || 1, inS = c.in || 0, outS = c.out ?? m.duration;
    pushUndo();
    let n = 0;
    for (const s of segs) {
      if (s.end <= inS || s.start >= outS) continue;
      const a = Math.max(s.start, inS), b = Math.min(s.end, outS);
      S.texts.push({ id: uid(), text: st.uppercase ? s.text.toLocaleUpperCase("tr") : s.text, start: c.start + (a - inS) / sp,
        dur: Math.max(.3, (b - a) / sp), x: .5, y: st.y, size: st.size, color: st.color, font: "sans", bg: !!st.box, bgColor: st.box_color,
        outline: !!st.outline, glow: false, shadow: false, animIn: "fade", animOut: "fade", animDur: .15, loop: "none" });
      n++;
    }
    layoutAll(); renderAll();
    card.say(n ? `${n} altyazı eklendi (Metin parçasından düzenlenebilir).` : "Konuşma bulunamadı.", n ? "fb-ok" : "");
  });

  const cleanAudio = run("Ses", async () => {
    const { c, m } = selectedClip();
    if (m.kind === "image") throw new Error("Fotoğrafın sesi yok.");
    const card = jobCard("Ses temizleme: " + m.name);
    card.say("Uğultu, gürültü ve seviye düzeltiliyor…");
    const { task } = await FB.post("/api/kesim/enhance", { file: await uploadMedia(m), strength: "orta" });
    const r = await FB.wait(task);
    const nm = await importRel(r.output, false);
    if (!nm) throw new Error("temizlenmiş dosya açılamadı");
    pushUndo();
    for (const x of S.clips) if (x.mid === c.mid) x.mid = nm.id;   // aynı medyayı kullanan bütün klipler
    layoutAll(); renderAll();
    card.say("Ses temizlendi: " + r.steps.join(" · "), "fb-ok");
  });

  /* ---------- 4) fabrika stili ---------- */
  const styleSel = h("select", {});
  const applyFactoryStyle = run("Stil", async () => {
    if (!S.clips.length) throw new Error("Önce zaman çizelgesine klip ekle.");
    const st = await FB.get("/api/kesim/style/" + encodeURIComponent(styleSel.value || ""));
    pushUndo();
    for (const c of S.clips) c.fx = { ...c.fx, ...st.clip_fx };
    cfg.caps = st.captions; cfg.style = styleSel.value; saveCfg();
    layoutAll(); renderAll();
    toast(`“${st.name}” (v${st.version}) uygulandı: renk düzenlemesi tüm kliplere; altyazılar bu stille eklenecek.`, 6000);
  });

  /* ---------- 5) AI asistan (fabrikanın Claude bağlantısı) ---------- */
  const aiIn = h("textarea", { rows: 1, placeholder: "Örn: Sinematik yap, başa “Merhaba” yaz, klipler arasına geçiş koy." });
  const aiLog = h("div", { class: "note" });
  const blobToData = (b) => new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(b); });
  // Kesim'in araçları var olan metin/efekt/katman/müziği değiştiremiyor: doğrulamalı genel düzenleme aracı
  const NUM = { size: [2, 24], x: [0, 1], y: [0, 1], w: [0.05, 1], opacity: [0, 1], start: [0, 36000], dur: [0.2, 3600],
    i: [0, 1], sp: [0.25, 4], rot: [-180, 180], volume: [0, 2], fin: [0, 5], fout: [0, 5], animDur: [0.1, 2], border: [0, 10] };
  const COLOR = new Set(["color", "bgColor", "borderColor"]);
  const BOOL = new Set(["bg", "outline", "glow", "shadow", "flip"]);
  const CHOICE = () => ({ font: typeof FONT_NAMES === "object" ? Object.keys(FONT_NAMES) : null,
    type: typeof FXLIB === "object" ? Object.keys(FXLIB) : null, loop: typeof TLOOP === "object" ? Object.keys(TLOOP) : null,
    shape: ["rect", "round", "circle"] });
  const EDITABLE = { text: ["text", "size", "color", "font", "x", "y", "start", "dur", "bg", "bgColor", "outline", "glow", "shadow", "animIn", "animOut", "animDur", "loop"],
    fx: ["type", "start", "dur", "i", "sp"], ov: ["x", "y", "w", "opacity", "rot", "start", "shape", "border", "borderColor", "shadow", "flip", "volume"],
    audio: ["start", "volume", "fin", "fout"] };
  const editTool = (log) => ({
    name: "edit_item",
    description: "Var olan bir metni (kind=text), efekti (fx), üst katmanı (ov) veya müziği (audio) değiştirir. i: get_project'teki "
      + "indeks; all=true o türün hepsine uygular. props örn. metin için {size:14, color:\"#ff0000\", y:0.2, text:\"...\"} "
      + "(size 2-24, x/y 0-1, renkler #rrggbb), müzik için {volume:0.4, fin:1, fout:2}, efekt için {i:0.8, dur:2}.",
    inputSchema: { type: "object", properties: { kind: { type: "string", enum: Object.keys(EDITABLE) }, i: { type: "number" },
      all: { type: "boolean" }, props: { type: "object" } }, required: ["kind", "props"] },
    execute: async (a) => {
      const kind = String(a.kind || ""), arr = typeof arrOf === "function" ? arrOf(kind) : null;
      if (!EDITABLE[kind] || !arr) throw new Error("bilinmeyen tür: " + kind);
      const items = a.all ? arr.slice() : [arr[Math.trunc(Number(a.i))]].filter(Boolean);
      if (!items.length) throw new Error(`${kind} #${a.i} yok`);
      const ch = CHOICE(), done = [];
      for (const [k, v] of Object.entries(a.props || {})) {
        if (!EDITABLE[kind].includes(k)) { log(`✖ ${kind}.${k} değiştirilemez`); continue; }
        let val = v;
        if (NUM[k]) { val = Number(v); if (!Number.isFinite(val)) continue; val = Math.min(NUM[k][1], Math.max(NUM[k][0], val)); }
        else if (COLOR.has(k)) { if (!/^#[0-9a-f]{6}$/i.test(String(v))) { log(`✖ renk biçimi #rrggbb olmalı: ${v}`); continue; } }
        else if (BOOL.has(k)) val = !!v;
        else if (ch[k] && !ch[k].includes(String(v))) { log(`✖ ${k}: “${v}” yok`); continue; }
        else if (k === "text") val = String(v).slice(0, 200);
        else val = String(v);
        for (const o of items) o[k] = val;
        done.push(`${k}=${val}`);
      }
      layoutAll(); renderAll();
      if (done.length) log(`${kind} ${a.all ? "(hepsi)" : "#" + a.i}: ${done.join(", ")}`);
      return done.length ? "Tamam" : "değişiklik yok";
    },
  });
  const toolList = (log) => [...aiTools(log || (() => {})), editTool(log || (() => {}))];
  // Claude'a giden proje özeti: metin görünümü, katman ve müzik sesi de görünsün (edit_item için)
  if (typeof projectState === "function") {
    const baseState = projectState;
    projectState = function () {
      const s = baseState();
      s.metinler = S.texts.map((x, i) => ({ ...s.metinler[i], boyut: x.size, renk: x.color, y: +(+x.y).toFixed(2), yazi_tipi: x.font }));
      s.muzik = (s.muzik || []).map((m, i) => ({ ...m, ses: S.audios[i] && S.audios[i].volume }));
      s.katmanlar = S.overlays.map((o, i) => ({ i, ad: (media.get(o.mid) || {}).name, bas: +o.start.toFixed(2),
        sure: +(o.out - o.in).toFixed(2), boyut: o.w, saydamlik: o.opacity }));
      return s;
    };
  }
  const assist = run("AI", async (text) => {
    const q = (typeof text === "string" ? text : aiIn.value).trim(); if (!q) return;
    if (!total) throw new Error("Önce zaman çizelgesine klip ekle.");
    aiLog.textContent = "Claude planlıyor…";
    const frames = await Promise.all((await captureFrames(3)).map(blobToData));
    const tools = toolList();
    const { task } = await FB.post("/api/kesim/assist", { request: q, state: projectState(), rules: aiRules(),
      tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })), frames });
    const plan = await FB.wait(task);
    const lines = [];
    const live = toolList((s) => lines.push(s));
    pushUndo();
    for (const call of plan.calls || []) {
      const tool = live.find((x) => x.name === call.tool);
      if (!tool) { lines.push(`✖ bilinmeyen araç: ${call.tool}`); continue; }
      try { await tool.execute(call.args || {}); } catch (e) { lines.push(`✖ ${call.tool}: ${e.message}`); }
    }
    layoutAll(); renderAll();
    aiLog.textContent = [plan.summary, ...lines].filter(Boolean).join("\n");
    if (typeof text !== "string") { aiIn.value = ""; aiIn.dispatchEvent(new Event("input")); }
  });

  /* ---------- 6) dışa aktarma → Hazır + öğrenme ---------- */
  const origSave = window.saveBlob;
  let capture = null;   // MCP dışa aktarması sırasında kaydedilen yollar
  if (typeof origSave === "function") {
    window.saveBlob = async function (blob, name) {
      if (!cfg.saveToReady && !capture) return origSave(blob, name);
      if (!blob || !blob.size) { toast("Dışa aktarma boş çıktı; tekrar deneyin (pencere görünür olmalı).", 6000); return; }
      try {
        const r = await FB.saveExport(name, await blob.arrayBuffer(), cfg.learn);
        if (capture) capture.push(r.path);
        toast(`Kaydedildi: ${r.path}${r.learned ? " · fabrika bu videodan öğreniyor" : ""}`, 6000);
      } catch (e) { toast("Hazır klasörüne kaydedilemedi: " + e.message, 6000); if (!capture) return origSave(blob, name); }
    };
  }

  /* ---------- panel ---------- */
  const chk = (label, key) => h("label", { class: "fb-chk" },
    h("input", { type: "checkbox", ...(cfg[key] ? { checked: true } : {}), onchange: (e) => { cfg[key] = e.target.checked; saveCfg(); } }), label);
  const dot = h("span", { class: "fb-dot" });
  const assistBox = h("div");
  panel.append(
    h("h2", {}, "Reels Fabrikası"), h("div", { class: "fb-row" }, dot, status),
    h("h2", {}, "🤖 Asistan — söyle, yapsın"), assistBox,
    h("h2", {}, "Otomatik montaj"), drop,
    h("div", { class: "fb-row" }, h("button", { class: "btn", onclick: fromTimeline }, "Zaman çizelgesindekini montajla")),
    h("h2", {}, "Şu videoyu yap · komutlar"), topic, h("div", { class: "fb-row" }, h("button", { class: "btn pri", onclick: () => makeVideo() }, "Yap")),
    h("p", { class: "note" }, "Fabrika araştırır, senaryo yazar, seslendirir, görsel/video/müzik bulur; bitince Kesim'e alınır."),
    h("h2", {}, "🖼 Fotoğraflarım"), phInfo,
    h("div", { class: "fb-row" }, h("label", { class: "btn" }, "＋ Fotoğraf ekle", phIn),
      h("button", { class: "btn", onclick: run("Klasör", async () => { const r = await FB.post("/api/photos/open", {}); if (r.error) throw new Error(r.error); }) }, "Klasörü aç"),
      h("button", { class: "btn", onclick: run("Fotoğraflar", loadPhotos) }, "Yenile"),
      h("button", { class: "btn", onclick: () => { phPicked.splice(0, phPicked.length, ...phCells.keys()); phMark(); } }, "Tümü"),
      h("button", { class: "btn", onclick: () => { phPicked.length = 0; phMark(); } }, "Temizle")),
    phGrid, phIstek,
    h("div", { class: "fb-row" }, h("button", { class: "btn pri", onclick: () => photoVideo("montaj") }, "🎞 Müzikli montaj"),
      h("button", { class: "btn", onclick: () => photoVideo("anlatim") }, "🎙 Anlatımlı video")),
    h("p", { class: "note" }, "Müzikli montaj: geçişli, müzikli slayt (istek isteğe bağlı). Anlatımlı: yazdığın konuyu seslendirip altyazılar, fotoğraflarını sahnelerde kullanır. Bitince Kesim'e ve Hazır klasörüne gelir."),
    h("h2", {}, "Seçili klip"),
    h("div", { class: "fb-row" }, h("button", { class: "btn", onclick: autoCaptions }, "Otomatik altyazı"), h("button", { class: "btn", onclick: cleanAudio }, "Sesi temizle")),
    h("h2", {}, "Fabrikanın öğrendiği stil"), styleSel,
    h("div", { class: "fb-row" }, h("button", { class: "btn", onclick: applyFactoryStyle }, "Stili uygula")),
    h("h2", {}, "AI asistan"), aiIn, h("div", { class: "fb-row" }, h("button", { class: "btn pri", onclick: assist }, "Uygula")), aiLog,
    h("p", { class: "note" }, "Fabrikanın Claude bağlantısını kullanır; değişiklikler Geri al ile kaldırılır."),
    h("h2", {}, "Ayarlar"),
    chk("Dışa aktarılanları Masaüstü\\kesim\\Hazır klasörüne kaydet", "saveToReady"),
    chk("Dışa aktardığım videolardan fabrika stil öğrensin", "learn"),
    chk("Biten montaj/videoyu otomatik Kesim'e al", "autoImport"),
    h("h2", {}, "İşler"), jobsBox);
  aiLog.style.whiteSpace = "pre-line";
  // Kesim'in kendi "✦ AI" sekmesi claude.ai sayfasına bağlıdır; masaüstünde kapalıdır. Üstteki "✦ AI Asistan"
  // düğmesi ve o sekmedeki uyarı Fabrika'nın (Claude) asistanına götürsün.
  const toAssist = () => { btn.click(); aiIn.scrollIntoView({ block: "center" }); aiIn.focus(); };
  setTimeout(() => {   // Kesim AI.fn'i eşzamansız belirler
    if (typeof AI === "object" && AI.fn) return;
    const bAi = document.getElementById("bAi"), aiOff = document.getElementById("aiOff");
    if (bAi) bAi.onclick = toAssist;
    if (aiOff) {
      aiOff.textContent = "Masaüstünde AI asistanı Fabrika üzerinden (Claude) çalışır. ";
      aiOff.append(h("button", { class: "btn pri", onclick: toAssist }, "Fabrika AI asistanını aç"));
    }
  }, 1500);

  async function refresh() {
    try {
      const s = await FB.status();
      dot.classList.toggle("on", s.alive);
      status.textContent = s.alive ? `Bağlı · çıktılar: ${s.ready}` : "Fabrika kapalı — ilk işte otomatik başlatılır.";
      if (s.alive && !styleSel.options.length) {
        const st = await FB.get("/api/kesim");
        styleSel.replaceChildren(h("option", { value: "" }, `Otomatik (${st.default_style})`),
          ...(st.styles || []).map((x) => h("option", { value: x.slug }, `${x.name} (v${x.version})`)));
        styleSel.value = cfg.style || "";
      }
    } catch (e) { status.textContent = "Fabrikaya ulaşılamadı: " + e.message; }
  }
  btn.addEventListener("click", refresh);
  let phLoaded = false;
  btn.addEventListener("click", () => { if (!phLoaded) { phLoaded = true; loadPhotos().catch((e) => { phLoaded = false; phInfo.textContent = "Fotoğraflar alınamadı: " + e.message; }); } });

  /* ---------- /komutlar: Fabrika araçları tek satırdan ---------- */
  const tabOpen = (id) => { const b = tabs.querySelector(`[data-tab="${id}"]`); if (b) b.click(); return !!b; };
  const URL_RE = /https?:\/\/\S+/i;
  const COMMANDS = [
    { name: "video", args: "<konu>", needArgs: true, desc: "Fabrika konuyu araştırıp video üretir", run: (a) => { makeVideo(a); return "Video üretimi başladı (İşler bölümünden izle)."; } },
    { name: "kesim", alias: ["montaj"], args: "[istek]", desc: "Zaman çizelgesindekini montajla (ör. /kesim enerjik, lo-fi, 30 sn)",
      run: async (a) => { await montageTimeline(a ? { serbest: a } : undefined); } },
    { name: "ref", alias: ["benzet", "gibi"], args: "<bağlantı> [istek]", needArgs: true, desc: "Şunun gibi yap: bağlantıdaki videonun tarzıyla montaj",
      run: async (a) => {
        const u = (a.match(URL_RE) || [""])[0];
        if (!u) throw new Error("Instagram/TikTok/YouTube bağlantısı yaz.");
        const rest = a.replace(u, "").trim();
        await montageTimeline({ reference: { url: u }, ...(rest ? { serbest: rest } : {}) });
      } },
    { name: "foto", alias: ["fotograf"], args: "[istek]", desc: "Seçili fotoğraflardan müzikli montaj", run: (a) => { photoVideo("montaj", a); } },
    { name: "anlat", args: "<ne anlatsın>", needArgs: true, desc: "Seçili fotoğraflardan seslendirmeli, altyazılı video", run: (a) => { photoVideo("anlatim", a); } },
    { name: "fotolar", desc: "Fotoğraflarım klasörünü aç", run: async () => (await FB.post("/api/photos/open", {})).path },
    { name: "altyazi", desc: "Seçili klibe otomatik altyazı", run: () => { autoCaptions(); } },
    { name: "ses", desc: "Seçili klibin sesini temizle", run: () => { cleanAudio(); } },
    { name: "iyilestir", args: "[1080p|2k|4k]", desc: "Seçili klibi iyileştir / büyüt", run: (a) => {
      if (!window.__fbIyilestir) throw new Error("iyileştirme yüklenmedi");
      window.__fbIyilestir(a); } },
    { name: "disa", alias: ["export", "4k", "2k"], args: "[4k|2k|1080]", desc: "Dışa aktarma penceresini aç (çözünürlüğü seçer)", run: (a) => {
      openExport();
      const v = { "4k": "2160", "2k": "1440", "1080": "1080", "1080p": "1080", "720": "720" }[FabrikaKomut.norm(a) || ""];
      const res = document.getElementById("exRes"); if (v && res) res.value = v; } },
    { name: "stil", desc: "Fabrikanın öğrendiği stili tüm kliplere uygula", run: () => { applyFactoryStyle(); } },
    { name: "kutuphane", alias: ["muzik", "efekt"], args: "[arama]", desc: "Ücretsiz müzik / efekt / görsel kütüphanesi", run: (a) => {
      if (!tabOpen("lib")) throw new Error("Kütüphane sekmesi yok");
      const box = document.getElementById("tabLib"), inp = box && box.querySelector("input[type=search]");
      if (inp && a) { inp.value = a; if (inp.form) inp.form.requestSubmit(); } } },
    { name: "ai", args: "<istek>", needArgs: true, desc: "AI asistan projeyi düzenlesin (ör. /ai sinematik yap)", run: (a) => { assist(a); return "Claude planlıyor…"; } },
    { name: "kanca", args: "<ilk cümle>", needArgs: true, desc: "Açılış cümlesinin kanca puanı", run: async (a) => {
      const r = await FB.post("/api/tools/hook", { text: a }); if (r.error) throw new Error(r.error);
      return `Kanca puanı ${r.verdict}/100 (${r.band_tr}) · kalıp: ${r.formula}\nEn zayıf: ${r.weakest} → ${r.fix}`; } },
    { name: "baslik", args: "<başlık> [| kapak yazısı]", needArgs: true, desc: "Başlık + kapak yazısı denetimi", run: async (a) => {
      const [t, th] = a.split("|").map((x) => x.trim());
      const r = await FB.post("/api/tools/title", { title: t, thumb: th || null }); if (r.error) throw new Error(r.error);
      return [`“${r.title}” · ${r.chars} karakter · puan ${r.score}/100`, ...r.issues_tr.map((x) => "✖ " + x), ...r.good.map((x) => "✔ " + x)].join("\n"); } },
    { name: "yardim", alias: ["help", "komutlar"], desc: "Bütün komutlar", run: () => FabrikaKomut.help(COMMANDS) },
  ];
  komutReady.then(() => {
    if (!window.FabrikaKomut) return;
    FabrikaKomut.attach(topic, COMMANDS, { onEnter: () => makeVideo() });
    FabrikaKomut.attach(aiIn, COMMANDS, { onEnter: () => assist(), out: aiLog });
    FabrikaKomut.grow(phIstek);
    FabrikaKomut.assistant(assistBox, COMMANDS, {
      post: (p, b) => FB.post(p, b),
      upload: async (blob, name) => FB.uploadBuffer(name, await blob.arrayBuffer()),
      context: () => `zaman çizelgesinde ${S.clips.length} klip, ${S.texts.length} yazı; seçili fotoğraf: ${phPicked.length}`,
    });
  });
  setTimeout(refresh, 1500);
  setInterval(() => { if (!panel.hidden) refresh(); }, 15000);

  /* ---------- Claude / MCP kontrol kapısı ---------- */
  window.__fabrika = {
    state: () => projectState(),
    tools: () => toolList().map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
    async call({ tool, args }) {
      const lines = [], t = toolList((s) => lines.push(s)).find((x) => x.name === tool);
      if (!t) throw new Error("Bilinmeyen araç: " + tool);
      if (tool !== "get_project") pushUndo();
      const r = await t.execute(args || {});
      layoutAll(); renderAll();
      return { result: typeof r === "string" ? r : JSON.parse(JSON.stringify(r ?? "Tamam")), log: lines };
    },
    async importPath({ path, timeline }) {
      const data = await FB.readFile(path), name = base(path);
      const m = await addMedia(new File([data], name, { type: mimeOf(name) }));
      if (!m) throw new Error("dosya açılamadı: " + name);
      if (timeline) addToTimeline(m);
      if (typeof renderBin === "function") renderBin();
      return { id: m.id, name: m.name, kind: m.kind, duration: m.duration };
    },
    async exportTo({ formats, res, fps }) {
      if (!total) throw new Error("Proje boş.");
      const want = new Set(formats && formats.length ? formats : ["v"]);
      openExport();
      for (const [f, id] of [["h", "exH"], ["v", "exV"], ["sq", "exSq"], ["p45", "exP"]]) { const el = document.getElementById(id); if (el) el.checked = want.has(f); }
      if (res) document.getElementById("exRes").value = String(res);
      if (fps) document.getElementById("exFps").value = String(fps);
      capture = [];
      try {
        await runExport();
        const btns = [...document.querySelectorAll("#exModal [data-save]")];
        for (const b of btns) b.click();
        for (let i = 0; i < 600 && capture.length < btns.length; i++) await sleep(200);
        document.getElementById("exOv").hidden = true;
        if (!capture.length) throw new Error("dışa aktarma kaydedilemedi (çıktı boş ya da iptal edildi)");
        return { saved: capture.slice() };
      } finally { capture = null; }
    },
  };
})();
