"""Skill endpoints — upload (.zip), inspect, download, list, update, toggle.

POST   /skills/inspect              — parse a zip → {name, description} (no save)
GET    /agents/{agent_id}/skills    — list skills for an agent
POST   /agents/{agent_id}/skills    — upload a skill zip (multipart: file + version)
GET    /skills/{skill_id}/download  — download the original zip
PUT    /skills/{skill_id}           — update metadata (JSON)
DELETE /skills/{skill_id}           — delete a skill
PATCH  /skills/{skill_id}/enabled   — toggle enabled

A skill is uploaded as a .zip. Its name + description are parsed from the
SKILL.md inside the package. The same skill may live on many agents, but a
given agent cannot hold two skills with the same name (HTTP 409).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.access import can_edit_agent
from api.api_response import current_user, iso, ok
from api.database import get_db
from api.models import models as M
from api.schemas import schemas as S
from api.skill_zip import parse_skill_zip
from api.util import jload, new_id

router = APIRouter(tags=["skills"])

_ZIP_MEDIA = "application/zip"

# Absolute path to the ``skills/`` directory (under VERA_DATA_DIR).
_DATA_DIR = os.environ.get("VERA_DATA_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"))
_SKILLS_DIR = os.path.join(_DATA_DIR, "skills")


def _skill_zip_path(skill_id: str) -> str:
    """Return the filesystem path for a skill's zip package."""
    return os.path.join(_SKILLS_DIR, f"{skill_id}.zip")


def _files_for(skill: M.Skill) -> list[dict]:
    """Lightweight file listing for the UI tree."""
    files = [{"name": "SKILL.md", "type": "markdown"}]
    if skill.filename:
        files.append({"name": skill.filename, "type": "code"})
    return files


def _skill_out(s: M.Skill) -> dict:
    return {
        "id": s.id,
        "agentId": s.agent_id,
        "name": s.name,
        "description": s.description or "",
        "body": s.body or "",
        "scope": s.scope,
        "path": s.path or "",
        "allowedTools": jload(s.allowed_tools),
        "runAs": s.run_as,
        "model": s.model,
        "version": s.version,
        "enabled": s.enabled,
        "hasZip": bool(s.file_path and os.path.isfile(s.file_path)),
        "updatedBy": s.updated_by,
        "updatedAt": iso(s.updated_at),
        "files": _files_for(s),
    }


async def _get_skill(db: AsyncSession, skill_id: str) -> M.Skill:
    s = (await db.execute(select(M.Skill).where(M.Skill.id == skill_id))).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail=f"skill {skill_id} not found")
    return s


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    return data


async def _parse_or_400(file: UploadFile) -> dict:
    data = await _read_upload(file)
    try:
        return parse_skill_zip(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/inspect")
async def inspect_skill(file: UploadFile = File(...), user: str = Depends(current_user)):
    """Parse a skill zip and return its name + description without persisting."""
    parsed = await _parse_or_400(file)
    return ok({"name": parsed["name"], "description": parsed["description"]})


@router.get("/agents/{agent_id}/skills")
async def list_skills(agent_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    skills = (
        await db.execute(
            select(M.Skill).where(M.Skill.agent_id == agent_id).order_by(M.Skill.updated_at.desc())
        )
    ).scalars().all()
    return ok([_skill_out(s) for s in skills])


@router.post("/agents/{agent_id}/skills")
async def upload_skill(
    agent_id: str,
    file: UploadFile = File(...),
    version: str = Form("1.0.0"),
    run_as: str = Form("inline"),
    model: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    if not await can_edit_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权编辑该智能体")

    data = await _read_upload(file)
    try:
        parsed = parse_skill_zip(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    name = parsed["name"]

    # Same agent cannot hold two skills with the same name; other agents may.
    duplicate = (
        await db.execute(
            select(M.Skill.id).where(M.Skill.agent_id == agent_id, M.Skill.name == name)
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail=f"该智能体已存在同名技能「{name}」")

    skill_id = new_id()
    zip_path = _skill_zip_path(skill_id)

    # Ensure the skills directory exists.
    os.makedirs(_SKILLS_DIR, exist_ok=True)

    # Write zip to filesystem.
    with open(zip_path, "wb") as f:
        f.write(data)

    skill = M.Skill(
        id=skill_id,
        agent_id=agent_id,
        name=name,
        description=parsed["description"],
        body=parsed["body"],
        scope="project",
        path=parsed["folder"] or "",
        run_as=run_as,
        model=model,
        version=version or "1.0.0",
        enabled=True,
        updated_by=user,
        file_path=zip_path,
        filename=file.filename or f"{name}.zip",
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return ok(_skill_out(skill))


@router.get("/skills/{skill_id}/download")
async def download_skill(skill_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    skill = await _get_skill(db, skill_id)
    if not skill.file_path or not os.path.isfile(skill.file_path):
        raise HTTPException(status_code=404, detail="该技能没有可下载的 zip 包")
    filename = skill.filename or f"{skill.name}.zip"
    with open(skill.file_path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type=_ZIP_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    data: S.SkillUpdate,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    skill = await _get_skill(db, skill_id)
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == skill.agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {skill.agent_id} not found")
    if not await can_edit_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权编辑该智能体")
    if data.description is not None:
        skill.description = data.description
    if data.model is not None:
        skill.model = data.model
    if data.version is not None:
        skill.version = data.version
    if data.enabled is not None:
        skill.enabled = data.enabled
    skill.updated_by = user
    await db.commit()
    await db.refresh(skill)
    return ok(_skill_out(skill))


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_db), user: str = Depends(current_user)):
    skill = await _get_skill(db, skill_id)
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == skill.agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {skill.agent_id} not found")
    if not await can_edit_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权编辑该智能体")
    # Remove zip file from disk if it exists.
    if skill.file_path and os.path.isfile(skill.file_path):
        os.remove(skill.file_path)
    await db.delete(skill)
    await db.commit()
    return ok(message="deleted")


@router.patch("/skills/{skill_id}/enabled")
async def toggle_skill_enabled(
    skill_id: str,
    data: S.ToggleEnabled,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(current_user),
):
    skill = await _get_skill(db, skill_id)
    agent = (await db.execute(select(M.Agent).where(M.Agent.id == skill.agent_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {skill.agent_id} not found")
    if not await can_edit_agent(db, agent, user):
        raise HTTPException(status_code=403, detail="无权编辑该智能体")
    skill.enabled = data.enabled
    await db.commit()
    return ok({"id": skill.id, "enabled": skill.enabled})
