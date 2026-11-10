"""Uygulama içi güncelleme: Heloo TV bir git klonu olarak kurulur (Belgeler\\Heloo); "Güncellemeleri denetle"
`git fetch` ile yeni sürümü bulur, "Güncelle" yalnız ileri sarma (`git pull --ff-only`) yapar — kullanıcının yerel
değişikliği ya da ayrık geçmiş varsa hiçbir şeyi ezmez. requirements.txt değiştiyse paketler de güncellenir.
Qt'ye bağımlı değildir."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REQUIREMENTS = "iptv/requirements.txt"


class UpdateError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str, timeout: float = 60) -> str:
    git = shutil.which("git")
    if not git:
        raise UpdateError("Git bulunamadı. Güncelleme için Git gerekir (PowerShell kurulum bloğu Git'i kurar).")
    flags = 0x08000000 if sys.platform.startswith("win") else 0
    try:
        r = subprocess.run([git, *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout,
                           creationflags=flags, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        raise UpdateError("GitHub'a ulaşılamadı (zaman aşımı). İnternet bağlantınızı denetleyin.") from e
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise UpdateError(msg[-1] if msg else f"git {' '.join(args)} başarısız")
    return r.stdout.strip()


def check(repo: Path | None = None) -> dict:
    """{'branch', 'behind', 'ahead', 'changes': [başlık...], 'dirty': bool, 'current', 'latest'}"""
    repo = Path(repo or repo_root())
    if not (repo / ".git").exists():
        raise UpdateError("Bu kurulum bir git klonu değil; güncelleme için PowerShell kurulum bloğunu kullanın.")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise UpdateError("Belirli bir dala bağlı değil (ayrık HEAD).")
    _git(repo, "fetch", "--quiet", "origin", branch, timeout=90)
    remote = f"origin/{branch}"
    behind = int(_git(repo, "rev-list", "--count", f"HEAD..{remote}") or 0)
    ahead = int(_git(repo, "rev-list", "--count", f"{remote}..HEAD") or 0)
    changes = [ln for ln in _git(repo, "log", "--format=%s", "-n", "15", f"HEAD..{remote}").splitlines() if ln]
    dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
    return {"branch": branch, "behind": behind, "ahead": ahead, "changes": changes, "dirty": dirty,
            "current": _git(repo, "rev-parse", "--short", "HEAD"),
            "latest": _git(repo, "rev-parse", "--short", remote)}


def apply(repo: Path | None = None, progress=None) -> dict:
    """İleri sarma güncellemesi. Dönüş: {'from', 'to', 'requirements_changed', 'packages_updated'}"""
    say = progress or (lambda m: None)
    repo = Path(repo or repo_root())
    info = check(repo)
    if not info["behind"]:
        return {"from": info["current"], "to": info["current"], "requirements_changed": False,
                "packages_updated": False}
    if info["dirty"]:
        raise UpdateError("Program dosyalarında yerel değişiklik var; güncelleme bunları ezmemek için durdu.")
    if info["ahead"]:
        raise UpdateError("Yerel kopyada GitHub'da olmayan değişiklikler var; güncelleme elle yapılmalı.")
    before = _git(repo, "rev-parse", "HEAD")
    say(f"{info['behind']} yenilik indiriliyor…")
    _git(repo, "pull", "--ff-only", "--quiet", "origin", info["branch"], timeout=180)
    after = _git(repo, "rev-parse", "HEAD")
    changed = REQUIREMENTS in _git(repo, "diff", "--name-only", before, after).splitlines()
    updated = False
    if changed:
        say("Gerekli paketler güncelleniyor…")
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(repo / REQUIREMENTS)],
                           capture_output=True, text=True, creationflags=flags)
        updated = r.returncode == 0
        if not updated:
            say("⚠ Paketler güncellenemedi: " + ((r.stderr or "").strip().splitlines() or ["?"])[-1])
    return {"from": before[:7], "to": after[:7], "requirements_changed": changed, "packages_updated": updated}
