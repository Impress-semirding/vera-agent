import api from './api';
import type { AgentPermission, PermissionFormData } from '@/types/agent';

const permissionService = {
  /** 获取 agent 的所有权限记录 */
  list: (agentId: string): Promise<{ data: AgentPermission[] }> =>
    api.get(`/agents/${agentId}/permissions`),

  /** 为 agent 添加一个用户权限 */
  add: (agentId: string, data: PermissionFormData): Promise<{ data: AgentPermission }> =>
    api.post(`/agents/${agentId}/permissions`, data),

  /** 更新某个权限记录 */
  update: (permissionId: string, data: Partial<PermissionFormData>): Promise<{ data: AgentPermission }> =>
    api.put(`/permissions/${permissionId}`, data),

  /** 移除某个权限记录 */
  remove: (permissionId: string): Promise<void> =>
    api.delete(`/permissions/${permissionId}`),
};

export default permissionService;
