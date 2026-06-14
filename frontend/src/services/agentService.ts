import api from './api';
import type { Agent, AgentFormData, AgentListParams } from '@/types/agent';
import type { ApiResponse, PaginatedData } from '@/types/api';

export const agentService = {
  list: (params?: AgentListParams) =>
    api.get<any, ApiResponse<PaginatedData<Agent>>>('/agents', { params }),

  get: (id: string) =>
    api.get<any, ApiResponse<Agent>>(`/agents/${id}`),

  create: (data: AgentFormData) =>
    api.post<any, ApiResponse<Agent>>('/agents', data),

  update: (id: string, data: Partial<Agent>) =>
    api.put<any, ApiResponse<Agent>>(`/agents/${id}`, data),

  delete: (id: string) =>
    api.delete<any, ApiResponse<void>>(`/agents/${id}`),

  star: (id: string) =>
    api.post<any, ApiResponse<void>>(`/agents/${id}/star`),

  // ─── WeChat iLink ────────────────────────────────────────
  getWechatStatus: (agentId: string) =>
    api.get<any, ApiResponse<{
      enabled: boolean;
      loginStatus: string;
      ilinkUserId?: string | null;
      ilinkBotId?: string | null;
    }>>(`/agents/${agentId}/wechat`),

  startWechatLogin: (agentId: string) =>
    api.post<any, ApiResponse<{
      qrcode: string;
      qrcodeImg: string;
      loginStatus: string;
    }>>(`/agents/${agentId}/wechat/login`),

  pollWechatLogin: (agentId: string) =>
    api.get<any, ApiResponse<{
      loginStatus: string;
      ilinkUserId?: string | null;
    }>>(`/agents/${agentId}/wechat/login/status`),

  disconnectWechat: (agentId: string) =>
    api.post<any, ApiResponse<{ loginStatus: string; enabled: boolean }>>(`/agents/${agentId}/wechat/logout`),

  toggleWechat: (agentId: string, enabled: boolean) =>
    api.put<any, ApiResponse<{ enabled: boolean }>>(`/agents/${agentId}/wechat/toggle`, { enabled }),
};
