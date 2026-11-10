"use strict";
// Aktarım — telefon ve bilgisayar için tek sayfa. Dinamik metinler yalnızca textContent ile yazılır.

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const isMobile = /iPhone|iPad|Android|Mobile/i.test(navigator.userAgent);
const isIOS = /iPhone|iPad/i.test(navigator.userAgent) || (navigator.userAgent.includes("Macintosh") && "ontouchend" in document);

const state = { data: null, version: -1, filter: "all", tab: "items", seen: new Set(), first: true };
const TITLES = { items: "Paylaşılanlar", send: "Gönder", bin: "Sonradan Sil", connect: "Bağlan" };
const DAYS_LABEL = { 7: "1 hafta", 14: "2 hafta", 30: "1 ay" };

// ---------- yardımcılar ----------
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, { credentials: "same-origin", cache: "no-store", ...opt });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 2400);
}
function size(n) {
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < 2);
  return n.toFixed(n < 10 ? 1 : 0).replace(".", ",") + " " + u[i];
}
function when(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const hm = d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return "Bugün " + hm;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Dün " + hm;
  return d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" }) + " " + hm;
}
function left(exp) {
  const s = exp - Date.now() / 1000;
  if (s <= 3600) return "1 saatten az kaldı";
  if (s < 86400) return Math.ceil(s / 3600) + " saat kaldı";
  return Math.ceil(s / 86400) + " gün kaldı";
}
function kind(it) {
  if (it.kind === "text") return "text";
  const m = it.mime || "";
  if (m.startsWith("image/")) return "photo";
  if (m.startsWith("video/")) return "video";
  if (m.startsWith("audio/")) return "audio";
  if (/zip|rar|7z|tar|gzip/.test(m)) return "zip";
  return "doc";
}
const ICON = { text: "✎", photo: "▣", video: "▶", audio: "♪", zip: "▤", doc: "▧" };
const fileUrl = (it, dl) => `/api/file/${it.id}/${encodeURIComponent(it.name)}${dl ? "?dl=1" : ""}`;
const viewable = (it) => kind(it) === "photo" && !/heic|heif/i.test(it.mime || "") || kind(it) === "video";

// ---------- sekmeler ----------
function setTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.dataset.page !== tab));
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("#title").textContent = TITLES[tab];
  if (tab === "connect") drawQR();
  window.scrollTo(0, 0);
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setTab(b.dataset.tab);
});
$("#filter").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.filter = b.dataset.f;
  document.querySelectorAll("#filter button").forEach((x) => x.classList.toggle("on", x === b));
  render();
});

// ---------- işlem sayfası (iOS action sheet) ----------
function sheet(title, actions) {
  const back = $("#sheet-back"), box = $("#sheet-actions");
  $("#sheet-title").textContent = title;
  box.replaceChildren();
  actions.forEach(([label, fn, red]) => {
    const b = el("button", red ? "red" : "", label);
    b.addEventListener("click", () => { back.hidden = true; fn(); });
    box.append(b);
  });
  back.hidden = false;
}
$("#sheet-cancel").addEventListener("click", () => ($("#sheet-back").hidden = true));
$("#sheet-back").addEventListener("click", (e) => { if (e.target.id === "sheet-back") e.currentTarget.hidden = true; });

function viewer(node) {
  $("#viewer-body").replaceChildren(node);
  $("#viewer").hidden = false;
}
$("#viewer-close").addEventListener("click", () => {
  $("#viewer").hidden = true;
  $("#viewer-body").replaceChildren();
});

function download(it) {
  const a = el("a");
  a.href = fileUrl(it, true);
  a.download = it.name;
  document.body.append(a);
  a.click();
  a.remove();
  if (isIOS) toast("İndirilenler → Dosyalar uygulamasında");
}
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const t = el("textarea");
    t.value = text;
    t.style.position = "fixed"; t.style.opacity = "0";
    document.body.append(t);
    t.select();
    t.setSelectionRange(0, text.length);
    document.execCommand("copy");
    t.remove();
  }
  toast("Kopyalandı");
}
async function shareFile(it) {
  try {
    const blob = await (await fetch(fileUrl(it))).blob();
    const file = new File([blob], it.name, { type: it.mime });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file] });
      return;
    }
  } catch (e) { if (e && e.name === "AbortError") return; }
  openItem(it);
  toast("Görsele basılı tut → “Fotoğraflara Ekle”");
}
function openItem(it) {
  const k = kind(it);
  if (k === "text") {
    const pre = el("pre", "", it.text);
    return viewer(pre);
  }
  if (k === "photo" && viewable(it)) {
    const img = el("img"); img.src = fileUrl(it); img.alt = it.name;
    return viewer(img);
  }
  if (k === "video") {
    const v = el("video"); v.src = fileUrl(it); v.controls = true; v.playsInline = true; v.autoplay = true;
    return viewer(v);
  }
  if (/pdf|text\/plain/.test(it.mime || "")) {
    const f = el("iframe"); f.src = fileUrl(it);
    return viewer(f);
  }
  window.open(fileUrl(it), "_blank");
}

