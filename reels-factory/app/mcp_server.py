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
sys.path.insert(0, str(ROOT / "scripts"))
BASE = os.environ.get("RF_APP_URL", "http://127.0.0.1:8765").rstrip("/")
UPLOAD_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".3gp", ".jpg", ".jpeg", ".png", ".webp",
              ".heic", ".heif", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}

mcp = FastMCP("reels-fabrikasi", instructions=(
    "Reels Fabrikası + Kesim. Montaj/video düzenleme isteklerinde Adobe Premiere yerine Kesim araçlarını kullan: "
    "tek adımda her şey için kesim_montaj; adım adım düzenleme için kesim_kes, kesim_aralik_sil, kesim_birlestir, "
    "kesim_yazi_ekle, kesim_renk, kesim_hiz, kesim_cerceve, kesim_muzik_ekle, kesim_ses_ayarla, "
    "kesim_ses_iyilestir, kesim_kapak; her araç yeni dosya üretir (girdiye yazmaz), sonucu bir sonraki araca ver; "
    "bitince kesim_hazira_koy. Yeni içerik videosu için kesim_video_yap. Kullanıcının açık Kesim programındaki "
    "projeyi düzenlemek için kesim_editor_durum → kesim_editor_araclari → kesim_editor (metin, efekt, filtre, "
    "geçiş, kesme), dosya almak için kesim_editor_ice_aktar, kaydetmek için kesim_editor_disa_aktar. "
    "Yayınlamak yerine yayina_hazirla (yalnızca onay kuyruğu)."))


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


# ----------------------------------------------------------------------------
# Kesim: montaj ve Premiere benzeri düzenleme araçları
# ----------------------------------------------------------------------------

def _kesim_tool(fn, name: str):
    """kesim_edit işlevini MCP aracı yapar; hataları kullanıcıya okunur mesaj olarak döndürür."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(str(exc)[-600:]) from exc
    mcp.tool(name=name)(wrapper)


def _register_kesim() -> None:
    from reels import kesim_edit as k
    for fn in (k.bilgi, k.kes, k.aralik_sil, k.birlestir, k.yazi_ekle, k.renk, k.hiz, k.cerceve, k.muzik_ekle,
               k.ses_ayarla, k.ses_iyilestir, k.kapak):
        _kesim_tool(fn, f"kesim_{fn.__name__}")


_register_kesim()


@mcp.tool()
def kesim_montaj(dosyalar: list[str], mod: str = "auto", istek: str = "", referans: str = "",
                 secenekler: dict | None = None) -> dict:
    """Videoları/fotoğrafları Kesim'de tek adımda montajlar: birleştirme, boşluk kesme, 9:16, kelime vurgulu
    altyazı, renk, zoom, ses iyileştirme, müzik; fabrikanın öğrendiği en güncel stil ve kendini geliştirme turu
    kullanılır. Sonuç Masaüstü\\kesim\\Hazır klasörüne konur. mod: auto / full (tamamı) / clips (en iyi anlar).
    İsteğe bağlı: istek = kullanıcının kendi cümleleri ("enerjik, lo-fi müzik, geçişlerde vınlama, 30 sn");
    referans = "şunun gibi yap" bağlantısı (Instagram/TikTok/YouTube) ya da referans video dosyası;
    secenekler = {"tarz","sure","altyazi","muzik","efekt","renk","tempo"} (değerler: /api/kesim/brief).
    İş kuyruğa eklenir; durumu kesim_durum ile izle."""
    if mod in ("full", "clips", "auto"):
        _api("POST", "/api/kesim/settings", {"mode": mod})
    brief = {k: v for k, v in (secenekler or {}).items() if isinstance(v, str) and v}
    if istek:
        brief["serbest"] = istek
    if referans:
        brief["reference"] = {"url": referans} if referans.startswith(("http://", "https://")) else {"file": _upload(referans)}
    return _api("POST", "/api/kesim/edit", {"files": [_upload(f) for f in dosyalar], "brief": brief or None})


@mcp.tool()
def kesim_video_yap(konu: str = "", metin: str = "", kategori: str = "", medya_dosyalari: list[str] | None = None) -> dict:
    """"Şu videoyu yap": fabrikanın araştırma, senaryo, ses, görsel/video/foto ve müzik kaynaklarıyla yeni video
    üretir; senin fotoğraf/video/müziğin varsa onları kullanır. Bitince Kesim'in Hazır klasörüne de konur."""
    media = [_upload(f) for f in (medya_dosyalari or [])]
    return _api("POST", "/api/new", {"topic": konu, "text": metin, "category": kategori or None, "count": 1,
                                     "media": media, "kesim": True})


