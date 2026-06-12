import { useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { sessionService } from '@/services/sessionService';
import { getUserName } from '@/services/authUser';

/** A single chat message. Assistant messages may carry a reasoning trace. */
export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  pending?: boolean;
  turnId?: string;
  timestamp?: string;
}

export type ChatStatus = 'idle' | 'connecting' | 'open' | 'closed';

function wsBase(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/v1`;
}

// Reconnect configuration
const RECONNECT_BASE_DELAY = 1000; // ms
const RECONNECT_MAX_DELAY = 30000; // ms
const RECONNECT_MAX_ATTEMPTS = 10;

/**
 * Drives a streaming chat over a WebSocket for one (agentId, sessionId).
 *
 * Features:
 * - Loads message history from the REST API when the session changes.
 * - Auto-reconnect with exponential backoff on unexpected disconnect.
 * - Heartbeat (ping/pong) to detect dead connections.
 * - Buffers outbound messages until the socket is open.
 */
export function useChatSocket(
  agentId: string | undefined,
  sessionId: string | undefined,
  onSessionCreated: (id: string) => void,
) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [status, setStatus] = useState<ChatStatus>('idle');
  const [streaming, setStreaming] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pendingRef = useRef<string | null>(null);
  const creatingRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);

  const handleEventRef = useRef<(data: any) => void>(() => {});

  const handleEvent = useCallback(
    (data: any) => {
      const t = data?.type;
      if (t === 'error') {
        message.error(data?.message || '聊天出错');
        setStreaming(false);
        return;
      }
      if (t === 'session' && data?.sessionId) {
        onSessionCreated(data.sessionId);
        return;
      }
      if (t === 'ready') {
        return;
      }
      if (t === 'stopped') {
        // Current turn was aborted. Set false for now; if queue has more
        // messages, the worker will send another turn_start immediately.
        setStreaming(false);
        return;
      }
      if (t === 'turn_start') {
        // Worker picked up a message from the queue — pre-create assistant message with turnId.
        const tid = data?.turnId;
        if (tid) {
          setStreaming(true);
          setMessages((prev) => {
            // Avoid duplicate if somehow already exists.
            if (prev.some((m) => m.turnId === tid)) return prev;
            return [...prev, {
              id: `a-${Date.now()}-${Math.random()}`,
              role: 'assistant' as const,
              content: '',
              reasoning: '',
              pending: true,
              turnId: tid,
              timestamp: new Date().toISOString(),
            }];
          });
        } else {
          setStreaming(true);
        }
        return;
      }
      if (t === 'ping') {
        // Respond to server heartbeat
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'pong' }));
        }
        return;
      }
      if (t === 'user_message') {
        // Server echo of user message — already added optimistically in send().
        // Ignore to avoid duplicates.
        return;
      }
      if (t === 'model_delta') {
        const channel = data?.channel;
        const text: string = data?.text ?? '';
        const tid = data?.turnId;
        setMessages((prev) => {
          const next = [...prev];
          // Find the assistant message by turnId, or fall back to last pending assistant.
          let idx = tid ? next.findIndex((m) => m.turnId === tid) : -1;
          if (idx === -1) {
            idx = next.length - 1;
            const last = next[idx];
            if (!last || last.role !== 'assistant' || !last.pending) {
              // No matching message — create one.
              const msg: ChatMsg = {
                id: `a-${Date.now()}-${Math.random()}`,
                role: 'assistant',
                content: '',
                reasoning: '',
                pending: true,
                turnId: tid || undefined,
                timestamp: new Date().toISOString(),
              };
              next.push(msg);
              idx = next.length - 1;
            }
          }
          const target = next[idx];
          if (channel === 'reasoning') {
            next[idx] = { ...target, reasoning: (target.reasoning || '') + text };
          } else {
            next[idx] = { ...target, content: (target.content || '') + text };
          }
          return next;
        });
        return;
      }
      if (t === 'model_final') {
        const tid = data?.turnId;
        setMessages((prev) => {
          const next = [...prev];
          // Find by turnId first, then fall back to last assistant message.
          let idx = tid ? next.findIndex((m) => m.turnId === tid) : -1;
          if (idx === -1) {
            idx = next.length - 1;
          }
          const target = next[idx];
          if (target && target.role === 'assistant') {
            next[idx] = {
              ...target,
              content: typeof data.content === 'string' ? data.content : target.content,
              reasoning: typeof data.reasoningContent === 'string' ? data.reasoningContent : target.reasoning,
              pending: false,
            };
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
          (res.data ?? []).map((m) => ({
            id: m.id,
            role: m.role === 'assistant' ? 'assistant' : 'user',
            content: m.content || '',
            reasoning: m.reasoningContent || undefined,
            timestamp: m.timestamp,
          })),
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
      reconnectAttemptRef.current = 0; // reset on successful connect
      // Send any buffered message
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
      // Auto-reconnect unless intentionally closed or normal closure
      if (!intentionalCloseRef.current && !ev.wasClean) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose will fire after this, which handles reconnect
    };
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
    // Clean up previous connection
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

    // Open new connection
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

      // No session yet → create one
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

      // Optimistically add user message to chat immediately (real send order).
      // Server's user_message echo is ignored to avoid duplicates.
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
        pendingRef.current = trimmed; // buffer until (re)connected
        // Try to reconnect if closed
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

  const clear = useCallback(() => setMessages([]), []);

  return { messages, status, streaming, send, stop, clear };
}
