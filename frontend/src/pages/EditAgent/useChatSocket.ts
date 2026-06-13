import { useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { sessionService } from '@/services/sessionService';
import { getUserName } from '@/services/authUser';

// ─── Segment model ─────────────────────────────────

export type Segment =
  | { kind: 'reasoning'; text: string; source?: 'reasoning' | 'content' }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; callId: string; name: string; args: string; output?: string; ok?: boolean; done: boolean };

/** A single chat message. Assistant messages may carry structured segments. */
export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  pending?: boolean;
  turnId?: string;
  timestamp?: string;
  durationMs?: number;
  segments?: Segment[];
}

export type ChatStatus = 'idle' | 'connecting' | 'open' | 'closed';

// ─── Segment helpers ────────────────────────────────

/** Find or create the last segment of a given kind, optionally matching a callId. */
function upsertSegment(
  segments: Segment[],
  kind: 'reasoning' | 'text' | 'tool',
  callId?: string,
): { segments: Segment[]; index: number } {
  const next = [...segments];

  if (kind === 'tool') {
    // Find existing tool segment by callId
    const idx = callId ? next.findIndex((s) => s.kind === 'tool' && s.callId === callId) : -1;
    if (idx !== -1) return { segments: next, index: idx };
    // Create new tool segment
    const seg: Segment = { kind: 'tool', callId: callId || '', name: '', args: '', done: false };
    next.push(seg);
    return { segments: next, index: next.length - 1 };
  }

  // Reasoning: always create a NEW segment (each thinking step is separate).
  // Text: append to the last text segment (final answer is one continuous block).
  if (kind === 'reasoning') {
    const seg: Segment = { kind: 'reasoning', text: '' };
    next.push(seg);
    return { segments: next, index: next.length - 1 };
  }

  // Text: find the last text segment, reuse if it's the last segment overall
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i]?.kind === kind) {
      if (i === next.length - 1) return { segments: next, index: i };
      break;
    }
  }

  // Create new segment
  const seg: Segment = { kind: 'text', text: '' };
  next.push(seg);
  return { segments: next, index: next.length - 1 };
}

// ─── WebSocket base ─────────────────────────────────

