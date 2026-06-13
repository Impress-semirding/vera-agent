"""Claude Agent subprocess client — manages claude-runner.py via stdin/stdout.

This class has the same public interface as LLMClient so _session_worker
can use either one transparently:
    - start(config)      → spawn subprocess + handshake
    - send(text)         → write user_input to stdin
    - read_deltas()      → async generator yielding protocol events
    - close()            → graceful shutdown
    - is_alive()         → check if subprocess is still running
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ClaudeAgentConfig:
    """Configuration for a Claude Agent subprocess."""
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-sonnet-4-20250514"
    cwd: str = "/tmp"
    claude_md: str = ""
    skills: list[dict] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 50


class ClaudeAgentClient:
    """Spawns claude-runner.py and communicates via stdin/stdout JSON lines.

    The runner uses Claude Agent SDK internally.  This class is a thin async
    wrapper — it does NOT inspect or transform events (the runner does).
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self.eof: bool = False
        self.cwd: str = "/tmp"

    async def start(self, config: ClaudeAgentConfig) -> None:
        """Spawn claude-runner.py and send initial config."""
        self.cwd = config.cwd
        runner_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "runner.py",
        )
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, runner_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.cwd or None,
        )
        # Drain stderr to prevent pipe deadlock
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Send start config
        await self._send({
            "type": "start",
            "apiKey": config.api_key,
            "baseUrl": config.base_url,
            "model": config.model,
            "cwd": config.cwd,
            "claudeMd": config.claude_md,
            "skills": config.skills,
            "mcpServers": config.mcp_servers,
            "allowedTools": config.allowed_tools,
            "maxTurns": config.max_turns,
        })

        # Wait for ready signal
        try:
            ready = await self._read_line()
            if not ready or ready.get("type") != "ready":
                raise RuntimeError(f"Claude Agent runner did not start: {ready}")
        except Exception:
            await self.close()
            raise

    async def send(self, text: str) -> None:
        """Send a user message to the runner."""
        await self._send({"type": "user_input", "text": text})

    async def read_deltas(self) -> AsyncIterator[dict]:
        """Yield protocol events from stdout until model_final or error."""
        while True:
            event = await self._read_line()
            if event is None:
                self.eof = True
                return
            yield event
            if event.get("type") in ("model_final", "error"):
                return

    async def close(self) -> None:
        """Shut down the runner subprocess gracefully."""
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            self._stderr_task = None
        if self._process and self._process.returncode is None:
            try:
                await self._send({"type": "quit"})
            except Exception:
                pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        return self._process is not None and self._process.returncode is None

    # ─── Private helpers (same pattern as LLMClient) ──

    async def _send(self, obj: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Claude Agent runner not running")
        data = json.dumps(obj, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_line(self) -> dict | None:
        if not self._process or not self._process.stdout:
            return None
        raw = await self._process.stdout.readline()
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8").strip())
        except json.JSONDecodeError:
            return None

    async def _drain_stderr(self) -> None:
        try:
            while True:
                if not self._process or not self._process.stderr:
                    return
                line = await self._process.stderr.readline()
                if not line:
                    return
                print(f"[claude-runner] {line.decode('utf-8', errors='replace').rstrip()}", flush=True)
        except asyncio.CancelledError:
            return
        except Exception:
            return
