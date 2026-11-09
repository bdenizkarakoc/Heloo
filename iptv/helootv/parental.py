"""Ebeveyn kilidi: PIN'in tuzlu PBKDF2 özeti saklanır (PIN'in kendisi asla). Kilit varken yetişkin içerik ancak PIN
ile görünür ve uygulama her açılışta yeniden kilitlenir."""
from __future__ import annotations

import hashlib
import hmac
import os

ROUNDS = 120_000


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_pin(pin, salt).split("$", 1)[1], digest_hex)


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 8
