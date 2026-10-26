"""Reels Fabrikası MCP sunucusu (stdio): Claude Desktop / Claude Code fabrikayı araç olarak kullanır.

Yerel uygulamaya (app/server.py, http://127.0.0.1:8765) bağlanır; çalışmıyorsa penceresiz başlatır. Uzun işler
uygulamanın iş kuyruğuna eklenir, durumları `durum` / `gorevler` ile izlenir.

Bilerek olmayanlar: gizli anahtar yazma (anahtarlar sohbete girmesin; Yayın → Ayarlar), yayını onaylama/yayınlama
(video yalnızca onay kuyruğuna eklenir; kanal ayarları geçerli), dosya silme.

    python app/mcp_server.py                      # stdio
    claude mcp add reels-fabrikasi -- python app/mcp_server.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
BASE = os.environ.get("RF_APP_URL", "http://127.0.0.1:8765").rstrip("/")
UPLOAD_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".3gp", ".jpg", ".jpeg", ".png", ".webp",
              ".heic", ".heif", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}

mcp = FastMCP("reels-fabrikasi")


def _call(method: str, path: str, body: dict | None = None, data: bytes | None = None, timeout: float = 60):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=data if data is not None else (json.dumps(body).encode() if body is not None
                                                                     else None),
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — yalnızca yerel uygulama
            raw = r.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return json.loads(raw)
        except ValueError:
            return {"error": f"HTTP {exc.code}"}
    return json.loads(raw) if raw else {}


def _alive() -> bool:
    try:
        _call("GET", "/api/jobs", timeout=3)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _ensure_app() -> None:
    """Uygulama kapalıysa arka planda (Windows'ta penceresiz) başlatır ve hazır olmasını bekler."""
    if _alive():
        return
    port = urllib.parse.urlparse(BASE).port or 8765
    kw: dict = {"cwd": ROOT, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, str(APP_DIR / "server.py"), "--port", str(port)], **kw)  # noqa: S603
    for _ in range(60):
        time.sleep(0.5)
        if _alive():
            return
    raise ToolError(f"Reels uygulaması başlatılamadı ({BASE}); `python app/server.py` ile elle deneyin")


def _api(method: str, path: str, body: dict | None = None):
    _ensure_app()
    return _call(method, path, body)


