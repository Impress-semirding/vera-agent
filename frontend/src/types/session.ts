/** Session and chat types */

export interface Session {
  id: string;
  agentId: string;
  name: string;
  projectId?: string;
  createdAt: string;
  lastMessageAt?: string;
}

export interface ChatMessage {
  id: string;
  sessionId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoningContent?: string;
  segments?: Array<{
    kind: string;
    text?: string;
    callId?: string;
    name?: string;
    args?: string;
    output?: string;
    ok?: boolean;
    done?: boolean;
    source?: string;
  }> | null;
  timestamp: string;
  artifacts?: Artifact[];
}

export interface ToolCallRecord {
  callId: string;
  name: string;
  args: string;
  status: string;
  ok?: boolean;
  output?: string;
}

export interface Artifact {
  type: 'browser' | 'file';
  url?: string;
  fileName?: string;
  content?: string;
}

export interface Project {
  id: string;
  name: string;
  sessions: Session[];
}
