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
        "user_text": job.state.get("user_text"),
        "draw_visuals": job.state.get("draw", False),
        "script_path": str(job.script_path.relative_to(ROOT)),
        "format_doc": "skills/reels-production/script-format.md",
    }
    if job.state.get("user_media"):
        brief["user_media"] = {
            "folder": str((job.dir / "user_media").relative_to(ROOT)),
            "items": job.state["user_media"],
            "note": "Kullanıcının kendi fotoğraf/videoları: HEPSİ videoda kullanılmalı. Dosyalara bak (Read), içeriğine "
                    "uygun sahneye ata: sahnenin visual'ına \"user\": \"<dosya adı>\" ekle. Senaryo bu medyayla uyumlu "
                    "olmalı. Atamadıkların sırayla boş fotoğraf sahnelerine yerleştirilir."}
    if job.state.get("user_music"):
        brief["user_music"] = "Kullanıcı kendi müziğini yükledi; arka plan müziği o olacak (music alanını boş bırakabilirsin)."
    try:  # Graphify içerik haritası varsa: işlenmiş kavramlar (tekrar etme, bağlantılardan yeni konu)
        from .knowledge import brief_context
        km = brief_context()
        if km:
            brief["knowledge_map"] = km
    except Exception as exc:  # noqa: BLE001 — harita isteğe bağlıdır
        L.debug("bilgi haritası okunamadı: %s", exc)
    write_json(job.dir / "brief.json", brief)
    return brief


def new_job(cfg: Config, category: str | None = None, topic: str | None = None,
            text: str | None = None, draw: bool = False, media: list[Path] | None = None) -> Job:
    """text: kullanıcının yazdığı metin (incelenip doğrulanarak senaryoya çevrilir).
    draw: görselleri ajan kendisi SVG illüstrasyon olarak çizer.
    media: kullanıcının kendi fotoğraf/video/müzik dosyaları — videoda mutlaka kullanılır."""
    cat = pick_category(cfg, category)
    job = Job.create(cat, topic or (text.strip().splitlines()[0][:80] if text else None))
    if text:
        job.state["user_text"] = text.strip()
    job.state["draw"] = bool(draw)
    if media:
        add_user_media(job, media)
    job.save()
    make_brief(job, cfg)
    L.info("Yeni görev: %s (kategori: %s)", job.id, cat)
    return job


def add_user_media(job: Job, files: list[Path]) -> None:
    """Kullanıcı medyasını göreve kopyalar: fotoğraflar JPG'ye (HEIC dahil, EXIF yönüyle), videolar olduğu gibi,
    ses dosyası arka plan müziği olarak."""
    import shutil
    from .studio import media_info, normalize_image
    dest = job.dir / "user_media"
    dest.mkdir(parents=True, exist_ok=True)
    items = []
    for i, f in enumerate(files, 1):
        try:
            info = media_info(f)
        except StageError as exc:
            job.warn(f"yüklenen dosya okunamadı, atlandı: {f.name} ({exc})")
            continue
        if info["kind"] == "audio":
            target = dest / f"muzik{f.suffix.lower()}"
            shutil.copy(f, target)
            job.state["user_music"] = str(target.relative_to(job.dir))
            continue
        if info["kind"] == "image":
            src = normalize_image(f) if f.suffix.lower() not in (".jpg", ".jpeg") else f
            target = dest / f"{i:02d}.jpg"
        else:
            src, target = f, dest / f"{i:02d}{f.suffix.lower()}"
        shutil.copy(src, target)
        items.append({"file": target.name, "kind": "photo" if info["kind"] == "image" else "video",
                      "width": info["width"], "height": info["height"], "duration": round(info["duration"], 1),
                      "original": f.name})
    job.state["user_media"] = items


