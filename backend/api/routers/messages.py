"""Chat message endpoints.

GET  /sessions/{session_id}/messages  — list messages in a session
POST /sessions/{session_id}/messages  — persist a user message

NOTE: this only persists conversation history for the management UI. The
actual agent reasoning/reply is produced by the ``reasonix_server`` runtime
(SSE event loop) and is intentionally out of scope here — when it produces a
reply it should POST it back through this endpoint (or write directly).
"""

from __future__ import annotations

import json
import os as _os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, iso, ok
from api.database import async_session, get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["messages"])


def _message_out(m: M.Message) -> dict:
    segments = None
    if m.tool_calls:
        try:
            data = json.loads(m.tool_calls)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # Check if it's a segment list (has 'kind' field) or tool_calls list
                if "kind" in data[0]:
                    segments = data
                else:
                    segments = None  # old format: tool_calls, not segments
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": m.id,
        "sessionId": m.session_id,
        "role": m.role,
        "content": m.content,
        "reasoningContent": m.reasoning_content,
        "segments": segments,
        "durationMs": m.duration_ms,
        "timestamp": iso(m.created_at),
        "artifacts": None,
    }


async def _get_session(db: AsyncSession, session_id: str) -> M.Session:
    s = (await db.execute(select(M.Session).where(M.Session.id == session_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return s


@router.post("/sessions/{session_id}/reset-context")
async def reset_context(session_id: str, user: str = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Clear and re-sync the session workspace (CLAUDE.md + skills)."""
    from agent_runtime.claude.config import _sync_workspace, build_claude_config
    from sqlalchemy import select

    session = await _get_session(db, session_id)
    # Load the agent's current config
    agent_result = await db.execute(select(M.Agent).where(M.Agent.id == session.agent_id))
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    model_config_result = await db.execute(
        select(M.ModelConfig).where(M.ModelConfig.model_id == agent.model, M.ModelConfig.enabled.is_(True))
    )
    model_config = model_config_result.scalar_one_or_none()

    config = await build_claude_config(agent.id, user, session_id, model_config)
    return ok({"cwd": config.cwd, "reset": True})


@router.delete("/sessions/{session_id}/messages")
async def clear_messages(session_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    """Delete all messages in a session."""
    from sqlalchemy import delete as _delete
    session = await _get_session(db, session_id)
    await db.execute(_delete(M.Message).where(M.Message.session_id == session.id))
    await db.commit()
    return ok({"deleted": True})


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    await _get_session(db, session_id)
    msgs = (
        await db.execute(
            select(M.Message)
            .where(M.Message.session_id == session_id)
            .order_by(M.Message.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return ok([_message_out(m) for m in msgs])


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    data: S.MessageSend,
    role: str = Query("user"),
    reasoningContent: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Persist a message.

    Defaults to a ``user`` message; pass ``?role=assistant`` (used by the
    agent runtime when it writes back a reply).
    """
    await _get_session(db, session_id)
    msg = M.Message(
        id=new_id(),
        session_id=session_id,
        role=role,
        content=data.content,
        reasoning_content=reasoningContent,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return ok(_message_out(msg))


# ═══════════════════════════════════════════════════════════════════════
# File download
# ═══════════════════════════════════════════════════════════════════════

from fastapi.responses import FileResponse, JSONResponse

@router.get("/files/{session_id}")
async def list_files(session_id: str, user: str = Depends(current_user)):
    """List generated files in the session workspace (any location, excluding config)."""
    from agent_runtime.claude.config import _WORKSPACE_BASE, scan_generated_files
    from sqlalchemy import select
    from api.models import models as M

    async with async_session() as db:
        session = (await db.execute(select(M.Session).where(M.Session.id == session_id))).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        cwd = _os.path.join(_WORKSPACE_BASE, session.agent_id, user, session_id)
    return scan_generated_files(cwd)


@router.get("/files/{session_id}/download")
async def download_file(session_id: str, path: str = Query(...), user: str = Depends(current_user)):
    """Download a generated file from the session workspace."""
    from agent_runtime.claude.config import _WORKSPACE_BASE, is_safe_workspace_path
    from sqlalchemy import select
    from api.models import models as M

    async with async_session() as db:
        session = (await db.execute(select(M.Session).where(M.Session.id == session_id))).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        cwd = _os.path.join(_WORKSPACE_BASE, session.agent_id, user, session_id)
    fp = is_safe_workspace_path(cwd, path)
    if fp is None:
        raise HTTPException(status_code=403, detail="路径非法")
    if not _os.path.isfile(fp):
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    return FileResponse(fp, filename=_os.path.basename(path))
