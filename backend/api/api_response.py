"""Shared API helpers: response envelope, error handling, current-user dep.

The frontend (``fr/src/services/api.ts``) unwraps every response with an
axios interceptor that returns ``res.data`` directly and reads errors from
``err.response.data.message``. So every endpoint must answer with the
``{code, data, message}`` envelope and every error must carry a ``message``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request
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


# ─── Current user ───────────────────────────────────────────────────────────
# There is no real auth in the management API yet. ``created_by`` / ``updated_by``
# are populated from the ``X-User`` header so a client can impersonate a user
# (useful against the seeded data, e.g. ``X-User: ``). Defaults to
# ``current-user`` so created agents show up under the "mine" filter.

DEFAULT_USER = "current-user"


def current_user(x_user: str | None = Header(default=None, alias="X-User")) -> str:
    """Resolve the acting user from the ``X-User`` header.

    The frontend percent-encodes the value (``encodeURIComponent``) because
    HTTP header bytes are decoded as latin-1 — raw non-ASCII (e.g. Chinese
    names) would arrive mojibake'd. We unquote here to recover the real name.
    """
    return unquote(x_user) if x_user else DEFAULT_USER


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
