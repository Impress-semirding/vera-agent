"""Scheduled task REST endpoints — agent-level CRUD.

GET    /agents/{agent_id}/schedules          — list all tasks for an agent
POST   /agents/{agent_id}/schedules          — create a task (source=system)
PUT    /agents/{agent_id}/schedules/{task_id} — update a task
DELETE /agents/{agent_id}/schedules/{task_id} — delete a task
POST   /agents/{agent_id}/schedules/{task_id}/toggle — enable/disable
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.access import can_access_agent
from api.database import get_db
from api.models import models as M
from api.scheduler.cron_util import next_run, validate_cron

router = APIRouter(tags=["schedules"])


class ScheduleCreate(BaseModel):
    name: str
    prompt: str
    cron: str
    timeout: int = 1200  # 20 min
    session_id: str | None = None
    enabled: bool = True
    task_type: str = "agent"  # agent | script+agent
    script_content: str | None = None
    script_name: str | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cron: str | None = None
    timeout: int | None = None
    session_id: str | None = None
    enabled: bool | None = None
    task_type: str | None = None
    script_content: str | None = None
    script_name: str | None = None


def _task_out(t: M.ScheduledTask) -> dict:
    from datetime import timedelta, timezone
    from api.api_response import iso

    # next_run_at / last_run_at are stored as Beijing time (CST, UTC+8).
    # Attach tzinfo so iso() won't append "Z" but "+08:00", making the
    # frontend display the correct Beijing time.
    _cst = timezone(timedelta(hours=8))
    def _cst_iso(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_cst)
        return iso(dt)

    return {
        "id": t.id,
        "agentId": t.agent_id,
        "userId": t.user_id,
        "sessionId": t.session_id,
        "name": t.name,
        "prompt": t.prompt,
        "scriptContent": t.script_content,
        "scriptName": t.script_name,
        "cron": t.cron,
        "timeout": t.timeout,
        "source": t.source,
        "taskType": t.task_type,
        "enabled": t.enabled,
        "status": t.status,
        "failCount": t.fail_count,
        "nextRunAt": _cst_iso(t.next_run_at),
        "lastRunAt": _cst_iso(t.last_run_at),
        "lastStatus": t.last_status,
        "lastResult": t.last_result,
        "createdAt": iso(t.created_at),
        "updatedAt": iso(t.updated_at),
    }


async def _get_agent_or_403(db: AsyncSession, agent_id: str, user: str):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")
    return agent


async def _validate_session(db: AsyncSession, session_id: str | None, agent_id: str) -> None:
    """Raise 400 if session_id is set but doesn't exist or belongs to another agent."""
    if not session_id:
        return
    session = (await db.execute(
        select(M.Session).where(M.Session.id == session_id)
    )).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=400, detail=f"会话 {session_id} 不存在")
    if session.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="会话不属于该智能体")


@router.get("/agents/{agent_id}/schedules")
async def list_schedules(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_agent_or_403(db, agent_id, user)
    rows = (await db.execute(
        select(M.ScheduledTask).where(M.ScheduledTask.agent_id == agent_id).order_by(M.ScheduledTask.created_at.desc())
    )).scalars().all()
    return ok([_task_out(t) for t in rows])


@router.post("/agents/{agent_id}/schedules")
async def create_schedule(
    agent_id: str,
    data: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_agent_or_403(db, agent_id, user)
    await _validate_session(db, data.session_id, agent_id)
    if not validate_cron(data.cron):
        raise HTTPException(status_code=400, detail=f"无效的 cron 表达式: {data.cron}")
    from api.util import new_id
    nxt = next_run(data.cron)
    task = M.ScheduledTask(
        id=new_id(),
        agent_id=agent_id,
        user_id=user,
        session_id=data.session_id,
        name=data.name,
        prompt=data.prompt,
        script_content=data.script_content,
        script_name=data.script_name,
        cron=data.cron,
        timeout=data.timeout,
        source="system",
        task_type=data.task_type,
        enabled=data.enabled,
        status="active" if data.enabled else "paused",
        next_run_at=nxt,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task))


@router.post("/agents/{agent_id}/schedules/chat")
async def create_schedule_from_chat(
    agent_id: str,
    data: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Create a schedule from within a chat session (source=chat).

    No can_access_agent check — the MCP server runs inside the agent's own
    container, so the caller already has implicit access (verified by token).
    WeChat users and other non-creator users can register schedules this way.
    """
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not validate_cron(data.cron):
        raise HTTPException(status_code=400, detail=f"无效的 cron 表达式: {data.cron}")
    from api.util import new_id
    nxt = next_run(data.cron)
    task = M.ScheduledTask(
        id=new_id(),
        agent_id=agent_id,
        user_id=user,
        session_id=data.session_id,
        name=data.name,
        prompt=data.prompt,
        script_content=data.script_content,
        script_name=data.script_name,
        cron=data.cron,
        timeout=data.timeout,
        source="chat",
        task_type=data.task_type,
        enabled=True,
        status="active",
        next_run_at=nxt,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task))


@router.put("/agents/{agent_id}/schedules/{task_id}")
async def update_schedule(
    agent_id: str,
    task_id: str,
    data: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_agent_or_403(db, agent_id, user)
    task = (await db.execute(
        select(M.ScheduledTask).where(M.ScheduledTask.id == task_id, M.ScheduledTask.agent_id == agent_id)
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if data.name is not None:
        task.name = data.name
    if data.prompt is not None:
        task.prompt = data.prompt
    if data.cron is not None:
        if not validate_cron(data.cron):
            raise HTTPException(status_code=400, detail=f"无效的 cron 表达式: {data.cron}")
        task.cron = data.cron
        task.next_run_at = next_run(data.cron)
        task.fail_count = 0
        task.status = "active"
    if data.timeout is not None:
        task.timeout = data.timeout
    if data.session_id is not None:
        task.session_id = data.session_id
    if data.enabled is not None:
        task.enabled = data.enabled
        task.status = "active" if data.enabled else "paused"
        if data.enabled:
            task.next_run_at = next_run(task.cron)
    if data.task_type is not None:
        task.task_type = data.task_type
    if data.script_content is not None:
        task.script_content = data.script_content
    if data.script_name is not None:
        task.script_name = data.script_name

    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task))


@router.delete("/agents/{agent_id}/schedules/{task_id}")
async def delete_schedule(
    agent_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_agent_or_403(db, agent_id, user)
    task = (await db.execute(
        select(M.ScheduledTask).where(M.ScheduledTask.id == task_id, M.ScheduledTask.agent_id == agent_id)
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    await db.delete(task)
    await db.commit()
    return ok(message="deleted")


@router.post("/agents/{agent_id}/schedules/{task_id}/toggle")
async def toggle_schedule(
    agent_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_agent_or_403(db, agent_id, user)
    task = (await db.execute(
        select(M.ScheduledTask).where(M.ScheduledTask.id == task_id, M.ScheduledTask.agent_id == agent_id)
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    task.enabled = not task.enabled
    task.status = "active" if task.enabled else "paused"
    if task.enabled:
        task.next_run_at = next_run(task.cron)
        task.fail_count = 0
    await db.commit()
    await db.refresh(task)
    return ok(_task_out(task))
