"""GitHub'dan en güncel mpv'yi indirir: libmpv-2.dll (gömülü oynatıcı) + mpv.exe (ayrı pencere yedeği).

Kaynaklar (GitHub Releases):
  * zhongfly/mpv-winbuild — mpv master'ın günlük Windows derlemeleri (RTX VSR/HDR içeren en yeni d3d11vpp)
  * shinchiro/mpv-winbuild-cmake — yedek
  * ip7z/7zip — 7-Zip'in resmî deposu: 7zr.exe (arşivler LZMA2+BCJ2; Python'un 7z kütüphanesi BCJ2 açamaz)

İşlemci AVX2 destekliyorsa x86-64-v3 derlemesi seçilir. GitHub, varlıklar için SHA-256 özeti verirse doğrulanır.

    python -m helootv.tools.fetch_mpv            # bin/ klasörüne kurar
    python -m helootv.tools.fetch_mpv --check    # yalnızca hangi dosyaların seçileceğini gösterir
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable

from .. import gpu, paths, shaders

MPV_REPOS = ("zhongfly/mpv-winbuild", "shinchiro/mpv-winbuild-cmake")
SEVENZIP_REPO = "ip7z/7zip"
SEVENZIP_FALLBACK = "https://www.7-zip.org/a/7zr.exe"
API = "https://api.github.com/repos/{repo}/releases/latest"
UA = "HelooTV-fetch-mpv"


class FetchError(Exception):
    pass


def _creationflags() -> int:
    return 0x08000000 if os.name == "nt" else 0


def _gh_json(url: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def arch_name(machine: str | None = None) -> str:
    m = (machine or platform.machine() or "").lower()
    return "aarch64" if m in ("arm64", "aarch64") else "x86_64"


def pick_asset(assets: list[dict], kind: str, avx2: bool, arch: str = "x86_64") -> dict | None:
    """kind: dev (libmpv-2.dll) | player (mpv.exe) | ffmpeg (ffmpeg.exe: 4K dışa aktarma, libplacebo + NVENC).
    LGPL ve hata ayıklama paketleri seçilmez."""
    if kind == "ffmpeg":
        rx = re.compile(rf"^ffmpeg-{re.escape(arch)}-(v3-)?()git-([0-9a-f]+)\.7z$")
    else:
        prefix = "mpv-dev" if kind == "dev" else "mpv"
        rx = re.compile(rf"^{prefix}-{re.escape(arch)}-(v3-)?(\d{{8}})-git-([0-9a-f]+)\.7z$")
    cands = []
    for a in assets:
        m = rx.match(a.get("name", ""))
        if m:
            v3 = bool(m.group(1))
            cands.append(((v3 == avx2, m.group(2)), a))
    return max(cands, key=lambda c: c[0])[1] if cands else None


def download(url: str, dest: Path, digest: str | None = None,
             progress: Callable[[str], None] | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last = 0.0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and time.monotonic() - last > 0.5:
                last = time.monotonic()
                pct = f" %{100 * done // total}" if total else ""
                progress(f"İndiriliyor: {dest.name}{pct} ({done / 1e6:.1f} MB)")
    if digest and digest.startswith("sha256:") and h.hexdigest() != digest.split(":", 1)[1]:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"{dest.name}: SHA-256 doğrulaması başarısız (indirme bozuk ya da değiştirilmiş).")
    tmp.replace(dest)
    return dest


def find_7z(bin_dir: Path, progress: Callable[[str], None] | None = None) -> str:
    for name in ("7z", "7za", "7zz", "7zr"):
        found = shutil.which(name)
        if found:
            return found
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.isfile(p):
            return p
    local = bin_dir / "7zr.exe"
    if local.is_file():
        return str(local)
    if os.name != "nt":
        raise FetchError("7z bulunamadı (Linux: apt install 7zip / p7zip-full).")
    if progress:
        progress("7-Zip (7zr.exe) GitHub'dan indiriliyor…")
    try:
        rel = _gh_json(API.format(repo=SEVENZIP_REPO))
        asset = next(a for a in rel.get("assets", []) if a.get("name") == "7zr.exe")
        download(asset["browser_download_url"], local, asset.get("digest"), progress)
    except Exception:
        download(SEVENZIP_FALLBACK, local, None, progress)
    return str(local)


def extract(archive: Path, members: list[str], outdir: Path, sevenzip: str) -> list[Path]:
    """Arşivden yalnız istenen dosyaları (klasör yapısını yok sayarak) çıkarır."""
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sevenzip, "e", str(archive), f"-o{outdir}", "-y", "-r", *members]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=_creationflags())
    if res.returncode != 0:
        tar = shutil.which("tar")
        if tar:  # Windows 10/11 tar.exe (libarchive) 7z okuyabilir
            res2 = subprocess.run([tar, "-xf", str(archive), "-C", str(outdir)], capture_output=True, text=True,
                                  creationflags=_creationflags())
            if res2.returncode != 0:
                raise FetchError(f"Arşiv açılamadı: {res.stderr.strip() or res2.stderr.strip()}")
        else:
            raise FetchError(f"Arşiv açılamadı: {res.stderr.strip()}")
    found = []
    for m in members:
        hit = next((p for p in outdir.rglob(m) if p.is_file()), None)
        if hit:
            found.append(hit)
    return found


def _install_file(src: Path, dest_dir: Path) -> Path:
    """Çalışan uygulamanın kilitlediği DLL'in üzerine yazılamaz; Windows yüklü DLL'i yeniden adlandırmaya izin verir."""
    target = dest_dir / src.name
    if target.exists():
        try:
            target.unlink()
        except OSError:
            old = dest_dir / f"{src.name}.{int(time.time())}.old"
            os.replace(target, old)
    shutil.copy2(src, target)
    for stale in dest_dir.glob(f"{src.name}.*.old"):
        try:
            stale.unlink()
        except OSError:
            pass
    return target


def install_shaders(dest: Path | None = None, progress: Callable[[str], None] | None = None) -> list[str]:
    """FSRCNNX (igv/FSRCNN-TensorFlow sürüm dosyası) ve ArtCNN (Artoriuz/ArtCNN, MIT) shader'larını indirir."""
    say = progress or (lambda m: None)
    dest = Path(dest or shaders.shader_dir())
    dest.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for key, meta in shaders.SHADERS.items():
        target = dest / meta["file"]
        if target.is_file() and target.stat().st_size > 1000:
            continue
        # sırayla: sürüm API'si (özet doğrulamalı) → sabit sürüm bağlantısı; ağ dalgalanmasına karşı 3 deneme
        errors: list[str] = []
        for attempt in range(3):
            if attempt:
                time.sleep(2 * attempt)
            try:
                _fetch_shader(meta, target, say, use_api=attempt == 0)
                done.append(str(target))
                say(f"Yapay zekâ büyütücü indirildi: {meta['label']}")
                break
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        else:
            say(f"{meta['file']} indirilemedi: {'; '.join(dict.fromkeys(errors))}")
    return done


