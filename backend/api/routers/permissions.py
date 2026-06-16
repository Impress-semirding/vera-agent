"""Permission endpoints.

GET    /agents/{agent_id}/permissions  — list members with permissions
POST   /agents/{agent_id}/permissions  — add a member
PUT    /permissions/{permission_id}    — update a member's permissions
DELETE /permissions/{permission_id}    — remove a member
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import jdump, jload, new_id

router = APIRouter(tags=["permissions"])


def _permission_out(p: M.Permission) -> dict:
    return {
        "id": p.id,
        "agentId": p.agent_id,
        "userName": p.user_name,
        "userEmail": p.user_email,
        "avatarUrl": p.avatar_url,
        "agentPermissions": jload(p.agent_permissions) or [],
        "authPermissions": jload(p.auth_permissions) or [],
    }


async def _get_permission(db: AsyncSession, permission_id: str) -> M.Permission:
    p = (await db.execute(select(M.Permission).where(M.Permission.id == permission_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail=f"permission {permission_id} not found")
    return p


@router.get("/agents/{agent_id}/permissions")
async def list_permissions(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    perms = (
        await db.execute(select(M.Permission).where(M.Permission.agent_id == agent_id))
    ).scalars().all()
    return ok([_permission_out(p) for p in perms])


@router.post("/agents/{agent_id}/permissions")
async def create_permission(
    agent_id: str,
    data: S.PermissionCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    perm = M.Permission(
        id=new_id(),
        agent_id=agent_id,
        user_name=data.userName,
        user_email=data.userEmail,
        avatar_url=data.avatarUrl,
        agent_permissions=jdump(data.agentPermissions),
        auth_permissions=jdump(data.authPermissions),
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    return ok(_permission_out(perm))


@router.put("/permissions/{permission_id}")
async def update_permission(
    permission_id: str,
    data: S.PermissionUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    perm = await _get_permission(db, permission_id)
    if data.userName is not None:
        perm.user_name = data.userName
    if data.userEmail is not None:
        perm.user_email = data.userEmail
    if data.avatarUrl is not None:
        perm.avatar_url = data.avatarUrl
    if data.agentPermissions is not None:
        perm.agent_permissions = jdump(data.agentPermissions)
    if data.authPermissions is not None:
        perm.auth_permissions = jdump(data.authPermissions)
    await db.commit()
    await db.refresh(perm)
    return ok(_permission_out(perm))


@router.delete("/permissions/{permission_id}")
async def delete_permission(permission_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    perm = await _get_permission(db, permission_id)
    await db.delete(perm)
    await db.commit()
    return ok(message="deleted")
