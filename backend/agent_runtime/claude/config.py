"""Build ClaudeAgentConfig from database + sync workspace to disk.

Loads agent configuration (skills, MCP servers, config files, model),
assembles it into a ClaudeAgentConfig, and writes CLAUDE.md + skills
to the per-session workspace directory so Claude SDK can discover them.

Workspace layout:
    {base}/{agent_id}/{user_id}/{session_id}/
    ├── CLAUDE.md
    └── .claude/skills/{skill_name}/SKILL.md
"""

from __future__ import annotations

import json
import os
import sys

from sqlalchemy import select

from api.database import async_session
from api.models import models as M
from api.mcp_jwt import is_mcp_jwt_enabled, mint_mcp_jwt
from agent_runtime.claude.client import ClaudeAgentConfig

_GLOBAL_CONSTRAINTS = """
# 工作区约束（系统级别，对所有 agent 生效）
# - 生成的文件必须写入 output/ 目录，不允许在根目录或其他位置创建非临时文件
# - 仅在自己的工作区内操作，不允许访问或修改其他用户/会话的目录
# - 不允许删除或修改 CLAUDE.md、.claude/ 目录下的内容
"""

_DATA_DIR = os.environ.get("VERA_DATA_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
))
_WORKSPACE_BASE = os.environ.get("AGENT_WORKSPACE_BASE", os.path.join(_DATA_DIR, "workspaces"))


async def build_claude_config(
    agent_id: str,
    user_id: str,
    session_id: str,
    model_config: M.ModelConfig | None,
) -> ClaudeAgentConfig:
    """Load agent config from DB and sync the workspace.

    The workspace is prepared fresh on every session start, so CLAUDE.md
    and skills always reflect the latest DB state.
    """
    config = ClaudeAgentConfig()

    # Per-agent + per-user + per-session workspace
    config.cwd = os.path.join(_WORKSPACE_BASE, agent_id, user_id, session_id)

    if model_config:
        config.api_key = model_config.api_key
        config.base_url = model_config.base_url
        config.model = model_config.model_id

    async with async_session() as db:
        # ── SDK session ID (UUID) for resume across container restarts ──
        session_row = (await db.execute(
            select(M.Session).where(M.Session.id == session_id)
        )).scalar_one_or_none()
        if session_row:
            config.sdk_session_id = session_row.sdk_session_id
        # ── Skills ──
        skills_result = await db.execute(
            select(M.Skill).where(
                M.Skill.agent_id == agent_id,
                M.Skill.enabled.is_(True),
            )
        )
        skills = skills_result.scalars().all()
        config.skills = [
            {
                "name": s.name,
                "description": s.description,
                "body": s.body,
                "allowed_tools": _json_loads_list(s.allowed_tools),
            }
            for s in skills
        ]

        # ── MCP servers ──
        servers_result = await db.execute(
            select(M.McpServer).where(
                M.McpServer.agent_id == agent_id,
                M.McpServer.disabled.is_(False),
            )
        )
        servers = servers_result.scalars().all()
        # Inject the user's session token into every MCP server's env so
        # the MCP tool can call back to Vera with a vera-token header.
        from api.api_response import get_user_token, sign_session_token, _store_user_token
        user_token = get_user_token(user_id)
        if not user_token:
            # Auto-generate a token for users without a login session
            # (e.g., WeChat users who don't go through the web login flow)
            user_token = sign_session_token(user_id)
            _store_user_token(user_id, user_token)

        config.mcp_servers = []
        for srv in servers:
            tools_result = await db.execute(
                select(M.McpTool).where(
                    M.McpTool.mcp_server_id == srv.id,
                    M.McpTool.enabled.is_(True),
                )
            )
            tools = tools_result.scalars().all()
            env = _json_loads_dict(srv.env)
            if user_token:
                env["VERA_TOKEN"] = user_token
            headers = _json_loads_dict(srv.headers)
            # 出站 http/sse MCP 调用注入 RS256 JWT（资源服务器持配对公钥验签）。
            # stdio server 无 HTTP 头概念，仍走上面的 VERA_TOKEN env 回调鉴权。
            transport = (srv.transport or "").lower()
            if transport in ("http", "streamable-http", "sse") and is_mcp_jwt_enabled():
                jwt_token = mint_mcp_jwt(sub=user_id, audience=srv.name)
                if jwt_token:
                    headers["Authorization"] = f"Bearer {jwt_token}"
            config.mcp_servers.append({
                "name": srv.name,
                "command": srv.command,
                "args": _json_loads_list(srv.args),
                "env": env,
                "transport": srv.transport,
                "url": srv.url,
                "headers": headers,
                "tools": [
                    {"name": t.name, "description": t.description}
                    for t in tools
                ],
            })

        # ── Config files ──
        files_result = await db.execute(
            select(M.ConfigFile).where(M.ConfigFile.agent_id == agent_id)
        )
        for f in files_result.scalars().all():
            if f.path.upper() == "CLAUDE.MD":
                config.claude_md = f.content or ""

        # ── Allowed tools (aggregated from skills) ──
        tool_set: set[str] = set()
        for s in skills:
            if s.allowed_tools:
                for t in _json_loads_list(s.allowed_tools):
                    tool_set.add(t)
        if tool_set:
            config.allowed_tools = sorted(tool_set)

    # ── Inject built-in scheduler MCP server (stdio, runs inside container) ──
    # Requires Docker mode — /app/vera_scheduler_mcp.py only exists in the image.
    if os.environ.get("AGENT_USE_DOCKER", "1") == "1":
        host_addr = "host.docker.internal" if sys.platform == "darwin" else "127.0.0.1"
        sched_env = {
            "VERA_AGENT_ID": agent_id,
            "VERA_SESSION_ID": session_id,
            "VERA_BACKEND_URL": f"http://{host_addr}:{os.environ.get('REASONIX_API_PORT', '18080')}/api/v1",
        }
        if user_token:
            sched_env["VERA_TOKEN"] = user_token
        config.mcp_servers.append({
            "name": "vera-scheduler",
            "transport": "stdio",
            "command": "python3",
            "args": ["/app/vera_scheduler_mcp.py"],
            "env": sched_env,
        })

    # ── Sync workspace to disk ──
    _sync_workspace(config.cwd, config.claude_md, config.skills)

    return config


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _sync_workspace(cwd: str, claude_md: str, skills: list[dict]) -> None:
    """Create workspace and write CLAUDE.md + skills to disk.

    Only writes CLAUDE.md if the user has configured content (i.e.
    ``config.claude_md`` is non-empty from the DB).  System-level
    constraints are passed separately to the runner, not in this file.
    """
    import re
    os.makedirs(cwd, exist_ok=True)
    os.makedirs(os.path.join(cwd, "output"), exist_ok=True)
    # Only write if user actually configured a CLAUDE.md
    if claude_md and claude_md.strip():
        _write_file(os.path.join(cwd, "CLAUDE.md"), claude_md)
    for s in skills:
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', s["name"])
        if not safe_name:
            continue
        skill_dir = os.path.join(cwd, ".claude", "skills", safe_name)
        os.makedirs(skill_dir, exist_ok=True)
        _write_file(os.path.join(skill_dir, "SKILL.md"), s.get("body", ""))


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# Files/dirs that are agent config, not user-generated artifacts.
_EXCLUDE_DIRS = {".claude"}
_EXCLUDE_FILES = {"CLAUDE.md"}


