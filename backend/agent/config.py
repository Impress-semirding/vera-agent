"""
Configuration reader — reads ~/.reasonix/config.json (same format as the Node.js backend).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal


def default_config_path() -> Path:
    return Path.home() / ".reasonix" / "config.json"


def read_config(path: Path | None = None) -> dict[str, Any]:
    """Read the config.json, return empty dict on missing/invalid."""
    p = path or default_config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_config(cfg: dict[str, Any], path: Path | None = None) -> None:
    """Write config.json atomically."""
    p = path or default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)


def load_api_key(path: Path | None = None) -> str | None:
    """API key: config.json takes priority, then DEEPSEEK_API_KEY env var."""
    cfg = read_config(path)
    if cfg.get("apiKey"):
        return cfg["apiKey"]
    return os.environ.get("DEEPSEEK_API_KEY")


def load_base_url(path: Path | None = None) -> str:
    """Base URL: config → env → default."""
    cfg = read_config(path)
    if cfg.get("baseUrl"):
        return cfg["baseUrl"]
    return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def load_workspace_dir(path: Path | None = None) -> str | None:
    cfg = read_config(path)
    return cfg.get("workspaceDir")


def load_recent_workspaces(path: Path | None = None) -> list[str]:
    cfg = read_config(path)
    return cfg.get("recentWorkspaces", [])


def load_preset(path: Path | None = None) -> str:
    cfg = read_config(path)
    return cfg.get("preset", "auto")


def load_edit_mode(path: Path | None = None) -> str:
    cfg = read_config(path)
    v = cfg.get("editMode", "auto")
    # Be lenient: unknown values fall back to "auto"
    return v if v in ("review", "auto", "yolo") else "auto"


def load_reasoning_effort(path: Path | None = None) -> str:
    cfg = read_config(path)
    return cfg.get("reasoningEffort", "high")


def load_editor(path: Path | None = None) -> str | None:
    cfg = read_config(path)
    return cfg.get("editor")


def load_budget_usd(path: Path | None = None) -> float | None:
    cfg = read_config(path)
    return cfg.get("budgetUsd")


def load_desktop_open_tabs(path: Path | None = None) -> list[str]:
    cfg = read_config(path)
    return cfg.get("desktopOpenTabs", [])


def save_desktop_open_tabs(dirs: list[str], path: Path | None = None) -> None:
    cfg = read_config(path)
    cfg["desktopOpenTabs"] = dirs
    write_config(cfg, path)


def save_api_key(key: str, path: Path | None = None) -> None:
    cfg = read_config(path)
    cfg["apiKey"] = key
    write_config(cfg, path)


def save_settings(patch: dict[str, Any], path: Path | None = None) -> None:
    cfg = read_config(path)
    for k, v in patch.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v
    write_config(cfg, path)


# Model presets — mirrors src/config.ts resolvePreset()
PRESETS: dict[str, dict[str, str]] = {
    "auto": {"model": "deepseek-v4-flash"},
    "flash": {"model": "deepseek-v4-flash"},
    "pro": {"model": "deepseek-v4-pro"},
}


def resolve_model(preset: str | None = None, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    p = preset or load_preset()
    return PRESETS.get(p, PRESETS["auto"])["model"]