function laterMenu(it) {
  sheet(`“${it.name}” ne zaman silinsin? Bu süre içinde Sonradan Sil'den geri yükleyebilirsin.`, [
    ["1 hafta sonra sil", () => softDelete(it, 7)],
    ["2 hafta sonra sil", () => softDelete(it, 14)],
    ["1 ay sonra sil", () => softDelete(it, 30)],
    ["Hemen kalıcı olarak sil", () => purge(it), true],
  ]);
}
async function softDelete(it, days) {
  await api("/api/delete", { id: it.id, days });
  toast(`Sonradan Sil'e taşındı · ${DAYS_LABEL[days]} sonra silinecek`);
  refresh(true);
}
async function purge(it) {
  if (!confirm(`“${it.name}” kalıcı olarak silinsin mi? Bu geri alınamaz.`)) return;
  await api("/api/purge", { id: it.id });
  toast("Kalıcı olarak silindi");
  refresh(true);
}

function itemMenu(it) {
  const k = kind(it), acts = [];
  if (k === "text") {
    acts.push(["Kopyala", () => copyText(it.text)], ["Aç", () => openItem(it)]);
    if (/^https?:\/\/\S+$/.test(it.text)) acts.push(["Bağlantıyı aç", () => window.open(it.text, "_blank")]);
  } else {
    acts.push(["Aç", () => openItem(it)]);
    if (isMobile && (k === "photo" || k === "video")) acts.push([isIOS ? "Fotoğraflara kaydet" : "Galeriye kaydet", () => (isIOS ? shareFile(it) : download(it))]);
    acts.push([isMobile ? "Dosyalara indir" : "Bilgisayara indir", () => download(it)]);
  }
  acts.push(["Sonradan sil…", () => laterMenu(it), true]);
  sheet(`${it.name} · ${it.source || ""} · ${when(it.created)}`, acts);
}
function binMenu(it) {
  sheet(`${it.name} · ${left(it.expires_at)}`, [
    ["Geri yükle", async () => { await api("/api/restore", { id: it.id }); toast("Geri yüklendi"); refresh(true); }],
    ["Süreyi 1 hafta yap", () => softDelete(it, 7)],
    ["Süreyi 2 hafta yap", () => softDelete(it, 14)],
    ["Süreyi 1 ay yap", () => softDelete(it, 30)],
    ["Kalıcı olarak sil", () => purge(it), true],
  ]);
}

