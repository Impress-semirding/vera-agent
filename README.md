# fast-agent

Agent management platform — a React + FastAPI app for creating agents, chatting
with them over a streaming WebSocket, and managing skills / tools / permissions.

## Structure

```
fast-agent/
├── frontend/   # React 18 + TypeScript + Vite + Ant Design + Zustand
└── backend/    # FastAPI + SQLite (async SQLAlchemy) + Pydantic + WebSocket chat
```

## Prerequisites

- Node.js 18+ with [pnpm](https://pnpm.io)
- Python 3.11+

## Backend

```bash
cd backend
pip install -e .          # fastapi, uvicorn, sqlalchemy, aiosqlite, websockets, ...
uvicorn api.main:app --host 127.0.0.1 --port 18080 --reload
```

- API base: `http://127.0.0.1:18080/api/v1` · docs: `http://127.0.0.1:18080/docs`
- First run creates `backend/reasonix.db` and seeds sample data + login users.
- Seeded login accounts (password `123456`): `王聪` / `鲁婉婉` / `张三` / `赵六`.

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
