import api from './api';
import type { ApiResponse } from '@/types/api';
import type { AuthUser } from './authUser';

export const authService = {
  /** Log in with name/email + password. Returns the authenticated user. */
  login: (identifier: string, password: string) =>
    api.post<any, ApiResponse<AuthUser | { requireTotp: boolean }>>('/auth/login', { identifier, password }),

  /** Raw login (supports extra fields like totpCode). */
  loginRaw: (body: any) =>
    api.post<any, ApiResponse<AuthUser | { requireTotp: boolean }>>('/auth/login', body),

  /** Confirm the persisted identity is still valid server-side. */
  me: () => api.get<any, ApiResponse<AuthUser>>('/auth/me'),

  // ─── DingTalk OAuth ──────────────────────────────────────
  /** Get DingTalk authorize URL + state (enabled=false if unconfigured). */
  dingtalkConfig: () =>
    api.get<any, ApiResponse<{ enabled: boolean; authorizeUrl: string | null; state: string | null }>>(
      '/auth/dingtalk/config',
    ),

  /** Exchange a DingTalk authCode for a Vera user. */
  dingtalkLogin: (authCode: string, state: string) =>
    api.post<any, ApiResponse<AuthUser>>('/auth/dingtalk/login', { authCode, state }),

  // ─── TOTP 2FA ────────────────────────────────────────
  totpSetup: () =>
    api.get<any, ApiResponse<{ secret: string; qrcodeUrl: string; qrcodeImg: string }>>('/auth/totp/setup'),

  totpVerify: (code: string) =>
    api.post<any, ApiResponse<{ enabled: boolean }>>('/auth/totp/verify', { code }),

  totpDisable: (code: string) =>
    api.post<any, ApiResponse<{ enabled: boolean }>>('/auth/totp/disable', { code }),
};
