/* Kesim ⇄ Reels Fabrikası: sayfa tarafı. "🏭 Fabrika" sekmesini kurar.
 * - Otomatik montaj (bırak ya da zaman çizelgesindekiyle), "şu videoyu yap", seçili klibe altyazı / ses temizleme
 * - Fabrikanın öğrendiği stili uygulama, fabrikanın Claude bağlantısıyla AI asistanı
 * - Dışa aktarılanları Masaüstü\kesim\Hazır'a kaydetme ve fabrikaya öğretme
 * - window.__fabrika: Claude/MCP kontrol kapısının çağırdığı işlevler (durum, araçlar, içe/dışa aktarma)
 * Dinamik metinler her zaman textContent ile yazılır. */
(function () {
  "use strict";
  const FB = window.fabrika;
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
  #tabFab textarea{min-height:58px;resize:vertical}
  .fb-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:6px}
  .fb-drop{border:2px dashed var(--line);border-radius:10px;padding:14px;text-align:center;color:var(--mute);cursor:pointer}
  .fb-drop.over,.fb-drop:hover{border-color:var(--accent);color:var(--fg)}
  .fb-job{border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:6px;background:var(--panel2);font-size:12px}
  .fb-job b{font-size:13px} .fb-ok{color:var(--ok)} .fb-bad{color:var(--danger)}
  .fb-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--danger);margin-right:6px}
  .fb-dot.on{background:var(--ok)} .fb-chk{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--mute);margin-top:4px}`;
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
    const card = h("div", { class: "fb-job" }, h("b", {}, title), msg, acts);
    jobsBox.prepend(card);
    while (jobsBox.children.length > 8) jobsBox.lastChild.remove();
    return {
      say: (t, cls) => { msg.textContent = t; msg.className = "note " + (cls || ""); },
      result: (rel) => {
        acts.append(h("button", { class: "btn", onclick: () => importRel(rel).then(() => toast("Zaman çizelgesine eklendi.")).catch((e) => toast(e.message)) }, "Kesim'e al"));
      },
    };
  }

  const run = (label, fn) => async (...a) => {
    try { await fn(...a); } catch (e) { toast(`${label}: ${e.message}`, 6000); }
  };

  /* ---------- 1) otomatik montaj ---------- */
  async function montage(names, title) {
    const card = jobCard(title);
    const proj = await FB.post("/api/kesim/edit", { files: names });
    card.say(`Başladı · stil: ${proj.options && proj.options.style}`);
    for (;;) {
      await sleep(3000);
      const st = await FB.get("/api/kesim");
      const p = (st.projects || []).find((x) => x.id === proj.id);
      if (!p) continue;
      if (p.status === "failed") return card.say("Hata: " + (p.error || "bilinmiyor").slice(0, 300), "fb-bad");
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

  const fromTimeline = run("Montaj", async () => {
    const ms = []; for (const c of S.clips) { const m = media.get(c.mid); if (m && !ms.includes(m)) ms.push(m); }
    if (!ms.length) throw new Error("Zaman çizelgesi boş.");
    const names = [];
    for (const m of ms) { status.textContent = `Fabrikaya gönderiliyor: ${m.name}`; names.push(await uploadMedia(m)); }
    refresh();
    await montage(names, `Montaj: zaman çizelgesindeki ${ms.length} medya`);
  });

  /* ---------- 2) şu videoyu yap ---------- */
  const topic = h("input", { type: "text", placeholder: "Örn: Venüs'te bir gün neden bir yıldan uzun?" });
  const makeVideo = run("Video yap", async () => {
    const q = topic.value.trim(); if (!q) return;
    topic.value = "";
    const since = Date.now() - 5000;
    const card = jobCard("Video: " + q.slice(0, 60));
    await FB.post("/api/new", { topic: q, text: q.length > 80 ? q : "", kesim: true, count: 1 });
    card.say("Araştırma, senaryo, ses, görsel ve müzik hazırlanıyor (birkaç dakika)…");
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
      card.say(`${j.title || "hazırlanıyor"} · ${cur ? cur[0] : ""} (${stages.filter(([, v]) => v === "done").length}/${stages.length})`);
    }
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
  const aiIn = h("textarea", { placeholder: "Örn: Sinematik yap, başa “Merhaba” yaz, klipler arasına geçiş koy." });
  const aiLog = h("div", { class: "note" });
  const blobToData = (b) => new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(b); });
  const toolList = (log) => aiTools(log || (() => {}));
  const assist = run("AI", async () => {
    const q = aiIn.value.trim(); if (!q) return;
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
    aiIn.value = "";
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
  panel.append(
    h("h2", {}, "Reels Fabrikası"), h("div", { class: "fb-row" }, dot, status),
    h("h2", {}, "Otomatik montaj"), drop,
    h("div", { class: "fb-row" }, h("button", { class: "btn", onclick: fromTimeline }, "Zaman çizelgesindekini montajla")),
    h("h2", {}, "Şu videoyu yap"), topic, h("div", { class: "fb-row" }, h("button", { class: "btn pri", onclick: makeVideo }, "Yap")),
    h("p", { class: "note" }, "Fabrika araştırır, senaryo yazar, seslendirir, görsel/video/müzik bulur; bitince Kesim'e alınır."),
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
