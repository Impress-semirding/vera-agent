/**
 * Dependency-free bridge for the logged-in user, backed by localStorage.
 *
 * Kept free of axios/zustand imports on purpose: the axios request interceptor
 * and the chat WebSocket read identity from here, while `useAuthStore` wraps it
 * for reactive UI. Importing the store from the interceptor would create a
 * cycle (api → store → authService → api); this module breaks it.
 */

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
  isSuperuser?: boolean;
  maxConcurrentTurns?: number | null;
  token?: string;
}

const USER_KEY = 'reasonix.user';
const TOKEN_KEY = 'reasonix.token';

export function getUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function getUserName(): string | null {
  return getUser()?.name ?? null;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) || getUser()?.token || null;
}

export function setUser(user: AuthUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (user.token) localStorage.setItem(TOKEN_KEY, user.token);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearUser(): void {
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(TOKEN_KEY);
}
