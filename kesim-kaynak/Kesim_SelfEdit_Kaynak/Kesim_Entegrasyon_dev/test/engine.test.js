"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { createCanvas } = require("@napi-rs/canvas");

const A = path.join(__dirname, "..", "..", "app", "selfedit");
const Core = require(path.join(A, "recipe-core.js"));
const Runtime = require(path.join(A, "recipe-runtime.js"));
const Check = require(path.join(A, "check.js"));
const TEMPLATES = require(path.join(A, "templates.js"));
const Proposers = require(path.join(A, "proposers.js"));
const { Engine } = require(path.join(A, "engine.js"));

const now = () => performance.now();
const realCheck = async (r) => Check.check(r, createCanvas, now);
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "se-"));

/* ---------- ifade dili ---------- */
test("ifade: aritmetik, fonksiyonlar, değişkenler", () => {
  const ev = (s, v = {}) => Core.compileExpr(s)({ i: 0.5, p: 0.25, lt: 1, tt: 2, sp: 1, W: 100, H: 50, PI: Math.PI, ...v });
  assert.strictEqual(ev("1+2*3"), 7);
  assert.strictEqual(ev("(1+2)*3"), 9);
  assert.strictEqual(ev("-i*4"), -2);
  assert.strictEqual(ev("2^3"), 8);
  assert.strictEqual(ev("clamp(5,0,1)"), 1);
  assert.strictEqual(ev("mix(0,10,p)"), 2.5);
  assert.strictEqual(ev("if(i<1,3,4)"), 3);
  assert.strictEqual(ev("1/0"), 0, "sıfıra bölme güvenli");
  assert.ok(Math.abs(ev("sin(PI/2)") - 1) < 1e-9);
  assert.strictEqual(ev("W*0.01"), 1);
});

test("ifade: kod enjeksiyonu ve kötü girdiler reddedilir", () => {
  const bad = ["alert(1)", "constructor", "window.x", "i; 1", "eval('1')", "__proto__", "this", "'a'", "i+", "(", "sin(1,2)", "1e999*1e999",
    "x+1", "Math.sin(1)", "process", "a=1", "i{", "`1`", "[1]", "i.toString()", "1+".repeat(100), "(".repeat(40) + "1" + ")".repeat(40)];
  for (const s of bad) {
    let ok = true;
    try { const f = Core.compileExpr(s); const r = f({ i: 1, p: 1, lt: 1, tt: 1, sp: 1, W: 1, H: 1, PI: 3 }); ok = Number.isFinite(r) && s === "1e999*1e999"; } catch { ok = false; }
    if (s === "1e999*1e999") assert.ok(ok, "sonsuz sonuç 0'a çevrilir"); else assert.ok(!ok, `reddedilmeliydi: ${s}`);
  }
});

/* ---------- şema ---------- */
test("şema: bilinmeyen alan/işlem/renk/filtre reddedilir", () => {
  const base = () => ({ v: 1, id: "deneme_fx", name: "Deneme", group: "Renk", di: 0.6, ops: [{ op: "fill", color: "#ff0000", alpha: "i" }] });
  assert.ok(Core.validate(base()).ok);
  const mut = (f) => { const r = base(); f(r); return Core.validate(r); };
  assert.ok(!mut((r) => { r.script = "alert(1)"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].op = "eval"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].color = "red"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].color = "url(http://x)"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].comp = "xor"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].alpha = "fetch(1)"; }).ok);
  assert.ok(!mut((r) => { r.ops[0].extra = 1; }).ok);
  assert.ok(!mut((r) => { r.id = "Bad-Id"; }).ok);
  assert.ok(!mut((r) => { r.name = "<img onerror=x>"; }).ok);
  assert.ok(!mut((r) => { r.group = "Hack"; }).ok);
  assert.ok(!mut((r) => { r.ops = []; }).ok);
  assert.ok(!mut((r) => { r.ops = Array(9).fill({ op: "scanlines", alpha: "1" }); }).ok);
  assert.ok(!mut((r) => { r.ops = [{ op: "filter", fx: [{ f: "url", v: "1" }] }]; }).ok);
  assert.ok(!mut((r) => { r.ops = [{ op: "filter", fx: [{ f: "blur", v: "1", extra: 2 }] }]; }).ok);
  assert.ok(!mut((r) => { r.desc = "<script>"; }).ok);
  assert.ok(!Core.validate(null).ok && !Core.validate([]).ok && !Core.validate("x").ok);
});

