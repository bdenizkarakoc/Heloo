"""Kendinden imzalı HTTPS sertifikası — yalnızca Python standart kitaplığı (ek paket yok).

Neden: bazı TV tarayıcıları (ör. LG webOS) yazılan adresi kendiliğinden https:// ile açar. Uygulama aynı portta
hem http hem https konuşur; https için bu sertifika kullanılır. TV ilk seferde "bağlantı gizli değil" uyarısı
gösterebilir (sertifika bu bilgisayarın kendisine ait): "Gelişmiş → Devam et" denir.

RSA 2048 + SHA-256, X.509 v3, SubjectAltName: bilgisayarın IP adresleri.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import ipaddress
import random
import ssl
from pathlib import Path

_rng = random.SystemRandom()
_KUCUK_ASALLAR = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


def _asal_mi(n: int, tur: int = 40) -> bool:
    for p in _KUCUK_ASALLAR:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(tur):
        x = pow(_rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _asal(bit: int) -> int:
    while True:
        n = _rng.getrandbits(bit) | (3 << (bit - 2)) | 1
        if _asal_mi(n):
            return n


# ---------------------------------------------------------------- DER
def _uzunluk(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(etiket: int, icerik: bytes) -> bytes:
    return bytes([etiket]) + _uzunluk(len(icerik)) + icerik


def _int(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")   # baştaki 0: pozitif
    return _tlv(0x02, b)


def _oid(metin: str) -> bytes:
    p = [int(x) for x in metin.split(".")]
    out = bytearray([40 * p[0] + p[1]])
    for v in p[2:]:
        parca = [v & 0x7F]
        v >>= 7
        while v:
            parca.append(0x80 | (v & 0x7F))
            v >>= 7
        out += bytes(reversed(parca))
    return _tlv(0x06, bytes(out))


def _seq(*ogeler: bytes) -> bytes:
    return _tlv(0x30, b"".join(ogeler))


def _zaman(t: dt.datetime) -> bytes:
    if t.year < 2050:
        return _tlv(0x17, t.strftime("%y%m%d%H%M%SZ").encode())
    return _tlv(0x18, t.strftime("%Y%m%d%H%M%SZ").encode())


NULL = b"\x05\x00"
SHA256_RSA = _seq(_oid("1.2.840.113549.1.1.11"), NULL)


def sertifika_uret(ad: str = "TV Yansit", ipler: list[str] | None = None, bit: int = 2048) -> tuple[bytes, bytes]:
    """(sertifika PEM, özel anahtar PEM)."""
    e = 65537
    while True:
        p, q = _asal(bit // 2), _asal(bit // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n, d = p * q, pow(e, -1, (p - 1) * (q - 1))
    k = (n.bit_length() + 7) // 8

    isim = _seq(_tlv(0x31, _seq(_oid("2.5.4.3"), _tlv(0x0C, ad.encode()))))
    simdi = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    gecerlilik = _seq(_zaman(simdi - dt.timedelta(days=1)), _zaman(simdi + dt.timedelta(days=3650)))
    acik_anahtar = _seq(_seq(_oid("1.2.840.113549.1.1.1"), NULL), _tlv(0x03, b"\x00" + _seq(_int(n), _int(e))))
    adlar = [_tlv(0x82, b"localhost")]
    for ip in ipler or []:
        try:
            adlar.append(_tlv(0x87, ipaddress.ip_address(ip).packed))
        except ValueError:
            continue
    uzantilar = _tlv(0xA3, _seq(
        _seq(_oid("2.5.29.17"), _tlv(0x04, _seq(*adlar))),                       # SubjectAltName
        _seq(_oid("2.5.29.19"), _tlv(0x04, _seq())),                             # basicConstraints: CA değil
    ))
    seri = _rng.getrandbits(63) | 1
    tbs = _seq(_tlv(0xA0, _int(2)), _int(seri), SHA256_RSA, isim, gecerlilik, isim, acik_anahtar, uzantilar)

    ozet = _seq(_seq(_oid("2.16.840.1.101.3.4.2.1"), NULL), _tlv(0x04, hashlib.sha256(tbs).digest()))
    em = b"\x00\x01" + b"\xff" * (k - len(ozet) - 3) + b"\x00" + ozet
    imza = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    sertifika = _seq(tbs, SHA256_RSA, _tlv(0x03, b"\x00" + imza))

    anahtar = _seq(_int(0), _int(n), _int(e), _int(d), _int(p), _int(q),
                   _int(d % (p - 1)), _int(d % (q - 1)), _int(pow(q, -1, p)))
    return _pem("CERTIFICATE", sertifika), _pem("RSA PRIVATE KEY", anahtar)


def _pem(tur: str, der: bytes) -> bytes:
    b64 = base64.b64encode(der).decode()
    satirlar = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return (f"-----BEGIN {tur}-----\n" + "\n".join(satirlar) + f"\n-----END {tur}-----\n").encode()


def ssl_baglami(klasor: Path, ipler: list[str]) -> ssl.SSLContext | None:
    """Sertifikayı (yoksa üretip) yükler. Hata olursa None: uygulama yalnızca http ile çalışır."""
    sert, anah = klasor / "sertifika.pem", klasor / "anahtar.pem"
    try:
        klasor.mkdir(parents=True, exist_ok=True)
        if not (sert.exists() and anah.exists()):
            s, a = sertifika_uret(ipler=ipler)
            anah.write_bytes(a)
            sert.write_bytes(s)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(sert), str(anah))
        return ctx
    except (OSError, ssl.SSLError, ValueError):
        return None
