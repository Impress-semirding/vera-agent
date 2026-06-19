"""为出站 MCP 调用签发 RS256 JWT。

资源服务器（如 mysql_mcp）持配对的 RSA 公钥做验签。私钥从环境变量
``VERA_MCP_JWT_PRIVATE_KEY`` 读取（PEM，换行可写成字面 ``\\n``），**绝不入库 / 提交**。

未配置私钥时，:func:`is_mcp_jwt_enabled` 返回 False，调用方应跳过 JWT 注入。
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

_ISSUER = os.environ.get("VERA_MCP_JWT_ISSUER", "vera-agent")
# 与会话时长匹配；过短会导致会话进行中 token 失效。
_TTL = int(os.environ.get("VERA_MCP_JWT_TTL", str(3600)))


@lru_cache(maxsize=1)
def _private_key() -> str | None:
    """加载并缓存 RSA 私钥 PEM（把字面 ``\\n`` 还原为真实换行）。未配置返回 None。"""
    raw = os.environ.get("VERA_MCP_JWT_PRIVATE_KEY", "").strip()
    if not raw:
        return None
    return raw.replace("\\n", "\n")


def is_mcp_jwt_enabled() -> bool:
    """是否配置了私钥（即是否应给出站 MCP 调用注入 JWT）。"""
    return _private_key() is not None


def mint_mcp_jwt(*, sub: str, audience: str) -> str | None:
    """签发一个 RS256 JWT。

    Args:
        sub: 调用方标识（通常为 user_id）。
        audience: 目标 MCP server 的标识（即该 server 在 DB 中的 name；
            资源服务器侧的 ``JWT_AUDIENCE`` 须与之相同）。

    Returns:
        签名后的 JWT 字符串；未配置私钥时返回 None。
    """
    import jwt  # PyJWT

    key = _private_key()
    if not key:
        return None
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "sub": sub,
        "aud": audience,
        "iat": now,
        "exp": now + _TTL,
        "jti": f"{sub}-{now}",
    }
    return jwt.encode(payload, key, algorithm="RS256")