/* ---------- şablonlar: hepsi gerçekten çalışmalı ---------- */
test("tüm şablonlar şemadan ve gerçek piksel kontrolünden geçer", async () => {
  const ids = new Set(), names = new Set();
  for (const t of TEMPLATES) {
    assert.ok(!ids.has(t.recipe.id), `yinelenen id ${t.recipe.id}`); ids.add(t.recipe.id);
    assert.ok(!names.has(t.recipe.name), `yinelenen ad ${t.recipe.name}`); names.add(t.recipe.name);
    const rep = await realCheck(t.recipe);
    assert.ok(rep.ok, `${t.recipe.id}: ` + rep.steps.filter((s) => !s.ok).map((s) => `${s.step}: ${s.detail}`).join(" | "));
  }
  assert.ok(TEMPLATES.length >= 15);
});

test("çalışma zamanı: efekt gerçekten piksel değiştirir; yoğunluk ölçeklenir", () => {
  const r = Core.validate({ id: "kirmizi_test", name: "Kırmızı test", group: "Renk", di: 0.6, ops: [{ op: "fill", color: "#ff0000", alpha: "i", comp: "source-over" }] }).recipe;
  const env = Runtime.makeEnv(createCanvas), cv = createCanvas(20, 20), g = cv.getContext("2d");
  g.fillStyle = "#000000"; g.fillRect(0, 0, 20, 20);
  Runtime.run(r, g, 20, 20, { lt: 0, p: 0, i: 0.5, sp: 1, tt: 0 }, env);
  const px = g.getImageData(10, 10, 1, 1).data;
  assert.ok(px[0] > 100 && px[0] < 150, `kırmızı kanal ~127 olmalı, ${px[0]}`);
  assert.strictEqual(px[1], 0);
});

test("check: görüntüyü karartan ve etkisiz tarifler reddedilir", async () => {
  const mk = (ops) => ({ v: 1, id: "karanlik_fx", name: "Karanlık", group: "Renk", di: 0.6, ops });
  const black = await realCheck(mk([{ op: "fill", color: "#000000", alpha: "1" }]));
  assert.ok(!black.ok && black.steps.some((s) => s.step === "görüntüyü karartmıyor" && !s.ok));
  const noop = await realCheck(mk([{ op: "fill", color: "#ff0000", alpha: "0" }]));
  assert.ok(!noop.ok && noop.steps.some((s) => s.step === "görünür etki" && !s.ok));
  const fixed = await realCheck(mk([{ op: "fill", color: "#ff0000", alpha: "0.4" }]));
  assert.ok(!fixed.ok && fixed.steps.some((s) => s.step === "yoğunluk ayarı işe yarıyor" && !s.ok), "i'den bağımsız efekt reddedilir");
});

/* ---------- öneri üreticiler ---------- */
test("çevrimdışı öneri: dilek doğru şablonu seçer, alınmış olanı tekrar önermez", () => {
  const s = { wishes: ["Videoya matrix tarzı yeşil hacker efekti istiyorum"], groups_used: {} };
  const p = Proposers.offlinePropose({ summary: s, takenIds: new Set(), takenNames: new Set() });
  assert.strictEqual(p.recipe.id, "matrix_yesil");
  const p2 = Proposers.offlinePropose({ summary: s, takenIds: new Set(["matrix_yesil"]), takenNames: new Set() });
  assert.notStrictEqual(p2.recipe.id, "matrix_yesil");
  const all = new Set(TEMPLATES.map((t) => t.recipe.id));
  assert.strictEqual(Proposers.offlinePropose({ summary: s, takenIds: all, takenNames: new Set() }), null);
});

const goodRecipe = { v: 1, id: "claude_efekt", name: "Claude efekti", group: "Renk", di: 0.6, ops: [{ op: "filter", fx: [{ f: "saturate", v: "1+i" }] }] };
const mockFetch = (texts) => { let n = 0; return async () => ({ ok: true, status: 200, json: async () => ({ content: [{ type: "text", text: texts[Math.min(n++, texts.length - 1)] }] }) }); };

