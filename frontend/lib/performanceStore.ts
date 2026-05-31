// frontend/lib/performanceStore.ts
import { create } from 'zustand';

export interface ClosedPosition {
  id: string;
  recId: string;
  symbol: string;
  contract: string;
  direction: string;
  entryPrice: number;
  entryDate?: string;
  exitPrice: number;
  exitDate: string;
  qtyClosed: number;
  realizedPnlDollar: number;
  realizedPnlPct: number;
  closedAt: string;
}

export interface PerfPoint { date: string; value: number }

export interface Performance {
  realizedToday: number;
  realizedWeek: number;
  realizedMonth: number;
  realizedYear: number;
  realizedCurve: PerfPoint[];
  equityCurve: PerfPoint[];
}

const EMPTY_PERF: Performance = {
  realizedToday: 0, realizedWeek: 0, realizedMonth: 0, realizedYear: 0,
  realizedCurve: [], equityCurve: [],
};

const BASE = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface PerfState {
  history: ClosedPosition[];
  performance: Performance;
  fetchHistory: () => Promise<void>;
  fetchPerformance: () => Promise<void>;
  removeHistory: (id: string) => Promise<void>;
}

export const usePerformanceStore = create<PerfState>((set, get) => ({
  history: [],
  performance: EMPTY_PERF,
  fetchHistory: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/history`);
      if (res.ok) set({ history: await res.json() });
    } catch { /* backend offline */ }
  },
  fetchPerformance: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/performance`);
      if (res.ok) set({ performance: await res.json() });
    } catch { /* backend offline */ }
  },
  removeHistory: async (id) => {
    try {
      await fetch(`${BASE()}/api/portfolio/history/${id}`, { method: 'DELETE' });
      set({ history: get().history.filter((h) => h.id !== id) });
    } catch { /* backend offline */ }
  },
}));