// ---------- çizim ----------
function row(it, sub, onClick, extra) {
  const r = el("button", "row");
  const ic = el("span", "ic " + kind(it));
  if (kind(it) === "photo" && viewable(it)) {
    const img = el("img"); img.loading = "lazy"; img.src = fileUrl(it); img.alt = "";
    ic.append(img);
  } else ic.textContent = ICON[kind(it)];
  const main = el("span", "main");
  main.append(el("div", "name", it.kind === "text" ? it.text.replace(/\s+/g, " ").slice(0, 120) : it.name), el("div", "sub", sub));
  r.append(ic, main, extra || el("span", "chev", "›"));
  r.addEventListener("click", onClick);
  return r;
}
function tile(it) {
  const t = el("button", "tile");
  const k = kind(it);
  if (k === "photo" && viewable(it)) {
    const img = el("img"); img.loading = "lazy"; img.src = fileUrl(it); img.alt = it.name;
    t.append(img);
  } else if (k === "video") {
    const v = el("video"); v.src = fileUrl(it) + "#t=0.1"; v.muted = true; v.playsInline = true; v.preload = "metadata";
    t.append(v, el("span", "badge", "▶ " + size(it.size)));
  } else t.append(el("span", "badge", it.name));
  if (it.source) t.append(el("span", "src", it.source));
  t.addEventListener("click", () => itemMenu(it));
  return t;
}
function render() {
  const d = state.data;
  if (!d) return;
  const f = state.filter;
  const items = d.items.filter((it) => f === "all" || kind(it) === f || (f === "doc" && ["doc", "zip", "audio"].includes(kind(it))));
  const media = items.filter((it) => ["photo", "video"].includes(kind(it)));
  const rest = items.filter((it) => !media.includes(it));
  $("#photos").replaceChildren(...media.map(tile));
  $("#list").replaceChildren(...rest.map((it) => row(it, `${it.source || ""} · ${when(it.created)} · ${size(it.size)}`, () => itemMenu(it))));
  $("#empty").hidden = items.length > 0;

  $("#bin").replaceChildren(...d.bin.map((it) => {
    const restoreBtn = el("span", "act", "Geri yükle");
    restoreBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api("/api/restore", { id: it.id });
      toast("Geri yüklendi");
      refresh(true);
    });
    return row(it, `${left(it.expires_at)} · ${size(it.size)}`, () => binMenu(it), restoreBtn);
  }));
  $("#bin-empty").hidden = d.bin.length > 0;
  $("#empty-bin").hidden = d.bin.length === 0;
  const c = $("#bin-count");
  c.hidden = d.bin.length === 0;
  c.textContent = d.bin.length;
  document.querySelectorAll("#retention button").forEach((b) => b.classList.toggle("on", +b.dataset.d === d.retention_days));
}

// ---------- veri ----------
async function refresh(force) {
  try {
    if (!force && state.data) {
      const v = await api("/api/version");
      $("#status").classList.remove("off");
      $("#status b").textContent = "Bağlı";
      if (v.version === state.version) return;
    }
    const d = await api("/api/items");
    $("#status").classList.remove("off");
    $("#status b").textContent = "Bağlı";
    const fresh = d.items.filter((it) => !state.seen.has(it.id) && it.source !== state.device);
    if (!state.first && fresh.length) {
      const from = [...new Set(fresh.map((i) => i.source))].join(", ");
      toast(`${from}: ${fresh.length} yeni öğe`);
    }
    d.items.forEach((it) => state.seen.add(it.id));
    state.first = false;
    state.data = d;
    state.version = d.version;
    render();
  } catch (e) {
    $("#status").classList.add("off");
    $("#status b").textContent = /anahtar/.test(e.message) ? "Yeniden okut" : "Bağlantı yok";
  }
}

// ---------- gönderme ----------
function upload(file, name) {
  name = name || file.name || "dosya";
  const r = el("div", "row");
  const main = el("span", "main");
  const bar = el("div", "bar"), fill = el("i");
  bar.append(fill);
  const sub = el("div", "sub", "Bekliyor · " + size(file.size));
  main.append(el("div", "name", name), sub, bar);
  r.append(el("span", "ic doc", "⬆︎"), main);
  $("#uploads").prepend(r);
  return new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/upload");
    x.setRequestHeader("X-Filename", encodeURIComponent(name));
    x.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    x.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = Math.round((e.loaded / e.total) * 100);
      fill.style.width = p + "%";
      sub.textContent = `%${p} · ${size(e.loaded)} / ${size(e.total)}`;
    };
    x.onload = () => {
      const ok = x.status === 201;
      sub.textContent = ok ? "Gönderildi ✓" : "Hata: " + (JSON.parse(x.responseText || "{}").error || x.status);
      fill.style.width = "100%";
      if (!ok) fill.style.background = "var(--red)";
      if (ok) state.seen.add(JSON.parse(x.responseText).id);
      setTimeout(() => r.remove(), ok ? 4000 : 15000);
      resolve(ok);
    };
    x.onerror = () => { sub.textContent = "Bağlantı koptu"; fill.style.background = "var(--red)"; resolve(false); };
    x.send(file);
  });
}
async function uploadAll(list) {
  const files = [...list].filter(Boolean);
  if (!files.length) return;
  if (state.tab !== "send") setTab("send");
  let ok = 0;
  for (const f of files) ok += (await upload(f.file || f, f.path)) ? 1 : 0;
  toast(`${ok}/${files.length} öğe gönderildi`);
  refresh(true);
}
$("#pick").addEventListener("change", (e) => { uploadAll(e.target.files); e.target.value = ""; });
$("#pick-cam").addEventListener("change", (e) => { uploadAll(e.target.files); e.target.value = ""; });
$("#send-text").addEventListener("click", async () => {
  const t = $("#text"), text = t.value.trim();
  if (!text) return t.focus();
  const it = await api("/api/text", { text });
  state.seen.add(it.id);
  t.value = "";
  toast("Yazı gönderildi");
  refresh(true);
});

