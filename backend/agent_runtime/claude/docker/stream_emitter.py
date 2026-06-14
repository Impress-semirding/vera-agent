"""Stream emitter — unified stdout writer for agent backends.

All agent backends (Claude, custom, ...) write through this layer.
It ensures no single stdout line exceeds the OS pipe buffer by:
- Splitting large text deltas into ≤ 2000-char chunks with 50ms gaps
- Truncating tool results to 400 chars (full version → events.jsonl)
- A global 60KB safety net on any single line
"""

from __future__ import annotations

import json
import os
import sys
import time

CHUNK_SIZE = 2000
CHUNK_DELAY = 0.05  # 50ms between chunks for visible streaming effect
TOOL_RESULT_MAX = 400
_MAX_LINE = 60000  # global safety net (OS pipe buffer is ~64KB)

# Debug log file path — set by StreamEmitter.__init__
_debug_log: str | None = None


def _write(obj: dict) -> None:
    """Write one JSON line to stdout (flush immediately). Also log to debug file."""
    line = json.dumps(obj, ensure_ascii=False)
    if len(line) > _MAX_LINE:
        for key in ("output", "content", "text", "args"):
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 500:
                obj = {**obj, key: obj[key][:500] + "...(global truncation)"}
        line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    # Mirror to debug log with timestamp
    if _debug_log:
        try:
            ts = time.strftime("%H:%M:%S.", time.localtime()) + f"{time.time() % 1:.3f}"[2:]
            t = obj.get("type", "?")
            size = len(line)
            with open(_debug_log, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] type={t} size={size} {line[:200]}\n")
        except Exception:
            pass


def _append_event_log(cwd: str, call_id: str, data: dict) -> None:
    """Append a full tool result to output/events.jsonl for debugging."""
    try:
        log_path = os.path.join(cwd, "output", "events.jsonl")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        entry = json.dumps({"callId": call_id, **data}, ensure_ascii=False)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


class StreamEmitter:
    """Unified stdout writer with chunking, truncation, and event logging."""

    def __init__(self, cwd: str = "/tmp") -> None:
        self.cwd = cwd
        self._step = 0
        global _debug_log
        _debug_log = os.path.join(cwd, "output", "_stream_debug.log")
        os.makedirs(os.path.dirname(_debug_log), exist_ok=True)

    def next_step(self) -> None:
        """Start a new thinking step. Call before emitting deltas for a new SDK message."""
        self._step += 1

    # ─── Text deltas (split into chunks) ──────────────────────────────

    def emit_delta(self, channel: str, text: str) -> None:
        """Text delta: short ones written as-is, long ones split into ≤ 2000-char chunks with 50ms gaps."""
        if not text or text in ("null", "None", "none"):
            return
        if len(text) <= CHUNK_SIZE:
            _write({"type": "model_delta", "channel": channel, "text": text, "step": self._step})
        else:
            chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
            for i, chunk in enumerate(chunks):
                _write({"type": "model_delta", "channel": channel, "text": chunk, "step": self._step})
                if i < len(chunks) - 1:
                    time.sleep(CHUNK_DELAY)

    # ─── Structured events (pass-through) ─────────────────────────────

    def emit_preparing(self, call_id: str, name: str) -> None:
        _write({"type": "tool.preparing", "callId": call_id, "name": name, "step": self._step})

    def emit_intent(self, call_id: str, name: str, args: str) -> None:
        """Tool intent: single write. Args truncated if > CHUNK_SIZE."""
        if len(args) > CHUNK_SIZE:
            args = args[:CHUNK_SIZE] + "...(参数过长已截断)"
        _write({"type": "tool.intent", "callId": call_id, "name": name, "args": args, "step": self._step})

    def emit_result(self, call_id: str, ok: bool, output: str) -> None:
        """Tool result: truncate to 400 chars, full version → events.jsonl."""
        if len(output) > TOOL_RESULT_MAX:
            _append_event_log(self.cwd, call_id, {"name": "tool_result", "ok": ok, "output": output})
            output = output[:TOOL_RESULT_MAX] + f"\n... (共 {len(output)} 字符，完整结果见事件日志)"
        _write({"type": "tool.result", "callId": call_id, "ok": ok, "output": output})

    # ─── Turn lifecycle ───────────────────────────────────────────────

    def emit_final(self, content: str = "", reasoning: str = "") -> None:
        _write({"type": "model_final", "content": content, "reasoningContent": reasoning})

    def emit_error(self, msg: str) -> None:
        _write({"type": "error", "message": msg})

    def emit_ready(self, model: str) -> None:
        _write({"type": "ready", "model": model})
