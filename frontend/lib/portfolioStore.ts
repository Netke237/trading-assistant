/*
 * Portfolio store — Zustand.
 *
 * Ephemeral for now (mock-only, resets on reload). Seeded from MOCK_PORTFOLIO
 * so the Portfolio page keeps its populated demo state. Step 7's "Send to
 * broker" flow calls `addPosition` to push new orders in — tagged as either
 * `broker` or `manual` via `source`.
 */

import { create } from 'zustand';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import type { PortfolioPosition } from '@/types/domain';

interface PortfolioStoreState {
  positions: PortfolioPosition[];
  addPosition:    (p: PortfolioPosition) => void;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  closePosition:  (contract: string) => void;
}

export const usePortfolioStore = create<PortfolioStoreState>((set) => ({
  positions: MOCK_PORTFOLIO,
  addPosition: (p) => set((s) => {
    const existingIdx = s.positions.findIndex((x) => x.contract === p.contract);
    if (existingIdx >= 0) {
      // Same contract already open — merge contract counts, keep the earlier entry.
      const next = [...s.positions];
      const prev = next[existingIdx]!;
      next[existingIdx] = {
        ...prev,
        contracts: (prev.contracts ?? 1) + (p.contracts ?? 1),
      };
      return { positions: next };
    }
    return { positions: [...s.positions, p] };
  }),
  updatePosition: (contract, patch) =>
    set((s) => ({
      positions: s.positions.map((r) => (r.contract === contract ? { ...r, ...patch } : r)),
    })),
  closePosition: (contract) =>
    set((s) => ({ positions: s.positions.filter((r) => r.contract !== contract) })),
}));
