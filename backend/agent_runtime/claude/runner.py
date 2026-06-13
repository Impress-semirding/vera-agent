"""
Claude Agent runner — subprocess script invoked by ClaudeAgentClient.

Reads JSON commands from stdin, calls Claude Agent SDK, writes protocol events
to stdout.  Reuses the same session across turns so conversation context is
preserved.

stdin protocol:
    {"type":"start", "apiKey":"...", "model":"...", ...}  — initial config
    {"type":"user_input", "text":"..."}                  — user message
    {"type":"quit"}                                      — shut down

stdout protocol (reuses WebSocket chat protocol):
    {"type":"ready"}
    {"type":"model_delta", "channel":"reasoning"|"content"|"tool_args", "text":"..."}
    {"type":"tool.preparing", "callId":"...", "name":"..."}
    {"type":"tool.intent", "callId":"...", "name":"...", "args":"..."}
    {"type":"tool.result", "callId":"...", "ok":true, "output":"..."}
    {"type":"model_final", "content":"...", "reasoningContent":"..."}
    {"type":"error", "message":"..."}

Usage:
    python claude-runner.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import os

from claude_agent_sdk import query, ClaudeAgentOptions


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _write(obj: dict) -> None:
    """Write one JSON line to stdout (flush immediately)."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _find_working_cli() -> str | None:
    """Find a working arm64 Claude CLI binary.

    The SDK's bundled x86_64 binary hangs on Apple Silicon in headless mode.
    We prefer the VSCode extension's native arm64 binary if available.
    """
    import glob
    try:
        base = os.path.expanduser("~/.vscode/extensions")
        dirs = sorted(glob.glob(os.path.join(base, "anthropic.claude-code-*darwin-arm64")))
        if dirs:
            return os.path.join(dirs[-1], "resources", "native-binary", "claude")
    except Exception:
        pass
    return None  # let SDK fall back to its bundled binary


def _write_delta(channel: str, text: str) -> None:
    _write({"type": "model_delta", "channel": channel, "text": text})


# ═══════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════

class RunnerConfig:
    """Holds configuration received via the 'start' command."""

    def __init__(self, data: dict):
        self.api_key: str = data.get("apiKey", "")
        self.base_url: str = data.get("baseUrl", "https://api.anthropic.com")
        self.model: str = data.get("model", "claude-sonnet-4-20250514")
        self.cwd: str = data.get("cwd", "/tmp")
        self.claude_md: str = data.get("claudeMd", "")
        self.skills: list[dict] = data.get("skills", [])
        self.mcp_servers: list[dict] = data.get("mcpServers", [])
        self.allowed_tools: list[str] = data.get("allowedTools", [])
        self.max_turns: int = data.get("maxTurns", 50)


# ═══════════════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════════════

_session_id: str | None = None
_config: RunnerConfig | None = None


# ═══════════════════════════════════════════════════════════════════════
# SDK event → stdout protocol translation
# ═══════════════════════════════════════════════════════════════════════

async def _handle_sdk_message(msg) -> None:
    """Translate one SDK message into our stdout protocol events.

    StreamEvent delivers real-time Anthropic API deltas — these are the
    primary source for streaming.  AssistantMessage is the fallback for
    fully-assembled blocks when the CLI doesn't emit StreamEvents.
    """
    global _session_id

    msg_type = type(msg).__name__

    # ── SystemMessage (init) — capture session_id ──
    if msg_type == "SystemMessage":
        if hasattr(msg, "subtype") and msg.subtype == "init":
            data = getattr(msg, "data", {}) or {}
            if isinstance(data, dict):
                _session_id = data.get("session_id", _session_id)
        return

    # ── StreamEvent — real-time Anthropic SSE deltas ──
    if msg_type == "StreamEvent":
        event = getattr(msg, "event", None)
        if not isinstance(event, dict):
            _write({"type": "model_delta", "channel": "reasoning",
                    "text": "[StreamEvent] event type=" + type(event).__name__ + " " + str(event)[:200]})
            return
        _dispatch_stream_event(event)
        return

    # ── AssistantMessage — assembled blocks (fallback) ──
    if msg_type == "AssistantMessage":
        blocks = getattr(msg, "content", None)
        if not isinstance(blocks, list):
            return
        for block in blocks:
            _dispatch_content_block(block)
        return

    # ── UserMessage — tool results / skill output ──
    if msg_type == "UserMessage":
        blocks = getattr(msg, "content", None)
        if not isinstance(blocks, list):
            return
        for block in blocks:
            block_type = type(block).__name__
            if block_type == "ToolResultBlock":
                call_id = getattr(block, "tool_use_id", "")
                output = getattr(block, "content", "")
                if isinstance(output, list):
                    output = "\n".join(
                        c.get("text", "") if isinstance(c, dict) else str(c) for c in output
                    )
                is_error = getattr(block, "is_error", False)
                _write({"type": "tool.result", "callId": call_id,
                        "ok": not is_error, "output": str(output or "")})
            elif block_type == "TextBlock":
                # Skill output / context injection — show as reasoning
                _write_delta("reasoning", block.text)
        return

    # ── ResultMessage — turn complete ──
    if msg_type == "ResultMessage":
        result = getattr(msg, "result", "") or ""
        content = result if isinstance(result, str) else str(result)
        _write({"type": "model_final", "content": content, "reasoningContent": ""})
        return


