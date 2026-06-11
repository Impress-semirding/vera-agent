"""WebSocket chat endpoint.

    ws /api/v1/chat/{agent_id}/{session_id}?user=<x>

Client → server JSON frames:
  {"type": "user_input", "text": "..."}
  {"type": "abort"}

Server → client JSON frames:
  {"type": "ready", "sessionId", "agentName"}
  {"type": "session", "sessionId", "created": true}
  {"type": "user_message", "text"}
  {"type": "model_delta", "channel": "reasoning"|"content", "text"}
  {"type": "model_final", "content", "reasoningContent"}
  {"type": "error", "message"}

The LLM reply is streamed via a subprocess (agent/chat.py) that calls
the Anthropic-compatible Messages API. Model config (baseUrl + apiKey)
is read from the model_configs table based on the agent's model field.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.access import can_access_agent
from api.database import async_session
from api.llm_client import LLMClient
from api.models import models as M
from api.util import new_id

router = APIRouter(tags=["chat"])

DEFAULT_USER = "current-user"


@router.websocket("/chat/{agent_id}/{session_id}")
async def chat_websocket(ws: WebSocket, agent_id: str, session_id: str) -> None:
    await ws.accept()
    user = ws.query_params.get("user") or DEFAULT_USER
    llm: LLMClient | None = None

    try:
        # ─── 1. validate agent + ownership ───────────────────────────────────
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

            # ─── 2. resolve / create session ─────────────────────────────────
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
            agent_model = agent.model
            resolved_session_id = session.id

            # ─── 2b. resolve model config (baseUrl + apiKey) ─────────────────
            model_config = (
                await db.execute(
                    select(M.ModelConfig).where(
                        M.ModelConfig.model_id == agent_model,
                        M.ModelConfig.enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()

        # ─── 3. ready ────────────────────────────────────────────────────────
        await ws.send_json({
            "type": "ready",
            "sessionId": resolved_session_id,
            "agentName": agent_name,
        })

        # ─── 4. chat loop ────────────────────────────────────────────────────
        while True:
            try:
                frame = await ws.receive_json()
            except WebSocketDisconnect:
                return
            except Exception:
                continue

            if frame.get("type") == "user_input":
                text = str(frame.get("text") or "").strip()
                if not text:
                    continue
                # Start LLM subprocess on first use
                if llm is None and model_config is not None:
                    llm = LLMClient()
                    await llm.start(
                        model=model_config.model_id,
                        base_url=model_config.base_url,
                        api_key=model_config.api_key,
                    )
                # Stream the reply
                llm = await _stream_reply(ws, resolved_session_id, text, agent_model, model_config, llm)

            elif frame.get("type") == "abort":
                if llm:
                    await llm.close()
                    llm = None
    except WebSocketDisconnect:
        return
    finally:
        if llm:
            await llm.close()


async def _stream_reply(
    ws: WebSocket,
    session_id: str,
    text: str,
    model: str,
    model_config: M.ModelConfig | None,
    llm: LLMClient | None,
) -> LLMClient | None:
    """Persist user message, stream LLM reply, persist reply. Returns updated LLMClient."""
    await ws.send_json({"type": "user_message", "text": text})
    await _persist_message(session_id, "user", text)

    if model_config is None:
        await ws.send_json({"type": "error", "message": f"模型 {model} 未配置或未启用，请先在「模型配置」中添加"})
        return None

    if llm is None:
        # This shouldn't happen (created above), but guard anyway
        await ws.send_json({"type": "error", "message": "LLM 客户端未初始化"})
        return None

    try:
        await llm.send(text)
        async for event in llm.read_deltas():
            event_type = event.get("type")
            if event_type == "model_delta":
                await ws.send_json(event)
            elif event_type == "model_final":
                await ws.send_json(event)
                await _persist_message(
                    session_id, "assistant",
                    event.get("content", ""),
                    event.get("reasoningContent", ""),
                )
            elif event_type == "error":
                await ws.send_json(event)
        return llm
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"模型调用失败: {exc}"})
        await llm.close()
        return None


async def _persist_message(session_id: str, role: str, content: str, reasoning: str | None = None) -> None:
    """Best-effort persistence."""
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
    except Exception as exc:
        print(f"[chat] failed to persist {role} message: {exc}", flush=True)


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
    finally:
        await ws.close()
