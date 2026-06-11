"""
SSE event bus — broadcasts IncomingEvent objects to all connected SSE clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from reasonix_server.protocol import IncomingEvent


class SSEEventBus:
    """
    Fan-out event bus. The /events SSE endpoint subscribes;
    the rest of the app calls emit() to push events to all subscribers.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[str | None]] = []

    def subscribe(self) -> asyncio.Queue[str | None]:
        """Create a new subscriber queue. Consumer reads from this queue."""
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4096)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str | None]) -> None:
        self._subscribers.remove(q)

    def emit(self, event: IncomingEvent, tab_id: str | None = None) -> None:
        """Broadcast an event to all SSE subscribers."""
        payload: dict[str, Any] = event.model_dump(by_alias=True)
        if tab_id is not None:
            payload["tabId"] = tab_id
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for q in self._subscribers:
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                # Drop oldest events if queue is full (streaming backpressure)
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(line)

    def close(self) -> None:
        """Signal all subscribers that the bus is shutting down."""
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


# Global singleton — imported by main.py and desktop.py
bus = SSEEventBus()
