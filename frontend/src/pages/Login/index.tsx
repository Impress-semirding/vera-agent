import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button, Form, Input, Alert, Divider } from 'antd';
import { StarOutlined } from '@ant-design/icons';
import { useAuthStore } from '@/stores/useAuthStore';
import { authService } from '@/services/authService';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const login = useAuthStore((s) => s.login);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dingtalkEnabled, setDingtalkEnabled] = useState(false);

  // Where to go after login (the page the user was trying to reach).
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  // Probe whether DingTalk login is configured (hides button if not).
  useEffect(() => {
    authService.dingtalkConfig().then((res: any) => {
      setDingtalkEnabled(!!res.data?.enabled);
    }).catch(() => setDingtalkEnabled(false));
  }, []);

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

  const handleDingtalk = async () => {
    setError(null);
    try {
      const res: any = await authService.dingtalkConfig();
      if (!res.data?.enabled || !res.data.authorizeUrl) {
        setError('钉钉登录未配置');
        return;
      }
      // state is held in sessionStorage for the callback to validate
      if (res.data.state) sessionStorage.setItem('dingtalk_state', res.data.state);
      sessionStorage.setItem('login_from', from);
      window.location.href = res.data.authorizeUrl;
    } catch {
      setError('无法发起钉钉登录');
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 360, background: '#fff', border: '1px solid #d9d9d9', borderRadius: 12, padding: 32, boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 8 }}>
          <StarOutlined style={{ color: '#1677ff', fontSize: 22 }} />
          <span style={{ fontSize: 20, fontWeight: 600 }}>Vera</span>
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

        {dingtalkEnabled && (
          <>
            <Divider style={{ margin: '16px 0', fontSize: 12, color: '#00000040' }}>或</Divider>
            <Button block size="large" onClick={handleDingtalk} style={{ color: '#1677ff', borderColor: '#1677ff' }}>
              钉钉登录
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
