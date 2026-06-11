import { useEffect, useState } from 'react';
import { Form, Input, Select, Switch, Button, Table, Space, Modal, message, Tag, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { ModelConfig, ModelProvider, ModelConfigCreate } from '@/types/modelConfig';
import { PROVIDER_PRESETS } from '@/types/modelConfig';
import { modelConfigService } from '@/services/modelConfigService';

const PROVIDER_OPTIONS = Object.entries(PROVIDER_PRESETS).map(([key, preset]) => ({
  label: preset.label,
  value: key,
}));

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: 'blue',
  glm: 'green',
  kimi: 'orange',
  mimo: 'red',
  minimax: 'purple',
};

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ModelConfigModal({ open, onClose }: Props) {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const res = await modelConfigService.list();
      setConfigs(res.data ?? []);
    } catch {
      message.error('获取模型配置失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchConfigs();
  }, [open]);

  const handleProviderChange = (provider: ModelProvider) => {
    const preset = PROVIDER_PRESETS[provider];
    if (preset) {
      form.setFieldsValue({
        modelId: preset.defaultModelId,
        baseUrl: preset.defaultBaseUrl,
      });
    }
  };

  const handleOpenCreate = () => {
    setEditing(null);
    form.resetFields();
    setEditModalOpen(true);
  };

  const handleOpenEdit = (record: ModelConfig) => {
    setEditing(record);
    form.setFieldsValue({
      provider: record.provider,
      name: record.name,
      modelId: record.modelId,
      baseUrl: record.baseUrl,
      apiKey: record.apiKey,
    });
    setEditModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (submitting) return;
      setSubmitting(true);

      if (editing) {
        await modelConfigService.update(editing.id, values);
        message.success('更新成功');
      } else {
        await modelConfigService.create(values as ModelConfigCreate);
        message.success('添加成功');
      }
      setEditModalOpen(false);
      fetchConfigs();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(editing ? '更新失败' : '添加失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await modelConfigService.remove(id);
      message.success('删除成功');
      fetchConfigs();
    } catch {
      message.error('删除失败');
    }
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await modelConfigService.toggleEnabled(id, enabled);
      fetchConfigs();
    } catch {
      message.error('操作失败');
    }
  };

  const columns: ColumnsType<ModelConfig> = [
    {
      title: '供应商',
      dataIndex: 'provider',
      width: 100,
      render: (v: ModelProvider) => (
        <Tag color={PROVIDER_COLORS[v] ?? 'default'}>{PROVIDER_PRESETS[v]?.label ?? v}</Tag>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 160,
    },
    {
      title: '模型 ID',
      dataIndex: 'modelId',
      width: 160,
    },
    {
      title: 'Base URL',
      dataIndex: 'baseUrl',
      ellipsis: true,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean, record) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(record.id, checked)} />
      ),
    },
    {
      title: '操作',
      width: 100,
      render: (_, record) => (
        <Space size="small">
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => handleOpenEdit(record)} />
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      {/* Outer: model config list modal */}
      <Modal
        title="模型配置"
        open={open}
        onCancel={onClose}
        footer={null}
        width={780}
        destroyOnClose
      >
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenCreate}>
            添加模型
          </Button>
        </div>

        <Table
          columns={columns}
          dataSource={configs}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={false}
        />
      </Modal>

      {/* Inner: create/edit form modal */}
      <Modal
        title={editing ? '编辑模型' : '添加模型'}
        open={editModalOpen}
        onOk={handleSubmit}
        onCancel={() => setEditModalOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Form.Item label="供应商" name="provider" rules={[{ required: true, message: '请选择供应商' }]}>
            <Select
              options={PROVIDER_OPTIONS}
              placeholder="请选择供应商"
              onChange={handleProviderChange}
              disabled={!!editing}
            />
          </Form.Item>

          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 DeepSeek V4 Pro" />
          </Form.Item>

          <Form.Item label="模型 ID" name="modelId" rules={[{ required: true, message: '请输入模型 ID' }]}>
            <Input placeholder="如 deepseek-v4-pro" />
          </Form.Item>

          <Form.Item label="Base URL" name="baseUrl" rules={[{ required: true, message: '请输入 Base URL' }]}>
            <Input placeholder="Anthropic 协议兼容的 Base URL" />
          </Form.Item>

          <Form.Item label="API Key" name="apiKey" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="请输入 API Key" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
