"""Pydantic schemas — request/response models for every endpoint.

These mirror the TypeScript types in ``fr/src/types/*`` one-to-one so the
frontend contract is enforced at the API boundary. Field names use camelCase
to match the frontend exactly (the DB models stay snake_case).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════ Generic ═══════════════════════


class ApiResponse(BaseModel):
    code: int = 0
    data: Any = None
    message: str = "ok"


class PaginatedData(BaseModel):
    items: list[Any]
    total: int


# ═══════════════════════ Auth ═══════════════════════


class LoginRequest(BaseModel):
    identifier: str  # user name or email
    password: str


class AuthUser(BaseModel):
    id: str
    name: str
    email: str
    avatarUrl: str | None = None
    page: int = 1
    pageSize: int = 50


# ═══════════════════════ Agent ═══════════════════════


class AgentFormData(BaseModel):
    name: str
    description: str | None = None
    model: str
    type: str = "personal"  # system | personal
    mode: str = "claude"  # claude | normal
    avatarUrl: str | None = None
    visibility: bool = True
    wechatEnabled: bool = False
    wechatToken: str | None = None


# Backwards-compatible alias used by older code paths.
AgentCreate = AgentFormData


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model: str | None = None
    type: str | None = None
    mode: str | None = None
    avatarUrl: str | None = None
    visibility: bool | None = None
    wechatEnabled: bool | None = None
    wechatToken: str | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    description: str | None
    type: str
    mode: str
    model: str
    avatarUrl: str | None
    visibility: bool
    starred: bool
    createdBy: str
    updatedBy: str
    wechatEnabled: bool | None = None
    wechatToken: str | None = None
    updatedAt: str
    createdAt: str


# ═══════════════════════ Session / Message ═══════════════════════


class SessionCreate(BaseModel):
    name: str | None = None
    projectId: str | None = None


class SessionUpdate(BaseModel):
    name: str | None = None


class SessionOut(BaseModel):
    id: str
    agentId: str
    name: str
    projectId: str | None
    createdAt: str
    lastMessageAt: str | None = None


class MessageSend(BaseModel):
    content: str


class Artifact(BaseModel):
    type: str = "file"  # browser | file
    url: str | None = None
    fileName: str | None = None
    content: str | None = None


class MessageOut(BaseModel):
    id: str
    sessionId: str
    role: str
    content: str | None
    reasoningContent: str | None
    timestamp: str
    artifacts: list[Artifact] | None = None


# ═══════════════════════ MCP ═══════════════════════


class McpServerCreate(BaseModel):
    name: str
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    transport: str = "stdio"  # stdio | sse | streamable-http
    url: str | None = None
    headers: dict[str, str] | None = None
    disabled: bool = False


class McpServerUpdate(BaseModel):
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    transport: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    disabled: bool | None = None


class McpToolOut(BaseModel):
    id: str
    name: str
    description: str | None
    parameters: dict | None = None
    enabled: bool


class McpServerOut(BaseModel):
    id: str
    agentId: str
    name: str
    command: str | None
    args: list[str] | None
    env: dict[str, str] | None
    transport: str
    url: str | None
    headers: dict[str, str] | None
    disabled: bool
    tools: list[McpToolOut] = []


class ToggleDisabled(BaseModel):
    disabled: bool


class ToggleEnabled(BaseModel):
    enabled: bool


# ═══════════════════════ Skill ═══════════════════════


class SkillFile(BaseModel):
    name: str
    type: str = "markdown"  # markdown | code | config


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    body: str = ""
    scope: str = "project"  # project | custom | global | builtin
    path: str | None = None
    allowedTools: list[str] | None = None
    runAs: str = "inline"  # inline | subagent
    model: str | None = None
    version: str = "1.0.0"
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None
    scope: str | None = None
    path: str | None = None
    allowedTools: list[str] | None = None
    runAs: str | None = None
    model: str | None = None
    version: str | None = None
    enabled: bool | None = None


class SkillOut(BaseModel):
    id: str
    agentId: str
    name: str
    description: str
    body: str
    scope: str
    path: str
    allowedTools: list[str] | None
    runAs: str
    model: str | None
    version: str
    enabled: bool
    updatedBy: str
    updatedAt: str
    files: list[SkillFile] = []


# ═══════════════════════ Permission ═══════════════════════


class PermissionCreate(BaseModel):
    userName: str
    userEmail: str
    avatarUrl: str | None = None
    agentPermissions: list[str] = Field(default_factory=lambda: ["view"])
    authPermissions: list[str] = Field(default_factory=lambda: ["view"])


class PermissionUpdate(BaseModel):
    userName: str | None = None
    userEmail: str | None = None
    avatarUrl: str | None = None
    agentPermissions: list[str] | None = None
    authPermissions: list[str] | None = None


class PermissionOut(BaseModel):
    id: str
    agentId: str
    userName: str
    userEmail: str
    avatarUrl: str | None
    agentPermissions: list[str]
    authPermissions: list[str]


# ═══════════════════════ Push task ═══════════════════════
# The frontend PushTask is a flat object. We persist the core scalars in
# dedicated columns and the rest in a JSON ``config`` blob; the API always
# returns / accepts the flat shape.


class PushTaskCreate(BaseModel):
    name: str
    type: str  # wecom-app | webhook-group | longconn-group | longconn-single
    status: str = "draft"  # active | draft | stopped
    enabled: bool = False
    formStyle: str = "msg"  # url | msg
    config: dict[str, Any] = Field(default_factory=dict)


class PushTaskUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    status: str | None = None
    enabled: bool | None = None
    formStyle: str | None = None
    config: dict[str, Any] | None = None


class PushTaskOut(BaseModel):
    id: str
    agentId: str
    name: str
    type: str
    status: str
    enabled: bool
    formStyle: str
    # All type-specific fields (webhookUrl, chatId, targetUser, cronExpression,
    # audit, title, ...) are flattened from the config blob.
    model_config = {"extra": "allow"}


class PushStatusUpdate(BaseModel):
    status: str


# ═══════════════════════ WeCom ═══════════════════════


class WeComSave(BaseModel):
    botId: str
    botKey: str
    showThinking: bool = False
    enabled: bool = True


class WeComEnabledUpdate(BaseModel):
    enabled: bool


class WeComBindingCreate(BaseModel):
    chatId: str
    description: str | None = None


class WeComBindingOut(BaseModel):
    id: str
    chatId: str
    description: str | None


class WeComOut(BaseModel):
    agentId: str
    enabled: bool
    botId: str | None
    botKey: str | None
    showThinking: bool
    bindings: list[WeComBindingOut] = []


# ═══════════════════════ Session settings ═══════════════════════
# Field names match fr/src/types/config.ts SessionSettings exactly.


class SessionSettingsUpdate(BaseModel):
    allowUpload: bool | None = None
    allowEffortCustomization: bool | None = None
    allowManualContextClear: bool | None = None


class SessionSettingsOut(BaseModel):
    allowUpload: bool
    allowEffortCustomization: bool
    allowManualContextClear: bool


# ═══════════════════════ Config file ═══════════════════════


class ConfigFileOut(BaseModel):
    name: str
    path: str
    content: str


class ConfigFileSave(BaseModel):
    content: str


class ConfigFileCreate(BaseModel):
    path: str
    content: str = ""


class ConfigFileTreeNode(BaseModel):
    name: str
    path: str
    type: str  # file | folder
    children: list["ConfigFileTreeNode"] | None = None


class ConfigFileVersion(BaseModel):
    id: str
    content: str
    author: str
    timestamp: str


# ═══════════════════════ History ═══════════════════════


class ExecRecordOut(BaseModel):
    id: str
    agentId: str
    sessionSource: str | None
    sessionId: str | None
    userId: str | None
    status: str
    content: str | None
    timestamp: str


class ModifyRecordOut(BaseModel):
    id: str
    agentId: str
    operator: str
    action: str
    detail: str | None
    timestamp: str


# ═══════════════════════ ModelConfig ═══════════════════════


class ModelConfigCreate(BaseModel):
    provider: str           # deepseek | glm | minimax | qianwen
    name: str               # display name
    modelId: str            # model identifier for API calls
    baseUrl: str            # Anthropic-compatible base URL
    apiKey: str             # API key
    enabled: bool = True


class ModelConfigUpdate(BaseModel):
    name: str | None = None
    modelId: str | None = None
    baseUrl: str | None = None
    apiKey: str | None = None
    enabled: bool | None = None


class ModelConfigOut(BaseModel):
    id: str
    provider: str
    name: str
    modelId: str
    baseUrl: str
    apiKey: str
    enabled: bool
    updatedAt: str
    createdAt: str


# ═══════════════════════ WeChat iLink ═══════════════════════


class WeChatLoginResponse(BaseModel):
    """Response after starting QR code login."""
    qrcode: str = ""  # QR code string for polling
    qrcodeImg: str = ""  # base64-encoded PNG image for display
    loginStatus: str = "pending"  # pending|scanned|confirmed|expired


class WeChatStatusResponse(BaseModel):
    """Full WeChat connection status for an agent."""
    enabled: bool = False
    loginStatus: str = "disconnected"  # pending|scanned|confirmed|disconnected
    ilinkUserId: str | None = None
    ilinkBotId: str | None = None
    qrcode: str | None = None
    qrcodeImg: str | None = None


ConfigFileTreeNode.model_rebuild()
