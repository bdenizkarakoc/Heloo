"""Bulutta üretilen videoları (GitHub 'reels-videos' dalı) bu bilgisayara indirir.

Bulut rutini videoları `scripts/deliver.sh` ile `reels-videos` dalına `videos/<tarih>/` altında yükler.
Burada yalnızca `git fetch` ile dal çekilir ve eksik dosyalar `output/cloud/<tarih>/` klasörüne yazılır;
var olan dosyaların üzerine yazılmaz, hiçbir şey silinmez. Kimlik bilgisi gerekmez: depo nasıl
klonlandıysa (Git Credential Manager vb.) aynı erişim kullanılır.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from . import log

L = log.get("cloud")
BRANCH = "reels-videos"
REF = f"refs/remotes/origin/{BRANCH}"
ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "output" / "cloud"
KEEP = (".mp4", ".jpg", ".txt", ".srt")


def _git(*args: str, binary: bool = False, timeout: float = 600) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # arka planda şifre sorup takılmasın
    kw = {} if binary else {"encoding": "utf-8", "errors": "replace"}  # Windows'ta cp1254 değil UTF-8
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=timeout, env=env, **kw)


def sync() -> dict:
    """Dalı çeker, yeni dosyaları indirir. Dönen sözlük: ok, new (yeni video adları), error."""
    res = {"ok": False, "new": [], "error": None, "time": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        f = _git("fetch", "-q", "origin", f"+refs/heads/{BRANCH}:{REF}")
        if f.returncode != 0:
            err = (f.stderr or "").strip()
            res["error"] = ("Bulutta henüz video yok" if "couldn't find remote ref" in err
                            else f"GitHub'a erişilemedi: {err[-300:]}")
            return res
        ls = _git("ls-tree", "-r", "--full-tree", "--name-only", REF, "videos/")
        for name in ls.stdout.split("\n"):
            if not name.lower().endswith(KEEP):
                continue
            target = DEST / Path(name).relative_to("videos")
            if target.exists():
                continue
            blob = _git("show", f"{REF}:{name}", binary=True)
            if blob.returncode != 0:
                L.warning("İndirilemedi: %s", name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(blob.stdout)
            tmp.replace(target)
            if target.suffix == ".mp4":
                res["new"].append(target.stem)
        hist = _git("show", f"{REF}:history.json")
        if hist.returncode == 0:
            DEST.mkdir(parents=True, exist_ok=True)
            (DEST / "history.json").write_text(hist.stdout, encoding="utf-8")
        res["ok"] = True
        if res["new"]:
            L.info("Buluttan %d yeni video indirildi: %s", len(res["new"]), ", ".join(res["new"]))
    except FileNotFoundError:
        res["error"] = "git bulunamadı (Git for Windows kurulu olmalı)"
    except Exception as exc:  # noqa: BLE001 — eşitleme hatası uygulamayı durdurmamalı
        res["error"] = str(exc)
    if res["error"]:
        L.warning("Bulut eşitleme: %s", res["error"])
    return res


def videos() -> list[dict]:
    """İndirilmiş bulut videoları, en yeni önce. Yollar /output/ altına görelidir."""
    titles = {}
    try:
        for h in json.loads((DEST / "history.json").read_text(encoding="utf-8")):
            titles[Path(h.get("output", "")).stem] = h.get("title")
    except (OSError, ValueError):
        pass
    out = []
    for mp4 in DEST.glob("*/*.mp4"):
        rel = mp4.relative_to(ROOT).as_posix()
        side = {ext: (mp4.with_suffix(ext).relative_to(ROOT).as_posix() if mp4.with_suffix(ext).exists() else None)
                for ext in (".jpg", ".txt", ".srt")}
        title = titles.get(mp4.stem) or mp4.stem.split("-", 1)[-1].replace("-", " ").capitalize()
        out.append({"name": mp4.stem, "date": mp4.parent.name, "title": title, "video": rel,
                    "thumbnail": side[".jpg"], "post": side[".txt"], "srt": side[".srt"],
                    "mtime": mp4.stat().st_mtime})
    return sorted(out, key=lambda v: (v["date"], v["mtime"]), reverse=True)
