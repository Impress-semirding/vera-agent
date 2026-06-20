"""Shared API helpers: response envelope, error handling, current-user dep.

The frontend (``fr/src/services/api.ts``) unwraps every response with an
axios interceptor that returns ``res.data`` directly and reads errors from
``err.response.data.message``. So every endpoint must answer with the
``{code, data, message}`` envelope and every error must carry a ``message``.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import os
import time
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# ─── Envelope ───────────────────────────────────────────────────────────────

CODE_OK = 0


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """Successful response envelope."""
    return {"code": CODE_OK, "data": data, "message": message}


def fail(code: int, message: str, data: Any = None, status_code: int | None = None) -> JSONResponse:
    """Error envelope as a JSONResponse (lets us set the HTTP status too)."""
    return JSONResponse(
        status_code=status_code or code,
        content={"code": code, "data": data, "message": message},
    )


def iso(dt: datetime | None) -> str | None:
    """Serialize a datetime to an ISO-8601 string the frontend expects.

    Model timestamps are naive UTC; append ``Z`` so the frontend's
    ``new Date(...)`` parsing treats them as UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


# ─── Session token (HMAC-SHA256, stdlib only) ───────────────────────────────

_SESSION_SECRET = os.environ.get("VERA_SESSION_SECRET", "vera-dev-secret-change-me")
_SESSION_TTL = int(os.environ.get("VERA_SESSION_TTL", str(86400)))  # default 24h


def sign_session_token(username: str) -> str:
    """Issue a short-lived signed token for a user."""
    payload = f"{username}|{int(time.time()) + _SESSION_TTL}"
    sig = hmac.new(
        _SESSION_SECRET.encode(), payload.encode(), hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def verify_session_token(token: str) -> str | None:
    """Verify a signed session token. Returns username or None."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit(".", 1)
        expected = hmac.new(
            _SESSION_SECRET.encode(), payload.encode(), hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, exp_str = payload.split("|", 1)
        if int(exp_str) < time.time():
            return None  # expired
        return username
    except Exception:
        return None


def verify_session_token_from_header(authorization: str | None) -> str | None:
    """Extract and verify a token from an Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return verify_session_token(authorization[7:])
    return None


# ─── Current user ───────────────────────────────────────────────────────────

DEFAULT_USER = "current-user"


def current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    vera_token: str | None = Header(default=None, alias="vera-token"),
    token: str | None = Query(default=None, alias="token"),
) -> str:
    """Resolve the acting user from a signed session token.

    Accepts ``Authorization: Bearer <token>``, ``vera-token: <token>``,
    or ``?token=...`` query param (the latter is for ``<a href download>``
    and other GET requests where custom headers cannot be set).
    """
    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:]
    elif vera_token:
        raw = vera_token
    elif token:
        raw = token
    if raw:
        username = verify_session_token(raw)
        if username:
            _store_user_token(username, raw)
            return username
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    raise HTTPException(status_code=401, detail="请先登录")


# ── User token cache (for MCP server env injection) ─────────────────────────

_user_tokens: dict[str, str] = {}


def _store_user_token(user: str, token: str) -> None:
    """Cache the most recent token for a user (used by MCP env injection)."""
    _user_tokens[user] = token


def get_user_token(user: str) -> str | None:
    """Return the most recently seen session token for a user, if any."""
    return _user_tokens.get(user)


# ─── Exception handlers ─────────────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Wrap FastAPI errors into the ``{code, data, message}`` envelope."""

    @app.exception_handler(HTTPException)
    async def _http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "data": None, "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        messages = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body')}: {err['msg']}".strip(": ")
            for err in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={"code": 422, "data": None, "message": messages or "validation error"},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"code": 500, "data": None, "message": f"{type(exc).__name__}: {exc}"},
        )
