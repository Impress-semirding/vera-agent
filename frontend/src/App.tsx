import { useEffect } from 'react';
import { Spin } from 'antd';
import { useAuthStore } from '@/stores/useAuthStore';
import AppRoutes from './routes';

export default function App() {
  const status = useAuthStore((s) => s.status);
  const bootstrap = useAuthStore((s) => s.bootstrap);

  useEffect(() => {
    // Validate any persisted identity once on app start.
    bootstrap();
  }, [bootstrap]);

  // Show nothing but a spinner while we confirm the persisted login, so the
  // route guard doesn't flash a redirect to /login before status resolves.
  if (status === 'unknown') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Spin />
      </div>
    );
  }

  return <AppRoutes />;
}
