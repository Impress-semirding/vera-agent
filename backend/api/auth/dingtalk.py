"""dingtalk-auth plugin — DingTalk OAuth2 client.

Self-contained DingTalk login integration. Reads all config from env vars
(see .env).  Used by api/routers/auth.py to add a DingTalk login path that
runs alongside the existing password login.

Modern OAuth2 flow (https://open.dingtalk.com):
  1. authorize  → https://login.dingtalk.com/oauth2/auth
  2. token      → POST https://api.dingtalk.com/v1.0/oauth2/userAccessToken
  3. userinfo   → GET  https://api.dingtalk.com/v1.0/contact/users/me
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import httpx


# ─── Config (env) ───────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def app_key() -> str:
    return _env("DINGTALK_APP_KEY")


def app_secret() -> str:
    return _env("DINGTALK_APP_SECRET")


def redirect_uri() -> str:
    return _env("DINGTALK_REDIRECT_URI")


def authorize_url() -> str:
    return _env("DINGTALK_AUTHORIZE_URL", "https://login.dingtalk.com/oauth2/auth")


def token_url() -> str:
    return _env("DINGTALK_TOKEN_URL", "https://api.dingtalk.com/v1.0/oauth2/userAccessToken")


def userinfo_url() -> str:
    return _env("DINGTALK_USERINFO_URL", "https://api.dingtalk.com/v1.0/contact/users/me")


def is_configured() -> bool:
    """True only when AppKey + AppSecret + redirect URI are all set."""
    return bool(app_key() and app_secret() and redirect_uri())


# ─── OAuth flow ─────────────────────────────────────────────────────────


def build_authorize_url(state: str) -> str:
    """Build the DingTalk authorize URL the browser redirects to."""
    params = {
        "client_id": app_key(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "prompt": "consent",
    }
    return f"{authorize_url()}?{urlencode(params)}"


def new_state() -> str:
    """Random CSRF state token."""
    return secrets.token_urlsafe(16)


async def exchange_code(auth_code: str) -> dict:
    """Exchange an authCode for a user access token.

    Returns DingTalk's token response: {accessToken, expireIn, refreshToken, ...}.
    """
    if not is_configured():
        raise RuntimeError("钉钉登录未配置 (DINGTALK_APP_KEY/SECRET/REDIRECT_URI)")

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), trust_env=False) as client:
        resp = await client.post(
            token_url(),
            json={
                "clientId": app_key(),
                "clientSecret": app_secret(),
                "code": auth_code,
                "grantType": "authorization_code",
            },
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"钉钉 token 接口异常: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        access_token = data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"钉钉未返回 accessToken: {data}")
        return data


async def get_userinfo(access_token: str) -> dict:
    """Fetch the DingTalk user profile (nick, unionId, openId, email, ...)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), trust_env=False) as client:
        resp = await client.get(
            userinfo_url(),
            headers={"x-acs-dingtalk-access-token": access_token},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"钉钉 userinfo 接口异常: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def fetch_user_by_code(auth_code: str) -> dict:
    """Full exchange: authCode → access token → userinfo. Returns userinfo dict."""
    token_data = await exchange_code(auth_code)
    return await get_userinfo(token_data["accessToken"])
