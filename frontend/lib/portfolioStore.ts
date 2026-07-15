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
  ) => Promise<{ ok: boolean; detail?: string }>;
  /** Returns whether the pull actually reached the backend and updated state
   *  (false on network failure — callers that just mutated local state around
   *  this call may need to know so they don't assume the pull "saw" their change). */
  syncFromBackend: () => Promise<boolean>;
  syncToBackend:  () => Promise<void>;
}

const _BASE_URL = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function toBackendPayload(p: PortfolioPosition, portfolioValue = 100_000) {
  return {
    recId:          p.recId,
    symbol:         p.symbol,
    contract:       p.contract,
    direction:      p.direction,
    entryPrice:     p.entryPrice,
    qty:            p.contracts ?? 1,
    entryDate:      p.entryDate ?? new Date().toISOString().slice(0, 10),
    stop:           p.stop > 0 ? p.stop : null,
    targets:        p.targets ?? [],
    dteTotal:       p.dteTotal ?? null,
    portfolioValue,
    scanStockPrice: p.scanStockPrice ?? null,
  };
}

async function postPosition(p: PortfolioPosition, portfolioValue = 100_000): Promise<void> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    // 409 is expected here: Step 7's order paths persistPosition() first, so this
    // fire-and-forget POST re-sends a contract the backend already has. Any other
    // refusal (422 risk check) leaves the local store ahead of the backend until
    // the next syncFromBackend reverts it — say so.
    if (!res.ok && res.status !== 409) {
      // eslint-disable-next-line no-console
      console.warn('[portfolioStore] backend rejected position', p.contract, `HTTP ${res.status}`);
    }
  } catch { /* network unavailable */ }
}

/** POST to the backend and return whether it was accepted.
 *  Used by the single-order buttons in Step 7 so rejections (risk check, duplicate
 *  contract) surface to the user instead of being silently dropped.
 *
 *  A 409 is *not* success: the backend keeps one open position per contract and
 *  has no scale-in path, so it recorded nothing. Reporting it as ok would let the
 *  caller add quantity that only ever existed in local state. */
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
    if (res.ok) return { ok: true };
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

/* The backend enforces one open position per contract (409 on a second POST),
 * so `contract` — not `recId` — is a position's identity. Dedupe on it, keeping
 * the earliest record, which is the one the backend accepted. */
