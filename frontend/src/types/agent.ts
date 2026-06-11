/** Agent types — mirrors Reasonix agent model + HTML prototype */
export type AgentType = 'system' | 'personal';
export type AppMode = 'claude' | 'normal';

export interface Agent {
  id: string;
  name: string;
  description?: string;
  type: AgentType;
  mode: AppMode;
  model: string;
  avatarUrl?: string;
  visibility: boolean;
  starred: boolean;
  createdBy: string;
  updatedBy: string;
  updatedAt: string;
  createdAt: string;
}

export interface AgentListParams {
  type?: AgentType | 'all';
  mode?: AppMode;
  search?: string;
  mine?: boolean;
  starred?: boolean;
  page?: number;
  pageSize?: number;
}

export interface AgentFormData {
  name: string;
  description?: string;
  model: string;
  avatarUrl?: string;
  visibility?: boolean;
  type: AgentType;
  mode: AppMode;
}
