/* Kesim SelfEdit: Electron ana süreç köprüsü.
 * Motoru başlatır, gizli doğrulama penceresini yönetir, IPC'yi (yalnızca Kesim penceresine) açar,
 * isteğe bağlı olarak tepsi simgesi + Windows ile başlatma ile arka planda çalışmayı sağlar. */
"use strict";
const fs = require("fs");
const path = require("path");
const { Engine } = require("./engine.js");

let engine = null, tray = null, quitting = false, ctx = null;

function makeSecrets(dir, safeStorage) {
  const f = path.join(dir, "api_key.bin");
  return {
    has: () => fs.existsSync(f),
    async get() { try { return fs.existsSync(f) ? safeStorage.decryptString(fs.readFileSync(f)) : null; } catch { return null; } },
    async set(key) {
      if (!/^sk-ant-[A-Za-z0-9_\-]{20,400}$/.test(key)) throw new Error("Bu bir Anthropic API anahtarına benzemiyor (sk-ant- ile başlamalı).");
      if (!safeStorage.isEncryptionAvailable()) throw new Error("Bu bilgisayarda güvenli anahtar depolama kullanılamıyor; anahtar kaydedilmedi.");
      fs.writeFileSync(f, safeStorage.encryptString(key));
    },
    async clear() { try { fs.unlinkSync(f); } catch { /* zaten yok */ } },
  };
}

/** Tarifi gizli bir Chromium penceresinde gerçek canvas ile sınar. Pencere her seferinde yok edilir. */
async function runCheck(recipe) {
  const { BrowserWindow } = ctx;
  const fail = (detail) => ({ ok: false, steps: [{ step: "doğrulama penceresi", ok: false, detail }] });
  const w = new BrowserWindow({ show: false, width: 900, height: 600, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
  try {
    w.webContents.on("will-navigate", (e) => e.preventDefault());
    w.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    await w.loadFile(path.join(__dirname, "validate.html"));
    let timer;
    const timeout = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error("zaman aşımı (20 sn)")), 20000); });
    try { return await Promise.race([w.webContents.executeJavaScript(`window.__check(${JSON.stringify(recipe)})`), timeout]); }
    finally { clearTimeout(timer); }
  } catch (e) { return fail(String(e && e.message || e)); }
  finally { if (!w.isDestroyed()) w.destroy(); }
}

function applyBackground() {
  const { app, Tray, Menu, nativeImage } = ctx, on = !!engine.config().background;
  try { app.setLoginItemSettings({ openAtLogin: on, args: on ? ["--arka-plan"] : [] }); } catch { /* bazı ortamlarda desteklenmez */ }
  if (on && !tray) {
    try {
      tray = new Tray(nativeImage.createFromPath(path.join(__dirname, "tray.png")));
      tray.setToolTip("Kesim: kendini geliştiriyor");
      tray.setContextMenu(Menu.buildFromTemplate([
        { label: "Kesim'i aç", click: () => ctx.showWindow() },
        { label: "Şimdi geliştirme turu çalıştır", click: () => { engine.runCycle({ force: true }); } },
        { type: "separator" },
        { label: "Çıkış", click: () => { quitting = true; app.quit(); } },
      ]));
      tray.on("click", () => ctx.showWindow());
    } catch (e) { console.error("[selfedit] tepsi simgesi oluşturulamadı:", e); tray = null; }
  } else if (!on && tray) { tray.destroy(); tray = null; }
}

function init(c) {
  ctx = c;
  const { app, ipcMain, safeStorage } = c;
  const dir = path.join(app.getPath("userData"), "selfedit");
  const secrets = makeSecrets(dir, safeStorage);
  engine = new Engine({ dir, check: runCheck, secrets });

  const trusted = (e) => { const w = c.getWindow(); return !!w && !w.isDestroyed() && e.sender === w.webContents; };
  const handle = (ch, fn) => ipcMain.handle(ch, async (e, ...a) => {
    if (!trusted(e)) return { ok: false, error: "yetkisiz" };
    try { const r = await fn(...a); return r && typeof r === "object" && "ok" in r ? r : { ok: true, ...(r === undefined ? {} : { data: r }) }; }
    catch (err) { return { ok: false, error: String(err && err.message || err) }; }
  });
  handle("se:state", () => engine.state());
  handle("se:run", (offline) => engine.runCycle({ force: true, offline: !!offline }));
  handle("se:apply", (id) => engine.apply(String(id)));
  handle("se:reject", (id) => engine.reject(String(id)));
  handle("se:rollback", (id) => engine.rollback(String(id)));
  handle("se:wish", (text) => { if (!engine.wish(String(text))) throw new Error("Dilek boş olamaz."); });
  handle("se:log", (ev, data) => { engine.log(String(ev), data); });
  handle("se:builtins", (list) => { engine.registerBuiltins(list); });
  handle("se:config", (k, v) => { const cfg = engine.setConfig(String(k), v); if (k === "background") applyBackground(); return cfg; });
  handle("se:set-key", async (key) => { await secrets.set(String(key).trim()); engine.emit("change"); });
  handle("se:clear-key", async () => { await secrets.clear(); engine.emit("change"); });

  let pending = false;
  engine.on("change", () => {   // arayüze "durum değişti" bildirimi; art arda gelenleri birleştir
    if (pending) return; pending = true;
    setTimeout(() => { pending = false; const w = c.getWindow(); if (w && !w.isDestroyed()) w.webContents.send("se:changed"); }, 150);
  });
  app.on("before-quit", () => { quitting = true; engine.stop(); });
  applyBackground();
  engine.start();
}

module.exports = {
  init,
  config: () => (engine ? engine.config() : { background: false }),
  /** Pencere kapatılırken tepsiye gizlenmeli mi? */
  shouldHideOnClose: () => !!(engine && engine.config().background && tray && !quitting),
  keepAlive: () => !!(engine && engine.config().background && tray),
};
