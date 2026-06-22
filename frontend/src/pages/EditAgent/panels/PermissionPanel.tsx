import { useEffect, useState, useCallback } from 'react';
import { Button, Table, Modal, Checkbox, Select, Popconfirm, Tag, message, Form, Space } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import permissionService from '@/services/permissionService';
import type { AgentPermission, PermissionFormData, PermissionLevel } from '@/types/agent';
import api from '@/services/api';

const PERMISSION_OPTIONS: { value: PermissionLevel; label: string; color: string }[] = [
  { value: 'view', label: '查看', color: 'blue' },
  { value: 'edit', label: '编辑', color: 'purple' },
  { value: 'delete', label: '删除', color: 'red' },
];

interface UserOption {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
}

interface Props {
  agentId: string;
}

export default function PermissionPanel({ agentId }: Props) {
  const [permissions, setPermissions] = useState<AgentPermission[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AgentPermission | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [users, setUsers] = useState<UserOption[]>([]);
  const [userSearching, setUserSearching] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await permissionService.list(agentId);
      setPermissions(res.data ?? []);
    } catch { /* logged by interceptor */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [agentId]);

  // Fetch users for the picker (debounced search)
  const fetchUsers = useCallback(async (q: string) => {
    setUserSearching(true);
    try {
      const res = await api.get(`/users?q=${encodeURIComponent(q)}`);
      setUsers(res.data ?? []);
    } catch { /* ignore */ }
    finally { setUserSearching(false); }
  }, []);

  const handleUserSearch = useCallback((value: string) => {
    if (value.length >= 1) {
      fetchUsers(value);
    } else {
      fetchUsers('');
    }
  }, [fetchUsers]);

  const openAdd = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ agentPermissions: ['view'] });
    fetchUsers('');
    setModalOpen(true);
  };

  const openEdit = (record: AgentPermission) => {
    setEditing(record);
    form.setFieldsValue({
      userId: record.userName,  // use name as the select value key
      agentPermissions: record.agentPermissions,
    });
    // Load the user into options so the select can display it
    setUsers([{ id: record.agentId, name: record.userName, email: record.userEmail }]);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // Resolve selected user from options
      const selectedUser = users.find(
        (u) => u.name === values.userId
      );

      if (!selectedUser) {
        message.error('请选择一个有效用户');
        setSaving(false);
        return;
      }

      const data: PermissionFormData = {
        userName: selectedUser.name,
        userEmail: selectedUser.email,
        agentPermissions: values.agentPermissions,
      };

      if (editing) {
        await permissionService.update(editing.id, data);
        message.success('权限已更新');
      } else {
        await permissionService.add(agentId, data);
        message.success('已添加用户');
      }

      setModalOpen(false);
      await load();
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error('操作失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await permissionService.remove(id);
      message.success('已移除');
      await load();
    } catch {
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: '用户名',
      dataIndex: 'userName',
      key: 'userName',
      width: 140,
    },
    {
      title: '邮箱',
      dataIndex: 'userEmail',
      key: 'userEmail',
      width: 200,
    },
    {
      title: '权限',
      dataIndex: 'agentPermissions',
      key: 'agentPermissions',
      render: (perms: PermissionLevel[]) => (
        <Space size={4}>
          {perms.map((p) => {
            const opt = PERMISSION_OPTIONS.find((o) => o.value === p);
            return opt ? <Tag key={p} color={opt.color}>{opt.label}</Tag> : null;
          })}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: any, record: AgentPermission) => (
        <>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认移除该用户的权限？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </>
      ),
    },
  ];

  return (
    <div style={{ background: '#fff', border: '1px solid #d9d9d9', borderRadius: 8, padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ fontWeight: 600, margin: 0 }}>用户权限管理</h4>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openAdd}>
          添加用户
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={permissions}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
        locale={{ emptyText: '暂无权限记录，点击"添加用户"授权' }}
      />

      <Modal
        title={editing ? '编辑权限' : '添加用户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="userId"
            label="选择用户"
            rules={[{ required: true, message: '请选择用户' }]}
          >
            <Select
              showSearch
              placeholder="输入用户名或邮箱搜索"
              disabled={!!editing}
              filterOption={false}
              onSearch={handleUserSearch}
              onFocus={() => fetchUsers('')}
              loading={userSearching}
              notFoundContent={userSearching ? '搜索中...' : '无匹配用户'}
              options={users.map((u) => ({
                value: u.name,
                label: `${u.name} (${u.email})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="agentPermissions"
            label="权限"
            rules={[{ required: true, type: 'array', min: 1, message: '至少选择一项权限' }]}
          >
            <Checkbox.Group>
              <Space>
                {PERMISSION_OPTIONS.map((opt) => (
                  <Checkbox key={opt.value} value={opt.value}>
                    <Tag color={opt.color}>{opt.label}</Tag>
                  </Checkbox>
                ))}
              </Space>
            </Checkbox.Group>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
