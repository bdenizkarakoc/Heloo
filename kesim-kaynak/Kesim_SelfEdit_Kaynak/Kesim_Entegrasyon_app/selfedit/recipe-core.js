/* Kesim SelfEdit: efekt TARİFİ çekirdeği.
 * Yapay zekâ kod değil, bu şemaya uyan bir JSON tarifi üretir. Tarif, aşağıdaki küçük ifade dili
 * ve sabit işlem listesiyle yorumlanır; hiçbir noktada eval / Function / dinamik kod çalışmaz.
 * Hem Electron ana sürecinde (require) hem sayfada (<script>) kullanılır. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SERecipe = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* ---------------- ifade dili ---------------- */
  const VARS = ["i", "p", "lt", "tt", "sp", "W", "H", "PI"];
  const hs = (n) => { const h = Math.sin(n * 127.1 + 311.7) * 43758.5453; return h - Math.floor(h); };
  const FUNCS = {
    sin: [1, Math.sin], cos: [1, Math.cos], tan: [1, Math.tan], abs: [1, Math.abs],
    sqrt: [1, (x) => Math.sqrt(Math.max(0, x))], floor: [1, Math.floor], ceil: [1, Math.ceil],
    round: [1, Math.round], fract: [1, (x) => x - Math.floor(x)],
    min: [2, Math.min], max: [2, Math.max], pow: [2, (a, b) => Math.pow(a, b)],
    step: [2, (e, x) => (x >= e ? 1 : 0)],
    clamp: [3, (x, a, b) => Math.min(b, Math.max(a, x))],
    mix: [3, (a, b, t) => a + (b - a) * t],
    smooth: [3, (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / ((b - a) || 1))); return t * t * (3 - 2 * t); }],
    ease: [1, (u) => 1 - Math.pow(1 - Math.min(1, Math.max(0, u)), 3)],
    hs: [1, hs],
    if: [3, (c, a, b) => (c > 0.5 ? a : b)],
  };
  const MAX_EXPR_LEN = 160, MAX_NODES = 60, MAX_DEPTH = 12;
  const fin = (x) => (Number.isFinite(x) ? x : 0);

  function tokenize(src) {
    const out = []; let k = 0;
    while (k < src.length) {
      const ch = src[k];
      if (ch === " ") { k++; continue; }
      if (/[0-9.]/.test(ch)) {
        const m = /^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i.exec(src.slice(k));
        if (!m) throw new Error("geçersiz sayı");
        out.push({ t: "num", v: parseFloat(m[0]) }); k += m[0].length; continue;
      }
      if (/[A-Za-z_]/.test(ch)) {
        const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(k));
        out.push({ t: "id", v: m[0] }); k += m[0].length; continue;
      }
      const two = src.slice(k, k + 2);
      if (two === "<=" || two === ">=") { out.push({ t: "op", v: two }); k += 2; continue; }
      if ("+-*/%^<>(),".includes(ch)) { out.push({ t: "op", v: ch }); k++; continue; }
      throw new Error(`geçersiz karakter '${ch}'`);
    }
    return out;
  }

  /** İfadeyi derler. Döner: v => number. Hata durumunda Error fırlatır. */
  function compileExpr(src) {
    if (typeof src === "number") { if (!Number.isFinite(src)) throw new Error("sayı sonlu değil"); const c = src; return () => c; }
    if (typeof src !== "string") throw new Error("ifade metin veya sayı olmalı");
    if (!src.trim() || src.length > MAX_EXPR_LEN) throw new Error(`ifade boş veya ${MAX_EXPR_LEN} karakterden uzun`);
    const toks = tokenize(src); let pos = 0, nodes = 0;
    const peek = () => toks[pos], next = () => toks[pos++];
    const isOp = (v) => peek() && peek().t === "op" && peek().v === v;
    const count = () => { if (++nodes > MAX_NODES) throw new Error("ifade çok karmaşık"); };

    function parseCmp(d) {
      let l = parseAdd(d);
      if (peek() && peek().t === "op" && ["<", ">", "<=", ">="].includes(peek().v)) {
        const op = next().v, r = parseAdd(d); count();
        const a = l, b = r;
        l = op === "<" ? (v) => (a(v) < b(v) ? 1 : 0) : op === ">" ? (v) => (a(v) > b(v) ? 1 : 0)
          : op === "<=" ? (v) => (a(v) <= b(v) ? 1 : 0) : (v) => (a(v) >= b(v) ? 1 : 0);
      }
      return l;
    }
    function parseAdd(d) {
      let l = parseMul(d);
      while (isOp("+") || isOp("-")) {
        const op = next().v, r = parseMul(d); count(); const a = l, b = r;
        l = op === "+" ? (v) => a(v) + b(v) : (v) => a(v) - b(v);
      }
      return l;
    }
    function parseMul(d) {
      let l = parseUnary(d);
      while (isOp("*") || isOp("/") || isOp("%")) {
        const op = next().v, r = parseUnary(d); count(); const a = l, b = r;
        l = op === "*" ? (v) => a(v) * b(v)
          : op === "/" ? (v) => { const x = b(v); return x === 0 ? 0 : a(v) / x; }
            : (v) => { const x = b(v); return x === 0 ? 0 : a(v) % x; };
      }
      return l;
    }
    function parseUnary(d) {
      if (isOp("-")) { next(); const e = parseUnary(d); count(); return (v) => -e(v); }
      if (isOp("+")) { next(); return parseUnary(d); }
      return parsePow(d);
    }
    function parsePow(d) {
      const base = parsePrimary(d);
      if (isOp("^")) { next(); const ex = parseUnary(d); count(); return (v) => fin(Math.pow(base(v), ex(v))); }
      return base;
    }
    function parsePrimary(d) {
      if (d > MAX_DEPTH) throw new Error("ifade çok iç içe");
      const t = next();
      if (!t) throw new Error("ifade beklenmedik şekilde bitti");
      count();
      if (t.t === "num") { const c = t.v; return () => c; }
      if (t.t === "op" && t.v === "(") {
        const e = parseCmp(d + 1);
        if (!isOp(")")) throw new Error("')' eksik");
        next(); return e;
      }
      if (t.t === "id") {
        if (isOp("(")) {
          next();
          const spec = Object.prototype.hasOwnProperty.call(FUNCS, t.v) ? FUNCS[t.v] : null;
          if (!spec) throw new Error(`bilinmeyen fonksiyon: ${t.v}`);
          const args = [];
          if (!isOp(")")) { for (;;) { args.push(parseCmp(d + 1)); if (isOp(",")) { next(); continue; } break; } }
          if (!isOp(")")) throw new Error("')' eksik");
          next();
          if (args.length !== spec[0]) throw new Error(`${t.v}() ${spec[0]} bağımsız değişken ister`);
          const fn = spec[1];
          if (args.length === 1) { const [a] = args; return (v) => fin(fn(a(v))); }
          if (args.length === 2) { const [a, b] = args; return (v) => fin(fn(a(v), b(v))); }
          const [a, b, c] = args; return (v) => fin(fn(a(v), b(v), c(v)));
        }
        if (t.v === "PI") return () => Math.PI;
        if (!VARS.includes(t.v)) throw new Error(`bilinmeyen değişken: ${t.v}`);
        const name = t.v; return (v) => v[name];
      }
      throw new Error(`beklenmeyen simge: ${t.v}`);
    }
    const f = parseCmp(0);
    if (pos !== toks.length) throw new Error("ifadenin sonunda fazlalık var");
    return (v) => fin(f(v));
  }

  /* ---------------- tarif şeması ---------------- */
  const COMP = ["source-over", "screen", "multiply", "overlay", "lighten", "darken", "color-dodge", "soft-light", "hard-light", "difference", "lighter"];
  const GROUPS = ["Odak", "Hareket", "Işık", "Retro", "Bozulma", "Renk", "Yeni"];
  const FILTERS = { blur: [0, 60, "px"], brightness: [0, 4, ""], contrast: [0, 4, ""], grayscale: [0, 1, ""], "hue-rotate": [-720, 720, "deg"], invert: [0, 1, ""], saturate: [0, 6, ""], sepia: [0, 1, ""], opacity: [0, 1, ""] };
  const EDGES = ["top", "bottom", "left", "right", "vertical", "horizontal"];
  // op: [zorunlu alanlar, isteğe bağlı alanlar, ifade olan alanlar]
  const OPS = {
    filter: [["fx"], ["alpha", "comp", "when"], ["alpha", "when"]],
    fill: [["color"], ["alpha", "comp", "when"], ["alpha", "when"]],
    gradient: [["kind", "stops"], ["cx", "cy", "r0", "r1", "angle", "alpha", "comp", "when"], ["cx", "cy", "r0", "r1", "angle", "alpha", "when"]],
    zoom: [[], ["scale", "dx", "dy", "rot", "when"], ["scale", "dx", "dy", "rot", "when"]],
    bars: [["edge", "size"], ["color", "when"], ["size", "when"]],
    rgbshift: [["amount"], ["when"], ["amount", "when"]],
    noise: [["amount"], ["comp", "animate", "when"], ["amount", "when"]],
    scanlines: [["alpha"], ["when"], ["alpha", "when"]],
    mirror: [["axis"], ["when"], ["when"]],
    pixelate: [["cells"], ["when"], ["cells", "when"]],
    glow: [["radius", "strength"], ["when"], ["radius", "strength", "when"]],
  };
  const COLOR_RE = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
  const ID_RE = /^[a-z][a-z0-9_]{2,30}$/;
  const NAME_RE = /^[\p{L}\p{N} .,'’()\-+&!?]{2,32}$/u;
  const MAX_OPS = 8;

  /** Tarifi doğrular ve temiz bir kopya döndürür: {ok, errors, recipe}. */
  function validate(r) {
    const errors = [];
    const err = (m) => errors.push(m);
    if (!r || typeof r !== "object" || Array.isArray(r)) return { ok: false, errors: ["tarif bir nesne olmalı"] };
    const allowedTop = ["v", "id", "name", "group", "di", "desc", "ops"];
    for (const k of Object.keys(r)) if (!allowedTop.includes(k)) err(`bilinmeyen alan: ${k}`);
    if (typeof r.id !== "string" || !ID_RE.test(r.id)) err("id geçersiz (küçük harf/rakam/_, 3-31 karakter)");
    if (typeof r.name !== "string" || !NAME_RE.test(r.name)) err("name geçersiz (2-32 karakter, harf/rakam)");
    if (!GROUPS.includes(r.group)) err(`group şunlardan biri olmalı: ${GROUPS.join(", ")}`);
    const di = r.di === undefined ? 0.6 : r.di;
    if (typeof di !== "number" || !(di >= 0.1 && di <= 1.5)) err("di 0.1 ile 1.5 arasında bir sayı olmalı");
    if (r.desc !== undefined && (typeof r.desc !== "string" || r.desc.length > 120 || /[\u0000-\u001f<>]/.test(r.desc))) err("desc en çok 120 karakter olmalı ve < > içermemeli");
    if (!Array.isArray(r.ops) || r.ops.length < 1 || r.ops.length > MAX_OPS) err(`ops 1 ile ${MAX_OPS} arasında işlem içermeli`);

    const ops = [];
    if (Array.isArray(r.ops)) r.ops.slice(0, MAX_OPS).forEach((o, n) => {
      const at = `ops[${n}]`;
      if (!o || typeof o !== "object" || !OPS[o.op]) { err(`${at}: bilinmeyen işlem '${o && o.op}'`); return; }
      const [req, opt, exprFields] = OPS[o.op];
      const allowed = ["op", ...req, ...opt];
      for (const k of Object.keys(o)) if (!allowed.includes(k)) err(`${at}: bilinmeyen alan '${k}'`);
      for (const k of req) if (o[k] === undefined) err(`${at}: '${k}' zorunlu`);
      const c = { op: o.op };
      for (const k of [...req, ...opt]) {
        if (o[k] === undefined) continue;
        if (exprFields.includes(k)) {
          try { compileExpr(o[k]); c[k] = typeof o[k] === "number" ? String(o[k]) : o[k].trim(); } catch (e) { err(`${at}.${k}: ${e.message}`); }
        } else c[k] = o[k];
      }
      if (c.comp !== undefined && !COMP.includes(c.comp)) err(`${at}: comp geçersiz`);
      if (c.color !== undefined && !COLOR_RE.test(c.color)) err(`${at}: color #rrggbb veya #rrggbbaa olmalı`);
      if (c.op === "filter") {
        if (!Array.isArray(c.fx) || c.fx.length < 1 || c.fx.length > 5) err(`${at}: fx 1-5 filtre içermeli`);
        else c.fx = c.fx.map((f, m) => {
          if (!f || typeof f !== "object" || !Object.prototype.hasOwnProperty.call(FILTERS, f.f)) { err(`${at}.fx[${m}]: bilinmeyen filtre`); return f; }
          for (const k of Object.keys(f)) if (k !== "f" && k !== "v") err(`${at}.fx[${m}]: bilinmeyen alan '${k}'`);
          try { compileExpr(f.v); } catch (e) { err(`${at}.fx[${m}].v: ${e.message}`); }
          return { f: f.f, v: typeof f.v === "number" ? String(f.v) : String(f.v).trim() };
        });
      }
      if (c.op === "gradient") {
        if (c.kind !== "radial" && c.kind !== "linear") err(`${at}: kind radial veya linear olmalı`);
        if (!Array.isArray(c.stops) || c.stops.length < 2 || c.stops.length > 6) err(`${at}: stops 2-6 durak içermeli`);
        else {
          let last = -1;
          c.stops = c.stops.map((s, m) => {
            if (!Array.isArray(s) || s.length !== 2 || typeof s[0] !== "number" || !(s[0] >= 0 && s[0] <= 1) || !COLOR_RE.test(s[1])) { err(`${at}.stops[${m}]: [0..1, "#rrggbb(aa)"] olmalı`); return s; }
            if (s[0] < last) err(`${at}.stops: konumlar artan olmalı`);
            last = s[0]; return [s[0], s[1]];
          });
        }
      }
      if (c.op === "bars" && !EDGES.includes(c.edge)) err(`${at}: edge şunlardan biri olmalı: ${EDGES.join(", ")}`);
      if (c.op === "mirror" && c.axis !== "h" && c.axis !== "v") err(`${at}: axis h veya v olmalı`);
      if (c.op === "noise" && c.animate !== undefined && typeof c.animate !== "boolean") err(`${at}: animate true/false olmalı`);
      ops.push(c);
    });

    const recipe = { v: 1, id: r.id, name: r.name, group: r.group, di: di, ops };
    if (r.desc) recipe.desc = r.desc;
    return { ok: errors.length === 0, errors, recipe };
  }

  /** Doğrulanmış tarifi çalıştırılabilir işlemlere derler. */
  function compile(recipe) {
    const ex = (s, d) => (s === undefined ? () => d : compileExpr(s));
    return recipe.ops.map((o) => {
      const c = { op: o.op, comp: o.comp || "source-over", when: o.when === undefined ? null : compileExpr(o.when), raw: o };
      switch (o.op) {
        case "filter": c.fx = o.fx.map((f) => ({ f: f.f, v: compileExpr(f.v) })); c.alpha = ex(o.alpha, 1); break;
        case "fill": c.alpha = ex(o.alpha, 1); break;
        case "gradient": c.cx = ex(o.cx, 0.5); c.cy = ex(o.cy, 0.5); c.r0 = ex(o.r0, 0); c.r1 = ex(o.r1, 0.5); c.angle = ex(o.angle, 0); c.alpha = ex(o.alpha, 1); break;
        case "zoom": c.scale = ex(o.scale, 1); c.dx = ex(o.dx, 0); c.dy = ex(o.dy, 0); c.rot = ex(o.rot, 0); break;
        case "bars": c.size = compileExpr(o.size); break;
        case "rgbshift": c.amount = compileExpr(o.amount); break;
        case "noise": c.amount = compileExpr(o.amount); break;
        case "scanlines": c.alpha = compileExpr(o.alpha); break;
        case "pixelate": c.cells = compileExpr(o.cells); break;
        case "glow": c.radius = compileExpr(o.radius); c.strength = compileExpr(o.strength); break;
        default: break;
      }
      return c;
    });
  }

  /** Aynı etkiyi üreten tarifleri ayırt etmek için parmak izi (ad/id hariç). */
  function fingerprint(recipe) { return JSON.stringify(recipe.ops); }

  const SPEC_TEXT = `Efekt tarifi (JSON). Kod YAZMA; yalnızca bu şemaya uyan bir nesne üret.
{"v":1,"id":"kucuk_harf_id","name":"Türkçe ad (2-32 karakter)","group":"${GROUPS.join("|")}","di":0.6,"desc":"kısa açıklama","ops":[ ...1-${MAX_OPS} işlem... ]}
Sayı alanları sayı veya ifade metni olabilir. İfade dili: sayılar, değişkenler ${VARS.join(", ")}, işleçler + - * / % ^ < > <= >=, parantez,
fonksiyonlar ${Object.keys(FUNCS).map((k) => `${k}(${FUNCS[k][0]})`).join(", ")}.
  i = efekt yoğunluğu (genelde 0.1-1.2), p = efekt süresince ilerleme 0..1, lt = efektin başından beri saniye, tt = zaman çizelgesi saniyesi, sp = hız çarpanı, W/H = kare boyutu.
Her işlemde isteğe bağlı "when": ifade (>0.5 ise işlem çalışır).
İşlemler:
 {"op":"filter","fx":[{"f":"${Object.keys(FILTERS).join("|")}","v":"ifade"}],"alpha":"1","comp":"source-over"}   (blur piksel, hue-rotate derece, diğerleri çarpan/oran)
 {"op":"fill","color":"#rrggbb","alpha":"ifade","comp":"${COMP.join("|")}"}
 {"op":"gradient","kind":"radial|linear","stops":[[0,"#rrggbbaa"],[1,"#rrggbbaa"]],"cx":"0.5","cy":"0.5","r0":"0","r1":"0.5","angle":"0 (derece)","alpha":"1","comp":"..."}   (r0/r1 köşegenin oranı)
 {"op":"zoom","scale":"1","dx":"0","dy":"0","rot":"0 (radyan)"}   (dx/dy kare boyutunun oranı)
 {"op":"bars","edge":"${EDGES.join("|")}","size":"0.1","color":"#000000"}   (kenar kalınlığı oranı)
 {"op":"rgbshift","amount":"0.006"}   (genişliğin oranı)
 {"op":"noise","amount":"0.2","comp":"overlay","animate":true}
 {"op":"scanlines","alpha":"0.5"}
 {"op":"mirror","axis":"h|v"}
 {"op":"pixelate","cells":"60"}   (genişlik boyunca hücre sayısı, 8-400)
 {"op":"glow","radius":"0.012","strength":"0.8"}   (radius genişliğin oranı)
Kurallar: bilinmeyen alan yasak; efekt görünür bir değişiklik yapmalı; görüntüyü tamamen karartmamalı; i ile ölçeklenmeli ki kullanıcı yoğunluğu ayarlayabilsin.`;

  return { VARS, FUNCS, COMP, GROUPS, FILTERS, EDGES, OPS, MAX_OPS, compileExpr, validate, compile, fingerprint, SPEC_TEXT };
});
