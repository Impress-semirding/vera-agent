"""Seed database with sample data for development."""

import os
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from api.models.models import User
from api.util import hash_password

# ── Seed users from env (or hardcoded defaults) ─────────────────────────
# Format: VERA_SEED_USERS=name:email:password,name:email:password,...
# Default: admin/admin@zhongan.com/123456 + demo/demo@example.com/123456
_DEFAULT = "admin:admin@zhongan.com:123456,demo:demo@example.com:123456"


def _parse_seed_users() -> list[tuple[str, str, str]]:
    raw = os.environ.get("VERA_SEED_USERS", _DEFAULT).strip()
    users = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) == 3:
            users.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return users


async def seed(db: AsyncSession) -> None:
    from sqlalchemy import select

    # ── Users (independent guard: runs even if agents already seeded) ──
    has_user = (await db.execute(select(User))).scalars().first()
    if has_user is None:
        for name, email, password in _parse_seed_users():
            pw_hash, salt = hash_password(password)
            db.add(User(
                id=uuid.uuid4().hex, name=name, email=email,
                password_hash=pw_hash, salt=salt,
                is_superuser=(name == "admin"),  # seeded admin is superuser
            ))
        await db.commit()
    else:
        # Existing DB: ensure the "admin" user is promoted to superuser
        admin = (await db.execute(select(User).where(User.name == "admin"))).scalar_one_or_none()
        if admin is not None and not admin.is_superuser:
            admin.is_superuser = True
            await db.commit()
