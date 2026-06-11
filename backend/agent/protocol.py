"""
Pydantic models for the desktop protocol.

These types MUST match desktop/src/protocol.ts exactly.
Every IncomingEvent must serialize to the same JSON shape the React frontend expects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None


# ---------------------------------------------------------------------------
# IncomingEvent types (Python → Frontend via SSE)
# ---------------------------------------------------------------------------

class ReadyEvent(BaseModel):
    type: Literal["$ready"] = "$ready"


class ProtocolErrorEvent(BaseModel):
    type: Literal["$error"] = "$error"
    message: str


class TurnCompleteEvent(BaseModel):
    type: Literal["$turn_complete"] = "$turn_complete"


class PathAccessRequiredEvent(BaseModel):
    type: Literal["$path_access_required"] = "$path_access_required"
    id: int
    path: str
    intent: Literal["read", "write"]
    tool_name: str = Field(alias="toolName")
    sandbox_root: str = Field(alias="sandboxRoot")
    allow_prefix: str = Field(alias="allowPrefix")

    model_config = {"populate_by_name": True}


class ConfirmationChoice(BaseModel):
    type: Literal["deny", "run_once", "always_allow"]
    deny_context: str | None = Field(None, alias="denyContext")
    prefix: str | None = None

    model_config = {"populate_by_name": True}


class ConfirmRequiredEvent(BaseModel):
    type: Literal["$confirm_required"] = "$confirm_required"
    id: int
    kind: Literal["run_command", "run_background"]
    command: str


class ChoiceOption(BaseModel):
    id: str
    title: str
    summary: str | None = None


class ChoiceRequiredEvent(BaseModel):
    type: Literal["$choice_required"] = "$choice_required"
    id: int
    question: str
    options: list[ChoiceOption]
    allow_custom: bool = Field(alias="allowCustom")

    model_config = {"populate_by_name": True}


class ChoiceVerdict(BaseModel):
    type: Literal["pick", "text", "cancel"]
    option_id: str | None = Field(None, alias="optionId")
    text: str | None = None

    model_config = {"populate_by_name": True}


class PlanStep(BaseModel):
    id: str
    title: str
    action: str
    risk: Literal["low", "med", "high"] | None = None


class PlanRequiredEvent(BaseModel):
    type: Literal["$plan_required"] = "$plan_required"
    id: int
    plan: str
    steps: list[PlanStep] | None = None
    summary: str | None = None


class PlanVerdict(BaseModel):
    type: Literal["approve", "refine", "cancel"]
    feedback: str | None = None


class CheckpointRequiredEvent(BaseModel):
    type: Literal["$checkpoint_required"] = "$checkpoint_required"
    id: int
    step_id: str = Field(alias="stepId")
    title: str | None = None
    result: str
    notes: str | None = None
    completed: int
    total: int

    model_config = {"populate_by_name": True}


class CheckpointVerdict(BaseModel):
    type: Literal["continue", "revise", "stop"]
    feedback: str | None = None


class RevisionRequiredEvent(BaseModel):
    type: Literal["$revision_required"] = "$revision_required"
    id: int
    reason: str
    remaining_steps: list[PlanStep] = Field(alias="remainingSteps")
    summary: str | None = None

    model_config = {"populate_by_name": True}


class RevisionVerdict(BaseModel):
    type: Literal["accepted", "rejected", "cancelled"]


class StepCompletedEvent(BaseModel):
    type: Literal["$step_completed"] = "$step_completed"
    step_id: str = Field(alias="stepId")
    title: str | None = None
    result: str
    notes: str | None = None

    model_config = {"populate_by_name": True}


class PlanClearedEvent(BaseModel):
    type: Literal["$plan_cleared"] = "$plan_cleared"


class SessionItem(BaseModel):
    name: str
    message_count: int = Field(alias="messageCount")
    mtime: str
    summary: str | None = None

    model_config = {"populate_by_name": True}


class SessionsEvent(BaseModel):
    type: Literal["$sessions"] = "$sessions"
    items: list[SessionItem]


class LoadedSegmentText(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class LoadedSegmentReasoning(BaseModel):
    kind: Literal["reasoning"] = "reasoning"
    text: str


class LoadedSegmentTool(BaseModel):
    kind: Literal["tool"] = "tool"
    call_id: str = Field(alias="callId")
    name: str
    args: str
    result: str | None = None
    ok: bool | None = None

    model_config = {"populate_by_name": True}


LoadedSegment = Annotated[
    Union[LoadedSegmentText, LoadedSegmentReasoning, LoadedSegmentTool],
    Field(discriminator="kind"),
]


class LoadedMessageUser(BaseModel):
    kind: Literal["user"] = "user"
    text: str


class LoadedMessageAssistant(BaseModel):
    kind: Literal["assistant"] = "assistant"
    turn: int
    segments: list[LoadedSegment]
    pending: bool = False


LoadedMessage = Annotated[
    Union[LoadedMessageUser, LoadedMessageAssistant],
    Field(discriminator="kind"),
]


class Carryover(BaseModel):
    total_cost_usd: float = Field(alias="totalCostUsd")
    cache_hit_tokens: int = Field(alias="cacheHitTokens")
    cache_miss_tokens: int = Field(alias="cacheMissTokens")

    model_config = {"populate_by_name": True}


class SessionLoadedEvent(BaseModel):
    type: Literal["$session_loaded"] = "$session_loaded"
    name: str
    messages: list[LoadedMessage]
    carryover: Carryover


class NeedsSetupEvent(BaseModel):
    type: Literal["$needs_setup"] = "$needs_setup"
    reason: Literal["no_api_key"] = "no_api_key"


class SettingsEvent(BaseModel):
    type: Literal["$settings"] = "$settings"
    reasoning_effort: Literal["high", "max"] = Field(alias="reasoningEffort")
    edit_mode: Literal["review", "auto", "yolo"] = Field(alias="editMode")
    budget_usd: float | None = Field(alias="budgetUsd")
    base_url: str | None = Field(None, alias="baseUrl")
    api_key_prefix: str | None = Field(None, alias="apiKeyPrefix")
    workspace_dir: str = Field(alias="workspaceDir")
    recent_workspaces: list[str] = Field(default_factory=list, alias="recentWorkspaces")
    model: str
    preset: Literal["auto", "flash", "pro"]
    editor: str | None = None
    version: str

    model_config = {"populate_by_name": True}


class BalanceEvent(BaseModel):
    type: Literal["$balance"] = "$balance"
    currency: str
    total: float
    is_available: bool = Field(alias="isAvailable")

    model_config = {"populate_by_name": True}


class SettingsPatch(BaseModel):
    reasoning_effort: Literal["high", "max"] | None = Field(None, alias="reasoningEffort")
    edit_mode: Literal["review", "auto", "yolo"] | None = Field(None, alias="editMode")
    budget_usd: float | None = Field(None, alias="budgetUsd")
    base_url: str | None = Field(None, alias="baseUrl")
    workspace_dir: str | None = Field(None, alias="workspaceDir")
    preset: Literal["auto", "flash", "pro"] | None = None
    editor: str | None = None

    model_config = {"populate_by_name": True}


class MentionResultsEvent(BaseModel):
    type: Literal["$mention_results"] = "$mention_results"
    nonce: int
    query: str
    results: list[str]


class MentionPreviewEvent(BaseModel):
    type: Literal["$mention_preview"] = "$mention_preview"
    nonce: int
    path: str
    head: str
    total_lines: int = Field(alias="totalLines")

    model_config = {"populate_by_name": True}


class TabOpenedEvent(BaseModel):
    type: Literal["$tab_opened"] = "$tab_opened"
    workspace_dir: str = Field(alias="workspaceDir")

    model_config = {"populate_by_name": True}


class TabClosedEvent(BaseModel):
    type: Literal["$tab_closed"] = "$tab_closed"


class McpSpecStatus(BaseModel):
    raw: str
    name: str | None
    transport: Literal["stdio", "sse", "streamable-http"]
    summary: str
    parse_error: str | None = Field(None, alias="parseError")
    status: Literal["configured", "handshake", "connected", "failed", "disabled"]
    status_reason: str | None = Field(None, alias="statusReason")
    tool_count: int | None = Field(None, alias="toolCount")

    model_config = {"populate_by_name": True}


class McpSpecsEvent(BaseModel):
    type: Literal["$mcp_specs"] = "$mcp_specs"
    specs: list[McpSpecStatus]
    bridged: bool


class SkillInfo(BaseModel):
    name: str
    description: str
    scope: Literal["project", "global", "builtin"]
    path: str
    run_as: Literal["inline", "subagent"] = Field(alias="runAs")
    model: str | None = None

    model_config = {"populate_by_name": True}


class SkillsEvent(BaseModel):
    type: Literal["$skills"] = "$skills"
    items: list[SkillInfo]


class CtxBreakdownEvent(BaseModel):
    type: Literal["$ctx_breakdown"] = "$ctx_breakdown"
    reserved_tokens: int = Field(alias="reservedTokens")

    model_config = {"populate_by_name": True}


class MemoryEntryInfo(BaseModel):
    name: str
    scope: Literal["project", "global"]
    description: str


class MemoryEvent(BaseModel):
    type: Literal["$memory"] = "$memory"
    entries: list[MemoryEntryInfo]


class JobInfo(BaseModel):
    id: int
    tab_id: str = Field(alias="tabId")
    session_label: str = Field(alias="sessionLabel")
    command: str
    pid: int | None
    running: bool
    exit_code: int | None = Field(None, alias="exitCode")
    started_at: int = Field(alias="startedAt")
    output_tail: str = Field(alias="outputTail")
    spawn_error: str | None = Field(None, alias="spawnError")

    model_config = {"populate_by_name": True}


class JobsEvent(BaseModel):
    type: Literal["$jobs"] = "$jobs"
    items: list[JobInfo]


# --- Streaming model/tool events (unprefixed) ---

class UserMessageEvent(BaseModel):
    type: Literal["user.message"] = "user.message"
    id: int
    ts: str
    turn: int
    text: str


class ModelTurnStartedEvent(BaseModel):
    type: Literal["model.turn.started"] = "model.turn.started"
    id: int
    ts: str
    turn: int
    model: str
    reasoning_effort: Literal["high", "max"] = Field(alias="reasoningEffort")
    prefix_hash: str = Field(alias="prefixHash")

    model_config = {"populate_by_name": True}


class ModelDeltaEvent(BaseModel):
    type: Literal["model.delta"] = "model.delta"
    id: int
    ts: str
    turn: int
    channel: Literal["content", "reasoning", "tool_args"]
    text: str


class ModelFinalEvent(BaseModel):
    type: Literal["model.final"] = "model.final"
    id: int
    ts: str
    turn: int
    content: str
    reasoning_content: str | None = Field(None, alias="reasoningContent")
    usage: Usage | None = None
    cost_usd: float | None = Field(None, alias="costUsd")

    model_config = {"populate_by_name": True}


class ToolPreparingEvent(BaseModel):
    type: Literal["tool.preparing"] = "tool.preparing"
    id: int
    ts: str
    turn: int
    call_id: str = Field(alias="callId")
    name: str

    model_config = {"populate_by_name": True}


class ToolIntentEvent(BaseModel):
    type: Literal["tool.intent"] = "tool.intent"
    id: int
    ts: str
    turn: int
    call_id: str = Field(alias="callId")
    name: str
    args: str

    model_config = {"populate_by_name": True}


class ToolResultEvent(BaseModel):
    type: Literal["tool.result"] = "tool.result"
    id: int
    ts: str
    turn: int
    call_id: str = Field(alias="callId")
    ok: bool
    output: str

    model_config = {"populate_by_name": True}


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    id: int
    ts: str
    turn: int
    text: str


class KernelErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    id: int
    ts: str
    turn: int
    message: str
    recoverable: bool


# Union of all incoming events
IncomingEvent = Annotated[
    Union[
        ReadyEvent,
        ProtocolErrorEvent,
        TurnCompleteEvent,
        ConfirmRequiredEvent,
        PathAccessRequiredEvent,
        ChoiceRequiredEvent,
        PlanRequiredEvent,
        SessionsEvent,
        SessionLoadedEvent,
        NeedsSetupEvent,
        SettingsEvent,
        BalanceEvent,
        CheckpointRequiredEvent,
        RevisionRequiredEvent,
        StepCompletedEvent,
        PlanClearedEvent,
        MentionResultsEvent,
        MentionPreviewEvent,
        TabOpenedEvent,
        TabClosedEvent,
        McpSpecsEvent,
        SkillsEvent,
        CtxBreakdownEvent,
        MemoryEvent,
        JobsEvent,
        UserMessageEvent,
        ModelTurnStartedEvent,
        ModelDeltaEvent,
        ModelFinalEvent,
        ToolPreparingEvent,
        ToolIntentEvent,
        ToolResultEvent,
        StatusEvent,
        KernelErrorEvent,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# OutgoingCommand types (Frontend → Python via POST /cmd)
# ---------------------------------------------------------------------------

class UserInputCmd(BaseModel):
    cmd: Literal["user_input"] = "user_input"
    tab_id: str | None = Field(None, alias="tabId")
    text: str

    model_config = {"populate_by_name": True}


class AbortCmd(BaseModel):
    cmd: Literal["abort"] = "abort"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class ConfirmResponseCmd(BaseModel):
    cmd: Literal["confirm_response"] = "confirm_response"
    tab_id: str | None = Field(None, alias="tabId")
    id: int
    response: ConfirmationChoice

    model_config = {"populate_by_name": True}


class ChoiceResponseCmd(BaseModel):
    cmd: Literal["choice_response"] = "choice_response"
    tab_id: str | None = Field(None, alias="tabId")
    id: int
    response: ChoiceVerdict

    model_config = {"populate_by_name": True}


class PlanResponseCmd(BaseModel):
    cmd: Literal["plan_response"] = "plan_response"
    tab_id: str | None = Field(None, alias="tabId")
    id: int
    response: PlanVerdict

    model_config = {"populate_by_name": True}


class CheckpointResponseCmd(BaseModel):
    cmd: Literal["checkpoint_response"] = "checkpoint_response"
    tab_id: str | None = Field(None, alias="tabId")
    id: int
    response: CheckpointVerdict

    model_config = {"populate_by_name": True}


class RevisionResponseCmd(BaseModel):
    cmd: Literal["revision_response"] = "revision_response"
    tab_id: str | None = Field(None, alias="tabId")
    id: int
    response: RevisionVerdict

    model_config = {"populate_by_name": True}


class SessionListCmd(BaseModel):
    cmd: Literal["session_list"] = "session_list"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class SessionDeleteCmd(BaseModel):
    cmd: Literal["session_delete"] = "session_delete"
    tab_id: str | None = Field(None, alias="tabId")
    name: str

    model_config = {"populate_by_name": True}


class SessionLoadCmd(BaseModel):
    cmd: Literal["session_load"] = "session_load"
    tab_id: str | None = Field(None, alias="tabId")
    name: str

    model_config = {"populate_by_name": True}


class NewChatCmd(BaseModel):
    cmd: Literal["new_chat"] = "new_chat"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class SetupSaveKeyCmd(BaseModel):
    cmd: Literal["setup_save_key"] = "setup_save_key"
    tab_id: str | None = Field(None, alias="tabId")
    key: str

    model_config = {"populate_by_name": True}


class SettingsGetCmd(BaseModel):
    cmd: Literal["settings_get"] = "settings_get"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class SettingsSaveCmd(BaseModel):
    cmd: Literal["settings_save"] = "settings_save"
    tab_id: str | None = Field(None, alias="tabId")
    reasoning_effort: Literal["high", "max"] | None = Field(None, alias="reasoningEffort")
    edit_mode: Literal["review", "auto", "yolo"] | None = Field(None, alias="editMode")
    budget_usd: float | None = Field(None, alias="budgetUsd")
    base_url: str | None = Field(None, alias="baseUrl")
    workspace_dir: str | None = Field(None, alias="workspaceDir")
    preset: Literal["auto", "flash", "pro"] | None = None
    editor: str | None = None

    model_config = {"populate_by_name": True}


class MentionQueryCmd(BaseModel):
    cmd: Literal["mention_query"] = "mention_query"
    tab_id: str | None = Field(None, alias="tabId")
    query: str
    nonce: int

    model_config = {"populate_by_name": True}


class MentionPreviewCmd(BaseModel):
    cmd: Literal["mention_preview"] = "mention_preview"
    tab_id: str | None = Field(None, alias="tabId")
    path: str
    nonce: int

    model_config = {"populate_by_name": True}


class MentionPickedCmd(BaseModel):
    cmd: Literal["mention_picked"] = "mention_picked"
    tab_id: str | None = Field(None, alias="tabId")
    path: str

    model_config = {"populate_by_name": True}


class TabOpenCmd(BaseModel):
    cmd: Literal["tab_open"] = "tab_open"
    tab_id: str | None = Field(None, alias="tabId")
    workspace_dir: str | None = Field(None, alias="workspaceDir")

    model_config = {"populate_by_name": True}


class TabCloseCmd(BaseModel):
    cmd: Literal["tab_close"] = "tab_close"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class McpSpecsGetCmd(BaseModel):
    cmd: Literal["mcp_specs_get"] = "mcp_specs_get"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class McpSpecsAddCmd(BaseModel):
    cmd: Literal["mcp_specs_add"] = "mcp_specs_add"
    tab_id: str | None = Field(None, alias="tabId")
    spec: str

    model_config = {"populate_by_name": True}


class McpSpecsRemoveCmd(BaseModel):
    cmd: Literal["mcp_specs_remove"] = "mcp_specs_remove"
    tab_id: str | None = Field(None, alias="tabId")
    spec: str

    model_config = {"populate_by_name": True}


class SkillsGetCmd(BaseModel):
    cmd: Literal["skills_get"] = "skills_get"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class SkillRunCmd(BaseModel):
    cmd: Literal["skill_run"] = "skill_run"
    tab_id: str | None = Field(None, alias="tabId")
    name: str
    args: str | None = None

    model_config = {"populate_by_name": True}


class JobsListCmd(BaseModel):
    cmd: Literal["jobs_list"] = "jobs_list"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


class JobsStopCmd(BaseModel):
    cmd: Literal["jobs_stop"] = "jobs_stop"
    tab_id: str | None = Field(None, alias="tabId")
    job_id: int = Field(alias="jobId")

    model_config = {"populate_by_name": True}


class JobsStopAllCmd(BaseModel):
    cmd: Literal["jobs_stop_all"] = "jobs_stop_all"
    tab_id: str | None = Field(None, alias="tabId")

    model_config = {"populate_by_name": True}


# Union of all outgoing commands
OutgoingCommand = Annotated[
    Union[
        UserInputCmd,
        AbortCmd,
        ConfirmResponseCmd,
        ChoiceResponseCmd,
        PlanResponseCmd,
        CheckpointResponseCmd,
        RevisionResponseCmd,
        SessionListCmd,
        SessionDeleteCmd,
        SessionLoadCmd,
        NewChatCmd,
        SetupSaveKeyCmd,
        SettingsGetCmd,
        SettingsSaveCmd,
        MentionQueryCmd,
        MentionPreviewCmd,
        MentionPickedCmd,
        TabOpenCmd,
        TabCloseCmd,
        McpSpecsGetCmd,
        McpSpecsAddCmd,
        McpSpecsRemoveCmd,
        SkillsGetCmd,
        SkillRunCmd,
        JobsListCmd,
        JobsStopCmd,
        JobsStopAllCmd,
    ],
    Field(discriminator="cmd"),
]
