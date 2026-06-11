/** Permission types */

export type PermissionAction = 'view' | 'update' | 'delete';

export interface Permission {
  id: string;
  agentId: string;
  userName: string;
  userEmail: string;
  avatarUrl?: string;
  agentPermissions: PermissionAction[];
  authPermissions: PermissionAction[];
}

export interface PermissionGroup {
  userName: string;
  userEmail: string;
  agentPermissions: PermissionAction[];
  authPermissions: PermissionAction[];
}
