import { useState } from 'react';
import { Segmented, Input, Checkbox, Button, Radio, Avatar } from 'antd';
import { StarOutlined, PlusOutlined, LogoutOutlined, UserOutlined, SettingOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAgentStore } from '@/stores/useAgentStore';
import { useAuthStore } from '@/stores/useAuthStore';
import ModelConfigModal from '@/components/ModelConfigModal';
import type { AppMode } from '@/types/agent';

const MODE_OPTIONS: { label: string; value: AppMode }[] = [
  { label: 'Claude Code', value: 'claude' },
  { label: '普通模式', value: 'normal' },
];

const TYPE_FILTERS = [
  { label: '全部', value: 'all' as const },
  { label: '系统虾', value: 'system' as const },
  { label: '个人虾', value: 'personal' as const },
];

export default function AgentListHeader() {
  const navigate = useNavigate();
  const { mode, typeFilter, search, mineOnly, starredOnly, setMode, setTypeFilter, setSearch, toggleMine, toggleStarred } = useAgentStore();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [modelConfigOpen, setModelConfigOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 24px', background: '#fff', borderBottom: '1px solid #d9d9d9' }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 18, fontWeight: 600, marginRight: 16 }}>
          <StarOutlined style={{ color: '#1677ff' }} />
          <span>Vera</span>
        </div>

        {/* Mode Switcher */}
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(v) => setMode(v as AppMode)} />

        {/* Divider */}
        <div style={{ width: 1, height: 24, background: '#d9d9d9' }} />

        {/* Type Filter */}
        <Radio.Group
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          size="small"
        >
          {TYPE_FILTERS.map((f) => (
            <Radio.Button key={f.value} value={f.value}>{f.label}</Radio.Button>
          ))}
        </Radio.Group>

        {/* Quick Filters */}
        <Checkbox checked={mineOnly} onChange={toggleMine}>我创建的</Checkbox>
        <Checkbox checked={starredOnly} onChange={toggleStarred}>我收藏的</Checkbox>

        {/* Search */}
        <Input.Search
          placeholder="搜索"
          allowClear
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onSearch={() => useAgentStore.getState().fetchAgents()}
          style={{ width: 200, marginLeft: 'auto' }}
        />

        {/* Action Buttons */}
        <Button icon={<SettingOutlined />} onClick={() => setModelConfigOpen(true)}>
          模型配置
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/create')}>
          创建智能体
        </Button>

        {/* Current user + logout */}
        {user ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1677ff' }} />
            <span style={{ fontSize: 13, color: '#000000a6' }}>{user.name}</span>
            <Button type="text" size="small" icon={<LogoutOutlined />} onClick={handleLogout} title="登出" />
          </div>
        ) : null}
      </div>

      {/* Model Config Modal */}
      <ModelConfigModal open={modelConfigOpen} onClose={() => setModelConfigOpen(false)} />
    </>
  );
}
