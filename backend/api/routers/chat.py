"""WebSocket chat endpoint.

    ws /api/v1/chat/{agent_id}/{session_id}?user=<x>

Client → server JSON frames:
  {"type": "user_input", "text": "..."}
  {"type": "pong"}                      (heartbeat response)
  {"type": "abort"}                     (stop current turn, keep queue)

Server → client JSON frames:
  {"type": "ready", "sessionId", "agentName"}
  {"type": "session", "sessionId", "created": true}
  {"type": "turn_start", "text", "turnId"} (worker begins processing a message)
  {"type": "user_message", "text"}
  {"type": "model_delta", "channel", "text", "turnId"}
  {"type": "model_final", "content", "reasoningContent", "turnId"}
  {"type": "error", "message"}
  {"type": "stopped"}                   (abort acknowledged, queue may have more)
  {"type": "ping"}                      (heartbeat probe)

Architecture:
  - A per-session asyncio.Queue collects user messages.
  - A single worker task consumes the queue sequentially — one LLM call at a time.
  - The LLM subprocess (agent/chat.py) is reused across turns; it maintains
    conversation history internally.
  - abort only stops the current LLM call; queued messages are preserved and
    processed after the current turn is cancelled.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.access import can_access_agent
from api.database import async_session
from api.llm_client import LLMClient
from api.models import models as M
from api.util import new_id

router = APIRouter(tags=["chat"])

DEFAULT_USER = "current-user"
_PING_INTERVAL = 30
_IDLE_TIMEOUT = 60
_SHUTDOWN = None


@router.websocket("/chat/{agent_id}/{session_id}")
async def chat_websocket(ws: WebSocket, agent_id: str, session_id: str) -> None:
    await ws.accept()
    user = ws.query_params.get("user") or DEFAULT_USER

    ws_holder: list[WebSocket | None] = [ws]
    llm_holder: list[LLMClient | None] = [None]

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

            # ─── 2b. resolve model config ────────────────────────────────────
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

        # ─── 4. message queue + worker ──────────────────────────────────────
        msg_queue: asyncio.Queue[str | None] = asyncio.Queue()
        worker_task = asyncio.create_task(
            _session_worker(
                session_id=resolved_session_id,
                model=agent_model,
                model_config=model_config,
                ws_holder=ws_holder,
                llm_holder=llm_holder,
                msg_queue=msg_queue,
            )
        )

        # ─── 5. heartbeat ──────────────────────────────────────────────────
        async def _heartbeat():
            try:
                while True:
                    await asyncio.sleep(_PING_INTERVAL)
                    current = ws_holder[0]
                    if current is None:
                        return
                    try:
                        await current.send_json({"type": "ping"})
                    except Exception:
                        return
            except asyncio.CancelledError:
                return

        heartbeat_task = asyncio.create_task(_heartbeat())

        # ─── 6. chat loop — message dispatcher ──────────────────────────────
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(ws.receive_json(), timeout=_IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    return
                except WebSocketDisconnect:
                    return
                except Exception:
                    continue

                msg_type = frame.get("type", "")

                if msg_type == "user_input":
                    text = str(frame.get("text") or "").strip()
                    if text:
                        # Persist immediately so messages survive crashes.
                        await _persist_message(resolved_session_id, "user", text)
                        await msg_queue.put(text)

                elif msg_type == "abort":
                    current_llm = llm_holder[0]
                    if current_llm:
                        try:
                            await current_llm.close()
                        except Exception:
                            pass
                    _try_push(ws_holder, {"type": "stopped"})

                elif msg_type == "pong":
                    pass

        finally:
            heartbeat_task.cancel()
            await msg_queue.put(_SHUTDOWN)
            if not worker_task.done():
                worker_task.cancel()
                try:
                    await worker_task
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await _send_error(ws, f"连接异常: {exc}")
        except Exception:
            pass
    finally:
        ws_holder[0] = None


# ═══════════════════════════════════════════════════════════════════════
# Session Worker
# ═══════════════════════════════════════════════════════════════════════


async def _session_worker(
    session_id: str,
    model: str,
    model_config: M.ModelConfig | None,
    ws_holder: list[WebSocket | None],
    llm_holder: list[LLMClient | None],
    msg_queue: asyncio.Queue[str | None],
) -> None:
    """Consume messages one at a time. Reuses LLM subprocess across turns.

    The LLM subprocess is kept alive between turns so agent/chat.py maintains
    conversation history. It is only recreated if abort closed it.
    """
    llm: LLMClient | None = None

    try:
        while True:
            text = await msg_queue.get()
            if text is _SHUTDOWN:
                break

            turn_id = new_id()

            # ── Signal frontend: turn starting ──
            _try_push(ws_holder, {"type": "turn_start", "text": text, "turnId": turn_id})

            # ── Ensure LLM subprocess is running ──
            if llm is None and model_config is not None:
                try:
                    llm = LLMClient()
                    await llm.start(
                        model=model_config.model_id,
                        base_url=model_config.base_url,
                        api_key=model_config.api_key,
                    )
                except Exception as exc:
                    _try_push(ws_holder, {"type": "error", "message": f"LLM 启动失败: {exc}", "turnId": turn_id})
                    continue

            # ── Store reference for abort access ──
            llm_holder[0] = llm

            # ── Process this turn ──
            llm_alive = await _process_turn(session_id, text, model, model_config, ws_holder, llm, turn_id)

            # ── Clean up reference ──
            llm_holder[0] = None

            if not llm_alive or not llm.is_alive():
                # Subprocess was killed (abort or error) or died — discard and recreate next turn
                if llm:
                    try:
                        await llm.close()
                    except Exception:
                        pass
                llm = None
    except asyncio.CancelledError:
        return
    finally:
        llm_holder[0] = None
        if llm:
            try:
                await llm.close()
            except Exception:
                pass


async def _process_turn(
    session_id: str,
    text: str,
    model: str,
    model_config: M.ModelConfig | None,
    ws_holder: list[WebSocket | None],
    llm: LLMClient | None,
    turn_id: str,
) -> bool:
    """Process one user message: call LLM, stream, persist reply.

    User message is already persisted when received (not here).
    Returns True if the LLM subprocess is still alive (can be reused),
    False if it was killed (abort or fatal error).
    """

    if model_config is None:
        _try_push(ws_holder, {"type": "error", "message": f"模型 {model} 未配置或未启用"})
        return True

    if llm is None:
        return False

    # Send to LLM subprocess
    try:
        await llm.send(text)
    except Exception:
        # Subprocess was closed (abort). User message is already in DB —
        # that's fine, it shows what the user asked even without a response.
        _try_push(ws_holder, {"type": "error", "message": "处理中断"})
        return False

    # Read streaming response
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    error_msg: str | None = None

    try:
        async for event in llm.read_deltas():
            event_type = event.get("type")

            if event_type == "model_delta":
                channel = event.get("channel", "content")
                delta_text = event.get("text", "")
                if channel == "content":
                    content_parts.append(delta_text)
                else:
                    reasoning_parts.append(delta_text)
                _try_push(ws_holder, {**event, "turnId": turn_id})

            elif event_type == "model_final":
                _try_push(ws_holder, {**event, "turnId": turn_id})
                await _persist_message(
                    session_id, "assistant",
                    event.get("content", ""),
                    event.get("reasoningContent", ""),
                )

            elif event_type == "error":
                error_msg = event.get("message", "未知错误")
                _try_push(ws_holder, {**event, "turnId": turn_id})

    except Exception:
        # Subprocess was killed (abort or unexpected error) — persist partial response
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        # Notify frontend so streaming state doesn't get stuck
        _try_push(ws_holder, {"type": "error", "message": "处理中断"})
        return False

    if error_msg and not content_parts:
        await _persist_message(session_id, "assistant", f"[错误] {error_msg}")

    # If read_deltas() hit EOF, the subprocess is dead — don't reuse it.
    if llm.eof:
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        _try_push(ws_holder, {"type": "error", "message": "LLM 子进程异常退出"})
        return False

    # LLM subprocess completed normally — still alive for reuse
    return True


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _try_push(ws_holder: list[WebSocket | None], data: dict) -> None:
    ws = ws_holder[0]
    if ws is None:
        return
    try:
        asyncio.create_task(_safe_send(ws, data))
    except Exception:
        pass


async def _safe_send(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        pass


async def _persist_message(session_id: str, role: str, content: str, reasoning: str | None = None) -> None:
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
