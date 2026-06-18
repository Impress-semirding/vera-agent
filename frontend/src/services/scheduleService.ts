import api from './api';
import type { ApiResponse } from '@/types/api';

export interface ScheduleTask {
  id: string;
  agentId: string;
  userId: string;
  sessionId?: string | null;
  name: string;
  prompt: string;
  scriptContent?: string | null;
  scriptName?: string | null;
  cron: string;
  timeout: number;
  source: 'system' | 'chat';
  taskType?: 'agent' | 'script+agent';
  enabled: boolean;
  status: string;
  failCount: number;
  nextRunAt?: string | null;
  lastRunAt?: string | null;
  lastStatus?: string | null;
  lastResult?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

export const scheduleService = {
  list: (agentId: string) =>
    api.get<any, ApiResponse<ScheduleTask[]>>(`/agents/${agentId}/schedules`),

  create: (agentId: string, data: Partial<ScheduleTask>) =>
    api.post<any, ApiResponse<ScheduleTask>>(`/agents/${agentId}/schedules`, data),

  update: (agentId: string, taskId: string, data: Partial<ScheduleTask>) =>
    api.put<any, ApiResponse<ScheduleTask>>(`/agents/${agentId}/schedules/${taskId}`, data),

  remove: (agentId: string, taskId: string) =>
    api.delete<any, ApiResponse<void>>(`/agents/${agentId}/schedules/${taskId}`),

  toggle: (agentId: string, taskId: string) =>
    api.post<any, ApiResponse<ScheduleTask>>(`/agents/${agentId}/schedules/${taskId}/toggle`),
};
