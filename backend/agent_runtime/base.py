"""Generic agent runtime — protocol & adapter base.

The API layer (chat.py) depends ONLY on this module.  Concrete backends
(claude, custom, ...) register themselves in registry.py and provide
factories that build an AgentClient.

This keeps chat.py agnostic of which agent backend is in use.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class AgentClient(Protocol):
    """Minimal lifecycle interface every backend client must implement.

    Same surface as LLMClient / ClaudeAgentClient so the session worker
    can drive any backend identically.
    """

    async def send(self, text: str) -> None: ...
    async def read_deltas(self) -> AsyncIterator[dict]: ...
    async def close(self) -> None: ...
    def is_alive(self) -> bool: ...


class AgentAdapter:
    """Wraps a backend client with lazy init + uniform lifecycle.

    Subclasses override `_create_client()` to spawn the right backend.
    """

    def __init__(
        self,
        mode: str,
        agent_id: str,
        user_id: str,
        session_id: str,
        model_config,
    ) -> None:
        self.mode = mode
        self.agent_id = agent_id
        self.user_id = user_id
        self.session_id = session_id
        self.model_config = model_config
        self._client: AgentClient | None = None

    # ─── Subclasses implement this ───────────────────────────────────

    async def _create_client(self) -> AgentClient:
        """Spawn and configure the backend client. Raise on failure."""
        raise NotImplementedError

    # ─── Public API ──────────────────────────────────────────────────

    async def _ensure_client(self) -> None:
        """Lazy-init the client on first use.

        If creation fails, the error propagates; the adapter remains
        usable for a retry on the next turn.
        """
        if self._client is None:
            self._client = await self._create_client()

    async def send(self, text: str) -> None:
        await self._ensure_client()
        await self._client.send(text)  # type: ignore[union-attr]

    async def read_deltas(self) -> AsyncIterator[dict]:
        await self._ensure_client()
        async for event in self._client.read_deltas():
            yield event

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def release(self) -> None:
        """Release resources back to a pool for reuse instead of destroying.

        Default behavior = close (kill the backing client). Backends that
        manage a pool (e.g. Claude Docker containers) override this to
        return the client to the pool so a later turn can reuse it and
        avoid a cold start. Call this after a successful turn; call
        ``close()`` only when the client is dead or the session is ending.
        """
        await self.close()

    def is_alive(self) -> bool:
        if self._client is None:
            return False
        return self._client.is_alive()

    @property
    def client(self) -> AgentClient | None:
        """Direct access for abort holder."""
        return self._client
