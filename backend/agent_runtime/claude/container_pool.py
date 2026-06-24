"""Container pool — manages Docker container lifecycle with concurrency limits.

Key behaviors:
- Max N containers running concurrently (default 5)
- Session-sticky: same session reuses the same container across turns
- Idle timeout: container destroyed after 30 min of inactivity
- Graceful queue: when pool is full, new requests wait for a slot
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from agent_runtime.claude.docker_client import DockerAgentClient


class PoolFullError(Exception):
    """Raised when the container pool is at capacity."""
    pass


@dataclass
class PooledContainer:
    client: DockerAgentClient
    session_id: str
    last_used: float = field(default_factory=time.time)
    busy: bool = False


class ContainerPool:
    """Manages a bounded pool of Docker containers for agent sessions."""

    MAX_CONTAINERS = int(__import__('os').environ.get("AGENT_MAX_CONTAINERS", "5"))
    IDLE_TIMEOUT = 1800  # 30 minutes

    def __init__(self) -> None:
        self._containers: list[PooledContainer] = []
        self._lock = asyncio.Lock()
        # Notified when a slot becomes idle so blocked acquirers wake up
        # immediately instead of polling every second.
        self._slot_available = asyncio.Condition(self._lock)
        self._idle_task: asyncio.Task | None = None

    async def _ensure_idle_check(self) -> None:
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._idle_loop())

    async def _idle_loop(self) -> None:
        """Periodically reap idle/dead containers."""
        while True:
            await asyncio.sleep(60)  # check every minute
            async with self._lock:
                now = time.time()
                to_remove = []
                for i, c in enumerate(self._containers):
                    # Reap if: idle AND past timeout, OR dead (even if busy).
                    # The busy-but-dead case is the backstop against leaked
                    # slots: a container killed mid-turn that was never
                    # released must still be reaped, otherwise it stays
                    # busy forever and exhausts the pool.
                    is_idle_expired = (not c.busy) and (now - c.last_used) > self.IDLE_TIMEOUT
                    is_dead = not c.client.is_alive()
                    if is_idle_expired or is_dead:
                        to_remove.append(i)
                for i in reversed(to_remove):
                    c = self._containers.pop(i)
                    try:
                        await c.client.close()
                    except Exception:
                        pass
                if to_remove:
                    self._slot_available.notify(len(to_remove))

    def _try_claim(self, session_id: str) -> tuple[DockerAgentClient, bool] | None:
        """Lock-held helper: claim an idle container or allocate a new one.

        Returns (client, is_new), or None if the pool is full and nothing
        is idle. Caller must already hold ``self._lock``.
        """
        # 1. Same session idle container (session-sticky reuse)
        for c in self._containers:
            if c.session_id == session_id and not c.busy:
                c.busy = True
                c.last_used = time.time()
                c.client._session_id = session_id
                return c.client, False

        # 2. Any idle container (repurpose)
        for c in self._containers:
            if not c.busy:
                c.session_id = session_id
                c.client._session_id = session_id
                c.busy = True
                c.last_used = time.time()
                return c.client, False

        # 3. New container
        if len(self._containers) < self.MAX_CONTAINERS:
            client = DockerAgentClient()
            client._session_id = session_id
            self._containers.append(PooledContainer(
                client=client, session_id=session_id, busy=True,
            ))
            return client, True

        return None  # pool full, nothing idle

    async def acquire(self, session_id: str) -> tuple[DockerAgentClient, bool]:
        """Get a container for the given session.

        Returns (client, is_new) — is_new=True means caller must call start().
        Reuses an existing idle container for the same session,
        or allocates a new one (blocking if pool is full).
        """
        await self._ensure_idle_check()

        # Fast path: try to claim under the lock without waiting.
        async with self._lock:
            claimed = self._try_claim(session_id)
            if claimed is not None:
                return claimed

        # Slow path: pool full, wait for a slot to be released (up to 2 min).
        # Use the Condition so release()/reaper wake us immediately instead
        # of polling every second.
        try:
            async with asyncio.timeout(120):
                async with self._slot_available:
                    while True:
                        claimed = self._try_claim(session_id)
                        if claimed is not None:
                            return claimed
                        await self._slot_available.wait()
        except TimeoutError:
            raise PoolFullError("请求人数太多，请稍后重试")

    async def release(self, client: DockerAgentClient) -> None:
        """Mark a container as idle (available for reuse) and wake waiters."""
        async with self._slot_available:
            for c in self._containers:
                if c.client is client:
                    c.busy = False
                    c.last_used = time.time()
                    self._slot_available.notify(1)
                    return

    async def shutdown(self) -> None:
        """Destroy all containers."""
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            for c in self._containers:
                try:
                    await c.client.close()
                except Exception:
                    pass
            self._containers.clear()
            self._slot_available.notify_all()


# Global singleton
_pool: ContainerPool | None = None


def get_container_pool() -> ContainerPool:
    global _pool
    if _pool is None:
        _pool = ContainerPool()
    return _pool
