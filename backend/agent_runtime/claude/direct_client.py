"""Direct Claude Agent client — calls SDK in-process via asyncio, no subprocess.

This eliminates the stdin/stdout pipe deadlock problem entirely.
Events flow through an asyncio.Queue instead of OS pipes.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agent_runtime.claude.client import ClaudeAgentConfig


class DirectClaudeAgentClient:
    """Calls Claude Agent SDK directly (no subprocess).

    Has the same public interface as LLMClient / ClaudeAgentClient so
    _session_worker can use it transparently:
        - start(config)
        - send(text)
        - read_deltas() -> AsyncIterator[dict]
        - close()
        - is_alive()
    """

    def __init__(self) -> None:
        self._config: ClaudeAgentConfig | None = None
        self._event_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._alive: bool = False
        self.cwd: str = ""
        self.eof: bool = False

    async def start(self, config: ClaudeAgentConfig) -> None:
        self._config = config
        self.cwd = config.cwd
        self._alive = True
        self._task = asyncio.create_task(self._run_agent_loop())

    async def send(self, text: str) -> None:
        await self._input_queue.put(text)

    async def read_deltas(self) -> AsyncIterator[dict]:
        while True:
            event = await self._event_queue.get()
            if event is None:
                return
            yield event
            if event.get("type") in ("model_final", "error"):
                return

    async def close(self) -> None:
        self._alive = False
        await self._input_queue.put(None)  # signal shutdown
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def is_alive(self) -> bool:
        return self._alive and (self._task is None or not self._task.done())

    # ─── Internal agent loop ──────────────────────────────────────────

    async def _run_agent_loop(self) -> None:
        """Run the Claude Agent SDK directly in-process."""
        import os
        import json as _json
        from claude_agent_sdk import query, ClaudeAgentOptions
        from agent_runtime.claude.runner import _find_working_cli

        assert self._config is not None
        cfg = self._config

        cli_path = _find_working_cli()

        def _on_cli_stderr(line: str) -> None:
            # stderr from CLI — log but don't push to frontend (too noisy)
            pass

        mcp_servers: dict[str, dict] = {}
        for srv in cfg.mcp_servers:
            name = srv.get("name", "")
            if not name:
                continue
            transport = srv.get("transport", "stdio")
            if transport == "stdio":
                sc: dict = {"command": srv.get("command", ""), "type": "stdio"}
                if srv.get("args"):
                    sc["args"] = srv["args"]
                if srv.get("env"):
                    sc["env"] = srv["env"]
                mcp_servers[name] = sc
            elif transport == "sse":
                sc = {"type": "sse", "url": srv.get("url", "")}
                if srv.get("headers"):
                    sc["headers"] = srv["headers"]
                mcp_servers[name] = sc
            else:
                sc = {"type": "http", "url": srv.get("url", "")}
                if srv.get("headers"):
                    sc["headers"] = srv["headers"]
                mcp_servers[name] = sc

        options = ClaudeAgentOptions(
            model=cfg.model,
            max_turns=cfg.max_turns,
            allowed_tools=cfg.allowed_tools,
            cwd=cfg.cwd or None,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers,
            cli_path=cli_path,
            stderr=_on_cli_stderr,
        )

        os.environ.setdefault("CLAUDE_CODE_DISABLE_NON_ESSENTIAL_TTY", "1")
        os.environ.setdefault("CLAUDE_CODE_HEADLESS", "1")
        os.environ["ANTHROPIC_API_KEY"] = cfg.api_key
        os.environ["ANTHROPIC_BASE_URL"] = cfg.base_url

        session_id: str | None = None

        async def handle(msg) -> None:
            nonlocal session_id
            mt = type(msg).__name__

            if mt == "SystemMessage":
                if hasattr(msg, "subtype") and msg.subtype == "init":
                    data = getattr(msg, "data", {}) or {}
                    if isinstance(data, dict):
                        session_id = data.get("session_id", session_id)
                return

            if mt == "StreamEvent":
                event = getattr(msg, "event", None)
                if isinstance(event, dict):
                    await _dispatch_stream_event_wrapper(event)
                return

            if mt == "AssistantMessage":
                blocks = getattr(msg, "content", None)
                if isinstance(blocks, list):
                    for block in blocks:
                        await _dispatch_content_block_wrapper(block)
                return

            if mt == "UserMessage":
                blocks = getattr(msg, "content", None)
                if isinstance(blocks, list):
                    for block in blocks:
                        bt = type(block).__name__
                        if bt == "ToolResultBlock":
                            call_id = getattr(block, "tool_use_id", "")
                            output = getattr(block, "content", "")
                            if isinstance(output, list):
                                output = "\n".join(
                                    c.get("text", "") if isinstance(c, dict) else str(c) for c in output
                                )
                            is_error = getattr(block, "is_error", False)
                            out_str = str(output or "")
                            await self._event_queue.put({
                                "type": "tool.result", "callId": call_id,
                                "ok": not is_error, "output": out_str,
                            })
                        elif bt == "TextBlock":
                            await self._event_queue.put({
                                "type": "model_delta", "channel": "reasoning",
                                "text": block.text,
                            })
                return

            if mt == "ResultMessage":
                result = getattr(msg, "result", "") or ""
                content = result if isinstance(result, str) else str(result)
                await self._event_queue.put({
                    "type": "model_final", "content": content, "reasoningContent": "",
                })
                return

        async def _dispatch_content_block_wrapper(block) -> None:
            bt = type(block).__name__
            if bt == "TextBlock":
                await self._event_queue.put({
                    "type": "model_delta", "channel": "content", "text": block.text,
                })
            elif bt == "ThinkingBlock":
                await self._event_queue.put({
                    "type": "model_delta", "channel": "reasoning", "text": block.thinking,
                })
            elif bt == "ToolUseBlock":
                call_id = getattr(block, "id", "")
                name = getattr(block, "name", "")
                args_str = _json.dumps(block.input, ensure_ascii=False) if block.input else ""
                await self._event_queue.put({
                    "type": "tool.preparing", "callId": call_id, "name": name,
                })
                await self._event_queue.put({
                    "type": "tool.intent", "callId": call_id, "name": name, "args": args_str,
                })
            elif bt == "ToolResultBlock":
                call_id = getattr(block, "tool_use_id", "")
                output = getattr(block, "content", "")
                if isinstance(output, list):
                    output = "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in output)
                is_error = getattr(block, "is_error", False)
                await self._event_queue.put({
                    "type": "tool.result", "callId": call_id,
                    "ok": not is_error, "output": str(output or ""),
                })

        async def _dispatch_stream_event_wrapper(event: dict) -> None:
            et = event.get("type", "")
            delta = event.get("delta", {})
            content_block = event.get("content_block", {})
            if et == "content_block_start":
                cb_type = content_block.get("type", "")
                if cb_type == "tool_use":
                    await self._event_queue.put({
                        "type": "tool.preparing",
                        "callId": content_block.get("id", ""),
                        "name": content_block.get("name", ""),
                    })
            elif et == "content_block_delta":
                dt = delta.get("type", "")
                text = ""
                channel = ""
                if dt == "text_delta":
                    text = delta.get("text", ""); channel = "content"
                elif dt == "thinking_delta":
                    text = delta.get("thinking", ""); channel = "reasoning"
                elif dt == "input_json_delta":
                    text = delta.get("partial_json", ""); channel = "tool_args"
                if text and channel:
                    await self._event_queue.put({
                        "type": "model_delta", "channel": channel, "text": text,
                    })

        try:
            while self._alive:
                text = await self._input_queue.get()
                if text is None:
                    break

                await self._event_queue.put({
                    "type": "model_delta", "channel": "reasoning",
                    "text": f"→ 模型: {cfg.model}",
                })

                if session_id:
                    options.resume = session_id

                async for msg in query(prompt=text, options=options):
                    await handle(msg)

                # Ensure model_final is always emitted
                await self._event_queue.put({"type": "model_final", "content": "", "reasoningContent": ""})
        except asyncio.CancelledError:
            pass
        except Exception:
            import traceback
            await self._event_queue.put({
                "type": "error", "message": f"Agent error: {traceback.format_exc()}",
            })
            await self._event_queue.put({"type": "model_final", "content": "", "reasoningContent": ""})
        finally:
            self._alive = False