// sürükle-bırak (klasörler dahil)
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; document.body.classList.add("dragging"); } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", async (e) => {
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return uploadAll(e.dataTransfer.files);
  const out = [];
  const walk = (entry, prefix) => new Promise((res) => {
    if (entry.isFile) return entry.file((f) => { out.push({ file: f, path: prefix + f.name }); res(); }, res);
    const reader = entry.createReader(), all = [];
    const next = () => reader.readEntries(async (batch) => {
      if (!batch.length) { for (const c of all) await walk(c, prefix + entry.name + "/"); return res(); }
      all.push(...batch); next();
    }, res);
    next();
  });
  for (const en of entries) await walk(en, "");
  uploadAll(out.map((o) => ({ file: o.file, path: o.path.replace(/\//g, " - ") })));
});

// yapıştır: görsel/dosya ya da yazı
window.addEventListener("paste", (e) => {
  if (e.target.closest && e.target.closest("textarea, input")) {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); uploadAll(files.map((f, i) => ({ file: f, path: f.name === "image.png" ? `Yapıştırılan ${Date.now()}-${i}.png` : f.name }))); }
    return;
  }
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) return uploadAll(files.map((f, i) => ({ file: f, path: f.name === "image.png" ? `Yapıştırılan ${Date.now()}-${i}.png` : f.name })));
  const text = e.clipboardData?.getData("text");
  if (text && text.trim()) api("/api/text", { text }).then((it) => { state.seen.add(it.id); toast("Yazı gönderildi"); refresh(true); });
});

// ---------- Sonradan Sil ayarları ----------
$("#retention").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  await api("/api/settings", { retention_days: +b.dataset.d });
  toast(`Varsayılan süre: ${DAYS_LABEL[b.dataset.d]}`);
  refresh(true);
});
$("#empty-bin").addEventListener("click", async () => {
  if (!confirm("Sonradan Sil kutusundaki her şey kalıcı olarak silinsin mi?")) return;
  const r = await api("/api/empty-bin", {});
  toast(`${r.removed} öğe kalıcı olarak silindi`);
  refresh(true);
});

// ---------- bağlan / QR ----------
let info = null;
function drawQR() {
  if (!info) return;
  const url = $("#urls").value || info.urls[0];
  const box = $("#qr");
  box.replaceChildren();
  if (window.QRCode) {
    new window.QRCode(box, { text: url, width: 220, height: 220, correctLevel: window.QRCode.CorrectLevel.M });
  } else {
    box.append(el("div", "muted", "QR kodu yüklenemedi; bağlantıyı telefona elle yaz:"), el("b", "", url));
  }
}
$("#urls").addEventListener("change", drawQR);
$("#copy-url").addEventListener("click", () => copyText($("#urls").value));

async function init() {
  info = await api("/api/info").catch(() => null);
  if (info) {
    state.device = info.device;
    $("#device").textContent = info.device === "Bilgisayar" ? "Bu bilgisayar" : info.device;
    $("#urls").replaceChildren(...info.urls.map((u) => { const o = el("option", "", u); o.value = u; return o; }));
    $("#data-dir").textContent = "Dosyalar bilgisayarda: " + info.data_dir;
  }
  if (isMobile) {
    $("#pick-hint").textContent = isIOS ? "Fotoğraf Arşivi, Dosyalar ya da Kamera" : "Galeri, Dosyalarım ya da Kamera";
  } else {
    $("#pick-cam").previousElementSibling.hidden = true;
    $("#pick-hint").textContent = "ya da dosyaları/klasörleri bu pencereye sürükle-bırak";
  }
  await refresh(true);
  if (!isMobile && state.data && !state.data.items.length) setTab("connect");
  setInterval(refresh, 2000);
  window.addEventListener("load", () => state.tab === "connect" && drawQR());
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
init();
