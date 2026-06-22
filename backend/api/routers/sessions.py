"""Session endpoints.

GET   /agents/{agent_id}/sessions   — list sessions for an agent
POST  /agents/{agent_id}/sessions   — create a session
PATCH /sessions/{session_id}        — rename a session
DELETE /sessions/{session_id}       — delete a session (+ its messages)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, iso, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id
import uuid as _uuid

router = APIRouter(tags=["sessions"])


def _session_out(s: M.Session, last_at=None) -> dict:
    return {
        "id": s.id,
        "agentId": s.agent_id,
        "name": s.name,
        "projectId": s.project_id,
        "createdAt": iso(s.created_at),
        "lastMessageAt": iso(last_at) if last_at else None,
        "createdBy": s.created_by,
    }


async def _get_session(db: AsyncSession, session_id: str) -> M.Session:
    s = (await db.execute(select(M.Session).where(M.Session.id == session_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return s


@router.get("/agents/{agent_id}/sessions")
async def list_sessions(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    # Join with last message timestamp for sorting.  Sessions with no messages
    # fall back to created_at, so newly-created sessions still appear at top.
    rows = (
        await db.execute(
            select(
                M.Session,
                func.coalesce(func.max(M.Message.created_at), M.Session.created_at).label("last_activity"),
            )
            .outerjoin(M.Message, M.Message.session_id == M.Session.id)
            .where(M.Session.agent_id == agent_id, M.Session.created_by == user)
            .group_by(M.Session.id)
            .order_by(func.coalesce(func.max(M.Message.created_at), M.Session.created_at).desc())
        )
    ).all()

    sessions = []
    last_map: dict[str, object] = {}
    for s, last_activity in rows:
        sessions.append(s)
        last_map[s.id] = last_activity if last_activity != s.created_at else None

    return ok([_session_out(s, last_map.get(s.id)) for s in sessions])


@router.post("/agents/{agent_id}/sessions")
async def create_session(
    agent_id: str,
    data: S.SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    # Ensure the agent exists.
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    session = M.Session(
        id=new_id(),
        agent_id=agent_id,
        name=data.name or "新会话",
        project_id=data.projectId,
        sdk_session_id=str(_uuid.uuid4()),
        created_by=user,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ok(_session_out(session))


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    data: S.SessionUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    session = await _get_session(db, session_id)
    if session.created_by != user:
        raise HTTPException(status_code=403, detail="无权修改他人会话")
    if data.name is not None:
        session.name = data.name
    await db.commit()
    await db.refresh(session)
    return ok(_session_out(session))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    session = await _get_session(db, session_id)
    if session.created_by != user:
        raise HTTPException(status_code=403, detail="无权删除他人会话")
    await db.execute(delete(M.Message).where(M.Message.session_id == session_id))
    await db.delete(session)
    await db.commit()
    return ok(message="deleted")
