"""Bilgi haritası (Graphify, github.com/Graphify-Labs/graphify, Apache-2.0 / MIT).

İki grafik:
  içerik : üretilen videolar (başlık, kategori, anlatım, doğrulanmış bilgiler, kaynaklar), Reel notları ve
           buluttan gelen video geçmişi → knowledge/corpus/*.md → `graphify extract` (Claude Code veya Claude API
           ile anlamsal çıkarım) → knowledge/corpus/graphify-out/{graph.html, GRAPH_REPORT.md, graph.json}.
           Konu seçerken brief.json → knowledge_map: işlenmiş kavramlar ve aralarındaki bağlar (tekrar etme,
           bağlantılardan yeni konu bul).
  kod    : scripts/ klasörünün yapısal haritası (`graphify update`, yapay zekâ gerekmez, yerel) — bulut rutininin
           kendi kendini onarma adımında kodda gezinmek için (scripts/graphify-out/GRAPH_REPORT.md, `graphify query`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import log
from .config import ROOT, load_config, secret
from .util import StageError, read_json, slugify

L = log.get("knowledge")
BASE = ROOT / "knowledge"
CORPUS = BASE / "corpus"
OUT = CORPUS / "graphify-out"


def available() -> bool:
    try:
        import graphify  # noqa: F401
        return True
    except ImportError:
        return False


def _graphify(*args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    if not available():
        raise StageError("Graphify kurulu değil: pip install graphifyy")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "graphify", *args], cwd=ROOT, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)


def build_corpus() -> dict:
    """Bilgi kaynaklarını Markdown belgelerine yazar (yalnızca knowledge/corpus altını yeniler)."""
    if CORPUS.exists():
        for d in ("videolar", "notlar", "gecmis"):
            shutil.rmtree(CORPUS / d, ignore_errors=True)
    counts = {"videolar": 0, "notlar": 0, "gecmis": 0}
    vdir = CORPUS / "videolar"
    vdir.mkdir(parents=True, exist_ok=True)
    for sp in sorted((ROOT / "projects").glob("*/script.json")):
        s = read_json(sp, {}) or {}
        if not s.get("title"):
            continue
        state = read_json(sp.parent / "job.json", {}) or {}
        narration = "\n".join(f"- {sc.get('narration', '')}" for sc in s.get("scenes", []))
        facts = "\n".join(f"- {f}" for f in s.get("facts", []) if isinstance(f, str))
        srcs = "\n".join(f"- {x.get('title', '')} — {x.get('publisher', '')} {x.get('url', '')}"
                         for x in s.get("sources", []) if isinstance(x, dict))
        md = (f"# {s['title']}\n\nTür: üretilmiş Reels videosu · Kategori: {state.get('category') or s.get('category', '')}"
              f" · Tarih: {str(state.get('created', ''))[:10]}\n\n## Anlatım\n{narration}\n\n"
              f"## Doğrulanmış bilgiler\n{facts or '-'}\n\n## Kaynaklar\n{srcs or '-'}\n")
        (vdir / f"{slugify(s['title'], 60)}.md").write_text(md, encoding="utf-8")
        counts["videolar"] += 1
    from .notes import vault
    ndir = CORPUS / "notlar"
    ndir.mkdir(parents=True, exist_ok=True)
    for f in sorted(vault().glob("*.md")) if vault().exists() else []:
        text = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith("![["))
        (ndir / f"{slugify(f.stem, 60)}.md").write_text(text, encoding="utf-8")
        counts["notlar"] += 1
    hist = read_json(ROOT / "output" / "cloud" / "history.json", []) or []
    hist += read_json(ROOT / "projects" / "_history.json", []) or []
    seen, rows = set(), []
    for h in hist:
        if h.get("title") and h["title"] not in seen:
            seen.add(h["title"])
            rows.append(f"- {h.get('date', '')} · {h.get('category', '')} · {h['title']}")
    if rows:
        (CORPUS / "gecmis").mkdir(exist_ok=True)
        (CORPUS / "gecmis" / "yayinlanan-videolar.md").write_text(
            "# Üretilen videoların listesi\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
        counts["gecmis"] = len(rows)
    return counts


def backend() -> str | None:
    from .llm import claude_cli
    if secret("ANTHROPIC_API_KEY"):
        return "claude"
    if claude_cli():
        return "claude-cli"
    return None


def build_graph() -> dict:
    """İçerik bilgi haritasını kurar/günceller. Claude yoksa çalışmaz (belgelerin anlamsal çıkarımı gerekir)."""
    counts = build_corpus()
    if not sum(counts.values()):
        raise StageError("Haritaya eklenecek içerik yok (önce video üretin veya not çıkarın)")
    be = backend()
    if not be:
        raise StageError("Bilgi haritası için Claude gerekli (bilgisayardaki Claude Code veya ANTHROPIC_API_KEY)")
    L.info("Bilgi haritası kuruluyor (%s; %s)…", be, counts)
    p = _graphify("extract", str(CORPUS), "--backend", be)
    if p.returncode != 0 or not (OUT / "graph.json").exists():
        raise StageError("Graphify hatası: " + (p.stderr or p.stdout)[-600:])
    c = _graphify("cluster-only", str(CORPUS), f"--backend={be}")  # topluluk adları, rapor, graph.html
    if c.returncode != 0:
        L.warning("Graphify kümeleme/rapor uyarısı: %s", (c.stderr or c.stdout)[-300:])
    L.info("Bilgi haritası hazır: %s", OUT / "graph.html")
    return {"counts": counts, "backend": be, **summary()}


def code_graph() -> Path:
    """Kod haritası (yapay zekâsız, yerel): scripts/graphify-out."""
    p = _graphify("update", "scripts", timeout=600)
    if p.returncode not in (0, 2) or not (ROOT / "scripts" / "graphify-out" / "graph.json").exists():
        raise StageError("Graphify kod haritası kurulamadı: " + (p.stderr or p.stdout)[-400:])
    return ROOT / "scripts" / "graphify-out" / "GRAPH_REPORT.md"


def summary(limit: int = 25) -> dict:
    """En bağlantılı kavramlar ve topluluklar (konu seçimine girdi)."""
    g = read_json(OUT / "graph.json")
    if not g:
        return {"ready": False}
    nodes = g.get("nodes") or []
    links = g.get("links") or g.get("edges") or []
    deg: dict[str, int] = {}
    for e in links:
        for k in ("source", "target"):
            deg[str(e.get(k))] = deg.get(str(e.get(k)), 0) + 1
    label = {str(n.get("id")): n.get("label") or n.get("name") or str(n.get("id")) for n in nodes}
    top = sorted(deg, key=lambda k: -deg[k])[:limit]
    report = (OUT / "GRAPH_REPORT.md").read_text(encoding="utf-8") if (OUT / "GRAPH_REPORT.md").exists() else ""
    return {"ready": True, "nodes": len(nodes), "edges": len(links),
            "top_concepts": [label.get(k, k) for k in top], "report": report[:6000],
            "updated": (OUT / "graph.json").stat().st_mtime}


def brief_context() -> dict | None:
    """brief.json için kısa bağlam (harita yoksa None)."""
    s = summary(30)
    if not s.get("ready"):
        return None
    return {"covered_concepts": s["top_concepts"],
            "note": "Bu kavramlar daha önce işlendi: aynı konuyu tekrarlama; bağlantılardan yeni, ilgili bir konu seç. "
                    "Ayrıntı: knowledge/corpus/graphify-out/GRAPH_REPORT.md, sorgu: python -m graphify query \"...\" "
                    "--graph knowledge/corpus/graphify-out/graph.json"}


def query(question: str) -> str:
    p = _graphify("query", question, "--graph", str(OUT / "graph.json"), timeout=120)
    return (p.stdout or p.stderr)[-8000:]


def info() -> dict:
    return {"available": available(), "backend": backend(), **summary(15)}
