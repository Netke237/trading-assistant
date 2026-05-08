/*
 * Portfolio store — Zustand with localStorage persistence.
 *
 * Holds open positions. Step 7's "Send to broker" flow calls `addPosition`
 * to push new orders in — tagged as either `broker` or `manual` via `source`.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { PortfolioPosition } from '@/types/domain';

interface PortfolioStoreState {
  positions: PortfolioPosition[];
  hydrate:        (positions: PortfolioPosition[]) => void;
  addPosition:    (p: PortfolioPosition) => void;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  closePosition:  (contract: string) => void;
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

function dedupePositions(positions: PortfolioPosition[]): PortfolioPosition[] {
  const map = new Map<string, PortfolioPosition>();
  for (const p of positions) {
    const existing = map.get(p.recId);
    if (!existing) {
      map.set(p.recId, p);
    } else {
      const existingTime = existing.orderedAt ?? existing.entryDate ?? '';
      const incomingTime = p.orderedAt ?? p.entryDate ?? '';
      if (incomingTime >= existingTime) {
        map.set(p.recId, p);
      }
    }
  }
  return Array.from(map.values());
}

function validatePositions(positions: unknown): PortfolioPosition[] {
  if (!Array.isArray(positions)) return [];
  return positions.filter((p): p is PortfolioPosition => {
    if (typeof p !== 'object' || p === null) return false;
    const po = p as Record<string, unknown>;
    return (
      typeof po.recId === 'string' &&
      typeof po.symbol === 'string' &&
      typeof po.contract === 'string'
    );
  });
}

export const usePortfolioStore = create<PortfolioStoreState>()(
  persist(
    (set) => ({
      positions: [],
      hydrate: (positions) =>
        set({
          positions: positions.map((p) =>
            (p as PortfolioPosition).recId ? p : { ...p, recId: generateRecId() }
          ),
        }),
      addPosition: (p) =>
        set((s) => {
          const recId = (p as PortfolioPosition & { recId?: string }).recId || generateRecId();
          const incoming = { ...p, recId } as PortfolioPosition;

          const idxByRecId = s.positions.findIndex((x) => x.recId === incoming.recId);
          if (idxByRecId >= 0) {
            const next = [...s.positions];
            next[idxByRecId] = { ...next[idxByRecId]!, ...incoming };
            return { positions: next };
          }

          const idxByKey = s.positions.findIndex(
            (x) =>
              x.symbol === incoming.symbol &&
              x.contract === incoming.contract &&
              x.entryDate === incoming.entryDate
          );
          if (idxByKey >= 0) {
            // eslint-disable-next-line no-console
            console.warn(
              '[portfolioStore] merging duplicate position for',
              incoming.symbol,
              incoming.contract
            );
            const next = [...s.positions];
            const existing = next[idxByKey]!;
            next[idxByKey] = {
              ...existing,
              contracts: (existing.contracts ?? 0) + (incoming.contracts ?? 0),
            };
            return { positions: next };
          }

          return { positions: [...s.positions, incoming] };
        }),
      updatePosition: (contract, patch) =>
        set((s) => ({
          positions: s.positions.map((r) =>
            r.contract === contract ? { ...r, ...patch } : r
          ),
        })),
      closePosition: (contract) =>
        set((s) => ({ positions: s.positions.filter((r) => r.contract !== contract) })),
    }),
    {
      name: 'bamendjou-portfolio-v1',
      partialize: (state) => ({ positions: state.positions }),
      merge: (persistedState, currentState) => {
        const ps = persistedState as Partial<PortfolioStoreState> | undefined;
        if (!ps || !Array.isArray(ps.positions)) {
          return currentState;
        }
        const valid = validatePositions(ps.positions).map((p) =>
          p.recId ? p : { ...p, recId: generateRecId() }
        );
        return {
          ...currentState,
          positions: dedupePositions(valid),
        };
      },
    }
  )
);
