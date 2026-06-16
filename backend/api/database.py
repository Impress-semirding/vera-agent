"""Database engine + session factory."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./data/db/reasonix.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn) -> None:
    """Idempotent column additions for pre-existing SQLite databases.

    ``create_all`` only creates missing tables — it will not add columns to a
    table that already exists. New nullable columns are ALTERed here so an
    existing dev database keeps working without a manual wipe. (A unique
    constraint can't be added to an existing SQLite table without rebuilding
    it, so (agent_id, name) uniqueness is also enforced in application code.)
    """
    # Skip migration entirely if the skills table was just created by create_all
    # (i.e. the new schema already has all columns).
    rows = (await conn.execute(text("PRAGMA table_info(skills)"))).fetchall()
    if not rows:
        return
    columns = {r[1] for r in rows}

    # For old DBs: add file_path column (zip_data already exists from prior migration).
    if "file_path" not in columns:
        await conn.execute(text("ALTER TABLE skills ADD COLUMN file_path VARCHAR(500)"))
    if "filename" not in columns:
        await conn.execute(text("ALTER TABLE skills ADD COLUMN filename VARCHAR(500)"))

    # users: add dingtalk_union_id for DingTalk SSO login (nullable, no unique
    # constraint — SQLite can't add one to an existing table; enforced in app code).
    user_cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(users)"))).fetchall()}
    if "dingtalk_union_id" not in user_cols:
        await conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_union_id VARCHAR(128)"))
    if "is_superuser" not in user_cols:
        await conn.execute(text("ALTER TABLE users ADD COLUMN is_superuser BOOLEAN DEFAULT 0"))
    if "max_concurrent_turns" not in user_cols:
        await conn.execute(text("ALTER TABLE users ADD COLUMN max_concurrent_turns INTEGER"))
    if "totp_secret" not in user_cols:
        await conn.execute(text("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)"))
    if "totp_enabled" not in user_cols:
        await conn.execute(text("ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
