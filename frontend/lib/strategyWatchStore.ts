'use client';

import { create } from 'zustand';
import { api, type StrategyWatch, type StrategyWatchSchedule } from '@/lib/api';
import type { TunedHorizon } from '@/lib/horizonPresets';

interface StrategyWatchStore {
  watches: StrategyWatch[];
  schedule: StrategyWatchSchedule | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  add: (symbol: string, strategyKey: string, direction?: 'Bullish' | 'Bearish',
        paramsHorizon?: TunedHorizon | null) => Promise<void>;
  addBulk: (symbols: string[], strategyKey: string, direction?: 'Bullish' | 'Bearish',
            paramsHorizon?: TunedHorizon | null) => Promise<void>;
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

  add: async (symbol, strategyKey, direction = 'Bullish', paramsHorizon = null) => {
    try {
      await api.addStrategyWatch(symbol, strategyKey, direction, paramsHorizon);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  addBulk: async (symbols, strategyKey, direction = 'Bullish', paramsHorizon = null) => {
    try {
      await api.addStrategyWatchesBulk(symbols, strategyKey, direction, paramsHorizon);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  remove: async (id) => {
    try {
      await api.removeStrategyWatch(id);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  setEnabled: async (id, enabled) => {
    try {
      await api.setStrategyWatchEnabled(id, enabled);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
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
