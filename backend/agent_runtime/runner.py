"""Agent runner — generic subprocess dispatched by backend clients.

Reads JSON commands from stdin, dispatches to the correct agent backend by mode,
writes protocol events to stdout through StreamEmitter.

stdin protocol:
    {"type":"start", "mode":"claude"|"normal", "apiKey":"...", ...}
    {"type":"user_input", "text":"..."}
    {"type":"quit"}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure backend/ is on sys.path so we can import agent_runtime.*
_backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from agent_runtime.stream_emitter import StreamEmitter


# ═══════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════

class RunnerConfig:
    def __init__(self, data: dict):
        self.mode: str = data.get("mode", "claude")
        self.api_key: str = data.get("apiKey", "")
        self.base_url: str = data.get("baseUrl", "https://api.anthropic.com")
        self.model: str = data.get("model", "")
        self.cwd: str = data.get("cwd", "/tmp")
        self.mcp_servers: list[dict] = data.get("mcpServers", [])
        self.allowed_tools: list[str] = data.get("allowedTools", [])
        self.max_turns: int = data.get("maxTurns", 50)


# ═══════════════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════════════

_session_id: str | None = None
_config: RunnerConfig | None = None
_emitter: StreamEmitter = StreamEmitter("/tmp")
_final_emitted: bool = False


# ═══════════════════════════════════════════════════════════════════════
# Backend dispatch
# ═══════════════════════════════════════════════════════════════════════

async def _process_turn(text: str) -> None:
    """Route to the correct backend based on _config.mode."""
    if _config is None:
        return
    if _config.mode == "claude":
        await _process_turn_claude(text)
    else:
        await _process_turn_custom(text)


# ═══════════════════════════════════════════════════════════════════════
# Claude backend
# ═══════════════════════════════════════════════════════════════════════

async def _process_turn_claude(text: str) -> None:
    """Claude Agent SDK backend."""
    from claude_agent_sdk import query, ClaudeAgentOptions

    global _session_id

    assert _config is not None

    # Find working CLI binary
    cli_path = _find_working_cli()

    def _on_cli_stderr(line: str) -> None:
        _emitter.emit_delta("reasoning", f"[CLI] {line.rstrip()}")

    # Build MCP config
    mcp_servers = _build_mcp_config()

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

    if _session_id:
        options.resume = _session_id

    os.environ["ANTHROPIC_API_KEY"] = _config.api_key
    os.environ["ANTHROPIC_BASE_URL"] = _config.base_url
    os.environ.setdefault("CLAUDE_CODE_DISABLE_NON_ESSENTIAL_TTY", "1")
    os.environ.setdefault("CLAUDE_CODE_HEADLESS", "1")

    _emitter.emit_delta("reasoning", f"→ 模型: {_config.model}")

    try:
        async for msg in query(prompt=text, options=options):
            await _handle_claude_message(msg)
    except Exception as exc:
        import traceback
        _emitter.emit_error(f"SDK 错误: {exc}\n{traceback.format_exc()}")


def _find_working_cli() -> str | None:
    """Find a working arm64 Claude CLI binary."""
    import glob
    try:
        base = os.path.expanduser("~/.vscode/extensions")
        dirs = sorted(glob.glob(os.path.join(base, "anthropic.claude-code-*darwin-arm64")))
        if dirs:
            return os.path.join(dirs[-1], "resources", "native-binary", "claude")
    except Exception:
        pass
    return None


def _build_mcp_config() -> dict[str, dict]:
    """Convert RunnerConfig.mcp_servers to SDK format."""
    if _config is None:
        return {}
    mcp: dict[str, dict] = {}
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
        else:
            cfg = {"type": "http", "url": srv.get("url", "")}
            if srv.get("headers"):
                cfg["headers"] = srv["headers"]
        mcp[name] = cfg
    return mcp


# ─── Claude SDK message → StreamEmitter ───────────────────────────────

async def _handle_claude_message(msg) -> None:
    """Translate one Claude SDK message into StreamEmitter events."""
    global _session_id

    mt = type(msg).__name__

    if mt == "SystemMessage":
        if hasattr(msg, "subtype") and msg.subtype == "init":
            data = getattr(msg, "data", {}) or {}
            if isinstance(data, dict):
                _session_id = data.get("session_id", _session_id)
        return

    if mt == "StreamEvent":
        event = getattr(msg, "event", None)
        if isinstance(event, dict):
            _claude_stream_event(event)
        return

    if mt == "AssistantMessage":
        blocks = getattr(msg, "content", None)
        if isinstance(blocks, list):
            for block in blocks:
                _claude_content_block(block)
        return

    if mt == "UserMessage":
        blocks = getattr(msg, "content", None)
        if isinstance(blocks, list):
            for block in blocks:
                _claude_user_block(block)
        return

    if mt == "ResultMessage":
        result = getattr(msg, "result", "") or ""
        content = result if isinstance(result, str) else str(result)
        _emitter.emit_final(content=content)
        global _final_emitted
        _final_emitted = True
        return


def _claude_stream_event(event: dict) -> None:
    et = event.get("type", "")
    delta = event.get("delta", {})
    content_block = event.get("content_block", {})
    if et == "content_block_start":
        if content_block.get("type") == "tool_use":
            _emitter.emit_preparing(content_block.get("id", ""), content_block.get("name", ""))
    elif et == "content_block_delta":
        dt = delta.get("type", "")
        if dt == "text_delta":
            _emitter.emit_delta("content", delta.get("text", ""))
        elif dt == "thinking_delta":
            _emitter.emit_delta("reasoning", delta.get("thinking", ""))
        elif dt == "input_json_delta":
            _emitter.emit_delta("tool_args", delta.get("partial_json", ""))


def _claude_content_block(block) -> None:
    bt = type(block).__name__
    if bt == "TextBlock":
        _emitter.emit_delta("content", block.text)
    elif bt == "ThinkingBlock":
        _emitter.emit_delta("reasoning", block.thinking)
    elif bt == "ToolUseBlock":
        call_id = getattr(block, "id", "")
        name = getattr(block, "name", "")
        args_str = json.dumps(block.input, ensure_ascii=False) if block.input else ""
        _emitter.emit_preparing(call_id, name)
        _emitter.emit_intent(call_id, name, args_str)
    elif bt == "ToolResultBlock":
        _claude_tool_result(block)


def _claude_user_block(block) -> None:
    bt = type(block).__name__
    if bt == "ToolResultBlock":
        _claude_tool_result(block)
    elif bt == "TextBlock":
        _emitter.emit_delta("reasoning", block.text)


def _claude_tool_result(block) -> None:
    call_id = getattr(block, "tool_use_id", "") or getattr(block, "id", "")
    output = getattr(block, "content", "")
    if isinstance(output, list):
        output = "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in output)
    is_error = getattr(block, "is_error", False)
    _emitter.emit_result(call_id, not is_error, str(output or ""))


# ═══════════════════════════════════════════════════════════════════════
# Custom backend (placeholder — implement your own agent here)
# ═══════════════════════════════════════════════════════════════════════

async def _process_turn_custom(text: str) -> None:
    """Custom / self-built agent backend.

    Implement your agent logic here.  Use `_emitter` to push protocol events:

        _emitter.emit_delta("reasoning", "分析中...")
        _emitter.emit_preparing("c1", "search")
        _emitter.emit_intent("c1", "search", '{"q":"..."}')
        _emitter.emit_result("c1", True, "结果...")
        _emitter.emit_delta("content", "最终回复...")
        _emitter.emit_final(content="最终回复")
    """
    assert _config is not None

    _emitter.emit_delta("reasoning", f"→ 自定义 Agent, 模型: {_config.model}")

    # TODO: Replace with your actual agent logic
    _emitter.emit_delta("content", "自定义 Agent 尚未实现")
    _emitter.emit_final(content="自定义 Agent 尚未实现")


# ═══════════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    global _config, _emitter

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            _emitter.emit_error("invalid JSON on stdin")
            continue

        cmd_type = cmd.get("type", "")

        if cmd_type == "start":
            _config = RunnerConfig(cmd)
            _emitter = StreamEmitter(_config.cwd)
            os.makedirs(_config.cwd, exist_ok=True)
            os.chdir(_config.cwd)
            _emitter.emit_ready(_config.model)

        elif cmd_type == "user_input":
            text = cmd.get("text", "")
            if text and _config:
                global _final_emitted
                _final_emitted = False
                asyncio.run(_process_turn(text))
                if not _final_emitted:
                    _emitter.emit_final()

        elif cmd_type == "quit":
            break


if __name__ == "__main__":
    main()
