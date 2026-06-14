# Vera — 智能 Agent 构建与编排平台

高度可扩展的智能 Agent 构建与编排平台，打破单一 AI 工具的边界。通过深度集成官方 Claude Agent SDK 与灵活的自建 Agent 架构，为开发者提供从"开箱即用"到"深度定制"的完整解决方案。

## demo
![alt text](image.png)

![alt text](image-1.png)

## ✨ 核心特性

- **双引擎驱动架构** — 原生支持 Claude Agent SDK，一键接入代码理解、文件读写与命令执行能力；同时提供自建 Agent 接口，允许通过 MCP 协议或自定义 Python/Node.js 脚本扩展专属工具链。
- **渐进式技能加载 (Skills System)** — 内置标准化的 Skill 规范，复杂工作流封装为可复用的技能包。Agent 按需加载指令，节省 Token 消耗并提升响应精准度。
- **企业级安全与权限管控** — 细粒度的权限模式（只读、自动批准编辑、拦截确认），结合 Hook 机制在工具调用前后进行安全审计。
- **多智能体协同编排** — 支持定义多个专属 Sub-Agent（代码审查员、安全扫描器、文档生成器），通过上下文隔离实现任务分发与并行处理。
- **流式思考过程展示** — 实时渲染 Agent 的推理步骤、工具调用和中间结果，支持折叠/展开和持久化存储。

## 架构

```
前端 (React)
  ↓ WebSocket
API 层 (FastAPI)
  ↓ AgentAdapter
agent_runtime/
├── claude/      → Claude Agent SDK (direct, 无 pipes, 无死锁)
└── normal/      → 裸 LLM HTTP API
```

## 目录结构

```
vera-agent/
├── frontend/   # React 18 + TypeScript + Vite + Ant Design + Zustand
├── backend/
│   ├── api/           # FastAPI 路由 + WebSocket
│   ├── agent_runtime/ # Agent 运行时 (claude/normal 双引擎)
│   └── data/          # SQLite DB + workspaces
└── docs/              # 协议文档
```

## 快速开始

### 环境要求

- Node.js 18+ with [pnpm](https://pnpm.io)
- Python 3.11+

### 后端

```bash
cd backend

# 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 基础安装
pip install -e .

# Claude 模式需要额外安装 SDK
pip install claude-agent-sdk
```

#### Docker 安装

```bash
# macOS
brew install --cask docker

# Linux
curl -fsSL https://get.docker.com | sh
```

#### 本地子进程模式（无需 Docker）

```bash
AGENT_USE_DOCKER=0 uvicorn api.main:app --host 127.0.0.1 --port 18080 --reload
```

#### Docker 隔离模式（推荐生产环境）

首次启动自动构建镜像，之后复用。

```bash
AGENT_USE_DOCKER=1 uvicorn api.main:app --host 127.0.0.1 --port 18080 --reload
```

配置项：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AGENT_USE_DOCKER` | `1` | `1`=Docker 容器隔离，`0`=本地子进程 |
| `AGENT_MAX_CONTAINERS` | `5` | 最大并发容器数 |
| `AGENT_IDLE_TIMEOUT` | `1800` | 容器空闲超时秒数（默认 30 分钟） |
| `AGENT_WORKSPACE_BASE` | 项目 `data/workspaces/` | Agent 工作区根目录 |

- API: `http://127.0.0.1:18080/api/v1` · Docs: `http://127.0.0.1:18080/docs`
- 首次运行自动创建 SQLite 数据库并初始化种子数据
- 默认登录账号: `admin`，密码: `123456`
- 如需新增用户，编辑 `backend/api/models/seed.py` 中的 `_SEED_USERS` 和 `_SEED_USER_PASSWORDS` 后重启即可
- 登录接口: `POST /api/v1/auth/login`，body `{"identifier": "admin", "password": "123456"}`，返回用户信息，后续请求通过 `X-User` header 携带身份

### 前端

```bash
cd frontend
pnpm install
pnpm dev    # http://127.0.0.1:3000
```

## Agent 模式

| 模式 | 引擎 | 适用场景 |
|------|------|---------|
| `claude` | Claude Agent SDK | 工具调用、代码编写、文件操作 |
| `normal` | 自建 LLM HTTP | DeepSeek/GLM 等 Anthropic 协议兼容模型 |

## 协议

前端通过 WebSocket 接收结构化事件流，详见 [协议文档](docs/websocket-chat-protocol.md)。支持推理步骤、工具调用、中间草稿和最终回复的实时渲染。
