import { create } from 'zustand';

interface UIStore {
  modeSelectVisible: boolean;
  setModeSelectVisible: (v: boolean) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  modeSelectVisible: false,
  setModeSelectVisible: (v) => set({ modeSelectVisible: v }),
}));
