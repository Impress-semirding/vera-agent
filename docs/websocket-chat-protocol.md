# WebSocket Chat 协议文档

> 版本: 1.0  
> 最后更新: 2026-06-13  
> 端点: `ws /api/v1/chat/{agent_id}/{session_id}?user=<x>`

---

## 概述

所有帧为 JSON 文本帧，每帧一个 JSON 对象，通过 `type` 字段区分。

### 设计原则

- **turnId**: 每个 turn（一轮用户消息 → 完整回复）有唯一 `turnId`，前端按此路由流式 delta 到正确的消息气泡
- **Segment 模型**: 一条 assistant 消息由多个 segment 组成（reasoning / text / tool），前端按 segment 渲染不同卡片
- **向后兼容**: 新增字段不破坏旧客户端，前端通过 `segments` 是否存在决定渲染模式

---

## 一、Client → Server 帧

| type | 字段 | 说明 |
|------|------|------|
| `user_input` | `{ type, text }` | 用户发送消息 |
| `abort` | `{ type }` | 中止当前 turn（保留队列中的后续消息） |
| `pong` | `{ type }` | 心跳响应 |

### 示例

```json
{ "type": "user_input", "text": "帮我分析一下这个项目" }
{ "type": "abort" }
{ "type": "pong" }
```

---

## 二、Server → Client 帧

### 2.1 连接生命周期事件

#### `ready`

连接建立成功。

```json
{
  "type": "ready",
  "sessionId": "sess_abc123",
  "agentName": "项目助手"
}
```

#### `session`

新会话创建（首次发消息时触发）。

```json
{
  "type": "session",
  "sessionId": "sess_abc123",
  "created": true
}
```

#### `ping`

心跳探测，客户端应回复 `pong`。

```json
{ "type": "ping" }
```

#### `error`

全局错误，连接可能随后关闭。

```json
{
  "type": "error",
  "message": "连接异常: ...",
  "turnId": "turn_xyz"          // 可选，关联到具体 turn
}
```

---

### 2.2 Turn 生命周期事件

#### `turn_start`

Worker 从队列取出一条消息开始处理。前端应预创建一条 pending 的 assistant 消息。

```json
{
  "type": "turn_start",
  "text": "帮我分析一下这个项目",
  "turnId": "turn_abc123"
}
```

**前端行为**: 创建 `{ role: "assistant", pending: true, turnId, segments: [] }`

#### `model_delta` ⭐ 核心流式事件

LLM 输出的增量文本。通过 `channel` 区分内容类型。

```json
{
  "type": "model_delta",
  "turnId": "turn_abc123",
  "channel": "content" | "reasoning" | "tool_args",
  "text": "一段增量文本"
}
```

| channel | 含义 | 前端处理 |
|---------|------|---------|
| `content` | 正式回复文本 | 追加到 text segment，同时更新 `msg.content` |
| `reasoning` | 思考/推理过程 | 追加到 reasoning segment（在 ThinkingBlock 内），同时更新 `msg.reasoning` |
| `tool_args` | 工具参数流式解析 | 追加到最后一个未完成 tool segment 的 `args` |

**前端行为**: 
- `channel === "content"` → 追加到最后一个 text segment（或新建）
- `channel === "reasoning"` → 追加到最后一个 reasoning segment（或新建）
- `channel === "tool_args"` → 追加到最后一个 `done: false` 的 tool segment

#### `tool.preparing`

工具名已解析，参数正在流式传入。前端创建新的 tool segment。

```json
{
  "type": "tool.preparing",
  "turnId": "turn_abc123",
  "callId": "call_search_1",
  "name": "search_files"
}
```

**前端行为**: 向 segments 追加 `{ kind: "tool", callId, name, args: "", done: false }`

#### `tool.intent`

工具参数完整，准备执行。前端更新对应 tool segment 的完整 args。

```json
{
  "type": "tool.intent",
  "turnId": "turn_abc123",
  "callId": "call_search_1",
  "name": "search_files",
  "args": "{\"query\": \"vera-agent\", \"max_results\": 5}"
}
```

**前端行为**: 找到 `callId` 匹配的 tool segment，填入完整 `name` 和 `args`

