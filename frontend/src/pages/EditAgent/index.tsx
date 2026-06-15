import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Button, Tag, Input, Switch, Spin,
  Modal, Popconfirm, Empty, message,
} from 'antd';
import ReactMarkdown from 'react-markdown';
import ReactECharts from 'echarts-for-react';
import mermaid from 'mermaid';

mermaid.initialize({ startOnLoad: false, theme: 'default' });
import {
  ArrowLeftOutlined, ArrowDownOutlined, MessageOutlined, SettingOutlined, AppstoreOutlined,
  PlusOutlined, SendOutlined, PaperClipOutlined,
  DownloadOutlined, RobotOutlined, UserOutlined,
  TeamOutlined, FileTextOutlined, CodeOutlined,
  GlobalOutlined, FileOutlined, CloseOutlined, ColumnWidthOutlined, StopOutlined,
  ThunderboltOutlined, LoadingOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons';
import { useAgentStore } from '@/stores/useAgentStore';
import { agentService } from '@/services/agentService';
import { sessionService } from '@/services/sessionService';
import type { Agent } from '@/types/agent';
import { useChatSocket } from './useChatSocket';
import type { ChatMsg, Segment } from './useChatSocket';
import { getUserName } from '@/services/authUser';
import ConfigNav from './sidebar/ConfigNav';
import SessionList from './sidebar/SessionList';
import BasicInfoPanel from './panels/BasicInfoPanel';
import BaseConfigPanel from './panels/BaseConfigPanel';
import ToolConfigPanel from './panels/ToolConfigPanel';
import SkillConfigPanel from './panels/SkillConfigPanel';
import s from './index.module.less';

// ─── Time formatting ────────────────────────────────
function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

/**
 * Format a message timestamp for display.
 *   Today        → 14:22
 *   Yesterday    → 昨天 14:22
 *   This year    → 6月10日 14:22
 *   Older        → 2024/12/25 09:30
 * Hover title shows full YYYY/M/D HH:mm:ss.
 */
function formatMsgTime(timestamp?: string): { label: string; title: string } {
  if (!timestamp) return { label: '', title: '' };
  const d = new Date(timestamp);
  if (isNaN(d.getTime())) return { label: '', title: '' };

  const now = new Date();
  const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;

  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return { label: hhmm, title: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` };
  }

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) {
    return { label: `昨天 ${hhmm}`, title: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` };
  }

  const full = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const sameYear = d.getFullYear() === now.getFullYear();
  if (sameYear) {
    const dateLabel = `${d.getMonth() + 1}月${d.getDate()}日 ${hhmm}`;
    return { label: dateLabel, title: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${full}` };
  }

  const dateLabel = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${hhmm}`;
  return { label: dateLabel, title: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${full}` };
}

// ─── Types ────────────────────────────────────────
type SidebarTab = 'session' | 'config';
type RightView = 'chat' | 'configPanel' | 'configFile';

// ─── Panel titles map ────────────────────────────
const PANEL_TITLES: Record<string, string> = {
  info: '基本信息',
  base: '基础配置',
  tool: '工具配置（MCP）',
  skill: '技能配置（Skill）',
  session: '会话设置',
  wecom: '企微连接',
};

// ─── Main Component ──────────────────────────────
export default function EditAgentPage() {
  const { agentId, sessionId } = useParams<{ agentId: string; sessionId?: string }>();
  const navigate = useNavigate();
  const agents = useAgentStore((s) => s.agents);

  // Resolve the agent by id. Seed from the store (instant when arriving from
  // the list) and confirm/refresh via the API so a direct visit or refresh of
  // /chat/:agentId also works.
  const seeded = agents.find((a) => a.id === agentId) ?? null;
  const [agent, setAgent] = useState<Agent | null>(seeded);
  const [agentLoading, setAgentLoading] = useState(seeded === null);

  useEffect(() => {
    if (!agentId) {
      setAgent(null);
      setAgentLoading(false);
      return;
    }
    setAgentLoading(true);
    agentService
      .get(agentId)
      .then((res) => setAgent(res.data))
      .catch(() => setAgent(null))
      .finally(() => setAgentLoading(false));
  }, [agentId]);

  // Sidebar state
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('session');

  // Right panel state
  const [activePanel, setActivePanel] = useState<string | null>(null);
  const [rightView, setRightView] = useState<RightView>('chat');

  // Sessions (sidebar) + chat input.
  const [sessions, setSessions] = useState<{ id: string; name: string }[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [artifactTab, setArtifactTab] = useState<'browser' | 'file'>('browser');

  // Config file state (personal agent)
  const [configFileName, setConfigFileName] = useState('CLAUDE.md');
  const [configFileContent, setConfigFileContent] = useState('');

  // Session settings toggles
  const [sessionSettings, setSessionSettings] = useState({
    upload: true, effort: true, context: true,
  });

  // Effect preview modal
  const [effectPreview, setEffectPreview] = useState<string | null>(null);

  // ─── Data loading ────────────────────────────────
  useEffect(() => {
    if (!agentId) return;
    sessionService
      .list(agentId)
      .then((res) => setSessions((res.data ?? []).map((s) => ({ id: s.id, name: s.name }))))
      .catch(() => { /* logged by interceptor */ });
  }, [agentId]);

  // ─── Streaming chat over WebSocket ───────────────
  // `handleSessionCreated` updates the URL when a session is created on the
  // first message; the URL change makes sessionId non-empty, which opens the
  // socket inside the hook.
  const handleSessionCreated = useCallback(
    (id: string) => {
      if (agentId) navigate(`/chat/${agentId}/${id}`, { replace: true });
      // Optimistic update: add new session immediately
      setSessions(prev => {
        if (prev.some(s => s.id === id)) return prev;
        return [...prev, { id, name: '新会话' }];
      });
      // Then refresh from API
      sessionService.list(agentId!).then((res) => {
        setSessions((res.data ?? []).map((s) => ({ id: s.id, name: s.name })));
      }).catch(() => {});
    },
    [agentId, navigate],
  );
  const { messages, streaming, artifacts, send, stop, clear } = useChatSocket(
    agentId,
    sessionId,
    handleSessionCreated,
  );

  const handleResetContext = useCallback(() => {
    if (!sessionId) return;
    fetch(`/api/v1/sessions/${sessionId}/reset-context?user=${encodeURIComponent(getUserName() ?? '')}`, { method: 'POST' })
      .then(() => {
        stop();  // kill current Claude client so next msg starts fresh
        message.success('上下文已重置');
      })
      .catch(() => message.error('重置失败'));
  }, [sessionId, stop]);

  const handleSend = () => {
    const text = chatInput;
    if (!text.trim()) return;
    if (!sessionId) {
      // No session yet: create it + switch the route, but keep the text in the
      // input box (don't clear, don't send). The socket opens for the new
      // session; the user presses send again to actually send.
      void send(text);
      return;
    }
    setChatInput('');
    void send(text);
  };

  if (agentLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Spin />
      </div>
    );
  }

  if (!agentId || !agent) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Empty description="智能体不存在" />
        <Button style={{ marginLeft: 16 }} onClick={() => navigate('/')}>返回列表</Button>
      </div>
    );
  }

  const isSystem = agent.type === 'system';

  // ─── Handlers (agentId is guaranteed from here on) ───
  const handlePanelChange = (panel: string) => {
    setActivePanel(panel);
    setRightView('configPanel');
  };

  const handleSessionSelect = (id: string) => {
    setSidebarTab('session');
    setRightView('chat');
    navigate(`/chat/${agentId}/${id}`);
  };

  const handleNewSession = () => {
    // Navigate to chat without a session — first message will create one.
    setSidebarTab('session');
    setRightView('chat');
    // Use a timestamp param to force React Router to treat it as a new route,
    // even when clicking "新建会话" while already on the no-session page.
    navigate(`/chat/${agentId}?t=${Date.now()}`, { replace: true });
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await sessionService.remove(id);
    } catch { /* logged by interceptor */ }
    const res = await sessionService.list(agentId).catch(() => null);
    if (res) setSessions((res.data ?? []).map((s) => ({ id: s.id, name: s.name })));
    if (id === sessionId) navigate(`/chat/${agentId}?t=${Date.now()}`, { replace: true });
  };

  // File tree handler (personal agent)
  const handleFileSelect = (name: string, content: string) => {
    setConfigFileName(name);
    setConfigFileContent(content);
    setRightView('configFile');
  };

  const sidebarSessions = sessions.map((s) => ({ ...s, active: s.id === sessionId }));
  const activeSession = sidebarSessions.find((s) => s.active) || null;

  return (
    <div className={s.editPage}>
      {/* ═══ Left Sidebar ═══ */}
      <div className={s.sidebar} data-type={agent.type}>
        {/* Header */}
        <div className={s.sidebarHeader}>
          <Button type="text" size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} />
          <span className={s.sidebarTitle}>{agent.name}</span>
          <Tag color={isSystem ? 'blue' : 'purple'} style={{ fontSize: 10, lineHeight: '16px', margin: 0, flexShrink: 0 }}>
            {isSystem ? '系统虾' : '个人虾'}
          </Tag>
        </div>

        {/* Tabs */}
        <div className={s.sidebarTabs}>
          <div className={`${s.sidebarTab} ${sidebarTab === 'session' ? s.active : ''}`} onClick={() => { setSidebarTab('session'); setRightView('chat'); }}>
            <MessageOutlined /> 会话
          </div>
          <div className={`${s.sidebarTab} ${sidebarTab === 'config' ? s.active : ''}`} onClick={() => setSidebarTab('config')}>
            {isSystem ? <><SettingOutlined /> 配置</> : <><FileTextOutlined /> 配置</>}
          </div>
        </div>

        {/* Session view */}
        {sidebarTab === 'session' && (
          <SessionList sessions={sidebarSessions} onNew={handleNewSession} onSelect={handleSessionSelect} onDelete={handleDeleteSession} />
        )}

        {/* Config view */}
        {sidebarTab === 'config' && isSystem && (
          <ConfigNav activePanel={activePanel || ''} onPanelChange={handlePanelChange} />
        )}

        {/* Personal config: file tree */}
        {sidebarTab === 'config' && !isSystem && (
          <PersonalFileTree onFileSelect={handleFileSelect} />
        )}

        {/* Footer */}
        <div className={s.sidebarFooter}>
          <Button type="text" size="small" block icon={<AppstoreOutlined />} onClick={() => navigate('/')}>所有智能体</Button>
        </div>
      </div>

      {/* ═══ Right Content ═══ */}
      <div className={s.mainContent}>
        {/* Chat Panel */}
        {rightView === 'chat' && (
          <ChatPanel
            agentName={agent.name}
            agentType={agent.type}
            sessionName={activeSession?.name || ''}
            hasSession={!!sessionId}
            messages={messages}
            streaming={streaming}
            chatInput={chatInput}
            onChatInputChange={setChatInput}
            onSend={handleSend}
            onStop={stop}
            onClear={clear}
            artifactOpen={artifactOpen}
            artifactTab={artifactTab}
            artifacts={artifacts}
            onToggleArtifact={() => setArtifactOpen(!artifactOpen)}
            onArtifactTabChange={setArtifactTab}
            sessionId={sessionId}
            onResetContext={handleResetContext}
          />
        )}

        {/* Config File Editor (personal) */}
        {rightView === 'configFile' && (
          <ConfigFileEditorPanel fileName={configFileName} content={configFileContent} onContentChange={setConfigFileContent} />
        )}

        {/* Config Panels (system) */}
        {rightView === 'configPanel' && activePanel && (
          <>
            {/* Panel Title Bar */}
            <div style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '12px 24px', flexShrink: 0 }}>
              <span style={{ fontWeight: 500, fontSize: 14 }}>{PANEL_TITLES[activePanel] || activePanel}</span>
            </div>
            {/* Panel Body */}
            <div className={s.configBody}>
              {activePanel === 'info' && <BasicInfoPanel agentId={agentId} agent={agent} />}
              {activePanel === 'base' && <BaseConfigPanel agentId={agentId} />}
              {activePanel === 'tool' && <ToolConfigPanel agentId={agentId} />}
              {activePanel === 'skill' && <SkillConfigPanel agentId={agentId} />}
              {activePanel === 'session' && (
                <SessionSettingsPanel settings={sessionSettings} onChange={setSessionSettings} onPreview={setEffectPreview} />
              )}
              {activePanel === 'wecom' && agent && <WeComPanel agent={agent} agentId={agentId!} />}
            </div>
          </>
        )}
      </div>

      {/* Effect Preview Modal */}
      <Modal open={!!effectPreview} onCancel={() => setEffectPreview(null)} footer={null} title="效果预览" width={500}>
        {effectPreview === 'upload' && (
          <div style={{ padding: 24, border: '1px dashed #d9d9d9', borderRadius: 8, textAlign: 'center' }}>
            <div style={{ marginBottom: 16, color: '#00000073', fontSize: 13 }}>附件上传区域</div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <Tag color="blue">📄 report.pdf</Tag>
              <Button size="small">添加附件</Button>
            </div>
            <div style={{ marginTop: 12, fontSize: 12, color: '#00000040' }}>支持 PDF、Word、Excel、图片、文本文件，单文件最大 20MB</div>
          </div>
        )}
        {effectPreview === 'effort' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
            {[
              { level: 1, label: '简单', desc: '快速响应，低消耗' },
              { level: 2, label: '标准', desc: '平衡质量与速度', active: true },
              { level: 3, label: '困难', desc: '深度思考，高准确度' },
            ].map((e) => (
              <div key={e.level} style={{
                padding: 16, borderRadius: 8, textAlign: 'center',
                border: e.active ? '2px solid #1677ff' : '1px solid #d9d9d9',
                background: e.active ? '#e6f4ff' : '#fff',
              }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: e.active ? '#1677ff' : '#00000040' }}>{e.level}</div>
                <div style={{ fontWeight: 600, fontSize: 14, marginTop: 4 }}>{e.label}</div>
                <div style={{ fontSize: 12, color: '#00000073', marginTop: 4 }}>{e.desc}</div>
              </div>
            ))}
          </div>
        )}
        {effectPreview === 'context' && (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Button danger style={{ marginRight: 16 }}>清除历史消息</Button>
            <Button type="primary">重置上下文</Button>
            <div style={{ marginTop: 12, fontSize: 12, color: '#ff4d4f' }}>⚠️ 此操作不可撤销</div>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════

// ─── Chat Panel ─────────────────────────────────
function ChatPanel({ agentName, agentType, sessionName, hasSession, messages, streaming, chatInput, onChatInputChange, onSend, onStop, onClear, artifactOpen, artifactTab, artifacts, onToggleArtifact, onArtifactTabChange, sessionId, onResetContext }: {
  agentName: string; agentType: string; sessionName: string;
  hasSession: boolean;
  messages: ChatMsg[];
  streaming: boolean;
  chatInput: string; onChatInputChange: (v: string) => void; onSend: () => void; onStop: () => void;
  onClear: () => void; artifactOpen: boolean; artifactTab: 'browser' | 'file';
  artifacts: { name: string; path: string; size: number }[];
  onToggleArtifact: () => void; onArtifactTabChange: (t: 'browser' | 'file') => void;
  sessionId?: string; onResetContext?: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showNewMsgBtn, setShowNewMsgBtn] = useState(false);
  const prevMsgCountRef = useRef(0);

  // Threshold: considered "near bottom" if within 30px
  const NEAR_BOTTOM_PX = 30;

  const checkNearBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    setIsNearBottom(atBottom);
    if (atBottom) setShowNewMsgBtn(false);
  };

  const scrollToBottom = (smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'instant' });
    setShowNewMsgBtn(false);
    setIsNearBottom(true);
  };

  // Auto-scroll when new messages arrive (only if user is near bottom)
  useEffect(() => {
    if (messages.length === prevMsgCountRef.current) return;
    prevMsgCountRef.current = messages.length;

    if (isNearBottom) {
      // Use requestAnimationFrame to wait for DOM render
      requestAnimationFrame(() => scrollToBottom(false));
    } else {
      setShowNewMsgBtn(true);
    }
  }, [messages.length, isNearBottom]);

  // During streaming, keep scrolling if user was at bottom
  useEffect(() => {
    if (streaming && isNearBottom) {
      requestAnimationFrame(() => scrollToBottom(false));
    }
  }, [messages, streaming, isNearBottom]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {hasSession ? (
        <>
          {/* Header */}
          <div style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <span style={{ fontSize: 13, color: '#00000073' }}>
              <MessageOutlined /> {sessionName}
              {streaming ? <span style={{ marginLeft: 8, color: '#1677ff' }}>· 正在思考…</span> : null}
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              <Popconfirm title="清空所有对话？" onConfirm={onClear}>
                <Button size="small">清空对话</Button>
              </Popconfirm>
              <Button size="small" icon={<ColumnWidthOutlined />} onClick={onToggleArtifact} />
            </div>
          </div>
          <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
            {/* Messages */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0, position: 'relative' }}>
              <div ref={scrollRef} onScroll={checkNearBottom} style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
                {messages.map((msg) => {
                  const isUser = msg.role === 'user';
                  const { label: timeLabel, title: timeTitle } = formatMsgTime(msg.timestamp);
                  const hasSegments = !isUser && msg.segments && msg.segments.length > 0;
                  return (
                    <div key={msg.id} style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 16 }}>
                      <div style={isUser
                        ? { maxWidth: '70%', display: 'flex', flexDirection: 'column', gap: 2 }
                        : { width: '70%', minWidth: 320, display: 'flex', flexDirection: 'column', gap: hasSegments ? 8 : 2, flexShrink: 0 }
                      }>
                        {timeLabel ? (
                          <div style={{ fontSize: 13, color: '#00000073', textAlign: isUser ? 'right' : 'left', padding: '0 4px' }} title={timeTitle}>
                            {timeLabel}
                            {!isUser && msg.durationMs != null ? (
                              <span style={{ marginLeft: 8, color: '#00000040' }}>
                                执行耗时: {msg.durationMs >= 1000
                                  ? `${(msg.durationMs / 1000).toFixed(1)}s`
                                  : `${msg.durationMs}ms`}
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                        {isUser ? (
                          /* User message: simple bubble */
                          <div style={{
                            padding: '10px 16px', borderRadius: 12, fontSize: 14, lineHeight: 1.6,
                            background: '#1677ff', color: '#fff', whiteSpace: 'pre-wrap',
                          }}>
                            {msg.content}
                          </div>
                        ) : hasSegments ? (
                          /* Assistant with segments: group reasoning+tool into ThinkingBlock, text segments separate */
                          <SegmentGroup segments={msg.segments!} pending={msg.pending} />
                        ) : (
                          /* Assistant fallback (no segments / old messages) */
                          <>
                            {msg.reasoning ? (
                              <div style={{ fontSize: 12, color: '#00000073', background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 8, padding: '8px 12px', whiteSpace: 'pre-wrap' }}>
                                <div style={{ fontWeight: 500, marginBottom: 4 }}>🧠 思考过程</div>
                                {msg.reasoning}
                              </div>
                            ) : null}
                            <div style={{
                              padding: '6px 16px', borderRadius: 12, fontSize: 14, lineHeight: 1.6,
                              background: '#f5f5f5', color: '#000000e0',
                            }}>
                              <ReactMarkdown components={{ code: CodeBlock }}>{msg.content}</ReactMarkdown>
                              {msg.pending ? <TypingDots /> : null}
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              {/* Floating "new messages" button */}
              {showNewMsgBtn && (
                <div style={{ position: 'absolute', bottom: 80, left: '50%', transform: 'translateX(-50%)', zIndex: 10 }}>
                  <Button
                    type="primary"
                    shape="round"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    onClick={() => scrollToBottom(true)}
                    style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
                  >
                    新消息
                  </Button>
                </div>
              )}
              <ChatInputArea value={chatInput} onChange={onChatInputChange} onSend={onSend} onStop={onStop} streaming={streaming} sessionId={sessionId} onResetContext={onResetContext} />
            </div>
            {/* Artifact sidebar */}
            {artifactOpen && <ArtifactSidebar tab={artifactTab} artifacts={artifacts} onTabChange={onArtifactTabChange} onClose={onToggleArtifact} />}
          </div>
        </>
      ) : (
        /* Empty state */
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, padding: '32px 24px' }}>
          <div style={{ width: 40, height: 40, borderRadius: '50%', background: agentType === 'system' ? '#e6f4ff' : '#f3e8ff', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
            {agentType === 'system' ? <RobotOutlined style={{ color: '#1677ff' }} /> : <UserOutlined style={{ color: '#722ed1' }} />}
          </div>
          <p style={{ fontSize: 14, color: '#00000073', marginBottom: 4 }}>{agentName}</p>
          <p style={{ fontSize: 12, color: '#00000040', marginBottom: 24 }}>
            <span style={{ fontWeight: 500, color: '#000000a6' }}>{agentName}</span> · {agentType === 'system' ? '系统虾' : '个人虾'}
          </p>
          <div style={{ width: '100%', maxWidth: 640 }}>
            <ChatInputArea value={chatInput} onChange={onChatInputChange} onSend={onSend} onStop={onStop} streaming={streaming} large />
            <p style={{ fontSize: 12, textAlign: 'center', color: '#00000040', marginTop: 8 }}>Enter 发送 · Shift+Enter 换行</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Chat Input Area ─────────────────────────────
function ChatInputArea({ value, onChange, onSend, onStop, streaming, large, sessionId, onResetContext }: {
  value: string; onChange: (v: string) => void; onSend: () => void; onStop: () => void;
  streaming?: boolean; large?: boolean; sessionId?: string; onResetContext?: () => void;
}) {
  // Button logic:
  //   streaming + input empty → show stop button
  //   streaming + input has text → show send button (queue next message)
  //   not streaming → show send button (normal)
  const inputHasText = value.trim().length > 0;
  const showStop = streaming && !inputHasText;
  const canSend = inputHasText;

  return (
    <div style={{ flexShrink: 0, background: '#fff', borderTop: '1px solid #f0f0f0', padding: large ? 0 : '16px 24px' }}>
      <div style={{ maxWidth: large ? '100%' : 1152, margin: large ? undefined : '0 auto' }}>
        <div style={{ border: '1px solid #d9d9d9', borderRadius: 12, transition: 'all 0.2s' }}>
          <Input.TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="发送消息…"
            autoSize={{ minRows: large ? 5 : 3, maxRows: 9 }}
            style={{ border: 'none', boxShadow: 'none', resize: 'none', padding: '12px 16px 4px', borderRadius: 12 }}
            onPressEnter={(e) => { if (!e.shiftKey && canSend) { e.preventDefault(); onSend(); } }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 16px 10px' }}>
            <div style={{ display: 'flex', gap: 12, color: '#00000040', fontSize: 14, alignItems: 'center' }}>
              <PaperClipOutlined style={{ cursor: 'pointer' }} />
              {sessionId && onResetContext ? (
                <Popconfirm title="清空上下文将重置工作区的 CLAUDE.md 和 skills，不删除聊天记录" onConfirm={onResetContext}>
                  <Button size="small" type="text" style={{ fontSize: 12, color: '#00000073', padding: '0 4px' }}>
                    🗑 清空上下文
                  </Button>
                </Popconfirm>
              ) : null}
            </div>
            {showStop ? (
              <Button
                danger
                size="small"
                icon={<StopOutlined />}
                onClick={onStop}
              >
                停止
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                icon={<SendOutlined />}
                onClick={onSend}
                disabled={!canSend}
              >
                发送
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Artifact Sidebar ────────────────────────────
function ArtifactSidebar({ tab, artifacts, onTabChange, onClose }: {
  tab: 'browser' | 'file'; artifacts: { name: string; path: string; size: number }[]; onTabChange: (t: 'browser' | 'file') => void; onClose: () => void;
}) {
  const { sessionId } = useParams<{ sessionId?: string }>();
  const [files, setFiles] = useState<{ name: string; path: string; size: number }[]>([]);

  // Fetch file list from API on open
  useEffect(() => {
    if (!sessionId || tab !== 'file') return;
    fetch(`/api/v1/files/${sessionId}?user=${encodeURIComponent(getUserName() ?? '')}`)
      .then(r => r.json())
      .then(data => { if (Array.isArray(data)) setFiles(data); })
      .catch(() => {});
  }, [sessionId, tab, artifacts]);

  const downloadUrl = (path: string) => `/api/v1/files/${sessionId}/download?path=${encodeURIComponent(path)}&user=${encodeURIComponent(getUserName() ?? '')}`;

  // Resizable sidebar
  const [sideWidth, setSideWidth] = useState(420);
  const dragRef = useRef(false);
  const MIN_W = 280;
  const MAX_W = Math.max(MIN_W, window.innerWidth * 0.5);
  const onMouseDown = useCallback(() => { dragRef.current = true; }, []);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const w = window.innerWidth - e.clientX;
      setSideWidth(Math.max(MIN_W, Math.min(MAX_W, w)));
    };
    const onUp = () => { dragRef.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [MAX_W]);

  return (
    <div style={{ width: sideWidth, flexShrink: 0, display: 'flex', position: 'relative' }}>
      {/* Drag handle */}
      <div
        onMouseDown={onMouseDown}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.width = '5px';
          (e.currentTarget as HTMLElement).style.background = '#d9d9d9';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.width = '4px';
          (e.currentTarget as HTMLElement).style.background = 'transparent';
        }}
        style={{
          width: 4, cursor: 'col-resize', flexShrink: 0,
          background: 'transparent', zIndex: 10, transition: 'width 0.1s, background 0.1s',
        }}
      />
      <div style={{ flex: 1, borderLeft: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', background: '#fff', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          <Button size="small" type={tab === 'browser' ? 'primary' : 'text'} icon={<GlobalOutlined />} onClick={() => onTabChange('browser')}>浏览器</Button>
          <Button size="small" type={tab === 'file' ? 'primary' : 'text'} icon={<FileOutlined />} onClick={() => onTabChange('file')}>文件</Button>
        </div>
        <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
      </div>
      {tab === 'browser' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', gap: 8, padding: '8px 12px', borderBottom: '1px solid #f0f0f0', background: '#fafafa' }}>
            <Input size="small" placeholder="输入URL" style={{ flex: 1 }} />
            <Button size="small" type="primary">跳转</Button>
          </div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#00000040', fontSize: 13 }}>
            浏览器预览区域
          </div>
        </div>
      )}
      {tab === 'file' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid #f0f0f0' }}>
            <span style={{ fontWeight: 500, fontSize: 14 }}>生成文件 · {files.length}</span>
          </div>
          <div style={{ flex: 1, overflow: 'auto' }}>
            {files.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', color: '#00000040', fontSize: 13 }}>暂无生成文件</div>
            ) : (
              files.map((f, i) => (
                <FileRow key={i} name={f.name} path={f.path} size={f.size} downloadUrl={downloadUrl(f.path)} />
              ))
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  );
}

// ─── Config File Editor Panel (personal) ─────────
function ConfigFileEditorPanel({ fileName, content, onContentChange }: {
  fileName: string; content: string; onContentChange: (v: string) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '12px 24px', display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14 }}>
          <CodeOutlined style={{ color: '#1677ff' }} />
          <span style={{ fontWeight: 500 }}>{fileName}</span>
          <span style={{ color: '#00000040', fontSize: 12 }}>.claude/</span>
        </div>
        <span style={{ fontSize: 12, color: '#52c41a' }}>● 已保存</span>
      </div>
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 24, background: '#fafafa' }}>
        <Input.TextArea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          placeholder="在此编辑文件内容…"
          style={{ flex: 1, fontFamily: 'monospace', lineHeight: 1.6, resize: 'none' }}
        />
      </div>
    </div>
  );
}

// ─── Personal File Tree ──────────────────────────
function PersonalFileTree({ onFileSelect }: { onFileSelect: (name: string, content: string) => void }) {
  const files = [
    { name: 'CLAUDE.md', icon: <FileTextOutlined style={{ color: '#1677ff' }} />, content: '# CLAUDE.md\n你是一个专业的业务智能助手...' },
    { name: 'settings.json', icon: <CodeOutlined style={{ color: '#52c41a' }} />, content: '{\n  "preset": "auto",\n  "editMode": "auto"\n}' },
    { name: 'commands/weekly-report.md', icon: <FileTextOutlined style={{ color: '#faad14' }} />, content: '# weekly-report skill\n生成每周VOC周报' },
    { name: 'hooks/post-push.sh', icon: <CodeOutlined style={{ color: '#722ed1' }} />, content: '#!/bin/bash\necho "post-push hook"' },
    { name: 'memory/user.md', icon: <FileOutlined style={{ color: '#00000073' }} />, content: '# User preferences\n- 输出中文' },
  ];
  return (
    <div className={s.sidebarBody} style={{ padding: '4px 8px' }}>
      <div style={{ fontSize: 11, color: '#00000040', padding: '4px', fontWeight: 500, marginBottom: 4 }}>文件夹</div>
      <div style={{ fontSize: 11, color: '#00000073', padding: '4px 8px', fontWeight: 500, fontFamily: 'monospace' }}>.claude/</div>
      {files.map((f) => (
        <div
          key={f.name}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px 6px 24px', borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#000000a6', transition: 'all 0.15s' }}
          onClick={() => onFileSelect(f.name, f.content)}
          onMouseEnter={(e) => { e.currentTarget.style.background = '#e6f4ff'; e.currentTarget.style.color = '#1677ff'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = ''; e.currentTarget.style.color = '#000000a6'; }}
        >
          {f.icon} <span>{f.name}</span>
        </div>
      ))}
      <div style={{ marginTop: 12 }}>
        <Button type="dashed" size="small" block icon={<PlusOutlined />}>新建文件</Button>
      </div>
    </div>
  );
}

// ─── Panel: Session Settings ─────────────────────
function SessionSettingsPanel({ settings, onChange, onPreview }: {
  settings: { upload: boolean; effort: boolean; context: boolean };
  onChange: (s: { upload: boolean; effort: boolean; context: boolean }) => void;
  onPreview: (type: string) => void;
}) {
  const items = [
    { key: 'upload' as const, label: '上传附件', desc: '允许用户在会话中上传附件' },
    { key: 'effort' as const, label: 'Effort自定义', desc: '允许用户自定义处理复杂度等级' },
    { key: 'context' as const, label: '手动清除上下文', desc: '允许用户手动清除会话历史和上下文' },
  ];
  return (
    <FormCard>
      <h4 style={{ fontWeight: 600, marginBottom: 24 }}>会话设置</h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {items.map((item) => (
          <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 16, border: '1px solid #d9d9d9', borderRadius: 8 }}>
            <div>
              <div style={{ fontWeight: 500, fontSize: 14 }}>{item.label}</div>
              <p style={{ fontSize: 12, color: '#00000073', marginTop: 4 }}>{item.desc}</p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Button type="link" size="small" onClick={() => onPreview(item.key)}>【效果】</Button>
              <Switch checked={settings[item.key]} onChange={(v) => onChange({ ...settings, [item.key]: v })} />
            </div>
          </div>
        ))}
      </div>
    </FormCard>
  );
}

// ─── Panel: WeChat iLink ─────────────────────────
function WeChatPanel({ agent, agentId }: { agent: Agent; agentId: string }) {
  const [loginStatus, setLoginStatus] = useState<string>('disconnected');
  const [ilinkUserId, setIlinkUserId] = useState<string | null>(null);
  const [qrcodeImg, setQrcodeImg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [enabled, setEnabled] = useState(agent.wechatEnabled ?? false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load current status on mount
  useEffect(() => {
    agentService.getWechatStatus(agentId).then((res: any) => {
      const d = res.data;
      setLoginStatus(d.loginStatus);
      setIlinkUserId(d.ilinkUserId ?? null);
      setEnabled(d.enabled);
    }).catch(() => {});
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [agentId]);

  // ─── QR Code Login ────────────────────────────
  const startLogin = async () => {
    setLoading(true);
    try {
      const res: any = await agentService.startWechatLogin(agentId);
      const d = res.data;
      setQrcodeImg(d.qrcodeImg);
      setLoginStatus(d.loginStatus);

      // Poll status every 2s
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const r: any = await agentService.pollWechatLogin(agentId);
          const s = r.data;
          setLoginStatus(s.loginStatus);
          if (s.loginStatus === 'confirmed') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setIlinkUserId(s.ilinkUserId ?? null);
            setQrcodeImg(null);
            setEnabled(true);
            message.success('微信已连接');
          } else if (s.loginStatus === 'expired') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setQrcodeImg(null);
          }
        } catch { /* polling continues on error */ }
      }, 2000);
    } catch {
      message.error('获取二维码失败');
    } finally {
      setLoading(false);
    }
  };

  // ─── Disconnect ──────────────────────────────
  const disconnect = async () => {
    setLoading(true);
    try {
      await agentService.disconnectWechat(agentId);
      setLoginStatus('disconnected');
      setIlinkUserId(null);
      setQrcodeImg(null);
      setEnabled(false);
      message.success('已断开微信连接');
    } catch {
      message.error('断开失败');
    } finally {
      setLoading(false);
    }
  };

  // ─── Toggle ──────────────────────────────────
  const toggleEnabled = async (v: boolean) => {
    if (v && loginStatus !== 'confirmed') {
      // Need to login first
      await startLogin();
      return;
    }
    setLoading(true);
    try {
      await agentService.toggleWechat(agentId, v);
      setEnabled(v);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    } finally {
      setLoading(false);
    }
  };

  // ─── Render ──────────────────────────────────
  const statusLabel: Record<string, { text: string; color: string }> = {
    disconnected: { text: '未连接', color: '#00000040' },
    pending: { text: '等待扫码', color: '#faad14' },
    scanned: { text: '已扫码，请确认', color: '#1677ff' },
    confirmed: { text: '已连接', color: '#52c41a' },
    expired: { text: '二维码已过期', color: '#ff4d4f' },
  };
  const s = statusLabel[loginStatus] ?? statusLabel.disconnected;

  return (
    <FormCard>
      <h4 style={{ fontWeight: 600, marginBottom: 24 }}>微信绑定</h4>

      {/* Toggle */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: 16, border: '1px solid #d9d9d9', borderRadius: 8, marginBottom: 16 }}>
        <div>
          <div style={{ fontWeight: 500 }}>
            微信连接
            <Tag color={s.color === '#52c41a' ? 'success' : s.color === '#ff4d4f' ? 'error' : s.color === '#faad14' ? 'warning' : 'default'} style={{ marginLeft: 8 }}>{s.text}</Tag>
          </div>
          <p style={{ fontSize: 12, color: '#00000073', marginTop: 4 }}>
            {loginStatus === 'confirmed'
              ? `已绑定: ${ilinkUserId || '(未知用户)'}`
              : '扫码即可在微信中使用 Vera Agent'}
          </p>
        </div>
        {loginStatus === 'confirmed' ? (
          <Button danger size="small" loading={loading} onClick={disconnect}>断开</Button>
        ) : (
          <Button type="primary" size="small" loading={loading} onClick={() => toggleEnabled(true)}>
            扫码绑定
          </Button>
        )}
      </div>

      {/* QR Code */}
      {(loginStatus === 'pending' || loginStatus === 'scanned') && qrcodeImg && (
        <div style={{ textAlign: 'center', padding: 24, border: '1px solid #d9d9d9', borderRadius: 8, marginBottom: 16 }}>
          <img
            src={`data:image/png;base64,${qrcodeImg}`}
            alt="微信扫码"
            style={{ width: 200, height: 200, imageRendering: 'pixelated' }}
          />
          <p style={{ marginTop: 12, fontSize: 14, color: '#1677ff', fontWeight: 500 }}>
            {loginStatus === 'scanned' ? '✓ 已扫码，请在手机上确认登录' : '请使用微信扫描二维码'}
          </p>
          <p style={{ fontSize: 12, color: '#00000073' }}>
            二维码有效期为 5 分钟
          </p>
        </div>
      )}

      {/* Expired */}
      {loginStatus === 'expired' && (
        <div style={{ textAlign: 'center', padding: 24, border: '1px solid #d9d9d9', borderRadius: 8, marginBottom: 16 }}>
          <p style={{ color: '#ff4d4f', fontWeight: 500 }}>二维码已过期</p>
          <Button type="primary" loading={loading} onClick={startLogin} style={{ marginTop: 8 }}>
            重新获取二维码
          </Button>
        </div>
      )}

      {/* Connected info */}
      {loginStatus === 'confirmed' && (
        <div style={{ fontSize: 12, color: '#00000073', lineHeight: 1.8, padding: '0 4px' }}>
          <p>✅ Vera 已连接到微信</p>
          <p>💬 在微信中给绑定的 Bot 发消息即可使用</p>
          <p>🔄 每用户自动创建独立会话，上下文保持</p>
          <p>📎 支持文本消息（图片/语音暂不支持）</p>
        </div>
      )}
    </FormCard>
  );
}

// Backwards-compatible alias
const WeComPanel = WeChatPanel;

// ═══ Utility Components ══════════════════════════

function FormCard({ children }: { children: React.ReactNode }) {
  return <div style={{ background: '#fff', border: '1px solid #d9d9d9', borderRadius: 8, padding: 20, marginBottom: 16 }}>{children}</div>;
}

// ─── Typing indicator ──────────────────────────────

function TypingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', marginLeft: 4 }}>
      {[0, 1, 2].map((i) => (
        <span key={i} style={{
          width: 6, height: 6, borderRadius: '50%', background: '#00000040',
          animation: `typingBounce 1.4s ${i * 0.2}s infinite ease-in-out`,
        }} />
      ))}
      <style>{`@keyframes typingBounce { 0%,60%,100% { transform:translateY(0);opacity:0.4 }
         30% { transform:translateY(-6px);opacity:1 } }`}</style>
    </span>
  );
}

// ─── File row with hover download ──────────────────

function FileRow({ name, size, downloadUrl }: { name: string; path: string; size: number; downloadUrl: string }) {
  const [hover, setHover] = useState(false);
  return (
    <a
      href={downloadUrl}
      download
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 16px', borderBottom: '1px solid #f0f0f0',
        fontSize: 12, color: 'inherit', textDecoration: 'none',
        background: hover ? '#f5f5f5' : undefined,
      }}
    >
      <FileTextOutlined style={{ color: '#1677ff', flexShrink: 0 }} />
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={name}>
        {name}
      </span>
      <span style={{
        color: '#00000040', flexShrink: 0, fontSize: 11,
        opacity: hover ? 0 : 1, transition: 'opacity 0.15s',
      }}>
        {size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`}
      </span>
      <DownloadOutlined style={{
        color: '#1677ff', flexShrink: 0, fontSize: 14,
        opacity: hover ? 1 : 0, transition: 'opacity 0.15s',
      }} />
    </a>
  );
}

// ─── Segment Rendering ────────────────────────────

/**
 * Group segments: consecutive reasoning + tool segments are merged into
 * a single ThinkingBlock; text segments are rendered separately.
 *
 * Layout: [ThinkingBlock(reasoning + tools)] [TextSegment] [TextSegment] ...
 */
function SegmentGroup({ segments, pending }: { segments: Segment[]; pending?: boolean }) {
  const groups: Array<{ type: 'thinking'; items: Segment[] } | { type: 'text'; segment: Segment }> = [];
  let thinkingBuf: Segment[] = [];

  const flushThinking = () => {
    if (thinkingBuf.length > 0) {
      groups.push({ type: 'thinking', items: thinkingBuf });
      thinkingBuf = [];
    }
  };

  for (const seg of segments) {
    if (seg.kind === 'reasoning' || seg.kind === 'tool') {
      thinkingBuf.push(seg);
    } else {
      flushThinking();
      groups.push({ type: 'text', segment: seg });
    }
  }
  flushThinking();

  return (
    <>
      {groups.map((g, gi) => {
        if (g.type === 'thinking') {
          return <ThinkingBlock key={gi} items={g.items} pending={pending} />;
        }
        return <TextSegment key={gi} text={(g.segment as Extract<Segment, { kind: 'text' }>).text} />;
      })}
      {pending ? <TypingDots /> : null}
    </>
  );
}

/** Unified collapsible thinking block — renders segments in original order */
function ThinkingBlock({ items, pending }: { items: Segment[]; pending?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  const toolParts = items.filter((s) => s.kind === 'tool');
  const hasContent = items.length > 0;

  return (
    <div style={{
      width: '100%',
      fontSize: 12, color: '#6b5ce7', background: '#f8f6ff',
      border: '1px solid #e8e0ff', borderRadius: 8, overflow: 'hidden',
    }}>
      <div
        onClick={() => setCollapsed(!collapsed)}
        style={{
          fontWeight: 500, padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 6,
          cursor: hasContent ? 'pointer' : 'default', userSelect: 'none',
        }}
      >
        <ThunderboltOutlined />
        思考过程
        {pending && !hasContent ? <LoadingOutlined style={{ fontSize: 10 }} /> : null}
        {toolParts.length > 0 ? (
          <span style={{ fontSize: 11, color: '#6b5ce780', fontWeight: 400 }}>· {toolParts.length} 次工具调用</span>
        ) : null}
        {hasContent ? (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6b5ce780' }}>{collapsed ? '展开' : '收起'}</span>
        ) : null}
      </div>

      {!collapsed ? (
        <div style={{ padding: '4px 0 8px' }}>
          {items.length === 0 && pending ? (
            <div style={{ padding: '8px 12px' }}>思考中…</div>
          ) : null}
          {items.map((seg, i) => {
            if (seg.kind === 'reasoning') {
              return <ReasoningStep key={i} text={seg.text} isLast={i === items.length - 1} pending={pending} source={seg.source} />;
            }
            if (seg.kind === 'tool') {
              return (
                <div key={i} style={{ margin: '6px 8px' }}>
                  <ToolCard segment={seg as Extract<Segment, { kind: 'tool' }>} />
                </div>
              );
            }
            return null;
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Single thinking step — individually collapsible, bordered card */
function ReasoningStep({ text, pending, source }: { text: string; isLast?: boolean; pending?: boolean; source?: 'reasoning' | 'content' }) {
  const [collapsed, setCollapsed] = useState(true);
  if (!text && !pending) return null;
  const isThinking = source === 'reasoning' || !source;
  const label = isThinking ? '🧠 推理' : '📝 回复草稿';
  const bg = isThinking ? '#f8f6ff' : '#fffbe6';
  const border = isThinking ? '#d9d9ff' : '#ffe58f';
  const topBg = isThinking ? '#f8f6ff' : '#fffbe6';
  const color = isThinking ? '#6b5ce7' : '#ad8b00';
  return (
    <div style={{
      margin: '6px 8px',
      width: 'calc(100% - 16px)',
      background: bg,
      border: `1px solid ${border}`,
      borderRadius: 6,
      overflow: 'hidden',
    }}>
      <div onClick={() => text && setCollapsed(!collapsed)} style={{
        padding: '6px 10px', display: 'flex', alignItems: 'center', gap: 6,
        cursor: text ? 'pointer' : 'default', userSelect: 'none',
        background: topBg, color, fontSize: 12, fontWeight: 500,
      }}>
        <span>{label}</span>
        {!text && pending ? <LoadingOutlined style={{ fontSize: 10 }} /> : null}
        {text ? (
          <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 400, opacity: 0.5 }}>
            {collapsed ? '展开' : '收起'}
          </span>
        ) : null}
      </div>
      {!collapsed && text ? (
        <div style={{
          padding: '8px 10px', whiteSpace: 'pre-wrap', lineHeight: 1.6,
          color: '#000000d9', borderTop: `1px solid ${border}`,
        }}>
          {text}
null
        </div>
      ) : null}
    </div>
  );
}

/** Tool call card — collapsible args and result */
function ToolCard({ segment }: { segment: Extract<Segment, { kind: 'tool' }> }) {
  const { name, args, output, ok, done } = segment;
  const [collapsed, setCollapsed] = useState(true);
  const headerIcon = done
    ? (ok ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />)
    : <LoadingOutlined style={{ color: '#1677ff' }} />;

  const hasBody = !!(args || output);
  return (
    <div style={{ width: '100%', background: '#fff', border: '1px solid #e8e8e8', borderRadius: 6, fontSize: 12, overflow: 'hidden' }}>
      <div onClick={() => hasBody && setCollapsed(!collapsed)} style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 10px', background: '#fafafa',
        cursor: hasBody ? 'pointer' : 'default', userSelect: 'none',
        borderBottom: !collapsed && hasBody ? '1px solid #f0f0f0' : 'none',
      }}>
        {headerIcon}
        <code style={{ fontWeight: 600, fontSize: 12, color: '#000000d9' }}>{name || 'tool'}</code>
        {!done && <span style={{ color: '#1677ff', fontSize: 11 }}>执行中…</span>}
        {done && ok && <span style={{ color: '#52c41a', fontSize: 11 }}>完成</span>}
        {done && !ok && <span style={{ color: '#ff4d4f', fontSize: 11 }}>失败</span>}
        {hasBody ? (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#00000040' }}>
            {collapsed ? '展开' : '收起'}
          </span>
        ) : null}
      </div>

      {!collapsed ? (
        <>
          {args ? (
            <pre style={{
              margin: 0, padding: '6px 10px', fontSize: 11, lineHeight: 1.5,
              background: '#f5f5f5', color: '#000000a6',
              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              fontFamily: "'SFMono-Regular', Consolas, monospace",
              borderBottom: output ? '1px solid #f0f0f0' : 'none',
            }}>
              {args}
            </pre>
          ) : null}
          {output ? (
            <pre style={{
              margin: 0, padding: '6px 10px', fontSize: 11, lineHeight: 1.5,
              background: done && !ok ? '#fff2f0' : '#f5f5f5',
              color: done && !ok ? '#cf1322' : '#000000a6',
              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              fontFamily: "'SFMono-Regular', Consolas, monospace",
              maxHeight: 200, overflowY: 'auto',
            }}>
              {output}
            </pre>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** Main content text — Markdown with ECharts support */
function TextSegment({ text }: { text: string; pending?: boolean }) {
  return (
    <div style={{
      padding: '6px 16px', borderRadius: 12, fontSize: 14, lineHeight: 1.6,
      background: '#f5f5f5', color: '#000000e0',
    }}>
      <ReactMarkdown components={{ code: CodeBlock }}>{text}</ReactMarkdown>
    </div>
  );
}

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useRef(`mermaid-${Math.random().toString(36).slice(2)}`).current;
  useEffect(() => {
    if (!ref.current) return;
    mermaid.render(id, code).then(({ svg }) => {
      if (ref.current) ref.current.innerHTML = svg;
    }).catch(() => {});
  }, [code, id]);
  return <div ref={ref} style={{ margin: '8px 0', display: 'flex', justifyContent: 'center' }} />;
}

/** Custom code block — ECharts / Mermaid maps to chart, others to styled pre */
function CodeBlock({ className, children }: any) {
  const lang = className?.replace('language-', '') || '';
  const code = String(children).replace(/\n$/, '');

  if (lang === 'echarts') {
    try {
      const option = JSON.parse(code);
      return (
        <div style={{ margin: '8px 0', border: '1px solid #e8e8e8', borderRadius: 8, overflow: 'hidden' }}>
          <ReactECharts option={option} style={{ height: 320 }} />
        </div>
      );
    } catch {
      return <pre style={preStyle}>{code}</pre>;
    }
  }

  if (lang === 'mermaid') {
    return <MermaidBlock code={code} />;
  }

  return (
    <pre style={preStyle}>
      {lang ? <span style={{ color: '#00000040', fontSize: 11 }}>{lang}</span> : null}
      <code>{code}</code>
    </pre>
  );
}

const preStyle: React.CSSProperties = {
  margin: '8px 0', padding: '8px 12px', fontSize: 12, lineHeight: 1.5,
  background: '#fafafa', borderRadius: 6, overflow: 'auto',
  fontFamily: "'SFMono-Regular', Consolas, monospace",
  whiteSpace: 'pre-wrap', wordBreak: 'break-all',
};
