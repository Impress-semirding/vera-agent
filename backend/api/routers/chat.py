"""WebSocket chat endpoint.

    ws /api/v1/chat/{agent_id}/{session_id}?user=<x>

Connection handshake (mirrors the desktop agent protocol, simplified):
  1. validate the agent exists **and** belongs to ``user`` (agent.created_by);
  2. resolve the session — reuse it if it exists for this agent, otherwise
     create one and tell the client the new id;
  3. emit ``ready`` and enter the chat loop.

Client → server JSON frames:
  {"type": "user_input", "text": "..."}
  {"type": "abort"}                      (reserved)

Server → client JSON frames:
  {"type": "ready", "sessionId", "agentName"}
  {"type": "session", "sessionId", "created": true}   (when a session was created)
  {"type": "user_message", "text"}                    (echo of the user's text)
  {"type": "model_delta", "channel": "reasoning"|"content", "text"}   (token stream)
  {"type": "model_final", "content", "reasoningContent"}
  {"type": "error", "message"}

The streamed reply is currently **simulated** token-by-token so the full
pipeline (reasoning + content + UI typing) works end to end. Swap
``_stream_reply`` for a real LLM streaming client when available.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.access import can_access_agent
from api.database import async_session
from api.models import models as M
from api.util import new_id

router = APIRouter(tags=["chat"])

DEFAULT_USER = "current-user"
# Per-token delay (seconds) for the simulated stream.
_TOKEN_DELAY = 0.02


@router.websocket("/chat/{agent_id}/{session_id}")
async def chat_websocket(ws: WebSocket, agent_id: str, session_id: str) -> None:
    await ws.accept()
    user = ws.query_params.get("user") or DEFAULT_USER

    # ─── 1. validate agent + ownership ───────────────────────────────────────
    async with async_session() as db:
        agent = (
            await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent is None:
            await _send_error(ws, f"智能体 {agent_id} 不存在")
            return
        if not await can_access_agent(db, agent, user):
            await _send_error(ws, "无权访问该智能体")
            return

        # ─── 2. resolve / create session ─────────────────────────────────────
        session = (
            await db.execute(select(M.Session).where(M.Session.id == session_id))
        ).scalar_one_or_none()
        if session is None:
            session = M.Session(id=new_id(), agent_id=agent_id, name="新会话")
            db.add(session)
            await db.commit()
            await db.refresh(session)
            await ws.send_json({"type": "session", "sessionId": session.id, "created": True})
        elif session.agent_id != agent_id:
            await _send_error(ws, "会话不属于该智能体")
            return

        agent_name = agent.name
        resolved_session_id = session.id

    # ─── 3. ready ────────────────────────────────────────────────────────────
    await ws.send_json({"type": "ready", "sessionId": resolved_session_id, "agentName": agent_name})

    # ─── 4. chat loop ────────────────────────────────────────────────────────
    try:
        while True:
            try:
                frame = await ws.receive_json()
            except WebSocketDisconnect:
                return
            except Exception:  # malformed JSON
                continue
            if frame.get("type") == "user_input":
                text = str(frame.get("text") or "").strip()
                if text:
                    await _handle_user_input(ws, resolved_session_id, text)
    except WebSocketDisconnect:
        return


async def _handle_user_input(ws: WebSocket, session_id: str, text: str) -> None:
    """Persist the user message, stream a simulated reply, persist the reply."""
    await ws.send_json({"type": "user_message", "text": text})
    await _persist_message(session_id, "user", text)

    reasoning = f"正在理解你的问题：「{text[:30]}」。\n分析意图，组织回答。"
    await _stream_tokens(ws, "reasoning", reasoning)

    content = (
        f"已收到你的消息：「{text}」。\n\n"
        "（这是一段模拟的流式回复 —— 思考过程与正文都是逐字推送的。"
        "接入真实大模型后，这里会替换为模型返回的 reasoning_content 与 content。）"
    )
    await _stream_tokens(ws, "content", content)

    await ws.send_json({"type": "model_final", "content": content, "reasoningContent": reasoning})
    await _persist_message(session_id, "assistant", content, reasoning)


async def _stream_tokens(ws: WebSocket, channel: str, text: str) -> None:
    """Emit ``text`` one character at a time on ``channel`` (typing effect)."""
    for ch in text:
        await ws.send_json({"type": "model_delta", "channel": channel, "text": ch})
        await asyncio.sleep(_TOKEN_DELAY)


async def _persist_message(session_id: str, role: str, content: str, reasoning: str | None = None) -> None:
    """Best-effort persistence — a DB hiccup must not crash the live chat."""
    try:
        async with async_session() as db:
            db.add(
                M.Message(
                    id=new_id(),
                    session_id=session_id,
                    role=role,
                    content=content,
                    reasoning_content=reasoning,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — log and keep streaming
        print(f"[chat] failed to persist {role} message: {exc}", flush=True)


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
    finally:
        await ws.close()