def _fetch_shader(meta: dict, target: Path, say, use_api: bool) -> None:
    if meta.get("url"):
        download(meta["url"], target, None, say)
    elif use_api or not meta.get("fallback"):
        rel = _gh_json(API.format(repo=meta["repo"]))
        asset = next((a for a in rel.get("assets", []) if a.get("name") == meta["file"]), None)
        if not asset:
            raise FetchError(f"{meta['repo']}: {meta['file']} bulunamadı")
        download(asset["browser_download_url"], target, asset.get("digest"), say)
    else:
        download(meta["fallback"], target, None, say)
    if "//!HOOK" not in target.read_text(encoding="utf-8", errors="replace")[:20000]:
        target.unlink()
        raise FetchError(f"{meta['file']} geçerli bir mpv shader'ı değil")


def latest_release(progress: Callable[[str], None] | None = None) -> tuple[str, dict]:
    last: Exception | None = None
    for repo in MPV_REPOS:
        try:
            rel = _gh_json(API.format(repo=repo))
            if rel.get("assets"):
                return repo, rel
        except Exception as e:  # ağ, oran sınırı
            last = e
            if progress:
                progress(f"{repo} okunamadı: {e}")
    raise FetchError(f"GitHub'dan mpv sürüm bilgisi alınamadı: {last}")


