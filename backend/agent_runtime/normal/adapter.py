"""Normal Agent backend adapter — wraps the existing LLMClient.

Uses a raw Anthropic-compatible HTTP API client (no agent loop, no tools).
This is the legacy/default backend.
"""

from __future__ import annotations

from agent_runtime.base import AgentAdapter, AgentClient
from api.llm_client import LLMClient


class NormalAgentAdapter(AgentAdapter):
    """Adapter for the raw LLM HTTP backend."""

    async def _create_client(self) -> AgentClient:
        if self.model_config is None:
            raise RuntimeError("模型未配置")

        client = LLMClient()
        await client.start(
            model=self.model_config.model_id,
            base_url=self.model_config.base_url,
            api_key=self.model_config.api_key,
        )
        return client  # type: ignore[return-value]
