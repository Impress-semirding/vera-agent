import { useCallback, useEffect, useState } from 'react';
import {
  Button, Form, Input, InputNumber, Modal, Select, Switch,
  Table, Tag, Popconfirm, message, Tooltip,
} from 'antd';
import { PlusOutlined, DeleteOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { FormCard } from '../components/FormParts';
import { scheduleService, type ScheduleTask } from '@/services/scheduleService';
import { sessionService } from '@/services/sessionService';

const CRON_PRESETS = [
  { label: '每30分钟', value: '*/30 * * * *' },
  { label: '每小时', value: '0 * * * *' },
  { label: '每天 8:00', value: '0 8 * * *' },
  { label: '每天 0:00', value: '0 0 * * *' },
  { label: '每周一 9:00', value: '0 9 * * 1' },
  { label: '每月1号', value: '0 0 1 * *' },
  { label: '自定义', value: '' },
];

export default function SchedulePanel({ agentId }: { agentId: string }) {
  const [tasks, setTasks] = useState<ScheduleTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduleTask | null>(null);
  const [sessions, setSessions] = useState<{ id: string; name: string }[]>([]);
  const [form] = Form.useForm();
  const [initValues, setInitValues] = useState<Record<string, any>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await scheduleService.list(agentId);
      setTasks(res.data ?? []);
    } catch { message.error('加载定时任务失败'); }
    finally { setLoading(false); }
  }, [agentId]);

  const loadSessions = useCallback(async () => {
    try {
      const res = await sessionService.list(agentId);
      setSessions((res.data ?? []) as any[]);
    } catch { /* ignore */ }
  }, [agentId]);

  useEffect(() => { load(); loadSessions(); }, [load, loadSessions]);

  const handleCreate = () => {
    setEditing(null);
    form.resetFields();
    setInitValues({ cron: '0 8 * * *', timeout: 1200, enabled: true, task_type: 'agent' });
    setModalOpen(true);
  };

  const handleEdit = (task: ScheduleTask) => {
    setEditing(task);
    setInitValues({
      name: task.name, prompt: task.prompt, cron: task.cron,
      timeout: task.timeout, enabled: task.enabled,
      task_type: task.taskType || 'agent',
      script_name: task.scriptName, script_content: task.scriptContent,
      session_id: task.sessionId || undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (editing) {
        await scheduleService.update(agentId, editing.id, values);
        message.success('已更新');
      } else {
        await scheduleService.create(agentId, values);
        message.success('已创建');
      }
      setModalOpen(false);
      load();
    } catch { /* validation error */ }
  };

  const handleDelete = async (id: string) => {
    try {
      await scheduleService.remove(agentId, id);
      message.success('已删除');
      load();
    } catch { message.error('删除失败'); }
  };

  const handleToggle = async (task: ScheduleTask) => {
    try {
      await scheduleService.toggle(agentId, task.id);
      load();
    } catch { message.error('操作失败'); }
  };

  const sourceTag = (source: string) => (
    source === 'chat'
      ? <Tag color="blue" style={{ fontSize: 10 }}>会话创建</Tag>
      : <Tag color="green" style={{ fontSize: 10 }}>系统配置</Tag>
  );

  const statusTag = (status: string, failCount: number) => {
    if (status === 'failed' || failCount >= 3) return <Tag color="red">已失败</Tag>;
    if (status === 'paused') return <Tag color="orange">已暂停</Tag>;
    if (status === 'running') return <Tag color="processing">执行中</Tag>;
    return <Tag color="green">活跃</Tag>;
  };

  return (
    <FormCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ fontWeight: 600, margin: 0 }}>
          <ClockCircleOutlined style={{ marginRight: 8 }} />
          定时任务
        </h4>
        <Button type="link" icon={<PlusOutlined />} onClick={handleCreate}>添加任务</Button>
      </div>

      <Table<ScheduleTask>
        rowKey="id"
        loading={loading}
        dataSource={tasks}
        pagination={false}
        size="small"
        columns={[
          {
            title: '名称', dataIndex: 'name', key: 'name', width: 160,
            render: (name: string, t) => (
              <div>
                <span style={{ fontWeight: 500, fontSize: 13 }}>{name}</span>
                <div style={{ marginTop: 2 }}>
                  {sourceTag(t.source)}
                  {t.taskType === 'script+agent' && <Tag color="purple" style={{ fontSize: 10, marginLeft: 2 }}>脚本</Tag>}
                </div>
              </div>
            ),
          },
          {
            title: 'Cron', dataIndex: 'cron', key: 'cron', width: 130,
            render: (cron: string) => (
              <code style={{ fontSize: 11, background: '#f5f5f5', padding: '2px 6px', borderRadius: 4 }}>{cron}</code>
            ),
          },
          {
            title: 'Prompt', dataIndex: 'prompt', key: 'prompt', ellipsis: true,
            render: (p: string) => <Tooltip title={p}><span style={{ fontSize: 12 }}>{p}</span></Tooltip>,
          },
          {
            title: '状态', key: 'status', width: 90,
            render: (_: unknown, t: ScheduleTask) => statusTag(t.status, t.failCount),
          },
          {
            title: '上次执行', key: 'last', width: 140,
            render: (_: unknown, t: ScheduleTask) => (
              <div style={{ fontSize: 11, color: '#00000073' }}>
                {t.lastRunAt ? new Date(t.lastRunAt).toLocaleString('zh-CN') : '—'}
                {t.lastStatus && (
                  <Tag color={t.lastStatus === 'success' ? 'green' : 'red'} style={{ marginLeft: 4, fontSize: 10 }}>
                    {t.lastStatus === 'success' ? '成功' : t.lastStatus === 'timeout' ? '超时' : '失败'}
                  </Tag>
                )}
              </div>
            ),
          },
          {
            title: '下次', key: 'next', width: 140,
            render: (_: unknown, t: ScheduleTask) => (
              <span style={{ fontSize: 11, color: '#00000073' }}>
                {t.nextRunAt ? new Date(t.nextRunAt).toLocaleString('zh-CN') : '—'}
              </span>
            ),
          },
          {
            title: '操作', key: 'actions', width: 120, fixed: 'right',
            render: (_: unknown, t: ScheduleTask) => (
              <div style={{ display: 'flex', gap: 4 }}>
                <Switch size="small" checked={t.enabled} onChange={() => handleToggle(t)} />
                <Button size="small" type="link" onClick={() => handleEdit(t)}>编辑</Button>
                <Popconfirm title="删除此任务？" onConfirm={() => handleDelete(t.id)}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑定时任务' : '添加定时任务'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
        destroyOnHidden
        key={editing?.id || 'new'}
      >
        <Form form={form} layout="vertical" preserve={false} initialValues={initValues}>
          <Form.Item name="session_id" label="目标会话（结果写入，空=自动创建）">
            <Select
              allowClear
              showSearch
              placeholder="自动创建新会话"
              optionFilterProp="label"
              options={sessions.map((s: any) => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：每日竞品检查" />
          </Form.Item>
          <Form.Item name="cron" label="执行时间" rules={[{ required: true }]}>
            <Select
              options={CRON_PRESETS}
              onChange={(v) => {
                if (v) form.setFieldValue('cron', v);
              }}
              showSearch
            />
          </Form.Item>
          {form.getFieldValue('cron') === '' && (
            <Form.Item name="cron" label="Cron 表达式" rules={[{ required: true }]}>
              <Input placeholder="分 时 日 月 周，如 0 8 * * *" style={{ fontFamily: 'monospace' }} />
            </Form.Item>
          )}
          <Form.Item name="prompt" label="执行内容（Prompt）" rules={[{ required: true, message: '请输入执行内容' }]}>
            <Input.TextArea rows={3} placeholder="到时间后发给 agent 的指令，如：查竞品价格并总结趋势" />
          </Form.Item>
          <Form.Item name="task_type" label="执行模式">
            <Select
              options={[
                { label: 'Agent 对话（直接发 prompt）', value: 'agent' },
                { label: '脚本 + Agent（先跑脚本，结果喂给 Agent 分析）', value: 'script+agent' },
              ]}
            />
          </Form.Item>
          <Form.Item name="script_name" label="脚本文件名（可选，script+agent 模式）">
            <Input placeholder="如：crawl_prices.py" />
          </Form.Item>
          <Form.Item name="script_content" label="脚本内容（可选，script+agent 模式）">
            <Input.TextArea rows={4} placeholder="Python 脚本内容，脚本 stdout 会作为上下文喂给 Agent" style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </Form.Item>
          <Form.Item name="timeout" label="超时（秒）">
            <InputNumber min={30} max={3600} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </FormCard>
  );
}
