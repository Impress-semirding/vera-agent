"""Docker-based Claude Agent client.

Spawns a Docker container running runner.py, communicates via stdin/stdout.
Provides filesystem isolation — the agent cannot access host files outside
mounted volumes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import AsyncIterator

from agent_runtime.claude.client import ClaudeAgentConfig


class DockerAgentClient:
    """Spawns a Docker container and communicates via stdin/stdout JSON lines.

    Same public interface as LLMClient / ClaudeAgentClient.
    """

    IMAGE_NAME = "vera-agent-runner:latest"

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._container_id: str | None = None
        self.eof: bool = False
        self.cwd: str = "/tmp"
        self._session_id: str = ""  # set by pool on reuse

    # ─── Build image ──────────────────────────────────────────────────

    @classmethod
    async def ensure_image(cls) -> None:
        """Build the Docker image if it doesn't exist."""
        # Check if image exists
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", cls.IMAGE_NAME,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        if rc == 0:
            return  # already built

        docker_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docker"
        )
        print(f"[docker] Building {cls.IMAGE_NAME}...", flush=True)
        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", cls.IMAGE_NAME, docker_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if proc.stdout:
            async for line in proc.stdout:
                print(f"[docker-build] {line.decode().rstrip()}", flush=True)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"Docker build failed with exit code {rc}")

    # ─── Public API ───────────────────────────────────────────────────

    async def start(self, config: ClaudeAgentConfig) -> None:
        """Start Docker container."""
        await self.ensure_image()
        self.cwd = config.cwd

        # Ensure workspace dirs exist
        os.makedirs(config.cwd, exist_ok=True)
        os.makedirs(os.path.join(config.cwd, "output"), exist_ok=True)
        os.makedirs(os.path.join(config.cwd, ".claude-persist"), exist_ok=True)

        cmd = [
            "docker", "run", "-i", "--rm",
            "--name", f"vera-agent-{os.path.basename(config.cwd)}-{os.urandom(4).hex()}",
            # Mount workspace (read-write)
            "-v", f"{os.path.abspath(config.cwd)}:/workspace",
            # Mount Claude session state (persist across container restarts)
            "-v", f"{os.path.abspath(os.path.join(config.cwd, '.claude-persist'))}:/home/agent/.claude",
            # Pass env vars
            "-e", f"ANTHROPIC_API_KEY={config.api_key}",
            "-e", f"ANTHROPIC_BASE_URL={config.base_url}",
            "-e", "CLAUDE_CODE_DISABLE_NON_ESSENTIAL_TTY=1",
            "-e", "CLAUDE_CODE_HEADLESS=1",
            # Network
            "--network", "host" if sys.platform == "linux" else "bridge",
            self.IMAGE_NAME,
        ]

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.cwd,
        )

        # Drain stderr (log to parent stderr)
        asyncio.create_task(self._drain_stderr())

        # Send start config
        await self._send({
            "type": "start",
            "mode": "claude",
            "apiKey": config.api_key,
            "baseUrl": config.base_url,
            "model": config.model,
            "cwd": "/workspace",  # inside container
            "mcpServers": config.mcp_servers,
            "allowedTools": config.allowed_tools,
            "maxTurns": config.max_turns,
        })

        # Wait for ready (with timeout)
        try:
            ready = await asyncio.wait_for(self._read_line(), timeout=30)
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError("Agent runner start timed out after 30s")
        if not ready or ready.get("type") != "ready":
            raise RuntimeError(f"Agent runner did not start: {ready}")

    async def send(self, text: str) -> None:
        if not self.is_alive():
            raise RuntimeError("Container not running")
        await self._send({"type": "user_input", "text": text})

    async def read_deltas(self) -> AsyncIterator[dict]:
        while True:
            event = await self._read_line()
            if event is None:
                self.eof = True
                return
            yield event
            if event.get("type") in ("model_final", "error"):
                return
        # If we exit the loop with EOF (no model_final), signal to recreate
        if self.eof:
            return

    async def close(self) -> None:
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
        return self._process is not None and self._process.returncode is None

    # ─── Private helpers ──────────────────────────────────────────────

    async def _send(self, obj: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Container not running")
        data = json.dumps(obj, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_line(self) -> dict | None:
        if not self._process or not self._process.stdout:
            return None
        raw = await self._process.stdout.readline()
        if not raw:
            # EOF — container may have crashed or stdout closed
            stderr = await self._process.stderr.read() if self._process.stderr else b""
            sys.stderr.write(f"[docker-agent] EOF on stdout. stderr={stderr[:500]!r}\n")
            sys.stderr.flush()
            return None
        try:
            return json.loads(raw.decode("utf-8").strip())
        except json.JSONDecodeError:
            # Corrupted line — log and skip
            sys.stderr.write(f"[docker-agent] JSON parse error: {raw[:200]!r}\n")
            sys.stderr.flush()
            return None

    async def _drain_stderr(self) -> None:
        try:
            while self._process and self._process.stderr:
                line = await self._process.stderr.readline()
                if not line:
                    break
                sys.stderr.write(f"[docker-agent] {line.decode('utf-8', errors='replace').rstrip()}\n")
                sys.stderr.flush()
        except (asyncio.CancelledError, Exception):
            pass
