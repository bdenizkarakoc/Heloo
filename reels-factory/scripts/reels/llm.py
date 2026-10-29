"""Tam otonom mod: Claude API ile konu seçimi, web araştırması ve senaryo yazımı.

Yalnızca llm.provider = anthropic ve ANTHROPIC_API_KEY tanımlıyken kullanılır.
Claude Code oturumunda (llm.provider = claude_code) bu adımları ajan kendisi yapar (SKILL.md).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

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
    user = ""
    if brief.get("user_text"):
        user = ("KULLANICI METNİ (videonun temeli; konusu bu metindir — iddialarını doğrula, yanlışları "
                "caveats'e yaz):\n" + brief["user_text"] + "\n\n")
    if brief.get("kurgu"):
        user += "KULLANICININ KURGU İSTEĞİ (tempo, süre, geçiş, müzik, ekran yazıları; senaryoyu buna göre kur):\n" + \
            str(brief["kurgu"]) + "\n\n"
    prompt = f"""Kategori: {brief['category_label']} ({brief['category']})
Ton: {brief['tone']} | Hedef kitle: {brief['audience']}
Konu ipucu: {brief.get('topic_hint') or 'yok — kategoriye uygun, merak uyandıran bir konu seç'}
Örnek konular (ilham için): {', '.join(brief.get('seed_topics', []))}
Daha önce işlenen başlıklar (TEKRARLAMA): {', '.join(brief.get('past_titles', [])) or 'yok'}
Son videolar (bütün kategoriler; konu, kişi, yer ve açı olarak bunlardan UZAK DUR): {', '.join(brief.get('recent_titles_all', [])) or 'yok'}
Anlatım biçimi (bu videoda zorunlu): {fmt_line(brief)}
Bilgi haritasındaki işlenmiş kavramlar (Graphify; tekrar etme, bunlarla bağlantılı yeni bir konu seçebilirsin): {', '.join((brief.get('knowledge_map') or {}).get('covered_concepts', [])) or 'yok'}

{user}Görev: 30-60 saniyelik bir Türkçe Reels videosu için tek bir konu seç ve web aramasıyla araştır.
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
Anlatım biçimi (senaryonun yapısı buna uymalı): {fmt_line(brief)}

ARAŞTIRMA:
{json.dumps(research_data, ensure_ascii=False, indent=1)}

SENARYO BİÇİMİ VE KURALLARI:
{fmt}

