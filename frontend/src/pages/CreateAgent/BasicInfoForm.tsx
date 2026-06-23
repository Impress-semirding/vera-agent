import { useEffect, useState } from 'react';
import { Form, Input, Select, Switch, Button, Avatar, Upload } from 'antd';
import { UserOutlined, CameraOutlined } from '@ant-design/icons';
import type { AgentType, AppMode, AgentFormData } from '@/types/agent';
import { modelConfigService } from '@/services/modelConfigService';
import type { ModelOption } from '@/types/modelConfig';
import { FormCard } from '@/components/ui/FormCard';

interface Props {
  agentType: AgentType;
  mode: AppMode;
  submitting?: boolean;
  onSubmit: (data: AgentFormData) => void;
  onBack: () => void;
}

export default function BasicInfoForm({ agentType, mode, submitting, onSubmit, onBack }: Props) {
  const [form] = Form.useForm();
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);

  useEffect(() => {
    modelConfigService.listModels().then(res => {
      const opts = res.data ?? [];
      setModelOptions(opts);
      // Set first model as default if form value is empty
      if (opts.length > 0) {
        form.setFieldValue('model', opts[0]!.value);
      }
    }).catch(() => {
      // silently fail
    });
  }, [form]);

  const handleFinish = (values: any) => {
    onSubmit({
      ...values,
      type: agentType,
      mode,
      visibility: values.visibility ?? true,
    });
  };

  return (
    <div style={{ maxWidth: 600, margin: '40px auto', padding: 24 }}>
      <FormCard title="基本信息">
        <Form form={form} layout="vertical" onFinish={handleFinish}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="请输入智能体名称" />
          </Form.Item>

          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} placeholder="请输入描述（可选）" />
          </Form.Item>

          <Form.Item label="使用模型" name="model" rules={[{ required: true, message: '请选择模型' }]}>
            <Select
              options={modelOptions.map(m => ({ label: m.label, value: m.value }))}
              placeholder="请选择模型（需先在模型配置中添加）"
              notFoundContent="暂无模型，请先在「模型配置」中添加"
            />
          </Form.Item>

          <Form.Item label="头像">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Avatar size={64} icon={<UserOutlined />} style={{ background: 'var(--color-primary)' }} />
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
      </FormCard>
    </div>
  );
}
