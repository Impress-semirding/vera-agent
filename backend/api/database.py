"""Database engine + session factory."""

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

_data_dir = os.environ.get("VERA_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
DATABASE_URL = f"sqlite+aiosqlite:///{_data_dir}/db/reasonix.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session


async def init_db() -> None:
    # Verify data dir is writable before doing anything
    _db_dir = os.path.dirname(DATABASE_URL.replace("sqlite+aiosqlite:///", ""))
    os.makedirs(_db_dir, exist_ok=True)
    try:
        probe = os.path.join(_db_dir, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except (OSError, PermissionError) as exc:
        raise RuntimeError(
            f"数据目录无写入权限: {_db_dir}\n"
            f"请确认 uvicorn 进程用户对 VERA_DATA_DIR 有写权限: {_data_dir}\n"
            f"  sudo chown -R <user> {_data_dir}\n"
            f"原始错误: {exc}"
        ) from exc

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

    # scheduled_tasks: add script + task_type columns (new schema since initial creation)
    sched_cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(scheduled_tasks)"))).fetchall()}
    if sched_cols and "script_content" not in sched_cols:
        await conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN script_content TEXT"))
    if sched_cols and "script_name" not in sched_cols:
        await conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN script_name VARCHAR(200)"))
    if sched_cols and "task_type" not in sched_cols:
        await conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN task_type VARCHAR(20) DEFAULT 'agent'"))
