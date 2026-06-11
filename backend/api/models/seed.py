"""Seed database with sample data for development."""

import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from api.models.models import (
    Agent, Session, SessionSetting, McpServer, McpTool,
    Skill, Permission, PushTask, WeComConfig, WeComBinding,
    ExecRecord, ModifyRecord, ConfigFile, User,
)
from api.util import hash_password

now = datetime.now(timezone.utc).isoformat()

# Dev login accounts (name / email → password "123456"). Seeded independently
# of the agents guard below so an already-seeded DB still gets loginable users.
_SEED_USERS = [
    ("王聪", "wangcong002@zhongan.com"),
    ("鲁婉婉", "luwanwan@zhongan.com"),
    ("张三", "zhangsan@zhongan.com"),
    ("赵六", "zhaoliu@zhongan.com"),
]


async def seed(db: AsyncSession) -> None:
    from sqlalchemy import select

    # ── Users (independent guard: runs even if agents already seeded) ──
    has_user = (await db.execute(select(User))).scalars().first()
    if has_user is None:
        for name, email in _SEED_USERS:
            pw_hash, salt = hash_password("123456")
            db.add(User(id=uuid.uuid4().hex, name=name, email=email, password_hash=pw_hash, salt=salt))
        await db.commit()

    # Check if agents already seeded
    existing = (await db.execute(select(Agent))).scalars().first()
    if existing:
        return

    agents = [
        Agent(id="agent-001", name="VOC示例_副本", description="VOC数据分析智能体，支持周报生成和数据查询",
              type="system", mode="claude", model="glm-5-1", starred=False,
              created_by="王聪", updated_by="王聪"),
        Agent(id="agent-002", name="测试语雀", description="语雀文档同步智能体",
              type="personal", mode="claude", model="claude-3-opus", starred=True,
              created_by="鲁婉婉", updated_by="鲁婉婉"),
        Agent(id="agent-003", name="数据简报助手", description="自动生成每日数据简报推送到企微",
              type="system", mode="normal", model="glm-5-1", starred=False,
              created_by="张三", updated_by="李四"),
        Agent(id="agent-004", name="代码审查专家", description="基于 Reasonix 技能系统的代码审查智能体",
              type="personal", mode="claude", model="deepseek-v4-pro", starred=False,
              created_by="赵六", updated_by="赵六"),
        # A PRIVATE agent (visibility=False) so the "no permission → 403" path
        # is testable: 赵六 owns it, 王聪 is granted view, everyone else blocked.
        Agent(id="agent-005", name="私有演示虾", description="私有智能体（仅授权可见）",
              type="personal", mode="claude", model="glm-5-1", starred=False,
              visibility=False, created_by="赵六", updated_by="赵六"),
    ]
    db.add_all(agents)

    # Sessions
    sessions = [
        Session(id="s1", agent_id="agent-001", name="会话 1"),
        Session(id="s2", agent_id="agent-001", name="会话 2"),
        Session(id="s3", agent_id="agent-001", name="VOC周报分析"),
        Session(id="s4", agent_id="agent-002", name="会话 1"),
    ]
    db.add_all(sessions)

    # Session settings
    settings = [
        SessionSetting(id="ss-1", agent_id="agent-001", allow_upload=True, allow_effort=True, allow_context=True),
        SessionSetting(id="ss-2", agent_id="agent-002", allow_upload=False, allow_effort=False, allow_context=False),
    ]
    db.add_all(settings)

    # MCP Servers + Tools
    mcp1 = McpServer(id="mcp-1", agent_id="agent-001", name="飞书 MCP", transport="stdio", disabled=False)
    mcp2 = McpServer(id="mcp-2", agent_id="agent-001", name="集智数据集查数", transport="stdio", disabled=True)
    db.add_all([mcp1, mcp2])

    tools = [
        McpTool(id="t-1", mcp_server_id="mcp-1", name="Ask User Question", description="用于向用户提问并获取反馈的工具", enabled=True),
        McpTool(id="t-2", mcp_server_id="mcp-1", name="Feishu: Chat Management", description="管理飞书群组和消息的工具", enabled=True),
        McpTool(id="t-3", mcp_server_id="mcp-2", name="jizhi_query_v2", description="基于集智数据集拼接查询参数并生成统计结果", enabled=False),
    ]
    db.add_all(tools)

    # Skills
    skills = [
        Skill(id="sk-1", agent_id="agent-001", name="VOC周报生成器", description="自动生成VOC周报",
              scope="project", run_as="subagent", version="1.2.0", enabled=True, updated_by="wangcong002"),
        Skill(id="sk-2", agent_id="agent-004", name="code-review", description="代码审查技能",
              scope="global", run_as="subagent", model="deepseek-v4-pro", version="1.0.0", enabled=True, updated_by="赵六"),
    ]
    db.add_all(skills)

    # Permissions
    perms = [
        Permission(id="p-1", agent_id="agent-001", user_name="鲁婉婉", user_email="luwanwan@zhongan.com",
                   agent_permissions='["view","update"]', auth_permissions='["view"]'),
        Permission(id="p-2", agent_id="agent-001", user_name="王聪", user_email="wangcong002@zhongan.com",
                   agent_permissions='["view","update","delete"]', auth_permissions='["view","update"]'),
        Permission(id="p-3", agent_id="agent-005", user_name="王聪", user_email="wangcong002@zhongan.com",
                   agent_permissions='["view"]', auth_permissions='["view"]'),
    ]
    db.add_all(perms)

    # Push tasks
    push = PushTask(id="pt-1", agent_id="agent-001", name="VOC周报推送", type="webhook-group",
                    status="active", enabled=True, form_style="msg",
                    config='{"target":"客服 VOC 反馈群","cron":"每周一 10:00","lastPush":"2026-05-19 10:05"}')
    db.add(push)

    # WeCom config + bindings
    wecom = WeComConfig(id="wc-1", agent_id="agent-001", enabled=True,
                        bot_id="aibkHGed147nfCXOBGrmUS-pvCaO155N4N_",
                        bot_key="DcBFECtxWgmS7XQ5BkjMrvWLycZfGxzjdPYnyayR77U",
                        show_thinking=True)
    db.add(wecom)
    binding = WeComBinding(id="wb-1", wecom_config_id="wc-1",
                           chat_id="wr3JFUoAeAQwQXJFUaoGEw", description="用于收集客户VOC反馈的工作群")
    db.add(binding)

    # Config files (personal agent)
    configs = [
        ConfigFile(id="cf-1", agent_id="agent-002", path="CLAUDE.md",
                   content="# CLAUDE.md\n你是一个专业的业务智能助手...\n"),
        ConfigFile(id="cf-2", agent_id="agent-002", path="settings.json",
                   content='{\n  "preset": "auto",\n  "editMode": "auto"\n}'),
        ConfigFile(id="cf-3", agent_id="agent-002", path="commands/weekly-report.md",
                   content="# weekly-report skill\n生成每周VOC周报"),
        ConfigFile(id="cf-4", agent_id="agent-002", path="hooks/post-push.sh",
                   content='#!/bin/bash\necho "post-push hook"'),
        ConfigFile(id="cf-5", agent_id="agent-002", path="memory/user.md",
                   content="# User preferences\n- 输出中文"),
    ]
    db.add_all(configs)

    # History records
    execs = [
        ExecRecord(id="er-1", agent_id="agent-001", session_source="企微机器人",
                   session_id="msg_001_20260522", user_id="wangcong002",
                   status="success", content="用户提问：生成上周VOC反馈周报。"),
    ]
    db.add_all(execs)

    modifies = [
        ModifyRecord(id="mr-1", agent_id="agent-001", operator="wangcong002",
                     action="修改了基础配置", detail="更新了 CLAUDE.md 内容"),
        ModifyRecord(id="mr-2", agent_id="agent-001", operator="wangcong002",
                     action="创建了智能体", detail="创建新智能体"),
    ]
    db.add_all(modifies)

    await db.commit()
