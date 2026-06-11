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
}

export type ChatStatus = 'idle' | 'connecting' | 'open' | 'closed';

function wsBase(): string {
  // Derive ws/wss from the page location; vite proxies /api → backend (ws too).
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/v1`;
}

/**
 * Drives a streaming chat over a WebSocket for one (agentId, sessionId).
 *
 * - Loads message history from the REST API when the session changes.
 * - Opens a WebSocket once a real session exists and reduces server events
 *   (`model_delta` reasoning/content, `model_final`) into the message list,
 *   appending tokens one at a time so the UI types them out.
 * - On the very first message (no session yet) it creates the session, lets
 *   the caller update the URL, and buffers the message until the socket opens.
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
  const pendingRef = useRef<string | null>(null); // message buffered until the socket opens
  const creatingRef = useRef(false); // guards against double session creation

  // Keep the latest event handler so the WS closure (created once per session)
  // always calls the current version without reconnecting.
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
        return; // handshake done
      }
      if (t === 'user_message') {
        // Server-authoritative user bubble (we don't optimistically append).
        const text: string = data?.text ?? '';
        setMessages((prev) => [...prev, { id: `u-${Date.now()}-${Math.random()}`, role: 'user', content: text }]);
        return;
      }
      if (t === 'model_delta') {
        const channel = data?.channel;
        const text: string = data?.text ?? '';
        setMessages((prev) => {
          const next = [...prev];
          let last = next[next.length - 1];
          if (!last || last.role !== 'assistant' || !last.pending) {
            last = { id: `a-${Date.now()}-${Math.random()}`, role: 'assistant', content: '', reasoning: '', pending: true };
            next.push(last);
          }
          if (channel === 'reasoning') {
            next[next.length - 1] = { ...last, reasoning: (last.reasoning || '') + text };
          } else {
            next[next.length - 1] = { ...last, content: (last.content || '') + text };
          }
          return next;
        });
        return;
      }
      if (t === 'model_final') {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'assistant') {
            next[next.length - 1] = {
              ...last,
              content: typeof data.content === 'string' ? data.content : last.content,
              reasoning: typeof data.reasoningContent === 'string' ? data.reasoningContent : last.reasoning,
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

  // Load history when the session changes.
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
          })),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Open the WebSocket whenever we have a real session to chat in.
  useEffect(() => {
    if (!agentId || !sessionId) return;
    setStatus('connecting');
    const ws = new WebSocket(
      `${wsBase()}/chat/${agentId}/${sessionId}?user=${encodeURIComponent(getUserName() ?? '')}`,
    );
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('open');
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
    ws.onclose = () => setStatus('closed');
    ws.onerror = () => setStatus('closed');

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [agentId, sessionId]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !agentId || streaming) return;

      // No session yet → create one and switch the URL, but do NOT send the
      // text. The caller keeps it in the input box; the user sends again once
      // the socket for the new session is open. (No streaming starts here.)
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

      setStreaming(true);
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'user_input', text: trimmed }));
      } else {
        pendingRef.current = trimmed; // buffer until (re)connected
      }
    },
    [agentId, sessionId, streaming, onSessionCreated],
  );

  const clear = useCallback(() => setMessages([]), []);

  return { messages, status, streaming, send, clear };
}
