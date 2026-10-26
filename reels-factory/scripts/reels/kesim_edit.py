"""Kesim düzenleme araçları: Premiere benzeri temel işlemler (ffmpeg). Claude MCP üzerinden adım adım kullanır.

Her işlem yeni bir dosya üretir (`output/kesim/islem/`); girdi dosyalarına asla yazılmaz. Telefon döndürmesi ve
HDR (iPhone) otomatik ele alınır. Uzun/akıllı işler (boşluk kesme, altyazı, stil, kendini geliştirme) için
`kesim.montage` kullanılır.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import log
from .config import ROOT
from .util import StageError, run, slugify

L = log.get("kesim")
WORK = ROOT / "output" / "kesim" / "islem"
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", "30",
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart"]
ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
LOOKS = {
    "sinematik": "eq=contrast=1.08:saturation=0.92:gamma=0.97,colorbalance=rs=0.04:bs=-0.03:rh=-0.02:bh=0.04",
    "canli": "eq=contrast=1.1:saturation=1.3:brightness=0.02",
    "sicak": "colortemperature=temperature=5200,eq=saturation=1.08",
    "soguk": "colortemperature=temperature=8000,eq=saturation=0.95",
    "siyah-beyaz": "hue=s=0,eq=contrast=1.15",
    "solgun": "eq=contrast=0.92:saturation=0.75:brightness=0.03",
}


def _src(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_file():
        raise StageError(f"dosya bulunamadı: {path}")
    return p


def _dest(src: Path, op: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    stem = slugify(src.stem, 40).split("-k-")[0]
    return WORK / f"{stem}-k-{op}-{time.strftime('%H%M%S')}{int(time.time() * 1000) % 1000:03d}.mp4"


def _info(src: Path) -> dict:
    from .studio import probe
    return probe(src)


def _sdr(src: Path, vf: str = "") -> str:
    from .studio import HDR_TO_SDR
    pre = HDR_TO_SDR if _info(src)["hdr"] else ""
    return ",".join(x for x in (pre, vf) if x) or "null"


def _audio_in(src: Path, args: list) -> list:
    """Sessiz videoya boş ses kanalı (sonraki birleştirmeler ses akışı bekler)."""
    info = _info(src)
    return args if info["audio"] else args + ["-f", "lavfi", "-t", f"{info['duration']:.3f}",
                                              "-i", "anullsrc=r=48000:cl=stereo"]


def _result(dest: Path, op: str) -> dict:
    info = _info(dest)
    L.info("Kesim %s → %s (%.1f sn)", op, dest.name, info["duration"])
    return {"file": str(dest), "rel": dest.relative_to(ROOT).as_posix(), "duration": round(info["duration"], 2),
            "width": info["width"], "height": info["height"]}


def bilgi(path: str) -> dict:
    """Süre, boyut, ses var mı, HDR mi."""
    from .studio import media_info
    return media_info(_src(path))


def kes(path: str, baslangic: float, bitis: float) -> dict:
    """[baslangic, bitis] aralığını (saniye) tutar."""
    src = _src(path)
    if bitis <= baslangic:
        raise StageError("bitiş başlangıçtan büyük olmalı")
    dest = _dest(src, "kes")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{baslangic:.3f}", "-to", f"{bitis:.3f}", "-i", src,
         "-vf", _sdr(src), *ENC, dest])
    return _result(dest, "kes")


def aralik_sil(path: str, baslangic: float, bitis: float) -> dict:
    """Ortadaki [baslangic, bitis] aralığını çıkarır, kalan iki parçayı birleştirir."""
    src = _src(path)
    d = _info(src)["duration"]
    if not 0 <= baslangic < bitis <= d:
        raise StageError(f"geçersiz aralık (video {d:.1f} sn)")
    dest = _dest(src, "sil")
    pre = _sdr(src)
    keep = f"between(t,0,{baslangic:.3f})+between(t,{bitis:.3f},{d + 1:.3f})"
    args = _audio_in(src, ["-i", src])
    a = "0:a" if _info(src)["audio"] else "1:a"
    run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex",
         f"[0:v]{pre},select='{keep}',setpts=N/FRAME_RATE/TB[v];[{a}]aselect='{keep}',asetpts=N/SR/TB[a]",
         "-map", "[v]", "-map", "[a]", "-shortest", *ENC, dest])
    return _result(dest, "sil")


def _normalize(src: Path, w: int, h: int, photo_sec: float) -> Path:
    """Tek parçayı ortak tuvale getirir (bulanık dolgu, 30 fps, stereo 48 kHz)."""
    from .studio import IMAGE_EXT, normalize_image
    dest = _dest(src, "parca")
    fill = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,"
            f"eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p")
    if src.suffix.lower() in IMAGE_EXT:
        img = normalize_image(src)
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{photo_sec}", "-i", img,
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex",
             f"[0:v]{fill},zoompan=z='min(zoom+0.0009,1.08)':d=1:s={w}x{h}:fps=30[v]",
             "-map", "[v]", "-map", "1:a", "-t", f"{photo_sec}", *ENC, dest])
        return dest
    args = _audio_in(src, ["-i", src])
    a = "0:a" if _info(src)["audio"] else "1:a"
    run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", f"[0:v]{_sdr(src)},{fill}[v]",
         "-map", "[v]", "-map", a, "-shortest", *ENC, dest])
    return dest


def birlestir(paths: list[str], oran: str = "9:16", gecis: str = "yok", gecis_sn: float = 0.5,
              foto_sn: float = 3.5) -> dict:
    """Videoları ve fotoğrafları sırayla birleştirir. gecis: yok / fade / beyaz / siyah / kay / yakinlas."""
    srcs = [_src(p) for p in paths]
    if not srcs:
        raise StageError("en az bir dosya gerekli")
    w, h = ASPECTS.get(oran, ASPECTS["9:16"])
    parts = [_normalize(s, w, h, foto_sn) for s in srcs]
    dest = _dest(srcs[0], "birlestir")
    if gecis == "yok" or len(parts) == 1:
        lst = dest.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dest])
        lst.unlink(missing_ok=True)
    else:
        kind = {"fade": "fade", "beyaz": "fadewhite", "siyah": "fadeblack", "kay": "slideleft",
                "yakinlas": "zoomin"}.get(gecis, "fade")
        durs = [_info(p)["duration"] for p in parts]
        t = min(gecis_sn, min(durs) / 3)
        ins, fc, off, vl, al = [], [], 0.0, "0:v", "0:a"
        for p in parts:
            ins += ["-i", p]
        for i in range(1, len(parts)):
            off += durs[i - 1] - t
            fc.append(f"[{vl}][{i}:v]xfade=transition={kind}:duration={t:.3f}:offset={off:.3f}[v{i}]")
            fc.append(f"[{al}][{i}:a]acrossfade=d={t:.3f}[a{i}]")
            vl, al = f"v{i}", f"a{i}"
        run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fc),
             "-map", f"[{vl}]", "-map", f"[{al}]", *ENC, dest])
    for p in parts:
        p.unlink(missing_ok=True)
    return _result(dest, "birlestir")


def yazi_ekle(path: str, metin: str, baslangic: float = 0.0, bitis: float = 0.0, konum: str = "ust",
              boyut: int = 0, renk: str = "white", kutu: bool = True) -> dict:
    """Ekrana yazı ekler (bitis 0: sonuna kadar). konum: ust / orta / alt. boyut 0: otomatik."""
    from .studio_render import font_file
    src = _src(path)
    info = _info(src)
    dest = _dest(src, "yazi")
    txt = dest.with_suffix(".txt")
    txt.write_text(metin, encoding="utf-8")
    size = boyut or max(28, int(min(info["width"], info["height"]) * 0.065))
    y = {"ust": "h*0.12", "orta": "(h-text_h)/2", "alt": "h*0.78-text_h"}.get(konum, "h*0.12")
    end = bitis if bitis > baslangic else info["duration"] + 1
    font = font_file(800).as_posix().replace(":", "\\:")
    box = ":box=1:boxcolor=black@0.55:boxborderw=18" if kutu else ":borderw=4:bordercolor=black@0.8"
    vf = (f"drawtext=fontfile='{font}':textfile='{txt.as_posix().replace(':', chr(92) + ':')}':fontsize={size}"
          f":fontcolor={renk}{box}:x=(w-text_w)/2:y={y}:line_spacing=8:enable='between(t,{baslangic},{end})'")
    run(["ffmpeg", "-y", "-v", "error", *_audio_in(src, ["-i", src]), "-vf", _sdr(src, vf),
         "-map", "0:v", "-map", "0:a" if info["audio"] else "1:a", "-shortest", *ENC, dest])
    txt.unlink(missing_ok=True)
    return _result(dest, "yazi")


def renk(path: str, gorunum: str = "", parlaklik: float = 0.0, kontrast: float = 1.0,
         doygunluk: float = 1.0) -> dict:
    """Renk düzenleme: hazır görünüm (sinematik, canli, sicak, soguk, siyah-beyaz, solgun) ve/veya elle ayar."""
    src = _src(path)
    parts = [LOOKS[gorunum]] if gorunum in LOOKS else []
    if parlaklik or kontrast != 1.0 or doygunluk != 1.0:
        parts.append(f"eq=brightness={parlaklik}:contrast={kontrast}:saturation={doygunluk}")
    if not parts:
        raise StageError(f"görünüm seçin: {', '.join(LOOKS)} ya da parlaklık/kontrast/doygunluk verin")
    dest = _dest(src, "renk")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", _sdr(src, ",".join(parts)), *ENC, dest])
    return _result(dest, "renk")


def hiz(path: str, kat: float) -> dict:
    """Hızlandır/yavaşlat (0.25–4; ses perdesi korunur)."""
    src = _src(path)
    if not 0.25 <= kat <= 4:
        raise StageError("kat 0.25 ile 4 arasında olmalı")
    tempo, k = [], kat
    while k > 2:
        tempo.append("atempo=2.0")
        k /= 2
    while k < 0.5:
        tempo.append("atempo=0.5")
        k /= 0.5
    tempo.append(f"atempo={k:.4f}")
    dest = _dest(src, "hiz")
    args = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", _sdr(src, f"setpts=PTS/{kat}")]
    args += ["-af", ",".join(tempo)] if _info(src)["audio"] else ["-an"]
    run([*args, *ENC, dest])
    return _result(dest, "hiz")


def cerceve(path: str, oran: str = "9:16", mod: str = "blur") -> dict:
    """En-boy oranı: 9:16 / 1:1 / 4:5 / 16:9. mod: blur (bulanık dolgu) / crop (ortadan kırp) / fit (siyah boşluk)."""
    src = _src(path)
    w, h = ASPECTS.get(oran, ASPECTS["9:16"])
    if mod == "crop":
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    elif mod == "fit":
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    else:
        vf = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,"
              f"eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    dest = _dest(src, "cerceve")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", f"[0:v]{_sdr(src, vf)}[v]",
         "-map", "[v]", "-map", "0:a?", *ENC, dest])
    return _result(dest, "cerceve")


def muzik_ekle(path: str, muzik: str, seviye_db: float = -18.0, konusmada_kis: bool = True) -> dict:
    """Arka plan müziği ekler; konuşma varken müzik otomatik kısılır (ducking). Müzik videonun sonunda söner."""
    src, mus = _src(path), _src(muzik)
    info = _info(src)
    d = info["duration"]
    dest = _dest(src, "muzik")
    m = (f"[1:a]atrim=0:{d:.3f},asetpts=N/SR/TB,volume={seviye_db}dB,"
         f"afade=t=out:st={max(0, d - 2):.3f}:d=2[m]")
    if info["audio"] and konusmada_kis:
        fc = (f"{m};[0:a]asplit[v1][v2];[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];"
              f"[v2][md]amix=inputs=2:duration=first:normalize=0[a]")
    elif info["audio"]:
        fc = f"{m};[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        fc = f"{m};[m]anull[a]"
    fc += f";[0:v]{_sdr(src)}[vv]"
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-stream_loop", "-1", "-i", mus, "-filter_complex", fc,
         "-map", "[vv]", "-map", "[a]", "-t", f"{d:.3f}", *ENC, dest])
    return _result(dest, "muzik")


def ses_ayarla(path: str, seviye_db: float = 0.0, kapat: bool = False) -> dict:
    """Ses seviyesini değiştirir ya da sesi tamamen kapatır."""
    src = _src(path)
    dest = _dest(src, "ses")
    af = "volume=0" if kapat else f"volume={seviye_db}dB"
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", _sdr(src), "-af", af, *ENC, dest])
    return _result(dest, "ses")


def ses_iyilestir(path: str, guc: str = "orta") -> dict:
    """Konuşma sesini temizler (uğultu, gürültü, cızırtı, seviye); görüntü aynen kalır."""
    from . import audiofx
    src = _src(path)
    dest = _dest(src, "temizses").with_suffix(".mp4" if _is_video(src) else ".wav")
    rep = audiofx.enhance_media(src, dest, guc if guc in ("hafif", "orta", "güçlü") else "orta")
    return {"file": str(dest), "rel": dest.relative_to(ROOT).as_posix(), "steps": rep["steps"]}


def _is_video(src: Path) -> bool:
    from .studio import media_info
    return media_info(src)["kind"] == "video"


def kapak(path: str, saniye: float = 1.0) -> dict:
    """Videodan kapak görseli (JPG)."""
    src = _src(path)
    dest = _dest(src, "kapak").with_suffix(".jpg")
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{saniye:.2f}", "-i", src, "-frames:v", "1",
         "-vf", _sdr(src), "-q:v", "2", dest])
    return {"file": str(dest), "rel": dest.relative_to(ROOT).as_posix()}
