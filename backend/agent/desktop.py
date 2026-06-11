"""
Desktop session manager — Tab management and command dispatch.

Ports src/cli/commands/desktop.ts. Manages multiple tabs, each with its own
workspace, session, model config, and (eventually) agent loop.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from reasonix_server.config import (
    load_api_key,
    load_base_url,
    load_budget_usd,
    load_desktop_open_tabs,
    load_edit_mode,
    load_editor,
    load_preset,
    load_reasoning_effort,
    load_recent_workspaces,
    load_workspace_dir,
    resolve_model,
    save_desktop_open_tabs,
    save_settings,
)
from reasonix_server.emitter import SSEEventBus
from reasonix_server.protocol import (
    NeedsSetupEvent,
    SettingsEvent,
    TabOpenedEvent,
    TabClosedEvent,
    TurnCompleteEvent,
)


def _next_tab_id() -> str:
    return f"t{uuid.uuid4().hex[:6]}"


@dataclass
class Tab:
    id: str
    root_dir: str
    current_session: str
    current_preset: str
    current_model: str
    budget_usd: float | None
    abort_event: asyncio.Event | None = None

    # Populated later during Phase 1+ when agent loop is implemented
    runtime: Any = None
    toolset: Any = None
    system_prompt: str = ""


# Lazy import to avoid circular at module level
import asyncio


class DesktopManager:
    """
    Manages the full lifecycle of desktop tabs and command dispatch.
    Mirrors the command switch in desktop.ts lines 1314-1683.
    """

    def __init__(self, bus: SSEEventBus) -> None:
        self.bus = bus
        self.tabs: dict[str, Tab] = {}
        self._first: Tab | None = None

    # ------------------------------------------------------------------
    # Tab lifecycle
    # ------------------------------------------------------------------

    def create_tab(self, workspace_dir: str | None = None) -> Tab:
        dir_ = os.path.abspath(workspace_dir or load_workspace_dir() or os.getcwd())
        preset = load_preset()
        model = resolve_model(preset)
        tab = Tab(
            id=_next_tab_id(),
            root_dir=dir_,
            current_session=f"session-{uuid.uuid4().hex[:8]}",
            current_preset=preset,
            current_model=model,
            budget_usd=load_budget_usd(),
        )
        self.tabs[tab.id] = tab
        if self._first is None:
            self._first = tab

        self.bus.emit(TabOpenedEvent(workspace_dir=dir_), tab.id)
        self._emit_settings(tab)

        if not load_api_key():
            self.bus.emit(NeedsSetupEvent(reason="no_api_key"), tab.id)

        return tab

    def close_tab(self, tab_id: str) -> None:
        tab = self.tabs.pop(tab_id, None)
        if tab is None:
            return
        if tab.abort_event:
            tab.abort_event.set()
        self.bus.emit(TabClosedEvent(), tab_id)
        if self._first and self._first.id == tab_id:
            self._first = next(iter(self.tabs.values()), None)
        save_desktop_open_tabs([t.root_dir for t in self.tabs.values()])

    def get_tab(self, tab_id: str | None) -> Tab | None:
        if tab_id:
            return self.tabs.get(tab_id)
        return self._first

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _emit_settings(self, tab: Tab) -> None:
        api_key = load_api_key()
        self.bus.emit(
            SettingsEvent(
                reasoning_effort=load_reasoning_effort(),
                edit_mode=load_edit_mode(),
                budget_usd=load_budget_usd(),
                base_url=load_base_url() or None,
                api_key_prefix=api_key[:4] + "..." if api_key and len(api_key) > 4 else None,
                workspace_dir=tab.root_dir,
                recent_workspaces=load_recent_workspaces(),
                model=tab.current_model,
                preset=tab.current_preset,
                editor=load_editor(),
                version="0.1.0-py",
            ),
            tab.id,
        )

    # ------------------------------------------------------------------
    # Command dispatch (Phase 0 skeleton — commands return immediately)
    # ------------------------------------------------------------------

    async def handle_command(self, raw: dict[str, Any]) -> None:
        """
        Dispatch an OutgoingCommand. Each cmd type is handled below.
        This is the Python equivalent of the rl.on("line") switch in desktop.ts.
        """
        cmd = raw.get("cmd", "")
        tab_id = raw.get("tabId")
        tab = self.get_tab(tab_id)

        if cmd == "tab_open":
            workspace_dir = raw.get("workspaceDir")
            self.create_tab(workspace_dir)
            save_desktop_open_tabs([t.root_dir for t in self.tabs.values()])
            return

        if cmd == "tab_close":
            if tab:
                self.close_tab(tab.id)
            return

        if cmd == "settings_get":
            if tab:
                self._emit_settings(tab)
            return

        if cmd == "settings_save":
            # Extract patch fields
            patch = {k: v for k, v in raw.items() if k not in ("cmd", "tabId") and v is not None}
            save_settings(patch)
            if tab:
                # Update model if preset changed
                if "preset" in patch:
                    tab.current_preset = patch["preset"]
                    tab.current_model = resolve_model(patch["preset"])
                self._emit_settings(tab)
            return

        if cmd == "setup_save_key":
            from reasonix_server.config import save_api_key
            save_api_key(raw["key"])
            # Re-emit settings for all tabs (key is global)
            for t in self.tabs.values():
                self._emit_settings(t)
            return

        if cmd == "session_list":
            # Phase 2: implement session persistence
            if tab:
                self.bus.emit(
                    __import__("reasonix_server.protocol", fromlist=["SessionsEvent"]).SessionsEvent(items=[]),
                    tab.id,
                )
            return

        if cmd == "new_chat":
            if tab:
                tab.current_session = f"session-{uuid.uuid4().hex[:8]}"
                self.bus.emit(TurnCompleteEvent(), tab.id)
            return

        if cmd == "abort":
            if tab and tab.abort_event:
                tab.abort_event.set()
            return

        # --- Commands that require agent loop (Phase 1+) ---
        if cmd == "user_input":
            # Phase 1: will call run_turn(tab, raw["text"])
            if tab:
                self.bus.emit(
                    __import__("reasonix_server.protocol", fromlist=["ProtocolErrorEvent"]).ProtocolErrorEvent(
                        message="Agent loop not yet implemented (Phase 1)"
                    ),
                    tab.id,
                )
            return

        # Approval gate responses — Phase 3
        if cmd in (
            "confirm_response",
            "choice_response",
            "plan_response",
            "checkpoint_response",
            "revision_response",
        ):
            # Phase 3: resolve pause gate
            return

        # Other commands — stubs for later phases
        # mention_query, mention_preview, mention_picked,
        # session_delete, session_load,
        # mcp_specs_get/add/remove, skills_get, skill_run,
        # jobs_list, jobs_stop, jobs_stop_all
        pass

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self) -> None:
        """
        Initialize tabs from persisted state (desktopOpenTabs).
        Mirrors desktop.ts bootstrap flow.
        """
        saved = load_desktop_open_tabs()
        if saved:
            for entry in saved:
                # desktopOpenTabs may be list[str] or list[dict{dir,session,active}]
                d = entry["dir"] if isinstance(entry, dict) else entry
                self.create_tab(d)
        else:
            self.create_tab()
