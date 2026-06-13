"""Claude Agent backend adapter.

Builds a DirectClaudeAgentClient (no subprocess, no pipe deadlock).
"""

from __future__ import annotations

from agent_runtime.base import AgentAdapter, AgentClient
from agent_runtime.claude.config import build_claude_config
from agent_runtime.claude.direct_client import DirectClaudeAgentClient


class ClaudeAgentAdapter(AgentAdapter):
    """Adapter for Claude Agent SDK backend (direct, no subprocess)."""

    async def _create_client(self) -> AgentClient:
        config = await build_claude_config(
            self.agent_id, self.user_id, self.session_id, self.model_config,
        )
        client = DirectClaudeAgentClient()
        await client.start(config)
        return client  # type: ignore[return-value]
