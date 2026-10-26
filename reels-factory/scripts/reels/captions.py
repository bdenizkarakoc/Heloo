"""Zaman çizelgesi ve altyazılar.

Seslendirme saattir: her sahnenin görüntüsü, kendi seslendirmesinin biraz önünde başlar,
geçiş süresi kadar bir sonraki sahnenin altında kalır. Altyazı grupları kelime zamanlarından üretilir.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .util import norm_word, tr_upper

BREAK_PUNCT = tuple(".!?…,;:")


def build_timeline(script: dict, voice: dict[str, dict], cfg: Config) -> dict:
    lead = float(cfg.get_path("tts.lead_in", 0.15))
    gap = float(cfg.get_path("tts.scene_gap", 0.28))
    tail = float(cfg.get_path("tts.tail", 1.8))
    overlap = float(cfg.get_path("render.transition_overlap", 0.4))
    pre = 0.18  # görüntü kesimi sesi bu kadar önden karşılar (J-cut)

    rows = []
    t = lead
    for sc in script["scenes"]:
        v = voice[sc["id"]]
        rows.append({"id": sc["id"], "voice_start": round(t, 3), "voice_end": round(t + v["duration"], 3)})
        t += v["duration"] + gap
    cuts = []
    for i, r in enumerate(rows):
        if i == 0:
            cuts.append(0.0)
        else:
            cuts.append(round(max(rows[i - 1]["voice_end"] + 0.04, r["voice_start"] - pre), 3))
    total = round(rows[-1]["voice_end"] + tail, 3)
    for i, r in enumerate(rows):
        r["start"] = cuts[i]
        last = i == len(rows) - 1
        r["end"] = total if last else round(min(total, cuts[i + 1] + overlap), 3)
        r["duration"] = round(r["end"] - r["start"], 3)
        r["next_cut"] = None if last else cuts[i + 1]
        r["exit_at"] = None if last else round(cuts[i + 1] - r["start"], 3)  # sahne yerel zamanı
        r["voice_local"] = round(r["voice_start"] - r["start"], 3)
    return {"total": total, "scenes": rows, "overlap": overlap}


def absolute_words(script: dict, voice: dict[str, dict], timeline: dict) -> list[dict]:
    rows = {r["id"]: r for r in timeline["scenes"]}
    out = []
    for sc in script["scenes"]:
        emph = {norm_word(w) for w in sc.get("emphasis", []) if norm_word(w)}
        for w in voice[sc["id"]]["words"]:
            a = rows[sc["id"]]["voice_start"]
            out.append({
                "scene": sc["id"],
                "text": w["text"],
                "start": round(a + w["start"], 3),
                "end": round(a + w["end"], 3),
                "emph": norm_word(w["text"]) in emph,
                "captions": bool(sc.get("captions", True)),
            })
    return out


def caption_groups(words: list[dict], cfg: Config) -> list[dict]:
    max_words = int(cfg.get_path("captions.max_words", 3))
    max_chars = int(cfg.get_path("captions.max_chars", 20))
    pause = float(cfg.get_path("captions.pause_break", 0.15))
    upper = bool(cfg.get_path("captions.uppercase", True))

    groups: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        if not w["captions"]:
            if cur:
                groups.append(cur)
                cur = []
            continue
        if cur:
            chars = sum(len(x["text"]) + 1 for x in cur) + len(w["text"])
            gap = w["start"] - cur[-1]["end"]
            if (len(cur) >= max_words or chars > max_chars or gap >= pause
                    or cur[-1]["text"].endswith(BREAK_PUNCT) or w["scene"] != cur[-1]["scene"]):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    out = []
    for gi, g in enumerate(groups):
        start = max(0.05, g[0]["start"] - 0.06)
        end = g[-1]["end"] + 0.25
        out.append({
            "id": f"cg{gi}",
            "start": round(start, 3),
            "end": round(end, 3),
            "words": [{
                "text": tr_upper(w["text"]) if upper else w["text"],
                "start": w["start"],
                "end": w["end"],
                "emph": w["emph"],
            } for w in g],
        })
    # Gruplar çakışmasın; kısa boşluklarda bir önceki grup bir sonrakine kadar kalsın.
    for a, b in zip(out, out[1:]):
        if a["end"] > b["start"] - 0.02:
            a["end"] = round(b["start"] - 0.02, 3)
        elif b["start"] - a["end"] < 0.45:
            a["end"] = round(b["start"] - 0.02, 3)
    return out


def _split_balanced(ws: list[dict], max_len: int) -> list[list[dict]]:
    """Kelime dizisini max_len karakteri aşmayan, mümkünse virgülden bölünmüş parçalara ayırır."""
    text_len = len(" ".join(w["text"] for w in ws))
    if text_len <= max_len or len(ws) < 2:
        return [ws]
    mid = text_len / 2
    best, best_score, pos = 1, None, 0
    for i in range(1, len(ws)):
        pos += len(ws[i - 1]["text"]) + 1
        score = abs(pos - mid) - (12 if ws[i - 1]["text"].endswith((",", ";", ":")) else 0)
        if best_score is None or score < best_score:
            best, best_score = i, score
    return _split_balanced(ws[:best], max_len) + _split_balanced(ws[best:], max_len)


def _two_lines(text: str, line_len: int) -> str:
    if len(text) <= line_len:
        return text
    words = text.split(" ")
    mid = len(text) / 2
    best, best_score, pos = 1, None, 0
    for i in range(1, len(words)):
        pos += len(words[i - 1]) + 1
        score = abs(pos - mid) - (10 if words[i - 1].endswith((",", ";", ":")) else 0)
        if best_score is None or score < best_score:
            best, best_score = i, score
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def srt_cues(words: list[dict], line_len: int = 42) -> list[dict]:
    """Platformlara yüklenecek SRT: cümle bazlı, en fazla iki satır, orijinal yazım."""
    sentences, cur = [], []
    for w in words:
        if cur and w["scene"] != cur[-1]["scene"]:
            sentences.append(cur)
            cur = []
        cur.append(w)
        if w["text"].endswith((".", "!", "?", "…")):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    cues = []
    for sent in sentences:
        for part in _split_balanced(sent, line_len * 2):
            text = " ".join(x["text"] for x in part)
            cues.append({"start": part[0]["start"], "end": part[-1]["end"] + 0.2,
                         "text": _two_lines(text, line_len)})
    return cues


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[dict], path: Path) -> Path:
    lines = []
    for i, c in enumerate(cues, 1):
        end = c["end"]
        if i < len(cues):
            end = min(end, cues[i]["start"] - 0.01)
        lines += [str(i), f"{_ts(c['start'])} --> {_ts(end)}", c["text"], ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
