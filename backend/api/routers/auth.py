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

from api.api_response import current_user, ok, sign_session_token
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import verify_password, generate_totp_secret, verify_totp, totp_qrcode_url

router = APIRouter(tags=["auth"])


def _user_out(u: M.User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "avatarUrl": u.avatar_url,
        "isSuperuser": bool(u.is_superuser),
        "maxConcurrentTurns": u.max_concurrent_turns,
        "isPasswordUser": not bool(u.dingtalk_union_id),  # only password users can set TOTP
    }


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

    # TOTP second factor
    if user.totp_enabled:
        if not user.totp_secret:
            raise HTTPException(status_code=500, detail="二次验证未正确配置，请联系管理员")
        if not data.totpCode:
            return ok({"requireTotp": True, "message": "请输入二次验证码"})
        if not verify_totp(user.totp_secret, data.totpCode):
            raise HTTPException(status_code=401, detail="二次验证码错误")

    token = sign_session_token(user.name)
    return ok({**_user_out(user), "token": token})


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
    token = sign_session_token(row.name)
    return ok({**_user_out(row), "token": token})


@router.get("/auth/userinfo")
async def userinfo(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    """Return the current user's info (for MCP servers calling back to Vera).
    Accepts ``Authorization: Bearer`` or ``vera-token`` header.
    """
    row = (
        await db.execute(select(M.User).where(M.User.name == user))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ok(_user_out(row))


# ═══════════════════════════════════════════════════════════════════════
# TOTP setup (self-service — the authenticated user manages their own 2FA)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/auth/totp/setup")
async def totp_setup(
    db: AsyncSession = Depends(get_db),
    user_name: str = Depends(current_user),
):
    """Generate a new TOTP secret and return the QR code for scanning.

    If TOTP is already enabled, returns ``{alreadyEnabled: true}`` without
    overwriting the existing secret — protects an active 2FA from being
    accidentally broken by re-entering setup.
    """
    row = (
        await db.execute(select(M.User).where(M.User.name == user_name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if row.totp_enabled:
        return ok({"alreadyEnabled": True, "message": "二次验证已开启"})


    secret = generate_totp_secret()
    row.totp_secret = secret
    row.totp_enabled = False  # stays disabled until verified
    await db.commit()

    qr_url = totp_qrcode_url(row.name, secret)
    import io, base64 as b64
    import qrcode as qrcode_lib
    img = qrcode_lib.make(qr_url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_img = b64.b64encode(buf.getvalue()).decode()
    return ok({"secret": secret, "qrcodeUrl": qr_url, "qrcodeImg": qr_img})


@router.post("/auth/totp/verify")
async def totp_verify(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user_name: str = Depends(current_user),
):
    """Verify the TOTP setup by checking a code, then enable 2FA."""
    row = (
        await db.execute(select(M.User).where(M.User.name == user_name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not row.totp_secret:
        raise HTTPException(status_code=400, detail="请先调用 /auth/totp/setup 生成密钥")

    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    if not verify_totp(row.totp_secret, code):
        raise HTTPException(status_code=400, detail="验证码错误")
    row.totp_enabled = True
    await db.commit()
    return ok({"enabled": True, "message": "二次验证已开启"})


@router.post("/auth/totp/disable")
async def totp_disable(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user_name: str = Depends(current_user),
):
    """Disable TOTP 2FA — must verify a valid code first to prove access."""
    row = (
        await db.execute(select(M.User).where(M.User.name == user_name))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not row.totp_enabled or not row.totp_secret:
        raise HTTPException(status_code=400, detail="二次验证未开启")

    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    if not verify_totp(row.totp_secret, code):
        raise HTTPException(status_code=400, detail="验证码错误")

    row.totp_secret = None
    row.totp_enabled = False
    await db.commit()
    return ok({"enabled": False, "message": "二次验证已关闭"})


# ═══════════════════════════════════════════════════════════════════════
# DingTalk OAuth login (dingtalk-auth plugin)
# ═══════════════════════════════════════════════════════════════════════

# Pending CSRF states: state → issued-epoch. Bounded + short-lived.
_dingtalk_states: dict[str, float] = {}
_STATE_TTL = 300  # seconds


@router.get("/auth/dingtalk/config")
async def dingtalk_config():
    """Return the DingTalk authorize URL + state, or enabled=false if unconfigured."""
    from api.auth import dingtalk

    if not dingtalk.is_configured():
        return ok({"enabled": False, "authorizeUrl": None, "state": None})

    # Drop expired states
    import time
    now = time.time()
    for s, t in list(_dingtalk_states.items()):
        if now - t > _STATE_TTL:
            _dingtalk_states.pop(s, None)

    state = dingtalk.new_state()
    _dingtalk_states[state] = now
    return ok({
        "enabled": True,
        "authorizeUrl": dingtalk.build_authorize_url(state),
        "state": state,
    })


@router.post("/auth/dingtalk/login")
async def dingtalk_login(body: dict, db: AsyncSession = Depends(get_db)):
    """Exchange a DingTalk authCode for a Vera user.

    Body: {"authCode": "...", "state": "..."}.
    """
    from api.auth import dingtalk
    import time

    if not dingtalk.is_configured():
        raise HTTPException(status_code=400, detail="钉钉登录未配置")

    auth_code = str(body.get("authCode") or "")
    state = str(body.get("state") or "")
    if not auth_code:
        raise HTTPException(status_code=400, detail="缺少 authCode")

    # Validate state (CSRF) — required, must match a state we issued.
    if not state:
        raise HTTPException(status_code=400, detail="缺少 state")
    issued = _dingtalk_states.pop(state, None)
    if issued is None:
        raise HTTPException(status_code=400, detail="state 无效或已过期")
    if time.time() - issued > _STATE_TTL:
        raise HTTPException(status_code=400, detail="state 已过期")

    try:
        info = await dingtalk.fetch_user_by_code(auth_code)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"钉钉登录失败: {exc}")

    user = await _upsert_dingtalk_user(db, info)
    token = sign_session_token(user.name)
    return ok({**_user_out(user), "token": token})


async def _upsert_dingtalk_user(db: AsyncSession, info: dict) -> M.User:
    """Find or create a User from DingTalk userinfo (matched by unionId)."""
    from api.util import hash_password, new_id

    union_id = str(info.get("unionId") or "").strip()
    if not union_id:
        raise HTTPException(status_code=400, detail="钉钉未返回 unionId")

    # Existing binding
    user = (
        await db.execute(select(M.User).where(M.User.dingtalk_union_id == union_id))
    ).scalar_one_or_none()
    if user is not None:
        # Refresh display fields if changed
        nick = str(info.get("nick") or "").strip()
        avatar = str(info.get("avatarUrl") or "").strip() or None
        if nick and nick != user.name:
            user.name = await _unique_name(db, nick, exclude_id=user.id)
        if avatar:
            user.avatar_url = avatar
        await db.commit()
        await db.refresh(user)
        return user

    # Create new SSO user (no usable password — random sentinel hash)
    nick = str(info.get("nick") or "").strip() or f"钉钉用户_{union_id[-6:]}"
    email = str(info.get("email") or "").strip() or f"{union_id}@dingtalk.local"
    avatar = str(info.get("avatarUrl") or "").strip() or None
    name = await _unique_name(db, nick)
    email = await _unique_email(db, email)
    sentinel_hash, sentinel_salt = hash_password(secrets_token())  # unguessable

    user = M.User(
        id=new_id(),
        name=name,
        email=email,
        password_hash=sentinel_hash,
        salt=sentinel_salt,
        avatar_url=avatar,
        dingtalk_union_id=union_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _unique_name(db: AsyncSession, base: str, exclude_id: str | None = None) -> str:
    """Ensure name uniqueness by appending -2, -3, ..."""
    name = base
    i = 1
    while True:
        q = select(M.User).where(M.User.name == name)
        if exclude_id:
            q = q.where(M.User.id != exclude_id)
        if (await db.execute(q)).scalar_one_or_none() is None:
            return name
        i += 1
        name = f"{base}-{i}"


async def _unique_email(db: AsyncSession, base: str) -> str:
    email = base
    i = 1
    while True:
        if (await db.execute(select(M.User).where(M.User.email == email))).scalar_one_or_none() is None:
            return email
        i += 1
        email = f"{base.split('@')[0]}-{i}@{'@'.join(base.split('@')[1:])}"


def secrets_token() -> str:
    """Random unguessable string for the sentinel password."""
    import secrets as _s
    return _s.token_urlsafe(32)