def _dispatch_stream_event(event: dict) -> None:
    """Route a raw Anthropic SSE event to the correct protocol action."""
    event_type = event.get("type", "")
    delta = event.get("delta", {})
    content_block = event.get("content_block", {})

    if event_type == "content_block_start":
        cb_type = content_block.get("type", "")
        if cb_type == "tool_use":
            _write({"type": "tool.preparing",
                    "callId": content_block.get("id", ""),
                    "name": content_block.get("name", "")})

    elif event_type == "content_block_delta":
        delta_type = delta.get("type", "")
        if delta_type == "text_delta":
            text = delta.get("text", "")
            if text:
                _write_delta("content", text)
        elif delta_type == "thinking_delta":
            text = delta.get("thinking", "")
            if text:
                _write_delta("reasoning", text)
        elif delta_type == "input_json_delta":
            text = delta.get("partial_json", "")
            if text:
                _write_delta("tool_args", text)

    elif event_type == "content_block_stop":
        pass


def _dispatch_content_block(block) -> None:
    """Route an assembled ContentBlock (AssistantMessage fallback)."""
    block_type = type(block).__name__

    if block_type == "TextBlock":
        _write_delta("content", block.text)
    elif block_type == "ThinkingBlock":
        _write_delta("reasoning", block.thinking)
    elif block_type == "ToolUseBlock":
        call_id = getattr(block, "id", "")
        name = getattr(block, "name", "")
        args_str = json.dumps(block.input, ensure_ascii=False) if block.input else ""
        # Emit preparing + intent together (args are already complete)
        _write({"type": "tool.preparing", "callId": call_id, "name": name})
        _write({"type": "tool.intent", "callId": call_id, "name": name, "args": args_str})
    elif block_type == "ToolResultBlock":
        call_id = getattr(block, "tool_use_id", "")
        output = getattr(block, "content", "")
        if isinstance(output, list):
            output = "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in output)
        is_error = getattr(block, "is_error", False)
        _write({"type": "tool.result", "callId": call_id, "ok": not is_error, "output": str(output or "")})


# ═══════════════════════════════════════════════════════════════════════
# Process one user turn
# ═══════════════════════════════════════════════════════════════════════

async def _process_turn(text: str) -> None:
    """Send user text to Claude Agent SDK and stream events to stdout."""
    global _session_id

    assert _config is not None

    # Point to a working arm64 Claude CLI (the SDK's bundled x86_64 binary
    # hangs under Rosetta on Apple Silicon in headless mode).
    cli_path = _find_working_cli()

    # Capture the SDK's internal CLI stderr for debugging
    def _on_cli_stderr(line: str) -> None:
        _write({"type": "model_delta", "channel": "reasoning",
                "text": f"[CLI] {line.rstrip()}"})

    # Convert our MCP server config to SDK format
    mcp_servers: dict[str, dict] = {}
    for srv in _config.mcp_servers:
        name = srv.get("name", "")
        if not name:
            continue
        transport = srv.get("transport", "stdio")
        if transport == "stdio":
            cfg: dict = {"command": srv.get("command", ""), "type": "stdio"}
            if srv.get("args"):
                cfg["args"] = srv["args"]
            if srv.get("env"):
                cfg["env"] = srv["env"]
        elif transport == "sse":
            cfg = {"type": "sse", "url": srv.get("url", "")}
            if srv.get("headers"):
                cfg["headers"] = srv["headers"]
        else:  # streamable-http
            cfg = {"type": "http", "url": srv.get("url", "")}
            if srv.get("headers"):
                cfg["headers"] = srv["headers"]
        mcp_servers[name] = cfg

    options = ClaudeAgentOptions(
        model=_config.model,
        max_turns=_config.max_turns,
        allowed_tools=_config.allowed_tools,
        cwd=_config.cwd or None,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        cli_path=cli_path,
        stderr=_on_cli_stderr,
    )

    # If we have a session, resume it
    if _session_id:
        options.resume = _session_id

    # Point SDK at the configured endpoint (API key + base URL come from ModelConfig)
    os.environ["ANTHROPIC_API_KEY"] = _config.api_key
    os.environ["ANTHROPIC_BASE_URL"] = _config.base_url

    # Log config for debugging
    _write({"type": "model_delta", "channel": "reasoning",
            "text": f"→ 模型: {_config.model}, base_url: {_config.base_url}"})

    # The SDK spawns a Claude CLI subprocess internally. In headless mode
    # we must ensure it doesn't wait for TTY input.
    os.environ.setdefault("CLAUDE_CODE_DISABLE_NON_ESSENTIAL_TTY", "1")
    os.environ.setdefault("CLAUDE_CODE_HEADLESS", "1")

    try:
        async for msg in query(prompt=text, options=options):
            await _handle_sdk_message(msg)
    except Exception as exc:
        import traceback
        _write({"type": "error", "message": f"SDK 错误: {exc}\n{traceback.format_exc()}"})


# ═══════════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    """Read commands from stdin, process them, write events to stdout."""
    global _config

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            _write({"type": "error", "message": "invalid JSON on stdin"})
            continue

        cmd_type = cmd.get("type", "")

        if cmd_type == "start":
            _config = RunnerConfig(cmd)
            # Enter workspace (config.py already synced CLAUDE.md + skills)
            os.makedirs(_config.cwd, exist_ok=True)
            os.chdir(_config.cwd)
            _write({"type": "ready", "model": _config.model})

        elif cmd_type == "user_input":
            text = cmd.get("text", "")
            if text and _config:
                asyncio.run(_process_turn(text))

        elif cmd_type == "quit":
            break


if __name__ == "__main__":
    main()
