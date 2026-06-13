# WebSocket Chat 协议文档

> 版本: 2.0  
> 最后更新: 2026-06-13  
> 端点: `ws /api/v1/chat/{agent_id}/{session_id}?user=<x>`

---

## 概述

所有帧为 JSON 文本帧，通过 `type` 字段区分。

### 设计原则

- **turnId**: 每轮有唯一 ID，前端按此路由 delta 到正确消息气泡
- **Segment 模型**: assistant 消息由 segments[] 数组组成，前端按序渲染卡片
- **语义分层**: 推理/中间输出 → ThinkingBlock（可折叠）；最终答案 → 独立 TextSegment（始终可见）
- **持久化**: segments[] 完整序列化到 DB，刷新页面不丢失

---

## 一、Client → Server

| type | 字段 | 说明 |
|------|------|------|
| `user_input` | `{type, text}` | 用户消息 |
| `abort` | `{type}` | 中止当前 turn |
| `pong` | `{type}` | 心跳响应 |

---

## 二、Server → Client 事件类型总览

### 生命周期

| type | 说明 |
|------|------|
| `ready` | 连接就绪 |
| `session` | 会话创建 |
| `ping` | 心跳 |
| `error` | 错误 |
| `stopped` | turn 中止 |

### Turn 流式事件（⭐ 核心）

| type | 语义 | 前端位置 |
|------|------|---------|
| `turn_start` | turn 开始 | 创建消息壳子 |
| `model_delta(reasoning)` | 推理/思考 | ThinkingBlock 内 · 🧠 推理 |
| `model_delta(content)` | 中间草稿 | ThinkingBlock 内 · 📝 回复草稿 |
| `model_delta(tool_args)` | 工具参数流式 | ThinkingBlock 内 · 追加到 tool segment |
| `tool.preparing` | 工具准备 | ThinkingBlock 内 · 新卡片 |
| `tool.intent` | 参数就绪 | 更新卡片 args |
| `tool.result` | 执行结果 | 更新卡片 output/done |
| `model_final` | 最终答案 | ThinkingBlock 外 · 始终可见 |

### 其他

| type | 说明 |
|------|------|
| `artifacts` | 工作区文件列表 |

---

## 三、事件详解

### `turn_start`

```json
{"type":"turn_start","text":"用户消息原文","turnId":"turn_abc"}
```
前端预创建 `{role:"assistant", pending:true, turnId, segments:[]}`。

### `model_delta`

```json
{"type":"model_delta","channel":"reasoning"|"content"|"tool_args","text":"增量","turnId":"..."}
```

| channel | 前端 label | 渲染 |
|---------|-----------|------|
| `reasoning` | 🧠 推理（紫色） | 新建 reasoning segment，永不合并 |
| `content` | 📝 回复草稿（黄色） | 同上，但标记 `source:'content'` |
| `tool_args` | — | 追加到最后一个未完成 tool segment |

### `tool.preparing`

```json
{"type":"tool.preparing","callId":"c1","name":"read_file","turnId":"..."}
```
前端创建 tool segment：`{kind:'tool', callId, name, args:'', done:false}`。

### `tool.intent`

```json
{"type":"tool.intent","callId":"c1","name":"read_file","args":"{\"path\":\"a.py\"}","turnId":"..."}
```
前端按 callId 填入完整 `name` 和 `args`。

### `tool.result`

```json
{"type":"tool.result","callId":"c1","ok":true,"output":"文件内容...","turnId":"..."}
```
前端设 `done:true`, `ok`, `output`。

### `model_final`

```json
{"type":"model_final","content":"最终回复正文","reasoningContent":"","turnId":"..."}
```
前端设 `pending:false`，追加 text segment 到 segments 末尾（ThinkingBlock 外，始终可见）。

### `artifacts`

```json
{"type":"artifacts","turnId":"...","files":[{"name":"ddl.sql","path":"ddl.sql","size":2048}]}
```
前端更新文件列表，显示在右侧"文件"Tab。

---

## 四、前端 Segment 模型

```typescript
type Segment =
  | { kind: 'reasoning'; text: string; source?: 'reasoning' | 'content' }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; callId: string; name: string; args: string; output?: string; ok?: boolean; done: boolean }
```

### 渲染规则

