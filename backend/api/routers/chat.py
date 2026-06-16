"""WebSocket chat endpoint — one connection per agent, multiplexed by sessionId.

    ws /api/v1/chat/{agent_id}?user=<x>

One WebSocket per agent (per browser tab).  Sessions are multiplexed over it:
every frame carries a `sessionId`.  The backend routes each session to its own
worker (own adapter + queue), so multiple sessions share one connection.

Client → server JSON frames:
  {"type":"user_input", "sessionId":"...", "text":"..."}
  {"type":"abort", "sessionId":"..."}
  {"type":"pong"}

Server → client JSON frames (turn-related carry sessionId):
  {"type":"ready", "agentName"}
  {"type":"turn_queued", "sessionId", "turnId"}
  {"type":"turn_start", "sessionId", "turnId", "text"}
  {"type":"model_delta", "sessionId", "channel", "text", "turnId"}
  {"type":"tool.*", "sessionId", ...}
  {"type":"model_final", "sessionId", "content", "reasoningContent", "turnId"}
  {"type":"session_renamed", "sessionId", "name"}
  {"type":"error", "sessionId"?, "message"}
  {"type":"stopped", "sessionId"}
  {"type":"ping"}

Architecture:
  - One WS connection per agent.  Per-session workers are spawned lazily on the
    first message to that session (just viewing a session costs nothing).
  - Each worker owns an AgentAdapter (Docker container via the pool) + a queue;
    turns within a session are serialized by a per-session lock.
  - A user-level semaphore caps concurrent turn processing across all sessions.
  - Session count is not explicitly limited — bounded by the container pool
    and the turn semaphore.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.access import can_access_agent
from api.database import async_session
from api.llm_client import LLMClient
from api.models import models as M
from api.util import new_id

if TYPE_CHECKING:
    from agent_runtime.base import AgentAdapter

router = APIRouter(tags=["chat"])

DEFAULT_USER = "current-user"
_PING_INTERVAL = 30
_IDLE_TIMEOUT = 180  # close only if connection idle AND no active workers
_SHUTDOWN = None

# ── User-level concurrency control ─────────────────────────────────
# Caps concurrent turn processing per user across ALL their sessions.
_user_semaphores: dict[str, asyncio.Semaphore] = {}

# Per-session serialization lock (key = session_id). Ensures one turn at a
# time within a session even if multiple workers exist.
_session_locks: dict[str, asyncio.Lock] = {}


def _get_max_turns() -> int:
    """Default max concurrent turns per user, from env or default 3."""
    return int(os.environ.get("AGENT_MAX_CONCURRENT_TURNS", "3"))


def _get_session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


async def _resolve_user_turn_limit(user: str) -> int:
    """A user's turn cap: their configured max_concurrent_turns, else env default."""
    try:
        async with async_session() as db:
            u = (
                await db.execute(select(M.User).where(M.User.name == user))
            ).scalar_one_or_none()
            if u is not None and u.max_concurrent_turns:
                return max(1, int(u.max_concurrent_turns))
    except Exception:
        pass
    return _get_max_turns()


async def _get_user_sem(user: str) -> asyncio.Semaphore:
    """Get or lazily create the per-user turn semaphore.

    The cap is resolved from the user's config (User.max_concurrent_turns) at
    creation time, falling back to the env default.  Call ``invalidate_user_sem``
    after an admin changes a user's limit so the next turn picks it up.
    """
    sem = _user_semaphores.get(user)
    if sem is not None:
        return sem
    limit = await _resolve_user_turn_limit(user)
    sem = asyncio.Semaphore(limit)
    _user_semaphores[user] = sem
    return sem


def invalidate_user_sem(user: str) -> None:
    """Drop a user's cached semaphore so the next creation reads the fresh limit."""
    _user_semaphores.pop(user, None)


