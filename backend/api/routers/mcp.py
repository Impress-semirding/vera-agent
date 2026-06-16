"""MCP server + tool endpoints.

GET    /agents/{agent_id}/mcp-servers          — servers with nested tools
POST   /agents/{agent_id}/mcp-servers          — add a server
PUT    /mcp-servers/{server_id}                — update a server
DELETE /mcp-servers/{server_id}                — delete a server (+ tools)
PATCH  /mcp-servers/{server_id}/disabled       — toggle server disabled
PATCH  /mcp-tools/{tool_id}/enabled            — toggle a tool
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import jdump, jload, new_id

router = APIRouter(tags=["mcp"])


# ─── Mappers ───────────────────────────────────────────────────────────────


def _tool_out(t: M.McpTool) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "parameters": jload(t.parameters),
        "enabled": t.enabled,
    }


def _server_out(s: M.McpServer, tools: list[M.McpTool] | None = None) -> dict:
    return {
        "id": s.id,
        "agentId": s.agent_id,
        "name": s.name,
        "command": s.command,
        "args": jload(s.args),
        "env": jload(s.env),
        "transport": s.transport,
        "url": s.url,
        "headers": jload(s.headers),
        "disabled": s.disabled,
        "tools": [_tool_out(t) for t in (tools or [])],
    }


async def _get_server(db: AsyncSession, server_id: str) -> M.McpServer:
    s = (await db.execute(select(M.McpServer).where(M.McpServer.id == server_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail=f"mcp server {server_id} not found")
    return s


async def _server_with_tools(db: AsyncSession, server_id: str) -> tuple[M.McpServer, list[M.McpTool]]:
    server = await _get_server(db, server_id)
    tools = (
        await db.execute(select(M.McpTool).where(M.McpTool.mcp_server_id == server_id).order_by(M.McpTool.name))
    ).scalars().all()
    return server, list(tools)


# ─── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/agents/{agent_id}/mcp-servers")
async def list_servers(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    servers = (
        await db.execute(
            select(M.McpServer).where(M.McpServer.agent_id == agent_id).order_by(M.McpServer.name)
        )
    ).scalars().all()
    result = []
    for s in servers:
        tools = (
            await db.execute(
                select(M.McpTool).where(M.McpTool.mcp_server_id == s.id).order_by(M.McpTool.name)
            )
        ).scalars().all()
        result.append(_server_out(s, list(tools)))
    return ok(result)


@router.post("/agents/{agent_id}/mcp-servers")
async def create_server(
    agent_id: str,
    data: S.McpServerCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    server = M.McpServer(
        id=new_id(),
        agent_id=agent_id,
        name=data.name,
        command=data.command,
        args=jdump(data.args) if data.args else None,
        env=jdump(data.env) if data.env else None,
        transport=data.transport,
        url=data.url,
        headers=jdump(data.headers) if data.headers else None,
        disabled=data.disabled,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return ok(_server_out(server, []))


@router.put("/mcp-servers/{server_id}")
async def update_server(
    server_id: str,
    data: S.McpServerUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    server, tools = await _server_with_tools(db, server_id)
    if data.name is not None:
        server.name = data.name
    if data.command is not None:
        server.command = data.command
    if data.args is not None:
        server.args = jdump(data.args)
    if data.env is not None:
        server.env = jdump(data.env)
    if data.transport is not None:
        server.transport = data.transport
    if data.url is not None:
        server.url = data.url
    if data.headers is not None:
        server.headers = jdump(data.headers)
    if data.disabled is not None:
        server.disabled = data.disabled
    await db.commit()
    return ok(_server_out(server, tools))


@router.delete("/mcp-servers/{server_id}")
async def delete_server(server_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    server = await _get_server(db, server_id)
    await db.execute(delete(M.McpTool).where(M.McpTool.mcp_server_id == server_id))
    await db.delete(server)
    await db.commit()
    return ok(message="deleted")


@router.patch("/mcp-servers/{server_id}/disabled")
async def toggle_server_disabled(
    server_id: str,
    data: S.ToggleDisabled,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    server = await _get_server(db, server_id)
    server.disabled = data.disabled
    await db.commit()
    return ok({"id": server.id, "disabled": server.disabled})


@router.patch("/mcp-tools/{tool_id}/enabled")
async def toggle_tool_enabled(
    tool_id: str,
    data: S.ToggleEnabled,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    tool = (await db.execute(select(M.McpTool).where(M.McpTool.id == tool_id))).scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"mcp tool {tool_id} not found")
    tool.enabled = data.enabled
    await db.commit()
    return ok({"id": tool.id, "enabled": tool.enabled})
