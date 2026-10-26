/* Kesim SelfEdit: bir tarifin GERÇEKTEN çalıştığını sınayan işlevsel kontrol.
 * Gizli bir pencerede (gerçek Chromium canvas) veya testlerde node-canvas ile çalışır. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./recipe-core.js"), require("./recipe-runtime.js"));
  else root.SECheck = factory(root.SERecipe, root.SERuntime);
})(typeof self !== "undefined" ? self : this, function (Core, Runtime) {
  "use strict";

  function scene(createCanvas, w, h) {
    const cv = createCanvas(w, h), g = cv.getContext("2d");
    const gr = g.createLinearGradient(0, 0, w, h);
    gr.addColorStop(0, "#2b5cff"); gr.addColorStop(0.5, "#d63fa6"); gr.addColorStop(1, "#ffb347");
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(w * 0.34, h * 0.5, h * 0.22, 0, 7); g.fill();
    g.fillStyle = "rgba(0,0,0,.35)"; g.fillRect(w * 0.58, h * 0.2, w * 0.3, h * 0.55);
    g.fillStyle = "#10b981"; g.fillRect(w * 0.05, h * 0.78, w * 0.4, h * 0.12);
    return cv;
  }
  function pixels(cv, w, h) { return cv.getContext("2d").getImageData(0, 0, w, h).data; }
  function meanDiff(a, b) { let s = 0, n = 0; for (let k = 0; k < a.length; k += 4) { s += Math.abs(a[k] - b[k]) + Math.abs(a[k + 1] - b[k + 1]) + Math.abs(a[k + 2] - b[k + 2]); n += 3; } return s / n; }
  function meanLum(a) { let s = 0, n = 0; for (let k = 0; k < a.length; k += 4) { s += 0.2126 * a[k] + 0.7152 * a[k + 1] + 0.0722 * a[k + 2]; n++; } return s / n; }
  function applyOnce(recipe, createCanvas, env, w, h, o, base) {
    const cv = createCanvas(w, h), g = cv.getContext("2d");
    g.drawImage(base, 0, 0);
    Runtime.run(recipe, g, w, h, o, env);
    return pixels(cv, w, h);
  }

  /** Döner: {ok, steps:[{step,ok,detail}], ms}. now = performans ölçer (ms). */
  function check(recipe, createCanvas, now) {
    const steps = [], t0 = now();
    const add = (step, ok, detail) => { steps.push({ step, ok, detail }); return ok; };
    const v = Core.validate(recipe);
    if (!add("şema", v.ok, v.ok ? "geçerli" : v.errors.join("; "))) return { ok: false, steps, ms: now() - t0 };
    const r = v.recipe, env = Runtime.makeEnv(createCanvas);
    try {
      const w = 160, h = 90, base = scene(createCanvas, w, h), basePx = pixels(base, w, h);
      const samples = [{ lt: 0.05, p: 0.0 }, { lt: 0.2, p: 0.15 }, { lt: 0.35, p: 0.35 }, { lt: 0.6, p: 0.6 }, { lt: 0.9, p: 0.85 }, { lt: 1.4, p: 1.0 }];
      let maxDiff = 0, minLum = 255;
      for (const s of samples) {
        const px = applyOnce(r, createCanvas, env, w, h, { lt: s.lt, p: s.p, i: r.di, sp: 1, tt: s.lt }, base);
        maxDiff = Math.max(maxDiff, meanDiff(basePx, px));
        minLum = Math.min(minLum, meanLum(px));
      }
      add("çalışma", true, "tüm örneklerde hatasız çizildi");
      add("görünür etki", maxDiff >= 2, `ortalama değişim ${maxDiff.toFixed(1)}/255 (en az 2 gerekir)`);
      add("görüntüyü karartmıyor", minLum >= 12, `en düşük parlaklık ${minLum.toFixed(0)}/255 (en az 12 gerekir)`);

      // yoğunluk ölçeklenmeli: düşük i ile yüksek i farklı sonuç vermeli
      let scale = 0;
      for (const s of samples) {   // zamana bağlı (yanıp sönen) efektler bazı anlarda kapalı olabilir: en iyi ana bak
        const lo = applyOnce(r, createCanvas, env, w, h, { lt: s.lt, p: s.p, i: 0.15, sp: 1, tt: s.lt }, base);
        const hi = applyOnce(r, createCanvas, env, w, h, { lt: s.lt, p: s.p, i: 1.2, sp: 1, tt: s.lt }, base);
        scale = Math.max(scale, meanDiff(lo, hi));
      }
      if (r.ops.every((o) => o.op === "mirror")) add("yoğunluk ayarı işe yarıyor", true, "yapısal efekt (ayna), yoğunluktan bağımsız");
      else add("yoğunluk ayarı işe yarıyor", scale >= 0.3, `düşük/yüksek yoğunluk farkı ${scale.toFixed(2)}`);

      // başarım: 854x480'de kare başına süre
      const W = 854, H = 480, big = scene(createCanvas, W, H), cv = createCanvas(W, H), g = cv.getContext("2d");
      const times = [];
      for (let k = 0; k < 6; k++) {
        g.drawImage(big, 0, 0);
        const a = now(); Runtime.run(r, g, W, H, { lt: 0.3 + k * 0.1, p: 0.4, i: r.di, sp: 1, tt: 0.3 + k * 0.1 }, env); g.getImageData(0, 0, 1, 1);
        times.push(now() - a);
      }
      const avg = times.slice(1).reduce((x, y) => x + y, 0) / (times.length - 1);
      add("hız", avg <= 90, `kare başına ${avg.toFixed(1)} ms (en çok 90)`);
    } catch (e) {
      add("çalışma", false, `${e && e.name}: ${e && e.message}`);
    }
    return { ok: steps.every((s) => s.ok), steps, ms: Math.round(now() - t0) };
  }

  return { check, scene };
});
