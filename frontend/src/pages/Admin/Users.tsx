import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, InputNumber, Tag, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { adminService, type AdminUser } from '@/services/adminService';
import { useAuthStore } from '@/stores/useAuthStore';

export default function AdminUsersPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [defaultMax, setDefaultMax] = useState(3);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<number | null>(null);

  const fetch = async () => {
    setLoading(true);
    try {
      const res = await adminService.listUsers();
      setUsers(res.data?.users ?? []);
      setDefaultMax(res.data?.defaultMaxTurns ?? 3);
    } catch {
      message.error('加载用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!user?.isSuperuser) {
      navigate('/', { replace: true });
      return;
    }
    fetch();
  }, [user]);

  const save = async (uid: string) => {
    try {
      await adminService.setConcurrency(uid, draft);
      message.success('已保存');
      setEditing(null);
      fetch();
    } catch {
      message.error('保存失败');
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 24px', background: '#fff', borderBottom: '1px solid #d9d9d9' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回</Button>
        <span style={{ fontSize: 18, fontWeight: 600 }}>用户并发管理</span>
        <span style={{ color: '#00000073', fontSize: 13, marginLeft: 'auto' }}>
          环境默认值：{defaultMax}（用户未设置时使用）
        </span>
      </div>

      <div style={{ padding: 24 }}>
        <Table<AdminUser>
          rowKey="id"
          loading={loading}
          dataSource={users}
          pagination={false}
          columns={[
            {
              title: '用户', dataIndex: 'name', key: 'name',
              render: (name: string, u) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 500 }}>{name}</span>
                  {u.isSuperuser && <Tag color="purple">超级管理员</Tag>}
                  {u.dingtalkUnionId && <Tag color="blue">钉钉</Tag>}
                </div>
              ),
            },
            { title: '邮箱', dataIndex: 'email', key: 'email', ellipsis: true },
            {
              title: '最大并发消息数', key: 'limit', width: 240,
              render: (_: unknown, u: AdminUser) => {
                if (editing === u.id) {
                  return (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <InputNumber
                        min={1} max={50}
                        value={draft}
                        onChange={(v) => setDraft(v ?? null)}
                        placeholder={`默认 ${defaultMax}`}
                        style={{ width: 120 }}
                      />
                      <Button size="small" type="primary" onClick={() => save(u.id)}>保存</Button>
                      <Button size="small" onClick={() => setEditing(null)}>取消</Button>
                    </div>
                  );
                }
                return (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span>{u.maxConcurrentTurns ?? <span style={{ color: '#00000040' }}>默认 ({defaultMax})</span>}</span>
                    <Button size="small" type="link" onClick={() => { setEditing(u.id); setDraft(u.maxConcurrentTurns); }}>修改</Button>
                  </div>
                );
              },
            },
          ]}
        />
      </div>
    </div>
  );
}
