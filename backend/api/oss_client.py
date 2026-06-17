"""Alibaba Cloud OSS upload client — stdlib + httpx, no extra deps.

Authenticates via AccessKey + HMAC-SHA1 signature (OSS V2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from email.utils import formatdate

import httpx


def _conf(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


BUCKET = _conf("OSS_BUCKET_NAME")
ENDPOINT = _conf("OSS_ENDPOINT")
KEY_ID = _conf("OSS_ACCESS_KEY_ID")
KEY_SECRET = _conf("OSS_ACCESS_KEY_SECRET")
BASE_URL = _conf("OSS_BASE_URL", f"https://{BUCKET}.{ENDPOINT}")


# ── Allowed MIME types (extensions mapped on upload) ────────────────────

ALLOWED_MIMES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",                                                         # .doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",         # .xlsx
    "application/vnd.ms-excel",                                                   # .xls
    "text/markdown", "text/x-markdown",
    "text/plain",  # .sql / .txt
    "application/sql", "text/x-sql",
}

MAX_FILE_COUNT = 10
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ─── Upload ──────────────────────────────────────────────────────────────


def _sign(verb: str, content_type: str, date: str, object_path: str) -> str:
    """OSS V2 signature (HMAC-SHA1)."""
    canon = f"{verb}\n\n{content_type}\n{date}\n/{BUCKET}{object_path}"
    sig = hmac.new(KEY_SECRET.encode(), canon.encode(), hashlib.sha1).digest()
    return base64.b64encode(sig).decode()


async def upload_file(filename: str, content: bytes, content_type: str) -> dict:
    """Upload a single file to OSS. Returns {name, url, size}."""
    if not KEY_ID or not KEY_SECRET or not BUCKET or not ENDPOINT:
        raise RuntimeError("OSS 未配置（检查 OSS_* 环境变量）")

    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"文件 {filename} 超过 {MAX_FILE_SIZE // 1024 // 1024}MB")

    # Unique object key to avoid collisions
    uid = uuid.uuid4().hex
    safe_name = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    object_key = f"vera/{uid[:2]}/{uid}_{filename}"

    date = formatdate(timeval=None, localtime=False, usegmt=True)
    path = f"/{object_key}"
    sig = _sign("PUT", content_type, date, path)
    auth = f"OSS {KEY_ID}:{sig}"

    url = f"https://{BUCKET}.{ENDPOINT}{path}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(30), trust_env=False) as client:
        resp = await client.put(
            url,
            content=content,
            headers={
                "Content-Type": content_type,
                "Date": date,
                "Authorization": auth,
            },
        )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"OSS upload {resp.status_code}: {resp.text[:200]}")

    return {
        "name": filename,
        "url": f"{BASE_URL.rstrip('/')}{path}",
        "size": len(content),
    }


def is_allowed(content_type: str) -> bool:
    """Reject video/audio; allow images, documents, text."""
    return content_type in ALLOWED_MIMES or content_type.startswith("image/")
