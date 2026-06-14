"""Claude Agent backend adapter.

Spawns a subprocess (runner.py) that uses StreamEmitter for pipe-safe stdout.
"""

from __future__ import annotations

from agent_runtime.base import AgentAdapter, AgentClient
from agent_runtime.claude.client import ClaudeAgentClient
from agent_runtime.claude.config import build_claude_config


class ClaudeAgentAdapter(AgentAdapter):
    """Adapter for Claude Agent SDK backend (subprocess + StreamEmitter)."""

    async def _create_client(self) -> AgentClient:
        config = await build_claude_config(
            self.agent_id, self.user_id, self.session_id, self.model_config,
        )
        client = ClaudeAgentClient()
        await client.start(config)
        return client  # type: ignore[return-value]
