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


def _get_image_name() -> str:
    """Docker image name from env, defaults to vera-agent-runner:latest."""
    return os.environ.get("AGENT_DOCKER_IMAGE", "vera-agent-runner:latest")


class DockerAgentClient:
    """Spawns a Docker container and communicates via stdin/stdout JSON lines.

    Same public interface as LLMClient / ClaudeAgentClient.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._container_id: str | None = None
        self.eof: bool = False
        self.cwd: str = "/tmp"
        self._session_id: str = ""  # set by pool on reuse

    # ─── Build image ──────────────────────────────────────────────────

    @classmethod
    async def ensure_image(cls) -> None:
        """Verify Docker is accessible and the image exists.  Fail fast if not.

        The image must be pre-built once with ``docker build``. We never build
        at runtime — that keeps startup predictable and avoids multi-minute
        delays on first request.
        """
        docker_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docker"
        )
        # 1. Check Docker daemon is reachable
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(
                "Docker daemon is not accessible. Make sure Docker Desktop "
                "is running and the socket is available."
            )

        # 2. Check image exists
        proc = await asyncio.create_subprocess_exec(
            "docker", "images", "-q", _get_image_name(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if stdout.decode().strip():
            print(f"[docker] Image {_get_image_name()} found", flush=True)
            return

        raise RuntimeError(
            f"Docker image '{_get_image_name()}' not found.\n"
            f"Build it once with:\n"
            f"  docker build -t {_get_image_name()} {docker_dir}"
        )

    # ─── Public API ───────────────────────────────────────────────────

    async def start(self, config: ClaudeAgentConfig) -> None:
        """Start Docker container."""
        await self.ensure_image()
        self.cwd = config.cwd

        # Ensure workspace dirs exist — chmod 777 so the container's non-root
        # `agent` user can write (host creates these as root, container runs as agent)
        os.makedirs(config.cwd, exist_ok=True)
        os.makedirs(os.path.join(config.cwd, "output"), exist_ok=True)
        os.makedirs(os.path.join(config.cwd, ".claude-persist"), exist_ok=True)
        # CLI stores conversation history here (NOT in ~/.claude/)
        os.makedirs(os.path.join(config.cwd, ".claude-cache"), exist_ok=True)
        os.makedirs(os.path.join(config.cwd, ".claude-sessions"), exist_ok=True)
        os.chmod(config.cwd, 0o777)
        os.chmod(os.path.join(config.cwd, "output"), 0o777)
        os.chmod(os.path.join(config.cwd, ".claude-persist"), 0o777)
        os.chmod(os.path.join(config.cwd, ".claude-cache"), 0o777)
        os.chmod(os.path.join(config.cwd, ".claude-sessions"), 0o777)

        cmd = [
            "docker", "run", "-i", "--rm",
            "--name", f"vera-agent-{os.path.basename(config.cwd)}-{os.urandom(4).hex()}",
            # Mount workspace (read-write)
            "-v", f"{os.path.abspath(config.cwd)}:/workspace",
            # Mount Claude skills/permissions config
            "-v", f"{os.path.abspath(os.path.join(config.cwd, '.claude-persist'))}:/home/agent/.claude",
            # Mount Claude CLI conversation history (where sessions are actually stored)
            "-v", f"{os.path.abspath(os.path.join(config.cwd, '.claude-cache'))}:/home/agent/.cache/claude-cli-nodejs",
            # Mount SDK session storage (persists across container restarts for resume)
            "-v", f"{os.path.abspath(os.path.join(config.cwd, '.claude-sessions'))}:/home/agent/.claude-sessions",
            # Pass env vars
            "-e", f"ANTHROPIC_API_KEY={config.api_key}",
            "-e", f"ANTHROPIC_BASE_URL={config.base_url}",
            "-e", "CLAUDE_CODE_DISABLE_NON_ESSENTIAL_TTY=1",
            "-e", "CLAUDE_CODE_HEADLESS=1",
            "-e", "CLAUDE_CONFIG_DIR=/home/agent/.claude-sessions",
            # Network
            "--network", "host" if sys.platform == "linux" else "bridge",
            _get_image_name(),
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
            "sdkSessionId": config.sdk_session_id,
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