function wsBase(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/v1`;
}

// Reconnect configuration
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const RECONNECT_MAX_ATTEMPTS = 10;

// ─── Main hook ──────────────────────────────────────

export function useChatSocket(
  agentId: string | undefined,
  sessionId: string | undefined,
  onSessionCreated: (id: string) => void,
) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [status, setStatus] = useState<ChatStatus>('idle');
  const [streaming, setStreaming] = useState(false);
  const [artifacts, setArtifacts] = useState<{ name: string; path: string; size: number }[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const pendingRef = useRef<string | null>(null);
  const creatingRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);
  const turnStartTimes = useRef<Map<string, number>>(new Map());

  const handleEventRef = useRef<(data: any) => void>(() => {});

  // ─── Helper: find message index by turnId ────
  const findMsgIdx = (next: ChatMsg[], tid?: string): number => {
    if (tid) {
      const idx = next.findIndex((m) => m.turnId === tid);
      if (idx !== -1) return idx;
    }
    // Fallback: last assistant message
    const last = next[next.length - 1];
    return (last && last.role === 'assistant') ? next.length - 1 : -1;
  };

  const handleEvent = useCallback(
    (data: any) => {
      const t = data?.type;

      // ─── Error ───
      if (t === 'error') {
        message.error(data?.message || '聊天出错');
        setStreaming(false);
        return;
      }

      // ─── Session created ───
      if (t === 'session' && data?.sessionId) {
        onSessionCreated(data.sessionId);
        return;
      }

      // ─── Ready ───
      if (t === 'ready') return;

      // ─── Stopped (abort) ───
      if (t === 'stopped') {
        setStreaming(false);
        return;
      }

      // ─── Turn start ───
      if (t === 'turn_start') {
        const tid = data?.turnId;
        if (tid) {
          turnStartTimes.current.set(tid, Date.now());
          setStreaming(true);
          setMessages((prev) => {
            if (prev.some((m) => m.turnId === tid)) return prev;
            return [...prev, {
              id: `a-${Date.now()}-${Math.random()}`,
              role: 'assistant' as const,
              content: '',
              reasoning: '',
              pending: true,
              turnId: tid,
              timestamp: new Date().toISOString(),
              segments: [],
            }];
          });
        } else {
          setStreaming(true);
        }
        return;
      }

      // ─── Ping ───
      if (t === 'ping') {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'pong' }));
        }
        return;
      }

      // ─── Artifacts (workspace files) ───
      if (t === 'artifacts') {
        setArtifacts((data?.files ?? []) as { name: string; path: string; size: number }[]);
        return;
      }

      // ─── User message echo (ignored) ───
      if (t === 'user_message') return;

      // ─── Model delta (content / reasoning / tool_args) ───
      if (t === 'model_delta') {
        const channel = data?.channel;
        const text: string = data?.text ?? '';
        const tid = data?.turnId;

        setMessages((prev) => {
          const next = [...prev];
          let idx = findMsgIdx(next, tid);
          if (idx === -1) return prev;
          const target = next[idx];
          if (!target) return prev;

          // Update flat fields for backward compat
          if (channel === 'reasoning') {
            next[idx] = { ...target, reasoning: (target.reasoning || '') + text } as ChatMsg;
          } else if (channel === 'content') {
            next[idx] = { ...target, content: (target.content || '') + text } as ChatMsg;
          }

          // Update segments
          if (target.segments != null) {
            const segs = [...target.segments];
            if (channel === 'tool_args') {
              // Append to the last incomplete tool segment's args
              let ti = -1;
              for (let k = segs.length - 1; k >= 0; k--) {
                const el = segs[k];
                if (el && el.kind === 'tool' && !(el as Extract<Segment, { kind: 'tool' }>).done) { ti = k; break; }
              }
              if (ti === -1) {
                segs.push({ kind: 'tool', callId: '', name: '', args: '', done: false });
                ti = segs.length - 1;
              }
              const seg = { ...segs[ti] } as Extract<Segment, { kind: 'tool' }>;
              seg.args = seg.args + text;
              segs[ti] = seg;
              next[idx] = { ...next[idx], segments: segs } as ChatMsg;
            } else {
              // Both reasoning and content deltas go into the thinking block.
              // Only model_final creates the final visible text segment.
              const kind = channel === 'reasoning' || channel === 'content' ? 'reasoning' : 'text';
              const { segments: updated, index: si } = upsertSegment(segs, kind);
              const seg = { ...updated[si] } as Extract<Segment, { kind: 'reasoning' | 'text' }>;
              seg.text = seg.text + text;
              if (kind === 'reasoning') {
                (seg as Extract<Segment, { kind: 'reasoning' }>).source = channel === 'content' ? 'content' : 'reasoning';
              }
              updated[si] = seg;
              next[idx] = { ...next[idx], segments: updated } as ChatMsg;
            }
          }
          return next;
        });
        return;
      }

      // ─── Tool preparing ───
      if (t === 'tool.preparing') {
        const tid = data?.turnId;
        const callId: string = data?.callId ?? '';
        const name: string = data?.name ?? '';
        setMessages((prev) => {
          const next = [...prev];
          const idx = findMsgIdx(next, tid);
          if (idx === -1) return prev;
          const target = next[idx];
          if (!target || target.segments == null) return prev;
          const segs = [...target.segments];
          segs.push({ kind: 'tool', callId, name, args: '', done: false });
          next[idx] = { ...target, segments: segs } as ChatMsg;
          return next;
        });
        return;
      }

      // ─── Tool intent (full args ready) ───
      if (t === 'tool.intent') {
        const tid = data?.turnId;
        const callId: string = data?.callId ?? '';
        const name: string = data?.name ?? '';
        const args: string = data?.args ?? '';
        setMessages((prev) => {
          const next = [...prev];
          const idx = findMsgIdx(next, tid);
          if (idx === -1) return prev;
          const target = next[idx];
          if (!target || target.segments == null) return prev;
          const segs = target.segments.map((s) =>
            s.kind === 'tool' && s.callId === callId ? { ...s, name, args } : s,
          );
          next[idx] = { ...target, segments: segs } as ChatMsg;
          return next;
        });
        return;
      }

      // ─── Tool result ───
      if (t === 'tool.result') {
        const tid = data?.turnId;
        const callId: string = data?.callId ?? '';
        const ok: boolean = data?.ok ?? false;
        const output: string = data?.output ?? '';
        setMessages((prev) => {
          const next = [...prev];
          const idx = findMsgIdx(next, tid);
          if (idx === -1) return prev;
          const target = next[idx];
          if (!target || target.segments == null) return prev;
          const segs = target.segments.map((s) =>
            s.kind === 'tool' && s.callId === callId ? { ...s, ok, output, done: true } : s,
          );
          next[idx] = { ...target, segments: segs } as ChatMsg;
          return next;
        });
        return;
      }

      // ─── Model final ───
      if (t === 'model_final') {
        const tid = data?.turnId;
        setMessages((prev) => {
          const next = [...prev];
          const idx = findMsgIdx(next, tid);
          if (idx === -1) return prev;
          const target = next[idx];
          if (target && target.role === 'assistant') {
            const finalContent = (typeof data.content === 'string' && data.content) ? data.content : target.content;
            const start = tid ? turnStartTimes.current.get(tid) : undefined;
            const durationMs = start ? Date.now() - start : undefined;
            next[idx] = {
              ...target,
              content: finalContent,
              reasoning: (typeof data.reasoningContent === 'string' && data.reasoningContent) ? data.reasoningContent : target.reasoning,
              pending: false,
              durationMs,
            };
            // Append final text segment after thinking block (always visible)
            if (finalContent && target.segments != null) {
              const segs = [...target.segments];
              segs.push({ kind: 'text', text: finalContent });
              next[idx].segments = segs;
            }
          }
          return next;
        });
        setStreaming(false);
      }
    },
    [onSessionCreated],
  );

  handleEventRef.current = handleEvent;

  // ─── Load history when session changes ───
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    sessionService
      .messages(sessionId)
      .then((res) => {
        if (cancelled) return;
        setMessages(
          (res.data ?? []).map((m) => {
            const msg: ChatMsg = {
              id: m.id,
              role: m.role === 'assistant' ? 'assistant' : 'user',
              content: m.content || '',
              reasoning: m.reasoningContent || undefined,
              timestamp: m.timestamp,
              durationMs: m.durationMs ?? undefined,
            };
            // Use persisted segments if available
            if (m.role === 'assistant' && m.segments && m.segments.length > 0) {
              msg.segments = m.segments as Segment[];
            }
            return msg;
          }),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // ─── Connect / reconnect logic ───
  const connectRef = useRef<() => void>(() => {});

  connectRef.current = () => {
    if (!agentId || !sessionId) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    setStatus('connecting');
    const ws = new WebSocket(
      `${wsBase()}/chat/${agentId}/${sessionId}?user=${encodeURIComponent(getUserName() ?? '')}`,
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('open');
      reconnectAttemptRef.current = 0;
      if (pendingRef.current) {
        ws.send(JSON.stringify({ type: 'user_input', text: pendingRef.current }));
        pendingRef.current = null;
      }
    };

    ws.onmessage = (ev) => {
      let data: any;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleEventRef.current(data);
    };

    ws.onclose = (ev) => {
      wsRef.current = null;
      setStatus('closed');
      if (!intentionalCloseRef.current && !ev.wasClean) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {};
  };

  const scheduleReconnect = () => {
    const attempt = reconnectAttemptRef.current;
    if (attempt >= RECONNECT_MAX_ATTEMPTS) return;

    const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempt), RECONNECT_MAX_DELAY);
    reconnectAttemptRef.current = attempt + 1;

    console.log(`[ws] reconnecting in ${delay}ms (attempt ${attempt + 1}/${RECONNECT_MAX_ATTEMPTS})`);
    reconnectTimerRef.current = setTimeout(() => {
      connectRef.current();
    }, delay);
  };

  // ─── Open/close WebSocket when session changes ───
  useEffect(() => {
    intentionalCloseRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    reconnectAttemptRef.current = 0;

    if (!agentId || !sessionId) {
      setStatus('idle');
      return;
    }

    intentionalCloseRef.current = false;
    connectRef.current();

    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [agentId, sessionId]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !agentId) return;

      if (!sessionId) {
        if (creatingRef.current) return;
        creatingRef.current = true;
        try {
          const res = await sessionService.create(agentId, `会话 ${new Date().toLocaleString('zh-CN')}`);
          onSessionCreated(res.data.id);
        } catch {
          message.error('创建会话失败');
        } finally {
          creatingRef.current = false;
        }
        return;
      }

      setMessages((prev) => [...prev, {
        id: `u-${Date.now()}-${Math.random()}`,
        role: 'user',
        content: trimmed,
        timestamp: new Date().toISOString(),
      }]);

      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'user_input', text: trimmed }));
      } else {
        pendingRef.current = trimmed;
        if (!ws || ws.readyState === WebSocket.CLOSED) {
          reconnectAttemptRef.current = 0;
          connectRef.current();
        }
      }
    },
    [agentId, sessionId, onSessionCreated],
  );

  const stop = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'abort' }));
    }
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setArtifacts([]);
    if (sessionId) {
      fetch(`/api/v1/sessions/${sessionId}/messages`, { method: 'DELETE' }).catch(() => {});
    }
  }, [sessionId]);

  return { messages, status, streaming, artifacts, send, stop, clear };
}