```
segments: [reasoning] [tool] [reasoning(content)] [tool] [reasoning] → ThinkingBlock
segments: [text]                                                     → 独立气泡（最终答案）

▼ 思考过程 · N 次工具调用           ← 整体可折叠
  ▶ 🧠 推理                         ← 各自可折叠
  ▶ 🔧 工具名                       ← 各自可折叠
  ▶ 📝 回复草稿                     ← 各自可折叠

  最终答案内容...                    ← 不可折叠，始终可见
```

### 持久化

segments 完整 JSON 存入 `Message.tool_calls` 列。API `GET /sessions/{id}/messages` 返回 `segments` 字段，前端加载后直接使用。

---

## 五、典型事件序列

### 5.1 简单对话

```
turn_start {t1}
model_delta × N {channel:content}        ← 直接当推理进 ThinkingBlock
model_final {content:"你好！"}           ← 创建可见气泡
```

### 5.2 带工具调用的 Agent 循环

```
turn_start {t1}
model_delta × N {channel:reasoning}      ← 🧠 "让我先搜索..."
tool.preparing {c1, name:search}
tool.intent {c1, args:{...}}
tool.result {c1, ok:true, output:"..."}
model_delta × N {channel:reasoning}      ← 🧠 "找到了，继续分析..."
model_delta × M {channel:content}        ← 📝 中间输出
tool.preparing {c2, name:read}
tool.intent {c2, args:{...}}
tool.result {c2, ok:true, output:"..."}
model_delta × N {channel:content}        ← 📝 最终草稿
model_final {content:"完整答案..."}       ← 创建可见气泡
artifacts {files:[...]}                  ← 文件列表
```

### 5.3 连续消息（队列模式）

```
→ user_input "A"
← turn_start {t1} → ... → model_final {t1}
→ user_input "B"
← turn_start {t2} → ... → model_final {t2}
```

---

## 六、适配器开发

### 自研 Agent 对接步骤

1. Agent 子进程 stdout 输出协议事件（每行一个 JSON）
2. 实现 `AgentClient` 协议（send / read_deltas / close / is_alive）
3. 继承 `AgentAdapter` 覆写 `_create_client()`
4. 在 `registry.py` 注册 `register_backend("custom", factory)`

### 适配器模板

```python
class ProtocolEmitter:
    """将 agent 内部事件转为协议帧推到 WebSocket。"""
    def __init__(self, turn_id, push): self.tid = turn_id; self.push = push

    async def reasoning(self, text):   await self.push({"type":"model_delta","channel":"reasoning","text":text,"turnId":self.tid})
    async def draft(self, text):       await self.push({"type":"model_delta","channel":"content","text":text,"turnId":self.tid})
    async def tool_preparing(self, cid, name):  await self.push({"type":"tool.preparing","callId":cid,"name":name,"turnId":self.tid})
    async def tool_intent(self, cid, name, args): await self.push({"type":"tool.intent","callId":cid,"name":name,"args":args,"turnId":self.tid})
    async def tool_result(self, cid, ok, output): await self.push({"type":"tool.result","callId":cid,"ok":ok,"output":output,"turnId":self.tid})
    async def final(self, content):    await self.push({"type":"model_final","content":content,"turnId":self.tid})
```

### 从 Anthropic SSE 适配

```
content_block_start(tool_use)       → tool.preparing {callId, name}
content_block_delta(thinking_delta) → model_delta {channel:reasoning}
content_block_delta(text_delta)     → model_delta {channel:content}
content_block_delta(input_json)     → model_delta {channel:tool_args}
content_block_stop                  → tool.intent {callId, args}
tool_result                         → tool.result {callId, ok, output}
message_stop                        → model_final
```

### 从 OpenAI 兼容 API 适配

```
delta.content        → model_delta {channel:content}
delta.reasoning      → model_delta {channel:reasoning}
delta.tool_calls[i]  → tool.preparing + model_delta {tool_args}
finish_reason:tool   → tool.intent × N
finish_reason:stop   → model_final
```

---

## 七、REST 端点（配套）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/sessions/{id}/messages` | 获取历史消息（含 segments） |
| `DELETE` | `/sessions/{id}/messages` | 清空会话消息 |
| `GET` | `/files/{id}` | 列出生成功文件 |
| `GET` | `/files/{id}/download?path=...` | 下载文件 |

---

## 八、变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.0 | 2026-06-13 | model_delta(content) 改为中间草稿语义；model_final 创建可见气泡；segments 持久化；artifacts 事件；各段默认折叠 |
| 1.0 | 2026-06-13 | 初始协议 |