# Per-(user, agent) single-WS enforcement. With multiplexing, one WS handles
# all of a user's sessions for an agent — a second tab for the SAME agent kills
# the first. Different agents coexist (different key).
# Key = f"{user}:{agent_id}", Value = WebSocket.
_user_ws: dict[str, WebSocket] = {}


# ═══════════════════════════════════════════════════════════════════════
# WebSocket endpoint
# ═══════════════════════════════════════════════════════════════════════


@router.websocket("/chat/{agent_id}")
async def chat_websocket(ws: WebSocket, agent_id: str) -> None:
    await ws.accept()
    # Token auth (primary): verify signed session token.
    # Fallback: ?user= query param (dev-compat).
    token = ws.query_params.get("token", "")
    if token:
        from api.api_response import verify_session_token, _store_user_token
        verified = verify_session_token(token)
        if verified:
            user = verified
            _store_user_token(user, token)  # cache for MCP env injection
        else:
            try: await ws.send_json({"type":"error","message":"token 无效或已过期"})
            finally: await ws.close()
            return
    else:
        user = ws.query_params.get("user") or DEFAULT_USER
    user_agent_key: str | None = None

    try:
        # ─── validate agent + ownership + model config ───────────────────
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
            model_config = (
                await db.execute(
                    select(M.ModelConfig).where(
                        M.ModelConfig.model_id == agent.model,
                        M.ModelConfig.enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if model_config is None:
                # Fallback: any enabled config (agent.model may be stale)
                model_config = (
                    await db.execute(
                        select(M.ModelConfig).where(M.ModelConfig.enabled.is_(True)).limit(1)
                    )
                ).scalar_one_or_none()
            if model_config is None:
                await _send_error(ws, f"智能体未配置可用模型（model={agent.model}），请先在模型配置中启用")
                return
            agent_name = agent.name
            agent_model = agent.model
            mode = agent.mode

        # ─── enforce single WS per (user, agent) ────────────────────────
        # A second tab for the same agent kills the first. The new WS then
        # receives all pushes for this user+agent.
        user_agent_key = f"{user}:{agent_id}"
        old_ws = _user_ws.get(user_agent_key)
        if old_ws is not None and old_ws is not ws:
            try:
                await old_ws.close(code=4001, reason="replaced by new connection")
            except Exception:
                pass
        _user_ws[user_agent_key] = ws

        await ws.send_json({"type": "ready", "agentName": agent_name})

        # ─── per-session worker registry (within this connection) ────────
        sessions: dict[str, dict] = {}  # session_id → {queue, worker, llm_holder}

        def make_push(session_id: str):
            """Session-scoped sender — stamps sessionId on every frame."""
            def push(frame: dict) -> None:
                _try_send(ws, {**frame, "sessionId": session_id})
            return push

        async def ensure_worker(session_id: str) -> None:
            """Lazily spawn (or re-spawn if dead) a worker for a session."""
            existing = sessions.get(session_id)
            if existing is not None and not existing["worker"].done():
                return  # alive — reuse
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            llm_holder: list[LLMClient | None] = [None]
            push = make_push(session_id)
            worker = asyncio.create_task(
                _session_worker(
                    session_id=session_id,
                    model=agent_model,
                    mode=mode,
                    agent_id=agent_id,
                    user=user,
                    model_config=model_config,
                    push=push,
                    llm_holder=llm_holder,
                    msg_queue=queue,
                )
            )
            sessions[session_id] = {"queue": queue, "worker": worker, "llm_holder": llm_holder}

        # ─── heartbeat ───────────────────────────────────────────────────
        async def _heartbeat():
            try:
                while True:
                    await asyncio.sleep(_PING_INTERVAL)
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        return
            except asyncio.CancelledError:
                return

        heartbeat_task = asyncio.create_task(_heartbeat())

        # ─── dispatch loop ───────────────────────────────────────────────
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(ws.receive_json(), timeout=_IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    # Only close if idle AND no active workers
                    if all(s["worker"].done() for s in sessions.values()):
                        return
                    continue
                except WebSocketDisconnect:
                    return
                except Exception:
                    continue

                msg_type = frame.get("type", "")
                sid = str(frame.get("sessionId") or "")

                if msg_type == "user_input":
                    text = str(frame.get("text") or "").strip()
                    if text and sid:
                        await ensure_worker(sid)
                        await _persist_message(sid, "user", text)
                        new_name = await _maybe_rename_session(sid, text)
                        if new_name:
                            make_push(sid)({"type": "session_renamed", "name": new_name})
                        await sessions[sid]["queue"].put(text)

                elif msg_type == "abort":
                    if sid and sid in sessions:
                        cur = sessions[sid]["llm_holder"][0]
                        if cur:
                            try:
                                await cur.close()
                            except Exception:
                                pass
                        make_push(sid)({"type": "stopped"})

                elif msg_type == "pong":
                    pass

        finally:
            heartbeat_task.cancel()
            # Signal all workers to shut down, then await them
            for s in sessions.values():
                try:
                    await s["queue"].put(_SHUTDOWN)
                except Exception:
                    pass
            for s in sessions.values():
                w = s["worker"]
                if not w.done():
                    w.cancel()
                    try:
                        await w
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
        # Unregister only if we're still the active WS for this user+agent
        # (a newer connection may have already replaced us).
        if user_agent_key and _user_ws.get(user_agent_key) is ws:
            _user_ws.pop(user_agent_key, None)


# ═══════════════════════════════════════════════════════════════════════
# Session Worker — one per session, multiplexed under a connection
# ═══════════════════════════════════════════════════════════════════════


async def _session_worker(
    session_id: str,
    model: str,
    mode: str,
    agent_id: str,
    user: str,
    model_config: M.ModelConfig | None,
    push,
    llm_holder: list[LLMClient | None],
    msg_queue: asyncio.Queue[str | None],
) -> None:
    """Consume a session's message queue one at a time. Each turn acquires
    the session lock (serialize within session) then the user semaphore
    (cap concurrent turns across sessions).

    The adapter (Docker container) is created lazily per turn, INSIDE the
    semaphore slot — so a container only occupies a pool slot when we actually
    have a turn slot.  If adapter creation fails, the message fails (it's
    already persisted in the DB) but the worker stays alive so subsequent
    queued messages still get processed.
    """
    from agent_runtime.registry import create_adapter

    adapter = None
    try:
        while True:
            text = await msg_queue.get()
            if text is _SHUTDOWN:
                break

            turn_id = new_id()
            session_lock = _get_session_lock(session_id)
            sem = await _get_user_sem(user)

            # Tell the frontend this turn is queued if EITHER the session is
            # busy (same-session back-to-back) OR the user concurrency slots
            # are full (cross-session).
            if session_lock.locked() or sem.locked():
                push({
                    "type": "turn_queued",
                    "turnId": turn_id,
                    "message": "当前消息正在排队，请等待...",
                })

            async with session_lock:
                async with sem:
                    # (Re)create the adapter inside the turn slot. If the
                    # previous turn left it dead, or this is the first turn,
                    # build a fresh one.  Failure here drops THIS message
                    # (already in DB) but keeps the worker alive for the next.
                    adapter_ready = True
                    if adapter is None:
                        try:
                            adapter = await create_adapter(mode, agent_id, user, session_id, model_config)
                        except Exception as exc:
                            push({"type": "error", "message": f"Agent 启动失败: {exc}"})
                            adapter_ready = False

                    if adapter_ready and adapter is not None:
                        push({"type": "turn_start", "text": text, "turnId": turn_id})
                        llm_holder[0] = adapter.client
                        client_alive = await _process_turn(
                            session_id, text, model, model_config, push, adapter, turn_id,
                            skip_mock=(mode == "claude"),
                        )
                    else:
                        client_alive = False

            llm_holder[0] = None

            # If the adapter died (turn killed it or subprocess crashed), drop
            # it so the next turn rebuilds a fresh one.
            if adapter is None or not client_alive or not adapter.is_alive():
                if adapter is not None:
                    try:
                        await adapter.close()
                    except Exception:
                        pass
                adapter = None

    except asyncio.CancelledError:
        return
    finally:
        llm_holder[0] = None
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:
                pass


async def _process_turn(
    session_id: str,
    text: str,
    model: str,
    model_config: M.ModelConfig | None,
    push,
    adapter: AgentAdapter | LLMClient | None,
    turn_id: str,
    skip_mock: bool = False,
) -> bool:
    """Process one user message: call LLM, stream, persist reply.

    Returns True if the adapter is still alive (reusable), False if killed.
    `push(frame)` sends a session-scoped frame to the client.
    """

    if adapter is None:
        return False

    try:
        await adapter.send(text)
    except Exception as exc:
        import traceback
        push({"type": "error", "message": f"Agent 启动失败: {exc}\n{traceback.format_exc()}"})
        return False

    if not skip_mock:
        await _emit_mock_tool_events(push, turn_id)

    turn_start_ms = int(time.time() * 1000)
    segments: list[dict] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict] = []
    error_msg: str | None = None
    final_emitted: bool = False

    def _push_seg(seg: dict) -> None:
        segments.append(seg)

    try:
        async for event in adapter.read_deltas():
            event_type = event.get("type")

            if event_type == "model_delta":
                channel = event.get("channel", "content")
                delta_text = event.get("text", "")
                if channel == "content":
                    content_parts.append(delta_text)
                else:
                    reasoning_parts.append(delta_text)
                if channel != "tool_args":
                    source = "content" if channel == "content" else "reasoning"
                    if segments and segments[-1].get("kind") == "reasoning" and segments[-1].get("source") == source:
                        segments[-1]["text"] = segments[-1]["text"] + delta_text
                    else:
                        _push_seg({"kind": "reasoning", "text": delta_text, "source": source})
                push({**event, "turnId": turn_id})

            elif event_type == "model_final":
                final_content = event.get("content", "")
                final_reasoning = event.get("reasoningContent", "")
                assembled = "".join(content_parts)
                if final_content:
                    _push_seg({"kind": "text", "text": final_content})
                elif assembled:
                    _push_seg({"kind": "text", "text": assembled})
                push({**event, "turnId": turn_id})
                duration_ms = int(time.time() * 1000) - turn_start_ms
                await _persist_message(
                    session_id, "assistant",
                    final_content or assembled,
                    final_reasoning or "".join(reasoning_parts),
                    tool_calls=tool_calls if tool_calls else None,
                    segments=segments if segments else None,
                    duration_ms=duration_ms,
                )
                final_emitted = True

            elif event_type == "tool.intent":
                tc = {
                    "callId": event.get("callId", ""),
                    "name": event.get("name", ""),
                    "args": event.get("args", ""),
                    "status": "running",
                }
                tool_calls.append(tc)
                _push_seg({"kind": "tool", "callId": tc["callId"], "name": tc["name"],
                           "args": tc["args"], "done": False})
                push({**event, "turnId": turn_id})

            elif event_type == "tool.result":
                cid = event.get("callId", "")
                ok = event.get("ok", False)
                output = event.get("output", "")
                for tc in tool_calls:
                    if tc.get("callId") == cid:
                        tc["ok"] = ok; tc["output"] = output; tc["status"] = "done"; break
                for seg in segments:
                    if seg.get("kind") == "tool" and seg.get("callId") == cid:
                        seg["ok"] = ok; seg["output"] = output; seg["done"] = True; break
                push({**event, "turnId": turn_id})

            elif event_type == "tool.preparing":
                push({**event, "turnId": turn_id})

            elif event_type == "artifacts":
                push({**event, "turnId": turn_id})

            elif event_type == "error":
                error_msg = event.get("message", "未知错误")
                push({**event, "turnId": turn_id})

    except asyncio.CancelledError:
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        push({"type": "model_final", "content": "", "reasoningContent": ""})
        raise
    except Exception as exc:
        import traceback
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        push({"type": "error", "message": f"处理中断: {exc}"})
        push({"type": "model_final", "content": "", "reasoningContent": ""})
        return False

    if error_msg and not content_parts:
        await _persist_message(session_id, "assistant", f"[错误] {error_msg}")

    if not adapter.is_alive():
        if not final_emitted and (content_parts or reasoning_parts):
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        push({"type": "error", "message": "LLM 子进程异常退出"})
        return False

    push({
        "type": "artifacts",
        "turnId": turn_id,
        "files": await _scan_workspace(adapter, turn_id),
    })

    return True


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


async def _emit_mock_tool_events(push, turn_id: str) -> None:
    """Mock tool events for non-claude mode debugging. TODO: remove."""
    reasoning_text = "让我分析一下用户的需求，需要先搜索相关文件，再查看具体实现，最后验证一下配置..."
    for chunk in _split_chunks(reasoning_text, 8):
        push({"type": "model_delta", "channel": "reasoning", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)
    await _mock_one_tool(push, turn_id, "call_search_1", "search_files",
                         '{"query": "vera-agent", "max_results": 5}', True,
                         "Found 3 files:\n1. backend/api/routers/chat.py\n2. frontend/src/pages/EditAgent/useChatSocket.ts")
    await asyncio.sleep(0.1)


async def _mock_one_tool(push, turn_id, call_id, name, args_text, ok, output):
    push({"type": "tool.preparing", "turnId": turn_id, "callId": call_id, "name": name})
    for chunk in _split_chunks(args_text, 6):
        push({"type": "model_delta", "channel": "tool_args", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.015)
    push({"type": "tool.intent", "turnId": turn_id, "callId": call_id, "name": name, "args": args_text})
    await asyncio.sleep(0.4 + len(output) * 0.001)
    push({"type": "tool.result", "turnId": turn_id, "callId": call_id, "ok": ok, "output": output})


def _split_chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def _try_send(ws: WebSocket, data: dict) -> None:
    """Fire-and-forget send — never blocks the caller."""
    try:
        asyncio.create_task(_safe_send(ws, data))
    except Exception:
        pass


async def _safe_send(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        pass


async def _maybe_rename_session(session_id: str, first_msg: str) -> str | None:
    """Rename a session from its first user message, if still default-named."""
    try:
        async with async_session() as db:
            session = (
                await db.execute(select(M.Session).where(M.Session.id == session_id))
            ).scalar_one_or_none()
            if session is None:
                return None
            if session.name and session.name != "新会话":
                return None
            new_name = first_msg.strip().replace("\n", " ")[:30] or "新会话"
            session.name = new_name
            await db.commit()
            return new_name
    except Exception as exc:
        print(f"[chat] failed to auto-rename session: {exc}", flush=True)
        return None


async def _persist_message(session_id: str, role: str, content: str, reasoning: str | None = None, tool_calls: list[dict] | None = None, segments: list[dict] | None = None, duration_ms: int | None = None) -> None:
    try:
        async with async_session() as db:
            db.add(
                M.Message(
                    id=new_id(),
                    session_id=session_id,
                    role=role,
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=json.dumps(segments, ensure_ascii=False) if segments else (json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None),
                    duration_ms=duration_ms,
                )
            )
            await db.commit()
    except Exception as exc:
        print(f"[chat] failed to persist {role} message: {exc}", flush=True)


async def _scan_workspace(adapter, turn_id: str) -> list[dict]:
    """Scan the workspace root for user-generated files (any location,
    excluding .claude/ and CLAUDE.md)."""
    from agent_runtime.claude.config import scan_generated_files
    client = getattr(adapter, 'client', None)
    cwd = getattr(client, 'cwd', None) if client else None
    if not cwd or not os.path.isdir(cwd):
        return []
    return scan_generated_files(cwd)


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
    finally:
        await ws.close()
