import { useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { sessionService } from '@/services/sessionService';
import { getUserName } from '@/services/authUser';

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

/** Merge cached (in-memory) messages with DB-loaded messages.
 *  DB is the source of truth for persisted messages; cached may contain
 *  newer messages streamed via WS that haven't been persisted yet.
 *  Deduplicates by message id. */
function mergeMessages(cached: ChatMsg[], db: ChatMsg[]): ChatMsg[] {
  const dbIds = new Set(db.map((m) => m.id));
  // Keep all DB messages + any cached messages not yet in DB
  const extra = cached.filter((m) => !dbIds.has(m.id));
  // Sort by timestamp
  return [...db, ...extra].sort((a, b) =>
    (a.timestamp || '').localeCompare(b.timestamp || ''),
  );
}

// ─── Main hook ──────────────────────────────────────

export function useChatSocket(
  agentId: string | undefined,
  sessionId: string | undefined,
  onSessionCreated: (id: string) => void,
) {
  // ── Per-session state (refs, not React state) ─────
  // Each session's data is isolated; the UI shows only current sessionId.
  const messagesMapRef = useRef<Map<string, ChatMsg[]>>(new Map());
  const streamingSetRef = useRef<Set<string>>(new Set());
  const artifactsMapRef = useRef<Map<string, { name: string; path: string; size: number }[]>>(new Map());

  // Derived for current sessionId
  const _messages = sessionId ? (messagesMapRef.current.get(sessionId) ?? []) : [];
  const _streaming = sessionId ? streamingSetRef.current.has(sessionId) : false;
  const _artifacts = sessionId ? (artifactsMapRef.current.get(sessionId) ?? []) : [];
  const [status, setStatus] = useState<ChatStatus>('idle');
  const [, setTick] = useState(0);
  const rerender = () => setTick((n) => n + 1);

  // Use ref so old handlers (from background WS connections) always see
  // the latest sessionId — avoids wasted re-renders and stale checks.
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const applyToSession = <T,>(map: React.MutableRefObject<Map<string, T>>, sid: string, val: T) => {
    map.current.set(sid, val);
    if (sid === sessionIdRef.current) rerender();
  };

  // ── WS management ──────────────────────────────────
  const wsMapRef = useRef<Map<string, WebSocket>>(new Map());
  const sessionAccessRef = useRef<Map<string, number>>(new Map()); // sid → lastAccess timestamp
  const activeSessionRef = useRef<string | undefined>(sessionId);
  // Per-session pending messages & reconnect state
  const pendingRef = useRef<Map<string, string>>(new Map());
  const reconnectAttemptRef = useRef<Map<string, number>>(new Map());
  const creatingRef = useRef(false);
  const reconnectTimerRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Generation counter — incremented on each mount cycle (StrictMode safe).
  // WS callbacks check the generation they were created with; stale callbacks
  // from a previous mount are silently ignored.
  const generationRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const turnStartTimes = useRef<Map<string, number>>(new Map());

  // LRU eviction limit — matches backend AGENT_MAX_SESSIONS default.
  // When exceeded, the least-recently-accessed session's WS is closed.
  const MAX_WS_CONNECTIONS = 3;  // must match backend AGENT_MAX_SESSIONS

  const touchSession = (sid: string) => { sessionAccessRef.current.set(sid, Date.now()); };

  const evictLRU = () => {
    const access = sessionAccessRef.current;
    let oldestSid: string | null = null;
    let oldestTime = Infinity;
    for (const [sid, ws] of wsMapRef.current) {
      if (sid === sessionId) continue; // never evict current session
      const t = access.get(sid) ?? 0;
      if (t < oldestTime) { oldestTime = t; oldestSid = sid; }
    }
    if (oldestSid) {
      const ws = wsMapRef.current.get(oldestSid);
      if (ws) { try { ws.close(); } catch {} }
      wsMapRef.current.delete(oldestSid);
      streamingSetRef.current.delete(oldestSid);
    }
  };

  const getCurrentWs = () => sessionId ? wsMapRef.current.get(sessionId) ?? null : null;

  // ── Session-bound event handler factory ────────────
  // Each WS gets its own handler with `sid` captured in closure.
  // All setState calls are scoped to this sid.

  const makeHandler = useCallback(
    (sid: string) => {
      const _findMsgIdx = (next: ChatMsg[], tid?: string): number => {
        if (tid) { const i = next.findIndex((m) => m.turnId === tid); if (i !== -1) return i; }
        const last = next[next.length - 1];
        return (last && last.role === 'assistant') ? next.length - 1 : -1;
      };

      const getMsgs = () => messagesMapRef.current.get(sid) ?? [];
      const setMsgs = (v: ChatMsg[]) => applyToSession(messagesMapRef, sid, v);
      const setStr = (v: boolean) => {
        if (v) streamingSetRef.current.add(sid); else streamingSetRef.current.delete(sid);
        if (sid === sessionIdRef.current) rerender();
      };
      const setArts = (v: { name: string; path: string; size: number }[]) => applyToSession(artifactsMapRef, sid, v);

      return (data: any) => {
        const t = data?.type;

        // ── Error ──
        if (t === 'error') { message.error(data?.message || '聊天出错'); setStr(false); return; }

        // ── Session created ──
        if (t === 'session' && data?.sessionId) { onSessionCreated(data.sessionId); return; }

        // ── Ready ──
        if (t === 'ready') return;

        // ── Stopped (abort) ──
        if (t === 'stopped') { setStr(false); return; }

        // ── Turn start / queued ──
        if (t === 'turn_start') {
          const tid = data?.turnId;
          if (tid) {
            turnStartTimes.current.set(tid, Date.now());
            setStr(true);
            setMsgs(getMsgs().some((m) => m.turnId === tid) ? getMsgs() : [...getMsgs(), {
              id: `a-${Date.now()}-${Math.random()}`, role: 'assistant' as const,
              content: '', reasoning: '', pending: true, turnId: tid,
              timestamp: new Date().toISOString(), segments: [],
            }]);
          } else { setStr(true); }
          return;
        }
        if (t === 'turn_queued') { return; }

        // ── Session limit / waiting ──
        if (t === 'session_limit') {
          message.warning(data?.message || '会话数已达上限，自动关闭最久未使用的会话');
          // Evict the LRU session to make room, then retry
          evictLRU();
          setTimeout(() => connectRef.current(), 1500);  // wait for backend to process WS close
          return;
        }
        if (t === 'session_resume') {
          message.success(data?.message || '会话已恢复');
          return;
        }
        if (t === 'session_waiting') { return; }  // silent heartbeat

        // ── Ping ──
        if (t === 'ping') {
          const w = wsMapRef.current.get(sid);
          if (w && w.readyState === WebSocket.OPEN) w.send(JSON.stringify({ type: 'pong' }));
          return;
        }

        // ── Artifacts ──
        if (t === 'artifacts') { setArts((data?.files ?? []) as any[]); return; }

        // ── User message echo ──
        if (t === 'user_message') return;

        // ── Model delta ──
        if (t === 'model_delta') {
          const channel = data?.channel;
          const text: string = data?.text ?? '';
          const tid = data?.turnId;
          setMsgs((() => {
            const prev = getMsgs();
            const next = [...prev];
            const idx = _findMsgIdx(next, tid);
            if (idx === -1) return prev;
            const target = next[idx]; if (!target) return prev;

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
                  return next;
                }
              }
              next[idx] = { ...next[idx], segments: segs } as ChatMsg;
            }
            return next;
          })());
          return;
        }

        // ── Tool preparing ──
        if (t === 'tool.preparing') {
          const tid = data?.turnId; const callId: string = data?.callId ?? ''; const name: string = data?.name ?? '';
          setMsgs((() => {
            const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
            if (idx === -1) return prev; const target = next[idx];
            if (!target?.segments) return prev;
            next[idx] = { ...target, segments: [...target.segments, { kind: 'tool', callId, name, args: '', done: false }] } as ChatMsg;
            return next;
          })());
          return;
        }

        // ── Tool intent ──
        if (t === 'tool.intent') {
          const tid = data?.turnId; const callId: string = data?.callId ?? ''; const name: string = data?.name ?? ''; const args: string = data?.args ?? '';
          setMsgs((() => {
            const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
            if (idx === -1) return prev; const target = next[idx];
            if (!target?.segments) return prev;
            next[idx] = { ...target, segments: target.segments.map((s) => s.kind === 'tool' && s.callId === callId ? { ...s, name, args } : s) } as ChatMsg;
            return next;
          })());
          return;
        }

        // ── Tool result ──
        if (t === 'tool.result') {
          const tid = data?.turnId; const callId: string = data?.callId ?? ''; const ok: boolean = data?.ok ?? false; const output: string = data?.output ?? '';
          setMsgs((() => {
            const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
            if (idx === -1) return prev; const target = next[idx];
            if (!target?.segments) return prev;
            next[idx] = { ...target, segments: target.segments.map((s) => s.kind === 'tool' && s.callId === callId ? { ...s, ok, output, done: true } : s) } as ChatMsg;
            return next;
          })());
          return;
        }

        // ── Model final ──
        if (t === 'model_final') {
          const tid = data?.turnId;
          setMsgs((() => {
            const prev = getMsgs(); const next = [...prev]; const idx = _findMsgIdx(next, tid);
            if (idx === -1) return prev; const target = next[idx];
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
            return next;
          })());
          setStr(false);
        }
      };
    },
    [onSessionCreated, sessionId],
  );

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
      // Merge: keep any in-memory messages that are newer than DB (e.g. from live WS)
      const cached = messagesMapRef.current.get(sessionId) ?? [];
      const merged = mergeMessages(cached, dbMsgs);
      applyToSession(messagesMapRef, sessionId, merged);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId]);

  // ─── Connect ───────────────────────────────────────
  const connectRef = useRef<() => void>(() => {});

  connectRef.current = (gen?: number) => {
    if (!agentId || !sessionId) return;
    const existing = wsMapRef.current.get(sessionId);
    if (existing && existing.readyState === WebSocket.OPEN) {
      touchSession(sessionId);
      setStatus('open');
      return;
    }

    if (wsMapRef.current.size >= MAX_WS_CONNECTIONS) evictLRU();

    setStatus('connecting');
    const myGen = gen ?? generationRef.current;
    const ws = new WebSocket(`${wsBase()}/chat/${agentId}/${sessionId}?user=${encodeURIComponent(getUserName() ?? '')}`);
    wsMapRef.current.set(sessionId, ws);
    touchSession(sessionId);

    ws.onopen = () => {
      // Stale callback from a previous mount cycle — ignore
      if (myGen !== generationRef.current) { try { ws.close(); } catch {} return; }
      if (sessionId === activeSessionRef.current) setStatus('open');
      reconnectAttemptRef.current.set(sessionId, 0);
      const pending = pendingRef.current.get(sessionId);
      if (pending) { ws.send(JSON.stringify({ type: 'user_input', text: pending })); pendingRef.current.delete(sessionId); }
    };

    // Each WS has its own handler bound to its sessionId — no cross-session leaks
    const handler = makeHandler(sessionId);
    ws.onmessage = (ev) => {
      let data: any;
      try { data = JSON.parse(ev.data); } catch { return; }
      handler(data);
    };

    ws.onclose = (ev) => {
      if (myGen !== generationRef.current) return;  // stale callback
      wsMapRef.current.delete(sessionId);
      if (sessionId === activeSessionRef.current) setStatus('closed');
      if (!intentionalCloseRef.current && !ev.wasClean) {
        const attempt = reconnectAttemptRef.current.get(sessionId) ?? 0;
        if (attempt < RECONNECT_MAX_ATTEMPTS) {
          const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempt), RECONNECT_MAX_DELAY);
          reconnectAttemptRef.current.set(sessionId, attempt + 1);
          reconnectTimerRef.current.set(sessionId, setTimeout(() => connectRef.current(), delay));
        }
      }
    };
    ws.onerror = () => {};
  };

  // ─── Session connection — when sessionId changes, connect (no kill) ──
  useEffect(() => {
    activeSessionRef.current = sessionId;
    if (sessionId) touchSession(sessionId);
    if (!agentId || !sessionId) { setStatus('idle'); return; }
    const gen = ++generationRef.current;
    intentionalCloseRef.current = false;
    connectRef.current(gen);
  }, [agentId, sessionId]);

  // ─── Unmount cleanup — only when leaving the chat page entirely ──
  useEffect(() => {
    return () => {
      intentionalCloseRef.current = true;
      reconnectTimerRef.current.forEach((t) => clearTimeout(t));
      reconnectTimerRef.current.clear();
      wsMapRef.current.forEach((w) => { try { w.close(); } catch {} });
      wsMapRef.current.clear();
    };
  }, []);

  // ── Send ───────────────────────────────────────────
  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !agentId) return;
    if (!sessionId) {
      if (creatingRef.current) return;
      creatingRef.current = true;
      try { const res = await sessionService.create(agentId, `会话 ${new Date().toLocaleString('zh-CN')}`); onSessionCreated(res.data.id); }
      catch { message.error('创建会话失败'); }
      finally { creatingRef.current = false; }
      return;
    }
    // Add user message to current session only
    messagesMapRef.current.set(sessionId, [...(messagesMapRef.current.get(sessionId) ?? []), {
      id: `u-${Date.now()}-${Math.random()}`, role: 'user', content: trimmed, timestamp: new Date().toISOString(),
    }]);
    rerender();
    const ws = getCurrentWs();
    if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify({ type: 'user_input', text: trimmed })); }
    else { pendingRef.current.set(sessionId, trimmed); if (!ws || ws.readyState === WebSocket.CLOSED) { reconnectAttemptRef.current.set(sessionId, 0); connectRef.current(); } }
  }, [agentId, sessionId, onSessionCreated]);

  // ── Stop / Clear ───────────────────────────────────
  const stop = useCallback(() => {
    const ws = getCurrentWs();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'abort' }));
  }, [sessionId]);

  const clear = useCallback(() => {
    if (sessionId) {
      messagesMapRef.current.set(sessionId, []);
      artifactsMapRef.current.set(sessionId, []);
      rerender();
      fetch(`/api/v1/sessions/${sessionId}/messages`, { method: 'DELETE' }).catch(() => {});
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
