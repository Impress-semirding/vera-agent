"""WeChat iLink integration endpoints.

Provides REST API for the frontend WeChat binding panel:
  - QR code login (fetch + poll status)
  - Disconnect
  - Enable/disable toggle

When WeChat is enabled and credentials are confirmed, a background Monitor
long-polls iLink for messages and dispatches them to the agent runtime.

Does NOT touch the web WebSocket flow (chat.py) — completely independent.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.access import can_access_agent
from api.database import get_db
from api.models import models as M
from api.util import new_id

logger = logging.getLogger("wechat.router")

router = APIRouter(tags=["wechat"])


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


async def _get_ilink(db: AsyncSession, agent_id: str) -> M.WeChatiLink | None:
    """Get the iLink credential row for an agent, or None."""
    return (
        await db.execute(
            select(M.WeChatiLink).where(M.WeChatiLink.agent_id == agent_id)
        )
    ).scalar_one_or_none()


async def _get_or_create_ilink(db: AsyncSession, agent_id: str) -> M.WeChatiLink:
    """Get or create an iLink credential row."""
    ilink = await _get_ilink(db, agent_id)
    if ilink is None:
        ilink = M.WeChatiLink(id=new_id(), agent_id=agent_id, login_status="disconnected")
        db.add(ilink)
        await db.commit()
        await db.refresh(ilink)
    return ilink


def _sync_dir() -> str:
    """Directory for monitor sync buffers."""
    import os
    d = os.path.join(os.path.dirname(__file__), "..", "..", "data", "wechat_sync")
    os.makedirs(d, exist_ok=True)
    return d


# ═══════════════════════════════════════════════════════════════════════
# Session factory for WeChat users
# ═══════════════════════════════════════════════════════════════════════


async def _get_or_create_wechat_session(agent_id: str, user_id: str) -> M.Session:
    """Find or create a session for a WeChat user.

    Each WeChat user (from_user_id) gets a persistent session per agent.
    Session name uses the WeChat user ID for traceability.
    """
    from api.database import async_session

    async with async_session() as db:
        session_name = f"wechat_{user_id}"
        session = (
            await db.execute(
                select(M.Session).where(
                    M.Session.agent_id == agent_id,
                    M.Session.name == session_name,
                )
            )
        ).scalar_one_or_none()

        if session is None:
            session = M.Session(
                id=new_id(),
                agent_id=agent_id,
                name=session_name,
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

        return session


async def _create_wechat_adapter(agent_id: str, user_id: str, session: M.Session):
    """Create an agent adapter for a WeChat user session."""
    from api.database import async_session
    from agent_runtime.registry import create_adapter

    async with async_session() as db:
        agent = (
            await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent is None:
            logger.error(f"[wechat] Agent {agent_id} not found")
            raise HTTPException(status_code=404, detail="Agent not found")

        model_config = (
            await db.execute(
                select(M.ModelConfig).where(
                    M.ModelConfig.model_id == agent.model,
                    M.ModelConfig.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()

        if model_config is None:
            # Try any enabled config as fallback
            model_config = (
                await db.execute(
                    select(M.ModelConfig).where(M.ModelConfig.enabled.is_(True))
                )
            ).scalar_one_or_none()

        if model_config is None:
            logger.error(f"[wechat] No enabled ModelConfig for agent {agent_id} (model={agent.model})")
            raise HTTPException(status_code=500, detail="没有可用的模型配置")

        logger.info(f"[wechat] Creating adapter: agent={agent.id} mode={agent.mode} "
                    f"model={agent.model} user={user_id} session={session.id} "
                    f"provider={model_config.provider}")

    return await create_adapter(
        agent.mode, agent_id, user_id, session.id, model_config,
    )


# ═══════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════


@router.get("/agents/{agent_id}/wechat")
async def get_wechat_status(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Get WeChat connection status for an agent."""
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")

    ilink = await _get_ilink(db, agent_id)

    resp: dict = {
        "enabled": agent.wechat_enabled,
        "loginStatus": ilink.login_status if ilink else "disconnected",
        "ilinkUserId": ilink.ilink_user_id if ilink else None,
        "ilinkBotId": ilink.ilink_bot_id if ilink else None,
    }

    return ok(resp)