#### `tool.result`

工具执行完成。前端填入结果，标记 done。

```json
{
  "type": "tool.result",
  "turnId": "turn_abc123",
  "callId": "call_search_1",
  "ok": true,
  "output": "Found 3 files:\n1. backend/api/routers/chat.py\n..."
```

**前端行为**: 找到 `callId` 匹配的 tool segment，设 `output`, `ok`, `done: true`

#### `model_final`

Turn 结束。包含完整的回复内容。前端标记 `pending: false`。

```json
{
  "type": "model_final",
  "turnId": "turn_abc123",
  "content": "根据分析，这个项目是...",
  "reasoningContent": "让我分析一下..."
}
```

**前端行为**: 
- 用 `content` / `reasoningContent` 更新 flat 字段（兼容旧渲染）
- 设 `pending: false`
- 设 `streaming: false`

#### `stopped`

当前 turn 被中止（abort）。队列中可能还有后续消息。

```json
{ "type": "stopped" }
```

---

## 三、典型事件序列

### 3.1 简单对话（无工具调用）

```
→ user_input: "你好"
← turn_start                    {turnId: "t1"}
← model_delta × N               {channel: "content", turnId: "t1"}
← model_final                   {turnId: "t1"}
```

### 3.2 带推理的对话（DeepSeek / Claude thinking）

```
→ user_input: "分析一下这段代码"
← turn_start                    {turnId: "t1"}
← model_delta × N               {channel: "reasoning"}     ← 思考过程
← model_delta × M               {channel: "content"}       ← 正式回复
← model_final                   {turnId: "t1"}
```

### 3.3 完整 Agent 循环（思考 → 多次工具调用 → 回复）

```
→ user_input: "帮我重构这个模块"
← turn_start                    {turnId: "t1"}

# 第一次推理
← model_delta × N               {channel: "reasoning"}     ← "让我先搜索相关文件..."
# 第一次工具调用
← tool.preparing                {callId: "c1", name: "search_files"}
← model_delta × K               {channel: "tool_args"}     ← 参数流式解析
← tool.intent                   {callId: "c1", args: "..."}
← tool.result                   {callId: "c1", ok: true, output: "..."}

# 继续推理
← model_delta × N               {channel: "reasoning"}     ← "找到了几个文件，让我看看..."

# 第二次工具调用
← tool.preparing                {callId: "c2", name: "read_file"}
← model_delta × K               {channel: "tool_args"}
← tool.intent                   {callId: "c2", args: "..."}
← tool.result                   {callId: "c2", ok: true, output: "..."}

# 第三次工具调用（失败）
← model_delta × N               {channel: "reasoning"}     ← "检查配置..."
← tool.preparing                {callId: "c3", name: "check_config"}
← tool.intent                   {callId: "c3", args: "..."}
← tool.result                   {callId: "c3", ok: false, output: "Error: ..."}

# 最终回复
← model_delta × M               {channel: "content"}       ← 正式回复文本
← model_final                   {turnId: "t1"}
```

### 3.4 连续发消息（队列模式）

```
→ user_input: "消息A"
→ user_input: "消息B"

# A 的处理
← turn_start                    {turnId: "t1"}
← model_delta ...               {turnId: "t1"}
← model_final                   {turnId: "t1"}

# B 的处理（A 完成后自动开始）
← turn_start                    {turnId: "t2"}
← model_delta ...               {turnId: "t2"}
← model_final                   {turnId: "t2"}
```

---

## 四、前端数据模型

### ChatMsg

```typescript
interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;            // 纯文本内容（兼容旧消息）
  reasoning?: string;         // 思考过程（兼容旧消息）
  pending?: boolean;          // 是否正在流式推送
  turnId?: string;            // 关联 turn
  timestamp?: string;         // ISO-8601 UTC
  segments?: Segment[];       // 结构化分段（新版）
}
```

### Segment 联合类型

```typescript
type Segment =
  | { kind: 'reasoning'; text: string }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; callId: string; name: string; args: string; output?: string; ok?: boolean; done: boolean }
```

### Segment 渲染规则

