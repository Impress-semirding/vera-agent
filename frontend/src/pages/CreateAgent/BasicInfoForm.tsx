import { Form, Input, Select, Switch, Button, Avatar, Upload } from 'antd';
import { UserOutlined, CameraOutlined } from '@ant-design/icons';
import type { AgentType, AppMode, AgentFormData } from '@/types/agent';

interface Props {
  agentType: AgentType;
  mode: AppMode;
  submitting?: boolean;
  onSubmit: (data: AgentFormData) => void;
  onBack: () => void;
}

const MODELS = [
  { label: 'GLM-5.1', value: 'glm-5-1' },
  { label: 'Claude 3 Opus', value: 'claude-3-opus' },
  { label: 'DeepSeek V4 Flash', value: 'deepseek-v4-flash' },
  { label: 'DeepSeek V4 Pro', value: 'deepseek-v4-pro' },
];

export default function BasicInfoForm({ agentType, mode, submitting, onSubmit, onBack }: Props) {
  const [form] = Form.useForm();

  const handleFinish = (values: any) => {
    onSubmit({
      ...values,
      type: agentType,
      mode,
      // System agents expose a "全员可见" toggle; personal agents are private.
      visibility: agentType === 'system' ? values.visibility ?? true : false,
    });
  };

  return (
    <div style={{ maxWidth: 600, margin: '40px auto', padding: 24 }}>
      <div
        style={{
          background: '#fff',
          border: '1px solid #d9d9d9',
          borderRadius: 12,
          padding: 24,
        }}
      >
        <h2 style={{ marginBottom: 24, fontSize: 16 }}>基本信息</h2>
        <Form form={form} layout="vertical" onFinish={handleFinish} initialValues={{ model: 'glm-5-1' }}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="请输入智能体名称" />
          </Form.Item>

          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} placeholder="请输入描述（可选）" />
          </Form.Item>

          <Form.Item label="使用模型" name="model" rules={[{ required: true, message: '请选择模型' }]}>
            <Select options={MODELS} />
          </Form.Item>

          <Form.Item label="头像">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Avatar size={64} icon={<UserOutlined />} style={{ background: '#1677ff' }} />
              <Upload showUploadList={false} beforeUpload={() => false}>
                <Button icon={<CameraOutlined />}>更换</Button>
              </Upload>
            </div>
          </Form.Item>

          {agentType === 'system' && (
            <Form.Item label="全员可见" name="visibility" valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}>
            <Button onClick={onBack} disabled={submitting}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              保存并下一步
            </Button>
          </div>
        </Form>
      </div>
    </div>
  );
}