@router.post("/agents/{agent_id}/wechat/login")
async def start_wechat_login(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Start QR code login flow. Returns QR code data for display.

    Spawns a background task to poll iLink for scan status, so this
    endpoint returns immediately.  The frontend polls GET .../login/status
    every 2 seconds for updates.
    """
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")

    from agent_runtime.wechat.ilink_client import ILinkClient, ILinkError

    # Stop any existing background poller for this agent
    _cancel_poller(agent_id)

    try:
        qr = await ILinkClient.fetch_qrcode()
    except ILinkError as exc:
        raise HTTPException(status_code=500, detail=f"获取二维码失败: {exc}")

    # Save QR code string to DB for background polling
    ilink = await _get_or_create_ilink(db, agent_id)
    ilink.qrcode = qr.qrcode
    ilink.login_status = "pending"
    await db.commit()
    await db.refresh(ilink)

    # Generate QR code PNG locally from the iLink URL (NOT the raw qrcode
    # string). WeChat only recognizes the full liteapp.weixin.qq.com URL as
    # a login QR; the raw string just shows as plain text when scanned.
    # We still use `qr.qrcode` for polling the status.
    import io
    import base64
    import qrcode as qrcode_lib
    qr_content = qr.qrcode_img_content or f"https://liteapp.weixin.qq.com/q/0?qrcode={qr.qrcode}&bot_type=3"
    img = qrcode_lib.make(qr_content, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qrcode_b64 = base64.b64encode(buf.getvalue()).decode()

    # Start background polling
    _start_poller(agent_id, qr.qrcode)

    return ok({
        "qrcode": qr.qrcode,
        "qrcodeImg": qrcode_b64,
        "loginStatus": "pending",
    })


@router.get("/agents/{agent_id}/wechat/login/status")
async def poll_login_status(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Get current QR code login status (non-blocking — reads from DB)."""
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")

    ilink = await _get_ilink(db, agent_id)
    if ilink is None:
        return ok({"loginStatus": "disconnected"})

    return ok({
        "loginStatus": ilink.login_status,
        "ilinkUserId": ilink.ilink_user_id if ilink.login_status == "confirmed" else None,
    })
# ═══════════════════════════════════════════════════════════════════════

_poller_tasks: dict[str, asyncio.Task] = {}


def _cancel_poller(agent_id: str) -> None:
    """Cancel any running poller for this agent."""
    task = _poller_tasks.pop(agent_id, None)
    if task and not task.done():
        task.cancel()


def _start_poller(agent_id: str, qrcode: str) -> None:
    """Start a background task that polls iLink until scan/expired."""
    _cancel_poller(agent_id)
    task = asyncio.create_task(_poll_ilink_status(agent_id, qrcode))
    _poller_tasks[agent_id] = task


async def _poll_ilink_status(agent_id: str, qrcode: str) -> None:
    """Background: poll iLink QR status and update DB.

    On confirmed → saves credentials and starts monitor.
    On expired → updates DB status.
    """
    from agent_runtime.wechat.ilink_client import ILinkClient, ILinkError, Credentials
    from api.database import async_session

    try:
        creds = await ILinkClient.poll_qrcode_status(qrcode)
    except ILinkError as exc:
        # Expired or cancelled
        async with async_session() as db:
            ilink = await _get_ilink(db, agent_id)
            if ilink:
                ilink.login_status = "expired"
                ilink.qrcode = None
                await db.commit()
        logger.info(f"QR login expired for agent {agent_id}: {exc}")
        return

    # Confirmed — save credentials and start monitor
    async with async_session() as db:
        ilink = await _get_ilink(db, agent_id)
        if ilink is None:
            return
        ilink.bot_token = creds.bot_token
        ilink.ilink_bot_id = creds.ilink_bot_id
        ilink.ilink_user_id = creds.ilink_user_id
        ilink.base_url = creds.base_url
        ilink.login_status = "confirmed"
        ilink.qrcode = None
        await db.commit()

        # Auto-enable WeChat
        agent = (
            await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent:
            agent.wechat_enabled = True
            await db.commit()

    await _start_monitor_for_agent(agent_id, creds)


@router.post("/agents/{agent_id}/wechat/logout")
async def disconnect_wechat(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Disconnect WeChat and stop the monitor."""
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")

    from agent_runtime.wechat.monitor import stop_monitor

    await stop_monitor(agent_id)

    ilink = await _get_ilink(db, agent_id)
    if ilink:
        ilink.bot_token = None
        ilink.ilink_bot_id = None
        ilink.ilink_user_id = None
        ilink.base_url = None
        ilink.qrcode = None
        ilink.login_status = "disconnected"
        await db.commit()

    agent.wechat_enabled = False
    await db.commit()

    return ok({"loginStatus": "disconnected", "enabled": False})


@router.put("/agents/{agent_id}/wechat/toggle")
async def toggle_wechat(
    agent_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Enable or disable WeChat for an agent.

    Body: {"enabled": true|false}
    """
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await can_access_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权访问该智能体")

    enabled = data.get("enabled", False)

    if enabled:
        # Check if we have valid credentials
        ilink = await _get_ilink(db, agent_id)
        if ilink is None or ilink.login_status != "confirmed":
            raise HTTPException(
                status_code=400,
                detail="请先扫码登录微信",
            )

    agent.wechat_enabled = enabled
    await db.commit()

    if enabled:
        # Start monitor
        ilink = await _get_ilink(db, agent_id)
        if ilink:
            from agent_runtime.wechat.ilink_client import Credentials
            creds = Credentials(
                bot_token=ilink.bot_token,
                ilink_bot_id=ilink.ilink_bot_id,
                base_url=ilink.base_url or "https://ilinkai.weixin.qq.com",
                ilink_user_id=ilink.ilink_user_id,
            )
            await _start_monitor_for_agent(agent_id, creds)
    else:
        from agent_runtime.wechat.monitor import stop_monitor
        await stop_monitor(agent_id)

    return ok({"enabled": enabled})


# ═══════════════════════════════════════════════════════════════════════
# Monitor lifecycle
# ═══════════════════════════════════════════════════════════════════════


async def _start_monitor_for_agent(agent_id: str, creds) -> None:
    """Start the WeChat long-poll monitor for an agent."""
    from agent_runtime.wechat.monitor import start_monitor

    async def _get_session(user_id: str):
        return await _get_or_create_wechat_session(agent_id, user_id)

    async def _create_adapter(user_id: str, session):
        return await _create_wechat_adapter(agent_id, user_id, session)

    def _on_expired():
        logger.warning(f"WeChat session expired for agent {agent_id}")

    try:
        logger.info(f"[wechat] Starting monitor for agent={agent_id} bot_id={creds.ilink_bot_id} base_url={creds.base_url}")
        await start_monitor(
            agent_id=agent_id,
            creds=creds,
            get_or_create_session=_get_session,
            create_adapter=_create_adapter,
            sync_dir=_sync_dir(),
            on_session_expired=_on_expired,
        )
        logger.info(f"[wechat] Monitor STARTED for agent {agent_id}")
    except Exception as exc:
        logger.exception(f"[wechat] Failed to start monitor for {agent_id}: {exc}")


async def _restore_all_monitors():
    """On app startup, restore monitors for all agents with confirmed WeChat."""
    from api.database import async_session
    from agent_runtime.wechat.ilink_client import Credentials

    async with async_session() as db:
        result = await db.execute(
            select(M.Agent, M.WeChatiLink)
            .join(M.WeChatiLink, M.WeChatiLink.agent_id == M.Agent.id)
            .where(
                M.Agent.wechat_enabled.is_(True),
                M.WeChatiLink.login_status == "confirmed",
            )
        )

        rows = result.all()
        logger.info(f"[wechat] Restoring {len(rows)} WeChat monitor(s) on startup")
        for agent, ilink in rows:
            logger.info(f"[wechat] Agent {agent.id}: token={'***' if ilink.bot_token else 'MISSING'}"
                        f" bot_id={ilink.ilink_bot_id} user={ilink.ilink_user_id}")
            if ilink.bot_token:
                creds = Credentials(
                    bot_token=ilink.bot_token,
                    ilink_bot_id=ilink.ilink_bot_id,
                    base_url=ilink.base_url or "https://ilinkai.weixin.qq.com",
                    ilink_user_id=ilink.ilink_user_id,
                )
                await _start_monitor_for_agent(agent.id, creds)
            else:
                logger.error(f"[wechat] Agent {agent.id} has confirmed status but NO bot_token — skipping")
