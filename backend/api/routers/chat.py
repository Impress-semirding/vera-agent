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
import json
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
_IDLE_TIMEOUT = 180  # 3 minutes — close only if BOTH client and agent are silent
_SHUTDOWN = None

# Track active WS per session — strict single-connection enforcement.
# Value is (websocket, ws_holder) tuple.
# When a connection is replaced, the old connection's release_event
# (stored in a closure/local) signals when its resources are freed.
_session_ws: dict[str, tuple[WebSocket, list[WebSocket | None]]] = {}

# ── User-level concurrency control ─────────────────────────────────
# Per-user semaphore caps concurrent turn processing across all sessions.
# Key = user name, Value = asyncio.Semaphore
_user_semaphores: dict[str, asyncio.Semaphore] = {}

# Map session_key → user name (for cleanup on disconnect).
_session_user: dict[str, str] = {}

# Per-session mutex — defence-in-depth against concurrent turn processing
# within the same session (in case single-connection enforcement has a
# race window).  Key = session_key.
_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(session_key: str) -> asyncio.Lock:
    """Get or create the per-session mutex."""
    lock = _session_locks.get(session_key)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_key] = lock
    return lock


def _get_max_turns() -> int:
    """Max concurrent turns per user, from env or default 3."""
    import os
    return int(os.environ.get("AGENT_MAX_CONCURRENT_TURNS", "3"))


def _get_max_sessions() -> int:
    """Max active WS sessions per user, from env or default 5."""
    import os
    return int(os.environ.get("AGENT_MAX_SESSIONS", "5"))


def _get_user_sem(user: str) -> asyncio.Semaphore:
    """Get or lazily create the per-user turn semaphore."""
    sem = _user_semaphores.get(user)
    if sem is None:
        sem = asyncio.Semaphore(_get_max_turns())
        _user_semaphores[user] = sem
    return sem


