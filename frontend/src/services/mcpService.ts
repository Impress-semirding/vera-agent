import api from './api';
import type { ApiResponse } from '@/types/api';
import type { McpTransport } from '@/types/mcp';

/** A single tool returned by the backend (includes id + parameters). */
export interface McpToolResponse {
  id: string;
  name: string;
  description: string;
  parameters?: unknown;
  enabled: boolean;
}

/** A server-with-tools row returned by the backend (includes id / agentId). */
export interface McpServerWithToolsResponse {
  id: string;
  agentId: string;
  name: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  transport: McpTransport;
  url?: string;
  headers?: Record<string, string>;
  disabled: boolean;
  tools: McpToolResponse[];
}

/** Payload accepted by POST /agents/{agentId}/mcp-servers. */
export interface McpServerCreateData {
  name: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  transport?: McpTransport;
  url?: string;
  headers?: Record<string, string>;
  disabled?: boolean;
}

/** Partial fields accepted by PUT /mcp-servers/{serverId}. */
export type McpServerUpdateData = Partial<Omit<McpServerCreateData, 'name'>> & {
  name?: string;
};

export const mcpService = {
  list: (agentId: string) =>
    api.get<unknown, ApiResponse<McpServerWithToolsResponse[]>>(
      `/agents/${agentId}/mcp-servers`,
    ),

  create: (agentId: string, data: McpServerCreateData) =>
    api.post<unknown, ApiResponse<McpServerWithToolsResponse>>(
      `/agents/${agentId}/mcp-servers`,
      data,
    ),

  update: (serverId: string, data: McpServerUpdateData) =>
    api.put<unknown, ApiResponse<McpServerWithToolsResponse>>(
      `/mcp-servers/${serverId}`,
      data,
    ),

  remove: (serverId: string) =>
    api.delete<unknown, ApiResponse<void>>(`/mcp-servers/${serverId}`),

  toggleServer: (serverId: string, disabled: boolean) =>
    api.patch<unknown, ApiResponse<{ id: string; disabled: boolean }>>(
      `/mcp-servers/${serverId}/disabled`,
      { disabled },
    ),

  toggleTool: (toolId: string, enabled: boolean) =>
    api.patch<unknown, ApiResponse<{ id: string; enabled: boolean }>>(
      `/mcp-tools/${toolId}/enabled`,
      { enabled },
    ),
};
