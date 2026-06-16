"""Small shared utilities: ID generation, JSON columns, password hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import uuid
from typing import Any

# pbkdf2 iterations for password hashing (stdlib only — no extra dependency).
_PBKDF2_ITERATIONS = 200_000


def new_id() -> str:
    """Generate a hex UUID string for a new row."""
    return uuid.uuid4().hex


def jload(raw: str | None) -> Any:
    """Parse a JSON column value; ``None``/empty → ``None``."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def jdump(value: Any) -> str:
    """Serialise a Python value to a JSON column string."""
    return json.dumps(value, ensure_ascii=False)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with pbkdf2-hmac-sha256.

    Returns ``(hex_hash, hex_salt)``. Generates a fresh salt when none given.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return digest, salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time password check."""
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


# ═══════════════════════════════════════════════════════════════════════
# TOTP (Time-based One-Time Password) — RFC 6238, stdlib only
# ═══════════════════════════════════════════════════════════════════════

_TOTP_INTERVAL = 30
_TOTP_DIGITS = 6
_TOTP_WINDOW = 1  # accept ±1 interval (60s total grace)


def generate_totp_secret() -> str:
    """Generate a random base32-encoded TOTP secret (20 bytes)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def verify_totp(secret: str, code: str, window: int = _TOTP_WINDOW) -> bool:
    """Verify a TOTP code against a base32 secret.

    ``window=1`` accepts the current, previous, and next 30-second intervals
    (90 seconds total grace) to tolerate clock skew.
    """
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        return False
    secret_bytes = base64.b32decode(secret.upper())
    now = int(time.time()) // _TOTP_INTERVAL
    for offset in range(-window, window + 1):
        counter = struct.pack(">Q", now + offset)
        h = hmac.new(secret_bytes, counter, hashlib.sha1).digest()
        offset_byte = h[-1] & 0x0f
        binary = struct.unpack(">I", h[offset_byte:offset_byte + 4])[0] & 0x7fffffff
        if binary % (10 ** _TOTP_DIGITS) == code_int:
            return True
    return False


def totp_qrcode_url(name: str, secret: str, issuer: str = "Vera") -> str:
    """Return an otpauth:// URL for scanning with an authenticator app."""
    return f"otpauth://totp/{issuer}:{name}?secret={secret}&issuer={issuer}"

