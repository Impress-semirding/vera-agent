import api from './api';
import type { ApiResponse } from '@/types/api';
import type { ConfigFile } from '@/types/config';

export interface ConfigFileContent {
  name: string;
  path: string;
  content: string;
}

export const configFileService = {
  tree: (agentId: string) =>
    api.get<any, ApiResponse<ConfigFile[]>>(`/agents/${agentId}/config-files`),

  read: (agentId: string, path: string) =>
    api.get<any, ApiResponse<ConfigFileContent>>(`/agents/${agentId}/config-files/content`, { params: { path } }),

  save: (agentId: string, path: string, content: string) =>
    api.put<any, ApiResponse<ConfigFileContent>>(`/agents/${agentId}/config-files`, { content }, { params: { path } }),

  create: (agentId: string, path: string, content: string) =>
    api.post<any, ApiResponse<ConfigFileContent>>(`/agents/${agentId}/config-files`, { path, content }),

  remove: (agentId: string, path: string) =>
    api.delete<any, ApiResponse<null>>(`/agents/${agentId}/config-files`, { params: { path } }),
};
