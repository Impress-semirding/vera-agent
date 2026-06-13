"""Backend registry — maps mode to an AgentAdapter factory.

chat.py calls `create_adapter(...)` and gets back a fully-configured
adapter without knowing which backend it uses.

To add a new backend (e.g. a self-built agent), register a factory here:
    register_backend("custom", CustomAgentAdapter)
"""

from __future__ import annotations

from typing import Callable, Awaitable

from agent_runtime.base import AgentAdapter


# Registry: mode name → adapter factory callable
_ADAPTER_FACTORIES: dict[str, Callable[..., Awaitable[AgentAdapter]]] = {}


def register_backend(
    mode: str,
    factory: Callable[..., Awaitable[AgentAdapter]],
) -> None:
    """Register an adapter factory for a given mode.

    factory signature: async factory(mode, agent_id, user_id, session_id, model_config) -> AgentAdapter
    """
    _ADAPTER_FACTORIES[mode] = factory


def _ensure_defaults() -> None:
    """Lazily register built-in backends on first use."""
    if _ADAPTER_FACTORIES:
        return

    # Normal mode: raw LLM HTTP client
    async def _normal_factory(mode, agent_id, user_id, session_id, model_config):
        from agent_runtime.normal.adapter import NormalAgentAdapter
        return NormalAgentAdapter(mode, agent_id, user_id, session_id, model_config)

    # Claude mode: Claude Agent SDK
    async def _claude_factory(mode, agent_id, user_id, session_id, model_config):
        from agent_runtime.claude.adapter import ClaudeAgentAdapter
        return ClaudeAgentAdapter(mode, agent_id, user_id, session_id, model_config)

    register_backend("normal", _normal_factory)
    register_backend("claude", _claude_factory)


async def create_adapter(
    mode: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    model_config,
) -> AgentAdapter:
    """Create the adapter for the given mode.

    Falls back to "normal" if the mode is unknown.
    """
    _ensure_defaults()
    factory = _ADAPTER_FACTORIES.get(mode) or _ADAPTER_FACTORIES["normal"]
    return await factory(mode, agent_id, user_id, session_id, model_config)
