import { useState, useEffect } from 'react';
import { Form, Input, Select, Switch, Button, Avatar, message } from 'antd';
import { RobotOutlined, EditOutlined } from '@ant-design/icons';
import type { Agent } from '@/types/agent';
import { agentService } from '@/services/agentService';
import { modelConfigService } from '@/services/modelConfigService';
import type { ModelOption } from '@/types/modelConfig';
import { FormCard, FormRow } from '@/pages/EditAgent/components/FormParts';

interface Values {
  name: string;
  description?: string;
  model: string;
  visibility?: boolean;
}

export default function BasicInfoPanel({ agentId, agent }: { agentId: string; agent: Agent }) {
  const [form] = Form.useForm<Values>();
  const [saving, setSaving] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);

  useEffect(() => {
    modelConfigService.listModels().then(res => {
      setModelOptions(res.data ?? []);
    }).catch(() => {
      // silently fail — dropdown will be empty
    });
  }, []);

  const handleFinish = async (values: Values) => {
    if (saving) return;
    setSaving(true);
    try {
      await agentService.update(agentId, {
        name: values.name,
        description: values.description,
        model: values.model,
        visibility: agent.type === 'system' ? values.visibility ?? true : agent.visibility,
        avatarUrl: agent.avatarUrl,
      });
      message.success('保存成功');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormCard>
      <h4 style={{ fontWeight: 600, marginBottom: 16 }}>基本信息</h4>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        initialValues={{
          name: agent.name,
          description: agent.description,
          model: agent.model,
          visibility: agent.visibility,
        }}
      >
        <div style={{ maxWidth: 480, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FormRow label="名称" required>
            <Form.Item name="name" noStyle rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="请输入名称" />
            </Form.Item>
          </FormRow>

          <FormRow label="描述">
            <Form.Item name="description" noStyle>
              <Input.TextArea rows={2} placeholder="请输入描述（可选）" />
            </Form.Item>
          </FormRow>

          <FormRow label="使用模型" required>
            <Form.Item name="model" noStyle rules={[{ required: true, message: '请选择模型' }]}>
              <Select
                options={modelOptions.map(m => ({ label: m.label, value: m.value }))}
                placeholder="请选择模型（需先在模型配置中添加）"
                style={{ width: '100%' }}
                notFoundContent="暂无模型，请先在「模型配置」中添加"
              />
            </Form.Item>
          </FormRow>

          <FormRow label="头像">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Avatar size={48} icon={<RobotOutlined />} style={{ background: '#1677ff' }} />
              <Button icon={<EditOutlined />}>更换</Button>
            </div>
          </FormRow>

          {agent.type === 'system' && (
            <FormRow label="全员可见">
              <Form.Item name="visibility" noStyle valuePropName="checked">
                <Switch />
              </Form.Item>
            </FormRow>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存
          </Button>
        </div>
      </Form>
    </FormCard>
  );
}
