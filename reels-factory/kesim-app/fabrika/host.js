/* Kesim ⇄ Reels Fabrikası: Electron ana süreç köprüsü.
 * - Sayfaya (yalnızca Kesim penceresine) fabrika işlevlerini IPC ile açar.
 * - Dışa aktarılan videoları Masaüstü\kesim\Hazır klasörüne yazar (isteğe bağlı: fabrika bunlardan stil öğrenir).
 * - Claude (MCP) için yerel kontrol kapısı: 127.0.0.1, rastgele belirteç; açık projeyi okuma/düzenleme/dışa aktarma.
 *   Belirteç ve kapı numarası %APPDATA%\kesim\fabrika-kontrol.json dosyasında (yalnızca bu kullanıcı okur). */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const crypto = require("crypto");
const { Factory } = require("./client.js");

const fx = new Factory();
// Sayfanın çağırabileceği fabrika uçları (yayın onayı gibi işlemler bilerek dışarıda)
const GET_OK = [/^\/api\/kesim(\/|$)/, /^\/api\/jobs$/, /^\/api\/status$/, /^\/api\/studio\/(projects|styles)$/];
const POST_OK = [/^\/api\/kesim\//, /^\/api\/new$/, /^\/api\/publish\/queue$/];
const MEDIA_RE = /\.(mp4|mov|m4v|webm|mkv|avi|mts|3gp|jpe?g|png|webp|gif|bmp|heic|heif|mp3|wav|m4a|aac|ogg|flac|opus)$/i;
// sayfadan gelen hatanın yalnızca ilk satırı (yığın izi ve "Error:" önekleri olmadan)
const firstLine = (e) => String((e && e.message) || e).split("\n")[0].replace(/^(.*?Error:\s*)+/, "").trim();
const allowed = (p, list) => { p = String(p); if (!list.some((r) => r.test(p.split("?")[0]))) throw new Error("izinsiz: " + p); return p; };
let ctx = null, control = null;

function readyDir() {
  const home = os.homedir();
  const desks = [path.join(home, "Desktop"), path.join(home, "Masaüstü"), path.join(home, "OneDrive", "Desktop"), path.join(home, "OneDrive", "Masaüstü")];
  const desk = desks.find((d) => fs.existsSync(path.join(d, "kesim"))) || desks.find((d) => fs.existsSync(d)) || home;
  const dir = path.join(desk, "kesim", "Hazır");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function safeName(name) {
  return String(name || "kesim.mp4").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").slice(0, 120) || "kesim.mp4";
}

async function saveExport(name, data, learn) {
  const dest = path.join(readyDir(), safeName(name));
  fs.writeFileSync(dest, Buffer.from(data));
  let learned = false;
  if (learn) {
    try { const f = await fx.uploadPath(dest); await fx.post("/api/kesim/learn", { file: f }); learned = true; }
    catch (e) { console.error("[fabrika] öğrenme gönderilemedi:", e.message); }
  }
  return { path: dest, learned };
}

/* ---------- Claude / MCP kontrol kapısı ---------- */
function startControl() {
  const { app } = ctx;
  const token = crypto.randomBytes(24).toString("hex");
  const file = path.join(app.getPath("userData"), "fabrika-kontrol.json");
  const run = async (fn, arg) => {
    const w = ctx.getWindow();
    if (!w || w.isDestroyed()) throw new Error("Kesim penceresi açık değil");
    // argümanlar JSON olarak gömülür (kod enjeksiyonu yok); sayfa tarafı window.__fabrika işlevleri
    return w.webContents.executeJavaScript(`window.__fabrika.${fn}(${JSON.stringify(arg ?? null)})`, true);
  };
  const ROUTES = {
    "/state": () => run("state"),
    "/tools": () => run("tools"),
    "/call": (b) => run("call", { tool: String(b.tool || ""), args: b.args || {} }),
    "/import": (b) => run("importPath", { path: String(b.path || ""), timeline: b.timeline !== false }),
    "/export": (b) => run("exportTo", { formats: b.formats, res: b.res, fps: b.fps, name: b.name }),
  };
  control = http.createServer((req, res) => {
    const send = (code, obj) => { res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" }); res.end(JSON.stringify(obj)); };
    if (req.method !== "POST" || req.headers["x-kesim-token"] !== token || !ROUTES[req.url]) return send(403, { error: "yetkisiz" });
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > 1e6) req.destroy(); else chunks.push(c); });
    req.on("end", async () => {
      try { const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {}; send(200, { ok: true, result: await ROUTES[req.url](body) }); }
      catch (e) { send(400, { error: firstLine(e) }); }
    });
  });
  control.on("error", (e) => console.error("[fabrika] kontrol kapısı açılamadı:", e.message));
  control.listen(0, "127.0.0.1", () => {
    try { fs.writeFileSync(file, JSON.stringify({ port: control.address().port, token, pid: process.pid }), { mode: 0o600 }); }
    catch (e) { console.error("[fabrika] kontrol dosyası yazılamadı:", e.message); }
  });
  app.on("before-quit", () => { try { fs.unlinkSync(file); } catch { /* yok */ } try { control.close(); } catch { /* kapalı */ } });
}

function init(c) {
  ctx = c;
  const { ipcMain, shell } = c;
  const trusted = (e) => { const w = c.getWindow(); return !!w && !w.isDestroyed() && e.sender === w.webContents; };
  const handle = (ch, fn) => ipcMain.handle(ch, async (e, ...a) => {
    if (!trusted(e)) return { ok: false, error: "yetkisiz" };
    try { return { ok: true, data: await fn(...a) }; }
    catch (err) { return { ok: false, error: firstLine(err) }; }
  });
  handle("fb:status", async () => ({ alive: await fx.alive(), root: fx.cfg.root, ready: readyDir() }));
  handle("fb:start", () => fx.ensure());
  handle("fb:get", (p) => fx.get(allowed(p, GET_OK)));
  handle("fb:post", (p, body) => fx.post(allowed(p, POST_OK), body || {}));
  handle("fb:uploadPath", (p) => fx.uploadPath(String(p)));
  handle("fb:uploadBuffer", (name, data) => fx.uploadBuffer(String(name), data));
  handle("fb:fetch", (rel) => fx.fetchFile(String(rel)));
  handle("fb:wait", (task) => fx.waitResult(String(task)));
  handle("fb:readFile", (p) => {
    if (!MEDIA_RE.test(String(p))) throw new Error("yalnızca video, fotoğraf ve ses dosyaları okunabilir");
    return fs.readFileSync(String(p));
  });
  handle("fb:saveExport", (name, data, learn) => saveExport(name, data, !!learn));
  handle("fb:show", (p) => { if (shell) shell.showItemInFolder(String(p)); });
  startControl();
  fx.ensure().catch(() => { /* sekme durumu gösterir */ });
}

module.exports = { init };
