"""Seed database with sample data for development."""

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from api.models.models import User
from api.util import hash_password

# Dev login account. Seeded only when the users table is empty.
_SEED_USERS = [
    ("admin", "admin@zhongan.com"),
    ("demo", "demo@example.com"),
]
_SEED_USER_PASSWORDS = {
    "admin": "123456",
    "demo": "123456",
}


async def seed(db: AsyncSession) -> None:
    from sqlalchemy import select

    # ── Users (independent guard: runs even if agents already seeded) ──
    has_user = (await db.execute(select(User))).scalars().first()
    if has_user is None:
        for name, email in _SEED_USERS:
            password = _SEED_USER_PASSWORDS.get(name, "123456")
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
