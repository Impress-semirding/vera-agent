"""LLM subprocess client — manages agent/chat.py via stdin/stdout.

This is the normal-engine client: it spawns agent/chat.py (which talks to
an Anthropic-compatible Messages API) and streams deltas back. ClaudeAgentClient
(agent_runtime/claude/) mirrors this same stdin/stdout protocol.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import AsyncIterator


class LLMClient:
    """Spawns agent/chat.py and communicates via stdin/stdout JSON lines."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self.eof: bool = False

    async def start(
        self,
        model: str,
        base_url: str,
        api_key: str,
        max_tokens: int = 4096,
    ) -> None:
        """Start the agent/chat.py subprocess and send initial config."""
        # agent/chat.py lives at <backend>/agent/chat.py. This module is at
        # <backend>/agent_runtime/normal/llm_client.py, so walk up three dirs.
        chat_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "agent", "chat.py",
        )
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, chat_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr in the background to prevent pipe-buffer deadlock.
        # If stderr fills up (typically 64 KB), the subprocess would block.
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        # Send start config
        config = {
            "type": "start",
            "model": model,
            "baseUrl": base_url,
            "apiKey": api_key,
            "maxTokens": max_tokens,
        }
        await self._send(config)
        # Wait for ready signal
        ready = await self._read_line()
        if not ready or ready.get("type") != "ready":
            raise RuntimeError(f"LLM subprocess did not start: {ready}")

    async def send(self, text: str) -> None:
        """Send a user message to the subprocess."""
        await self._send({"type": "user_input", "text": text})

    async def read_deltas(self) -> AsyncIterator[dict]:
        """Yield JSON events from stdout until model_final is received.

        Sets self.eof = True if the subprocess closed stdout (died).
        """
        while True:
            event = await self._read_line()
            if event is None:
                # Subprocess closed stdout (crashed or exited).
                # Signal that the subprocess is dead so the caller can
                # avoid reusing it.
                self.eof = True
                return
            yield event
            if event.get("type") in ("model_final", "error"):
                return

    async def close(self) -> None:
        """Shut down the subprocess gracefully."""
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

    async def _drain_stderr(self) -> None:
        """Consume stderr in the background to prevent pipe-buffer deadlock."""
        try:
            while True:
                if not self._process or not self._process.stderr:
                    return
                line = await self._process.stderr.readline()
                if not line:
                    return
                # Log stderr output for debugging.
                print(f"[llm-subprocess] {line.decode('utf-8', errors='replace').rstrip()}", flush=True)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _send(self, obj: dict) -> None:
        """Write a JSON line to subprocess stdin."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("LLM subprocess not running")
        data = json.dumps(obj, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_line(self) -> dict | None:
        """Read one JSON line from subprocess stdout."""
        if not self._process or not self._process.stdout:
            return None
        raw = await self._process.stdout.readline()
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8").strip())
        except json.JSONDecodeError:
            return None