def scan_generated_files(cwd: str) -> list[dict]:
    """List user-generated files under the workspace root.

    Scans the whole workspace (not just output/) so files show up regardless
    of where the agent wrote them.  Excludes hidden dirs/files (.claude,
    .claude-persist, .git, ...) and CLAUDE.md (agent config).
    """
    import os
    if not os.path.isdir(cwd):
        return []
    files = []
    for root, dirs, filenames in os.walk(cwd):
        # Prune ALL hidden directories (.claude, .claude-persist, .git, ...)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or name in _EXCLUDE_FILES:
                continue
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
                rel = os.path.relpath(full, cwd)
                files.append({"name": rel, "path": rel, "size": size})
            except OSError:
                pass
    return files


def is_safe_workspace_path(cwd: str, rel_path: str) -> str | None:
    """Resolve a relative path under cwd, blocking traversal and hidden/config
    paths. Returns the absolute path if safe, else None."""
    import os
    safe = os.path.normpath(rel_path).lstrip("/\\")
    parts = safe.split(os.sep)
    # Block any hidden path component (.claude, .claude-persist, ...) and CLAUDE.md
    if any(p.startswith(".") for p in parts) or safe in _EXCLUDE_FILES:
        return None
    fp = os.path.join(cwd, safe)
    if not os.path.realpath(fp).startswith(os.path.realpath(cwd) + os.sep):
        return None
    return fp


def _json_loads_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_loads_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