@router.websocket("/chat/{agent_id}/{session_id}")
async def chat_websocket(ws: WebSocket, agent_id: str, session_id: str) -> None:
    await ws.accept()
    user = ws.query_params.get("user") or DEFAULT_USER

    # Kick old connection for the same session (only one active WS per session)
    ws_holder: list[WebSocket | None] = [ws]
    llm_holder: list[LLMClient | None] = [None]
    session_key: str | None = None

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

        # ─── 3. ready — single-connection per session (backend enforced) ──────
        session_key = f"{agent_id}/{resolved_session_id}"
        existing = _session_ws.get(session_key)
        if existing is not None:
            existing_ws, existing_holder = existing
            # Create a release event that the OLD connection's finally block
            # will signal when its resources (adapter, container) are freed.
            old_released: asyncio.Event = asyncio.Event()
            # Stash it on the old holder so the old finally can find it.
            # We use a sentinel key in the holder list: holder[1] = release_event
            existing_holder.append(old_released)  # type: ignore[arg-type]

            # Kill the old connection
            existing_holder[0] = None
            try:
                await existing_ws.close(code=4001, reason="replaced by new connection")
            except Exception:
                pass

            # Wait for old worker to finish cleanup (adapter closed, container gone)
            try:
                await asyncio.wait_for(old_released.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

            _session_ws.pop(session_key, None)

        _session_ws[session_key] = (ws, ws_holder)

        # ── Check per-user session limit ───────────────────────────────
        max_sessions = _get_max_sessions()
        _session_user[session_key] = user
        current_sessions = sum(1 for sk, u in _session_user.items()
                               if u == user and sk.startswith(f"{agent_id}/"))
        if current_sessions > max_sessions:
            # Don't force-close — send a friendly prompt and let the user
            # decide.  Poll until a slot frees or the user disconnects.
            await ws.send_json({
                "type": "session_limit",
                "message": f"已达上限 ({max_sessions}个会话)，请关闭其他标签页后等待自动重连",
                "maxSessions": max_sessions,
                "currentSessions": current_sessions,
            })
            # Remove from tracking so we don't count this waiting WS as active
            _session_ws.pop(session_key, None)
            _session_user.pop(session_key, None)
            # Wait loop: poll every 5s until a slot frees or user leaves
            try:
                while True:
                    await asyncio.sleep(5)
                    count = sum(1 for sk, u in _session_user.items()
                               if u == user and sk.startswith(f"{agent_id}/"))
                    if count < max_sessions:
                        # Slot freed — but check if another WS for the same
                        # session already connected while we were waiting
                        if _session_ws.get(session_key) is not None:
                            # Another connection took this session — we're
                            # no longer needed
                            await ws.send_json({
                                "type": "session_limit",
                                "message": "该会话已被其他连接接管，请关闭此标签页",
                            })
                            return
                        _session_ws[session_key] = (ws, ws_holder)
                        _session_user[session_key] = user
                        await ws.send_json({
                            "type": "session_resume",
                            "message": "会话槽位已释放，正在连接...",
                        })
                        break
                    # Keep-alive ping so the frontend knows we're still waiting
                    try:
                        await ws.send_json({"type": "session_waiting", "message": f"等待中 ({count}/{max_sessions})..."})
                    except Exception:
                        return  # user disconnected
            except Exception:
                return  # user disconnected or error

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
                mode=agent.mode,
                agent_id=agent_id,
                user=user,
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
                    # Only close if agent is idle — don't kill during long turns
                    if worker_task.done():
                        return
                    continue  # agent busy, reset timer
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
        if session_key:
            entry = _session_ws.get(session_key)
            if entry is not None:
                registered_ws, _ = entry
                if registered_ws is ws:
                    _session_ws.pop(session_key, None)
                    _session_user.pop(session_key, None)
        # Signal "my resources are released" — if we were replaced, the
        # new connection is waiting on this event.  The event is stashed
        # at ws_holder[1] by the replacing connection.
        release_event = ws_holder[1] if len(ws_holder) > 1 else None
        if release_event is not None:
            release_event.set()


# ═══════════════════════════════════════════════════════════════════════
# Session Worker
# ═══════════════════════════════════════════════════════════════════════


async def _session_worker(
    session_id: str,
    model: str,
    mode: str,
    agent_id: str,
    user: str,
    model_config: M.ModelConfig | None,
    ws_holder: list[WebSocket | None],
    llm_holder: list[LLMClient | None],
    msg_queue: asyncio.Queue[str | None],
) -> None:
    """Consume messages one at a time. Uses AgentAdapter to route to the
    correct backend (Claude Agent SDK for mode=claude, raw HTTP otherwise).
    """
    from agent_runtime.registry import create_adapter

    try:
        adapter = await create_adapter(mode, agent_id, user, session_id, model_config)
    except Exception as exc:
        _try_push(ws_holder, {"type": "error", "message": f"Agent 启动失败: {exc}"})
        return

    try:
        while True:
            text = await msg_queue.get()
            if text is _SHUTDOWN:
                break

            turn_id = new_id()
            session_key = f"{agent_id}/{session_id}"

            # ── Session-level mutex: only ONE turn processes at a time ──
            # for this session, even if single-connection enforcement has a
            # race window.  Held for the entire turn (queue wait + LLM call).
            session_lock = _get_session_lock(session_key)

            # ── Acquire user concurrency slot ────────────────────────────
            sem = _get_user_sem(user)
            if sem.locked():
                _try_push(ws_holder, {
                    "type": "turn_queued",
                    "text": text,
                    "turnId": turn_id,
                    "message": "当前消息正在排队，请等待...",
                })

            async with session_lock:
                async with sem:
                    _try_push(ws_holder, {"type": "turn_start", "text": text, "turnId": turn_id})
                    llm_holder[0] = adapter.client

                    client_alive = await _process_turn(
                        session_id, text, model, model_config, ws_holder, adapter, turn_id,
                        skip_mock=(mode == "claude"),
                    )

            # ── Clean up reference ──
            llm_holder[0] = None

            # ── Check if client died ──
            if not client_alive or not adapter.is_alive():
                await adapter.close()
                # Re-create adapter (fresh client on next turn)
                adapter = await create_adapter(mode, agent_id, user, session_id, model_config)

    except asyncio.CancelledError:
        return
    finally:
        llm_holder[0] = None
        await adapter.close()


async def _process_turn(
    session_id: str,
    text: str,
    model: str,
    model_config: M.ModelConfig | None,
    ws_holder: list[WebSocket | None],
    adapter: AgentAdapter | LLMClient | None,
    turn_id: str,
    skip_mock: bool = False,
) -> bool:
    """Process one user message: call LLM, stream, persist reply.

    User message is already persisted when received (not here).
    Returns True if the LLM subprocess is still alive (can be reused),
    False if it was killed (abort or fatal error).

    When skip_mock is True, the mock tool events are skipped (used for
    Claude Agent mode where the SDK handles tool calls natively).
    """

    if adapter is None:
        return False

    # Send user text to the backend (triggers lazy client init on first call)
    try:
        await adapter.send(text)
    except Exception as exc:
        import traceback
        _try_push(ws_holder, {"type": "error", "message": f"Agent 启动失败: {exc}\n{traceback.format_exc()}"})
        return False

    # ── Mock tool events for frontend debugging ──
    # TODO: Remove when real tool execution is wired in.
    # Only used in normal mode; Claude Agent mode has real tool calls via SDK.
    if not skip_mock:
        await _emit_mock_tool_events(ws_holder, turn_id)

    # Build segment list as events flow through — matches frontend model
    turn_start_ms = int(time.time() * 1000)
    segments: list[dict] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict] = []
    error_msg: str | None = None
    final_emitted: bool = False  # guard against double-persist if subprocess dies right after model_final

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
                # Track in segments
                if channel != "tool_args":
                    source = "content" if channel == "content" else "reasoning"
                    # Append to last reasoning segment if compatible, else create new
                    if segments and segments[-1].get("kind") == "reasoning" and segments[-1].get("source") == source:
                        segments[-1]["text"] = segments[-1]["text"] + delta_text
                    else:
                        _push_seg({"kind": "reasoning", "text": delta_text, "source": source})
                _try_push(ws_holder, {**event, "turnId": turn_id})

            elif event_type == "model_final":
                final_content = event.get("content", "")
                final_reasoning = event.get("reasoningContent", "")
                assembled = "".join(content_parts)
                if final_content:
                    _push_seg({"kind": "text", "text": final_content})
                elif assembled:
                    _push_seg({"kind": "text", "text": assembled})
                _try_push(ws_holder, {**event, "turnId": turn_id})
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
                _try_push(ws_holder, {**event, "turnId": turn_id})

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
                _try_push(ws_holder, {**event, "turnId": turn_id})

            elif event_type == "tool.preparing":
                _try_push(ws_holder, {**event, "turnId": turn_id})

            elif event_type == "artifacts":
                _try_push(ws_holder, {**event, "turnId": turn_id})

            elif event_type == "error":
                error_msg = event.get("message", "未知错误")
                _try_push(ws_holder, {**event, "turnId": turn_id})

    except asyncio.CancelledError:
        # Worker cancelled (WS disconnect, server shutdown) — persist partial
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        _try_push(ws_holder, {"type": "model_final", "content": "", "reasoningContent": ""})
        raise  # re-raise to let worker handle cancellation properly
    except Exception as exc:
        import traceback
        # Subprocess was killed (abort or unexpected error) — persist partial response
        if content_parts or reasoning_parts:
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        # Notify frontend so streaming state doesn't get stuck
        _try_push(ws_holder, {"type": "error", "message": f"处理中断: {exc}"})
        _try_push(ws_holder, {"type": "model_final", "content": "", "reasoningContent": ""})
        return False

    if error_msg and not content_parts:
        await _persist_message(session_id, "assistant", f"[错误] {error_msg}")

    # If read_deltas() hit EOF, the subprocess is dead — don't reuse it.
    # Skip persist if we already emitted model_final (avoids double-persist).
    if not adapter.is_alive():
        if not final_emitted and (content_parts or reasoning_parts):
            await _persist_message(
                session_id, "assistant",
                "".join(content_parts),
                "".join(reasoning_parts),
            )
        _try_push(ws_holder, {"type": "error", "message": "LLM 子进程异常退出"})
        return False

    # ── Scan workspace for files generated this turn ──
    _try_push(ws_holder, {
        "type": "artifacts",
        "turnId": turn_id,
        "files": await _scan_workspace(adapter, turn_id),
    })

    # LLM subprocess completed normally — still alive for reuse
    return True


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


