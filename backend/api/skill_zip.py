"""Parse an uploaded skill ``.zip`` to extract its name + description.

A skill package is a zip that contains a ``SKILL.md`` either at the root or
inside a single top-level folder. ``SKILL.md`` may begin with YAML
frontmatter::

    ---
    name: voc-report
    description: Generate the weekly VOC report.
    ---
    # body…

The name is read from the frontmatter ``name`` field; if absent it falls back
to the enclosing folder name, then to the zip file name.
"""

from __future__ import annotations

import io
import re
import zipfile

import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _find_skill_md(zf: zipfile.ZipFile) -> str | None:
    """Locate SKILL.md in the archive, preferring the one closest to the root."""
    candidates = [n for n in zf.namelist() if n.rsplit("/", 1)[-1].upper() == "SKILL.MD"]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (n.count("/"), len(n)))
    return candidates[0]


def parse_skill_zip(data: bytes, filename: str = "") -> dict:
    """Parse a skill zip.

    Returns ``{"name", "description", "body", "folder"}``.
    Raises ``ValueError`` if the data is not a valid zip or has no SKILL.md.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("无效的 zip 文件") from exc

    skill_md = _find_skill_md(zf)
    if skill_md is None:
        raise ValueError("zip 内未找到 SKILL.md")

    body = zf.read(skill_md).decode("utf-8", errors="replace")
    folder = skill_md.rsplit("/", 1)[0] if "/" in skill_md else ""

    name = ""
    description = ""
    match = _FRONTMATTER_RE.match(body.lstrip("﻿"))
    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        if isinstance(frontmatter, dict):
            name = str(frontmatter.get("name") or "").strip()
            description = str(frontmatter.get("description") or "").strip()

    # Fallbacks for the name: enclosing folder, then the zip file name.
    if not name and folder:
        name = folder.rsplit("/", 1)[-1].strip()
    if not name:
        base = filename.rsplit("/", 1)[-1]
        name = base[:-4] if base.lower().endswith(".zip") else base
    name = name.strip() or "未命名技能"

    return {"name": name, "description": description, "body": body, "folder": folder}
