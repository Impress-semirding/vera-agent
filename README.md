# Vera

Agent management platform — a React + FastAPI app for creating agents, chatting
with them over a streaming WebSocket, and managing skills / tools / permissions.

## Structure

```
vera/
├── frontend/   # React 18 + TypeScript + Vite + Ant Design + Zustand
└── backend/    # FastAPI + SQLite (async SQLAlchemy) + Pydantic + WebSocket chat
```

## Prerequisites

- Node.js 18+ with [pnpm](https://pnpm.io)
- Python 3.11+

## Backend

```bash
cd backend

# 1. 创建并激活虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -e .            # 仅运行时依赖
pip install -e ".[dev]"     # 运行时 + 开发依赖（pytest、ruff、mypy 等）

#    如果下载超时，使用国内镜像源：
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 启动服务
uvicorn api.main:app --host 127.0.0.1 --port 18080 --reload
```

**运行时依赖：** fastapi, uvicorn, pydantic, httpx, sse-starlette, sqlalchemy, aiosqlite, websockets, python-multipart 等。

**开发依赖（`[dev]`）：** pytest, pytest-asyncio, mypy, ruff。

- API base: `http://127.0.0.1:18080/api/v1` · docs: `http://127.0.0.1:18080/docs`
- First run creates `backend/reasonix.db` and seeds sample data + login users.
- Seeded login account: `admin` (password `123456`).

## Frontend

```bash
cd frontend
pnpm install
pnpm dev                  # http://127.0.0.1:3000
```

Vite proxies `/api` → `http://127.0.0.1:18080` (HTTP **and** WebSocket).

## Auth & permissions

- Login at `/login` (`POST /api/v1/auth/login` with name/email + password).
- Identity is carried via the `X-User` header (URL-encoded for non-ASCII names)
  and `?user=` on the chat WebSocket.
- Agent access = **owner** OR an explicit `Permission` row with `view`
  (`can_access_agent` in `backend/api/access.py`). The agent list and chat are
  both gated by this rule.

## Chat (streaming)

`ws /api/v1/chat/{agent_id}/{session_id}?user=<name>` validates the agent +
session (creating the session if missing), then streams
`model_delta` events (`channel: "reasoning" | "content"`) token-by-token,
finishing with `model_final`. The reply is currently **simulated** in
`backend/api/routers/chat.py` — swap `_handle_user_input` for a real LLM
stream and the frontend needs no changes.
