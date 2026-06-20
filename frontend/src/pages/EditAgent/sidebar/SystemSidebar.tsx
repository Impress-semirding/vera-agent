import { useState } from 'react';
import { Button, Tag } from 'antd';
import { ArrowLeftOutlined, MessageOutlined, SettingOutlined, AppstoreOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import SessionList from './SessionList';
import ConfigNav from './ConfigNav';
import s from '../index.module.less';

type SidebarTab = 'session' | 'config';

interface SystemSidebarProps {
  agentName: string;
  activePanel: string;
  onPanelChange: (panel: string) => void;
  sessions: { id: string; name: string; active: boolean }[];
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}

export default function SystemSidebar({
  agentName, activePanel, onPanelChange,
  sessions, onNewSession, onSelectSession, onDeleteSession,
}: SystemSidebarProps) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<SidebarTab>('session');

  return (
    <div className={s.sidebar} data-type="system">
      {/* Header */}
      <div className={s.sidebarHeader}>
        <Button type="text" size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} />
        <span className={s.sidebarTitle}>{agentName || '系统智能体'}</span>
        <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', margin: 0, flexShrink: 0 }}>Claude Code</Tag>
      </div>

      {/* Tabs */}
      <div className={s.sidebarTabs}>
        <div className={`${s.sidebarTab} ${tab === 'session' ? s.active : ''}`} onClick={() => setTab('session')}>
          <MessageOutlined /> 会话
        </div>
        <div className={`${s.sidebarTab} ${tab === 'config' ? s.active : ''}`} onClick={() => setTab('config')}>
          <SettingOutlined /> 配置
        </div>
      </div>

      {/* Session view */}
      {tab === 'session' && (
        <SessionList sessions={sessions} onNew={onNewSession} onSelect={onSelectSession} onDelete={onDeleteSession} />
      )}

      {/* Config view */}
      {tab === 'config' && (
        <ConfigNav activePanel={activePanel} onPanelChange={onPanelChange} />
      )}

      {/* Footer */}
      <div className={s.sidebarFooter}>
        <Button type="text" size="small" block icon={<AppstoreOutlined />} onClick={() => navigate('/')}>
          所有智能体
        </Button>
      </div>
    </div>
  );
}
