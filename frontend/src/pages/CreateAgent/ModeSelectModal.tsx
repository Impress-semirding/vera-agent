import { useState } from 'react';
import { Modal, Card, Radio } from 'antd';
import { RobotOutlined, UserOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons';
import type { AgentType, AppMode } from '@/types/agent';

interface Props {
  open: boolean;
  onSelect: (type: AgentType, mode: AppMode) => void;
  onCancel: () => void;
}

const AGENT_TYPES: { type: AgentType; icon: React.ReactNode; title: string; desc: string; features: string[] }[] = [
  {
    type: 'system',
    icon: <RobotOutlined style={{ fontSize: 32, color: '#1677ff' }} />,
    title: '系统虾',
    desc: '面向团队的共享智能体，支持权限管理和推送配置',
    features: ['全员可见，团队共享', '支持 MCP 工具和技能扩展', '企微推送和权限管理'],
  },
  {
    type: 'personal',
    icon: <UserOutlined style={{ fontSize: 32, color: '#52c41a' }} />,
    title: '个人虾',
    desc: '面向个人的私有智能体，完全自主配置',
    features: ['个人私有，仅自己可见', '支持 .claude/ 目录配置', '灵活的文件和会话管理'],
  },
];

export default function ModeSelectModal({ open, onSelect, onCancel }: Props) {
  const [appMode, setAppMode] = useState<AppMode>('claude');

  return (
    <Modal
      title="选择智能体类型"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={640}
      centered
    >
      {/* Mode toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 0 8px' }}>
        <span style={{ fontSize: 13, color: '#00000073', whiteSpace: 'nowrap' }}>运行模式</span>
        <Radio.Group
          value={appMode}
          onChange={(e) => setAppMode(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          size="middle"
        >
          <Radio.Button value="claude">
            <ThunderboltOutlined style={{ marginRight: 6 }} />
            Claude 模式
          </Radio.Button>
          <Radio.Button value="normal">
            <ToolOutlined style={{ marginRight: 6 }} />
            普通模式
          </Radio.Button>
        </Radio.Group>
      </div>

      {/* Claude mode: show system / personal cards */}
      {appMode === 'claude' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: '8px 0 16px' }}>
          {AGENT_TYPES.map((m) => (
            <Card
              key={m.type}
              hoverable
              style={{ cursor: 'pointer', textAlign: 'center' }}
              onClick={() => onSelect(m.type, 'claude')}
            >
              <div style={{ marginBottom: 12 }}>{m.icon}</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{m.title}</div>
              <div style={{ fontSize: 13, color: '#00000073', marginBottom: 12 }}>{m.desc}</div>
              <ul style={{ textAlign: 'left', fontSize: 12, color: '#00000073', listStyle: 'disc', paddingLeft: 16 }}>
                {m.features.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}

      {/* Normal mode: self-built agent description */}
      {appMode === 'normal' && (
        <div style={{ padding: '16px 0' }}>
          <Card
            hoverable
            style={{ cursor: 'pointer', textAlign: 'center' }}
            onClick={() => onSelect('personal', 'normal')}
          >
            <div style={{ marginBottom: 12 }}>
              <ToolOutlined style={{ fontSize: 32, color: '#faad14' }} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>自建 Agent</div>
            <div style={{ fontSize: 13, color: '#00000073', marginBottom: 12 }}>
              使用自定义 LLM 配置，灵活对接各类模型服务
            </div>
            <ul style={{ textAlign: 'left', fontSize: 12, color: '#00000073', listStyle: 'disc', paddingLeft: 16, margin: 0 }}>
              <li>支持对接任意 OpenAI 兼容 API</li>
              <li>自定义系统提示词和参数</li>
              <li>个人私有，按需配置</li>
            </ul>
          </Card>
        </div>
      )}
    </Modal>
  );
}
