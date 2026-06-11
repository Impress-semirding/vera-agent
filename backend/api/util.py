"""Small shared utilities: ID generation, JSON columns, password hashing."""

from __future__ import annotations

import hashlib
import json
import secrets
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

