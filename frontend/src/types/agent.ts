/** Agent types — mirrors Reasonix agent model + HTML prototype */
export type AgentType = 'system' | 'personal';
export type AppMode = 'claude' | 'normal';

export type PermissionLevel = 'view' | 'edit' | 'delete';

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
  wechatEnabled?: boolean;
  wechatToken?: string | null;
  createdBy: string;
  updatedBy: string;
  updatedAt: string;
  createdAt: string;
  /** 当前用户对该 agent 的权限列表（owner 返回全部） */
  permissions?: PermissionLevel[];
}

export interface AgentPermission {
  id: string;
  agentId: string;
  userName: string;
  userEmail: string;
  avatarUrl?: string;
  agentPermissions: PermissionLevel[];
  authPermissions: string[];
}

export interface PermissionFormData {
  userName: string;
  userEmail: string;
  avatarUrl?: string;
  agentPermissions: PermissionLevel[];
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