def install(dest: str | Path | None = None, want_player: bool = True, force: bool = False,
            progress: Callable[[str], None] | None = None) -> dict:
    say = progress or (lambda m: None)
    if os.name != "nt" and not os.environ.get("HELOOTV_FETCH_ANY_OS"):
        raise FetchError("Bu indirici Windows içindir. Linux'ta: sudo apt install libmpv2 (ya da mpv); "
                         "macOS'ta: brew install mpv.")
    dest = Path(dest or paths.bin_dir())
    dest.mkdir(parents=True, exist_ok=True)
    avx2 = gpu.cpu_has_avx2()
    arch = arch_name()
    repo, rel = latest_release(say)
    tag = rel.get("tag_name", "")
    marker = dest / "mpv-version.txt"
    if not force and marker.is_file() and marker.read_text(encoding="utf-8").strip() == f"{repo}@{tag}" \
            and (dest / "libmpv-2.dll").is_file():
        say(f"mpv zaten güncel ({tag}).")
        return {"repo": repo, "tag": tag, "files": [], "skipped": True}
    assets = rel.get("assets", [])
    jobs = []
    dev = pick_asset(assets, "dev", avx2, arch)
    if not dev:
        raise FetchError(f"{repo} {tag}: libmpv paketi (mpv-dev-{arch}-*.7z) bulunamadı.")
    jobs.append((dev, ["libmpv-2.dll"]))
    if want_player:
        player = pick_asset(assets, "player", avx2, arch)
        if player:
            jobs.append((player, ["mpv.exe", "mpv.com"]))
        ff = pick_asset(assets, "ffmpeg", avx2, arch)
        if ff:
            jobs.append((ff, ["ffmpeg.exe"]))
    installed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="helootv-mpv-") as td:
        sevenzip = find_7z(dest, say)
        for asset, members in jobs:
            archive = Path(td) / asset["name"]
            say(f"İndiriliyor: {asset['name']} ({asset.get('size', 0) / 1e6:.0f} MB)")
            download(asset["browser_download_url"], archive, asset.get("digest"), say)
            files = extract(archive, members, Path(td) / ("x-" + asset["name"]), sevenzip)
            if not files and members[0] == "libmpv-2.dll":
                raise FetchError(f"{asset['name']} içinde libmpv-2.dll yok.")
            for f in files:
                installed.append(str(_install_file(f, dest)))
    marker.write_text(f"{repo}@{tag}", encoding="utf-8")
    try:
        installed += install_shaders(dest / "shaders", say)
    except Exception as e:  # shader'lar isteğe bağlı: oynatma onlarsız da çalışır
        say(f"Yapay zekâ büyütücü indirilemedi: {e}")
    say(f"mpv kuruldu: {repo} {tag} ({'x86-64-v3/AVX2' if avx2 else 'x86-64'})")
    return {"repo": repo, "tag": tag, "files": installed, "avx2": avx2}


def main(argv: list[str] | None = None) -> int:
    paths.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="GitHub'dan mpv (libmpv-2.dll + mpv.exe) indirir.")
    ap.add_argument("--dest", help="hedef klasör (varsayılan: iptv/bin)")
    ap.add_argument("--force", action="store_true", help="güncel olsa da yeniden indir")
    ap.add_argument("--no-player", action="store_true", help="mpv.exe'yi indirme (yalnız libmpv)")
    ap.add_argument("--check", action="store_true", help="yalnız seçilecek dosyaları göster")
    ap.add_argument("--shaders-only", action="store_true", help="yalnız yapay zekâ büyütücü shader'larını indir")
    args = ap.parse_args(argv)
    try:
        if args.shaders_only:
            print("\n".join(install_shaders(Path(args.dest) / "shaders" if args.dest else None, print)) or "güncel")
            return 0
        if args.check:
            repo, rel = latest_release(print)
            avx2 = gpu.cpu_has_avx2()
            for kind in ("dev", "player", "ffmpeg"):
                a = pick_asset(rel.get("assets", []), kind, avx2, arch_name())
                print(f"{repo} {rel.get('tag_name')} {kind}: {a['name'] if a else '—'}"
                      + (f"  {a.get('digest', '')}" if a else ""))
            return 0
        info = install(args.dest, want_player=not args.no_player, force=args.force, progress=print)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    except FetchError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
