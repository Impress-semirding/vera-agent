"""LLM subprocess client — manages agent/chat.py via stdin/stdout."""

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

    async def start(
        self,
        model: str,
        base_url: str,
        api_key: str,
        max_tokens: int = 4096,
    ) -> None:
        """Start the agent/chat.py subprocess and send initial config."""
        chat_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent", "chat.py")
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, chat_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
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
        """Yield JSON events from stdout until model_final is received."""
        while True:
            event = await self._read_line()
            if event is None:
                return
            yield event
            if event.get("type") in ("model_final", "error"):
                return

    async def close(self) -> None:
        """Shut down the subprocess gracefully."""
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
