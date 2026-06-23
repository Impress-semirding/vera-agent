import { useState } from 'react';
import { Modal, Card, Radio } from 'antd';
import { RobotOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons';
import type { AgentType, AppMode } from '@/types/agent';

interface Props {
  open: boolean;
  onSelect: (type: AgentType, mode: AppMode) => void;
  onCancel: () => void;
}

export default function ModeSelectModal({ open, onSelect, onCancel }: Props) {
  const [appMode, setAppMode] = useState<AppMode>('claude');

  return (
    <Modal
      title="选择智能体类型"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={480}
      centered
    >
      {/* Mode toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 0 8px' }}>
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', whiteSpace: 'nowrap' }}>运行模式</span>
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

      {/* Claude mode: system agent */}
      {appMode === 'claude' && (
        <div style={{ padding: '8px 0 16px' }}>
          <Card
            hoverable
            style={{ cursor: 'pointer', textAlign: 'center' }}
            onClick={() => onSelect('system', 'claude')}
          >
            <div style={{ marginBottom: 12 }}>
              <RobotOutlined style={{ fontSize: 32, color: 'var(--color-primary)' }} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Claude Code</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
              面向团队的共享智能体，支持权限管理和推送配置
            </div>
            <ul style={{ textAlign: 'left', fontSize: 12, color: 'var(--color-text-tertiary)', listStyle: 'disc', paddingLeft: 16, margin: 0 }}>
              <li>全员可见，团队共享</li>
              <li>支持 MCP 工具和技能扩展</li>
              <li>企微推送和权限管理</li>
            </ul>
          </Card>
        </div>
      )}

      {/* Normal mode: self-built agent */}
      {appMode === 'normal' && (
        <div style={{ padding: '8px 0 16px' }}>
          <Card
            hoverable
            style={{ cursor: 'pointer', textAlign: 'center' }}
            onClick={() => onSelect('system', 'normal')}
          >
            <div style={{ marginBottom: 12 }}>
              <ToolOutlined style={{ fontSize: 32, color: 'var(--color-warning)' }} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>自建 Agent</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
              使用自定义 LLM 配置，灵活对接各类模型服务
            </div>
            <ul style={{ textAlign: 'left', fontSize: 12, color: 'var(--color-text-tertiary)', listStyle: 'disc', paddingLeft: 16, margin: 0 }}>
              <li>支持对接任意 OpenAI 兼容 API</li>
              <li>自定义系统提示词和参数</li>
            </ul>
          </Card>
        </div>
      )}
    </Modal>
  );
}
