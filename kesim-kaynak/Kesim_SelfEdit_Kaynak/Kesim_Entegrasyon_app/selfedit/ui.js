/* Kesim SelfEdit: sayfa tarafı. "Gelişim" sekmesini kurar, motorun eklediği efektleri FXLIB'e kaydeder,
 * kullanım olaylarını (yalnızca yerel motora) bildirir. Dinamik metinler her zaman textContent ile yazılır. */
(function () {
  "use strict";
  const GROUP = "✦ Yeni eklenenler";
  if (typeof TABN === "object") TABN.evo = "Evo";   // Kesim'in sekme geçiş tablosuna yeni sekmeyi tanıt
  const panel = document.getElementById("tabEvo");
  if (!panel) return;

  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return e;
  };

  const SE = window.selfedit;
  if (!SE || typeof FXLIB === "undefined" || !window.SERuntime || !window.SECheck) {
    panel.append(h("h2", {}, "Kendini geliştirme"), h("p", { class: "note" }, "Bu özellik yalnızca Kesim masaüstü uygulamasında çalışır."));
    return;
  }

  const css = document.createElement("style");
  css.textContent = `
  .se-card{border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--panel2);display:flex;flex-direction:column;gap:6px}
  .se-card canvas{width:100%;aspect-ratio:16/9;border-radius:6px;background:#000;display:block}
  .se-card .ttl{font-weight:600}
  .se-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .se-chk{font-size:12px;color:var(--mute);line-height:1.5}
  .se-chk b.ok{color:var(--ok)} .se-chk b.no{color:var(--danger)}
  .se-badge{font-size:11px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute)}
  .se-badge.on{color:var(--ok);border-color:var(--ok)} .se-badge.bad{color:var(--danger);border-color:var(--danger)}
  #tabEvo textarea,#tabEvo input[type=password],#tabEvo select{width:100%;background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px;font:inherit}
  #tabEvo textarea{min-height:64px;resize:vertical}
  .se-dot{color:var(--accent)}`;
  document.head.append(css);

  const env = SERuntime.makeEnv((w, ht) => { const c = document.createElement("canvas"); c.width = w; c.height = ht; return c; });
  const tabBtn = document.querySelector('#leftTabs [data-tab="evo"]');
  let state = null, firstLoad = true;
  const seenProposals = new Set(), installed = new Map();   // FXLIB anahtarı -> tarif

  /* ---------- efektleri FXLIB'e kaydet ---------- */
  function syncPlugins(list) {
    const want = new Map(list.map((p) => ["se_" + p.recipe.id, p.recipe]));
    let changed = false;
    for (const [key, r] of want) {
      if (installed.has(key)) continue;
      FXLIB[key] = { n: r.name, g: GROUP, di: r.di, _se: r.id, _grp: r.group, f: (c, W, H, o) => SERuntime.run(r, c, W, H, o, env) };
      installed.set(key, r); changed = true;
      if (!firstLoad) toast(`Yeni efekt eklendi: ${r.name}. Efekt sekmesinde "${GROUP}" altında.`, 6000);
    }
    for (const key of [...installed.keys()]) if (!want.has(key)) { delete FXLIB[key]; installed.delete(key); changed = true; }
    if (changed) { fxSig = ""; const fx = document.getElementById("tabFx"); if (fx && !fx.hidden) renderFxLib(); }
  }

  /* ---------- önizleme ---------- */
  function preview(recipe) {
    const cv = h("canvas", { width: 160, height: 90 });
    try {
      const base = SECheck.scene((w, ht) => { const c = document.createElement("canvas"); c.width = w; c.height = ht; return c; }, 160, 90);
      const g = cv.getContext("2d"); g.drawImage(base, 0, 0);
      SERuntime.run(recipe, g, 160, 90, { lt: 0.35, p: 0.35, i: recipe.di, sp: 1, tt: 0.35 }, env);
    } catch { /* önizleme çizilemezse boş kalır */ }
    return cv;
  }

  /* ---------- sabit denetimler (bir kez kurulur) ---------- */
  const statusBox = h("div", { class: "se-card" });
  const runBtn = h("button", { class: "btn pri", onclick: async () => {
    runBtn.disabled = true; runBtn.textContent = "Çalışıyor…";
    const r = await SE.runCycle(false);
    const d = r.ok === false ? { result: "error", reason: r.error } : (r.data || r);
    toast(describe(d), 6000); await refresh();
  } }, "Şimdi geliştirme turu çalıştır");

  const modeSel = h("select", { "aria-label": "Mod", onchange: () => SE.config("mode", modeSel.value) },
    h("option", { value: "approve" }, "Onay iste (önerilen)"), h("option", { value: "auto" }, "Doğrulananı otomatik ekle"));
  const intSel = h("select", { "aria-label": "Tur aralığı", onchange: () => SE.config("interval_minutes", +intSel.value) });
  for (const [m, t] of [[15, "15 dakikada bir"], [30, "30 dakikada bir"], [60, "Saatte bir"], [180, "3 saatte bir"], [720, "12 saatte bir"]]) intSel.append(h("option", { value: m }, t));
  const bgChk = h("input", { type: "checkbox", id: "seBg", onchange: async () => { const r = await SE.config("background", bgChk.checked); if (r.ok === false) toast(r.error); } });

  const wishIn = h("textarea", { placeholder: "Örn: Korku filmi gibi karanlık kırmızı bir efekt istiyorum. / Matrix yeşili efekti." });
  const wishBtn = h("button", { class: "btn", onclick: async () => {
    const r = await SE.wish(wishIn.value);
    if (r.ok === false) return toast(r.error);
    wishIn.value = ""; toast("Dileğin kaydedildi; sonraki turda dikkate alınacak.");
  } }, "Dileği kaydet");

  const keyIn = h("input", { type: "password", autocomplete: "off", spellcheck: "false", placeholder: "sk-ant-…" });
  const keyState = h("span", { class: "se-badge" });
  const keySave = h("button", { class: "btn", onclick: async () => {
    const r = await SE.setKey(keyIn.value); keyIn.value = "";
    toast(r.ok === false ? r.error : "Anahtar bu bilgisayarda şifreli olarak kaydedildi."); refresh();
  } }, "Kaydet");
  const keyDel = h("button", { class: "btn", onclick: async () => { await SE.clearKey(); toast("Anahtar silindi."); refresh(); } }, "Sil");

  const propBox = h("div", { class: "se-list", style: "display:flex;flex-direction:column;gap:10px" });
  const plugBox = h("div", { style: "display:flex;flex-direction:column;gap:6px" });

  panel.append(
    h("h2", {}, "Kendini geliştirme"),
    h("p", { class: "note" }, "Kesim arka planda kullanımını izler, yeni efekt tarifleri önerir, gerçek bir deneme çizimiyle sınar ve sonuç sağlamsa efekt listene ekler. Yapay zekâ kod yazmaz; yalnızca sınırlı bir efekt tarifi üretir. Her ekleme geri alınabilir."),
    statusBox, runBtn,
    h("h2", {}, "Ayarlar"),
    h("label", { class: "note" }, "Mod", modeSel), h("label", { class: "note" }, "Sıklık", intSel),
    h("label", { class: "se-chk", for: "seBg" }, bgChk, " Pencereyi kapatınca arka planda çalışmaya devam et (tepsi simgesi) ve Windows ile başlat. Tamamen kapatmak için tepsi simgesinden “Çıkış”."),
    h("h2", {}, "Dilek"), wishIn, wishBtn,
    h("h2", {}, "Öneriler"), propBox,
    h("h2", {}, "Eklenen efektler"), plugBox,
    h("h2", {}, "Claude ile öneri (isteğe bağlı)"),
    h("p", { class: "note" }, "Anthropic API anahtarı girersen öneriler şablon yerine Claude'dan gelir. Anahtar bu bilgisayarda şifreli saklanır. Claude'a yalnızca efekt adları, kullanım sayıları ve dileklerin gider; videon, görüntülerin ve dosya adların asla gönderilmez."),
    keyIn, h("div", { class: "se-row" }, keySave, keyDel, keyState)
  );

  /* ---------- çizim ---------- */
  const ago = (ts) => { const m = Math.round((Date.now() - ts) / 60000); return m < 1 ? "az önce" : m < 60 ? `${m} dk önce` : `${Math.round(m / 60)} sa önce`; };
  const inn = (ts) => { const m = Math.max(0, Math.round((ts - Date.now()) / 60000)); return m < 1 ? "1 dakikadan az" : m < 60 ? `${m} dk` : `${Math.round(m / 60)} sa`; };
  function describe(r) {
    if (!r) return "Henüz tur çalışmadı.";
    const n = r.note ? ` ${r.note}` : "";
    switch (r.result) {
      case "validated": return `Yeni öneri hazır: ${r.effect}. Onayını bekliyor.${n}`;
      case "applied": return `Yeni efekt eklendi: ${r.effect}.${n}`;
      case "failed": return `Öneri (${r.effect || "?"}) doğrulamayı geçemedi, uygulanmadı.${n}`;
      case "skipped": return `Tur atlandı: ${r.reason}.`;
      case "nothing": return `Yeni öneri kalmadı. Dilek bırakabilir veya Claude anahtarı ekleyebilirsin.`;
      case "busy": return "Bir tur zaten çalışıyor.";
      default: return `Tur tamamlanamadı: ${r.reason || r.result}`;
    }
  }

  function renderStatus() {
    const { status, config, summary } = state;
    statusBox.replaceChildren(
      h("div", { class: "se-row" }, h("span", { class: "se-badge " + (status.scheduler ? "on" : "") }, status.scheduler ? "Otomatik tur açık" : "Otomatik tur kapalı"),
        status.running ? h("span", { class: "se-badge on" }, "şu an çalışıyor") : null),
      h("div", { class: "note" }, status.nextRun && status.scheduler ? `Sonraki tur: ~${inn(status.nextRun)} sonra` : ""),
      h("div", { class: "note" }, status.lastRun ? `Son tur (${ago(status.lastRun)}): ${describe(status.lastResult)}` : "Henüz tur çalışmadı."),
      h("div", { class: "note" }, `Kullanım kaydı: ${Object.values(summary.effects_used).reduce((a, b) => a + b, 0)} efekt eklemesi, ${summary.exports_ok} dışa aktarma (yalnızca bu bilgisayarda).`)
    );
    runBtn.disabled = status.running; runBtn.textContent = status.running ? "Çalışıyor…" : "Şimdi geliştirme turu çalıştır";
    modeSel.value = config.mode; bgChk.checked = !!config.background;
    if (![...intSel.options].some((o) => +o.value === config.interval_minutes)) intSel.append(h("option", { value: config.interval_minutes }, `${config.interval_minutes} dakikada bir`));
    intSel.value = String(config.interval_minutes);
    keyState.textContent = state.hasKey ? "Claude anahtarı kayıtlı ✓" : "Anahtar yok (şablonlar kullanılıyor)";
    keyState.className = "se-badge " + (state.hasKey ? "on" : "");
    keyDel.hidden = !state.hasKey;
  }

  const LABEL = { validated: "onay bekliyor", applied: "eklendi", failed: "doğrulanamadı", rejected: "reddedildi", rolled_back: "geri alındı" };
  function renderProposals() {
    const list = state.proposals.slice(0, 8);
    if (!list.length) { propBox.replaceChildren(h("p", { class: "note" }, "Henüz öneri yok. “Şimdi geliştirme turu çalıştır” ile ilkini oluşturabilirsin.")); return; }
    propBox.replaceChildren(...list.map((p) => {
      const act = [];
      const run = async (fn, okMsg) => { const r = await fn(p.id); toast(r.ok === false ? (r.error || r.detail || "Başarısız") : (r.detail || okMsg), 4500); refresh(); };
      if (p.status === "validated") act.push(h("button", { class: "btn pri", onclick: () => run(SE.apply, "Eklendi.") }, "Onayla ve ekle"), h("button", { class: "btn", onclick: () => run(SE.reject, "Reddedildi.") }, "Reddet"));
      if (p.status === "applied") act.push(h("button", { class: "btn", onclick: () => run(SE.rollback, "Geri alındı.") }, "Geri al"));
      const steps = ((p.validation && p.validation.steps) || []).map((s) => h("div", {}, h("b", { class: s.ok ? "ok" : "no" }, s.ok ? "✓ " : "✗ "), `${s.step}: ${s.detail}`));
      return h("div", { class: "se-card" },
        p.recipe && p.status !== "failed" ? preview(p.recipe) : null,
        h("div", { class: "se-row" }, h("span", { class: "ttl" }, p.title), h("span", { class: "se-badge " + (p.status === "applied" ? "on" : p.status === "failed" ? "bad" : "") }, LABEL[p.status] || p.status), h("span", { class: "se-badge" }, p.source)),
        h("div", { class: "note" }, p.rationale), h("div", { class: "se-chk" }, steps), act.length ? h("div", { class: "se-row" }, act) : null);
    }));
  }

  function renderPlugins() {
    if (!state.plugins.length) { plugBox.replaceChildren(h("p", { class: "note" }, "Henüz kendi eklenen efekt yok.")); return; }
    plugBox.replaceChildren(...state.plugins.map((p) => h("div", { class: "se-row" }, h("span", {}, p.recipe.name),
      h("button", { class: "btn", onclick: async () => { const r = await SE.rollback(p.proposal); toast(r.ok === false ? (r.error || r.detail) : r.detail); refresh(); } }, "Kaldır"))));
  }

  async function refresh() {
    const r = await SE.state();
    if (r.ok === false || !r.data) return;
    state = r.data;
    syncPlugins(state.plugins);
    const pending = state.proposals.filter((p) => p.status === "validated");
    for (const p of pending) { if (!firstLoad && !seenProposals.has(p.id)) toast(`Yeni efekt önerisi: ${p.recipe.name}. Gelişim sekmesinden onaylayabilirsin.`, 6000); }
    state.proposals.forEach((p) => seenProposals.add(p.id));
    if (tabBtn) tabBtn.textContent = pending.length ? `⟳ Gelişim ●` : "⟳ Gelişim";
    renderStatus(); renderProposals(); renderPlugins();
    firstLoad = false;
  }

  /* ---------- kullanım olayları ---------- */
  document.getElementById("fxList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fx]"); if (!b) return;
    const d = FXLIB[b.dataset.fx]; if (d) SE.log("effect_used", { type: b.dataset.fx, group: d._se ? d._grp : d.g });
  }, true);
  const exModal = document.getElementById("exModal");
  if (exModal) {
    let logged = false;
    new MutationObserver(() => {
      const t = document.getElementById("exTitle");
      if (t && t.textContent === "Hazır") { if (!logged) { logged = true; SE.log("export_ok", { fx: [...new Set(S.fxs.map((f) => f.type))] }); } }
      else logged = false;
    }).observe(exModal, { childList: true, subtree: true, characterData: true });
  }

  /* ---------- başlat ---------- */
  (async () => {
    await SE.builtins(Object.entries(FXLIB).filter(([, d]) => !d._se).map(([id, d]) => ({ id, name: d.n })));
    await refresh();
    SE.onChange(refresh);
    setInterval(() => { if (state && !document.getElementById("tabEvo").hidden) renderStatus(); }, 30000);
  })();
})();
