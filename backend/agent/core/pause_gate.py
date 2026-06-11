"""
PauseGate — asyncio.Future-based approval gate.

Ports src/core/pause-gate.ts. Tools that need human approval call ask(),
which blocks until the frontend sends back a response via POST /cmd.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateRequest:
    """A pending approval request."""
    gate_id: int
    kind: str  # "shell", "path", "choice", "plan", "checkpoint", "revision"
    payload: dict[str, Any]
    tab_id: str | None = None
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())


class PauseGate:
    """
    Manages pending approval requests. Tools call ask() to suspend;
    the command handler calls resolve() to unblock them.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self._pending: dict[int, GateRequest] = {}
        self._on_ask: list[Any] = []  # callbacks: (GateRequest) -> None

    def on(self, callback: Any) -> None:
        """Register a callback fired when a new gate is created."""
        self._on_ask.append(callback)

    async def ask(self, kind: str, payload: dict[str, Any], tab_id: str | None = None) -> Any:
        """
        Create a gate request and wait for resolution.
        Returns the response dict from the frontend.
        """
        gate_id = self._next_id
        self._next_id += 1
        req = GateRequest(gate_id=gate_id, kind=kind, payload=payload, tab_id=tab_id)
        self._pending[gate_id] = req

        # Notify listeners (so they can emit the $*_required event via SSE)
        for cb in self._on_ask:
            cb(req)

        # Wait for resolve() to set the future result
        return await req.future

    def resolve(self, gate_id: int, response: Any) -> bool:
        """Resolve a pending gate. Returns True if found."""
        req = self._pending.pop(gate_id, None)
        if req is None:
            return False
        if not req.future.done():
            req.future.set_result(response)
        return True

    def forget(self, gate_id: int) -> GateRequest | None:
        """Remove a pending gate without resolving it."""
        return self._pending.pop(gate_id, None)

    def cancel_all(self) -> None:
        """Cancel all pending gates (e.g. on abort)."""
        for req in self._pending.values():
            if not req.future.done():
                req.future.cancel()
        self._pending.clear()
