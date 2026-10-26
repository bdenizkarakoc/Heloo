/* Kesim SelfEdit: öneri üreticiler. Biri çevrimdışı şablon kütüphanesi, diğeri Claude API.
 * İkisi de yalnızca bir efekt TARİFİ (JSON) döndürür; kod döndüremez. */
"use strict";
const Core = require("./recipe-core.js");
const TEMPLATES = require("./templates.js");

function normalize(s) { return String(s || "").toLocaleLowerCase("tr"); }

/** Çevrimdışı: dileklere ve kullanım alışkanlığına göre sıradaki şablonu seçer. */
function offlinePropose({ summary, takenIds, takenNames }) {
  const taken = new Set(takenIds), names = new Set([...takenNames].map(normalize));
  const wishText = normalize((summary.wishes || []).join(" "));
  const topGroup = Object.entries(summary.groups_used || {}).sort((a, b) => b[1] - a[1])[0];
  const cands = TEMPLATES.filter((t) => !taken.has(t.recipe.id) && !names.has(normalize(t.recipe.name)));
  if (!cands.length) return null;
  const score = (t) => {
    let s = 0;
    for (const k of t.keywords) if (wishText.includes(normalize(k))) s += 10;
    if (topGroup && t.recipe.group === topGroup[0]) s += 2;
    return s;
  };
  let best = cands[0], bs = score(best);
  for (const t of cands) { const s = score(t); if (s > bs) { best = t; bs = s; } }
  const why = bs >= 10 ? "Dileklerinde bu efektle ilgili bir istek vardı."
    : bs > 0 ? "En çok kullandığın efekt grubuna uyuyor." : "Kütüphanedeki sıradaki yaygın eksik efekt.";
  return { recipe: JSON.parse(JSON.stringify(best.recipe)), title: `Yeni efekt: ${best.recipe.name}`, rationale: why, source: "şablon" };
}

function buildPrompt({ summary, builtins, taken, errors }) {
  const lines = [
    "Kesim adlı bir video düzenleyicinin efekt kütüphanesine EKLENECEK TEK BİR yeni efekt tarifi tasarla.",
    "", Core.SPEC_TEXT, "",
    `Zaten var olan efektler (tekrar etme, farklı ve işe yarar bir şey öner): ${builtins.map((b) => b.name).join(", ")}`,
    `Daha önce önerilmiş id'ler (kullanma): ${[...taken].join(", ") || "yok"}`,
    "", "Kullanıcı kullanım özeti (JSON):", JSON.stringify(summary, null, 1), "",
    "Önce kullanıcı dileklerine bak; yoksa çok kullanılan gruplara tamamlayıcı bir efekt öner.",
    'Yanıtın YALNIZCA şu JSON olsun: {"title":"...","rationale":"neden bu efekt (1-2 cümle, Türkçe)","recipe":{...}}',
  ];
  if (errors && errors.length) lines.push("", "ÖNCEKİ DENEMEN ŞU HATALARLA REDDEDİLDİ, düzelt:", ...errors.map((e) => "- " + e));
  return lines.join("\n");
}

function extractJson(text) {
  const m = /\{[\s\S]*\}/.exec(text || "");
  if (!m) return null;
  try { return JSON.parse(m[0]); } catch { return null; }
}

async function callClaude({ apiKey, model, prompt, fetchImpl }) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 60000);
  try {
    const res = await fetchImpl("https://api.anthropic.com/v1/messages", {
      method: "POST", signal: ctl.signal,
      headers: { "content-type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model, max_tokens: 1500, system: "Yalnızca istenen JSON'u döndür. Kod yazma; yalnızca şemaya uyan tarif üret.", messages: [{ role: "user", content: prompt }] }),
    });
    if (!res.ok) throw new Error(`Claude API ${res.status}`);
    const data = await res.json();
    return (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
  } finally { clearTimeout(timer); }
}

/** Claude ile öner. Şema hatası olursa hataları geri verip bir kez daha dener. */
async function llmPropose({ apiKey, model, summary, builtins, takenIds, fetchImpl }) {
  let errors = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    const text = await callClaude({ apiKey, model, fetchImpl, prompt: buildPrompt({ summary, builtins, taken: takenIds, errors }) });
    const d = extractJson(text);
    if (!d || !d.recipe) { errors = ["yanıt geçerli bir JSON değildi veya 'recipe' alanı yoktu"]; continue; }
    const v = Core.validate(d.recipe);
    if (!v.ok) { errors = v.errors.slice(0, 8); continue; }
    if (takenIds.has(v.recipe.id)) { errors = [`id '${v.recipe.id}' zaten kullanılmış, başka bir id seç`]; continue; }
    return { recipe: v.recipe, title: String(d.title || `Yeni efekt: ${v.recipe.name}`).slice(0, 80), rationale: String(d.rationale || "").slice(0, 300), source: "Claude" };
  }
  return { failed: true, errors };
}

module.exports = { offlinePropose, llmPropose, buildPrompt, extractJson };
