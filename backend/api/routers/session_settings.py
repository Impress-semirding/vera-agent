"""Session-settings endpoints.

GET /agents/{agent_id}/session-settings  — read (auto-created with defaults)
PUT /agents/{agent_id}/session-settings  — partial update (upsert)

Model columns map to the frontend SessionSettings type:
    allow_upload      → allowUpload
    allow_effort      → allowEffortCustomization
    allow_context     → allowManualContextClear
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.access import can_edit_agent
from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["session-settings"])


def _settings_out(s: M.SessionSetting) -> dict:
    return {
        "allowUpload": s.allow_upload,
        "allowEffortCustomization": s.allow_effort,
        "allowManualContextClear": s.allow_context,
    }


async def _get_or_create(db: AsyncSession, agent_id: str) -> M.SessionSetting:
    s = (
        await db.execute(select(M.SessionSetting).where(M.SessionSetting.agent_id == agent_id))
    ).scalar_one_or_none()
    if s is None:
        agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
        s = M.SessionSetting(id=new_id(), agent_id=agent_id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s


@router.get("/agents/{agent_id}/session-settings")
async def get_settings(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    s = await _get_or_create(db, agent_id)
    return ok(_settings_out(s))


@router.put("/agents/{agent_id}/session-settings")
async def update_settings(
    agent_id: str,
    data: S.SessionSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    s = await _get_or_create(db, agent_id)
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    if not await can_edit_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权编辑该智能体")
    if data.allowUpload is not None:
        s.allow_upload = data.allowUpload
    if data.allowEffortCustomization is not None:
        s.allow_effort = data.allowEffortCustomization
    if data.allowManualContextClear is not None:
        s.allow_context = data.allowManualContextClear
    await db.commit()
    await db.refresh(s)
    return ok(_settings_out(s))
