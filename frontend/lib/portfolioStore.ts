/*
 * Portfolio store — Zustand with localStorage persistence.
 *
 * Holds open positions. Step 7's "Send to broker" flow calls `addPosition`
 * to push new orders in — tagged as either `broker` or `manual` via `source`.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { PortfolioPosition, TargetLevel, Direction } from '@/types/domain';

type BackendPosition = {
  id: string;
  recId: string;
  symbol: string;
  contract: string;
  direction: string;
  entryPrice: number;
  qty: number;
  entryDate: string;
  stop: number | null;
  targets: TargetLevel[];
  dteTotal: number | null;
  createdAt: string;
  // Live fields enriched by GET /portfolio via Tradier
  currentPrice?: number;
  pnlDollar?: number;
  pnlPct?: number;
  dteRemaining?: number;
  delta?: number | null;
  theta?: number | null;
  ivRank?: number | null;
};

function fromBackend(p: BackendPosition): PortfolioPosition {
  const parts = p.contract.split('|');
  const expiry = parts[2] ?? '';

  return {
    symbol:       p.symbol,
    contract:     p.contract,
    direction:    p.direction as Direction,
    entryPrice:   p.entryPrice,
    contracts:    p.qty,
    entryDate:    p.entryDate,
    expiry,
    stop:         p.stop ?? 0,
    targets:      p.targets ?? [],
    dteTotal:     p.dteTotal ?? 0,
    dteRemaining: p.dteRemaining ?? 0,
    status:       'PENDING',
    recId:        p.recId,
    currentPrice: p.currentPrice ?? 0,
    pnlDollar:    p.pnlDollar ?? 0,
    pnlPct:       p.pnlPct ?? 0,
    delta:        p.delta ?? undefined,
    theta:        p.theta ?? undefined,
    ivRank:       p.ivRank ?? undefined,
  };
}

interface PortfolioStoreState {
  positions: PortfolioPosition[];
  hydrate:        (positions: PortfolioPosition[]) => void;
  addPosition:    (p: PortfolioPosition) => void;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  closePosition:  (contract: string) => void;
  closePositionRemote: (
    recId: string,
    opts: { qtyToClose?: number | null; exitPrice?: number | null; exitDate?: string | null; sendToBroker?: boolean },
  ) => Promise<boolean>;
  syncFromBackend: () => Promise<void>;
  syncToBackend:  () => Promise<void>;
}

const _BASE_URL = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function toBackendPayload(p: PortfolioPosition, portfolioValue = 100_000) {
  return {
    recId:         p.recId,
    symbol:        p.symbol,
    contract:      p.contract,
    direction:     p.direction,
    entryPrice:    p.entryPrice,
    qty:           p.contracts ?? 1,
    entryDate:     p.entryDate ?? new Date().toISOString().slice(0, 10),
    stop:          p.stop > 0 ? p.stop : null,
    targets:       p.targets ?? [],
    dteTotal:      p.dteTotal ?? null,
    portfolioValue,
  };
}

async function postPosition(p: PortfolioPosition, portfolioValue = 100_000): Promise<void> {
  try {
    await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    // 409 = already exists → fine. Other errors silently ignored (backend may be offline).
  } catch { /* network unavailable */ }
}

/** POST to the backend and return whether it was accepted.
 *  Used by the single-order buttons in Step 7 so rejections (risk check, duplicate
 *  symbol) surface to the user instead of being silently dropped. */
export async function persistPosition(
  p: PortfolioPosition,
  portfolioValue = 100_000,
): Promise<{ ok: boolean; detail?: string }> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    if (res.ok || res.status === 409) return { ok: true };
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    return { ok: true }; // backend offline — don't block the user
  }
}

async function deletePosition(recId: string): Promise<void> {
  try {
    await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, { method: 'DELETE' });
  } catch { /* network unavailable */ }
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
      addPosition: (p) => {
        let resolvedPosition: PortfolioPosition | null = null;
        let computedPortfolioValue = 100_000;
        set((s) => {
          const recId = (p as PortfolioPosition & { recId?: string }).recId || generateRecId();
          const incoming = { ...p, recId } as PortfolioPosition;
          resolvedPosition = incoming;

          // Compute portfolio value from existing positions so the backend risk
          // check is calibrated against real capital, not the 100k default.
          computedPortfolioValue = s.positions.reduce((sum, pos) => {
            const multiplier = pos.contract?.endsWith('|STOCK') ? 1 : 100;
            return sum + pos.entryPrice * (pos.contracts ?? 1) * multiplier;
          }, 0) || 100_000;

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
        });
        // Fire-and-forget sync to backend so the monitor sees new positions
        if (resolvedPosition) postPosition(resolvedPosition, computedPortfolioValue);
      },
      updatePosition: (contract, patch) =>
        set((s) => ({
          positions: s.positions.map((r) =>
            r.contract === contract ? { ...r, ...patch } : r
          ),
        })),
      closePosition: (contract) => {
        let closedRecId: string | undefined;
        set((s) => {
          closedRecId = s.positions.find((r) => r.contract === contract)?.recId;
          return { positions: s.positions.filter((r) => r.contract !== contract) };
        });
        if (closedRecId) deletePosition(closedRecId);
      },
      closePositionRemote: async (recId, opts) => {
        try {
          const res = await fetch(`${_BASE_URL()}/api/portfolio/${recId}/close`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              qtyToClose: opts.qtyToClose ?? null,
              exitPrice: opts.exitPrice ?? null,
              exitDate: opts.exitDate ?? null,
              sendToBroker: opts.sendToBroker ?? false,
            }),
          });
          if (!res.ok) return false;
          // Re-pull authoritative open positions (partial closes change qty)
          await usePortfolioStore.getState().syncFromBackend();
          return true;
        } catch {
          return false;
        }
      },
      syncFromBackend: async () => {
        try {
          const res = await fetch(`${_BASE_URL()}/api/portfolio`);
          if (!res.ok) return;
          const positions: BackendPosition[] = await res.json();
          set({ positions: positions.map(fromBackend) });
        } catch {
          // network unavailable — keep localStorage state
        }
      },
      syncToBackend: async () => {
        // Push all local positions to the backend (409 = already there, safe to ignore).
        const { positions } = usePortfolioStore.getState();
        const totalValue = positions.reduce((sum, pos) => {
          const multiplier = pos.contract?.endsWith('|STOCK') ? 1 : 100;
          return sum + pos.entryPrice * (pos.contracts ?? 1) * multiplier;
        }, 0) || 100_000;
        await Promise.all(positions.map((p) => postPosition(p, totalValue)));
      },
    }),
    {
      name: 'bamendjou-portfolio-v1',
      skipHydration: true,
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
