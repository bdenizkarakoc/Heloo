/* Kesim: montaj sihirbazı — video bırakınca (Fabrika sekmesi) montajdan önce “nasıl bir şey istiyorsun?” sorar.
 * Hepsi isteğe bağlı: (1) şuna benzet: Instagram/TikTok/YouTube bağlantısı ya da referans video,
 * (2) kendi cümlelerinle anlat, (3) hazır seçenekler (tarz, süre, altyazı, müzik, geçiş sesi, renk, tempo).
 * Cevaplar Fabrikaya gider (reels.brief): stil ayarlarına çevrilir; müzik internetten (Openverse) aranır, geçiş sesi
 * kütüphaneden bulunur, serbest metni Claude yorumlar. “Sormadan yap” eski otomatik davranıştır.
 * window.__kesimSihirbaz(names) → false (iptal) | {} (otomatik) | cevaplar. Dinamik metin yalnızca textContent ile. */
(function () {
  "use strict";
  const FB = window.fabrika;
  if (!FB) return;

  const h = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
    return e;
  };
  const KEY = "kesim.sihirbaz";
  const cfg = Object.assign({ ask: true, last: {} }, (() => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } })());
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch { /* özel pencere */ } };

  const css = document.createElement("style");
  css.textContent = `
  .wz-ov{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px}
  .wz{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);width:min(760px,100%);max-height:92vh;overflow:auto;padding:18px 20px}
  .wz h3{margin:0 0 4px;font-size:18px} .wz .note{margin:2px 0 10px}
  .wz-sec{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:10px;background:var(--panel2)}
  .wz-sec h4{margin:0 0 6px;font-size:14px}
  .wz input[type=url],.wz textarea{width:100%;box-sizing:border-box;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}
  .wz textarea{min-height:56px;resize:none;overflow-y:hidden;white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh}
  .wz textarea.wz-url{min-height:0}
  .wz-q{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 10px;align-items:start;margin:6px 0}
  .wz-q>span{font-size:12px;color:var(--mute);padding-top:5px}
  .wz-chips{display:flex;flex-wrap:wrap;gap:5px}
  .wz-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px}
  .wz-foot{display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap;margin-top:14px}
  .wz-foot label{margin-right:auto;font-size:12px;color:var(--mute);display:flex;gap:6px;align-items:center}
  @media (max-width:560px){.wz-q{grid-template-columns:1fr}}`;
  document.head.append(css);

  // yazdıkça aşağı doğru uzayan kutu (uzun bağlantı/metin yana kaymaz)
  const grow = (el) => {
    const fit = () => { el.style.height = "auto"; el.style.height = (el.scrollHeight + 2) + "px"; };
    el.addEventListener("input", fit); setTimeout(fit, 0);
    return el;
  };
  const URL_RE = /https?:\/\/\S+/i;

  let questions = null;
  async function loadQuestions() {
    if (questions) return questions;
    try { questions = (await FB.get("/api/kesim/brief")).questions || []; } catch { questions = []; }
    return questions;
  }

  async function ask(names) {
    if (!cfg.ask) return {};
    const qs = await loadQuestions();
    return new Promise((resolve) => {
      const ans = { ...(cfg.last || {}) };
      delete ans.reference; delete ans.serbest;
      let refFile = null;
      const url = grow(h("textarea", { class: "wz-url", rows: 1, placeholder: "Instagram / TikTok / YouTube bağlantısı (isteğe bağlı)" }));
      url.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
      const refName = h("span", { class: "note" }, "");
      // birebir (kesim zamanları, geçişler, hareketler, yazılar aynı) ya da yalnızca tarz; yazıların ne olacağı
      const pick = (opts, val, onch) => {
        const box = h("div", { class: "wz-chips" });
        const draw = () => box.replaceChildren(...opts.map(([v, n]) => h("button", { class: "chip" + (val === v ? " on" : ""), type: "button",
          onclick: () => { val = v; onch(v); draw(); } }, n)));
        draw(); return box;
      };
      let refMode = cfg.refMode || "birebir", textMode = cfg.textMode || "uyarla";
      const modeBox = pick([["birebir", "Birebir aynısı (kesimler, geçişler, yazılar)"], ["tarz", "Yalnızca tarzı (renk, altyazı, tempo)"]],
        refMode, (v) => { refMode = v; textRow.style.display = v === "birebir" ? "" : "none"; });
      const textRow = h("div", { class: "wz-row" }, h("span", { class: "note" }, "Ekrandaki yazılar:"),
        pick([["aynen", "Aynen kopyala"], ["uyarla", "Benim konuma uyarla"], ["yok", "Olmasın"]], textMode, (v) => { textMode = v; }));
      const refIn = h("input", { type: "file", accept: "video/*", hidden: true });
      refIn.onchange = () => { refFile = refIn.files[0] || null; refName.textContent = refFile ? "Referans: " + refFile.name : ""; };
      const free = grow(h("textarea", { placeholder: "Kendi cümlelerinle anlat (ör. enerjik olsun, lo-fi müzik, geçişlerde vınlama, 30 saniye)" }));
      const rows = qs.map((q) => {
        const box = h("div", { class: "wz-chips" });
        const draw = () => box.replaceChildren(...q.choices.map((c) => h("button", {
          class: "chip" + (ans[q.key] === c.value ? " on" : ""), type: "button",
          onclick: () => { ans[q.key] = ans[q.key] === c.value ? undefined : c.value; draw(); },
        }, c.label)));
        draw();
        return h("div", { class: "wz-q" }, h("span", {}, q.label), box);
      });
      const noAsk = h("input", { type: "checkbox" });
      const close = (val) => { ov.remove(); removeEventListener("keydown", onKey, true); resolve(val); };
      const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(false); } };
      const finish = async () => {
        const out = {};
        for (const [k, v] of Object.entries(ans)) if (v) out[k] = v;
        // bağlantı kutusuna bağlantıyla birlikte yazılan sözler de isteğe eklenir
        const link = (url.value.match(URL_RE) || [""])[0], extra = url.value.replace(link, "").trim();
        const txt = [free.value.trim(), extra].filter(Boolean).join(". ");
        if (txt) out.serbest = txt;
        if (link) out.reference = { url: link };
        if (refFile) {
          go.disabled = true; go.textContent = "Referans gönderiliyor…";
          try {
            const p = FB.pathOf && FB.pathOf(refFile);
            out.reference = { file: p ? await FB.uploadPath(p) : await FB.uploadBuffer(refFile.name, await refFile.arrayBuffer()) };
          } catch (e) { toast("Referans video gönderilemedi: " + e.message); }
        }
        if (out.reference) Object.assign(out.reference, { mode: refMode, text_mode: textMode });
        cfg.refMode = refMode; cfg.textMode = textMode;
        cfg.last = Object.fromEntries(Object.entries(out).filter(([k]) => k !== "reference" && k !== "serbest"));
        if (noAsk.checked) cfg.ask = false;
        save();
        close(out);
      };
      const go = h("button", { class: "btn pri", type: "button", onclick: finish }, "Bu isteğe göre yap");
      const ov = h("div", { class: "wz-ov", onclick: (e) => { if (e.target === ov) close(false); } },
        h("div", { class: "wz", role: "dialog", "aria-label": "Montaj sihirbazı" },
          h("h3", {}, "Nasıl bir video istiyorsun?"),
          h("p", { class: "note" }, `${names.length} dosya montaja hazır. Hepsi isteğe bağlı; boş bıraktığını Fabrika kendisi seçer.`),
          h("div", { class: "wz-sec" }, h("h4", {}, "🔗 Şuna benzet"), url,
            h("div", { class: "wz-row" }, h("label", { class: "btn" }, "veya referans video seç", refIn), refName),
            modeBox, textRow,
            h("p", { class: "note", style: "margin:6px 0 0" }, "Birebir: referansın her kesimi aynı saniyede, aynı geçiş, kamera hareketi ve yazı konumlarıyla senin görsellerine uygulanır; müzik aynı tempoda lisanslı bir parça olur. Referansın kendi görüntüsü ve müziği kullanılmaz. Gizli hesaplardaki bağlantılar indirilemez.")),
          h("div", { class: "wz-sec" }, h("h4", {}, "💬 Kendi cümlelerinle anlat"), free,
            h("p", { class: "note", style: "margin:6px 0 0" }, "Claude okur; müzik ve efekt için uygun aramaları kendisi yapar.")),
          h("div", { class: "wz-sec" }, h("h4", {}, "🎛 Seçerek anlat"), rows),
          h("div", { class: "wz-foot" },
            h("label", {}, noAsk, "Bir daha sorma (Fabrika sekmesinden açılır)"),
            h("button", { class: "btn", type: "button", onclick: () => close(false) }, "İptal"),
            h("button", { class: "btn", type: "button", onclick: () => { if (noAsk.checked) { cfg.ask = false; save(); } close({}); } }, "Sormadan yap"),
            go)));
      document.body.append(ov);
      addEventListener("keydown", onKey, true);
      setTimeout(() => url.focus(), 50);
    });
  }
  window.__kesimSihirbaz = ask;

  /* Fabrika sekmesine aç/kapa düğmesi */
  function mount() {
    const panel = document.getElementById("tabFab");
    if (!panel) return false;
    const c = h("input", { type: "checkbox" });
    c.checked = !!cfg.ask; c.onchange = () => { cfg.ask = c.checked; save(); };
    const drop = panel.querySelector(".fb-drop");
    const row = h("label", { class: "fb-chk" }, c, "Montajdan önce ne istediğimi sor (bağlantı, tarz, müzik…)");
    if (drop) drop.after(row); else panel.append(row);
    return true;
  }
  if (!mount()) { let n = 0; const iv = setInterval(() => { if (mount() || ++n > 40) clearInterval(iv); }, 250); }
})();
