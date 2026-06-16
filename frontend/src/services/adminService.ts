import api from './api';
import type { ApiResponse } from '@/types/api';

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string | null;
  dingtalkUnionId?: string | null;
  isSuperuser: boolean;
  maxConcurrentTurns: number | null;
}

export const adminService = {
  listUsers: () => api.get<any, ApiResponse<{ users: AdminUser[]; defaultMaxTurns: number }>>('/admin/users'),

  setConcurrency: (userId: string, maxConcurrentTurns: number | null) =>
    api.put<any, ApiResponse<AdminUser>>(`/admin/users/${userId}/concurrency`, { maxConcurrentTurns }),
};
