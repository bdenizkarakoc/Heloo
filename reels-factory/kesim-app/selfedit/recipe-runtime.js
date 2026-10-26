/* Kesim SelfEdit: tarif yorumlayıcı. Doğrulanmış bir tarifi bir canvas 2D bağlamı üzerinde çalıştırır.
 * Kesim'in FXLIB imzasıyla uyumludur: run(tarif, ctx, W, H, {lt,p,i,sp,tt}, env). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./recipe-core.js"));
  else root.SERuntime = factory(root.SERecipe);
})(typeof self !== "undefined" ? self : this, function (Core) {
  "use strict";
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const compiled = new WeakMap();

  /** createCanvas(w,h) -> canvas  (tarayıcıda document.createElement, testlerde node-canvas) */
  function makeEnv(createCanvas) { return { createCanvas, scr: new Map(), noise: null, scan: null }; }

  function scratch(env, W, H, n) {
    const k = W + "x" + H + "x" + n;
    let s = env.scr.get(k);
    if (!s) {
      s = env.createCanvas(W, H); s._g = s.getContext("2d"); env.scr.set(k, s);
      if (env.scr.size > 14) env.scr.delete(env.scr.keys().next().value);
    }
    return s;
  }
  function snap(env, c, W, H, n) {
    const s = scratch(env, W, H, n || 0), g = s._g;
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "source-over"; g.globalAlpha = 1; g.filter = "none";
    g.clearRect(0, 0, W, H); g.drawImage(c.canvas, 0, 0, W, H);
    return s;
  }
  function noisePattern(env, c) {
    if (!env.noise) {
      const n = env.createCanvas(256, 256), g = n.getContext("2d"), d = g.createImageData(256, 256);
      for (let k = 0; k < d.data.length; k += 4) { const v = Math.random() * 255; d.data[k] = d.data[k + 1] = d.data[k + 2] = v; d.data[k + 3] = 255; }
      g.putImageData(d, 0, 0); env.noise = n;
    }
    return c.createPattern(env.noise, "repeat");
  }
  function scanPattern(env, c) {
    if (!env.scan) {
      const n = env.createCanvas(4, 4), g = n.getContext("2d");
      g.fillStyle = "rgba(0,0,0,.75)"; g.fillRect(0, 0, 4, 2); env.scan = n;
    }
    return c.createPattern(env.scan, "repeat");
  }
  const hs = (n) => { const h = Math.sin(n * 127.1 + 311.7) * 43758.5453; return h - Math.floor(h); };

  function setup(c, op, alpha) {
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.filter = "none"; c.globalCompositeOperation = op.comp; c.globalAlpha = clamp(alpha, 0, 1);
  }

  function runOp(op, c, W, H, v, env) {
    switch (op.op) {
      case "filter": {
        const s = snap(env, c, W, H, 0);
        const parts = op.fx.map((f) => {
          const [lo, hi, unit] = Core.FILTERS[f.f];
          return `${f.f}(${clamp(f.v(v), lo, hi).toFixed(4)}${unit})`;
        });
        setup(c, op, op.alpha(v)); c.filter = parts.join(" "); c.drawImage(s, 0, 0); break;
      }
      case "fill": setup(c, op, op.alpha(v)); c.fillStyle = op.raw.color; c.fillRect(0, 0, W, H); break;
      case "gradient": {
        const u = Math.hypot(W, H); let g;
        if (op.raw.kind === "radial") {
          const cx = op.cx(v) * W, cy = op.cy(v) * H, r0 = Math.max(0, op.r0(v)) * u;
          g = c.createRadialGradient(cx, cy, r0, cx, cy, Math.max(r0 + 0.5, op.r1(v) * u));
        } else {
          const a = op.angle(v) * Math.PI / 180, dx = Math.cos(a), dy = Math.sin(a);
          const L = (Math.abs(W * dx) + Math.abs(H * dy)) / 2;
          g = c.createLinearGradient(W / 2 - dx * L, H / 2 - dy * L, W / 2 + dx * L, H / 2 + dy * L);
        }
        for (const [pos, col] of op.raw.stops) g.addColorStop(pos, col);
        setup(c, op, op.alpha(v)); c.fillStyle = g; c.fillRect(0, 0, W, H); break;
      }
      case "zoom": {
        const s = snap(env, c, W, H, 0), k = clamp(op.scale(v), 0.2, 5);
        setup(c, op, 1); c.fillStyle = "#000"; c.fillRect(0, 0, W, H);
        c.translate(W / 2 + clamp(op.dx(v), -1, 1) * W, H / 2 + clamp(op.dy(v), -1, 1) * H);
        const r = op.rot(v); if (r) c.rotate(clamp(r, -6.3, 6.3));
        c.scale(k, k); c.drawImage(s, -W / 2, -H / 2); break;
      }
      case "bars": {
        const f = clamp(op.size(v), 0, 0.5); setup(c, op, 1); c.fillStyle = op.raw.color || "#000000";
        const e = op.raw.edge, vh = H * f, hw = W * f;
        if (e === "top" || e === "vertical") c.fillRect(0, 0, W, vh);
        if (e === "bottom" || e === "vertical") c.fillRect(0, H - vh, W, vh);
        if (e === "left" || e === "horizontal") c.fillRect(0, 0, hw, H);
        if (e === "right" || e === "horizontal") c.fillRect(W - hw, 0, hw, H);
        break;
      }
      case "rgbshift": {
        const off = clamp(op.amount(v), 0, 0.1) * W; if (off < 0.3) break;
        const s = snap(env, c, W, H, 0), cols = ["#f00", "#0f0", "#00f"], dx = [-off, 0, off];
        const chs = cols.map((col, k) => {
          const t = scratch(env, W, H, 1 + k), g = t._g;
          g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.filter = "none"; g.globalCompositeOperation = "source-over"; g.clearRect(0, 0, W, H);
          g.drawImage(s, 0, 0); g.globalCompositeOperation = "multiply"; g.fillStyle = col; g.fillRect(0, 0, W, H); g.globalCompositeOperation = "source-over";
          return t;
        });
        setup(c, { comp: "source-over" }, 1); c.fillStyle = "#000"; c.fillRect(0, 0, W, H);
        c.globalCompositeOperation = "lighter"; chs.forEach((t, k) => c.drawImage(t, dx[k], 0));
        break;
      }
      case "noise": {
        const k = Math.max(1, Math.min(W, H) / 540), n = Math.floor(v.tt * 24);
        setup(c, { comp: op.comp === "source-over" ? "overlay" : op.comp }, op.amount(v));
        if (op.raw.animate) c.translate(-hs(n) * 256 * k, -hs(n + 9) * 256 * k);
        c.scale(k, k); c.fillStyle = noisePattern(env, c); c.fillRect(0, 0, (W + 520 * k) / k, (H + 520 * k) / k); break;
      }
      case "scanlines": {
        const k = Math.max(1, Math.min(W, H) / 540);
        setup(c, op, op.alpha(v) * 0.9); c.scale(k, k); c.fillStyle = scanPattern(env, c); c.fillRect(0, 0, W / k, H / k); break;
      }
      case "mirror": {
        const s = snap(env, c, W, H, 0); setup(c, op, 1);
        if (op.raw.axis === "h") { c.translate(W, 0); c.scale(-1, 1); c.drawImage(s, 0, 0, W / 2, H, 0, 0, W / 2, H); }
        else { c.translate(0, H); c.scale(1, -1); c.drawImage(s, 0, 0, W, H / 2, 0, 0, W, H / 2); }
        break;
      }
      case "pixelate": {
        const cells = clamp(Math.round(op.cells(v)), 8, 400), sz = Math.max(1, W / cells);
        const w = Math.max(1, Math.ceil(W / sz)), h = Math.max(1, Math.ceil(H / sz));
        const s = snap(env, c, W, H, 0), sm = scratch(env, w, h, 5);
        sm._g.setTransform(1, 0, 0, 1, 0, 0); sm._g.globalAlpha = 1; sm._g.filter = "none"; sm._g.clearRect(0, 0, w, h); sm._g.drawImage(s, 0, 0, w, h);
        setup(c, op, 1); c.imageSmoothingEnabled = false; c.drawImage(sm, 0, 0, w, h, 0, 0, w * sz, h * sz); break;
      }
      case "glow": {
        const s = snap(env, c, W, H, 0);
        setup(c, { comp: "screen" }, op.strength(v));
        c.filter = `blur(${clamp(op.radius(v), 0, 0.08) * W}px) brightness(1.3)`; c.drawImage(s, 0, 0); break;
      }
      default: break;
    }
  }

  /** Bir tarifi çalıştırır. Tarif Core.validate'ten geçmiş olmalıdır. */
  function run(recipe, c, W, H, o, env) {
    let ops = compiled.get(recipe);
    if (!ops) { ops = Core.compile(recipe); compiled.set(recipe, ops); }
    const v = { i: o.i, p: o.p, lt: o.lt, tt: o.tt, sp: o.sp || 1, W, H, PI: Math.PI };
    for (const op of ops) {
      if (op.when && op.when(v) <= 0.5) continue;
      c.save();
      try { runOp(op, c, W, H, v, env); } finally { c.restore(); }
    }
  }

  return { makeEnv, run };
});