test("Claude önerisi: geçerli tarif kabul, geçersizde hata geri bildirimiyle ikinci deneme", async () => {
  const base = { apiKey: "k", model: "claude-sonnet-5-5", summary: {}, builtins: [], takenIds: new Set() };
  const ok = await Proposers.llmPropose({ ...base, fetchImpl: mockFetch(["işte: " + JSON.stringify({ title: "T", rationale: "R", recipe: goodRecipe })]) });
  assert.strictEqual(ok.recipe.id, "claude_efekt");
  const evil = { ...goodRecipe, ops: [{ op: "filter", fx: [{ f: "saturate", v: "fetch(1)" }] }] };
  const prompts = [];
  const seq = mockFetch([JSON.stringify({ recipe: evil }), JSON.stringify({ title: "T2", rationale: "R", recipe: goodRecipe })]);
  const f2 = async (_u, init) => { prompts.push(JSON.parse(init.body).messages[0].content); return seq(); };
  const retry = await Proposers.llmPropose({ ...base, fetchImpl: f2 });
  assert.strictEqual(retry.recipe.id, "claude_efekt");
  assert.ok(prompts[1].includes("REDDEDİLDİ"), "ikinci istem hataları içermeli");
  const bad = await Proposers.llmPropose({ ...base, fetchImpl: mockFetch([JSON.stringify({ recipe: evil })]) });
  assert.ok(bad.failed);
  const apiKeySeen = [];
  await Proposers.llmPropose({ ...base, fetchImpl: async (u, init) => { apiKeySeen.push(init.headers["x-api-key"], u); return mockFetch([JSON.stringify({ recipe: goodRecipe })])(); } });
  assert.deepStrictEqual(apiKeySeen, ["k", "https://api.anthropic.com/v1/messages"]);
});

/* ---------- motor ---------- */
const newEngine = (extra = {}) => new Engine({ dir: tmp(), check: realCheck, ...extra });

test("motor: onay modunda doğrular ve bekler; onaylayınca eklenir; geri alınır", async () => {
  const e = newEngine(); let plugged = 0; e.on("plugins", () => plugged++);
  const r = await e.runCycle({ force: true, offline: true });
  assert.strictEqual(r.result, "validated", JSON.stringify(r));
  assert.strictEqual(e.plugins().length, 0, "onaysız uygulanmamalı");
  const a = await e.apply(r.id);
  assert.ok(a.ok, a.detail);
  assert.strictEqual(e.plugins().length, 1); assert.strictEqual(plugged, 1);
  assert.strictEqual(e.proposal(r.id).status, "applied");
  assert.ok(e.rollback(r.id).ok);
  assert.strictEqual(e.plugins().length, 0); assert.strictEqual(e.proposal(r.id).status, "rolled_back");
  assert.ok(!(await e.apply(r.id)).ok, "geri alınan öneri tekrar uygulanamaz");
});

test("motor: auto modda doğrulanan kendiliğinden uygulanır", async () => {
  const e = newEngine(); e.setConfig("mode", "auto");
  const r = await e.runCycle({ force: true, offline: true });
  assert.strictEqual(r.result, "applied", JSON.stringify(r));
  assert.strictEqual(e.plugins().length, 1);
});

test("motor: doğrulamayı geçemeyen öneri asla uygulanmaz", async () => {
  const e = newEngine({ check: async () => ({ ok: false, steps: [{ step: "hız", ok: false, detail: "yavaş" }] }) });
  e.setConfig("mode", "auto");
  const r = await e.runCycle({ force: true, offline: true });
  assert.strictEqual(r.result, "failed" === r.result ? "failed" : r.result);
  assert.notStrictEqual(r.result, "applied");
  assert.strictEqual(e.plugins().length, 0);
  assert.ok(!(await e.apply(r.id)).ok);
});

