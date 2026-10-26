/* Kesim ⇄ Reels Fabrikası istemcisi (Electron ana süreci; yalnızca Node çekirdek modülleri).
 * Fabrika yerel uygulamasıyla (http://127.0.0.1:8765) konuşur; kapalıysa penceresiz başlatır.
 * Ayarlar fabrika/config.json (kurulum betiği yazar): {"root": ".../reels-factory", "python": "pythonw", "port": 8765} */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

function loadConfig() {
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(path.join(__dirname, "config.json"), "utf8")); } catch { /* varsayılanlar */ }
  const home = os.homedir();
  const guesses = [cfg.root, path.join(home, "Documents", "Heloo", "reels-factory"),
    path.join(home, "OneDrive", "Documents", "Heloo", "reels-factory"), path.join(home, "OneDrive", "Belgeler", "Heloo", "reels-factory")];
  const root = guesses.find((p) => p && fs.existsSync(path.join(p, "app", "server.py"))) || cfg.root || guesses[1];
  return { root, python: cfg.python || (process.platform === "win32" ? "pythonw" : "python3"), port: Number(cfg.port) || 8765 };
}

class Factory {
  constructor(cfg = loadConfig()) { this.cfg = cfg; this.starting = null; }

  request(method, p, { body, json, stream, length, timeout = 60000, raw = false } = {}) {
    return new Promise((resolve, reject) => {
      const headers = {};
      let payload = null;
      if (json !== undefined) { payload = Buffer.from(JSON.stringify(json)); headers["Content-Type"] = "application/json"; }
      else if (body) payload = Buffer.isBuffer(body) ? body : Buffer.from(body);
      if (payload) headers["Content-Length"] = payload.length;
      if (stream) headers["Content-Length"] = length;
      const req = http.request({ host: "127.0.0.1", port: this.cfg.port, path: p, method, headers }, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const buf = Buffer.concat(chunks);
          if (raw) return res.statusCode < 400 ? resolve(buf) : reject(new Error(`HTTP ${res.statusCode}`));
          let data = {};
          try { data = buf.length ? JSON.parse(buf.toString("utf8")) : {}; } catch { return reject(new Error(`geçersiz yanıt (HTTP ${res.statusCode})`)); }
          if (res.statusCode >= 400 || (data && data.error)) return reject(new Error((data && data.error) || `HTTP ${res.statusCode}`));
          resolve(data);
        });
      });
      req.setTimeout(timeout, () => req.destroy(new Error("fabrika yanıt vermedi (zaman aşımı)")));
      req.on("error", reject);
      if (stream) { stream.on("error", (e) => req.destroy(e)); stream.pipe(req); }
      else { if (payload) req.write(payload); req.end(); }
    });
  }

  async alive() { try { await this.request("GET", "/api/jobs", { timeout: 3000 }); return true; } catch { return false; } }

  /** Fabrika kapalıysa arka planda penceresiz başlatır ve hazır olmasını bekler. */
  async ensure() {
    if (await this.alive()) return true;
    if (!this.starting) {
      this.starting = (async () => {
        const server = path.join(this.cfg.root, "app", "server.py");
        if (!fs.existsSync(server)) throw new Error(`Reels Fabrikası bulunamadı: ${this.cfg.root}`);
        const child = spawn(this.cfg.python, [server, "--port", String(this.cfg.port)],
          { cwd: this.cfg.root, detached: true, stdio: "ignore", windowsHide: true });
        child.on("error", () => { /* aşağıdaki bekleme zaman aşımıyla bildirir */ });
        child.unref();
        for (let i = 0; i < 60; i++) { await new Promise((r) => setTimeout(r, 500)); if (await this.alive()) return true; }
        throw new Error("Reels Fabrikası başlatılamadı (python ve kurulum yolunu denetleyin)");
      })().finally(() => { this.starting = null; });
    }
    return this.starting;
  }

  async get(p) { await this.ensure(); return this.request("GET", p); }
  async post(p, json) { await this.ensure(); return this.request("POST", p, { json }); }

  /** Bilgisayardaki dosyayı fabrikaya yükler (akış; bellek kullanmaz). Fabrikadaki adını döndürür. */
  async uploadPath(file) {
    await this.ensure();
    const st = fs.statSync(file);
    const r = await this.request("PUT", "/api/studio/upload?name=" + encodeURIComponent(path.basename(file)),
      { stream: fs.createReadStream(file), length: st.size, timeout: 3600000 });
    return r.file;
  }

  /** Kesim'deki bir medyanın verisini (Blob → ArrayBuffer) yükler. */
  async uploadBuffer(name, data) {
    await this.ensure();
    const r = await this.request("PUT", "/api/studio/upload?name=" + encodeURIComponent(name || "medya.mp4"),
      { body: Buffer.from(data), timeout: 3600000 });
    return r.file;
  }

  /** Fabrika çıktısını indirir (output/... yolu). */
  async fetchFile(rel) {
    await this.ensure();
    const clean = String(rel).replace(/\\/g, "/").replace(/^\/+/, "");
    if (!clean.startsWith("output/") || clean.includes("..")) throw new Error("izinsiz yol");
    return this.request("GET", "/" + clean.split("/").map(encodeURIComponent).join("/"), { raw: true, timeout: 600000 });
  }

  /** Yan işin (altyazı, AI planı, ses) bitmesini bekler. */
  async waitResult(task, ms = 30 * 60000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const r = await this.request("GET", "/api/kesim/result/" + encodeURIComponent(task));
      if (r.status === "done") return r.result;
      if (r.status === "failed") throw new Error(r.error || "iş başarısız");
      if (r.status === "unknown") throw new Error("iş bulunamadı (fabrika yeniden başlamış olabilir)");
      await new Promise((res) => setTimeout(res, 1500));
    }
    throw new Error("zaman aşımı");
  }
}

module.exports = { Factory, loadConfig };
