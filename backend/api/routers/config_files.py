"""Config-file endpoints (personal-agent ``.claude/`` tree + system base files).

GET    /agents/{agent_id}/config-files             — file tree (nested folders)
GET    /agents/{agent_id}/config-files/content      — read one file (?path=)
POST   /agents/{agent_id}/config-files              — create a file (fails if exists)
PUT    /agents/{agent_id}/config-files              — upsert a file's content (?path=)
DELETE /agents/{agent_id}/config-files              — delete a file (?path=)

Paths are POSIX-style (e.g. ``CLAUDE.md``, ``commands/weekly-report.md``,
``rules/SAFETY.md``). Intermediate folders are synthesised when building the
tree, so they don't need their own rows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_response import current_user, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.util import new_id

router = APIRouter(tags=["config-files"])


# ─── Tree builder ──────────────────────────────────────────────────────────


def _build_tree(paths: list[str]) -> list[dict]:
    root: dict[str, dict] = {}
    for path in paths:
        parts = path.split("/")
        node = root
        for i, part in enumerate(parts):
            cur_path = "/".join(parts[: i + 1])
            is_leaf = i == len(parts) - 1
            if part not in node:
                node[part] = {"_path": cur_path, "_type": "file" if is_leaf else "folder", "_children": {}}
            elif is_leaf:
                node[part]["_type"] = "file"
            node = node[part]["_children"]

    def to_list(d: dict) -> list[dict]:
        out: list[dict] = []
        for name, n in d.items():
            entry = {"name": name, "path": n["_path"], "type": n["_type"]}
            children = to_list(n["_children"])
            if children:
                entry["children"] = children
            out.append(entry)
        # folders first, then files; alphabetical within each group.
        out.sort(key=lambda e: (e["type"] != "folder", e["name"]))
        return out

    return to_list(root)


def _file_name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


async def _find(db: AsyncSession, agent_id: str, path: str) -> M.ConfigFile | None:
    return (
        await db.execute(
            select(M.ConfigFile).where(M.ConfigFile.agent_id == agent_id, M.ConfigFile.path == path)
        )
    ).scalar_one_or_none()


# ─── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/agents/{agent_id}/config-files")
async def list_config_files(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    rows = (
        await db.execute(select(M.ConfigFile).where(M.ConfigFile.agent_id == agent_id))
    ).scalars().all()
    paths = sorted(r.path for r in rows if r.path)
    return ok(_build_tree(paths))


@router.get("/agents/{agent_id}/config-files/content")
async def read_config_file(
    agent_id: str,
    path: str = Query(..., description="File path, e.g. CLAUDE.md"),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    f = await _find(db, agent_id, path)
    if f is None:
        raise HTTPException(status_code=404, detail=f"config file {path} not found")
    return ok({"name": _file_name(path), "path": path, "content": f.content or ""})


@router.post("/agents/{agent_id}/config-files")
async def create_config_file(
    agent_id: str,
    data: S.ConfigFileCreate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    if await _find(db, agent_id, data.path) is not None:
        raise HTTPException(status_code=409, detail=f"config file {data.path} already exists")

    f = M.ConfigFile(id=new_id(), agent_id=agent_id, path=data.path, content=data.content)
    db.add(f)
    await db.commit()
    return ok({"name": _file_name(data.path), "path": data.path, "content": data.content})


@router.put("/agents/{agent_id}/config-files")
async def upsert_config_file(
    agent_id: str,
    data: S.ConfigFileSave,
    path: str = Query(..., description="File path to create or update"),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")

    f = await _find(db, agent_id, path)
    if f is None:
        f = M.ConfigFile(id=new_id(), agent_id=agent_id, path=path, content=data.content)
        db.add(f)
    else:
        f.content = data.content
    await db.commit()
    return ok({"name": _file_name(path), "path": path, "content": data.content})


@router.delete("/agents/{agent_id}/config-files")
async def delete_config_file(
    agent_id: str,
    path: str = Query(..., description="File path to delete"),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    f = await _find(db, agent_id, path)
    if f is None:
        raise HTTPException(status_code=404, detail=f"config file {path} not found")
    await db.delete(f)
    await db.commit()
    return ok(message="deleted")
