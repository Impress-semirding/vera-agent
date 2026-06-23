import { useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { sessionService } from '@/services/sessionService';
import { getToken, getUserName } from '@/services/authUser';

// ─── Segment model ─────────────────────────────────

export type Segment =
  | { kind: 'reasoning'; text: string; source?: 'reasoning' | 'content'; step?: number }
  | { kind: 'text'; text: string }
  | { kind: 'tool'; callId: string; name: string; args: string; output?: string; ok?: boolean; done: boolean };

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

function upsertSegment(
  segments: Segment[],
  kind: 'reasoning' | 'text' | 'tool',
  callId?: string,
): { segments: Segment[]; index: number } {
  const next = [...segments];
  if (kind === 'tool') {
    const idx = callId ? next.findIndex((s) => s.kind === 'tool' && s.callId === callId) : -1;
    if (idx !== -1) return { segments: next, index: idx };
    next.push({ kind: 'tool', callId: callId || '', name: '', args: '', done: false });
    return { segments: next, index: next.length - 1 };
  }
  if (kind === 'reasoning') {
    next.push({ kind: 'reasoning', text: '' });
    return { segments: next, index: next.length - 1 };
  }
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i]?.kind === kind) {
      if (i === next.length - 1) return { segments: next, index: i };
      break;
    }
  }
  next.push({ kind: 'text', text: '' });
  return { segments: next, index: next.length - 1 };
}

// ─── WebSocket base ─────────────────────────────────

