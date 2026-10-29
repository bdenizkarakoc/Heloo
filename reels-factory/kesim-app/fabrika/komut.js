/* /komut menüsü + aşağı doğru büyüyen metin kutusu. Kesim'de (fabrika/komut.js) ve Fabrika sayfalarında
 * (server.py → /komut.js) aynı dosya kullanılır.
 *   window.FabrikaKomut.grow(textarea)                    yazdıkça aşağı doğru uzar (yana kaymaz)
 *   window.FabrikaKomut.attach(textarea, komutlar, {onEnter, out})
 *     komutlar: [{ name: "kesim", args: "[istek]", desc: "…", run: async (argMetni) => "sonuç metni" | void }]
 *     "/" ile başlayınca eşleşen komutlar listelenir; ↑↓ seç, Tab tamamla, Enter çalıştır, Esc kapat.
 *     Komutsuz Enter → onEnter (varsa); Shift+Enter her zaman yeni satır.
 * Dinamik metin yalnızca textContent ile yazılır. */
(function () {
  "use strict";
  if (window.FabrikaKomut) return;

  const css = document.createElement("style");
  css.textContent = `
  textarea.fk-grow{resize:none;overflow-y:hidden;white-space:pre-wrap;overflow-wrap:anywhere;min-height:2.6em;max-height:45vh;line-height:1.4}
  .fk-menu{border:1px solid var(--line,#253049);border-radius:9px;margin-top:4px;background:var(--panel2,var(--card,#141b2d));max-height:260px;overflow:auto;font-size:13px}
  .fk-item{display:flex;gap:8px;align-items:baseline;padding:6px 9px;cursor:pointer}
  .fk-item b{color:var(--accent,var(--acc,#ffd23f));white-space:nowrap} .fk-item i{color:var(--mute,var(--muted,#9aa6c2));font-style:normal;white-space:nowrap}
  .fk-item span{color:var(--fg,var(--ink,#eef2fb));opacity:.85}
  .fk-item.on,.fk-item:hover{background:rgba(127,127,127,.18)}
  .fk-out{white-space:pre-line;font-size:12.5px;margin-top:6px;padding:7px 9px;border-radius:8px;border:1px solid var(--line,#253049);color:var(--fg,var(--ink,#eef2fb))}
  .fk-out.bad{color:var(--danger,var(--bad,#ff6b6b))}
  .fk-hint{font-size:11.5px;color:var(--mute,var(--muted,#9aa6c2));margin-top:3px}`;
  document.head.append(css);

  // Türkçe harfler ve büyük/küçük harf fark etmesin: /altyazı = /altyazi = /ALTYAZI
  const norm = (s) => String(s || "").toLocaleLowerCase("tr").replace(/[çğıöşü]/g, (c) => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u" }[c]));

  function grow(el) {
    if (!el || el.dataset.fkGrow) return el;
    el.dataset.fkGrow = "1";
    el.classList.add("fk-grow");
    if (!el.getAttribute("rows")) el.setAttribute("rows", "1");
    const fit = () => { el.style.height = "auto"; el.style.height = (el.scrollHeight + 2) + "px"; };
    el.addEventListener("input", fit);
    el.__fkFit = fit;
    requestAnimationFrame(fit);
    return el;
  }

  function attach(el, commands, opts = {}) {
    grow(el);
    const menu = document.createElement("div");
    menu.className = "fk-menu"; menu.hidden = true;
    const out = opts.out || document.createElement("div");
    if (!opts.out) { out.className = "fk-out"; out.hidden = true; }
    const hint = document.createElement("div");
    hint.className = "fk-hint";
    hint.textContent = "İpucu: / yaz → komutlar (ör. /kesim, /foto, /video). Shift+Enter yeni satır.";
    el.after(menu); menu.after(hint); if (!opts.out) hint.after(out);
    let shown = [], idx = 0;

    const list = () => (typeof commands === "function" ? commands() : commands) || [];
    const parse = () => {
      const v = el.value;
      if (!v.startsWith("/")) return null;
      const m = v.slice(1).match(/^(\S*)(?:\s+([\s\S]*))?$/);
      return { name: norm(m ? m[1] : ""), args: m && m[2] ? m[2].trim() : "", spaced: /^\/\S*\s/.test(v) };
    };
    const find = (name) => list().find((c) => norm(c.name) === name || (c.alias || []).some((a) => norm(a) === name));

    function draw() {
      const p = parse();
      if (!p || (p.spaced && find(p.name))) { menu.hidden = true; shown = []; return; }
      shown = list().filter((c) => [c.name, ...(c.alias || [])].some((n) => norm(n).startsWith(p.name)) || norm(c.desc).includes(p.name));
      idx = Math.min(idx, Math.max(0, shown.length - 1));
      menu.replaceChildren(...shown.map((c, i) => {
        const row = document.createElement("div");
        row.className = "fk-item" + (i === idx ? " on" : "");
        const b = document.createElement("b"); b.textContent = "/" + c.name;
        const a = document.createElement("i"); a.textContent = c.args || "";
        const d = document.createElement("span"); d.textContent = c.desc || "";
        row.append(b, a, d);
        row.addEventListener("mousedown", (e) => { e.preventDefault(); complete(c); });
        return row;
      }));
      menu.hidden = !shown.length;
    }
    function complete(c) {
      el.value = "/" + c.name + " ";
      menu.hidden = true; el.focus(); el.__fkFit && el.__fkFit();
      if (!c.args) run();
    }
    function say(text, bad) {
      if (text == null || text === "") return;
      out.hidden = false; out.textContent = String(text); out.classList.toggle("bad", !!bad);
    }
    async function run() {
      const p = parse();
      if (!p) return false;
      const c = find(p.name);
      if (!c) { say(`Bilinmeyen komut: /${p.name}. Komutları görmek için /yardim yaz.`, true); return true; }
      if (c.needArgs && !p.args) { say(`/${c.name} ${c.args} — ${c.desc}`, true); return true; }
      const keep = el.value;
      el.value = ""; el.__fkFit && el.__fkFit(); menu.hidden = true;
      try { say(await c.run(p.args)); } catch (e) { el.value = keep; el.__fkFit && el.__fkFit(); say(`/${c.name}: ${e.message}`, true); }
      return true;
    }

    el.addEventListener("input", () => { idx = 0; draw(); });
    el.addEventListener("blur", () => setTimeout(() => { menu.hidden = true; }, 150));
    el.addEventListener("keydown", (e) => {
      if (!menu.hidden && shown.length) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault(); idx = (idx + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length; draw(); return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !find((parse() || {}).name))) {
          e.preventDefault(); complete(shown[idx]); return;
        }
        if (e.key === "Escape") { e.preventDefault(); menu.hidden = true; return; }
      }
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        if (el.value.startsWith("/")) { e.preventDefault(); run(); return; }
        if (opts.onEnter && el.value.trim()) { e.preventDefault(); opts.onEnter(); }
      }
    });
    return { say, run, out };
  }

  /** /yardim için komut listesi metni */
  const help = (commands) => ((typeof commands === "function" ? commands() : commands) || [])
    .map((c) => `/${c.name}${c.args ? " " + c.args : ""} — ${c.desc}`).join("\n");

  /* ---------- AI asistan: yaz ya da söyle → "Şunu anladım" → yapar ----------
   * assistant(kutu, komutlar, { post(path, body) → Promise<json>, upload(blob, ad) → Promise<yüklenen ad>, context() })
   * Sohbet balonları yalnızca textContent ile yazılır. */
  const css2 = document.createElement("style");
  css2.textContent = `
  .fa-log{display:flex;flex-direction:column;gap:6px;max-height:320px;overflow:auto;margin-bottom:8px}
  .fa-b{padding:7px 10px;border-radius:10px;font-size:13px;white-space:pre-line;max-width:95%}
  .fa-me{align-self:flex-end;background:rgba(127,127,127,.18)}
  .fa-ai{align-self:flex-start;border:1px solid var(--line,#253049)}
  .fa-ok{color:var(--ok,var(--acc2,#4fd1c5))} .fa-bad{color:var(--danger,var(--bad,#ff6b6b))} .fa-dim{opacity:.7}
  .fa-row{display:flex;gap:6px;align-items:flex-start;margin-top:6px;flex-wrap:wrap;justify-content:flex-end} .fa-row textarea{width:100%} .fa-row>div{flex:1 1 100%}
  .fa-mic{min-width:44px} .fa-mic.rec{background:var(--danger,var(--bad,#ff6b6b))!important;color:#fff!important;animation:fa-p 1s infinite}
  @keyframes fa-p{50%{opacity:.6}}`;
  document.head.append(css2);

  function assistant(box, commands, opts) {
    const list = () => (typeof commands === "function" ? commands() : commands) || [];
    const log = document.createElement("div"); log.className = "fa-log";
    const ta = document.createElement("textarea");
    ta.placeholder = "Ne yapayım? Yaz ya da 🎤 ile söyle — ör. “Venüs hakkında 40 saniyelik video yap”, “seçtiğim fotoğraflarla neşeli bir montaj yap”";
    const mic = document.createElement("button"); mic.className = "btn ghost fa-mic"; mic.type = "button"; mic.textContent = "🎤"; mic.title = "Basıp konuş, bitince tekrar bas";
    const send = document.createElement("button"); send.className = "btn pri"; send.type = "button"; send.textContent = "Yap";
    const wrap = document.createElement("div"); wrap.style.cssText = "min-width:0"; wrap.append(ta);  // menü/ipucu kutunun altına
    const row = document.createElement("div"); row.className = "fa-row"; row.append(wrap, mic, send);
    box.append(log, row);
    const k = attach(ta, commands, { onEnter: () => go() });
    k.out.hidden = true;
    const bubble = (text, cls) => {
      const b = document.createElement("div"); b.className = "fa-b " + cls; b.textContent = text;
      log.append(b); log.scrollTop = log.scrollHeight; return b;
    };
    let busy = false;
    async function go(spoken) {
      const text = (typeof spoken === "string" ? spoken : ta.value).trim();
      if (!text || busy) return;
      if (text.startsWith("/")) return k.run();
      busy = true; send.disabled = true;
      ta.value = ""; ta.__fkFit && ta.__fkFit();
      bubble((spoken ? "🎤 " : "") + text, "fa-me");
      const think = bubble("Düşünüyorum…", "fa-ai fa-dim");
      try {
        const p = await opts.post("/api/assistant", { text, commands: list().map(({ name, args, desc }) => ({ name, args, desc })),
          context: opts.context ? opts.context() : "" });
        if (p.error) throw new Error(p.error);
        think.classList.remove("fa-dim");
        think.textContent = p.soru ? "❓ " + p.soru : p.cevap ? p.cevap : "Anladım: " + (p.anladigim || "—") + (p.kural ? "  (Claude'a ulaşılamadı; basit kurallarla anladım)" : "");
        if (p.uyari) bubble("⏳ " + p.uyari, "fa-ai fa-bad");
        for (const st of p.adimlar || []) {
          const c = list().find((x) => x.name === st.komut);
          if (!c) continue;
          const b = bubble(`▶ ${c.desc}${st.arg ? ": " + st.arg : ""}`, "fa-ai fa-dim");
          try {
            const r = await c.run(st.arg || "");
            b.classList.remove("fa-dim"); b.classList.add("fa-ok");
            b.textContent = "✓ " + (r ? String(r) : c.desc + " başladı.");
          } catch (e) { b.classList.remove("fa-dim"); b.classList.add("fa-bad"); b.textContent = "✖ " + e.message; }
        }
      } catch (e) { think.classList.add("fa-bad"); think.textContent = "✖ " + e.message; }
      busy = false; send.disabled = false;
    }
    send.addEventListener("click", () => go());

    let rec = null, chunks = [];
    mic.addEventListener("click", async () => {
      if (rec) { rec.stop(); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        chunks = [];
        rec = new MediaRecorder(stream);
        rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
        rec.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          rec = null; mic.classList.remove("rec"); mic.textContent = "🎤";
          const blob = new Blob(chunks, { type: chunks[0] ? chunks[0].type : "audio/webm" });
          if (blob.size < 2000) return;
          const wait = bubble("🎤 Dinlediğimi yazıya döküyorum…", "fa-ai fa-dim");
          try {
            const name = await opts.upload(blob, "konusma.webm");
            const r = await opts.post("/api/assistant/listen", { file: name });
            if (r.error) throw new Error(r.error);
            wait.remove();
            if (!r.text) { bubble("Seni duyamadım, tekrar dener misin?", "fa-ai fa-bad"); return; }
            go(r.text);
          } catch (e) { wait.classList.add("fa-bad"); wait.textContent = "✖ " + e.message; }
        };
        rec.start(); mic.classList.add("rec"); mic.textContent = "■";
      } catch (e) { bubble("Mikrofon açılamadı: " + e.message, "fa-ai fa-bad"); }
    });
    return { go, bubble };
  }

  window.FabrikaKomut = { grow, attach, help, norm, assistant };
})();
