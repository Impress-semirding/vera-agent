import { create } from 'zustand';
import { authService } from '@/services/authService';
import { clearUser, getUser, setUser } from '@/services/authUser';
import type { AuthUser } from '@/services/authUser';

type Status = 'unknown' | 'authed' | 'guest';

interface AuthStore {
  user: AuthUser | null;
  status: Status;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => void;
  /** Validate the persisted identity once on app start. */
  bootstrap: () => Promise<void>;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: getUser(),
  // 'unknown' while a persisted user is validated via bootstrap() (App shows a
  // spinner, avoiding a redirect flash); 'guest' when there's nothing stored.
  status: getUser() ? 'unknown' : 'guest',

  login: async (identifier, password) => {
    const res = await authService.login(identifier, password);
    setUser(res.data);
    set({ user: res.data, status: 'authed' });
  },

  logout: () => {
    clearUser();
    set({ user: null, status: 'guest' });
  },

  bootstrap: async () => {
    const stored = getUser();
    if (!stored) {
      set({ status: 'guest' });
      return;
    }
    try {
      const res = await authService.me();
      setUser(res.data);
      set({ user: res.data, status: 'authed' });
    } catch {
      // Persisted user no longer valid — drop it and require re-login.
      clearUser();
      set({ user: null, status: 'guest' });
    }
  },
}));