KANCA (ilk sahnenin narration'ı) — şu kalıplardan birine göre yaz; ilk 2 saniyede kapanmayan bir soru aç,
izleyiciye seslen, somut bir sayı/isim/tarih kullan (araştırmada varsa), 7-20 kelime:
{hook_guide()}
Başlık ile ilk sahnenin headline'ı (kapak) aynı kelimeleri tekrar etmesin; başlık ≤60 karakter.
{user_media_note(brief)}{fix}

Yalnızca script.json içeriğini (tek bir JSON nesnesi) döndür."""
    return extract_json(_call(cfg, state, prompt, web=False))


def fmt_line(brief: dict) -> str:
    f = brief.get("format") or {}
    return f"{f.get('name')}: {f.get('instruction')}" if f.get("name") else "serbest"


def user_media_note(brief: dict) -> str:
    um = brief.get("user_media")
    if not um:
        return ""
    rows = "\n".join(f"- {it['file']} ({it['kind']}, özgün ad: {it.get('original', '')})" for it in um["items"])
    return ("\nKULLANICININ KENDİ MEDYASI (hepsi kullanılacak; sahnelere visual.user ile ata, dosya adından "
            f"içeriği tahmin et):\n{rows}\n")


def hook_guide(limit: int = 21) -> str:
    """YouTube agent skill'in 21 kanca kalıbı (yt-script/hooks.json) — kısa liste."""
    try:
        from .yt_tools import hook_formulas
        return "\n".join(f"- {h['name']}: {h['shape']}" for h in hook_formulas()[:limit])
    except Exception:  # noqa: BLE001
        return "- Soru, şaşırtıcı sayı, karşıtlık, sır, hata uyarısı"


def improve_hook(script: dict, research_data: dict, cfg: Config, state: dict) -> dict:
    """Kanca zayıfsa 5 alternatif yazdırır, Türkçe uyarlanmış kanca puanıyla en iyisini seçer (API modu)."""
    from .yt_tools import hook_score
    scenes = script.get("scenes") or []
    if not scenes:
        return script
    cur = hook_score(scenes[0].get("narration", ""))
    if cur["verdict"] >= int(cfg.get_path("script.min_hook_score", 45)):
        return script
    prompt = (f"Bu Reels'in açılış cümlesi zayıf (puan {cur['verdict']}/100; en zayıf: {cur['fix']}).\n"
              f"Başlık: {script.get('title')}\nŞu anki kanca: {scenes[0].get('narration')}\n"
              f"Sonraki sahne: {scenes[1].get('narration') if len(scenes) > 1 else ''}\n"
              f"Araştırma (yalnızca buradaki bilgiler): {json.dumps(research_data, ensure_ascii=False)[:3000]}\n\n"
              f"Kalıplar:\n{hook_guide()}\n\nFarklı kalıplarla 5 alternatif kanca yaz (Türkçe, 7-20 kelime, "
              "uydurma bilgi yok, sonraki sahneye doğal bağlansın). Yalnızca JSON: {\"hooks\": [\"...\"]}")
    try:
        alts = extract_json(_call(cfg, state, prompt, web=False)).get("hooks") or []
    except StageError as exc:
        L.warning("kanca iyileştirilemedi: %s", exc)
        return script
    best = max((hook_score(h) for h in alts if isinstance(h, str) and h.strip()), key=lambda r: r["verdict"],
               default=None)
    if best and best["verdict"] > cur["verdict"]:
        L.info("Kanca güçlendirildi: %d → %d (%s)", cur["verdict"], best["verdict"], best["formula"])
        scenes[0]["narration"] = best["hook"]
        script.setdefault("facts", []).append(f"kanca: {best['formula']} kalıbı, puan {best['verdict']}/100")
    return script


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
    try:
        script = improve_hook(script, data, cfg, state)
    except StageError as exc:  # bütçe sınırı vb.: mevcut kanca kalır
        L.info("kanca iyileştirme atlandı: %s", exc)
    script["category"] = brief["category"]
    return script, data


# ----------------------------------------------------------------------------
# Claude Code komut satırı (bilgisayarda kurulu ve girişli `claude`) ile senaryo
# ----------------------------------------------------------------------------

# Claude Code kullanım sınırı ("You've hit your session limit · resets 2pm") ve API kredi hatası: dolu olduğu
# sürece boşuna çağrı yapılmaz; otomatik mod sıfırlanma saatine kadar bekler, elle istenen video yeniden denenir.
_CLI_LIMIT_UNTIL = 0.0
_API_DOWN_UNTIL = 0.0
_LIMIT_RE = re.compile(r"hit your [\w ]*limit|usage limit reached|limit reached|out of (?:extra )?usage", re.I)
_RESET_RE = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


class ClaudeLimitError(StageError):
    """Claude Code kullanım sınırı dolu (ve API kullanılamıyor)."""


def _reset_time(text: str) -> float:
    m = _RESET_RE.search(text or "")
    if not m:
        return time.time() + 3600
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    cur = dt.datetime.now()
    at = cur.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
    if at <= cur:
        at += dt.timedelta(days=1)
    return at.timestamp() + 60


def cli_limited() -> float:
    """Claude Code sınırı doluysa sıfırlanma zamanı (epoch), değilse 0."""
    return _CLI_LIMIT_UNTIL if _CLI_LIMIT_UNTIL > time.time() else 0.0


def limit_message(until: float | None = None) -> str:
    until = until or cli_limited() or time.time() + 3600
    return (f"Claude kullanım sınırın doldu (saat {dt.datetime.fromtimestamp(until):%H:%M}'de sıfırlanır) ve Claude API "
            "kredisi de kullanılamıyor. Fabrika sınır sıfırlanınca kendiliğinden yeniden dener; beklemek istemezsen "
            "console.anthropic.com'dan API kredisi yükleyebilirsin.")


def check_cli_limit(text: str) -> None:
    """Claude Code çıktısında sınır mesajı varsa sınırı kaydeder ve ClaudeLimitError fırlatır."""
    global _CLI_LIMIT_UNTIL
    if text and _LIMIT_RE.search(text):
        _CLI_LIMIT_UNTIL = _reset_time(text)
        L.warning("Claude Code kullanım sınırı doldu; %s'e kadar denenmeyecek",
                  dt.datetime.fromtimestamp(_CLI_LIMIT_UNTIL).strftime("%H:%M"))
        raise ClaudeLimitError(limit_message(_CLI_LIMIT_UNTIL))


def mark_api_down(exc: Exception | str) -> None:
    """Kredi/erişim hatasında API bir saat denenmez (doğrudan Claude Code)."""
    global _API_DOWN_UNTIL
    if re.search(r"credit|billing|authentication|permission|401|403", str(exc), re.I):
        _API_DOWN_UNTIL = time.time() + 3600


def api_down() -> bool:
    return _API_DOWN_UNTIL > time.time()


def cli_env() -> dict:
    """Claude Code alt süreci için ortam: ANTHROPIC_API_KEY çıkarılır; böylece `claude` .env'deki (krediye bağlı)
    API anahtarı yerine kullanıcının kendi Claude Code oturumunu kullanır."""
    import os
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def claude_cli() -> str | None:
    """`claude` komutu: PATH'te yoksa yerel kurulumun varsayılan yerine (~/.local/bin) bakılır —
    uygulama, kurulumdan önce başlamışsa PATH'i eskidir."""
    import os
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude"):
        p = Path.home() / ".local" / "bin" / name
        if p.is_file() and (os.name == "nt" or os.access(p, os.X_OK)):
            return str(p)
    return None


def resolve_provider(cfg: Config) -> str:
    """auto: ANTHROPIC_API_KEY varsa anthropic, yoksa kurulu Claude Code (claude_cli), yoksa manual."""
    p = str(cfg.get_path("llm.provider", "auto"))
    if p in ("anthropic", "claude_cli", "manual"):
        return p
    if p == "claude_code":  # eski ad: senaryoyu oturumdaki ajan elle yazar
        return "manual"
    if available():
        return "anthropic"
    if claude_cli():
        return "claude_cli"
    return "manual"


CLI_PROMPT = """Sen bu klasördeki otonom Reels fabrikasının senaryo adımını yürütüyorsun.
skills/reels-production/SKILL.md ve skills/reels-production/script-format.md dosyalarını oku ve
SKILL.md'deki 2. (araştırma), 3. (senaryo) ve 4. (görseller) adımları uygula:

- Görev: {job}  (klasör: projects/{job}/, brif: projects/{job}/brief.json)
- Konu ipucu: {topic}
- brief.json'da `user_media` varsa: kullanıcının kendi fotoğraf/videoları — HEPSİNİ kullan. Read ile bak, içeriğine uygun
  sahnelere `"visual": {{"kind": "photo"|"video", "user": "<dosya>"}}` olarak ata; senaryo bu medyayla uyumlu olsun.
- brief.json'daki `format` anlatım biçimine uy; `recent_titles_all` konularından farklı bir alt konu/açı seç (`variety_rule`).
- brief.json'da `kurgu` varsa: kullanıcının kurgu/biçim isteğidir (tempo, süre, sahne sayısı, geçişler, müzik, ekran
  yazıları, altyazı) — senaryoyu ve sahne ayarlarını buna göre kur; altyazı istemiyorsa her sahnede "captions": false.
- brief.json'da `knowledge_map` varsa: işlenmiş kavramları tekrarlama; ayrıntı için knowledge/corpus/graphify-out/GRAPH_REPORT.md.
- WebSearch/WebFetch ile güvenilir kaynaklardan araştır; her sayıyı doğrula.
- projects/{job}/script.json dosyasını yaz ve `{py} scripts/factory.py validate {job}` hatasız olana kadar düzelt.
- Gerekirse `{py} scripts/factory.py candidates {job} <sahne>` ile görsel adaylarını incele ve visual.pick ile seç.
- Kanca: skills/youtube-agent/yt-script/hooks.json'daki kalıplardan 5 farklı açılış cümlesi yaz,
  `{py} scripts/factory.py hook "1" "2" "3" "4" "5"` ile puanla, en yükseğini ilk sahneye koy (uydurma yok).
  Başlık ile kapak: `{py} scripts/factory.py title "<başlık>" --thumb "<ilk sahne headline>"` — tekrar etmesin.
{extra}- `produce` komutunu ÇALIŞTIRMA; üretimi uygulama yapacak.
- Bitirince yalnızca kısa bir özet yaz: başlık ve kullanılan kaynaklar.
"""


TEXT_EXTRA = """- KULLANICI METNİ (brief.json → user_text) videonun temelidir. Önce incele: iddiaları web'de doğrula,
  yanlış veya abartılı ifadeleri düzelt (düzeltmeleri facts listesine not et), anlamı ve tonu koru;
  sonra 30-60 sn'lik akıcı bir Reels senaryosuna dönüştür. Uydurma bilgi ekleme.
"""
DRAW_EXTRA = """- GÖRSELLERİ KENDİN ÇİZ: her fotoğraf sahnesi için projects/{job}/media/<sahne>.svg dosyası yaz
  (viewBox="0 0 1080 1920", özgün, sahneyle uyumlu, derinlikli illüstrasyon: gradyanlar, katmanlar, ışık;
  İÇİNDE YAZI OLMASIN). YERLEŞİM: üst bölge (y<600) başlıklar için, y=1130-1330 altyazı bandı için sade
  ve koyu kalsın; ana öğe y=620-1100 arasında ve yatayda x=150-930 içinde olsun. Yanına <sahne>.json yaz:
  {{"provider":"agent_svg","title":"<kısa açıklama>","license":"özgün çizim (Claude)"}}.
  Bu sahnelerde visual = {{"kind":"photo","providers":["agent_media"],"fit":"cover"}}.
  Gerçek kişileri çizerek taklit etme; kişi sahnelerinde sembolik çizim kullan.
"""


def generate_via_claude_cli(job_id: str, job_dir, topic: str | None, cfg: Config, on_line=None,
                            text: str | None = None, draw: bool = False) -> dict:
    import subprocess
    import sys
    exe = claude_cli()
    if not exe:
        raise StageError("Claude Code (`claude`) bulunamadı; https://claude.com/claude-code kurun ve giriş yapın")
    py = "python" if sys.platform.startswith("win") else "python3"
    tools = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch",
             f"Bash({py} scripts/factory.py validate:*)", f"Bash({py} scripts/factory.py candidates:*)",
             f"Bash({py} scripts/factory.py hook:*)", f"Bash({py} scripts/factory.py title:*)"]
    extra = (TEXT_EXTRA if text else "") + (DRAW_EXTRA.format(job=job_id) if draw else "")
    cmd = [exe, "-p", CLI_PROMPT.format(job=job_id, topic=topic or "yok — brief.json'a göre sen seç", py=py,
                                        extra=extra),
           "--permission-mode", "acceptEdits", "--allowedTools", *tools]
    if cli_limited():
        raise ClaudeLimitError(limit_message())
    timeout = int(cfg.get_path("llm.claude_cli.timeout_sec", 1800))
    L.info("Claude Code ile senaryo yazılıyor (en fazla %d dk)...", timeout // 60)
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", env=cli_env())
    tail: list[str] = []
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                tail = (tail + [line])[-20:]
                L.info("claude │ %s", line[:300])
                if on_line:
                    on_line(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise StageError("Claude Code zaman aşımı") from exc
    from .cancel import check as cancel_check
    cancel_check()  # "Durdur" ile sonlandırıldıysa
    if proc.returncode != 0:
        check_cli_limit("\n".join(tail))
        raise StageError(f"Claude Code hata kodu {proc.returncode}" + (f": {tail[-1][:200]}" if tail else ""))
    path = job_dir / "script.json"
    if not path.exists():
        raise StageError("Claude Code script.json yazmadı")
    script = normalize(json.loads(path.read_text(encoding="utf-8")), cfg)
    probs = errors_only(validate(script, cfg))
    if probs:
        raise StageError("Claude Code'un senaryosu doğrulanamadı: " + "; ".join(probs))
    return script
