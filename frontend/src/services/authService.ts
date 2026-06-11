import api from './api';
import type { ApiResponse } from '@/types/api';
import type { AuthUser } from './authUser';

export const authService = {
  /** Log in with name/email + password. Returns the authenticated user. */
  login: (identifier: string, password: string) =>
    api.post<any, ApiResponse<AuthUser>>('/auth/login', { identifier, password }),

  /** Confirm the persisted identity is still valid server-side. */
  me: () => api.get<any, ApiResponse<AuthUser>>('/auth/me'),
};
