import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button, Form, Input, Alert } from 'antd';
import { StarOutlined } from '@ant-design/icons';
import { useAuthStore } from '@/stores/useAuthStore';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const login = useAuthStore((s) => s.login);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Where to go after login (the page the user was trying to reach).
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  const handleFinish = async (values: { identifier: string; password: string }) => {
    setError(null);
    setSubmitting(true);
    try {
      await login(values.identifier, values.password);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        '登录失败，请重试';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 360, background: '#fff', border: '1px solid #d9d9d9', borderRadius: 12, padding: 32, boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 8 }}>
          <StarOutlined style={{ color: '#1677ff', fontSize: 22 }} />
          <span style={{ fontSize: 20, fontWeight: 600 }}>小智</span>
        </div>
        <p style={{ textAlign: 'center', color: '#00000073', fontSize: 13, marginBottom: 24 }}>登录以管理你的智能体</p>

        {error ? <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} /> : null}

        <Form layout="vertical" onFinish={handleFinish} preserve={false}>
          <Form.Item label="用户名 / 邮箱" name="identifier" rules={[{ required: true, message: '请输入用户名或邮箱' }]}>
            <Input placeholder="请输入用户名或邮箱" autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>登录</Button>
        </Form>

        <div style={{ marginTop: 16, textAlign: 'center', fontSize: 12, color: '#00000040' }}>
          演示账号：王聪 / 123456（或 鲁婉婉、张三、赵六）
        </div>
      </div>
    </div>
  );
}
