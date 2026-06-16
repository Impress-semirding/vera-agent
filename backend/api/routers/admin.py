"""Admin endpoints — superuser-only.

Currently manages per-user concurrency limits (max concurrent agent turns).
The admin user (password-login, seeded) is the superuser; DingTalk users are
regular users whose limits the admin can tune.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M

router = APIRouter(tags=["admin"])


async def require_superuser(
    user: str = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> M.User:
    """Dependency: the caller must be a superuser."""
    row = (
        await db.execute(select(M.User).where(M.User.name == user))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="无权访问")
    if not row.is_superuser:
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return row


def _user_admin_out(u: M.User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "avatarUrl": u.avatar_url,
        "dingtalkUnionId": u.dingtalk_union_id,
        "isSuperuser": bool(u.is_superuser),
        "maxConcurrentTurns": u.max_concurrent_turns,
    }


@router.get("/admin/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: M.User = Depends(require_superuser),
):
    """List all users with their concurrency config + the env default."""
    from api.routers.chat import _get_max_turns
    rows = (
        await db.execute(select(M.User).order_by(M.User.created_at.desc()))
    ).scalars().all()
    return ok({
        "users": [_user_admin_out(u) for u in rows],
        "defaultMaxTurns": _get_max_turns(),
    })


@router.put("/admin/users/{user_id}/concurrency")
async def set_user_concurrency(
    user_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: M.User = Depends(require_superuser),
):
    """Set a user's max concurrent turns (null = use env default).

    Body: {"maxConcurrentTurns": 5 | null}
    """
    target = (
        await db.execute(select(M.User).where(M.User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    raw = body.get("maxConcurrentTurns")
    if raw is None or raw == "":
        target.max_concurrent_turns = None
    else:
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="maxConcurrentTurns 必须是整数")
        if val < 1:
            raise HTTPException(status_code=400, detail="maxConcurrentTurns 必须 >= 1")
        target.max_concurrent_turns = val

    await db.commit()
    await db.refresh(target)

    # Invalidate the user's cached semaphore so the next turn picks up the new cap
    from api.routers.chat import invalidate_user_sem
    invalidate_user_sem(target.name)

    return ok(_user_admin_out(target))
