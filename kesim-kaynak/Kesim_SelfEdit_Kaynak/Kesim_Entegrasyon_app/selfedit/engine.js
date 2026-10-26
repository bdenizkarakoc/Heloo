/* Kesim SelfEdit: kendini geliştirme motoru (Electron ana sürecinde çalışır; Electron'a bağımlı değildir).
 * Döngü: kullanım özeti -> öneri (şablon/Claude) -> şema + işlevsel kontrol -> (onay) -> uygula -> geri alınabilir. */
"use strict";
const fs = require("fs");
const path = require("path");
const { EventEmitter } = require("events");
const Core = require("./recipe-core.js");
const Proposers = require("./proposers.js");

const DEFAULTS = { mode: "approve", interval_minutes: 60, max_per_day: 4, max_pending: 5, model: "claude-sonnet-5-5", background: false };
const MODES = ["approve", "auto"];
const EVENTS = new Set(["effect_used", "export_ok", "wish"]);
const DAY = 86400000;

class Engine extends EventEmitter {
  /** opts: {dir, check(recipe)->Promise<{ok,steps}>, secrets:{get,set,clear,has}, fetchImpl, now} */
  constructor(opts) {
    super();
    this.dir = opts.dir;
    this.check = opts.check;
    this.secrets = opts.secrets || { get: async () => null, set: async () => {}, clear: async () => {}, has: () => false };
    this.fetchImpl = opts.fetchImpl || (typeof fetch === "function" ? fetch : null);
    this.now = opts.now || Date.now;
    this.builtins = [];
    this.running = false;
    this.timer = null;
    this.status = { running: false, lastRun: null, lastResult: null, nextRun: null, scheduler: false };
    for (const d of ["", "proposals", "plugins"]) fs.mkdirSync(path.join(this.dir, d), { recursive: true });
  }

