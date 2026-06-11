"""SQLAlchemy models — all entities the frontend needs."""

from datetime import datetime
from sqlalchemy import String, Text, Boolean, Integer, Float, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.database import Base


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # system | personal
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # claude | normal
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    visibility: Mapped[bool] = mapped_column(Boolean, default=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(100), default="anonymous")
    updated_by: Mapped[str] = mapped_column(String(100), default="anonymous")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("projects.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    reasoning_content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[str | None] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    command: Mapped[str | None] = mapped_column(String(500))
    args: Mapped[str | None] = mapped_column(Text)  # JSON array
    env: Mapped[str | None] = mapped_column(Text)  # JSON object
    transport: Mapped[str] = mapped_column(String(20), default="stdio")
    url: Mapped[str | None] = mapped_column(String(500))
    headers: Mapped[str | None] = mapped_column(Text)  # JSON
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class McpTool(Base):
    __tablename__ = "mcp_tools"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mcp_server_id: Mapped[str] = mapped_column(String(64), ForeignKey("mcp_servers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[str | None] = mapped_column(Text)  # JSON Schema
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Skill(Base):
    __tablename__ = "skills"
    # Same skill name may exist on different agents, but not twice on one agent.
    __table_args__ = (UniqueConstraint("agent_id", "name", name="uq_skill_agent_name"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(20), default="project")
    path: Mapped[str] = mapped_column(String(500), default="")
    allowed_tools: Mapped[str | None] = mapped_column(Text)  # JSON array
    run_as: Mapped[str] = mapped_column(String(20), default="inline")
    model: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(100), default="anonymous")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Uploaded skill package (.zip) saved to ``skills/`` directory on disk.
    # ``file_path`` stores the relative path (e.g. ``skills/{id}.zip``).
    # ``body`` holds the extracted SKILL.md text.
    file_path: Mapped[str | None] = mapped_column(String(500))
    filename: Mapped[str | None] = mapped_column(String(500))


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    user_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_email: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    agent_permissions: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    auth_permissions: Mapped[str] = mapped_column(Text, default="[]")  # JSON array


class User(Base):
    """A login identity. Passwords are pbkdf2-hashed (see api.util)."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    salt: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class PushTask(Base):
    __tablename__ = "push_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    form_style: Mapped[str] = mapped_column(String(10), default="msg")
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON blob for all type-specific fields
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WeComConfig(Base):
    __tablename__ = "wecom_configs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_id: Mapped[str | None] = mapped_column(String(200))
    bot_key: Mapped[str | None] = mapped_column(String(200))
    show_thinking: Mapped[bool] = mapped_column(Boolean, default=False)


class WeComBinding(Base):
    __tablename__ = "wecom_bindings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wecom_config_id: Mapped[str] = mapped_column(String(64), ForeignKey("wecom_configs.id"), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))


class SessionSetting(Base):
    __tablename__ = "session_settings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False, unique=True)
    allow_upload: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_effort: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_context: Mapped[bool] = mapped_column(Boolean, default=True)


class ConfigFile(Base):
    __tablename__ = "config_files"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExecRecord(Base):
    __tablename__ = "exec_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    session_source: Mapped[str | None] = mapped_column(String(200))
    session_id: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="success")
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ModifyRecord(Base):
    __tablename__ = "modify_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), nullable=False)
    operator: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ModelConfig(Base):
    """LLM model provider configuration — stores baseUrl + apiKey per provider."""
    __tablename__ = "model_configs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # deepseek | glm | minimax | qianwen
    name: Mapped[str] = mapped_column(String(200), nullable=False)     # display name
    model_id: Mapped[str] = mapped_column(String(100), nullable=False) # model identifier for API calls
    base_url: Mapped[str] = mapped_column(String(500), nullable=False) # Anthropic-compatible base URL
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)  # API key
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
