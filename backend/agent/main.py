"""
Reasonix Python HTTP backend — FastAPI entry point.

Endpoints:
  POST /cmd    — receive OutgoingCommand from Tauri
  GET  /events — SSE stream of IncomingEvent back to Tauri
  GET  /health — liveness check

Startup sequence:
  1. Bind to 127.0.0.1:{port} (port 0 = ephemeral)
  2. Print REASONIX_READY port=<port> token=<token> to stdout
  3. Rust reads this line, connects SSE to /events, starts POSTing to /cmd
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from reasonix_server.desktop import DesktopManager
from reasonix_server.emitter import SSEEventBus, bus as global_bus

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Reasonix Python Backend", version="0.1.0")

bus: SSEEventBus = global_bus
desktop: DesktopManager = DesktopManager(bus)

_auth_token: str = ""


def _check_token(request: Request) -> bool:
    """Validate the auth token from query param or header."""
    token = request.query_params.get("token") or request.headers.get("X-Reasonix-Token", "")
    return secrets.compare_digest(token, _auth_token)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/cmd")
async def command_endpoint(request: Request) -> Response:
    """Receive an OutgoingCommand from Tauri."""
    if not _check_token(request):
        return Response(status_code=403, content="bad token")

    body = await request.body()
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="invalid json")

    # Fire-and-forget: handle command asynchronously
    # Errors are emitted as $error events via SSE, not as HTTP errors
    try:
        await desktop.handle_command(raw)
    except Exception as e:
        bus.emit(
            __import__("reasonix_server.protocol", fromlist=["ProtocolErrorEvent"]).ProtocolErrorEvent(
                message=f"command error: {e}"
            )
        )

    return Response(status_code=200, content="ok")


async def _event_generator(request: Request):
    """SSE generator that yields events from the bus."""
    q = bus.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                # Send keepalive ping
                yield {"event": "ping", "data": json.dumps({"kind": "ping"})}
                continue
            if item is None:
                break
            yield {"data": item}
    finally:
        bus.unsubscribe(q)


@app.get("/events")
async def events_endpoint(request: Request, token: str = Query("")) -> EventSourceResponse:
    """SSE stream of IncomingEvent objects."""
    if not secrets.compare_digest(token, _auth_token):
        return Response(status_code=403, content="bad token")

    return EventSourceResponse(_event_generator(request))


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _on_startup():
    """Boot tabs and signal readiness."""
    desktop.boot()


def main():
    global _auth_token

    parser = argparse.ArgumentParser(description="Reasonix Python HTTP backend")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = ephemeral)")
    parser.add_argument("--token", type=str, default="", help="Auth token (auto-generated if empty)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    args = parser.parse_args()

    _auth_token = args.token or secrets.token_hex(32)

    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port or 0,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # After startup, print the actual bound port for Rust to read
    async def _signal_ready():
        # Give uvicorn a moment to bind the socket
        for _ in range(50):
            if server.servers:
                for s in server.servers:
                    try:
                        addr = s.getsockname()
                        if isinstance(addr, tuple) and addr[1]:
                            print(f"REASONIX_READY port={addr[1]} token={_auth_token}", flush=True)
                            return
                    except Exception:
                        pass
            await asyncio.sleep(0.1)
        # Fallback: print requested port
        print(f"REASONIX_READY port={args.port} token={_auth_token}", flush=True)

    @app.on_event("startup")
    async def _ready_hook():
        asyncio.create_task(_signal_ready())

    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