| 条件 | 渲染模式 |
|------|---------|
| `segments` 存在且非空 | 按 segment 渲染 |
| `segments` 不存在（旧消息） | 用 `content` / `reasoning` flat 字段渲染 |

连续的 reasoning + tool segments 合并到一个 **ThinkingBlock**（统一折叠区域）：
```
[reasoning] [tool] [tool] [reasoning] [tool] → 一个 ThinkingBlock
[text] [text]                               → 独立的 TextSegment 气泡
```

---

## 五、适配器开发指南

任何后端（Agent / Claude CLI / 自研 LLM 管道）只需将内部事件转化为上述协议帧推送到 WebSocket。

### 5.1 从 Claude CLI 适配

```
Claude CLI SSE event              →  WebSocket 帧
─────────────────────────────────────────────────
content_block_start(type:text)    →  (无需映射，等待 delta)
content_block_delta(text_delta)   →  model_delta {channel: "content"}
content_block_delta(thinking)     →  model_delta {channel: "reasoning"}
content_block_start(type:tool)    →  tool.preparing {callId, name}
input_json_delta                  →  model_delta {channel: "tool_args"}
content_block_stop(tool)          →  tool.intent {callId, args}
tool_result                       →  tool.result {callId, ok, output}
message_stop                      →  model_final
```

### 5.2 从 OpenAI 兼容 API 适配

```
OpenAI SSE chunk                  →  WebSocket 帧
─────────────────────────────────────────────────
choices[0].delta.content          →  model_delta {channel: "content"}
choices[0].delta.reasoning        →  model_delta {channel: "reasoning"}
choices[0].delta.tool_calls[i]    →  tool.preparing + model_delta {channel: "tool_args"}
finish_reason: "tool_calls"       →  tool.intent × N
(执行工具后继续 stream)            →  tool.result × N → model_delta(content) → model_final
finish_reason: "stop"             →  model_final
```

### 5.3 从 Reasonix NDJSON 适配

```
Reasonix Kernel Event             →  WebSocket 帧
──────────────────────────────────────────────────
model.delta(channel: content)     →  model_delta {channel: "content"}
model.delta(channel: reasoning)   →  model_delta {channel: "reasoning"}
model.delta(channel: tool_args)   →  model_delta {channel: "tool_args"}
tool.preparing                    →  tool.preparing
tool.intent                       →  tool.intent
tool.result                       →  tool.result
model.final                       →  model_final
```

### 5.4 适配器模板（Python）

```python
class ProtocolAdapter:
    """将任意 LLM 后端事件转为 WebSocket 协议帧。"""

    def __init__(self, turn_id: str, push_fn):
        self.turn_id = turn_id
        self.push = push_fn  # async def push(frame: dict)

    async def turn_start(self, text: str):
        await self.push({"type": "turn_start", "text": text, "turnId": self.turn_id})

    async def reasoning_delta(self, text: str):
        await self.push({"type": "model_delta", "channel": "reasoning", "text": text, "turnId": self.turn_id})

    async def content_delta(self, text: str):
        await self.push({"type": "model_delta", "channel": "content", "text": text, "turnId": self.turn_id})

    async def tool_preparing(self, call_id: str, name: str):
        await self.push({"type": "tool.preparing", "callId": call_id, "name": name, "turnId": self.turn_id})

    async def tool_args_delta(self, text: str):
        await self.push({"type": "model_delta", "channel": "tool_args", "text": text, "turnId": self.turn_id})

    async def tool_intent(self, call_id: str, name: str, args: str):
        await self.push({"type": "tool.intent", "callId": call_id, "name": name, "args": args, "turnId": self.turn_id})

    async def tool_result(self, call_id: str, ok: bool, output: str):
        await self.push({"type": "tool.result", "callId": call_id, "ok": ok, "output": output, "turnId": self.turn_id})

    async def model_final(self, content: str, reasoning_content: str = ""):
        await self.push({"type": "model_final", "content": content, "reasoningContent": reasoning_content, "turnId": self.turn_id})
```

---

## 六、变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-06-13 | 初始协议：turnId, tool.preparing/intent/result, channel 新增 tool_args |
