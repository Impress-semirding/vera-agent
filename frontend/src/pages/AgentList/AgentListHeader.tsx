import { useState } from 'react';
import { Segmented, Input, Checkbox, Button, Avatar, Modal, message } from 'antd';
import { StarOutlined, PlusOutlined, LogoutOutlined, UserOutlined, SettingOutlined, SafetyOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAgentStore } from '@/stores/useAgentStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { authService } from '@/services/authService';
import ModelConfigModal from '@/components/ModelConfigModal';
import type { AppMode } from '@/types/agent';

const MODE_OPTIONS: { label: string; value: AppMode }[] = [
  { label: 'Claude Code', value: 'claude' },
  { label: '普通模式', value: 'normal' },
];

export default function AgentListHeader() {
  const navigate = useNavigate();
  const { mode, search, mineOnly, starredOnly, setMode, setSearch, toggleMine, toggleStarred } = useAgentStore();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [modelConfigOpen, setModelConfigOpen] = useState(false);
  // TOTP setup
  const [totpOpen, setTotpOpen] = useState(false);
  const [totpQR, setTotpQR] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpSetup, setTotpSetup] = useState(false);

  const handleTotpSetup = async () => {
    try {
      const res: any = await authService.totpSetup();
      if (res.data?.alreadyEnabled) {
        // TOTP is already active — show disable UI
        setTotpQR('');
        setTotpSetup(false);
      } else {
        setTotpQR(res.data?.qrcodeImg || '');
        setTotpSetup(true);
      }
      setTotpCode('');
      setTotpOpen(true);
    } catch {
      message.error('获取 TOTP 密钥失败');
    }
  };

  const handleTotpVerify = async () => {
    if (totpCode.length !== 6) return;
    try {
      await authService.totpVerify(totpCode);
      message.success('二次验证已开启');
      setTotpSetup(false);  // now in "enabled" state
      setTotpOpen(false);
    } catch {
      message.error('验证码错误');
    }
  };

  const [totpDisabling, setTotpDisabling] = useState(false);
  const [totpDisableCode, setTotpDisableCode] = useState('');

  const handleTotpDisable = async () => {
    if (totpDisableCode.length !== 6) return;
    try {
      await authService.totpDisable(totpDisableCode);
      message.success('二次验证已关闭');
      setTotpSetup(false);
      setTotpQR('');
      setTotpDisabling(false);
      setTotpDisableCode('');
      setTotpOpen(false);
    } catch {
      message.error('验证码错误');
    }
  };

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
        {user?.isSuperuser && (
          <Button onClick={() => navigate('/admin/users')}>用户并发管理</Button>
        )}
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/create')}>
          创建智能体
        </Button>

        {/* Current user + logout */}
        {user ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1677ff' }} />
            <span style={{ fontSize: 13, color: '#000000a6' }}>{user.name}</span>
            {user.isPasswordUser && (
              <Button type="text" size="small" icon={<SafetyOutlined />} onClick={handleTotpSetup} title="二次验证" />
            )}
            <Button type="text" size="small" icon={<LogoutOutlined />} onClick={handleLogout} title="登出" />
          </div>
        ) : null}
      </div>

      {/* Model Config Modal */}
      <ModelConfigModal open={modelConfigOpen} onClose={() => setModelConfigOpen(false)} />

      {/* TOTP Setup Modal */}
      <Modal
        open={totpOpen}
        onCancel={() => setTotpOpen(false)}
        footer={null}
        title="Google Authenticator 二次验证"
        width={400}
      >
        {totpSetup && totpQR ? (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 13, color: '#00000073', marginBottom: 12 }}>使用 Google Authenticator 扫描二维码</p>
            <img src={`data:image/png;base64,${totpQR}`} alt="TOTP QR" style={{ width: 180, height: 180 }} />
            <p style={{ fontSize: 13, color: '#00000073', margin: '12px 0' }}>扫码后输入 6 位验证码确认</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <Input
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                style={{ width: 120, textAlign: 'center', fontSize: 16, letterSpacing: 4 }}
                onPressEnter={handleTotpVerify}
              />
              <Button type="primary" onClick={handleTotpVerify} disabled={totpCode.length !== 6}>确认</Button>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 13, color: '#00000073', marginBottom: 12 }}>关闭前需验证身份，请输入当前验证码</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginBottom: 12 }}>
              <Input
                maxLength={6}
                value={totpDisableCode}
                onChange={(e) => setTotpDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                style={{ width: 120, textAlign: 'center', fontSize: 16, letterSpacing: 4 }}
                onPressEnter={handleTotpDisable}
              />
              <Button danger onClick={handleTotpDisable} disabled={totpDisableCode.length !== 6}>关闭</Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}
