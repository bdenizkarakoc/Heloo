"""Yerel kullanım kaydı. Dışarı hiçbir şey gönderilmez; sadece iyileştirme motoru okur."""
import json
import time
from collections import Counter

from . import paths


def _file():
    return paths.data() / "telemetry.jsonl"


def log(event: str, **data) -> None:
    rec = {"ts": time.time(), "event": event, **data}
    try:
        with _file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # kayıt tutulamıyorsa uygulama çalışmaya devam eder


def read(days: float = 30) -> list:
    cutoff = time.time() - days * 86400
    out = []
    try:
        with _file().open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("ts", 0) >= cutoff:
                    out.append(rec)
    except OSError:
        pass
    return out


def summarize(days: float = 30) -> dict:
    recs = read(days)
    ok = [r for r in recs if r["event"] == "render_ok"]
    fail = [r for r in recs if r["event"] == "render_fail"]
    fail_fx = Counter(fx for r in fail for fx in r.get("effects", []))
    unknown = Counter(r.get("name", "?") for r in recs if r["event"] == "unknown_effect")
    used = Counter(fx for r in ok for fx in r.get("effects", []))
    wishes = [r.get("text", "") for r in recs if r["event"] == "wish"][-10:]
    avg = sum(r.get("seconds", 0) for r in ok) / len(ok) if ok else 0.0
    return {
        "renders_ok": len(ok),
        "renders_failed": len(fail),
        "avg_render_seconds": round(avg, 2),
        "effects_used": dict(used.most_common(10)),
        "failing_effects": dict(fail_fx.most_common(5)),
        "unknown_effects_requested": dict(unknown.most_common(10)),
        "last_errors": [r.get("error", "")[-300:] for r in fail[-3:]],
        "wishes": wishes,
    }
