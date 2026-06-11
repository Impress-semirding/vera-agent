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
  timestamp: string;
  artifacts?: Artifact[];
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
