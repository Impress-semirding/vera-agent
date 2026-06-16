"""Model config endpoints — CRUD for LLM provider configurations.

GET    /model-configs              — list all model configs
POST   /model-configs              — create a model config
PUT    /model-configs/{id}         — update a model config
DELETE /model-configs/{id}         — delete a model config
PATCH  /model-configs/{id}/enabled — toggle enabled
GET    /model-configs/models       — list enabled models for agent dropdown
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, iso, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["model-configs"])


def _model_config_out(m: M.ModelConfig) -> dict:
    return {
        "id": m.id,
        "provider": m.provider,
        "name": m.name,
        "modelId": m.model_id,
        "baseUrl": m.base_url,
        "apiKey": m.api_key,
        "enabled": m.enabled,
        "updatedAt": iso(m.updated_at),
        "createdAt": iso(m.created_at),
    }


async def _get_model_config(db: AsyncSession, config_id: str) -> M.ModelConfig:
    mc = (
        await db.execute(select(M.ModelConfig).where(M.ModelConfig.id == config_id))
    ).scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=404, detail=f"model config {config_id} not found")
    return mc


@router.get("/model-configs")
async def list_model_configs(db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    configs = (
        await db.execute(select(M.ModelConfig).order_by(M.ModelConfig.created_at.desc()))
    ).scalars().all()
    return ok([_model_config_out(c) for c in configs])


@router.post("/model-configs")
async def create_model_config(
    data: S.ModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    config = M.ModelConfig(
        id=new_id(),
        provider=data.provider,
        name=data.name,
        model_id=data.modelId,
        base_url=data.baseUrl,
        api_key=data.apiKey,
        enabled=data.enabled,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return ok(_model_config_out(config))


@router.put("/model-configs/{config_id}")
async def update_model_config(
    config_id: str,
    data: S.ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    config = await _get_model_config(db, config_id)
    if data.name is not None:
        config.name = data.name
    if data.modelId is not None:
        config.model_id = data.modelId
    if data.baseUrl is not None:
        config.base_url = data.baseUrl
    if data.apiKey is not None:
        config.api_key = data.apiKey
    if data.enabled is not None:
        config.enabled = data.enabled
    await db.commit()
    await db.refresh(config)
    return ok(_model_config_out(config))


@router.delete("/model-configs/{config_id}")
async def delete_model_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    config = await _get_model_config(db, config_id)
    await db.delete(config)
    await db.commit()
    return ok(message="deleted")


@router.patch("/model-configs/{config_id}/enabled")
async def toggle_model_config_enabled(
    config_id: str,
    data: S.ToggleEnabled,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    config = await _get_model_config(db, config_id)
    config.enabled = data.enabled
    await db.commit()
    return ok({"id": config.id, "enabled": config.enabled})


@router.get("/model-configs/models")
async def list_available_models(db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    """Return enabled model configs as simple {label, value} options for agent dropdowns."""
    configs = (
        await db.execute(
            select(M.ModelConfig).where(M.ModelConfig.enabled.is_(True)).order_by(M.ModelConfig.name)
        )
    ).scalars().all()
    return ok([
        {
            "label": c.name,
            "value": c.model_id,
            "provider": c.provider,
            "baseUrl": c.base_url,
        }
        for c in configs
    ])
