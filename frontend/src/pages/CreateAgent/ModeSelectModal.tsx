import { Modal, Card } from 'antd';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import type { AgentType } from '@/types/agent';

interface Props {
  open: boolean;
  onSelect: (type: AgentType) => void;
  onCancel: () => void;
}

const MODES: { type: AgentType; icon: React.ReactNode; title: string; desc: string; features: string[] }[] = [
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
  return (
    <Modal
      title="选择智能体类型"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={640}
      centered
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: '16px 0' }}>
        {MODES.map((m) => (
          <Card
            key={m.type}
            hoverable
            style={{ cursor: 'pointer', textAlign: 'center' }}
            onClick={() => onSelect(m.type)}
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
    </Modal>
  );
}