def _upload(path: str) -> str:
    """Bilgisayardaki dosyayı uygulamanın yükleme klasörüne gönderir; uygulamadaki adını döndürür."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"dosya bulunamadı: {p}")
    if p.suffix.lower() not in UPLOAD_EXT:
        raise ToolError(f"desteklenmeyen dosya türü: {p.suffix or p.name}")
    _ensure_app()
    req = urllib.request.Request(f"{BASE}/api/studio/upload?name={urllib.parse.quote(p.name)}", method="PUT",
                                 data=p.open("rb"), headers={"Content-Length": str(p.stat().st_size)})
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:  # noqa: S310
            res = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        res = json.loads(exc.read() or b"{}")
    if res.get("error"):
        raise ToolError(res["error"])
    return res["file"]


@mcp.tool()
def durum() -> dict:
    """Fabrikanın durumu: hazır mı, eksik bileşenler, açık yetenekler (AI görsel/video, ses...), kategoriler,
    şu an çalışan ve sıradaki işler."""
    return _api("GET", "/api/status")


@mcp.tool()
def gorevler() -> list:
    """Son video görevleri: başlık, adım durumları, hatalar, uyarılar ve çıktı dosyaları."""
    return _api("GET", "/api/jobs")


@mcp.tool()
def gorev_logu(gorev_id: str) -> str:
    """Bir görevin günlük kaydının son kısmı (hata ayıklama için)."""
    return _api("GET", f"/api/log/{urllib.parse.quote(gorev_id)}").get("log", "")


@mcp.tool()
def video_uret(konu: str = "", kategori: str = "", metin: str = "", adet: int = 1, cizim: bool = False,
               medya_dosyalari: list[str] | None = None) -> dict:
    """Yeni Türkçe Reels videosu üretimini kuyruğa ekler (senaryo, ses, görsel, kurgu, QC otomatik).

    konu: isteğe bağlı konu ("Venüs'te bir gün"); kategori: `durum` çıktısındaki kategori anahtarı;
    metin: hazır metin/senaryo fikri (verilirse tek video); adet: 1-10; cizim: kendi çizdiği SVG grafikleri;
    medya_dosyalari: bilgisayardaki fotoğraf/video/müzik yolları — videoda kullanılır."""
    media = [_upload(f) for f in (medya_dosyalari or [])]
    return _api("POST", "/api/new", {"topic": konu, "category": kategori or None, "text": metin, "count": adet,
                                     "draw": cizim, "media": media})


@mcp.tool()
def yeniden_uret(gorev_id: str, adimdan: str = "") -> dict:
    """Var olan görevi yeniden üretir; adimdan: script / voice / captions / visuals / music / compose / render / mix / qc / export."""
    return _api("POST", "/api/produce", {"job": gorev_id, "from_stage": adimdan or None})


@mcp.tool()
def sesi_iyilestir(dosya: str, guc: str = "orta") -> dict:
    """Video ya da ses kaydının sesini temizler (uğultu, gürültü, cızırtı, seviye). Videoda görüntü değişmez.
    guc: hafif / orta / güçlü. Çıktı: output/enhanced/."""
    return _api("POST", "/api/audio/enhance", {"file": _upload(dosya), "strength": guc})


@mcp.tool()
def stil_listesi() -> list:
    """Stüdyoda kaydedilmiş stiller (referans videolardan öğrenilen)."""
    return _api("GET", "/api/studio/styles")


@mcp.tool()
def stil_ogren(baglanti: str = "", video_dosyasi: str = "") -> dict:
    """Beğenilen bir Reels'in stilini öğrenir (bağlantı ya da bilgisayardaki video). Bitince proje `stüdyo_projeleri`
    içinde görünür; stile ad vermek için Stüdyo sayfası kullanılır."""
    if baglanti:
        return _api("POST", "/api/studio/analyze", {"url": baglanti})
    return _api("POST", "/api/studio/analyze", {"file": _upload(video_dosyasi)})


@mcp.tool()
def videomu_duzenle(dosyalar: list[str], stil: str = "", mod: str = "clips", adet: int = 3, muzik: bool = True,
                    altyazi: bool = True, notlar: str = "") -> dict:
    """Kendi video/fotoğraflarını düzenler: boşlukları keser, 9:16, altyazı, renk, zoom, müzik, ses iyileştirme.
    Birden çok dosya tek montajda birleşir. mod: "clips" (en iyi anlardan kısa klipler) ya da "full" (tamamı)."""
    files = [_upload(f) for f in dosyalar]
    body = {"files": files, "mode": mod, "count": adet, "music": muzik, "captions": altyazi, "notes": notlar}
    if stil:
        body["style"] = stil
    return _api("POST", "/api/studio/edit", body)


@mcp.tool()
def studyo_projeleri() -> list:
    """Stüdyo işleri (stil öğrenme ve düzenleme) ve çıktıları."""
    return _api("GET", "/api/studio/projects")


@mcp.tool()
def yayin_kuyrugu() -> list:
    """Yayın onay kuyruğundaki videolar ve durumları (bekliyor / onaylandı / reddedildi / yayınlandı)."""
    return _api("GET", "/api/publish/items")


@mcp.tool()
def yayina_hazirla(video: str, kanal: str = "", platformlar: list[str] | None = None) -> dict:
    """Videoyu yayın ONAY kuyruğuna ekler (başlık/paylaşım yazısı hazırlanır, logo damgalanır). Yayınlamaz:
    onay ve yayın kanal ayarlarına göre olur. video: output/ altındaki dosya yolu (gorevler çıktısından)."""
    return _api("POST", "/api/publish/queue", {"video": video, "channel": kanal or None,
                                               "targets": platformlar or None})


@mcp.tool()
def kanca_puani(kancalar: list[str]) -> str:
    """Açılış cümlelerinin (kanca) Türkçe puanı ve önerileri; birkaç seçenek verilirse karşılaştırılır."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "factory.py"), "hook", *kancalar],  # noqa: S603
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout + r.stderr).strip()


if __name__ == "__main__":
    mcp.run()
