"""Access control: who can use an agent.

Rule (single source of truth, shared by the agents + chat routers):
  a user can access an agent if they CREATED it, OR they have a ``Permission``
  row on it whose ``agent_permissions`` contains ``"view"``. ``visibility`` is
  only a display flag — it no longer grants access to everyone.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import models as M
from api.util import jload


async def can_access_agent(db: AsyncSession, agent: M.Agent, user_name: str) -> bool:
    if not user_name:
        return False
    if agent.created_by == user_name:
        return True
    perm = (
        await db.execute(
            select(M.Permission).where(
                M.Permission.agent_id == agent.id,
                M.Permission.user_name == user_name,
            )
        )
    ).scalar_one_or_none()
    if perm is None:
        return False
    perms = jload(perm.agent_permissions) or []
    return "view" in perms
