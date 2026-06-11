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
};