  /* ---------- depolama ---------- */
  _p(...a) { return path.join(this.dir, ...a); }
  _readJson(file, fallback) { try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return fallback; } }
  _writeJson(file, obj) { fs.writeFileSync(file + ".tmp", JSON.stringify(obj, null, 2), "utf8"); fs.renameSync(file + ".tmp", file); }
  _changelog(entry) { try { fs.appendFileSync(this._p("changelog.jsonl"), JSON.stringify({ ts: this.now(), ...entry }) + "\n"); } catch { /* günlük yazılamazsa devam */ } }

  config() { return { ...DEFAULTS, ...this._readJson(this._p("config.json"), {}) }; }
  setConfig(key, value) {
    if (!Object.prototype.hasOwnProperty.call(DEFAULTS, key)) throw new Error(`Bilinmeyen ayar: ${key}`);
    if (key === "mode" && !MODES.includes(value)) throw new Error("mode approve veya auto olmalı");
    if (typeof DEFAULTS[key] === "number") { value = Math.round(Number(value)); if (!(value >= 1 && value <= 100000)) throw new Error(`${key} geçersiz`); }
    if (typeof DEFAULTS[key] === "boolean") value = !!value;
    if (key === "model" && !/^[a-z0-9.\-]{3,60}$/.test(String(value))) throw new Error("model adı geçersiz");
    const cfg = this.config(); cfg[key] = value; this._writeJson(this._p("config.json"), cfg);
    if (key === "interval_minutes" && this.status.scheduler) this._schedule();
    this.emit("change"); return cfg;
  }

  /* ---------- kullanım kaydı (yalnızca yerelde) ---------- */
  log(event, data) {
    if (!EVENTS.has(event) || !data || typeof data !== "object") return false;
    const rec = { ts: this.now(), event };
    if (event === "effect_used") { rec.type = String(data.type || "").slice(0, 60); rec.group = String(data.group || "").slice(0, 30); }
    else if (event === "export_ok") rec.fx = (Array.isArray(data.fx) ? data.fx : []).slice(0, 40).map((x) => String(x).slice(0, 60));
    else if (event === "wish") { rec.text = String(data.text || "").trim().slice(0, 200); if (!rec.text) return false; }
    const f = this._p("telemetry.jsonl");
    try {
      fs.appendFileSync(f, JSON.stringify(rec) + "\n");
      if (fs.statSync(f).size > 300000) { const lines = fs.readFileSync(f, "utf8").trim().split("\n"); fs.writeFileSync(f, lines.slice(-1000).join("\n") + "\n"); }
    } catch { return false; }
    if (event === "wish") this.emit("change");
    return true;
  }
  _telemetry(days = 60) {
    const cutoff = this.now() - days * DAY, out = [];
    try { for (const l of fs.readFileSync(this._p("telemetry.jsonl"), "utf8").split("\n")) { if (!l) continue; try { const r = JSON.parse(l); if (r.ts >= cutoff) out.push(r); } catch { /* bozuk satırı atla */ } } } catch { /* dosya yok */ }
    return out;
  }
  summary() {
    const ev = this._telemetry(), cnt = (arr) => arr.reduce((m, k) => (k ? ((m[k] = (m[k] || 0) + 1), m) : m), {});
    const top = (o, n) => Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n));
    return {
      effects_used: top(cnt(ev.filter((e) => e.event === "effect_used").map((e) => e.type)), 10),
      groups_used: top(cnt(ev.filter((e) => e.event === "effect_used").map((e) => e.group)), 6),
      exports_ok: ev.filter((e) => e.event === "export_ok").length,
      wishes: ev.filter((e) => e.event === "wish").map((e) => e.text).slice(-10),
    };
  }
  wish(text) { return this.log("wish", { text }); }
  registerBuiltins(list) {
    this.builtins = (Array.isArray(list) ? list : []).slice(0, 300).filter((b) => b && typeof b.id === "string").map((b) => ({ id: b.id.slice(0, 60), name: String(b.name || b.id).slice(0, 60) }));
  }

  /* ---------- öneriler ve eklentiler ---------- */
  proposals() {
    let files = []; try { files = fs.readdirSync(this._p("proposals")).filter((f) => f.endsWith(".json")); } catch { /* boş */ }
    return files.map((f) => this._readJson(this._p("proposals", f), null)).filter(Boolean).sort((a, b) => a.created - b.created);
  }
  proposal(id) { const p = this._readJson(this._p("proposals", `${String(id).replace(/[^\w\-]/g, "")}.json`), null); if (!p) throw new Error("Öneri bulunamadı"); return p; }
  _saveProposal(p) { this._writeJson(this._p("proposals", `${p.id}.json`), p); }

  plugins() {
    let files = []; try { files = fs.readdirSync(this._p("plugins")).filter((f) => f.endsWith(".json")); } catch { /* boş */ }
    const out = [];
    for (const f of files) {
      const rec = this._readJson(this._p("plugins", f), null);
      if (!rec || !rec.recipe) continue;
      const v = Core.validate(rec.recipe);          // dosya elle bozulmuş olabilir: yüklerken yeniden doğrula
      if (v.ok) out.push({ recipe: v.recipe, proposal: rec.proposal, applied_at: rec.applied_at });
    }
    return out.sort((a, b) => (a.applied_at || 0) - (b.applied_at || 0));
  }
  _takenIds() {
    return new Set([...this.plugins().map((p) => p.recipe.id), ...this.proposals().map((p) => p.recipe && p.recipe.id), ...this.builtins.map((b) => b.id)].filter(Boolean));
  }
  _takenNames() { return new Set([...this.plugins().map((p) => p.recipe.name), ...this.proposals().map((p) => p.recipe && p.recipe.name), ...this.builtins.map((b) => b.name)].filter(Boolean)); }

  /* ---------- tek bir geliştirme turu ---------- */
  async runCycle({ force = false, offline = false } = {}) {
    if (this.running) return { result: "busy", reason: "bir tur zaten çalışıyor" };
    this.running = true; this.status.running = true; this.emit("change");
    let res;
    try { res = await this._cycle({ force, offline }); }
    catch (e) { res = { result: "error", reason: `${e && e.name}: ${e && e.message}` }; }
    finally { this.running = false; this.status.running = false; }
    this.status.lastRun = this.now(); this.status.lastResult = res;
    this._changelog({ event: "cycle", result: res.result, id: res.id });
    this.emit("change"); return res;
  }

  async _cycle({ force, offline }) {
    const cfg = this.config(), proposals = this.proposals();
    if (!force) {
      if (proposals.filter((p) => p.created >= this.now() - DAY).length >= cfg.max_per_day) return { result: "skipped", reason: "günlük öneri sınırına ulaşıldı" };
      if (proposals.filter((p) => p.status === "validated").length >= cfg.max_pending) return { result: "skipped", reason: "onay bekleyen öneri sayısı sınırda" };
    }
    const summary = this.summary(), takenIds = this._takenIds(), takenNames = this._takenNames();
    let prop = null, note = "";
    const apiKey = offline ? null : await this.secrets.get();
    if (apiKey && this.fetchImpl) {
      try {
        const r = await Proposers.llmPropose({ apiKey, model: cfg.model, summary, builtins: this.builtins, takenIds, fetchImpl: this.fetchImpl });
        if (r.failed) note = `Claude geçerli tarif üretemedi (${(r.errors || []).join("; ").slice(0, 200)}); şablonla devam edildi.`;
        else prop = r;
      } catch (e) { note = `Claude'a ulaşılamadı (${e && e.message}); şablonla devam edildi.`; }
    }
    if (!prop) prop = Proposers.offlinePropose({ summary, takenIds, takenNames });
    if (!prop) return { result: "nothing", reason: "yeni öneri kalmadı", note };

    // aynı etkiyi üreten bir tarif zaten var mı?
    const fp = Core.fingerprint(prop.recipe);
    if ([...this.plugins().map((p) => p.recipe), ...proposals.map((p) => p.recipe).filter(Boolean)].some((r) => Core.fingerprint(r) === fp))
      return { result: "skipped", reason: "aynı etkiyi üreten bir tarif zaten var", note };

    const report = await this.check(prop.recipe);
    const rec = { id: new Date(this.now()).toISOString().replace(/[-:T]/g, "").slice(0, 14) + "-" + prop.recipe.id, created: this.now(), title: prop.title, rationale: prop.rationale, source: prop.source, recipe: prop.recipe, status: report.ok ? "validated" : "failed", validation: report };
    this._saveProposal(rec);
    this._changelog({ event: "proposal", id: rec.id, status: rec.status, source: rec.source });
    const out = { result: rec.status, id: rec.id, effect: rec.recipe.name, source: rec.source, note };
    if (rec.status === "validated" && cfg.mode === "auto") {
      const a = await this.apply(rec.id);
      out.result = a.ok ? "applied" : "failed"; out.detail = a.detail;
    }
    return out;
  }

  async apply(id) {
    const p = this.proposal(id);
    if (p.status !== "validated") return { ok: false, detail: `durum '${p.status}'; yalnızca doğrulanmış öneriler uygulanır` };
    const report = await this.check(p.recipe);   // uygulama anında yeniden doğrula
    if (!report.ok) { p.status = "failed"; p.validation = report; this._saveProposal(p); this.emit("change"); return { ok: false, detail: "yeniden doğrulama başarısız" }; }
    if (this.plugins().some((x) => x.recipe.id === p.recipe.id)) return { ok: false, detail: "bu id ile bir efekt zaten kurulu" };
    this._writeJson(this._p("plugins", `${p.recipe.id}.json`), { recipe: p.recipe, proposal: p.id, applied_at: this.now() });
    p.status = "applied"; p.applied_at = this.now(); this._saveProposal(p);
    this._changelog({ event: "applied", id: p.id, effect: p.recipe.id });
    this.emit("change"); this.emit("plugins");
    return { ok: true, detail: `'${p.recipe.name}' efekt listesine eklendi` };
  }
  reject(id) {
    const p = this.proposal(id);
    if (p.status === "applied") return { ok: false, detail: "uygulanmış öneri reddedilemez; geri al" };
    p.status = "rejected"; this._saveProposal(p); this._changelog({ event: "rejected", id: p.id }); this.emit("change");
    return { ok: true, detail: "reddedildi" };
  }
  rollback(id) {
    const p = this.proposal(id);
    if (p.status !== "applied") return { ok: false, detail: "yalnızca uygulanmış öneriler geri alınır" };
    try { fs.unlinkSync(this._p("plugins", `${p.recipe.id}.json`)); } catch { /* zaten yok */ }
    p.status = "rolled_back"; this._saveProposal(p); this._changelog({ event: "rollback", id: p.id });
    this.emit("change"); this.emit("plugins");
    return { ok: true, detail: `'${p.recipe.name}' kaldırıldı` };
  }

  /* ---------- zamanlayıcı ---------- */
  start({ firstDelayMs = 90000 } = {}) { this.status.scheduler = true; this._schedule(firstDelayMs); this.emit("change"); }
  stop() { this.status.scheduler = false; this.status.nextRun = null; if (this.timer) clearTimeout(this.timer); this.timer = null; this.emit("change"); }
  _schedule(delay) {
    if (this.timer) clearTimeout(this.timer);
    const ms = delay != null ? delay : this.config().interval_minutes * 60000;
    this.status.nextRun = this.now() + ms;
    this.timer = setTimeout(async () => { await this.runCycle(); if (this.status.scheduler) this._schedule(); }, ms);
  }

  /* ---------- arayüz için durum ---------- */
  state() {
    return {
      config: this.config(), status: { ...this.status }, hasKey: !!(this.secrets.has && this.secrets.has()),
      summary: this.summary(),
      plugins: this.plugins(),
      proposals: this.proposals().slice(-30).reverse(),
    };
  }
}

module.exports = { Engine, DEFAULTS, MODES };
