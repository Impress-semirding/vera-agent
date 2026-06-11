"""Chat message endpoints.

GET  /sessions/{session_id}/messages  — list messages in a session
POST /sessions/{session_id}/messages  — persist a user message

NOTE: this only persists conversation history for the management UI. The
actual agent reasoning/reply is produced by the ``reasonix_server`` runtime
(SSE event loop) and is intentionally out of scope here — when it produces a
reply it should POST it back through this endpoint (or write directly).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import iso, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["messages"])


def _message_out(m: M.Message) -> dict:
    return {
        "id": m.id,
        "sessionId": m.session_id,
        "role": m.role,
        "content": m.content,
        "reasoningContent": m.reasoning_content,
        "timestamp": iso(m.created_at),
        "artifacts": None,
    }


async def _get_session(db: AsyncSession, session_id: str) -> M.Session:
    s = (await db.execute(select(M.Session).where(M.Session.id == session_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return s


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
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