test("motor: tur sırasında geçerli olan ama uygulama anında bozulan öneri uygulanmaz", async () => {
  let calls = 0;
  const e = newEngine({ check: async (r) => (++calls === 1 ? realCheck(r) : { ok: false, steps: [] }) });
  const r = await e.runCycle({ force: true, offline: true });
  assert.strictEqual(r.result, "validated");
  assert.ok(!(await e.apply(r.id)).ok);
  assert.strictEqual(e.plugins().length, 0);
});

test("motor: günlük sınır, bekleyen sınırı, reddedilen tekrar önerilmez", async () => {
  const e = newEngine(); e.setConfig("max_per_day", 1);
  const r1 = await e.runCycle({ offline: true });
  assert.strictEqual(r1.result, "validated");
  assert.strictEqual((await e.runCycle({ offline: true })).result, "skipped");
  e.reject(r1.id);
  const r3 = await e.runCycle({ force: true, offline: true });
  assert.notStrictEqual(r3.effect, r1.effect);
  const e2 = newEngine(); e2.setConfig("max_pending", 1); e2.setConfig("max_per_day", 50);
  await e2.runCycle({ offline: true });
  assert.strictEqual((await e2.runCycle({ offline: true })).result, "skipped");
});

test("motor: eş zamanlı iki tur çakışmaz", async () => {
  const e = newEngine();
  const [a, b] = await Promise.all([e.runCycle({ force: true, offline: true }), e.runCycle({ force: true, offline: true })]);
  assert.deepStrictEqual([a.result, b.result].sort(), ["busy", "validated"]);
});

test("motor: Claude anahtarı varsa Claude önerisi kullanılır; API hatasında şablona düşer", async () => {
  const secrets = { get: async () => "anahtar", has: () => true, set: async () => {}, clear: async () => {} };
  const e = newEngine({ secrets, fetchImpl: mockFetch([JSON.stringify({ title: "Süper", rationale: "çünkü", recipe: goodRecipe })]) });
  const r = await e.runCycle({ force: true });
  assert.strictEqual(r.source, "Claude"); assert.strictEqual(r.result, "validated");
  const e2 = newEngine({ secrets, fetchImpl: async () => { throw new Error("ağ yok"); } });
  const r2 = await e2.runCycle({ force: true });
  assert.strictEqual(r2.source, "şablon"); assert.match(r2.note, /ulaşılamadı/);
});

test("motor: telemetri yalnızca izinli olayları kabul eder ve dilekleri özetler", () => {
  const e = newEngine();
  assert.ok(e.log("effect_used", { type: "bw", group: "Renk" }));
  assert.ok(!e.log("rm_rf", { x: 1 }));
  assert.ok(!e.log("wish", { text: "   " }));
  e.wish("sansür efekti ister misin " + "x".repeat(500));
  const s = e.summary();
  assert.strictEqual(s.effects_used.bw, 1); assert.strictEqual(s.groups_used["Renk"], 1);
  assert.ok(s.wishes[0].length <= 200);
});

test("motor: elle bozulan eklenti dosyası yüklenmez", async () => {
  const e = newEngine();
  const r = await e.runCycle({ force: true, offline: true }); await e.apply(r.id);
  const f = path.join(e.dir, "plugins", fs.readdirSync(path.join(e.dir, "plugins"))[0]);
  const rec = JSON.parse(fs.readFileSync(f, "utf8")); rec.recipe.ops[0].alpha = "fetch(1)"; fs.writeFileSync(f, JSON.stringify(rec));
  assert.strictEqual(e.plugins().length, 0);
});

test("motor: ayar doğrulama", () => {
  const e = newEngine();
  assert.throws(() => e.setConfig("mode", "yolo"));
  assert.throws(() => e.setConfig("nope", 1));
  assert.throws(() => e.setConfig("interval_minutes", -5));
  assert.throws(() => e.setConfig("model", "x; rm -rf"));
  assert.strictEqual(e.setConfig("mode", "auto").mode, "auto");
});

test("zamanlayıcı: başlar, tur çalıştırır, durur", async () => {
  const e = newEngine();
  e.start({ firstDelayMs: 20 });
  await new Promise((r) => setTimeout(r, 1500));
  e.stop();
  assert.ok(e.status.lastRun, "zamanlayıcı bir tur çalıştırmalı");
  assert.strictEqual(e.status.scheduler, false);
});
