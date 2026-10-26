"""Komut satırı arayüzü: python -m selfedit <komut>"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import config, ffmpeg, project, render, telemetry
from .effects import load_registry
from .evolve import daemon, engine, store


def _kv(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"Parametre 'ad=değer' biçiminde olmalı: {it}")
        k, v = it.split("=", 1)
        out[k] = v
    return out


def cmd_new(a):
    project.save(project.new_project(a.width, a.height, a.fps), a.project)
    print(f"Proje oluşturuldu: {a.project}")


def cmd_add(a):
    p = project.load(a.project)
    project.add_clip(p, a.clip, a.start, a.end)
    project.save(p, a.project)
    print(f"Klip eklendi (sıra {len(p['clips']) - 1}).")


def cmd_fx(a):
    p = project.load(a.project)
    project.add_effect(p, a.clip_index, a.effect, _kv(a.params))
    project.save(p, a.project)
    print("Efekt eklendi.")


def cmd_render(a):
    p = project.load(a.project)
    try:
        r = render.render_project(p, a.output, Path(a.project).resolve().parent)
    except (render.RenderError, ffmpeg.FFmpegError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1
    print(f"Hazır: {r['output']} ({r['seconds']} sn)")


def cmd_effects(a):
    reg = load_registry()
    for n in reg.names():
        e = reg.get(n)
        print(f"{n:12} {e.description}  {e.params if e.params else ''}")
    for f, err in reg.errors.items():
        print(f"! yüklenemedi: {f}: {err}")


def cmd_wish(a):
    telemetry.log("wish", text=a.text)
    print("Dileğin kaydedildi; sonraki geliştirme turunda dikkate alınacak.")


def cmd_demo(a):
    d = Path(tempfile.mkdtemp(prefix="selfedit_demo_"))
    ffmpeg.make_test_video(d / "a.mp4", 3, True)
    ffmpeg.make_test_video(d / "b.mp4", 3, False)
    p = project.new_project(640, 360, 30)
    project.add_clip(p, "a.mp4")
    project.add_effect(p, 0, "grayscale")
    project.add_effect(p, 0, "fade")
    project.add_clip(p, "b.mp4", 0, 2)
    project.add_effect(p, 1, "text", {"text": "SelfEdit demo", "start": 0.2, "end": 1.8})
    r = render.render_project(p, a.output, d)
    print(f"Demo hazır: {r['output']}")


def cmd_evolve(a):
    res = engine.run_cycle(offline=a.offline, force=True)
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_proposals(a):
    if a.action == "list":
        for p in store.list_all():
            print(f"{p['id']:40} {p['status']:12} {p['source']:8} {p['title']}")
        return
    if not a.id:
        raise SystemExit("Öneri kimliği gerekli.")
    if a.action == "show":
        p = store.load(a.id)
        print(f"{p['title']}  [{p['status']}]\nNeden: {p['rationale']}\n")
        for s in (p.get("validation") or {}).get("steps", []):
            print(f"  {'✓' if s['ok'] else '✗'} {s['step']}: {s['detail']}")
        print("\n" + p["code"])
    else:
        fn = {"approve": engine.apply, "reject": engine.reject, "rollback": engine.rollback}[a.action]
        res = fn(store.load(a.id)["id"])
        print(res["detail"])
        return 0 if res["ok"] else 1


def cmd_daemon(a):
    if a.action == "run":
        daemon.run(once=a.once, offline=a.offline)
    elif a.action == "stop":
        daemon.request_stop()
        print("Durdurma isteği gönderildi.")
    else:
        print(json.dumps(daemon.read_status(), indent=2, ensure_ascii=False))


def cmd_config(a):
    if a.key:
        config.set_value(a.key, a.value)
    print(json.dumps(config.load(), indent=2, ensure_ascii=False))


def cmd_gui(a):
    from . import gui
    gui.main()


def build_parser():
    ap = argparse.ArgumentParser(prog="selfedit", description="Kendini geliştiren video düzenleyici")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="yeni proje")
    s.add_argument("project"); s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720); s.add_argument("--fps", type=int, default=30)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("add", help="projeye klip ekle")
    s.add_argument("project"); s.add_argument("clip")
    s.add_argument("--start", type=float, default=0); s.add_argument("--end", type=float)
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("fx", help="klibe efekt ekle: fx proje.json 0 fade in_s=1")
    s.add_argument("project"); s.add_argument("clip_index", type=int); s.add_argument("effect")
    s.add_argument("params", nargs="*"); s.set_defaults(fn=cmd_fx)

    s = sub.add_parser("render", help="videoyu dışa aktar")
    s.add_argument("project"); s.add_argument("output"); s.set_defaults(fn=cmd_render)

    sub.add_parser("effects", help="efekt listesi").set_defaults(fn=cmd_effects)

    s = sub.add_parser("wish", help="eksik bir özelliği iste"); s.add_argument("text"); s.set_defaults(fn=cmd_wish)

    s = sub.add_parser("demo", help="örnek video üret"); s.add_argument("output", nargs="?", default="demo.mp4")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("evolve", help="bir geliştirme turu çalıştır")
    s.add_argument("--offline", action="store_true", help="Claude API yerine şablon kütüphanesi")
    s.set_defaults(fn=cmd_evolve)

    s = sub.add_parser("proposals", help="önerileri yönet")
    s.add_argument("action", choices=["list", "show", "approve", "reject", "rollback"])
    s.add_argument("id", nargs="?"); s.set_defaults(fn=cmd_proposals)

    s = sub.add_parser("daemon", help="arka plan servisi")
    s.add_argument("action", choices=["run", "status", "stop"])
    s.add_argument("--once", action="store_true"); s.add_argument("--offline", action="store_true")
    s.set_defaults(fn=cmd_daemon)

    s = sub.add_parser("config", help="ayarları göster/değiştir: config mode auto")
    s.add_argument("key", nargs="?"); s.add_argument("value", nargs="?"); s.set_defaults(fn=cmd_config)

    sub.add_parser("gui", help="masaüstü arayüzü").set_defaults(fn=cmd_gui)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except (ffmpeg.FFmpegError, KeyError, ValueError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
