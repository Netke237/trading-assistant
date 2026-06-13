'use client';

import { create } from 'zustand';
import { api, type StrategyWatch, type StrategyWatchSchedule } from '@/lib/api';

interface StrategyWatchStore {
  watches: StrategyWatch[];
  schedule: StrategyWatchSchedule | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  add: (symbol: string, strategyKey: string) => Promise<void>;
  addBulk: (symbols: string[], strategyKey: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  setEnabled: (id: string, enabled: boolean) => Promise<void>;
  saveSchedule: (cfg: StrategyWatchSchedule) => Promise<void>;
  evaluateNow: () => Promise<number>;
}

export const useStrategyWatchStore = create<StrategyWatchStore>((set, get) => ({
  watches: [],
  schedule: null,
  loading: false,
  error: null,

  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const [watches, schedule] = await Promise.all([
        api.getStrategyWatches(),
        api.getStrategyWatchSchedule(),
      ]);
      set({ watches, schedule, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  add: async (symbol, strategyKey) => {
    try {
      await api.addStrategyWatch(symbol, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  addBulk: async (symbols, strategyKey) => {
    try {
      await api.addStrategyWatchesBulk(symbols, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  remove: async (id) => {
    await api.removeStrategyWatch(id);
    await get().refresh();
  },

  setEnabled: async (id, enabled) => {
    await api.setStrategyWatchEnabled(id, enabled);
    await get().refresh();
  },

  saveSchedule: async (cfg) => {
    const saved = await api.setStrategyWatchSchedule(cfg);
    set({ schedule: saved });
  },

  evaluateNow: async () => {
    const result = await api.evaluateStrategyWatches();
    await get().refresh();
    return result.fired;
  },
}));
