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

from sqlalchemy import select

from api.database import async_session
from api.models import models as M
from agent_runtime.claude.client import ClaudeAgentConfig

_GLOBAL_CONSTRAINTS = """
# 工作区约束（系统级别，对所有 agent 生效）
# - 生成的文件必须写入 output/ 目录，不允许在根目录或其他位置创建非临时文件
# - 仅在自己的工作区内操作，不允许访问或修改其他用户/会话的目录
# - 不允许删除或修改 CLAUDE.md、.claude/ 目录下的内容
"""

_WORKSPACE_BASE = os.environ.get("AGENT_WORKSPACE_BASE", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "workspaces",
))


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
        config.mcp_servers = []
        for srv in servers:
            tools_result = await db.execute(
                select(M.McpTool).where(
                    M.McpTool.mcp_server_id == srv.id,
                    M.McpTool.enabled.is_(True),
                )
            )
            tools = tools_result.scalars().all()
            config.mcp_servers.append({
                "name": srv.name,
                "command": srv.command,
                "args": _json_loads_list(srv.args),
                "env": _json_loads_dict(srv.env),
                "transport": srv.transport,
                "url": srv.url,
                "headers": _json_loads_dict(srv.headers),
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

    # ── Sync workspace to disk ──
    _sync_workspace(config.cwd, config.claude_md, config.skills)

    return config


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _sync_workspace(cwd: str, claude_md: str, skills: list[dict]) -> None:
    """Create workspace and write CLAUDE.md + skills to disk.

    Skill names are sanitized to prevent path traversal.
    """
    import re
    os.makedirs(cwd, exist_ok=True)
    os.makedirs(os.path.join(cwd, "output"), exist_ok=True)
    # Append system-level constraints (applies to ALL Claude agents, not per-agent config)
    claude_md = (claude_md or "") + _GLOBAL_CONSTRAINTS
    if claude_md.strip():
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
