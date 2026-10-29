/* Kesim: 4K / 2K / 1080p dışa aktarma ve Fabrika ile video iyileştirme.
 * - Dışa aktar penceresine 4K (2160p) ve 2K (1440p) eklenir.
 * - "Kaydettikten sonra iyileştir": tarayıcı kaydı (ör. 1080p) Fabrikaya gider; gürültü azaltma, lanczos büyütme
 *   (2K/4K), CAS keskinleştirme, renk ve isteğe bağlı ses temizleme; NVIDIA kart varsa donanımla kodlanır.
 *   Sonuç Masaüstü\kesim\Hazır'a konur. 4K'yı doğrudan kaydetmekten daha akıcıdır.
 * - Fabrika sekmesinde "Seçili klibi iyileştir": klibin kaynağı iyileştirilip zaman çizelgesinde değiştirilir.
 * Dinamik metinler yalnızca textContent ile yazılır. */
(function () {
  "use strict";
  const FB = window.fabrika;
  if (!FB || typeof openExport !== "function" || typeof runExport !== "function") return;

  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return e;
  };
  const KEY = "kesim.kalite";
  const cfg = Object.assign({ after: "kapali", audio: false, target: "orijinal", denoise: "hafif", sharpen: "orta" },
    (() => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } })());
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch { /* özel pencere */ } };
  const TARGETS = [["orijinal", "Aynı boyut"], ["1080p", "1080p"], ["2k", "2K (1440p)"], ["4k", "4K (2160p)"]];
  const select = (opts, val, onch) => {
    const s = h("select", {}, ...opts.map(([v, n]) => h("option", { value: v }, n)));
    s.value = val; s.onchange = () => onch(s.value);
    return s;
  };

  async function enhanceFile(file, opts) {
    const { task } = await FB.post("/api/kesim/video-enhance", { file, ...opts });
    return FB.wait(task);
  }

  /* ---------- dışa aktarma penceresi ---------- */
  const _open = openExport;
  openExport = function () {
    _open.apply(this, arguments);
    const res = document.getElementById("exRes");
    if (!res || res.querySelector('option[value="2160"]')) return;
    res.prepend(h("option", { value: "1440" }, "2K (1440p)"));
    res.prepend(h("option", { value: "2160" }, "4K (2160p, güçlü bilgisayar)"));
    res.value = "1080";
    const after = select([["kapali", "Kapalı"], ["1080p", "İyileştir (aynı boyut 1080p)"], ["2k", "İyileştir + 2K'ya büyüt"],
      ["4k", "İyileştir + 4K'ya büyüt (önerilen)"]], cfg.after, (v) => { cfg.after = v; save(); });
    const aud = h("input", { type: "checkbox" });
    aud.checked = !!cfg.audio; aud.onchange = () => { cfg.audio = aud.checked; save(); };
    const box = h("div", { class: "grp" },
      h("label", { class: "lbl" }, "Kaydettikten sonra Fabrika ile", after),
      h("label", { class: "fld chk" }, aud, h("span", {}, "Sesi de temizle")),
      h("p", { class: "note", style: "margin:0" },
        "4K için önerilen: 1080p kaydet, Fabrika gürültüyü azaltıp keskinleştirerek büyütsün (NVIDIA kartla birkaç saniye). Sonuç Hazır klasörüne gelir."));
    res.closest(".two") ? res.closest(".two").after(box) : res.parentNode.after(box);
  };
  const bExport = document.getElementById("bExport");   // Kesim düğmeyi eski işleve doğrudan bağlamış
  if (bExport) bExport.onclick = () => openExport();
  if (window.__kesim) window.__kesim.openExport = openExport;

  const _run = runExport;
  runExport = async function () {
    const target = cfg.after;
    await _run.apply(this, arguments);
    const mod = document.getElementById("exModal");
    if (!mod) return;
    for (const r of mod.querySelectorAll(".res")) {
      const vid = r.querySelector("video"), saveBtn = r.querySelector("[data-save]");
      if (!vid || !saveBtn || r.querySelector(".q-enh")) continue;
      const label = target === "kapali" ? "4K'ya büyüt" : target === "4k" ? "İyileştir + 4K" : target === "2k" ? "İyileştir + 2K" : "İyileştir";
      const b = h("button", { class: "btn q-enh", title: "Fabrika ile iyileştir; sonuç Hazır klasörüne kaydedilir" }, "✨ " + label);
      const msg = h("div", { class: "note q-msg" });
      b.onclick = async () => {
        b.disabled = true;
        try {
          msg.textContent = "Fabrikaya gönderiliyor…";
          const blob = await (await fetch(vid.src)).blob();
          const base = (r.querySelector("b") || {}).textContent || "video";
          const ext = /mp4/.test(blob.type) ? ".mp4" : ".webm";
          const name = `kesim-${base.replace(/[^\wğüşöçıİĞÜŞÖÇ]+/g, "-").toLowerCase()}-${Date.now()}${ext}`;
          const file = await FB.uploadBuffer(name, await blob.arrayBuffer());
          msg.textContent = "İyileştiriliyor…";
          const rep = await enhanceFile(file, { target: target === "kapali" ? "4k" : target, denoise: "hafif", sharpen: "orta",
            audio: !!cfg.audio, ready: true });
          msg.textContent = `Hazır: ${rep.size} · ${rep.steps.join(" · ")} · ${rep.encoder} · ${rep.seconds} sn`;
          if (rep.ready && FB.show) {
            const show = h("button", { class: "btn" }, "Klasörde göster");
            show.onclick = () => FB.show(rep.ready);
            msg.after(show);
          }
        } catch (e) {
          msg.textContent = "İyileştirilemedi: " + e.message;
          b.disabled = false;
        }
      };
      saveBtn.after(b);
      r.append(msg);
      if (target !== "kapali") b.click();
    }
  };

  /* ---------- Fabrika sekmesi: seçili klibi iyileştir ---------- */
  function mount() {
    const panel = document.getElementById("tabFab");
    if (!panel) return false;
    const tgt = select(TARGETS, cfg.target, (v) => { cfg.target = v; save(); });
    const dn = select([["yok", "Gürültü azaltma yok"], ["hafif", "Gürültü: hafif"], ["orta", "Gürültü: orta"], ["güçlü", "Gürültü: güçlü"]],
      cfg.denoise, (v) => { cfg.denoise = v; save(); });
    const sh = select([["yok", "Keskinlik yok"], ["hafif", "Keskinlik: hafif"], ["orta", "Keskinlik: orta"], ["güçlü", "Keskinlik: güçlü"]],
      cfg.sharpen, (v) => { cfg.sharpen = v; save(); });
    const aud = h("input", { type: "checkbox" });
    aud.checked = !!cfg.audio; aud.onchange = () => { cfg.audio = aud.checked; save(); };
    const msg = h("div", { class: "note" });
    const go = h("button", { class: "btn pri" }, "✨ Seçili klibi iyileştir");
    go.onclick = async () => {
      const c = typeof findSel === "function" ? findSel() : null;
      if (!c || !sel || sel.k !== "clip") return toast("Önce zaman çizelgesinde bir video klibi seç.");
      const m = media.get(c.mid);
      if (!m || m.kind !== "video" || !m.file) return toast("Yalnızca video klipler iyileştirilebilir.");
      go.disabled = true;
      try {
        msg.textContent = "Fabrikaya gönderiliyor…";
        const p = FB.pathOf && FB.pathOf(m.file);
        const ext = (m.file.name.match(/\.[a-z0-9]+$/i) || [".mp4"])[0];
        const file = p ? await FB.uploadPath(p) : await FB.uploadBuffer(m.name + ext, await m.file.arrayBuffer());
        msg.textContent = "İyileştiriliyor…";
        const rep = await enhanceFile(file, { target: cfg.target, denoise: cfg.denoise, sharpen: cfg.sharpen, audio: !!cfg.audio });
        const data = await FB.fetch(rep.output);
        const name = rep.output.split("/").pop();
        const nm = await addMedia(new File([data], name, { type: "video/mp4" }));
        if (!nm) throw new Error("iyileştirilmiş dosya açılamadı");
        pushUndo();
        for (const x of S.clips) if (x.mid === c.mid) x.mid = nm.id;   // aynı kaynağı kullanan bütün klipler
        if (typeof renderBin === "function") renderBin();
        layoutAll(); renderAll();
        msg.textContent = `İyileştirildi: ${rep.size} · ${rep.steps.join(" · ")} · ${rep.seconds} sn (Ctrl+Z ile geri al)`;
      } catch (e) {
        msg.textContent = "İyileştirilemedi: " + e.message;
      } finally { go.disabled = false; }
    };
    // /iyilestir [1080p|2k|4k] komutu (ui.js)
    window.__fbIyilestir = (arg) => {
      const v = String(arg || "").toLowerCase().replace(/\s/g, "");
      const t = { "4k": "4k", "2160": "4k", "2k": "2k", "1440": "2k", "1080": "1080p", "1080p": "1080p" }[v];
      if (t) { tgt.value = t; cfg.target = t; save(); }
      go.click();
    };
    panel.append(h("h2", {}, "Video iyileştirme"),
      h("p", { class: "note" }, "Gürültüyü azaltır, keskinleştirir, rengi canlandırır; istersen 1080p / 2K / 4K'ya büyütür."),
      h("div", { class: "fb-row" }, tgt, dn, sh),
      h("label", { class: "fb-chk" }, aud, "Sesi de temizle"),
      h("div", { class: "fb-row" }, go), msg);
    return true;
  }
  if (!mount()) { let n = 0; const iv = setInterval(() => { if (mount() || ++n > 40) clearInterval(iv); }, 250); }
})();
