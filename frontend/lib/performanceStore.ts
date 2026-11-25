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
  openPnlCurve: PerfPoint[];
  /** Newest equity_snapshots date (server-local `YYYY-MM-DD`), null when none. */
  lastSnapshotDate: string | null;
  /** Date of the latest GET /api/portfolio that skipped the snapshot (unquoted rows). */
  snapshotSkippedOn: string | null;
  /** Contract ids of the rows that blocked that snapshot. */
  snapshotSkippedContracts: string[];
}

const EMPTY_PERF: Performance = {
  realizedToday: 0, realizedWeek: 0, realizedMonth: 0, realizedYear: 0,
  realizedCurve: [], equityCurve: [], openPnlCurve: [],
  lastSnapshotDate: null, snapshotSkippedOn: null, snapshotSkippedContracts: [],
};

// Monotonic request sequence: the dashboard and the Portfolio page both call
// fetchPerformance, unordered. A response from an earlier-issued request never
// overwrites one applied from a later-issued request.
let _issuedSeq = 0;
let _appliedSeq = 0;

const BASE = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface PerfState {
  history: ClosedPosition[];
  performance: Performance;
  /** Epoch ms the request that produced `performance` was ISSUED (not when it
   *  resolved), so the page can tell it was read after the first sync. Not persisted. */
  fetchedAt: number | null;
  fetchHistory: () => Promise<void>;
  fetchPerformance: () => Promise<void>;
  /** Resolves true when the row was dropped (2xx/204/404); false when it still exists server-side. */
  removeHistory: (id: string) => Promise<boolean>;
  clearAllHistory: () => Promise<void>;
}

export const usePerformanceStore = create<PerfState>((set, get) => ({
  history: [],
  performance: EMPTY_PERF,
  fetchedAt: null,
  fetchHistory: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/history`);
      if (res.ok) set({ history: await res.json() });
    } catch { /* backend offline */ }
  },
  fetchPerformance: async () => {
    const issuedAt = Date.now();
    const seq = ++_issuedSeq;
    try {
      const res = await fetch(`${BASE()}/api/portfolio/performance`);
      if (!res.ok) return;
      const raw = await res.json();
      if (seq < _appliedSeq) return; // a later-issued request already applied
      _appliedSeq = seq;
      const performance: Performance = {
        ...EMPTY_PERF,
        ...raw,
        lastSnapshotDate: raw?.lastSnapshotDate ?? null,
        snapshotSkippedOn: raw?.snapshotSkippedOn ?? null,
        snapshotSkippedContracts: Array.isArray(raw?.snapshotSkippedContracts) ? raw.snapshotSkippedContracts : [],
      };
      set({ performance, fetchedAt: issuedAt });
    } catch { /* backend offline */ }
  },
  removeHistory: async (id) => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/history/${id}`, { method: 'DELETE' });
      // 404: already gone server-side, so dropping it locally is correct. Anything
      // else (500…) means it still counts server-side: keep the row on screen.
      if (res.ok || res.status === 204 || res.status === 404) {
        set({ history: get().history.filter((h) => h.id !== id) });
        return true;
      }
      return false;
    } catch {
      return false; /* backend offline */
    }
  },
  clearAllHistory: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/history`, { method: 'DELETE' });
      if (res.ok || res.status === 204) set({ history: [], performance: EMPTY_PERF });
    } catch { /* backend offline */ }
  },
}));
