"""Reasonix management API — FastAPI entry point.

Run from the ``server-py`` directory:

    uvicorn api.main:app --host 127.0.0.1 --port 18080 --reload

The Vite dev server (``fr/``) proxies ``/api`` → ``http://127.0.0.1:18080``,
so all routes are mounted under ``/api/v1`` to match the frontend's
``axios`` ``baseURL: '/api/v1'``.

Startup creates the SQLite schema (``data/db/reasonix.db``) and seeds sample data.
The sibling ``reasonix_server`` package owns the *agent runtime* and is kept
fully separate.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.api_response import ok, register_exception_handlers
from api.database import async_session, init_db
from api.models.seed import seed
from api.routers import (
    agents,
    auth,
    chat,
    config_files,
    history,
    mcp,
    messages,
    model_configs,
    permissions,
    push,
    session_settings,
    sessions,
    skills,
    wecom,
)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and seed sample data on startup."""
    await init_db()
    async with async_session() as db:
        await seed(db)
    yield


app = FastAPI(
    title="Reasonix Management API",
    version="0.1.0",
    description="Agent management REST API (SQLite + Pydantic) for the Reasonix frontend.",
    lifespan=lifespan,
)

# Permissive CORS for local development (Vite runs on :3000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

# Mount every router under /api/v1.
for _router in (
    agents.router,
    auth.router,
    sessions.router,
    messages.router,
    chat.router,
    mcp.router,
    skills.router,
    model_configs.router,
    permissions.router,
    push.router,
    wecom.router,
    session_settings.router,
    config_files.router,
    history.router,
):
    app.include_router(_router, prefix=API_PREFIX)


@app.get("/")
async def root():
    return ok({"service": "reasonix-management-api", "docs": "/docs", "prefix": API_PREFIX})


@app.get("/health")
async def health():
    return ok({"status": "ok"})


def main():
    host = os.environ.get("REASONIX_API_HOST", "127.0.0.1")
    port = int(os.environ.get("REASONIX_API_PORT", "18080"))
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=bool(os.environ.get("REASONIX_API_RELOAD")),
        log_level=os.environ.get("REASONIX_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
