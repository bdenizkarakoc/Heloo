/* Kesim: çoklu seçim + toplu ayar, geniş yakınlaştırma, büyütülebilir zaman çizelgesi (CapCut benzeri).
 * - Ctrl/Shift+tık ile ekle-çıkar; boş alanda basılı tutup sürükleyerek çerçeveyle seç; klibe uzun basınca
 *   çoklu seçim modu açılır (sonraki dokunuşlar ekler/çıkarır); Ctrl+A hepsi, Esc seçimi kaldırır.
 * - Birden çok öğe seçiliyken sağ paneldeki her ayar seçili aynı türdeki öğelerin hepsine uygulanır;
 *   seçili grup birlikte sürüklenir, birlikte silinir/kopyalanır, hizalanır.
 * - Yakınlık 2–1500 px/sn (logaritmik), Ctrl+tekerlek imlecin olduğu yere yakınlaştırır, + / − tuşları.
 * - Önizleme ile zaman çizelgesi arasındaki tutamaçla çizelge büyütülür/küçültülür (çift tık: sıfırla).
 * Kesim'in global durumunu (S, sel, pxs, renderTimeline...) kullanır; dinamik metin yalnızca textContent ile. */
(function () {
  "use strict";
  if (typeof S !== "object" || typeof renderTimeline !== "function") return;
  const tlin = document.getElementById("tlin"), tl = document.getElementById("tl"), insp = document.getElementById("insp");
  const wrap = document.querySelector(".tlwrap");
  if (!tlin || !tl || !insp || !wrap) return;

  const KINDS = { clip: "Video", text: "Metin", fx: "Efekt", ov: "Katman", audio: "Müzik" };
  const LKEY = "kesim.coklu";
  const pref = (() => { try { return JSON.parse(localStorage.getItem(LKEY) || "{}"); } catch { return {}; } })();
  const savePref = () => { try { localStorage.setItem(LKEY, JSON.stringify(pref)); } catch { /* özel pencere */ } };
  const MS = new Map();          // seçili öğeler: id -> tür (birincil öğe `sel`, her zaman MS içinde)
  let pickMode = false;          // çoklu seçim modu: düz tık ekler/çıkarır

  const css = document.createElement("style");
  css.textContent = `
  .clip.msel{box-shadow:0 0 0 2px var(--accent);z-index:3}
  .clip.msel.sel{box-shadow:0 0 0 2px var(--fg),0 0 0 4px var(--accent)}
  .ms-box{position:absolute;border:1px solid var(--accent);background:color-mix(in srgb,var(--accent) 18%,transparent);z-index:20;pointer-events:none;border-radius:3px}
  .ms-split{height:7px;cursor:ns-resize;background:var(--panel);border-top:1px solid var(--line);display:flex;align-items:center;justify-content:center}
  .ms-split::after{content:"";width:42px;height:3px;border-radius:2px;background:var(--line)}
  .ms-split:hover::after,.ms-split.on::after{background:var(--accent)}
  .ms-banner{border:1px solid var(--accent);border-radius:10px;padding:10px;margin-bottom:12px;background:var(--panel2)}
  .ms-banner b{font-size:14px} .ms-banner .note{margin:4px 0}
  .ms-banner .ms-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  #bMulti.on{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}`;
  document.head.append(css);

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const find = (k, id) => arrOf(k).find((x) => x.id === id) || null;
  const items = () => [...MS].map(([id, k]) => ({ k, id, o: find(k, id) })).filter((x) => x.o);
  const clipEl = (id) => tlin.querySelector(`.clip[data-id="${CSS.escape(id)}"]`);
  const startOf = (it) => it.o.start || 0;
  const durOf = (it) => it.k === "clip" ? clipDur(it.o) : it.k === "text" || it.k === "fx" ? it.o.dur : it.o.out - it.o.in;

  function sync() {
    for (const [id, k] of MS) if (!find(k, id)) MS.delete(id);
    if (!sel) { MS.clear(); return; }
    if (!MS.has(sel.id)) { MS.clear(); MS.set(sel.id, sel.k); }
  }
  function paint() {
    const many = MS.size > 1;
    for (const c of tlin.querySelectorAll(".clip")) {
      const on = MS.has(c.dataset.id);
      c.classList.toggle("sel", !!sel && sel.id === c.dataset.id);
      c.classList.toggle("msel", many && on);
    }
  }
  function setSelection(map, primary) {
    MS.clear();
    for (const [id, k] of map) MS.set(id, k);
    if (primary && MS.has(primary.id)) sel = { k: primary.k, id: primary.id };
    else { const f = MS.entries().next().value; sel = f ? { k: f[1], id: f[0] } : null; }
    renderInspector(); paint();
  }
  function toggle(id, k) {
    if (!MS.size && sel) MS.set(sel.id, sel.k);
    const m = new Map(MS);
    if (m.has(id)) m.delete(id); else m.set(id, k);
    setSelection(m, m.has(id) ? { k, id } : sel && m.has(sel.id) ? sel : null);
  }
  function selectAll(kind) {
    const m = new Map();
    for (const k of Object.keys(KINDS)) if (!kind || k === kind) for (const x of arrOf(k)) m.set(x.id, k);
    setSelection(m, sel && m.has(sel.id) ? sel : null);
    if (m.size > 1) toast(`${m.size} öğe seçildi`);
  }
  function clearSelection() { MS.clear(); sel = null; renderInspector(); paint(); }

  /* ---------- Kesim işlevlerini sar ---------- */
  const _renderTimeline = renderTimeline;
  renderTimeline = function () {
    _renderTimeline.apply(this, arguments);
    baseH = parseFloat(wrap.style.height) || 282;
    sync(); paint(); applyHeight();
  };
  const _renderInspector = renderInspector;
  renderInspector = function () {
    _renderInspector.apply(this, arguments);
    sync();
    if (MS.size > 1) insp.prepend(banner());
  };
  const _delSel = delSel;
  delSel = function () { if (MS.size > 1) return batchDelete(); return _delSel.apply(this, arguments); };
  const _dupSel = dupSel;
  dupSel = function () { if (MS.size > 1) return batchDuplicate(); return _dupSel.apply(this, arguments); };
  const bDel = document.getElementById("bDel");
  if (bDel) bDel.onclick = () => delSel();

  /* ---------- toplu işlemler ---------- */
  function batchDelete() {
    const its = items();
    if (!its.length) return;
    pushUndo();
    for (const it of its) { const arr = arrOf(it.k), i = arr.indexOf(it.o); if (i >= 0) arr.splice(i, 1); }
    MS.clear(); sel = null;
    layoutAll(); renderAll(); setT(Math.min(t, total));
    toast(`${its.length} öğe silindi (Ctrl+Z ile geri al)`);
  }
  function batchDuplicate() {
    const its = items();
    if (!its.length) return;
    pushUndo();
    const free = its.filter((x) => x.k !== "clip");
    const a = Math.min(...free.map(startOf), Infinity), b = Math.max(...free.map((x) => startOf(x) + durOf(x)), -Infinity);
    const shift = free.length ? b - a : 0;
    const m = new Map();
    for (const it of its) {
      const n = JSON.parse(JSON.stringify(it.o)); n.id = uid();
      if (it.k === "clip") S.clips.splice(S.clips.indexOf(it.o) + 1, 0, n);
      else { n.start = it.o.start + shift; arrOf(it.k).push(n); }
      m.set(n.id, it.k);
    }
    layoutAll();
    setSelection(m, null); renderAll();
    toast(`${its.length} öğe kopyalandı`);
  }
  function alignToPlayhead() {
    const free = items().filter((x) => x.k !== "clip");
    if (!free.length) return toast("Hizalanacak metin, efekt, katman veya müzik seç.");
    pushUndo();
    for (const it of free) it.o.start = t;
    renderAll();
  }
  function lineUp() {
    const free = items().filter((x) => x.k !== "clip").sort((p, q) => startOf(p) - startOf(q));
    if (free.length < 2) return toast("Arka arkaya dizmek için en az iki metin/efekt/katman/müzik seç.");
    pushUndo();
    let s = startOf(free[0]);
    for (const it of free) { it.o.start = s; s += durOf(it); }
    renderAll();
  }

  function banner() {
    const its = items(), count = {};
    for (const it of its) count[it.k] = (count[it.k] || 0) + 1;
    const b = el("div", "ms-banner");
    b.append(el("b", null, `${its.length} öğe seçili`));
    b.append(el("div", "note", Object.entries(count).map(([k, n]) => `${n} ${KINDS[k]}`).join(" · ")));
    const kinds = Object.keys(count);
    b.append(el("div", "note", kinds.length > 1
      ? `Aşağıdaki ayarlar seçili bütün ${KINDS[sel.k]} öğelerine uygulanır. Başka türü ayarlamak için seç:`
      : "Aşağıda değiştirdiğin her ayar seçili öğelerin hepsine uygulanır."));
    if (kinds.length > 1) {
      const r = el("div", "ms-row");
      for (const k of kinds) {
        const c = el("button", "chip" + (k === sel.k ? " on" : ""), `${KINDS[k]} (${count[k]})`);
        c.onclick = () => { const f = its.find((x) => x.k === k); sel = { k, id: f.id }; renderInspector(); paint(); };
        r.append(c);
      }
      b.append(r);
    }
    const r2 = el("div", "ms-row");
    const add = (text, fn, cls = "btn") => { const x = el("button", cls, text); x.onclick = fn; r2.append(x); };
    add("Hepsini kopyala", batchDuplicate);
    add("Oynatma çizgisine hizala", alignToPlayhead);
    add("Arka arkaya diz", lineUp);
    add(`Tüm ${KINDS[sel.k]} öğelerini seç`, () => selectAll(sel.k));
    add("Seçimi kaldır", clearSelection);
    add("Hepsini sil", batchDelete, "btn dng");
    b.append(r2);
    return b;
  }

  /* ---------- ayarları gruba yay ---------- */
  const MEDIA_PROPS = new Set(["speed", "volume", "mute", "fin", "fout", "dur"]);
  const SKIP = new Set(["text", "start"]);   // metin içeriği ve başlangıç her öğede ayrı kalır
  const setDeep = (o, p, v) => {
    const ks = p.split("."), last = ks.pop();
    let cur = o;
    for (const k of ks) { if (cur[k] == null || typeof cur[k] !== "object") cur[k] = {}; cur = cur[k]; }
    cur[last] = v && typeof v === "object" ? JSON.parse(JSON.stringify(v)) : v;
  };
  function peers() {
    if (MS.size < 2 || !sel) return [];
    return items().filter((x) => x.k === sel.k && x.id !== sel.id);
  }
  function spread(props) {
    const src = findSel(), ps = peers();
    if (!src || !ps.length) return false;
    const srcKind = sel.k === "clip" ? (media.get(src.mid) || {}).kind : null;
    for (const p of props) {
      if (SKIP.has(p)) continue;
      for (const it of ps) {
        if (sel.k === "clip" && MEDIA_PROPS.has(p) && (media.get(it.o.mid) || {}).kind !== srcKind) continue;
        if (sel.k === "clip" && p === "dur") it.o.out = it.o.in + clipDur(src) * it.o.speed;
        else setDeep(it.o, p, getP(src, p));
      }
    }
    layout(); renderTimeline(); dirty = true;
    if (!playing) syncMedia(t, false);
    return true;
  }
  // Kesim'in kendi işleyicisi önce birincil öğeyi değiştirir (geri alma kaydı dahil), sonra burada gruba yayılır.
  insp.addEventListener("input", (e) => { const p = e.target.dataset && e.target.dataset.p; if (p) spread([p]); });
  insp.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || MS.size < 2) return;
    if (b.dataset.set) spread([b.dataset.set.split("|")[0]]);
    else if (b.dataset.preset) spread(["fx"]);
    else if (b.dataset.act === "rot") spread(["rot"]);
    else if (b.dataset.act === "flipH" || b.dataset.act === "flipV") spread([b.dataset.act]);
  });

  /* ---------- zaman çizelgesinde seçim ---------- */
  function groupDrag(e, id, k) {
    const free = items().filter((x) => x.k !== "clip");
    const s0 = new Map(free.map((x) => [x.id, x.o.start]));
    const minS = Math.min(...free.map((x) => x.o.start), Infinity);
    let pushed = false;
    if (playing) pause();
    dragger(e, (dx) => {
      if (!free.length) return;
      if (!pushed) { pushUndo(); pushed = true; }
      const d = Math.max(dx / pxs, -minS);
      for (const x of free) { x.o.start = s0.get(x.id) + d; const c = clipEl(x.id); if (c) c.style.left = x.o.start * pxs + "px"; }
      dirty = true;
    }, (moved) => {
      if (moved) { renderAll(); return; }
      if (pickMode) { toggle(id, k); return; }
      setSelection(new Map([[id, k]]), { k, id }); renderTimeline();
    });
  }

  function marquee(e) {
    const base = e.ctrlKey || e.metaKey || e.shiftKey || pickMode ? new Map(MS) : new Map();
    if (sel && base.size && !base.has(sel.id)) base.set(sel.id, sel.k);
    const box = el("div", "ms-box");
    const r0 = tlin.getBoundingClientRect(), x0 = e.clientX - r0.left, y0 = e.clientY - r0.top;
    let hit = new Map(base);
    dragger(e, (dx, dy, ev) => {
      if (!box.isConnected) tlin.append(box);
      const tr = tl.getBoundingClientRect();
      if (ev.clientX > tr.right - 30) tl.scrollLeft += 24; else if (ev.clientX < tr.left + 30) tl.scrollLeft -= 24;
      const r = tlin.getBoundingClientRect(), x1 = ev.clientX - r.left, y1 = ev.clientY - r.top;
      const L = Math.min(x0, x1), T = Math.min(y0, y1), R = Math.max(x0, x1), B = Math.max(y0, y1);
      Object.assign(box.style, { left: L + "px", top: T + "px", width: R - L + "px", height: B - T + "px" });
      hit = new Map(base);
      for (const c of tlin.querySelectorAll(".clip")) {
        const q = c.getBoundingClientRect(), cl = q.left - r.left, ct = q.top - r.top;
        const inside = cl < R && cl + q.width > L && ct < B && ct + q.height > T;
        if (inside) hit.set(c.dataset.id, c.dataset.k);
        c.classList.toggle("msel", hit.has(c.dataset.id));
      }
    }, (moved) => {
      box.remove();
      if (!moved) {   // tık: Kesim'in davranışı (seçimi kaldır, oynatma çizgisini taşı)
        if (!pickMode) { MS.clear(); sel = null; renderInspector(); renderTimeline(); }
        pause(); setT(xToT(e)); return;
      }
      setSelection(hit, null);
      if (hit.size > 1) toast(`${hit.size} öğe seçildi — sağdaki ayarlar hepsine uygulanır`);
    });
  }

  let pressTimer = null;
  tlin.addEventListener("pointerdown", (e) => {
    if (exporting || e.button !== 0) return;
    clearTimeout(pressTimer);
    const c = e.target.closest(".clip");
    const mod = e.ctrlKey || e.metaKey || e.shiftKey;
    if (c) {
      const id = c.dataset.id, k = c.dataset.k, handle = e.target.classList.contains("h");
      if (mod || (pickMode && !handle && !(MS.size > 1 && MS.has(id)))) {
        e.stopImmediatePropagation(); e.preventDefault(); toggle(id, k); return;
      }
      if (MS.size > 1 && MS.has(id) && !handle) { e.stopImmediatePropagation(); groupDrag(e, id, k); return; }
      // uzun basış: çoklu seçim modunu aç ve önceki seçimi koru
      const prev = new Map(MS.size ? MS : sel ? [[sel.id, sel.k]] : []);
      const sx = e.clientX, sy = e.clientY;
      const cancel = (ev) => { if (!ev || ev.type !== "pointermove" || Math.hypot(ev.clientX - sx, ev.clientY - sy) > 6) { clearTimeout(pressTimer); off(); } };
      const off = () => { removeEventListener("pointermove", cancel); removeEventListener("pointerup", cancel); };
      addEventListener("pointermove", cancel); addEventListener("pointerup", cancel);
      pressTimer = setTimeout(() => {
        off(); setPick(true); prev.set(id, k); setSelection(prev, { k, id });
        toast("Çoklu seçim açık: eklemek/çıkarmak için öğelere dokun");
      }, 550);
      MS.clear();
      return;   // Kesim'in kendi tek seçim / sürükleme davranışı
    }
    if (e.target.closest(".ruler") || !e.target.closest(".row")) return;
    e.stopImmediatePropagation();
    marquee(e);
  }, true);

  /* ---------- çoklu seçim düğmesi + kısayollar ---------- */
  const transport = document.querySelector(".transport"), spacer = transport && transport.querySelector(".sp");
  const bMulti = el("button", "btn", "Çoklu seçim");
  bMulti.id = "bMulti";
  bMulti.title = "Çoklu seçim (Ctrl/Shift+tık, sürükleyerek çerçeve, Ctrl+A)";
  const setPick = (on) => { pickMode = on; bMulti.classList.toggle("on", on); };
  bMulti.onclick = () => { setPick(!pickMode); if (!pickMode && MS.size < 2) paint(); };
  if (spacer) transport.insertBefore(bMulti, spacer);

  addEventListener("keydown", (e) => {
    if (exporting) return;
    const tg = e.target;
    if (tg && (tg.tagName === "TEXTAREA" || tg.tagName === "SELECT" || (tg.tagName === "INPUT" && tg.type !== "range" && tg.type !== "checkbox"))) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === "a") { e.preventDefault(); selectAll(); }
    else if ((e.ctrlKey || e.metaKey) && k === "d") { e.preventDefault(); dupSel(); }
    else if (k === "escape" && (MS.size || pickMode)) { setPick(false); clearSelection(); }
    else if (!e.ctrlKey && !e.metaKey && (k === "+" || k === "=")) { e.preventDefault(); zoomBy(1.4); }
    else if (!e.ctrlKey && !e.metaKey && (k === "-" || k === "_")) { e.preventDefault(); zoomBy(1 / 1.4); }
  });

  /* ---------- yakınlaştırma: 2–1500 px/sn, logaritmik ---------- */
  const ZMIN = 2, ZMAX = 1500;
  const toSlider = (p) => Math.round(1000 * Math.log(p / ZMIN) / Math.log(ZMAX / ZMIN));
  const fromSlider = (v) => ZMIN * Math.pow(ZMAX / ZMIN, v / 1000);
  const oldZoom = document.getElementById("zoom"), zoom = oldZoom.cloneNode(true);   // kopya: eski dinleyiciler düşer
  zoom.min = "0"; zoom.max = "1000"; zoom.step = "1"; zoom.value = String(toSlider(pxs));
  oldZoom.replaceWith(zoom);
  function setZoom(p, anchorX) {
    const ax = anchorX == null ? tl.clientWidth / 2 : anchorX;
    const at = (tl.scrollLeft + ax) / pxs;
    pxs = clamp(p, ZMIN, ZMAX);
    zoom.value = String(toSlider(pxs));
    renderTimeline();
    tl.scrollLeft = at * pxs - ax;
  }
  const zoomBy = (f, ax) => setZoom(pxs * f, ax);
  zoom.addEventListener("input", () => setZoom(fromSlider(+zoom.value)));
  tl.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey || e.altKey)) return;
    e.preventDefault();
    zoomBy(Math.exp(-e.deltaY * 0.0022), e.clientX - tl.getBoundingClientRect().left);
  }, { passive: false });
  const oldFit = document.getElementById("bFit");
  if (oldFit) {
    const fit = oldFit.cloneNode(true);
    oldFit.replaceWith(fit);
    fit.addEventListener("click", () => { setZoom((tl.clientWidth - 60) / Math.max(total, 5)); tl.scrollLeft = 0; });
  }
  const zbox = zoom.parentNode;
  if (zbox) for (const [txt, f, tip] of [["−", 1 / 1.6, "Uzaklaştır (−)"], ["+", 1.6, "Yakınlaştır (+)"]]) {
    const b = el("button", "btn", txt); b.title = tip; b.onclick = () => zoomBy(f);
    if (txt === "−") zbox.insertBefore(b, zoom); else zbox.insertBefore(b, zoom.nextSibling);
  }

  /* ---------- zaman çizelgesi yüksekliği (tutamaç) ---------- */
  const BASE = { t: 34, v: 66, a: 40 };
  const labs = wrap.querySelectorAll(".labels > div");   // Efekt, Metin, Katman, Video, Müzik
  const rows = { t: document.getElementById("rowT"), v: document.getElementById("rowV"), a: document.getElementById("rowA") };
  const labOf = { t: labs[1], v: labs[3], a: labs[4] };
  const BASE_SUM = BASE.t + BASE.v + BASE.a;
  let extra = Number(pref.extra) || 0;
  const maxExtra = () => Math.max(0, innerHeight - 282 - 300);
  function applyHeight() {
    extra = clamp(extra, -50, maxExtra());
    const f = 1 + extra / BASE_SUM;
    for (const k of ["t", "v", "a"]) {
      const hgt = Math.round(BASE[k] * f) + "px";
      if (rows[k]) rows[k].style.height = hgt;
      if (labOf[k]) labOf[k].style.height = hgt;
    }
    wrap.style.height = baseH + extra + "px";
  }
  let baseH = parseFloat(wrap.style.height) || 282;   // Kesim'in her çizimde verdiği yükseklik (efekt/katman şeritleri dahil)
  const split = el("div", "ms-split");
  split.title = "Sürükle: zaman çizelgesini büyüt / küçült · çift tık: sıfırla";
  wrap.parentNode.insertBefore(split, wrap);
  split.addEventListener("pointerdown", (e) => {
    const e0 = extra;
    split.classList.add("on");
    dragger(e, (dx, dy) => { extra = e0 - dy; applyHeight(); fitStage && fitStage(); dirty = true; },
      () => { split.classList.remove("on"); pref.extra = extra; savePref(); fitStage && fitStage(); dirty = true; });
  });
  split.addEventListener("dblclick", () => { extra = 0; pref.extra = 0; savePref(); applyHeight(); fitStage && fitStage(); dirty = true; });
  addEventListener("resize", () => applyHeight());

  // Claude/MCP ve diğer modüller için: seçili öğeler
  window.__kesimSecim = () => items().map((x) => ({ tur: x.k, id: x.id }));

  renderTimeline();
})();
