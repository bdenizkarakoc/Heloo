"""Üretim hattı: KONU → ARAŞTIRMA → SENARYO → SES → ALTYAZI → GÖRSEL → MÜZİK → KURGU → RENDER → MİKS → QC → ÇIKTI.

Her adım projects/<görev>/job.json içinde izlenir; tamamlanan adımlar yeniden çalıştırılmaz
(senaryo değişirse ilgili adımlar otomatik olarak geçersiz kılınır). Başarısız adım asla 'done' olmaz.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from . import audio, captions, compose, log, qc, tts, visuals
from .config import Config, ROOT
from .job import PROJECTS, STAGES, Job
from .script_model import errors_only, normalize, validate
from .util import StageError, read_json, slugify, write_json

L = log.get("pipeline")
HISTORY = PROJECTS / "_history.json"
OUT = ROOT / "output"


# ----------------------------------------------------------------------------
# Konu/kategori seçimi ve brif
# ----------------------------------------------------------------------------

def history() -> list[dict]:
    return read_json(HISTORY, []) or []


def pick_category(cfg: Config, wanted: str | None = None) -> str:
    cats = cfg.get_path("categories", {})
    if wanted:
        if wanted not in cats:
            raise StageError(f"bilinmeyen kategori '{wanted}'. Mevcut: {', '.join(cats)}")
        return wanted
    counts = {c: 0 for c in cats}
    for h in history():
        if h.get("category") in counts:
            counts[h["category"]] += 1
    # Ağırlığa göre en az kullanılmış kategori (deterministik sıralı seçim)
    return min(cats, key=lambda c: (counts[c] / max(0.1, float(cats[c].get("weight", 1))), list(cats).index(c)))


def make_brief(job: Job, cfg: Config) -> dict:
    cat_id = job.state["category"]
    cat = cfg.get_path(f"categories.{cat_id}", {})
    past = [h["title"] for h in history() if h.get("title")]
    used_seeds = {h.get("topic_hint") for h in history()}
    brief = {
        "job": job.id,
        "date": dt.date.today().isoformat(),
        "category": cat_id,
        "category_label": cat.get("label", cat_id),
        "kicker": cat.get("kicker", ""),
        "tone": cat.get("tone", ""),
        "audience": cat.get("audience", ""),
        "topic_hint": job.state.get("topic_hint"),
        "seed_topics": [t for t in cat.get("seed_topics", []) if t not in used_seeds],
        "past_titles": past[-50:],
        "target_seconds": cfg.get_path("output.duration.target", 45),
        "duration_range": [cfg.get_path("output.duration.min", 30), cfg.get_path("output.duration.max", 60)],
        "visual_providers": cat.get("visual_providers", ["openverse"]),
        "layouts": cfg.get_path("script.layouts"),
        "script_path": str(job.script_path.relative_to(ROOT)),
        "format_doc": "skills/reels-production/script-format.md",
    }
    write_json(job.dir / "brief.json", brief)
    return brief


def new_job(cfg: Config, category: str | None = None, topic: str | None = None) -> Job:
    cat = pick_category(cfg, category)
    job = Job.create(cat, topic)
    make_brief(job, cfg)
    L.info("Yeni görev: %s (kategori: %s)", job.id, cat)
    return job


def auto_script(job: Job, cfg: Config) -> dict:
    """llm.provider = anthropic ise senaryoyu Claude API ile üretir."""
    from . import llm
    brief = read_json(job.dir / "brief.json") or make_brief(job, cfg)
    with job.stage("script") as info:
        script, research = llm.generate(brief, cfg, job.state)
        write_json(job.dir / "research.json", research)
        write_json(job.script_path, script)
        info.update({"provider": "anthropic", "title": script.get("title"), "scenes": len(script["scenes"])})
    return script


# ----------------------------------------------------------------------------
# Adımlar
# ----------------------------------------------------------------------------

def _script_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def load_script(job: Job, cfg: Config) -> dict:
    if not job.script_path.exists():
        raise StageError(f"senaryo yok: {job.script_path} (SKILL.md akışıyla yazın veya llm.provider=anthropic)")
    raw = json.loads(job.script_path.read_text(encoding="utf-8"))
    script = normalize(raw, cfg)
    probs = validate(script, cfg)
    errs = errors_only(probs)
    if errs:
        raise StageError("senaryo geçersiz:\n- " + "\n- ".join(errs))
    for p in probs:
        job.warn(p)
    return script


def stage_voice(job: Job, script: dict, cfg: Config) -> dict:
    out = job.d("voice")
    metas = {}
    with job.stage("voice") as info:
        for sc in script["scenes"]:
            metas[sc["id"]] = tts.synthesize_scene(sc, out, cfg)
        info["providers"] = sorted({m["provider"] for m in metas.values()})
        info["seconds"] = round(sum(m["duration"] for m in metas.values()), 2)
        info["timing"] = sorted({m["timing"] for m in metas.values()})
        write_json(out / "index.json", metas)
    job.state["providers"]["tts"] = info["providers"]
    job.save()
    return metas


def stage_captions(job: Job, script: dict, metas: dict, cfg: Config) -> tuple[dict, list[dict], list[dict]]:
    with job.stage("captions") as info:
        tl = captions.build_timeline(script, metas, cfg)
        words = captions.absolute_words(script, metas, tl)
        groups = captions.caption_groups(words, cfg) if cfg.get_path("captions.enabled", True) else []
        write_json(job.dir / "timeline.json", tl)
        write_json(job.dir / "words.json", words)
        write_json(job.dir / "captions.json", groups)
        captions.write_srt(captions.srt_cues(words), job.dir / "final" / "captions.srt")
        info.update({"total_seconds": tl["total"], "groups": len(groups), "words": len(words)})
        hard = cfg.get_path("output.duration.hard_max", 90)
        if tl["total"] > hard:
            raise StageError(f"video {tl['total']:.1f} sn; üst sınır {hard} sn — senaryoyu kısaltın")
        dmin, dmax = cfg.get_path("output.duration.min", 30), cfg.get_path("output.duration.max", 60)
        if not dmin <= tl["total"] <= dmax:
            job.warn(f"süre {tl['total']:.1f} sn; hedef aralık {dmin}-{dmax} sn")
    return tl, words, groups


def stage_visuals(job: Job, script: dict, tl: dict, cfg: Config) -> dict:
    from .util import http
    http(cfg.get_path("visuals.user_agent"))
    cat = cfg.get_path(f"categories.{job.state['category']}", {})
    providers = cat.get("visual_providers", ["openverse"])
    used = {"sources": set(), "hashes": []}
    budget = visuals.Budget(cfg, job.state)
    rows = {r["id"]: r for r in tl["scenes"]}
    media: dict[str, dict | None] = {}
    with job.stage("visuals") as info:
        for sc in script["scenes"]:
            ref = sc["visual"].get("reuse")
            if ref and media.get(ref):  # bilinçli tekrar (ör. kapanışta açılış görseline dönüş)
                meta = dict(media[ref])
                meta["fit"] = visuals.choose_fit(meta, sc)
                meta["reused_from"] = ref
            else:
                meta = visuals.fetch_scene_visual(sc, job.dir, cfg, providers, used, budget,
                                                  rows[sc["id"]]["duration"])
            media[sc["id"]] = meta
            if meta is None and sc["visual"]["kind"] in ("photo", "video"):
                job.warn(f"{sc['id']}: uygun görsel bulunamadı → hareketli grafik arka plan kullanıldı")
            if meta and sc["visual"]["kind"] == "video" and meta["kind"] != "video":
                job.warn(f"{sc['id']}: video klip istenmişti, fotoğraf + kamera hareketi kullanıldı "
                         "(video üretim/stok sağlayıcısı yapılandırılmamış)")
        unchecked = [sid for sid, m in media.items() if m and not m.get("license_checked", True)]
        if unchecked:
            job.warn(f"lisansı doğrulanmamış görseller (license_mode: any): {', '.join(unchecked)} — "
                     "yayın öncesi kullanım hakkını kontrol edin")
        write_json(job.dir / "visuals.json", media)
        credits = [{"scene": sid, **{k: m.get(k, "") for k in ("provider", "title", "license", "credit", "source",
                                                               "verified")},
                    "license_checked": m.get("license_checked", True)} for sid, m in media.items() if m]
        write_json(job.dir / "credits_visuals.json", credits)
        sheet_items = [(f"{sid} · {next(s['layout'] for s in script['scenes'] if s['id'] == sid)}",
                        (job.dir / "visuals" / m["file"]) if m and m["kind"] == "photo" else
                        (job.dir / "visuals" / f"{sid}_poster.jpg") if m else None,
                        f"{m['provider']}: {m['title']}" if m else "grafik") for sid, m in media.items()]
        visuals.contact_sheet(sheet_items, job.dir / "qc" / "media_review.jpg", cfg.path(cfg.get_path("brand.font_file")))
        info["providers"] = sorted({m["provider"] for m in media.values() if m})
        info["with_media"] = sum(1 for m in media.values() if m)
        info["graphic_only"] = sum(1 for m in media.values() if not m)
        info["budget_used"] = job.state.get("budget_used", {})
    job.state["providers"]["visuals"] = info["providers"]
    job.save()
    return media


def stage_music(job: Job, script: dict, tl: dict, cfg: Config) -> dict | None:
    cat = cfg.get_path(f"categories.{job.state['category']}", {})
    queries = (script.get("music") or {}).get("queries") or cat.get("music_queries", ["ambient"])
    recent = {h.get("music") for h in history()[-5:]}
    with job.stage("music") as info:
        music = audio.pick_music(cfg, queries, job.d("audio"), tl["total"], {x for x in recent if x})
        if music:
            music["path"] = str(music["path"])
        write_json(job.dir / "audio" / "music.json", music or {})
        info.update({k: music.get(k) for k in ("provider", "title", "license")} if music else {"provider": None})
    if not music:
        job.warn("arka plan müziği bulunamadı; müziksiz devam")
    return music


def stage_compose(job: Job, script: dict, tl: dict, metas: dict, media: dict, groups: list[dict],
                  cfg: Config) -> dict:
    cat = cfg.get_path(f"categories.{job.state['category']}", {})
    with job.stage("compose") as info:
        res = compose.build_project(job.dir, script, tl, metas, media, groups, cat, cfg)
        if res["safe_zone_problems"]:
            raise StageError("güvenli alan ihlali: " + "; ".join(res["safe_zone_problems"]))
        lint = compose.lint(Path(res["dir"]))
        write_json(job.dir / "composition" / "lint.json", lint)
        write_json(job.dir / "audio" / "sfx_events.json", res["sfx"])
        errs = int(lint.get("errorCount", 0))
        info.update({"lint_errors": errs, "lint_warnings": int(lint.get("warningCount", 0)),
                     "text_boxes": res["text_boxes"], "sfx_events": len(res["sfx"])})
        if errs:
            raise StageError(f"HyperFrames lint {errs} hata: " + json.dumps(lint.get("findings", [])[:3],
                                                                             ensure_ascii=False)[:800])
    return res


def stage_render(job: Job, cfg: Config) -> Path:
    comp = job.dir / "composition"
    out = job.dir / "render" / "video.mp4"
    with job.stage("render") as info:
        try:
            compose.render(comp, out, cfg)
            info["workers"] = cfg.get_path("render.workers", 4)
        except StageError as exc:
            L.warning("render başarısız (%s); 2 işçi ile yeniden deneniyor", str(exc)[:300])
            compose.render(comp, out, cfg, workers=2)
            info["workers"] = 2
            info["retried"] = True
        info["mb"] = round(out.stat().st_size / 1e6, 2)
    return out


def stage_mix(job: Job, script: dict, tl: dict, music: dict | None, video: Path, cfg: Config) -> Path:
    work = job.d("audio")
    with job.stage("mix") as info:
        voice_wav = audio.build_voice_track(script, tl, job.dir / "voice", work, cfg)
        bed = audio.build_music_bed(music, voice_wav, tl["total"], work, cfg) if music else None
        events = read_json(work / "sfx_events.json", [])
        sfx_wav, placed = audio.build_sfx_track(events, tl["total"], work, cfg)
        mix = audio.final_mix(voice_wav, bed, sfx_wav, tl["total"], work, cfg)
        final = job.dir / "final" / "video.mp4"
        audio.mux(video, mix, final, cfg)
        write_json(work / "sfx_placed.json", placed)
        if music:
            write_json(work / "music.json", music)
        info.update({"music": music.get("title") if music else None, "sfx": len(placed)})
    return final


def stage_qc(job: Job, script: dict, tl: dict, words: list[dict], final: Path, zone_problems: list[str],
             cfg: Config, autofix: bool = True) -> dict:
    with job.stage("qc") as info:
        report = qc.run_qc(final, cfg, tl, words, script, job.d("qc"), cfg.path(cfg.get_path("brand.font_file")),
                           zone_problems, autofix=autofix)
        write_json(job.dir / "qc" / "report.json", report)
        info.update({"passed": report["passed"], "errors": report["errors"], "warnings": report["warnings"],
                     "fixes": report["fixes"]})
        for c in report["checks"]:
            mark = "–" if c.get("skipped") else "✔" if c["ok"] else ("✖" if c["severity"] == "error" else "!")
            L.info("  %s %-24s %s", mark, c["name"], c["detail"])
        if not report["passed"]:
            failed = [f"{c['name']}: {c['detail']}" for c in report["checks"]
                      if not c["ok"] and c["severity"] == "error"]
            raise StageError("kalite kontrolünden geçemedi: " + "; ".join(failed))
    return report


def stage_export(job: Job, script: dict, final: Path, music: dict | None, cfg: Config) -> dict:
    with job.stage("export") as info:
        date = dt.date.today().strftime("%Y%m%d")
        slug = f"{date}-{slugify(script.get('title', job.id))}"
        vid = OUT / "videos" / f"{slug}.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(final, vid)
        thumb = OUT / "thumbnails" / f"{slug}.jpg"
        thumb.parent.mkdir(parents=True, exist_ok=True)
        from .util import run
        run(["ffmpeg", "-y", "-v", "error", "-ss", "0.9", "-i", final, "-frames:v", "1", "-q:v", "2", thumb])
        cap_dir = OUT / "captions"
        cap_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(job.dir / "final" / "captions.srt", cap_dir / f"{slug}.srt")
        credits = read_json(job.dir / "credits_visuals.json", [])
        lines = [script["post"].get("caption", script.get("title", "")), "",
                 " ".join(script["post"].get("hashtags", [])), "", "Kaynaklar:"]
        lines += [f"- {s.get('title', '')}: {s['url']}" for s in script.get("sources", [])]
        attributions = [c for c in credits if c.get("credit") or "CC" in str(c.get("license", ""))
                        or not c.get("license_checked", True)]
        if attributions or (music and music.get("provider") == "openverse"):
            lines += ["", "Görsel/müzik atıfları:"]
            lines += [f"- {c['scene']}: {c.get('credit') or c.get('title')} ({c.get('license')}"
                      f"{'' if c.get('license_checked', True) else '; kullanım hakkı doğrulanmadı'}) {c.get('source')}"
                      for c in attributions]
            if music and music.get("provider") == "openverse":
                lines.append(f"- Müzik: {music.get('credit')} ({music.get('license')}) {music.get('source')}")
        lines += ["", "Bu video yapay zekâ destekli bir üretim hattıyla hazırlanmıştır (seslendirme: sentetik ses)."]
        post = cap_dir / f"{slug}.txt"
        post.write_text("\n".join(lines) + "\n", encoding="utf-8")
        job.state["outputs"] = {"video": str(vid.relative_to(ROOT)), "thumbnail": str(thumb.relative_to(ROOT)),
                                "srt": str((cap_dir / f"{slug}.srt").relative_to(ROOT)),
                                "post": str(post.relative_to(ROOT))}
        info.update(job.state["outputs"])
        hist = [h for h in history() if h.get("job") != job.id]
        hist.append({"job": job.id, "date": dt.date.today().isoformat(), "category": job.state["category"],
                     "topic_hint": job.state.get("topic_hint"), "title": script.get("title"),
                     "music": (music or {}).get("url") or (music or {}).get("title"), "output": info["video"]})
        write_json(HISTORY, hist)
    return job.state["outputs"]


def recover_black_frames(job: Job, tl: dict, media: dict) -> bool:
    """QC yalnızca siyah kare yüzünden kaldıysa, o anlara denk gelen sahnelerin medyasını devre dışı bırakır."""
    report = read_json(job.dir / "qc" / "report.json", {})
    errors = [c for c in report.get("checks", []) if not c["ok"] and c["severity"] == "error"]
    if not errors or any(c["name"] != "siyah_ekran_yok" for c in errors):
        return False
    changed = []
    for a, b in errors[0].get("spans", []):
        for row in tl["scenes"]:
            if row["start"] < b and a < row["end"] and media.get(row["id"]):
                media[row["id"]] = None
                changed.append(row["id"])
    if changed:
        write_json(job.dir / "visuals.json", media)
        job.warn(f"siyah kare tespit edildi; {', '.join(sorted(set(changed)))} sahne(ler)i grafik arka planla "
                 "yeniden üretiliyor")
    return bool(changed)


# ----------------------------------------------------------------------------
# Ana akış
# ----------------------------------------------------------------------------

def produce(job: Job, cfg: Config, from_stage: str | None = None, autofix: bool = True) -> dict:
    handler = log.attach_job_log(job.id)
    try:
        if from_stage:
            if from_stage not in STAGES:
                raise StageError(f"bilinmeyen adım '{from_stage}'. Adımlar: {', '.join(STAGES)}")
            job.reset_from(from_stage)
        h = _script_hash(job.script_path) if job.script_path.exists() else None
        if h and job.state.get("script_hash") not in (None, h):
            L.info("senaryo değişmiş → ses adımından itibaren yeniden üretilecek")
            job.reset_from("voice")
        job.state["script_hash"] = h
        job.set_status("producing")

        if not job.stage_done("script"):
            with job.stage("script") as info:
                script = load_script(job, cfg)
                info.update({"title": script.get("title"), "scenes": len(script["scenes"])})
        script = load_script(job, cfg)
        write_json(job.dir / "script.normalized.json", script)

        metas = read_json(job.dir / "voice" / "index.json") if job.stage_done("voice") else None
        if not metas:
            metas = stage_voice(job, script, cfg)
        if job.stage_done("captions"):
            tl = read_json(job.dir / "timeline.json")
            words = read_json(job.dir / "words.json")
            groups = read_json(job.dir / "captions.json")
        else:
            tl, words, groups = stage_captions(job, script, metas, cfg)
        media = read_json(job.dir / "visuals.json") if job.stage_done("visuals") else None
        if media is None:
            media = stage_visuals(job, script, tl, cfg)
        music = read_json(job.dir / "audio" / "music.json") if job.stage_done("music") else None
        if music is None:
            music = stage_music(job, script, tl, cfg)
        music = music or None

        res = None
        if not job.stage_done("compose"):
            res = stage_compose(job, script, tl, metas, media, groups, cfg)
        zone_problems = res["safe_zone_problems"] if res else []
        video = job.dir / "render" / "video.mp4"
        if not job.stage_done("render") or not video.exists():
            video = stage_render(job, cfg)
        final = job.dir / "final" / "video.mp4"
        if not job.stage_done("mix") or not final.exists():
            final = stage_mix(job, script, tl, music, video, cfg)
        if not job.stage_done("qc"):
            try:
                stage_qc(job, script, tl, words, final, zone_problems, cfg, autofix)
            except StageError:
                if not (autofix and recover_black_frames(job, tl, media)):
                    raise
                L.info("otomatik düzeltme: sorunlu sahneler grafik arka planla yeniden üretiliyor")
                res = stage_compose(job, script, tl, metas, media, groups, cfg)
                video = stage_render(job, cfg)
                final = stage_mix(job, script, tl, music, video, cfg)
                stage_qc(job, script, tl, words, final, res["safe_zone_problems"], cfg, autofix)
        outputs = stage_export(job, script, final, music, cfg)
        job.set_status("done")
        return outputs
    except Exception:
        job.set_status("failed")
        raise
    finally:
        log.detach(handler)
