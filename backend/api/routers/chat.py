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
                mode=agent.mode,  # "claude" or "normal"
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

    adapter = await create_adapter(mode, agent_id, user, session_id, model_config)

    try:
        while True:
            text = await msg_queue.get()
            if text is _SHUTDOWN:
                break

            turn_id = new_id()

            # ── Signal frontend: turn starting ──
            _try_push(ws_holder, {"type": "turn_start", "text": text, "turnId": turn_id})

            # ── Store reference for abort access ──
            llm_holder[0] = adapter.client

            # ── Process this turn ──
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
        _try_push(ws_holder, {"type": "error", "message": f"Agent 启动失败: {exc}"})
        return False

    # ── Mock tool events for frontend debugging ──
    # TODO: Remove when real tool execution is wired in.
    # Only used in normal mode; Claude Agent mode has real tool calls via SDK.
    if not skip_mock:
        await _emit_mock_tool_events(ws_holder, turn_id)

    # Build segment list as events flow through — matches frontend model
    segments: list[dict] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict] = []
    error_msg: str | None = None

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
                if final_content:
                    _push_seg({"kind": "text", "text": final_content})
                _try_push(ws_holder, {**event, "turnId": turn_id})
                await _persist_message(
                    session_id, "assistant",
                    final_content or "".join(content_parts),
                    final_reasoning or "".join(reasoning_parts),
                    tool_calls=tool_calls if tool_calls else None,
                    segments=segments if segments else None,
                )

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
    if not adapter.is_alive():
        if content_parts or reasoning_parts:
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


async def _persist_message(session_id: str, role: str, content: str, reasoning: str | None = None, tool_calls: list[dict] | None = None, segments: list[dict] | None = None) -> None:
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
