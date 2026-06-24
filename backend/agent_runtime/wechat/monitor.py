"""WeChat iLink monitor + message handler.

Monitor: long-poll loop that receives messages from WeChat via iLink API.
Handler: processes messages by dispatching to the Vera agent runtime.

Key design:
- One Monitor per agent (when WeChat enabled)
- Each WeChat user gets a persistent session + adapter (lazy created, cached)
- Messages are processed concurrently as asyncio Tasks
- Agent replies are sent back via iLink sendmessage
- Typing indicators shown while agent is working
- Session expired (-14) triggers auto re-login
- Does NOT touch the web WebSocket flow at all
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

from agent_runtime.wechat.ilink_client import (
    ERR_SESSION_EXPIRED,
    MSG_TYPE_BOT,
    ILinkClient,
    Credentials,
    WeixinMessage,
)

logger = logging.getLogger("wechat.monitor")

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

MAX_CONSECUTIVE_FAILURES = 5
MAX_SESSION_EXPIRED = 5  # consecutive session-expired → stop monitor
INITIAL_BACKOFF = 3.0  # seconds
MAX_BACKOFF = 60.0
SESSION_EXPIRED_BACKOFF = 60.0  # 1 min — token expired, no need to hammer the API
ADAPTER_IDLE_TIMEOUT = 600  # 10 min — close adapter after idle
SEEN_MSG_TTL = 300  # 5 min — dedup window
AGENT_PROCESSING_TIMEOUT = 120  # 2 min — max time for agent to respond


# ═══════════════════════════════════════════════════════════════════════
# Handler — processes incoming WeChat messages
# ═══════════════════════════════════════════════════════════════════════


class Handler:
    """Processes WeChat messages by dispatching to the Vera agent runtime.

    Each WeChat user gets their own session + adapter, cached for reuse.
    Replies are sent back via iLink client.
    """

    def __init__(
        self,
        agent_id: str,
        client: ILinkClient,
        get_or_create_session,
        create_adapter,
    ) -> None:
        self._agent_id = agent_id
        self._client = client
        self._get_or_create_session = get_or_create_session  # async (user_id) -> session
        self._create_adapter = create_adapter  # async (user_id, session) -> adapter

        # Per-user state
        self._adapters: dict[str, object] = {}  # user_id -> AgentAdapter
        self._sessions: dict[str, object] = {}  # user_id -> Session
        self._context_tokens: dict[str, str] = {}  # user_id -> context_token
        self._last_active: dict[str, float] = {}  # user_id -> timestamp
        self._locks: dict[str, asyncio.Lock] = {}  # user_id -> per-user lock

        # Dedup
        self._seen_msg_ids: dict[int, float] = {}  # message_id -> timestamp

    # ─── Dedup ─────────────────────────────────────────────────────────

    def _is_duplicate(self, msg_id: int) -> bool:
        """Check if message was already processed (within TTL)."""
        now = time.time()

        # Clean expired entries periodically
        expired = [mid for mid, ts in self._seen_msg_ids.items() if now - ts > SEEN_MSG_TTL]
        for mid in expired:
            del self._seen_msg_ids[mid]

        if msg_id and msg_id in self._seen_msg_ids:
            return True
        if msg_id:
            self._seen_msg_ids[msg_id] = now
        return False

    # ─── User lock ─────────────────────────────────────────────────────

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    # ─── Main dispatch ─────────────────────────────────────────────────

    async def handle(self, msg: WeixinMessage) -> None:
        """Process an incoming WeChat message.

        Awaited directly — the long-poll already runs in its own task.
        """
        user_id = msg.from_user_id
        text = msg.extract_text()
        logger.info(f"[wechat] RECV from={user_id} text={text[:80] if text else '(no text)'}")

        try:
            await self._process(msg)
        except Exception as exc:
            logger.exception(f"[wechat] Unhandled error in handle: {exc}")
            try:
                await self._send_text(user_id, f"内部错误: {exc}")
            except Exception:
                pass

    async def _process(self, msg: WeixinMessage) -> None:
        user_id = msg.from_user_id
        msg_id = msg.message_id

        # Skip bot's own messages (echo). Process everything else.
        if msg.message_type == MSG_TYPE_BOT:
            logger.debug(f"[wechat] SKIP bot echo: id={msg_id}")
            return

        # Dedup
        if self._is_duplicate(msg_id):
            logger.info(f"[wechat] DEDUP message {msg_id} from {user_id}")
            return

        text = msg.extract_text()
        if not text:
            if msg.has_media():
                logger.info(f"[wechat] media message from {user_id}")
                await self._send_text(user_id, "[收到媒体消息，暂不支持处理]")
            return

        logger.info(f"[wechat] PROCESS from={user_id} text={text[:100]} "
                    f"type={msg.message_type} state={msg.message_state}")

        # Serialize per user
        lock = self._get_lock(user_id)
        async with lock:
            try:
                await self._process_locked(user_id, text, msg.context_token)
            except Exception as exc:
                logger.exception(f"[wechat] Error processing from {user_id}: {exc}")
                try:
                    await self._send_text(user_id, f"处理消息时出错: {exc}")
                except Exception:
                    pass

    async def _process_locked(self, user_id: str, text: str, context_token: str) -> None:
        """Process a message with the per-user lock held."""
        if context_token:
            self._context_tokens[user_id] = context_token

        adapter = await self._ensure_adapter(user_id)
        if adapter is None:
            logger.error(f"[wechat] adapter creation FAILED for {user_id}")
            await self._send_text(user_id, "Agent 初始化失败，请稍后重试")
            return

        logger.info(f"[wechat] adapter ready for {user_id}, sending text...")
        self._last_active[user_id] = time.time()

        try:
            await adapter.send(text)
            logger.info(f"[wechat] sent to agent, reading deltas...")

            content_parts: list[str] = []

            async for event in self._read_deltas_with_timeout(adapter, user_id):
                etype = event.get("type", "")

                if etype == "model_delta":
                    txt = event.get("text", "")
                    if event.get("channel") == "content" and txt:
                        content_parts.append(txt)

                elif etype == "model_final":
                    logger.info(f"[wechat] got model_final for {user_id}")
                    break
                elif etype == "error":
                    err_msg = event.get("message", "Unknown error")
                    logger.error(f"[wechat] agent error for {user_id}: {err_msg}")
                    await self._send_text(user_id, f"⚠️ {err_msg}")
                    break

            # Send complete response (iLink doesn't support in-place streaming —
            # sending partials would create duplicate message bubbles)
            full_content = "".join(content_parts)
            if full_content.strip():
                logger.info(f"[wechat] reply to {user_id} len={len(full_content)}")
                max_len = 2000
                for i in range(0, len(full_content), max_len):
                    await self._send_text(user_id, full_content[i:i + max_len])
            else:
                logger.info(f"[wechat] empty reply to {user_id}")
                await self._send_text(user_id, "已处理（无文本回复）")

        except asyncio.TimeoutError:
            logger.error(f"[wechat] agent TIMEOUT for {user_id}")
            await self._send_text(user_id, "处理超时，请稍后重试")
        except Exception as exc:
            logger.exception(f"[wechat] Agent error for {user_id}: {exc}")
            await self._send_text(user_id, f"Agent 执行错误: {exc}")

    async def _read_deltas_with_timeout(self, adapter, user_id: str):
        """Read deltas with a timeout. Creates generator once."""
        gen = adapter.read_deltas()
        while True:
            try:
                event = await asyncio.wait_for(gen.__anext__(), timeout=AGENT_PROCESSING_TIMEOUT)
                yield event
                if event.get("type") in ("model_final", "error"):
                    return
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                logger.error(f"[wechat] read_deltas timeout for {user_id}")
                yield {"type": "error", "message": "处理超时"}
                return

    # ─── Session / adapter management ──────────────────────────────────

    async def _ensure_adapter(self, user_id: str):
        """Get or create an adapter for a WeChat user.

        Adapters are cached and reused across turns for the same user.
        """
        # Return cached if alive
        adapter = self._adapters.get(user_id)
        if adapter is not None and adapter.is_alive():
            return adapter

        # Create new session
        try:
            session = await self._get_or_create_session(user_id)
            adapter = await self._create_adapter(user_id, session)
            self._adapters[user_id] = adapter
            self._sessions[user_id] = session
            return adapter
        except Exception as exc:
            logger.exception(f"Failed to create adapter for {user_id}: {exc}")
            return None

    async def _get_typing_ticket(self, user_id: str) -> str:
        """Fetch typing ticket for a user."""
        ctx_token = self._context_tokens.get(user_id, "")
        try:
            return await self._client.get_typing_ticket(user_id, ctx_token)
        except Exception:
            return ""

    async def _send_text(self, user_id: str, text: str) -> None:
        """Send a text reply to a WeChat user."""
        ctx_token = self._context_tokens.get(user_id, "")
        try:
            await self._client.send_text(user_id, text, ctx_token)
        except Exception as exc:
            logger.error(f"Failed to send to {user_id}: {exc}")

    # ─── Cleanup ───────────────────────────────────────────────────────

    async def cleanup_idle(self) -> None:
        """Close adapters that have been idle too long."""
        now = time.time()
        to_close = []
        for user_id, last in self._last_active.items():
            if now - last > ADAPTER_IDLE_TIMEOUT:
                to_close.append(user_id)

        for user_id in to_close:
            adapter = self._adapters.pop(user_id, None)
            if adapter:
                try:
                    await adapter.close()
                except Exception:
                    pass
            self._sessions.pop(user_id, None)
            self._last_active.pop(user_id, None)
            self._context_tokens.pop(user_id, None)
            logger.info(f"Cleaned up idle adapter for {user_id}")

    async def close_all(self) -> None:
        """Close all adapters (called on shutdown)."""
        for user_id, adapter in list(self._adapters.items()):
            try:
                await adapter.close()
            except Exception:
                pass
        self._adapters.clear()
        self._sessions.clear()
        self._last_active.clear()
        self._context_tokens.clear()


# ═══════════════════════════════════════════════════════════════════════
# Monitor — long-poll loop
# ═══════════════════════════════════════════════════════════════════════


class Monitor:
    """Long-poll monitor that receives WeChat messages and dispatches to handler.

    One Monitor per agent. Runs as a background asyncio Task.
    Auto-recovers from transient errors with exponential backoff.
    Detects session expiry and notifies caller to re-login.
    """

    def __init__(
        self,
        agent_id: str,
        creds: Credentials,
        handler: Handler,
        sync_dir: str,
        on_session_expired: Callable[[], None] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._client = ILinkClient(creds)
        self._handler = handler
        self._sync_dir = Path(sync_dir)
        self._sync_dir.mkdir(parents=True, exist_ok=True)
        self._sync_file = self._sync_dir / f"{agent_id}_sync.json"
        self._on_session_expired = on_session_expired

        self._buf: str = ""
        self._failures: int = 0
        self._session_expired_count: int = 0
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._idle_cleanup_task: asyncio.Task | None = None

    # ─── Lifecycle ─────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the long-poll loop and idle cleanup."""
        if self._running:
            return
        self._running = True
        self._load_buf()

        def _on_done(task: asyncio.Task) -> None:
            try:
                exc = task.exception()
                if exc and not isinstance(exc, asyncio.CancelledError):
                    logger.exception(f"[monitor:{self._agent_id}] background task crashed: {exc}")
            except asyncio.CancelledError:
                pass

        self._task = asyncio.create_task(self._run())
        self._task.add_done_callback(_on_done)
        self._idle_cleanup_task = asyncio.create_task(self._idle_cleanup_loop())
        self._idle_cleanup_task.add_done_callback(_on_done)
        logger.info(f"[monitor:{self._agent_id}] started")

    async def stop(self) -> None:
        """Stop the monitor gracefully."""
        self._running = False
        for task in (self._task, self._idle_cleanup_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self._handler.close_all()
        await self._client.close()
        logger.info(f"[monitor:{self._agent_id}] stopped")

    # ─── Main loop ─────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Long-poll loop with exponential backoff."""
        logger.info(f"[monitor:{self._agent_id}] long-poll loop started, base_url={self._client.base_url}")
        poll_count = 0
        while self._running:
            try:
                poll_count += 1
                if poll_count <= 3 or poll_count % 10 == 0:
                    logger.info(f"[monitor:{self._agent_id}] polling #{poll_count} buf_len={len(self._buf)}")
                resp = await self._client.get_updates(self._buf)
            except Exception as exc:
                if not self._running:
                    return
                self._failures += 1
                backoff = self._calc_backoff()
                logger.warning(
                    f"[monitor:{self._agent_id}] getupdates error "
                    f"({self._failures}/{MAX_CONSECUTIVE_FAILURES}, backoff={backoff}s): {exc}"
                )
                if self._failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        f"[monitor:{self._agent_id}] {MAX_CONSECUTIVE_FAILURES} "
                        f"consecutive failures. Session may need re-login."
                    )
                    if self._on_session_expired:
                        self._on_session_expired()
                await asyncio.sleep(backoff)
                continue

            # Reset failure counters on any successful response
            self._failures = 0
            self._session_expired_count = 0

            # Log message count
            if resp.msgs:
                logger.info(f"[monitor:{self._agent_id}] received {len(resp.msgs)} message(s)")

            # Session expired
            if resp.err_code == ERR_SESSION_EXPIRED:
                if self._buf:
                    logger.info(f"[monitor:{self._agent_id}] session expired, resetting sync buf")
                    self._buf = ""
                    self._save_buf()
                else:
                    self._session_expired_count += 1
                    logger.warning(
                        f"[monitor:{self._agent_id}] token expired "
                        f"({self._session_expired_count}/{MAX_SESSION_EXPIRED}), needs re-login"
                    )
                    if self._on_session_expired:
                        self._on_session_expired()
                    if self._session_expired_count >= MAX_SESSION_EXPIRED:
                        logger.error(
                            f"[monitor:{self._agent_id}] session expired "
                            f"{MAX_SESSION_EXPIRED} consecutive times, stopping monitor"
                        )
                        self._running = False
                        break
                await asyncio.sleep(SESSION_EXPIRED_BACKOFF)
                continue

            # Other server-side errors
            if resp.ret != 0 and resp.err_code != 0:
                logger.warning(
                    f"[monitor:{self._agent_id}] server error: "
                    f"ret={resp.ret} errcode={resp.err_code} errmsg={resp.err_msg}"
                )
                continue

            # Update sync buffer
            if resp.get_updates_buf:
                self._buf = resp.get_updates_buf
                self._save_buf()

            # Dispatch messages
            for msg in resp.msgs:
                await self._handler.handle(msg)

    # ─── Idle cleanup ──────────────────────────────────────────────────

    async def _idle_cleanup_loop(self) -> None:
        """Periodically clean up idle adapters."""
        while self._running:
            await asyncio.sleep(ADAPTER_IDLE_TIMEOUT)
            if self._running:
                await self._handler.cleanup_idle()

    # ─── Backoff ───────────────────────────────────────────────────────

    def _calc_backoff(self) -> float:
        d = INITIAL_BACKOFF
        for _ in range(1, self._failures):
            d *= 2
        return min(d, MAX_BACKOFF)

    # ─── Persist sync buffer ───────────────────────────────────────────

    def _load_buf(self) -> None:
        try:
            if self._sync_file.exists():
                data = json.loads(self._sync_file.read_text())
                self._buf = data.get("get_updates_buf", "")
                if self._buf:
                    logger.info(f"[monitor:{self._agent_id}] loaded sync buf")
        except Exception:
            pass

    def _save_buf(self) -> None:
        try:
            self._sync_file.write_text(json.dumps({"get_updates_buf": self._buf}))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Global monitor registry — manages monitors across agents
# ═══════════════════════════════════════════════════════════════════════

_monitors: dict[str, Monitor] = {}  # agent_id -> Monitor


def get_monitor(agent_id: str) -> Monitor | None:
    return _monitors.get(agent_id)


async def start_monitor(
    agent_id: str,
    creds: Credentials,
    get_or_create_session,
    create_adapter,
    sync_dir: str,
    on_session_expired: Callable[[], None] | None = None,
) -> Monitor:
    """Start a monitor for an agent. Stops existing one if running."""
    await stop_monitor(agent_id)

    client = ILinkClient(creds)
    handler = Handler(agent_id, client, get_or_create_session, create_adapter)
    monitor = Monitor(agent_id, creds, handler, sync_dir, on_session_expired)
    await monitor.start()
    _monitors[agent_id] = monitor
    return monitor


async def stop_monitor(agent_id: str) -> None:
    """Stop and remove a monitor."""
    monitor = _monitors.pop(agent_id, None)
    if monitor:
        await monitor.stop()


async def stop_all_monitors() -> None:
    """Stop all monitors (called on app shutdown)."""
    for agent_id in list(_monitors.keys()):
        await stop_monitor(agent_id)
