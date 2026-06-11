import api from './api';
import type { ApiResponse } from '@/types/api';
import type { Session, ChatMessage } from '@/types/session';

export const sessionService = {
  /** List all sessions for an agent. */
  list: (agentId: string) =>
    api.get<any, ApiResponse<Session[]>>(`/agents/${agentId}/sessions`),

  /** Create a new session under an agent; returns the created session. */
  create: (agentId: string, name?: string) =>
    api.post<any, ApiResponse<Session>>(`/agents/${agentId}/sessions`, { name }),

  /** Delete a session (and its messages). */
  remove: (sessionId: string) =>
    api.delete<any, ApiResponse<void>>(`/sessions/${sessionId}`),

  /** Load the message history of a session. */
  messages: (sessionId: string) =>
    api.get<any, ApiResponse<ChatMessage[]>>(`/sessions/${sessionId}/messages`),

  /** Persist a message in a session (default role: user). */
  send: (sessionId: string, content: string, role: 'user' | 'assistant' = 'user') =>
    api.post<any, ApiResponse<ChatMessage>>(
      `/sessions/${sessionId}/messages`,
      { content },
      { params: { role } },
    ),
};
