"""History endpoints.

GET /agents/{agent_id}/exec-records    — execution records (filterable)
GET /agents/{agent_id}/modify-records  — modification records
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import iso, ok
from api.database import get_db
from api.models import models as M

router = APIRouter(tags=["history"])


def _exec_out(r: M.ExecRecord) -> dict:
    return {
        "id": r.id,
        "agentId": r.agent_id,
        "sessionSource": r.session_source,
        "sessionId": r.session_id,
        "userId": r.user_id,
        "status": r.status,
        "content": r.content,
        "timestamp": iso(r.created_at),
    }


def _modify_out(r: M.ModifyRecord) -> dict:
    return {
        "id": r.id,
        "agentId": r.agent_id,
        "operator": r.operator,
        "action": r.action,
        "detail": r.detail,
        "timestamp": iso(r.created_at),
    }


@router.get("/agents/{agent_id}/exec-records")
async def list_exec_records(
    agent_id: str,
    sessionId: str | None = Query(None),
    userId: str | None = Query(None),
    search: str | None = Query(None),
    date: str | None = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(M.ExecRecord).where(M.ExecRecord.agent_id == agent_id)
    if sessionId:
        stmt = stmt.where(M.ExecRecord.session_id.ilike(f"%{sessionId}%"))
    if userId:
        stmt = stmt.where(M.ExecRecord.user_id.ilike(f"%{userId}%"))
    if search:
        stmt = stmt.where(M.ExecRecord.content.ilike(f"%{search}%"))
    if date:
        # SQLite date() truncates the stored datetime to YYYY-MM-DD.
        stmt = stmt.where(func.date(M.ExecRecord.created_at) == date)

    stmt = stmt.order_by(M.ExecRecord.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok([_exec_out(r) for r in rows])


@router.get("/agents/{agent_id}/modify-records")
async def list_modify_records(
    agent_id: str,
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(M.ModifyRecord).where(M.ModifyRecord.agent_id == agent_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(M.ModifyRecord.action.ilike(like), M.ModifyRecord.detail.ilike(like)))
    stmt = stmt.order_by(M.ModifyRecord.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok([_modify_out(r) for r in rows])
