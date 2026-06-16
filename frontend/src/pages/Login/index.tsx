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
  const [totpPending, setTotpPending] = useState({ identifier: '', password: '' });
  const [totpCode, setTotpCode] = useState('');

  const from = (location.state as { from?: string } | null)?.from ?? '/';

  useEffect(() => {
    authService.dingtalkConfig().then((res: any) => {
      setDingtalkEnabled(!!res.data?.enabled);
    }).catch(() => setDingtalkEnabled(false));
  }, []);

  const handleFinish = async (values: { identifier: string; password: string }) => {
    setError(null);
    setSubmitting(true);
    try {
      const res: any = await login(values.identifier, values.password);
      if (res?.requireTotp) {
        setTotpPending(values);
        return;
      }
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

  const handleTotpSubmit = async () => {
    if (!totpCode || totpCode.length !== 6) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(totpPending.identifier, totpPending.password, totpCode);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      setError(
        (err as any)?.response?.data?.message || '验证失败',
      );
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

        {totpPending.identifier ? (
          /* TOTP second-factor */
          <>
            <p style={{ textAlign: 'center', color: '#00000073', fontSize: 13, marginBottom: 12 }}>
              已通过密码验证，请输入 Google Authenticator 中的 6 位验证码
            </p>
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <Input
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onPressEnter={handleTotpSubmit}
                placeholder="000000"
                style={{ textAlign: 'center', fontSize: 18, letterSpacing: 4 }}
                autoFocus
              />
            </div>
            <Button type="primary" block loading={submitting} onClick={handleTotpSubmit} disabled={totpCode.length !== 6}>
              验证
            </Button>
            <Button type="link" block onClick={() => { setTotpPending({ identifier: '', password: '' }); setTotpCode(''); }}>
              返回
            </Button>
          </>
        ) : (
          <Form layout="vertical" onFinish={handleFinish} preserve={false}>
          <Form.Item label="用户名 / 邮箱" name="identifier" rules={[{ required: true, message: '请输入用户名或邮箱' }]}>
            <Input placeholder="请输入用户名或邮箱" autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>登录</Button>
          {dingtalkEnabled && (
            <>
              <Divider style={{ margin: '16px 0', fontSize: 12, color: '#00000040' }}>或</Divider>
              <Button block size="large" onClick={handleDingtalk} style={{ color: '#1677ff', borderColor: '#1677ff' }}>
                钉钉登录
              </Button>
            </>
          )}
        </Form>
        )}
      </div>
    </div>
  );
}
