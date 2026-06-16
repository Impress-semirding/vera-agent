import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spin, Result } from 'antd';
import { useAuthStore } from '@/stores/useAuthStore';

/**
 * DingTalk OAuth callback target.
 * DingTalk redirects here with ?authCode=... after the user scans/logs in.
 * We exchange the authCode for a Vera session via the backend, then navigate.
 */
export default function DingtalkCallback() {
  const navigate = useNavigate();
  const dingtalkLogin = useAuthStore((s) => s.dingtalkLogin);
  const startedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const authCode = params.get('authCode');
    const state = params.get('state') ?? '';
    const from = sessionStorage.getItem('login_from') ?? '/';
    sessionStorage.removeItem('login_from');
    // The DingTalk-issued state is opaque to us (we generated it server-side);
    // pass it back so the backend can validate CSRF.
    const storedState = sessionStorage.getItem('dingtalk_state') ?? '';
    sessionStorage.removeItem('dingtalk_state');

    if (!authCode) {
      setError('未收到钉钉授权码');
      return;
    }

    dingtalkLogin(authCode, state || storedState)
      .then(() => navigate(from, { replace: true }))
      .catch((err: unknown) => {
        const msg =
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
          '钉钉登录失败';
        setError(msg);
      });
  }, [dingtalkLogin, navigate]);

  if (error) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Result
          status="error"
          title="钉钉登录失败"
          subTitle={error}
          extra={
            <a href="/login" style={{ color: '#1677ff' }}>返回登录</a>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Spin tip="正在登录..." size="large" />
    </div>
  );
}