function dedupePositions(positions: PortfolioPosition[]): PortfolioPosition[] {
  const map = new Map<string, PortfolioPosition>();
  for (const p of positions) {
    const existing = map.get(p.contract);
    if (!existing) {
      map.set(p.contract, p);
    } else {
      const existingTime = existing.orderedAt ?? existing.entryDate ?? '';
      const incomingTime = p.orderedAt ?? p.entryDate ?? '';
      if (incomingTime < existingTime) {
        map.set(p.contract, p);
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
            (x) => x.symbol === incoming.symbol && x.contract === incoming.contract
          );
          if (idxByKey >= 0) {
            // eslint-disable-next-line no-console
            console.warn(
              '[portfolioStore] merging duplicate position for',
              incoming.symbol,
              incoming.contract
            );
            // Only the count merges. entryPrice/entryDate stay at the original
            // fill because the backend refuses the second POST (409) and keeps
            // the first — averaging them here would diverge from the authoritative
            // cost basis that syncFromBackend pulls back.
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
        const doClose = async (id: string): Promise<Response> =>
          fetch(`${_BASE_URL()}/api/portfolio/${id}/close`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              qtyToClose: opts.qtyToClose ?? null,
              exitPrice: opts.exitPrice ?? null,
              exitDate: opts.exitDate ?? null,
              sendToBroker: opts.sendToBroker ?? false,
            }),
          });
        const local = usePortfolioStore.getState().positions.find((p) => p.recId === recId);

        // Fetch the authoritative open positions, or null if the backend is
        // unreachable / errors. Used to decide recId drift vs a genuinely-gone
        // position WITHOUT guessing from a persist failure code.
        const fetchRemote = async (): Promise<BackendPosition[] | null> => {
          try {
            const r = await fetch(`${_BASE_URL()}/api/portfolio`);
            if (!r.ok) return null;
            return (await r.json()) as BackendPosition[];
          } catch {
            return null;
          }
        };

        // Tracks whichever recId the successful close actually landed under —
        // starts as the caller's id, but drift recovery below may retry against
        // the backend's real id instead. Anything restored to local state after
        // a successful close must use THIS id, not the original parameter, or a
        // drift-recovered restore would carry a recId that 404s on every
        // subsequent action until the next sync heals it.
        let effectiveRecId = recId;

        try {
          let res = await doClose(recId);

          // A 404 means the backend has no open position under this recId:
          // either the original POST never landed, or the backend holds the same
          // *contract* under a different recId (drift, e.g. a DB reset while
          // localStorage kept the old id). Recover carefully — and only drop a
          // local row when the backend POSITIVELY confirms the contract is gone.
          if (res.status === 404 && local) {
            const persisted = await persistPosition(local);
            if (persisted.ok) {
              res = await doClose(recId);
            } else {
              const remote = await fetchRemote();
              if (remote) {
                const match = remote.find((p) => p.contract === local.contract);
                if (match?.recId && match.recId !== recId) {
                  effectiveRecId = match.recId;
                  res = await doClose(match.recId);            // drift: close the real row
                } else if (!match) {
                  // Backend reachable AND has no such contract → genuinely gone.
                  set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
                  return {
                    ok: false,
                    detail: 'This position was no longer on the server (already closed or cleared) — removed it from your list.',
                  };
                }
                // match with same recId shouldn't 404 — fall through to the error below.
              }
              // Backend unreachable: do NOT drop a possibly-valid position.
            }
          }

          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
          }

          // Success: remove the acted-upon local row so a fully-closed position
          // can't linger via syncFromBackend's localOnly retention (its contract
          // is now absent from the backend). A partial close re-appears from the
          // authoritative pull below with its reduced qty.
          const closedRow = usePortfolioStore.getState().positions.find((p) => p.recId === recId);
          const wasFullClose = !opts.qtyToClose || opts.qtyToClose >= (closedRow?.contracts ?? 1);
          set((s) => ({ positions: s.positions.filter((p) => p.recId !== recId) }));
          const synced = await usePortfolioStore.getState().syncFromBackend();
          // The close itself succeeded server-side regardless of this GET. But if
          // it was only a PARTIAL close and the follow-up pull failed (network),
          // the row above is now gone from local state with no way to learn its
          // reduced qty until the next successful sync — restore it locally
          // (qty adjusted, price/P&L stale until next sync) rather than making a
          // still-open position disappear from the list entirely.
          if (!synced && !wasFullClose && closedRow) {
            const remainingQty = Math.max(0, (closedRow.contracts ?? 1) - (opts.qtyToClose ?? 0));
            if (remainingQty > 0) {
              // Restore under effectiveRecId (the id the backend actually closed
              // against) — if drift recovery kicked in above, the backend no
              // longer recognizes the original `recId`, and restoring under the
              // stale id would just 404 again on the next action.
              set((s) => ({ positions: [...s.positions, { ...closedRow, recId: effectiveRecId, contracts: remainingQty }] }));
            }
          }
          return { ok: true };
        } catch (e) {
          return { ok: false, detail: e instanceof Error ? e.message : 'Network error' };
        }
      },
      syncFromBackend: async () => {
        try {
          const res = await fetch(`${_BASE_URL()}/api/portfolio`);
          if (!res.ok) return false;
          const remote: BackendPosition[] = await res.json();
          const remotePositions = remote.map(fromBackend);
          const remoteRecIds = new Set(remotePositions.map((p) => p.recId).filter(Boolean));
          const remoteContracts = new Set(remotePositions.map((p) => p.contract));
          // Keep any locally-held positions that haven't landed in the backend yet
          // (e.g. postPosition failed silently or is still in-flight). A local
          // position whose contract is already open remotely under a different
          // recId was rejected by the backend's 409 — drop it rather than render
          // a phantom clone of the remote row.
          const localOnly = usePortfolioStore.getState().positions.filter(
            (p) => p.recId && !remoteRecIds.has(p.recId) && !remoteContracts.has(p.contract)
          );
          // dedupePositions is a backstop: two local rows can share a contract if
          // both were refused by the backend and neither reached remoteContracts.
          set({ positions: dedupePositions([...remotePositions, ...localOnly]) });
          return true;
        } catch {
          // network unavailable — keep localStorage state
          return false;
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
