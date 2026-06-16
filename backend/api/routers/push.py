"""Push task endpoints.

The frontend PushTask is a flat object; we persist the core scalars in
columns and the type-specific details (webhookUrl, chatId, cron, audit, …)
in a JSON ``config`` blob. The API always answers with the merged flat shape.

GET    /agents/{agent_id}/push-tasks      — list (optional ?type= filter)
POST   /agents/{agent_id}/push-tasks      — create
PUT    /push-tasks/{task_id}             — update
DELETE /push-tasks/{task_id}             — delete
PATCH  /push-tasks/{task_id}/enabled     — toggle enabled
PATCH  /push-tasks/{task_id}/status      — change status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, iso, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import jdump, jload, new_id

router = APIRouter(tags=["push"])


def _push_out(t: M.PushTask) -> dict:
    config = jload(t.config) or {}
    merged = {
        "id": t.id,
        "agentId": t.agent_id,
        "name": t.name,
        "type": t.type,
        "status": t.status,
        "enabled": t.enabled,
        "formStyle": t.form_style,
        "createdAt": iso(t.created_at),
        "updatedAt": iso(t.updated_at),
    }
    merged.update(config)
    return merged


async def _get_task(db: AsyncSession, task_id: str) -> M.PushTask:
    t = (await db.execute(select(M.PushTask).where(M.PushTask.id == task_id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail=f"push task {task_id} not found")
    return t


@router.get("/agents/{agent_id}/push-tasks")
async def list_push_tasks(
    agent_id: str,
    type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    stmt = select(M.PushTask).where(M.PushTask.agent_id == agent_id)
    if type and type != "all":
        stmt = stmt.where(M.PushTask.type == type)
    stmt = stmt.order_by(M.PushTask.updated_at.desc())
    tasks = (await db.execute(stmt)).scalars().all()
    return ok([_push_out(t) for t in tasks])


@router.post("/agents/{agent_id}/push-tasks")
async def create_push_task(
    agent_id: str,
    data: S.PushTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    task = M.PushTask(
        id=new_id(),
        agent_id=agent_id,
        name=data.name,
        type=data.type,
        status=data.status,
        enabled=data.enabled,
        form_style=data.formStyle,
        config=jdump(data.config) if data.config else "{}",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ok(_push_out(task))


@router.put("/push-tasks/{task_id}")
async def update_push_task(
    task_id: str,
    data: S.PushTaskUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    task = await _get_task(db, task_id)
    if data.name is not None:
        task.name = data.name
    if data.type is not None:
        task.type = data.type
    if data.status is not None:
        task.status = data.status
    if data.enabled is not None:
        task.enabled = data.enabled
    if data.formStyle is not None:
        task.form_style = data.formStyle
    if data.config is not None:
        task.config = jdump(data.config)
    await db.commit()
    await db.refresh(task)
    return ok(_push_out(task))


@router.delete("/push-tasks/{task_id}")
async def delete_push_task(task_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    task = await _get_task(db, task_id)
    await db.delete(task)
    await db.commit()
    return ok(message="deleted")


@router.patch("/push-tasks/{task_id}/enabled")
async def toggle_push_enabled(
    task_id: str,
    data: S.ToggleEnabled,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    task = await _get_task(db, task_id)
    task.enabled = data.enabled
    await db.commit()
    return ok({"id": task.id, "enabled": task.enabled})


@router.patch("/push-tasks/{task_id}/status")
async def update_push_status(
    task_id: str,
    data: S.PushStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    task = await _get_task(db, task_id)
    task.status = data.status
    await db.commit()
    return ok({"id": task.id, "status": task.status})
