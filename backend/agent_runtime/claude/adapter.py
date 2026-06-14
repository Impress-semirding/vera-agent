"""Claude Agent backend adapter.

Uses a container pool for Docker isolation (max N containers, 30min idle timeout).
Falls back to local subprocess if AGENT_USE_DOCKER=0.
"""

from __future__ import annotations

import os

from agent_runtime.base import AgentAdapter, AgentClient
from agent_runtime.claude.config import build_claude_config
from agent_runtime.claude.docker_client import DockerAgentClient


class ClaudeAgentAdapter(AgentAdapter):
    """Adapter for Claude Agent SDK backend (Docker pool by default)."""

    _pool_client: DockerAgentClient | None = None

    async def _create_client(self) -> AgentClient:
        config = await build_claude_config(
            self.agent_id, self.user_id, self.session_id, self.model_config,
        )

        if os.environ.get("AGENT_USE_DOCKER", "1") == "1":
            from agent_runtime.claude.container_pool import get_container_pool, PoolFullError
            pool = get_container_pool()
            try:
                client, is_new = await pool.acquire(self.session_id)
            except PoolFullError:
                raise PoolFullError("请求人数太多，请稍后重试")
            if is_new or not client.is_alive():
                await client.start(config)
            elif client._session_id != self.session_id:
                # Reused from different session — restart with new config
                await client.close()
                await client.start(config)
            self._pool_client = client
            return client  # type: ignore[return-value]
        else:
            from agent_runtime.claude.client import ClaudeAgentClient
            client = ClaudeAgentClient()
            await client.start(config)
            return client  # type: ignore[return-value]

    async def close(self) -> None:
        if self._pool_client is not None:
            # Kill container on close — don't leave stale agent running
            try:
                await self._pool_client.close()
            except Exception:
                pass
            self._pool_client = None
            self._client = None
        await super().close()