def assign_user_media(job: Job, script: dict) -> list[str]:
    """Kullanıcı medyasını sahnelere yerleştirir. Senaryo `visual.user` ile atadıysa ona, kalanları sırayla
    fotoğraf/video sahnelerine. Hiçbir yüklenen dosya boşa gitmez; sahne sayısı yetmezse uyarılır."""
    items = job.state.get("user_media") or []
    if not items:
        return []
    import json as _json
    import shutil
    media_dir = job.dir / "media"
    media_dir.mkdir(exist_ok=True)
    names = {it["file"]: it for it in items}
    used, placed = set(), []

    def place(sc: dict, it: dict) -> None:
        src = job.dir / "user_media" / it["file"]
        ext = src.suffix.lower()
        for old in media_dir.glob(f"{sc['id']}.*"):
            old.unlink()
        shutil.copy(src, media_dir / f"{sc['id']}{ext}")
        (media_dir / f"{sc['id']}.json").write_text(_json.dumps(
            {"provider": "user", "title": it.get("original", it["file"]), "license": "kullanıcının kendi medyası",
             "credit": "", "source": ""}, ensure_ascii=False), encoding="utf-8")
        vis = sc["visual"]
        for k in ("pick", "crop", "skip", "url", "reuse"):  # eski aday seçimleri kullanıcı medyasını ezmesin
            vis.pop(k, None)
        vis.update(kind=it["kind"], providers=["agent_media"])
        vis.setdefault("fit", "cover" if it["height"] >= it["width"] else "auto")
        if it["kind"] == "video":
            vis.setdefault("start", 0.0)
        used.add(it["file"])
        placed.append(f"{sc['id']} ← {it.get('original', it['file'])}")

    asked = []  # `user: true` (ya da bilinmeyen ad): sıradaki kullanılmamış dosya
    for sc in script["scenes"]:
        want = sc["visual"].get("user")
        if isinstance(want, str) and want in names and want not in used:
            place(sc, names[want])
        elif want:
            asked.append(sc)
    free = asked + [sc for sc in script["scenes"] if sc["visual"].get("kind") in ("photo", "video")
                    and not sc["visual"].get("user") and not sc["visual"].get("reuse")]
    free += [sc for sc in script["scenes"] if sc["visual"].get("kind") == "graphic" and sc["layout"] not in
             ("list", "compare", "stat") and sc not in free]
    for it in [it for it in items if it["file"] not in used]:
        if not free:
            job.warn(f"yüklenen dosya için uygun sahne kalmadı: {it.get('original', it['file'])}")
            continue
        place(free.pop(0), it)
    return placed


def auto_script(job: Job, cfg: Config, on_line=None) -> dict:
    """Senaryoyu insansız yazar: Claude API (anthropic) veya bilgisayardaki Claude Code (claude_cli)."""
    from . import llm
    provider = llm.resolve_provider(cfg)
    if provider == "manual":
        raise StageError("Otomatik senaryo için ANTHROPIC_API_KEY ya da kurulu Claude Code (`claude`) gerekir")
    brief = read_json(job.dir / "brief.json") or make_brief(job, cfg)
    with job.stage("script") as info:
        if provider == "anthropic":
            script, research = llm.generate(brief, cfg, job.state)
            write_json(job.dir / "research.json", research)
            write_json(job.script_path, script)
        else:
            script = llm.generate_via_claude_cli(job.id, job.dir, job.state.get("topic_hint"), cfg, on_line,
                                                 text=job.state.get("user_text"), draw=job.state.get("draw", False))
        info.update({"provider": provider, "title": script.get("title"), "scenes": len(script["scenes"])})
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
    placed = assign_user_media(job, script)
    if placed:
        L.info("Kullanıcı medyası yerleştirildi: %s", "; ".join(placed))
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
    mcfg = script.get("music") or {}
    subject = mcfg.get("subject") or next((sc["visual"].get("subject") for sc in script["scenes"]
                                            if sc["visual"].get("subject")), None)
    with job.stage("music") as info:
        if job.state.get("user_music"):  # kullanıcının yüklediği müzik her zaman öncelikli
            path = job.dir / job.state["user_music"]
            music = {"path": path, "provider": "user", "title": path.stem, "artist": "", "credit": "", "source": "",
                     "license": "kullanıcının kendi müziği", "license_checked": True,
                     "vocals": audio._looks_vocal(path)}
        else:
            music = audio.pick_music(cfg, queries, job.d("audio"), tl["total"], {x for x in recent if x},
                                     want=mcfg.get("file"), subject=subject)
        if music and not music.get("license_checked", True):
            job.warn(f"müziğin kullanım hakkı doğrulanmadı ({music.get('title')}) — telif riski kullanıcıda")
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
        # HyperFrames lint yalnızca o motorla render edilecekse durdurucu (Remotion aynı veriyi React ile çizer)
        lint = compose.lint(Path(res["dir"])) if compose.engine(cfg) == "hyperframes" else {"errorCount": 0, "engine": "remotion"}
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
        eng = compose.engine(cfg)
        draw = compose.render_remotion if eng == "remotion" else compose.render
        info["engine"] = eng
        try:
            draw(comp, out, cfg)
            info["workers"] = cfg.get_path("render.workers", 4)
        except StageError as exc:
            L.warning("render başarısız (%s); 2 işçi ile yeniden deneniyor", str(exc)[:300])
            draw(comp, out, cfg, workers=2)
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
        owners = {h.get("output"): h.get("job") for h in history()}
        if owners.get(f"output/videos/{slug}.mp4", job.id) != job.id:
            slug = f"{slug}-{job.id[-4:]}"  # aynı gün aynı başlık: başka görevin dosyasının üzerine yazma
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
        if attributions or (music and (music.get("provider") == "openverse" or not music.get("license_checked", True))):
            lines += ["", "Görsel/müzik atıfları:"]
            lines += [f"- {c['scene']}: {c.get('credit') or c.get('title')} ({c.get('license')}"
                      f"{'' if c.get('license_checked', True) else '; kullanım hakkı doğrulanmadı'}) {c.get('source')}"
                      for c in attributions]
            if music and (music.get("provider") == "openverse" or not music.get("license_checked", True)):
                note = "" if music.get("license_checked", True) else "; kullanım hakkı doğrulanmadı"
                lines.append(f"- Müzik: {music.get('credit') or music.get('title')} ({music.get('license')}{note}) "
                             f"{music.get('source')}")
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