async def _emit_mock_tool_events(
    ws_holder: list[WebSocket | None],
    turn_id: str,
) -> None:
    """Send mock tool events to the frontend for segment rendering development.

    Simulates a realistic agent turn:
      reasoning → tool1 → tool2 → tool3 → then LLM produces final text.
    Then the real LLM streaming continues after this function returns.

    TODO: Remove when real tool execution is wired in.
    """
    import asyncio

    # 1. Reasoning — initial thinking
    reasoning_text = "让我分析一下用户的需求，需要先搜索相关文件，再查看具体实现，最后验证一下配置..."
    for chunk in _split_chunks(reasoning_text, 8):
        _try_push(ws_holder, {"type": "model_delta", "channel": "reasoning", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)

    # ── Tool 1: search_files ──
    await _mock_one_tool(ws_holder, turn_id, "call_search_1", "search_files",
                         '{"query": "vera-agent", "max_results": 5}',
                         True,
                         "Found 3 files:\n1. backend/api/routers/chat.py\n2. frontend/src/pages/EditAgent/useChatSocket.ts\n3. backend/agent/chat.py")
    await asyncio.sleep(0.1)

    # More reasoning between tools
    more_reasoning = "找到了几个关键文件，让我看看 chat.py 的具体实现..."
    for chunk in _split_chunks(more_reasoning, 8):
        _try_push(ws_holder, {"type": "model_delta", "channel": "reasoning", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)

    # ── Tool 2: read_file ──
    await _mock_one_tool(ws_holder, turn_id, "call_read_1", "read_file",
                         '{"path": "backend/api/routers/chat.py"}',
                         True,
                         "# chat.py — WebSocket endpoint\n\nasync def chat_websocket(ws, agent_id, session_id):\n    await ws.accept()\n    # ... 120 lines omitted")
    await asyncio.sleep(0.1)

    # More reasoning
    more_reasoning2 = "已经了解了代码结构，再检查一下模型配置..."
    for chunk in _split_chunks(more_reasoning2, 8):
        _try_push(ws_holder, {"type": "model_delta", "channel": "reasoning", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)

    # ── Tool 3: check_config (simulated failure) ──
    await _mock_one_tool(ws_holder, turn_id, "call_config_1", "check_model_config",
                         '{"model_id": "deepseek-v4-pro"}',
                         False,
                         "Error: Model 'deepseek-v4-pro' is not enabled.\nPlease check ModelConfig table.")
    await asyncio.sleep(0.1)


async def _mock_one_tool(
    ws_holder: list[WebSocket | None],
    turn_id: str,
    call_id: str,
    name: str,
    args_text: str,
    ok: bool,
    output: str,
) -> None:
    """Emit a single tool call lifecycle: preparing → args streaming → intent → result."""
    import asyncio

    # preparing
    _try_push(ws_holder, {
        "type": "tool.preparing", "turnId": turn_id,
        "callId": call_id, "name": name,
    })

    # Stream args
    for chunk in _split_chunks(args_text, 6):
        _try_push(ws_holder, {"type": "model_delta", "channel": "tool_args", "text": chunk, "turnId": turn_id})
        await asyncio.sleep(0.015)

    # intent
    _try_push(ws_holder, {
        "type": "tool.intent", "turnId": turn_id,
        "callId": call_id, "name": name, "args": args_text,
    })

    # Execution delay
    await asyncio.sleep(0.4 + len(output) * 0.001)

    # result
    _try_push(ws_holder, {
        "type": "tool.result", "turnId": turn_id,
        "callId": call_id, "ok": ok, "output": output,
    })


def _split_chunks(text: str, size: int) -> list[str]:
    """Split text into chunks of given size."""
    return [text[i:i + size] for i in range(0, len(text), size)]


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
    """Scan only the output/ subdirectory for user-visible generated files.

    Config files (.claude/, CLAUDE.md) are ignored because they live above output/.
    """
    import os as _os
    client = getattr(adapter, 'client', None)
    cwd = getattr(client, 'cwd', None) if client else None
    if not cwd or not _os.path.isdir(cwd):
        return []
    output_dir = _os.path.join(cwd, "output")
    if not _os.path.isdir(output_dir):
        _os.makedirs(output_dir, exist_ok=True)
        return []
    files = []
    for root, dirs, filenames in _os.walk(output_dir):
        for name in filenames:
            if name.startswith('.'):
                continue
            full = _os.path.join(root, name)
            try:
                size = _os.path.getsize(full)
                rel = _os.path.relpath(full, output_dir)
                files.append({"name": rel, "path": rel, "size": size})
            except OSError:
                pass
    return files


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
    finally:
        await ws.close()
