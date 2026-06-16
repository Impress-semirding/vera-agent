import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import AgentListPage from '@/pages/AgentList';
import CreateAgentPage from '@/pages/CreateAgent';
import EditAgentPage from '@/pages/EditAgent';
import LoginPage from '@/pages/Login';
import DingtalkCallback from '@/pages/Login/DingtalkCallback';
import AdminUsersPage from '@/pages/Admin/Users';
import { useAuthStore } from '@/stores/useAuthStore';

/** Guard: redirect unauthenticated users to /login, remembering the target. */
function RequireAuth({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login/dingtalk/callback" element={<DingtalkCallback />} />
      <Route path="/" element={<RequireAuth><AgentListPage /></RequireAuth>} />
      <Route path="/admin/users" element={<RequireAuth><AdminUsersPage /></RequireAuth>} />
      <Route path="/create" element={<RequireAuth><CreateAgentPage /></RequireAuth>} />
      <Route path="/chat/:agentId" element={<RequireAuth><EditAgentPage /></RequireAuth>} />
      <Route path="/chat/:agentId/:sessionId" element={<RequireAuth><EditAgentPage /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
