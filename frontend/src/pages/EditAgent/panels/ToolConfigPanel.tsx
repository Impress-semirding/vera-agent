import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Spin,
  Switch,
  message,
} from 'antd';
import { DeleteOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { FormCard } from '../components/FormParts';
import {
  mcpService,
  type McpServerCreateData,
  type McpServerWithToolsResponse,
} from '@/services/mcpService';

const TRANSPORT_OPTIONS = [
  { label: 'stdio', value: 'stdio' },
  { label: 'sse', value: 'sse' },
  { label: 'streamable-http', value: 'streamable-http' },
];

interface CreateFormValues {
  name: string;
  command?: string;
  transport: 'stdio' | 'sse' | 'streamable-http';
  url?: string;
  args?: string;
  env?: string;
  headers?: string;
}

function _parseJsonField(raw: string | undefined, defaultVal: any): any {
  if (!raw?.trim()) return defaultVal;
  try {
    return JSON.parse(raw);
  } catch {
    return defaultVal;
  }
}

function matchKeyword(query: string, ...fields: (string | undefined)[]): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return fields.some((f) => !!f && f.toLowerCase().includes(q));
}

export default function ToolConfigPanel({ agentId }: { agentId: string }) {
  const [servers, setServers] = useState<McpServerWithToolsResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [keyword, setKeyword] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();

  const loadServers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await mcpService.list(agentId);
      setServers(res.data ?? []);
    } catch {
      message.error('加载 MCP Server 列表失败');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadServers();
  }, [loadServers]);

  const toggleExpand = (id: string) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  const handleCreate = async () => {
    let values: CreateFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload: McpServerCreateData = {
      name: values.name.trim(),
      command: values.command?.trim() || undefined,
      transport: values.transport,
      url: values.url?.trim() || undefined,
      args: _parseJsonField(values.args, []),
      env: _parseJsonField(values.env, {}),
      headers: _parseJsonField(values.headers, {}),
    };
    setCreating(true);
    try {
      await mcpService.create(agentId, payload);
      message.success('MCP Server 添加成功');
      setModalOpen(false);
      form.resetFields();
      await loadServers();
    } catch {
      message.error('添加 MCP Server 失败');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (serverId: string) => {
    try {
      await mcpService.remove(serverId);
      message.success('已删除 MCP Server');
      setServers((prev) => prev.filter((s) => s.id !== serverId));
    } catch {
      message.error('删除 MCP Server 失败');
    }
  };

  const handleToggleServer = async (
    serverId: string,
    newEnabled: boolean,
  ) => {
    const prev = servers;
    setServers((cur) =>
      cur.map((s) => (s.id === serverId ? { ...s, disabled: !newEnabled } : s)),
    );
    try {
      await mcpService.toggleServer(serverId, !newEnabled);
    } catch {
      setServers(prev);
      message.error('更新 MCP Server 状态失败');
    }
  };

  const handleToggleTool = async (
    serverId: string,
    toolId: string,
    newEnabled: boolean,
  ) => {
    const prev = servers;
    setServers((cur) =>
      cur.map((s) =>
        s.id === serverId
          ? {
              ...s,
              tools: s.tools.map((t) =>
                t.id === toolId ? { ...t, enabled: newEnabled } : t,
              ),
            }
          : s,
      ),
    );
    try {
      await mcpService.toggleTool(toolId, newEnabled);
    } catch {
      setServers(prev);
      message.error('更新工具状态失败');
    }
  };

  const query = keyword.trim();
  const filtered = servers
    .map((s) => ({
      server: s,
      tools: s.tools.filter((t) =>
        matchKeyword(query, s.name, t.name, t.description),
      ),
    }))
    .filter(
      ({ server, tools }) =>
        matchKeyword(query, server.name) || tools.length > 0,
    );

  return (
    <FormCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ fontWeight: 600, margin: 0 }}>工具配置（MCP）</h4>
        <Button type="link" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          添加MCP Server
        </Button>
      </div>

      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder="搜索工具名称"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        style={{ marginBottom: 16 }}
      />

      <Spin spinning={loading}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filtered.map(({ server, tools }) => {
            const isOpen = !!expanded[server.id];
            return (
              <div
                key={server.id}
                style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 16 }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: isOpen ? 12 : 0,
                  }}
                >
                  <div
                    style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
                    onClick={() => toggleExpand(server.id)}
                  >
                    <span
                      style={{
                        transition: 'transform 0.2s',
                        transform: isOpen ? 'rotate(90deg)' : '',
                        display: 'inline-block',
                      }}
                    >
                      ▶
                    </span>
                    <span style={{ fontWeight: 500, fontSize: 14 }}>{server.name}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Switch
                      size="small"
                      checked={!server.disabled}
                      onChange={(checked) => handleToggleServer(server.id, checked)}
                    />
                    <Popconfirm
                      title="删除该 MCP Server？"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => handleDelete(server.id)}
                    >
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </div>
                </div>

                {isOpen && tools.length > 0 && (
                  <div style={{ paddingLeft: 24, borderLeft: '2px solid #d9d9d9', marginLeft: 8 }}>
                    {tools.map((tool) => (
                      <div
                        key={tool.id}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          padding: '8px 0',
                        }}
                      >
                        <div>
                          <div style={{ fontWeight: 500, fontSize: 14 }}>{tool.name}</div>
                          {tool.description && (
                            <div style={{ fontSize: 12, color: '#00000073', marginTop: 2 }}>
                              {tool.description}
                            </div>
                          )}
                        </div>
                        <Switch
                          size="small"
                          checked={tool.enabled}
                          onChange={(checked) => handleToggleTool(server.id, tool.id, checked)}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Spin>

      <Modal
        title="添加 MCP Server"
        open={modalOpen}
        confirmLoading={creating}
        onCancel={() => setModalOpen(false)}
        onOk={handleCreate}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <Form<CreateFormValues>
          form={form}
          layout="vertical"
          initialValues={{ transport: 'stdio' }}
          preserve={false}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="请输入 MCP Server 名称" />
          </Form.Item>
          <Form.Item name="command" label="命令 (command)">
            <Input placeholder="stdio 启动命令，例如 npx" />
          </Form.Item>
          <Form.Item name="transport" label="传输方式 (transport)">
            <Select options={TRANSPORT_OPTIONS} />
          </Form.Item>
          <Form.Item name="url" label="地址 (url)">
            <Input placeholder="sse / streamable-http 远程地址" />
          </Form.Item>
          <Form.Item name="args" label="启动参数 (args, JSON 数组)">
            <Input.TextArea rows={2} placeholder='["--arg1", "--arg2"]' style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </Form.Item>
          <Form.Item name="env" label="环境变量 (env, JSON 对象)">
            <Input.TextArea rows={2} placeholder='{"KEY1": "val1", "KEY2": "val2"}' style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </Form.Item>
          <Form.Item name="headers" label="请求头 (headers, JSON 对象)">
            <Input.TextArea rows={2} placeholder='{"Authorization": "Bearer xxx", "X-Custom": "val"}' style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </Form.Item>
        </Form>
      </Modal>
    </FormCard>
  );
}