@mcp.tool()
def kesim_durum() -> dict:
    """Kesim: son montajlar (aşama, çıktılar), kullanılan stil, Montaja at / Hazır klasörleri, Kesim.exe bilgisi."""
    st = _api("GET", "/api/kesim")
    st["projects"] = [{k: p.get(k) for k in ("id", "status", "stage", "error", "style_used", "delivered", "notes")}
                      | {"clips": [c.get("output") for c in p.get("clips", [])]} for p in st.get("projects", [])]
    return st


@mcp.tool()
def kesim_hazira_koy(dosya: str) -> str:
    """Bitmiş videoyu Masaüstü\\kesim\\Hazır klasörüne kopyalar."""
    from reels import kesim
    p = Path(dosya).expanduser()
    p = p if p.is_absolute() else ROOT / p
    if not p.is_file():
        raise ToolError(f"dosya bulunamadı: {dosya}")
    return kesim.to_ready(p)


# ----------------------------------------------------------------------------
# Açık Kesim programını yönetme (Kesim'in yerel kontrol kapısı; Premiere MCP'nin Kesim karşılığı)
# ----------------------------------------------------------------------------

def _kesim_control(route: str, body: dict | None = None, timeout: float = 120):
    """Kesim penceresi açıkken %APPDATA%\\kesim\\fabrika-kontrol.json'daki kapı ve belirteçle konuşur."""
    appdata = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    files = [appdata / "kesim" / "fabrika-kontrol.json", appdata / "Kesim" / "fabrika-kontrol.json",
             *appdata.glob("*/fabrika-kontrol.json")]
    info = next((json.loads(f.read_text(encoding="utf-8")) for f in files if f.is_file()), None)
    if not info:
        raise ToolError("Kesim açık değil (ya da Fabrika eklentisi kurulu değil). Kesim'i açıp tekrar deneyin.")
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}{route}", method="POST",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json", "X-Kesim-Token": info["token"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — yalnızca yerel Kesim
            res = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        res = json.loads(exc.read() or b"{}")
    except (urllib.error.URLError, OSError) as exc:
        raise ToolError(f"Kesim'e bağlanılamadı ({exc}); Kesim kapanmış olabilir") from exc
    if res.get("error"):
        raise ToolError(res["error"])
    return res.get("result")


@mcp.tool()
def kesim_editor_durum() -> dict:
    """Açık Kesim projesinin durumu: klipler (sıra, süre, hız), metinler, efektler, müzik, toplam süre."""
    return _kesim_control("/state")


@mcp.tool()
def kesim_editor_araclari() -> list:
    """Kesim editörünün araçları ve parametreleri (add_text, add_effect, edit_clip, add_transition, split_at,
    remove_item, add_sound, smart_tool...). kesim_editor ile çağrılır."""
    return _kesim_control("/tools")


@mcp.tool()
def kesim_editor(arac: str, argumanlar: dict | None = None) -> dict:
    """Açık Kesim projesinde bir düzenleme aracını çalıştırır (ör. arac="add_text",
    argumanlar={"text": "Merhaba", "start": 0, "dur": 3, "style": "Başlık"}). Her değişiklik Kesim'de Geri al ile
    kaldırılabilir. Önce kesim_editor_araclari ile parametrelere bak."""
    return _kesim_control("/call", {"tool": arac, "args": argumanlar or {}})


@mcp.tool()
def kesim_editor_ice_aktar(dosya: str, zaman_cizelgesine: bool = True) -> dict:
    """Bilgisayardaki video/fotoğraf/ses dosyasını açık Kesim projesine alır (isteğe bağlı zaman çizelgesinin sonuna)."""
    p = Path(dosya).expanduser()
    p = p if p.is_absolute() else ROOT / p
    if not p.is_file():
        raise ToolError(f"dosya bulunamadı: {dosya}")
    return _kesim_control("/import", {"path": str(p), "timeline": zaman_cizelgesine}, timeout=600)


@mcp.tool()
def kesim_editor_disa_aktar(bicimler: list[str] | None = None, cozunurluk: int = 1080, fps: int = 30) -> dict:
    """Açık Kesim projesini dışa aktarır ve Masaüstü\\kesim\\Hazır klasörüne kaydeder. bicimler: v (dikey 9:16),
    h (yatay 16:9), sq (kare), p45 (4:5). Gerçek zamanlı çalışır: video ne kadar uzunsa o kadar sürer."""
    return _kesim_control("/export", {"formats": bicimler or ["v"], "res": cozunurluk, "fps": fps}, timeout=3600)


if __name__ == "__main__":
    mcp.run()
