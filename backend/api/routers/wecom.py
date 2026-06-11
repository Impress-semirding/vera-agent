"""WeCom (企业微信) connection endpoints.

GET    /agents/{agent_id}/wecom                — config + bindings (auto-created)
PUT    /agents/{agent_id}/wecom                — save bot credentials
PATCH  /agents/{agent_id}/wecom/enabled        — toggle enabled
POST   /agents/{agent_id}/wecom/bindings       — add a bound chat
DELETE /wecom/bindings/{binding_id}            — remove a bound chat
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["wecom"])


def _binding_out(b: M.WeComBinding) -> dict:
    return {"id": b.id, "chatId": b.chat_id, "description": b.description}


def _wecom_out(cfg: M.WeComConfig, bindings: list[M.WeComBinding]) -> dict:
    return {
        "agentId": cfg.agent_id,
        "enabled": cfg.enabled,
        "botId": cfg.bot_id,
        "botKey": cfg.bot_key,
        "showThinking": cfg.show_thinking,
        "bindings": [_binding_out(b) for b in bindings],
    }


async def _get_or_create_config(db: AsyncSession, agent_id: str) -> M.WeComConfig:
    cfg = (
        await db.execute(select(M.WeComConfig).where(M.WeComConfig.agent_id == agent_id))
    ).scalar_one_or_none()
    if cfg is None:
        # Agent must exist.
        agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
        cfg = M.WeComConfig(id=new_id(), agent_id=agent_id, enabled=False, show_thinking=False)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


async def _bindings_for(db: AsyncSession, config_id: str) -> list[M.WeComBinding]:
    rows = (
        await db.execute(select(M.WeComBinding).where(M.WeComBinding.wecom_config_id == config_id))
    ).scalars().all()
    return list(rows)


@router.get("/agents/{agent_id}/wecom")
async def get_wecom(agent_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await _get_or_create_config(db, agent_id)
    bindings = await _bindings_for(db, cfg.id)
    return ok(_wecom_out(cfg, bindings))


@router.put("/agents/{agent_id}/wecom")
async def save_wecom(
    agent_id: str,
    data: S.WeComSave,
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_or_create_config(db, agent_id)
    cfg.bot_id = data.botId
    cfg.bot_key = data.botKey
    cfg.show_thinking = data.showThinking
    cfg.enabled = data.enabled
    await db.commit()
    await db.refresh(cfg)
    bindings = await _bindings_for(db, cfg.id)
    return ok(_wecom_out(cfg, bindings))


@router.patch("/agents/{agent_id}/wecom/enabled")
async def toggle_wecom_enabled(
    agent_id: str,
    data: S.WeComEnabledUpdate,
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_or_create_config(db, agent_id)
    cfg.enabled = data.enabled
    await db.commit()
    return ok({"agentId": agent_id, "enabled": cfg.enabled})


@router.post("/agents/{agent_id}/wecom/bindings")
async def add_binding(
    agent_id: str,
    data: S.WeComBindingCreate,
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_or_create_config(db, agent_id)
    binding = M.WeComBinding(
        id=new_id(),
        wecom_config_id=cfg.id,
        chat_id=data.chatId,
        description=data.description,
    )
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return ok(_binding_out(binding))


@router.delete("/wecom/bindings/{binding_id}")
async def delete_binding(binding_id: str, db: AsyncSession = Depends(get_db)):
    binding = (
        await db.execute(select(M.WeComBinding).where(M.WeComBinding.id == binding_id))
    ).scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail=f"binding {binding_id} not found")
    await db.delete(binding)
    await db.commit()
    return ok(message="deleted")
