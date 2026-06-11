/** History types */

export interface ExecRecord {
  id: string;
  agentId: string;
  sessionSource: string;
  sessionId: string;
  userId: string;
  timestamp: string;
  status: 'success' | 'failed' | 'timeout';
  content: string;
}

export interface ModifyRecord {
  id: string;
  agentId: string;
  operator: string;
  action: string;
  detail: string;
  timestamp: string;
}
