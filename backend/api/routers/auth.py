"""Authentication endpoints.

POST /auth/login {identifier, password} — verify credentials, return the user.
GET  /auth/me                    — return the user for the current X-User header.

Identity is then carried by the X-User header on all other requests (see
``api.api_response.current_user``); login is the one place a password is checked.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import verify_password

router = APIRouter(tags=["auth"])


def _user_out(u: M.User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "avatarUrl": u.avatar_url}


@router.post("/auth/login")
async def login(data: S.LoginRequest, db: AsyncSession = Depends(get_db)):
    identifier = (data.identifier or "").strip()
    if not identifier or not data.password:
        raise HTTPException(status_code=401, detail="用户不存在或密码错误")
    user = (
        await db.execute(
            select(M.User).where(or_(M.User.name == identifier, M.User.email == identifier))
        )
    ).scalar_one_or_none()
    # Same message for "no such user" and "wrong password" — avoid enumeration.
    if user is None or not verify_password(data.password, user.salt, user.password_hash):
        raise HTTPException(status_code=401, detail="用户不存在或密码错误")
    return ok(_user_out(user))


@router.get("/auth/me")
async def me(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    row = (
        await db.execute(select(M.User).where(M.User.name == user))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="未登录")
    return ok(_user_out(row))
