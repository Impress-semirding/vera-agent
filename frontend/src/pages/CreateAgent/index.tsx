import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useAgentStore } from '@/stores/useAgentStore';
import ModeSelectModal from './ModeSelectModal';
import BasicInfoForm from './BasicInfoForm';
import type { AgentType, AppMode, AgentFormData } from '@/types/agent';

export default function CreateAgentPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { createAgent } = useAgentStore();

  const preselectedType = searchParams.get('mode') as AgentType | null;
  const [agentType, setAgentType] = useState<AgentType | null>(preselectedType);
  const [appMode, setAppMode] = useState<AppMode>('claude');
  const [showModal, setShowModal] = useState(!preselectedType);
  const [submitting, setSubmitting] = useState(false);

  const handleSelectType = (type: AgentType, mode: AppMode) => {
    setAgentType(type);
    setAppMode(mode);
    setShowModal(false);
  };

  const handleSubmit = async (data: AgentFormData) => {
    setSubmitting(true);
    try {
      const agent = await createAgent(data);
      message.success('创建成功');
      navigate(`/chat/${agent.id}`);
    } catch {
      message.error('创建失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="app-page">
      {/* Header */}
      <div className="app-header-bar">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} />
        <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-text)' }}>创建智能体 - 基础信息</span>
        <Button style={{ marginLeft: 'auto' }} onClick={() => navigate('/')}>取消</Button>
      </div>

      {/* Mode selection modal */}
      <ModeSelectModal
        open={showModal}
        onSelect={handleSelectType}
        onCancel={() => navigate('/')}
      />

      {/* Form */}
      {agentType && (
        <BasicInfoForm
          agentType={agentType}
          mode={appMode}
          submitting={submitting}
          onSubmit={handleSubmit}
          onBack={() => navigate('/')}
        />
      )}
    </div>
  );
}
