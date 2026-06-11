import { create } from 'zustand';
import type { Agent, AgentType, AppMode } from '@/types/agent';
import { agentService } from '@/services/agentService';

interface AgentStore {
  agents: Agent[];
  total: number;
  loading: boolean;
  mode: AppMode;
  typeFilter: AgentType | 'all';
  search: string;
  mineOnly: boolean;
  starredOnly: boolean;
  setMode: (mode: AppMode) => void;
  setTypeFilter: (f: AgentType | 'all') => void;
  setSearch: (s: string) => void;
  toggleMine: () => void;
  toggleStarred: () => void;
  fetchAgents: () => Promise<void>;
  toggleStar: (id: string) => Promise<void>;
  createAgent: (data: any) => Promise<Agent>;
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: [],
  total: 0,
  loading: false,
  mode: 'claude',
  typeFilter: 'all',
  search: '',
  mineOnly: false,
  starredOnly: false,

  setMode: (mode) => set({ mode }),
  setTypeFilter: (f) => set({ typeFilter: f }),
  setSearch: (s) => set({ search: s }),
  toggleMine: () => set((s) => ({ mineOnly: !s.mineOnly })),
  toggleStarred: () => set((s) => ({ starredOnly: !s.starredOnly })),

  fetchAgents: async () => {
    set({ loading: true });
    try {
      const { mode, typeFilter, search, mineOnly, starredOnly } = get();
      const res = await agentService.list({
        mode,
        type: typeFilter,
        search: search || undefined,
        mine: mineOnly || undefined,
        starred: starredOnly || undefined,
      });
      set({ agents: res.data.items, total: res.data.total });
    } catch {
      // Error already logged by the axios response interceptor.
      // Keep existing list rather than wiping it on a transient failure.
    } finally {
      set({ loading: false });
    }
  },

  toggleStar: async (id) => {
    await agentService.star(id);
    set((s) => ({
      agents: s.agents.map((a) => (a.id === id ? { ...a, starred: !a.starred } : a)),
    }));
  },

  createAgent: async (data) => {
    const res = await agentService.create(data);
    await get().fetchAgents();
    return res.data;
  },
}));
