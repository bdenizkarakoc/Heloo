"""Tam otonom mod: Claude API ile konu seçimi, web araştırması ve senaryo yazımı.

Yalnızca llm.provider = anthropic ve ANTHROPIC_API_KEY tanımlıyken kullanılır.
Claude Code oturumunda (llm.provider = claude_code) bu adımları ajan kendisi yapar (SKILL.md).
"""
from __future__ import annotations

import json
import re

from . import log
from .config import Config, ROOT, secret
from .script_model import errors_only, normalize, validate
from .util import StageError

L = log.get("llm")
FORMAT_DOC = ROOT / "skills" / "reels-production" / "script-format.md"

SYSTEM = """Sen Türkçe kısa dikey videolar (Instagram Reels, TikTok, YouTube Shorts) için çalışan bir
araştırmacı ve senaristsin. Kuralların:
- Yalnızca doğrulanabilir bilgiler kullan; her önemli iddia güvenilir bir kaynağa dayanmalı.
- Uydurma bilgi, yanıltıcı başlık, gerçekmiş gibi sunulan kurgu olay üretme. Emin olmadığın bir
  ayrıntıyı senaryoya koyma.
- Doğal, akıcı, konuşma dilinde Türkçe yaz. Seslendirme metnini yüksek sesle okunacak şekilde yaz:
  sembol kullanma (°, &, / yerine kelimeler), kısaltmaları aç.
- İstenen çıktı biçimine birebir uy; yalnızca JSON döndür."""


def available() -> bool:
    return bool(secret("ANTHROPIC_API_KEY"))


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise StageError("anthropic paketi kurulu değil (pip install anthropic)") from exc
    return anthropic.Anthropic()


def _take_call(state: dict, cfg: Config) -> None:
    used = state.setdefault("budget_used", {}).setdefault("llm_calls", 0)
    limit = cfg.get_path("budget.max_llm_calls_per_video", 4)
    if used >= limit:
        raise StageError(f"maliyet sınırı: dil modeli çağrısı sınırı ({limit}) doldu")
    state["budget_used"]["llm_calls"] = used + 1


def _call(cfg: Config, state: dict, prompt: str, web: bool = False) -> str:
    import anthropic

    acfg = cfg.get_path("llm.anthropic", {})
    client = _client()
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": int(acfg.get("max_web_searches", 8))}] if web else []
    for _ in range(5):  # pause_turn devamları için sınır
        _take_call(state, cfg)
        try:
            kwargs = dict(model=acfg.get("model", "claude-opus-5-5"), max_tokens=int(acfg.get("max_tokens", 32000)),
                          betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                          output_config={"effort": acfg.get("effort", "high")},
                          system=SYSTEM, messages=messages)
            if tools:
                kwargs["tools"] = tools
            with client.beta.messages.stream(**kwargs) as stream:
                resp = stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise StageError("Claude API hız sınırı; daha sonra tekrar deneyin") from exc
        except anthropic.APIStatusError as exc:
            raise StageError(f"Claude API hatası {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise StageError("Claude API bağlantı hatası") from exc
        L.info("Claude yanıtı: stop_reason=%s, giriş=%s, çıkış=%s token", resp.stop_reason,
               resp.usage.input_tokens, resp.usage.output_tokens)
        if resp.stop_reason == "refusal":
            raise StageError("Claude bu isteği reddetti (refusal); konu/kategori değiştirilmeli")
        if resp.stop_reason == "pause_turn":
            messages = messages[:1] + [{"role": "assistant", "content": resp.content}]
            continue
        if resp.stop_reason == "max_tokens":
            raise StageError("yanıt max_tokens sınırında kesildi")
        return "".join(b.text for b in resp.content if b.type == "text")
    raise StageError("Claude yanıtı tamamlanamadı (pause_turn sınırı)")


def extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StageError(f"dil modeli geçerli JSON döndürmedi: {exc}") from exc


def research(brief: dict, cfg: Config, state: dict) -> dict:
    prompt = f"""Kategori: {brief['category_label']} ({brief['category']})
Ton: {brief['tone']} | Hedef kitle: {brief['audience']}
Konu ipucu: {brief.get('topic_hint') or 'yok — kategoriye uygun, merak uyandıran bir konu seç'}
Örnek konular (ilham için): {', '.join(brief.get('seed_topics', []))}
Daha önce işlenen başlıklar (TEKRARLAMA): {', '.join(brief.get('past_titles', [])) or 'yok'}

Görev: 30-60 saniyelik bir Türkçe Reels videosu için tek bir konu seç ve web aramasıyla araştır.
Birincil ve güvenilir kaynakları tercih et (resmî kurumlar, akademik kaynaklar, köklü yayınlar).
Bilgileri en az iki kaynakla karşılaştır; tutarsızlık varsa belirt ve tartışmalı ayrıntıyı kullanma.

Yalnızca şu JSON'u döndür:
{{"topic": "...", "angle": "videonun şaşırtıcı/özgün bakış açısı", "hook_ideas": ["..."],
  "facts": [{{"claim": "Türkçe, kesin ifade", "numbers": "varsa sayılar ve birimleri",
              "sources": [0]}}],
  "caveats": ["yanlış anlaşılmaya açık noktalar"],
  "sources": [{{"title": "...", "url": "https://...", "publisher": "..."}}]}}"""
    return extract_json(_call(cfg, state, prompt, web=True))


def write_script(brief: dict, research_data: dict, cfg: Config, state: dict, problems: list[str] | None = None,
                 previous: dict | None = None) -> dict:
    fmt = FORMAT_DOC.read_text(encoding="utf-8")
    fix = ""
    if problems and previous:
        fix = ("\n\nÖnceki senaryonun doğrulama hataları (düzelt ve tam senaryoyu yeniden ver):\n- "
               + "\n- ".join(problems) + "\n\nÖnceki senaryo:\n" + json.dumps(previous, ensure_ascii=False))
    prompt = f"""Aşağıdaki araştırmaya dayanarak senaryo yaz. Araştırmada olmayan bir bilgiyi ekleme.
Kategori: {brief['category']} | Ton: {brief['tone']} | Hedef süre: {brief['target_seconds']} sn
Görsel kaynak sırası: {', '.join(brief['visual_providers'])}

ARAŞTIRMA:
{json.dumps(research_data, ensure_ascii=False, indent=1)}

SENARYO BİÇİMİ VE KURALLARI:
{fmt}{fix}

Yalnızca script.json içeriğini (tek bir JSON nesnesi) döndür."""
    return extract_json(_call(cfg, state, prompt, web=False))


def generate(brief: dict, cfg: Config, state: dict) -> tuple[dict, dict]:
    if not available():
        raise StageError("ANTHROPIC_API_KEY tanımlı değil; Claude Code oturumunda SKILL.md akışını kullanın")
    data = research(brief, cfg, state)
    if not data.get("sources"):
        raise StageError("araştırma kaynak döndürmedi; uydurma bilgi riskine karşı durduruldu")
    script = normalize(write_script(brief, data, cfg, state), cfg)
    probs = errors_only(validate(script, cfg))
    if probs:
        L.warning("senaryo doğrulaması başarısız, bir kez onarılıyor: %s", probs)
        script = normalize(write_script(brief, data, cfg, state, probs, script), cfg)
        probs = errors_only(validate(script, cfg))
        if probs:
            raise StageError("senaryo doğrulanamadı: " + "; ".join(probs))
    script["category"] = brief["category"]
    return script, data
