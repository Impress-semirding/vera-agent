"""Access control: who can use an agent.

Rule (single source of truth, shared by the agents + chat routers):
  a user can access (view) an agent if they CREATED it, they have a
  ``Permission`` row on it whose ``agent_permissions`` contains ``"view"``,
  OR it is a public system agent (``type == 'system'`` and ``visibility`` True)
  — public agents are visible to everyone.

  Edit/delete require the corresponding permission level (public visibility
  does NOT grant edit/delete). The owner always has full permissions.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import models as M
from api.util import jload

PermissionLevel = Literal["view", "edit", "delete"]

ALL_PERMISSIONS: list[PermissionLevel] = ["view", "edit", "delete"]


def _has_perm(perm_list: list[str], level: str) -> bool:
    """Check if a permission list contains the given level."""
    return level in (perm_list or [])


async def _get_user_perm_list(
    db: AsyncSession, agent_id: str, user_name: str,
) -> list[str] | None:
    """Return the agent_permissions list for a user on an agent, or None."""
    perm = (
        await db.execute(
            select(M.Permission).where(
                M.Permission.agent_id == agent_id,
                M.Permission.user_name == user_name,
            )
        )
    ).scalar_one_or_none()
    if perm is None:
        return None
    return jload(perm.agent_permissions) or []


async def can_access_agent(db: AsyncSession, agent: M.Agent, user_name: str) -> bool:
    if not user_name:
        return False
    # Public system agents (visibility=True) are viewable by everyone.
    if agent.visibility and agent.type == "system":
        return True
    if agent.created_by == user_name:
        return True
    perms = await _get_user_perm_list(db, agent.id, user_name)
    return _has_perm(perms or [], "view")


async def can_edit_agent(
    db: AsyncSession, agent: M.Agent, user_name: str,
) -> bool:
    """Owner always can edit; others need the 'edit' permission."""
    if not user_name:
        return False
    if agent.created_by == user_name:
        return True
    perms = await _get_user_perm_list(db, agent.id, user_name)
    return _has_perm(perms or [], "edit")


async def can_delete_agent(
    db: AsyncSession, agent: M.Agent, user_name: str,
) -> bool:
    """Owner always can delete; others need the 'delete' permission."""
    if not user_name:
        return False
    if agent.created_by == user_name:
        return True
    perms = await _get_user_perm_list(db, agent.id, user_name)
    return _has_perm(perms or [], "delete")


async def get_user_agent_permissions(
    db: AsyncSession, agent_id: str, user_name: str,
) -> list[PermissionLevel]:
    """Return the effective permissions a user has on an agent.

    The owner gets ALL_PERMISSIONS; others get whatever is in their
    Permission row's agent_permissions (or empty list).
    """
    if not user_name:
        return []
    agent = (
        await db.execute(select(M.Agent).where(M.Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return []
    if agent.created_by == user_name:
        return list(ALL_PERMISSIONS)
    perms = await _get_user_perm_list(db, agent_id, user_name)
    return [p for p in (perms or []) if p in ALL_PERMISSIONS]
