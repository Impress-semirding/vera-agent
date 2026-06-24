"""
LLM chat subprocess — reads JSON lines from stdin, calls Anthropic-compatible
Messages API (streaming), writes JSON lines to stdout.

Usage (spawned by agent_runtime/normal/llm_client.py, not manually):
    python -m agent.chat

Input (stdin, one JSON per line):
    {"type":"start","model":"deepseek-v4-pro","baseUrl":"https://...","apiKey":"sk-...","maxTokens":4096}
    {"type":"user_input","text":"Hello"}

Output (stdout, one JSON per line):
    {"type":"model_delta","channel":"content","text":"..."}
    {"type":"model_delta","channel":"reasoning","text":"..."}
    {"type":"model_final","content":"...","reasoningContent":"..."}
    {"type":"error","message":"..."}
"""

from __future__ import annotations

import json
import sys

import httpx


def _write(obj: dict) -> None:
    """Write a JSON line to stdout (flush immediately)."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _call_anthropic_stream(
    model: str,
    base_url: str,
    api_key: str,
    messages: list[dict],
    max_tokens: int = 4096,
) -> str | None:
    """Call Anthropic Messages API (streaming) and write deltas to stdout.

    Returns the assembled assistant content (for appending to messages),
    or None on error.
    """
    url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    current_channel: str | None = None

    with httpx.Client(timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10)) as client:
        with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = resp.read().decode("utf-8", errors="replace")
                _write({"type": "error", "message": f"API {resp.status_code}: {body[:500]}"})
                return None

            for line in resp.iter_lines():
                if not line:
                    continue
                # SSE lines start with "data: "
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")

                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")
                        text = delta.get("text", "")

                        if delta_type == "thinking_delta":
                            reasoning_parts.append(text)
                            _write({"type": "model_delta", "channel": "reasoning", "text": text})
                        elif delta_type == "text_delta":
                            content_parts.append(text)
                            _write({"type": "model_delta", "channel": "content", "text": text})

                    elif event_type == "message_stop":
                        # Stream complete
                        pass

                    elif event_type == "error":
                        err = event.get("error", {})
                        _write({"type": "error", "message": err.get("message", str(event))})

    # Send final assembled message
    content = "".join(content_parts)
    _write({
        "type": "model_final",
        "content": content,
        "reasoningContent": "".join(reasoning_parts),
    })
    return content


def main() -> None:
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 4096
    messages: list[dict] = []

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _write({"type": "error", "message": "invalid JSON on stdin"})
            continue

        msg_type = msg.get("type", "")

        if msg_type == "start":
            model = msg.get("model", "")
            base_url = msg.get("baseUrl", "")
            api_key = msg.get("apiKey", "")
            max_tokens = msg.get("maxTokens", 4096)
            messages = []
            _write({"type": "ready", "model": model})

        elif msg_type == "user_input":
            text = msg.get("text", "")
            if not text or not model or not base_url or not api_key:
                _write({"type": "error", "message": "missing start config or empty text"})
                continue
            messages.append({"role": "user", "content": text})
            assistant_content = _call_anthropic_stream(model, base_url, api_key, messages, max_tokens)
            if assistant_content is not None:
                messages.append({"role": "assistant", "content": assistant_content})

        elif msg_type == "reset":
            messages = []
            _write({"type": "reset"})

        elif msg_type == "quit":
            break


if __name__ == "__main__":
    main()
