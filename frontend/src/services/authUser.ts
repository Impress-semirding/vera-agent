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
}

const KEY = 'reasonix.user';

export function getUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function getUserName(): string | null {
  return getUser()?.name ?? null;
}

export function setUser(user: AuthUser): void {
  localStorage.setItem(KEY, JSON.stringify(user));
}

export function clearUser(): void {
  localStorage.removeItem(KEY);
}