function wsBase(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/v1`;
}

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const RECONNECT_MAX_ATTEMPTS = 10;

/** Merge cached (live) messages with DB-loaded messages, preserving
 *  conversation order without a timestamp sort (client vs. server clocks can
 *  misorder the user vs. assistant message under clock skew). */
function mergeMessages(cached: ChatMsg[], db: ChatMsg[]): ChatMsg[] {
  // Walk DB in server order, substituting the live cached copy wherever it
  // matches (by id, or role+content for transient optimistic msgs), then append
  // cached msgs the DB doesn't know yet (in-flight assistant turn).
  const isTransient = (id: string) => id.startsWith('u-') || id.startsWith('a-');
  const used = new Set<number>();
  const findCached = (dbm: ChatMsg): number =>
    cached.findIndex((c, i) => {
      if (used.has(i)) return false;
      if (c.id === dbm.id) return true;
      if (isTransient(c.id) && c.role === dbm.role && (c.content ?? '') === (dbm.content ?? '')) return true;
      return false;
    });
  const result: ChatMsg[] = [];
  for (const dbm of db) {
    const ci = findCached(dbm);
    if (ci !== -1) { used.add(ci); result.push(cached[ci]); }
    else { result.push(dbm); }
  }
  cached.forEach((c, i) => { if (!used.has(i)) result.push(c); });
  return result;
}

// ─── Main hook — single WS per agent, sessions multiplexed ─────────

export function useChatSocket(
  agentId: string | undefined,
  sessionId: string | undefined,
  onSessionRenamed?: (id: string, name: string) => void,
) {
  // Per-session state (refs). Each session's data is isolated; the UI shows
  // only the current sessionId's data. One WS demuxes by sessionId.
  const messagesMapRef = useRef<Map<string, ChatMsg[]>>(new Map());
  const streamingSetRef = useRef<Set<string>>(new Set());
  const artifactsMapRef = useRef<Map<string, { name: string; path: string; size: number }[]>>(new Map());
  const turnStartTimes = useRef<Map<string, number>>(new Map());

  // Derived for current sessionId
  const _messages = sessionId ? (messagesMapRef.current.get(sessionId) ?? []) : [];
  const _streaming = sessionId ? streamingSetRef.current.has(sessionId) : false;
  const _artifacts = sessionId ? (artifactsMapRef.current.get(sessionId) ?? []) : [];
  const [status, setStatus] = useState<ChatStatus>('idle');
  const [, setTick] = useState(0);
  const rerender = () => setTick((n) => n + 1);

  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // Single WS + reconnect state
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);
  // Messages sent while WS wasn't open yet — flushed on open. Keyed by sessionId.
  const pendingRef = useRef<Map<string, string[]>>(new Map());

  // ── Per-session message helpers ──────────────────────
  const applyMessages = (sid: string, msgs: ChatMsg[]) => {
    messagesMapRef.current.set(sid, msgs);
    if (sid === sessionIdRef.current) rerender();
  };

  // ── Demux handler — routes a frame to its session's state ──
  const handleFrame = useCallback((data: any) => {
    const t = data?.type;
    const sid: string = data?.sessionId || '';

    // Connection-level events (no sessionId)
    if (t === 'ready') return;
    if (t === 'ping') {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'pong' }));
      return;
    }
    if (t === 'error' && !sid) {
      message.error(data?.message || '聊天出错');
      return;
    }

    if (!sid) return;  // all other events must carry sessionId

    const _findMsgIdx = (next: ChatMsg[], tid?: string): number => {
      if (tid) { const i = next.findIndex((m) => m.turnId === tid); if (i !== -1) return i; }
      const last = next[next.length - 1];
      return (last && last.role === 'assistant') ? next.length - 1 : -1;
    };
    const getMsgs = () => messagesMapRef.current.get(sid) ?? [];

    // ── Error (session-scoped) ──
    if (t === 'error') {
      message.error(data?.message || '聊天出错');
      streamingSetRef.current.delete(sid);
      if (sid === sessionIdRef.current) rerender();
      return;
    }

    // ── Session renamed ──
    if (t === 'session_renamed') { onSessionRenamed?.(sid, data.name); return; }

    // ── Stopped (abort) ──
    if (t === 'stopped') {
      streamingSetRef.current.delete(sid);
      if (sid === sessionIdRef.current) rerender();
      return;
    }

    // ── Turn queued ──
    if (t === 'turn_queued') {
      if (sid === sessionIdRef.current) message.info(data?.message || '排队中...');
      return;
    }

    // ── Turn start ──
    if (t === 'turn_start') {
      const tid = data?.turnId;
      if (tid) {
        turnStartTimes.current.set(tid, Date.now());
        streamingSetRef.current.add(sid);
        const prev = getMsgs();
        if (!prev.some((m) => m.turnId === tid)) {
          applyMessages(sid, [...prev, {
            id: `a-${Date.now()}-${Math.random()}`, role: 'assistant' as const,
            content: '', reasoning: '', pending: true, turnId: tid,
            timestamp: new Date().toISOString(), segments: [],
          }]);
        }
        if (sid === sessionIdRef.current) rerender();
      }
      return;
    }

    // ── Artifacts ──
    if (t === 'artifacts') {
      artifactsMapRef.current.set(sid, (data?.files ?? []) as any[]);
      if (sid === sessionIdRef.current) rerender();
      return;
    }

    // ── Model delta ──
    if (t === 'model_delta') {
      const channel = data?.channel;
      const text: string = data?.text ?? '';
      const tid = data?.turnId;
      const prev = getMsgs();
      const next = [...prev];
      const idx = _findMsgIdx(next, tid);
      if (idx === -1) return;
      const target = next[idx]; if (!target) return;

      if (channel === 'reasoning') next[idx] = { ...target, reasoning: (target.reasoning || '') + text } as ChatMsg;
      else if (channel === 'content') next[idx] = { ...target, content: (target.content || '') + text } as ChatMsg;

      if (target.segments != null) {
        const segs = [...target.segments];
        if (channel === 'tool_args') {
          let ti = -1;
          for (let k = segs.length - 1; k >= 0; k--) {
            const el = segs[k]; if (el?.kind === 'tool' && !(el as any).done) { ti = k; break; }
          }
          if (ti === -1) { segs.push({ kind: 'tool', callId: '', name: '', args: '', done: false }); ti = segs.length - 1; }
          const seg = { ...segs[ti] } as any; seg.args += text; segs[ti] = seg;
        } else {
          const step = data?.step;
          if (step != null) {
            const lastSeg = segs.length > 0 ? segs[segs.length - 1] : null;
            if (lastSeg?.kind === 'reasoning' && (lastSeg as any).step === step) {
              const s = { ...lastSeg } as any; s.text += text; segs[segs.length - 1] = s;
            } else {
              segs.push({ kind: 'reasoning', text, source: channel === 'content' ? 'content' : 'reasoning', step } as Segment);
            }
          } else {
            const { segments: up, index: si } = upsertSegment(segs, 'reasoning');
            (up[si] as any).text += text;
            next[idx] = { ...next[idx], segments: up } as ChatMsg;
            applyMessages(sid, next);
            return;
          }
        }
        next[idx] = { ...next[idx], segments: segs } as ChatMsg;
      }
      applyMessages(sid, next);
      return;
    }

    // ── Tool preparing ──
    if (t === 'tool.preparing') {
      const tid = data?.turnId; const callId: string = data?.callId ?? ''; const name: string = data?.name ?? '';
      const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
      if (idx === -1) return; const target = next[idx];
      if (!target?.segments) return;
      next[idx] = { ...target, segments: [...target.segments, { kind: 'tool', callId, name, args: '', done: false }] } as ChatMsg;
      applyMessages(sid, next);
      return;
    }

    // ── Tool intent ──
    if (t === 'tool.intent') {
      const tid = data?.turnId; const callId: string = data?.callId ?? ''; const name: string = data?.name ?? ''; const args: string = data?.args ?? '';
      const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
      if (idx === -1) return; const target = next[idx];
      if (!target?.segments) return;
      next[idx] = { ...target, segments: target.segments.map((s) => s.kind === 'tool' && s.callId === callId ? { ...s, name, args } : s) } as ChatMsg;
      applyMessages(sid, next);
      return;
    }

    // ── Tool result ──
    if (t === 'tool.result') {
      const tid = data?.turnId; const callId: string = data?.callId ?? ''; const ok: boolean = data?.ok ?? false; const output: string = data?.output ?? '';
      const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
      if (idx === -1) return; const target = next[idx];
      if (!target?.segments) return;
      next[idx] = { ...target, segments: target.segments.map((s) => s.kind === 'tool' && s.callId === callId ? { ...s, ok, output, done: true } : s) } as ChatMsg;
      applyMessages(sid, next);
      return;
    }

    // ── Model final ──
    if (t === 'model_final') {
      const tid = data?.turnId;
      const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
      if (idx === -1) return; const target = next[idx];
      if (target?.role === 'assistant') {
        const finalContent = (typeof data.content === 'string' && data.content) ? data.content : target.content;
        const start = tid ? turnStartTimes.current.get(tid) : undefined;
        const dur = start ? Date.now() - start : undefined;
        next[idx] = { ...target, content: finalContent,
          reasoning: (typeof data.reasoningContent === 'string' && data.reasoningContent) ? data.reasoningContent : target.reasoning,
          pending: false, durationMs: dur };
        if (finalContent && target.segments) {
          next[idx].segments = [...target.segments, { kind: 'text', text: finalContent }];
        }
      }
      streamingSetRef.current.delete(sid);
      applyMessages(sid, next);
    }
  }, [onSessionRenamed]);

  // ─── Load history when session changes (merge with cache) ───
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    sessionService.messages(sessionId).then((res) => {
      if (cancelled) return;
      const dbMsgs: ChatMsg[] = (res.data ?? []).map((m: any) => {
        const msg: ChatMsg = { id: m.id, role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content || '', reasoning: m.reasoningContent || undefined,
          timestamp: m.timestamp, durationMs: m.durationMs ?? undefined };
        if (m.role === 'assistant' && m.segments?.length > 0) {
          const segs = m.segments as Segment[];
          if (!segs.some(s => s.kind === 'text') && m.content) segs.push({ kind: 'text', text: m.content });
          msg.segments = segs;
        }
        return msg;
      });
      const cached = messagesMapRef.current.get(sessionId) ?? [];
      applyMessages(sessionId, mergeMessages(cached, dbMsgs));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId]);

  // ─── Connect single WS on agentId; disconnect on unmount ───
  const connectRef = useRef<() => void>(() => {});

  connectRef.current = () => {
    if (!agentId) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      setStatus('open'); return;
    }

    setStatus('connecting');
    intentionalCloseRef.current = false;
    const tok = getToken();
    const qs = `user=${encodeURIComponent(getUserName() ?? '')}${tok ? `&token=${encodeURIComponent(tok)}` : ''}`;
    const ws = new WebSocket(`${wsBase()}/chat/${agentId}?${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      // Stale callback (StrictMode replaced this WS) — ignore
      if (wsRef.current !== ws) return;
      setStatus('open');
      reconnectAttemptRef.current = 0;
      // Flush any messages queued while the WS was connecting/closed
      for (const [sid, texts] of pendingRef.current) {
        for (const t of texts) {
          try { ws.send(JSON.stringify({ type: 'user_input', sessionId: sid, text: t })); } catch {}
        }
      }
      pendingRef.current.clear();
    };

    ws.onmessage = (ev) => {
      if (wsRef.current !== ws) return;  // stale
      let data: any;
      try { data = JSON.parse(ev.data); } catch { return; }
      handleFrame(data);
    };

    ws.onclose = (ev) => {
      // Only mutate state if this is still the active WS; otherwise it's a
      // stale callback from a replaced/cleaned-up connection (StrictMode).
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      setStatus('closed');
      // 4001 = backend replaced us (same user opened this agent in another tab).
      if (ev.code === 4001) {
        message.warning('该智能体已在其他标签页打开，当前连接已断开');
        return;
      }
      if (!intentionalCloseRef.current) {
        const attempt = reconnectAttemptRef.current;
        if (attempt < RECONNECT_MAX_ATTEMPTS) {
          const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempt), RECONNECT_MAX_DELAY);
          reconnectAttemptRef.current = attempt + 1;
          reconnectTimerRef.current = setTimeout(() => connectRef.current(), delay);
        }
      }
    };
    ws.onerror = () => {};
  };

  // One WS for the whole agent; sessionId changes don't reconnect
  useEffect(() => {
    if (!agentId) { setStatus('idle'); return; }
    connectRef.current();
    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
      if (wsRef.current) { try { wsRef.current.close(); } catch {} wsRef.current = null; }
    };
  }, [agentId]);

  // ── Send ───────────────────────────────────────────
  // Assumes a session already exists (sessionId is set). The caller creates the
  // session first and invokes send only once the route carries a sessionId, so
  // a message is never emitted before the session is established, and never
  // sent twice.
  const send = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !agentId || !sessionId) return;

    // Optimistic user message in this session
    messagesMapRef.current.set(sessionId, [...(messagesMapRef.current.get(sessionId) ?? []), {
      id: `u-${Date.now()}-${Math.random()}`, role: 'user', content: trimmed, timestamp: new Date().toISOString(),
    }]);
    rerender();

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'user_input', sessionId, text: trimmed }));
    } else {
      // WS not open yet — buffer and flush on connect (don't lose the message)
      const arr = pendingRef.current.get(sessionId) ?? [];
      arr.push(trimmed);
      pendingRef.current.set(sessionId, arr);
      reconnectAttemptRef.current = 0;
      connectRef.current();
    }
  }, [agentId, sessionId]);

  // ── Stop / Clear ───────────────────────────────────
  const stop = useCallback(() => {
    if (!sessionId) return;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'abort', sessionId }));
    }
  }, [sessionId]);

  const clear = useCallback(() => {
    if (sessionId) {
      messagesMapRef.current.set(sessionId, []);
      artifactsMapRef.current.set(sessionId, []);
      rerender();
      fetch(`/api/v1/sessions/${sessionId}/messages`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${getToken()}` },
      }).catch(() => {});
    }
  }, [sessionId]);

  return {
    messages: _messages,
    status,
    streaming: _streaming,
    artifacts: _artifacts,
    send, stop, clear,
  };
}