# ----------------------------------------------------------------------------
# Kendi kendini test
# ----------------------------------------------------------------------------

def selftest(cfg: Config, render: bool = False) -> dict:
    """Kod, araçlar ve üretim hattını örnek senaryo ile dener. Başarılıysa test görevini siler."""
    import compileall
    import tempfile
    from . import doctor
    from .util import run
    report: dict = {"ok": True, "steps": []}

    def step(name: str, fn):
        t0 = dt.datetime.now()
        try:
            detail = fn() or ""
            report["steps"].append({"step": name, "ok": True, "detail": str(detail)[:300]})
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["steps"].append({"step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:800]})
            raise
        finally:
            report["steps"][-1]["seconds"] = round((dt.datetime.now() - t0).total_seconds(), 1)

    def tools():
        bad = [r["name"] for r in doctor.check(cfg, network=False) if not r["ok"] and r["need"] == "zorunlu"]
        if bad:
            raise StageError("eksik zorunlu bileşen: " + ", ".join(bad))
        return "zorunlu bileşenler tamam"

    def svg():
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "t.svg", Path(d) / "t.png"
            src.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920"><rect width="1080" '
                           'height="1920" fill="#123"/><circle cx="540" cy="900" r="300" fill="#fd3"/></svg>')
            run(["ffmpeg", "-y", "-v", "error", "-i", src, "-frames:v", "1", dst])
            return f"{dst.stat().st_size} bayt"

    job = None
    try:
        step("python_derleme", lambda: compileall.compile_dir(str(ROOT / "scripts"), quiet=1) or
             (_ for _ in ()).throw(StageError("derleme hatası")))
        step("araclar", tools)
        step("svg_cizim", svg)
        example = ROOT / "examples" / "venus-gun-yil" / "script.json"
        job = Job.create("bilim-uzay", "selftest")
        job.script_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        script = load_script(job, cfg)
        metas: dict = {}
        step("seslendirme", lambda: metas.update(stage_voice(job, script, cfg)) or f"{len(metas)} sahne")
        out: dict = {}
        step("altyazi", lambda: out.update(zip(("tl", "words", "groups"), stage_captions(job, script, metas, cfg)))
             or f"{out['tl']['total']:.1f} sn")
        step("gorseller", lambda: out.update(media=stage_visuals(job, script, out["tl"], cfg))
             or f"{sum(1 for m in out['media'].values() if m)} görsel")
        step("muzik", lambda: out.update(music=stage_music(job, script, out["tl"], cfg))
             or (out["music"] or {}).get("provider"))
        step("kurgu_lint", lambda: out.update(res=stage_compose(job, script, out["tl"], metas, out["media"],
                                                                 out["groups"], cfg)) or "lint temiz")
        if render:
            step("render", lambda: out.update(video=stage_render(job, cfg)) or "tamam")
            step("miks", lambda: out.update(final=stage_mix(job, script, out["tl"], out["music"], out["video"], cfg))
                 or "tamam")
            step("kalite_kontrol", lambda: stage_qc(job, script, out["tl"], out["words"], out["final"],
                                                    out["res"]["safe_zone_problems"], cfg)["passed"])
    except Exception:  # noqa: BLE001 — rapor zaten hatayı içeriyor
        pass
    if job and report["ok"]:
        shutil.rmtree(job.dir, ignore_errors=True)
    elif job:
        report["job"] = job.id
    write_json(ROOT / "logs" / "selftest.json", report)
    return report
