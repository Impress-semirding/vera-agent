"""Agent CRUD endpoints.

GET    /agents                         — filtered + paginated list
GET    /agents/{agent_id}              — single agent
POST   /agents                         — create
PUT    /agents/{agent_id}              — partial update
DELETE /agents/{agent_id}              — delete (+ cascade related rows)
POST   /agents/{agent_id}/star         — toggle starred
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, iso, ok
from api.access import can_access_agent
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["agents"])


# ─── Mapper ────────────────────────────────────────────────────────────────


def _agent_out(a: M.Agent) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "type": a.type,
        "mode": a.mode,
        "model": a.model,
        "avatarUrl": a.avatar_url,
        "visibility": a.visibility,
        "starred": a.starred,
        "createdBy": a.created_by,
        "updatedBy": a.updated_by,
        "updatedAt": iso(a.updated_at),
        "createdAt": iso(a.created_at),
    }


async def _get_agent(db: AsyncSession, agent_id: str) -> M.Agent:
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    return agent


# ─── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/agents")
async def list_agents(
    type: str = Query("all"),
    mode: str | None = Query(None),
    search: str | None = Query(None),
    mine: bool | None = Query(None),
    starred: bool | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    stmt = select(M.Agent)
    # Baseline access: only agents the current user may see (owner / permitted).
    permitted = select(M.Permission.agent_id).where(
        M.Permission.user_name == user,
        M.Permission.agent_permissions.like('%"view"%'),
    )
    stmt = stmt.where(
        or_(
            M.Agent.created_by == user,
            M.Agent.id.in_(permitted),
        )
    )
    if type and type != "all":
        stmt = stmt.where(M.Agent.type == type)
    if mode:
        stmt = stmt.where(M.Agent.mode == mode)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(M.Agent.name.ilike(like), M.Agent.description.ilike(like)))
    if mine:
        stmt = stmt.where(M.Agent.created_by == user)
    if starred:
        stmt = stmt.where(M.Agent.starred.is_(True))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = stmt.order_by(M.Agent.starred.desc(), M.Agent.updated_at.desc())
    stmt = stmt.offset((page - 1) * pageSize).limit(pageSize)
    items = (await db.execute(stmt)).scalars().all()

    return ok({"items": [_agent_out(a) for a in items], "total": total, "page": page, "pageSize": pageSize})


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = await _get_agent(db, agent_id)
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")
    return ok(_agent_out(agent))


@router.post("/agents")
async def create_agent(
    data: S.AgentFormData,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = M.Agent(
        id=new_id(),
        name=data.name,
        description=data.description,
        type=data.type,
        mode=data.mode,
        model=data.model,
        avatar_url=data.avatarUrl,
        visibility=data.visibility,
        starred=False,
        created_by=user,
        updated_by=user,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return ok(_agent_out(agent))


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    data: S.AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = await _get_agent(db, agent_id)
    field_map = {
        "name": "name",
        "description": "description",
        "model": "model",
        "type": "type",
        "mode": "mode",
        "avatarUrl": "avatar_url",
        "visibility": "visibility",
    }
    for fe, col in field_map.items():
        value = getattr(data, fe)
        if value is not None:
            setattr(agent, col, value)
    agent.updated_by = user
    await db.commit()
    await db.refresh(agent)
    return ok(_agent_out(agent))


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await _get_agent(db, agent_id)

    # Cascade-delete everything that belongs to this agent so nothing orphans.
    session_ids = select(M.Session.id).where(M.Session.agent_id == agent_id)
    mcp_ids = select(M.McpServer.id).where(M.McpServer.agent_id == agent_id)
    wecom_ids = select(M.WeComConfig.id).where(M.WeComConfig.agent_id == agent_id)

    await db.execute(delete(M.Message).where(M.Message.session_id.in_(session_ids)))
    await db.execute(delete(M.McpTool).where(M.McpTool.mcp_server_id.in_(mcp_ids)))
    await db.execute(delete(M.WeComBinding).where(M.WeComBinding.wecom_config_id.in_(wecom_ids)))

    children = [
        M.Session, M.Project, M.McpServer, M.Skill, M.Permission,
        M.PushTask, M.WeComConfig, M.SessionSetting, M.ConfigFile,
        M.ExecRecord, M.ModifyRecord,
    ]
    for child in children:
        if hasattr(child, "agent_id"):
            await db.execute(delete(child).where(child.agent_id == agent_id))

    await db.delete(agent)
    await db.commit()
    return ok(message="deleted")


@router.post("/agents/{agent_id}/star")
async def toggle_star(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await _get_agent(db, agent_id)
    agent.starred = not agent.starred
    await db.commit()
    await db.refresh(agent)
    return ok({"id": agent.id, "starred": agent.starred})
