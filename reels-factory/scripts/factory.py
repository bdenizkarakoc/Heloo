#!/usr/bin/env python3
"""Otonom AI Reels Fabrikası — komut satırı.

Kullanım (reels-factory/ klasöründen):
  python scripts/factory.py doctor                     # ortam ve hizmet denetimi
  python scripts/factory.py new [--category C] [--topic "..."]
  python scripts/factory.py validate <görev>           # script.json doğrulama
  python scripts/factory.py produce <görev> [--from voice]
  python scripts/factory.py run [--category C] [--count N]   # tam otonom (ANTHROPIC_API_KEY)
  python scripts/factory.py candidates <görev> <sahne> [--query "..."]   # görsel adayları
  python scripts/factory.py status [<görev>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):  # Windows konsolu (cp1254) ✔/✖ işaretlerinde çökmesin
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from reels import doctor, log, pipeline  # noqa: E402
from reels.config import ROOT, load_config  # noqa: E402
from reels.job import Job  # noqa: E402
from reels.script_model import normalize, validate  # noqa: E402
from reels.util import StageError  # noqa: E402


def cmd_doctor(args, cfg) -> int:
    rows = doctor.check(cfg, network=not args.offline)
    bad = 0
    for r in rows:
        mark = "✔" if r["ok"] else ("✖" if r["need"] == "zorunlu" else "–")
        if not r["ok"] and r["need"] == "zorunlu":
            bad += 1
        print(f" {mark} {r['name']:<22} {r['detail']}")
    print("\nKullanılabilir üretim yöntemleri:")
    for k, v in doctor.capabilities(cfg).items():
        print(f"   {k:<12} {v}")
    print("\nDurum:", "HAZIR" if not bad else f"{bad} zorunlu bileşen eksik")
    return 0 if not bad else 1


def cmd_new(args, cfg) -> int:
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
    job = pipeline.new_job(cfg, args.category, args.topic, text=text, draw=args.draw)
    from reels.llm import resolve_provider
    provider = resolve_provider(cfg)
    if provider != "manual" and not args.manual:
        pipeline.auto_script(job, cfg)
        print(f"Görev {job.id}: senaryo {provider} ile yazıldı → {job.script_path.relative_to(ROOT)}")
    else:
        print(f"Görev oluşturuldu: {job.id}")
        print(f"Brif: {(job.dir / 'brief.json').relative_to(ROOT)}")
        print(f"Sonraki adım: skills/reels-production/SKILL.md akışıyla araştır ve "
              f"{job.script_path.relative_to(ROOT)} dosyasını yaz, ardından:\n"
              f"  python scripts/factory.py validate {job.id}\n  python scripts/factory.py produce {job.id}")
    return 0


def cmd_validate(args, cfg) -> int:
    job = Job.load(args.job)
    if not job.script_path.exists():
        print(f"✖ senaryo yok: {job.script_path}")
        return 1
    script = normalize(json.loads(job.script_path.read_text(encoding="utf-8")), cfg)
    probs = validate(script, cfg)
    from reels.script_model import estimate_seconds
    est = estimate_seconds(script, cfg.get_path("script.words_per_second", 2.3))
    for p in probs:
        print(("! " if p.startswith("UYARI") else "✖ ") + p)
    errs = [p for p in probs if not p.startswith("UYARI")]
    print(f"{'✔ geçerli' if not errs else '✖ geçersiz'} — {len(script['scenes'])} sahne, tahmini {est:.0f} sn")
    return 0 if not errs else 1


def cmd_produce(args, cfg) -> int:
    job = Job.load(args.job)
    out = pipeline.produce(job, cfg, from_stage=args.from_stage, autofix=not args.no_autofix)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args, cfg) -> int:
    from reels.llm import resolve_provider
    if resolve_provider(cfg) == "manual":
        print("Tam otonom mod için ANTHROPIC_API_KEY ya da kurulu ve girişli Claude Code (`claude`) gerekir.\n"
              "Claude Code oturumunda 'reels-production' becerisini kullanın.")
        return 2
    failures = 0
    for _ in range(args.count):
        job = pipeline.new_job(cfg, args.category, args.topic)
        try:
            pipeline.auto_script(job, cfg)
            out = pipeline.produce(job, cfg)
            print(f"✔ {job.id} → {out['video']}")
        except StageError as exc:
            failures += 1
            print(f"✖ {job.id} başarısız: {exc}")
    return 0 if not failures else 1


def cmd_candidates(args, cfg) -> int:
    """Bir sahne için ücretsiz kaynaklardaki görsel adaylarını listeler ve inceleme görüntüsü üretir."""
    from reels import visuals
    from reels.script_model import normalize
    job = Job.load(args.job)
    script = normalize(json.loads(job.script_path.read_text(encoding="utf-8")), cfg)
    scene = next((s for s in script["scenes"] if s["id"] == args.scene), None)
    if scene is None:
        print(f"sahne bulunamadı: {args.scene}")
        return 1
    if args.query:
        scene["visual"]["query"] = args.query
    providers = cfg.get_path(f"categories.{job.state['category']}.visual_providers", ["openverse"])
    found = visuals.search_candidates(scene, job.dir, cfg, providers, limit=args.limit)
    for name, cands in found.items():
        for i, c in enumerate(cands):
            print(f"{name}:{i:<3} {str(c.get('w')):>5}x{str(c.get('h')):<5} {c.get('license', '')[:18]:<18} "
                  f"{c.get('title', '')[:70]}  {c.get('source', '')}")
    sheet = visuals.candidates_sheet(found, job.dir / "qc" / f"candidates_{scene['id']}.jpg",
                                     cfg.path(cfg.get_path("brand.font_file")))
    print(f"\nİnceleme görüntüsü: {sheet.relative_to(ROOT)}")
    print('Seçim için script.json → visual.pick: "<sağlayıcı>:<sıra>" (gerekirse visual.query ile birlikte)')
    return 0


def cmd_selftest(args, cfg) -> int:
    rep = pipeline.selftest(cfg, render=args.render)
    for st in rep["steps"]:
        print(f" {'✔' if st['ok'] else '✖'} {st['step']:<16} {st['seconds']:>6.1f} sn  {st['detail']}")
    print("SONUÇ:", "BAŞARILI" if rep["ok"] else f"BAŞARISIZ (görev klasörü: projects/{rep.get('job')})")
    return 0 if rep["ok"] else 1


def cmd_hook(args, cfg) -> int:
    from reels.yt_tools import hook_score
    rows = sorted((hook_score(h) for h in args.hooks), key=lambda r: -r["verdict"])
    for r in rows:
        print(f"\n  {r['hook']}")
        for k, v in r["properties"].items():
            print(f"    {k:<12} {v:3d}  {'#' * (v // 5)}")
        print(f"    PUAN         {r['verdict']:3d}  {r['band_tr']}   kalıp: {r['formula']}")
        print(f"    en zayıf     {r['weakest']} → {r['fix']}")
    if len(rows) > 1:
        print(f"\n  kazanan: {rows[0]['hook']} ({rows[0]['verdict']})")
    return 0


def cmd_title(args, cfg) -> int:
    from reels.yt_tools import title_check
    for t in args.titles:
        r = title_check(t, args.thumb)
        print(f'\n  "{r["title"]}"  {r["chars"]} karakter, puan {r["score"]}/100')
        for i in r["issues_tr"]:
            print(f"    ✖ {i}")
        for g in r["good"]:
            print(f"    ✔ {g}")
    return 0


def cmd_chapters(args, cfg) -> int:
    from reels.yt_tools import chapters, edl
    if args.edl:
        r = edl(Path(args.srt), args.floor)
        for c in r["cuts"]:
            print(f"  {c['kind']:<7} {c['start']:8.2f} → {c['end']:8.2f}  {c['why']}")
        print(f"  {len(r['cuts'])} kesim, {r['removed']} sn çıkar → {r['out']} sn")
        return 0
    r = chapters(Path(args.srt), args.target)
    print(r.get("text") or r.get("reason"))
    print("✔ YouTube kurallarına uygun" if r["valid"] else "✖ geçersiz (en az 3 bölüm, 00:00 ile başlamalı, her biri ≥10 sn)")
    return 0 if r["valid"] else 1


def cmd_status(args, cfg) -> int:
    jobs = [Job.load(args.job)] if args.job else Job.all()
    for job in jobs:
        st = job.state
        stages = " ".join(f"{s}:{v.get('status', '?')[0]}" for s, v in st.get("stages", {}).items())
        print(f"{job.id:<40} {st.get('status', '?'):<10} {stages}")
        if args.job:
            for s, v in st.get("stages", {}).items():
                if v.get("error"):
                    print(f"   ✖ {s}: {v['error'][:400]}")
            for w in st.get("warnings", [])[-10:]:
                print(f"   ! {w['msg']}")
            if st.get("outputs"):
                print("   çıktılar:", json.dumps(st["outputs"], ensure_ascii=False))
    return 0


def cmd_kesim(args, cfg) -> int:
    from reels import kesim
    if args.mode:
        kesim.save_settings({"mode": args.mode})
    answers = {"serbest": args.istek or ""}
    if args.ref:  # bağlantı (Instagram/TikTok/YouTube) ya da referans video dosyası
        answers["reference"] = {"file": str(Path(args.ref).expanduser().resolve())} if Path(args.ref).expanduser().is_file() \
            else {"url": args.ref}
    for k in ("tarz", "sure", "altyazi", "muzik", "efekt", "renk", "tempo"):
        if getattr(args, k):
            answers[k] = getattr(args, k)
    proj = kesim.montage([Path(f).expanduser().resolve() for f in args.files],
                         answers=answers if any(answers.values()) else None)
    for c in proj.get("clips", []):
        print(f"✔ {c.get('output')}  ({c.get('duration', 0):.1f} sn)")
    for d in proj.get("delivered", []):
        print(f"  Hazır: {d}")
    for n in proj.get("notes", []):
        print(f"  · {n}")
    return 0 if proj.get("status") == "done" else 1


def cmd_foto(args, cfg) -> int:
    """Fotoğraflarım (Masaüstü/kesim/Fotoğraflarım) kutusundaki fotoğraflardan video."""
    from reels import photos
    items = photos.list_photos()
    if args.list or not (args.names or args.son):
        print(f"Klasör: {photos.photo_dir()}  ({len(items)} fotoğraf, en yeni önce)")
        for it in items[:60]:
            print(f"  {it['name']}")
        return 0
    names = list(args.names) or [it["name"] for it in items[:args.son]][::-1]   # --son N: en yeni N, çekim sırasıyla
    if args.anlat:  # seslendirmeli video fabrika hattında üretilir: çalışan uygulamanın kuyruğuna ekle
        import json
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8765/api/photos/video", method="POST",
                                     data=json.dumps({"photos": names, "mode": "anlatim", "istek": args.anlat}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except OSError as exc:
            raise StageError(f"uygulama kapalı (python app/server.py): {exc}") from exc
        print(r.get("error") or f"✔ Anlatımlı video kuyruğa eklendi ({r['count']} fotoğraf); bitince Masaüstü\\kesim\\Hazır")
        return 1 if r.get("error") else 0
    from reels import kesim
    proj = kesim.montage(photos.to_uploads(names), answers={"serbest": args.istek} if args.istek else None)
    for c in proj.get("clips", []):
        print(f"✔ {c.get('output')}  ({c.get('duration', 0):.1f} sn)")
    for d in proj.get("delivered", []):
        print(f"  Hazır: {d}")
    return 0 if proj.get("status") == "done" else 1


def cmd_mcp(args, cfg) -> int:
    from reels import mcp_setup
    if args.list:
        for name, conf, note in mcp_setup.servers():
            print(f"{'✔' if conf else '–'} {name:<16} {note}")
        return 0
    res = mcp_setup.register()
    for r in res["rows"]:
        print(f"{r['status']:<8} {r['name']:<16} {r['note']}")
    print(res["message"])
    return 0 if res["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Otonom AI Reels Fabrikası")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor", help="ortam denetimi")
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("new", help="yeni üretim görevi")
    p.add_argument("--category")
    p.add_argument("--topic")
    p.add_argument("--manual", action="store_true", help="senaryoyu otomatik yazma (ajan elle yazacak)")
    p.add_argument("--text", help="kendi metnin: incelenip doğrulanarak videoya çevrilir")
    p.add_argument("--text-file", help="metni dosyadan oku")
    p.add_argument("--draw", action="store_true", help="görselleri ajan kendisi SVG illüstrasyon olarak çizsin")
    p = sub.add_parser("validate", help="senaryoyu doğrula")
    p.add_argument("job")
    p = sub.add_parser("produce", help="senaryodan videoya üretim")
    p.add_argument("job")
    p.add_argument("--from", dest="from_stage")
    p.add_argument("--no-autofix", action="store_true")
    p = sub.add_parser("run", help="tam otonom üretim (Claude API)")
    p.add_argument("--category")
    p.add_argument("--topic")
    p.add_argument("--count", type=int, default=1)
    p = sub.add_parser("candidates", help="sahne için görsel adaylarını listele")
    p.add_argument("job")
    p.add_argument("scene")
    p.add_argument("--query", help="farklı bir arama sorgusu dene")
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("selftest", help="sistemi örnek senaryo ile dene")
    p.add_argument("--render", action="store_true", help="render, miks ve kalite kontrolünü de dene")
    p = sub.add_parser("hook", help="kanca puanı (YouTube agent skill, Türkçe uyarlama)")
    p.add_argument("hooks", nargs="+", help="bir veya birden çok kanca cümlesi")
    p = sub.add_parser("title", help="başlık + kapak yazısı denetimi")
    p.add_argument("titles", nargs="+")
    p.add_argument("--thumb", help="kapak yazısı")
    p = sub.add_parser("chapters", help="SRT'den YouTube bölümleri (veya --edl: kesim listesi)")
    p.add_argument("srt")
    p.add_argument("--target", type=int, default=7)
    p.add_argument("--edl", action="store_true", help="boşluk/dolgu/tekrar kesim listesi")
    p.add_argument("--floor", type=float, default=0.45)
    p = sub.add_parser("kesim", help="Kesim: dosyaları tek adımda montajla (öğrenilen stil, ses, altyazı, müzik)")
    p.add_argument("files", nargs="+")
    p.add_argument("--mode", choices=["auto", "full", "clips"])
    p.add_argument("--ref", help="şuna benzet: Instagram/TikTok/YouTube bağlantısı veya referans video dosyası")
    p.add_argument("--istek", help='serbest istek, ör. "enerjik, lo-fi müzik, geçişlerde vınlama, 30 sn"')
    from reels.brief import QUESTIONS
    for key, label, choices in QUESTIONS:
        p.add_argument(f"--{key}", choices=[v for v, _ in choices], help=label)
    p = sub.add_parser("foto", help="Fotoğraflarım kutusundaki fotoğraflardan video (montaj ya da --anlat)")
    p.add_argument("names", nargs="*", help="fotoğraf adları (Fotoğraflarım klasörüne göre); boşsa listeler")
    p.add_argument("--son", type=int, default=0, help="en yeni N fotoğrafı kullan")
    p.add_argument("--istek", help='montaj isteği, ör. "neşeli müzik, 30 sn"')
    p.add_argument("--anlat", help="seslendirmeli, altyazılı video: ne anlatılacağı (uygulama açık olmalı)")
    p.add_argument("--list", action="store_true")
    p = sub.add_parser("mcp", help="MCP sunucularını Claude Code'a kaydet (reels-fabrikasi, playwright, github...)")
    p.add_argument("--list", action="store_true", help="yalnızca listele, kaydetme")
    p = sub.add_parser("status", help="görev durumları")
    p.add_argument("job", nargs="?")
    args = ap.parse_args()

    log.setup_logging(args.verbose)
    cfg = load_config()
    handlers = {"doctor": cmd_doctor, "new": cmd_new, "validate": cmd_validate, "produce": cmd_produce,
                "run": cmd_run, "status": cmd_status, "candidates": cmd_candidates, "selftest": cmd_selftest,
                "hook": cmd_hook, "title": cmd_title, "chapters": cmd_chapters, "mcp": cmd_mcp, "kesim": cmd_kesim,
                "foto": cmd_foto}
    try:
        return handlers[args.cmd](args, cfg)
    except (StageError, FileNotFoundError) as exc:
        log.get("cli").error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
