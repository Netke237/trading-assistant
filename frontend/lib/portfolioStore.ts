/*
 * Portfolio store — Zustand with localStorage persistence.
 *
 * Holds open positions. Step 7's "Send to broker" flow calls `addPosition`
 * to push new orders in — tagged as either `broker` or `manual` via `source`.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { PortfolioPosition, TargetLevel, Direction } from '@/types/domain';
import { useRiskStore } from '@/lib/riskStore';

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
  structuralStop?: number | null;
  targets: TargetLevel[];
  dteTotal: number | null;
  createdAt: string;
  // Live fields enriched by GET /portfolio via Tradier
  currentPrice?: number;
  currentStockPrice?: number | null;
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
    stop:         p.stop,
    structuralStop: p.structuralStop ?? null,
    targets:      p.targets ?? [],
    dteTotal:     p.dteTotal ?? 0,
    dteRemaining: p.dteRemaining ?? 0,
    status:       'PENDING',
    recId:        p.recId,
    currentPrice: p.currentPrice ?? 0,
    currentStockPrice: p.currentStockPrice ?? undefined,
    pnlDollar:    p.pnlDollar ?? 0,
    pnlPct:       p.pnlPct ?? 0,
    delta:        p.delta ?? undefined,
    theta:        p.theta ?? undefined,
    ivRank:       p.ivRank ?? undefined,
    syncStatus:   'synced',
    syncedAt:     Date.now(),
  };
}

interface PortfolioStoreState {
  positions: PortfolioPosition[];
  /** Last backend rejection of a save, for the UI to surface. Null when clean. */
  lastSyncError: { symbol: string; contract: string; detail: string; at: number } | null;
  clearSyncError: () => void;
  hydrate:        (positions: PortfolioPosition[]) => void;
  /** status: 'ok' saved; 'rejected' backend refused (dropped); 'pending' network
   *  error, kept locally and retried by syncFromBackend. `ok` === (status==='ok').
   *  `adjustedQty` is set when the backend's risk check auto-reduced the
   *  requested size to fit exposure limits — the position was still saved,
   *  just at a smaller quantity than requested; callers should surface this
   *  rather than silently showing the originally-requested size. */
  /** `opts.skipPost` skips this call's own internal POST — for a caller that
   *  already got a real, backend-confirmed successful response from its own
   *  `persistPosition` call and just needs local state to reflect that. Do
   *  NOT pass this based on `persistPosition`'s offline-optimistic fallback
   *  (see `persistPosition`'s `offline` field) — only on a genuine confirmed
   *  success, or a network hiccup would get marked `synced` despite never
   *  reaching the backend. */
  addPosition:    (p: PortfolioPosition, opts?: { skipPost?: boolean }) => Promise<{ ok: boolean; status: 'ok' | 'rejected' | 'pending'; detail?: string; adjustedQty?: number }>;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  closePosition:  (contract: string) => void;
  closePositionRemote: (
    recId: string,
    opts: { qtyToClose?: number | null; exitPrice?: number | null; exitDate?: string | null; sendToBroker?: boolean },
  ) => Promise<{ ok: boolean; detail?: string }>;
  /** Returns whether the pull actually reached the backend and updated state
   *  (false on network failure — callers that just mutated local state around
   *  this call may need to know so they don't assume the pull "saw" their change).
   *  force=true bypasses the concurrent-sync dedup by SERIALIZING a fresh run
   *  after any in-flight one — used by closePositionRemote, which needs a GET
   *  that post-dates its own write. */
  syncFromBackend: (force?: boolean) => Promise<boolean>;
  syncToBackend:  () => Promise<void>;
}

const _BASE_URL = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** The account value the backend risk check must measure exposure against —
 *  the user's configured value, identical to the Step-7 pre-check. Using the
 *  sum of deployed premiums here made a single option read as a huge fraction
 *  of the account and got otherwise-valid trades rejected (the ABT 422). */
function accountValue(): number {
  return useRiskStore.getState().limits.portfolioValue || 100_000;
}

function toBackendPayload(p: PortfolioPosition, portfolioValue = 100_000) {
  return {
    recId:          p.recId,
    symbol:         p.symbol,
    contract:       p.contract,
    direction:      p.direction,
    entryPrice:     p.entryPrice,
    qty:            p.contracts ?? 1,
    entryDate:      p.entryDate ?? new Date().toISOString().slice(0, 10),
    stop:           p.stop != null && p.stop > 0 ? p.stop : null,
    structuralStop: p.structuralStop != null && p.structuralStop > 0 ? p.structuralStop : null,
    targets:        p.targets ?? [],
    dteTotal:       p.dteTotal ?? null,
    portfolioValue,
    scanStockPrice: p.scanStockPrice ?? null,
    tradeCardSnapshot: p.tradeCardSnapshot ?? null,
  };
}

type SaveOutcome =
  | { kind: 'ok'; adjustedQty?: number }
  | { kind: 'rejected'; detail: string }   // backend 4xx (except 409) — do not keep the row
  | { kind: 'duplicate' }                  // 409 — backend already has this contract
  | { kind: 'network' };                   // unreachable — keep the row pending

async function postPosition(p: PortfolioPosition, portfolioValue = accountValue()): Promise<SaveOutcome> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      return typeof adjustedQty === 'number' ? { kind: 'ok', adjustedQty } : { kind: 'ok' };
    }
    if (res.status === 409) return { kind: 'duplicate' };
    const body = await res.json().catch(() => ({}));
    return { kind: 'rejected', detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    return { kind: 'network' };
  }
}

/** POST to the backend and return whether it was accepted.
 *  Used by the single-order buttons in Step 7 so rejections (risk check, duplicate
 *  contract) surface to the user instead of being silently dropped.
 *
 *  A 409 is *not* success: the backend keeps one open position per contract and
 *  has no scale-in path, so it recorded nothing. Reporting it as ok would let the
 *  caller add quantity that only ever existed in local state.
 *
 *  On a network failure, `ok` is `false` and `offline` is `true` — this is
 *  DELIBERATELY distinguishable from a genuine rejection. A caller must not
 *  treat `offline: true` the same as `ok: true` (nothing was actually
 *  persisted) nor the same as a hard rejection (the position may well be
 *  valid — the backend just couldn't be reached to confirm it). The correct
 *  handling is to fall back to `addPosition`'s own POST + pending/retry path,
 *  exactly as every other call site (without a `persistPosition` step) does. */
export async function persistPosition(
  p: PortfolioPosition,
  portfolioValue = accountValue(),
): Promise<{ ok: boolean; offline?: boolean; detail?: string; adjustedQty?: number }> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      return typeof adjustedQty === 'number' ? { ok: true, adjustedQty } : { ok: true };
    }
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    // Backend unreachable. Do NOT report ok:true here — nothing was actually
    // persisted, and a caller that skips its own retry path on ok:true would
    // silently lose this position on the next reconcile (see the `offline`
    // doc comment above).
    return { ok: false, offline: true };
  }
}

export type PersistPositionResult = Awaited<ReturnType<typeof persistPosition>>;

/**
 * The three-way outcome every `persistPosition` call site must branch on — extracted here
 * (rather than left inline at each call site) so the real production branching logic can be
 * unit-tested directly, instead of only via a hand-reimplemented copy in a test file:
 *  - offline (network failure): `persistPosition` did NOT confirm anything was saved. Fall
 *    through to `addPosition`'s own POST + pending/retry path, same as every call site that
 *    never calls `persistPosition` at all.
 *  - rejected (backend responded, said no): surface the error, do not add the position.
 *  - confirmed success: skip `addPosition`'s own POST (already persisted) but still sync local
 *    state via `addPosition(pos, { skipPost: true })`.
 * Returns `{ rejected: true }` when the caller should show `saved.detail` and stop, mirroring
 * the `if (!saved.ok) { setOrderError(...); return; }` shape each call site used inline before.
 */
export function applyPersistedPosition(
  saved: PersistPositionResult,
  pos: PortfolioPosition,
  addPosition: (p: PortfolioPosition, opts?: { skipPost?: boolean }) => unknown,
  onAdjusted?: (adjustedQty: number) => void,
): { rejected: boolean; detail?: string } {
  if (saved.offline) {
    void addPosition(pos);
    return { rejected: false };
  }
  if (!saved.ok) {
    return { rejected: true, detail: saved.detail };
  }
  if (saved.adjustedQty != null) onAdjusted?.(saved.adjustedQty);
  void addPosition(pos, { skipPost: true });
  return { rejected: false };
}

async function deletePosition(recId: string): Promise<void> {
  try {
    await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, { method: 'DELETE' });
  } catch { /* network unavailable */ }
}

/** Whitelists the drawer's persistable fields out of an `updatePosition` patch.
 *  `currentPrice`/`pnlDollar`/`pnlPct` are deliberately excluded — they're
 *  live-computed by the backend from a broker quote on every GET, so a manual
 *  override here would just be overwritten by the next sync anyway.
 *
 *  `contracts` (-> `qty`) always carries `portfolioValue` alongside it — the
 *  backend re-runs the exposure gate when a PATCH increases qty (same gate
 *  POST /api/portfolio enforces at creation) and requires it for that check,
 *  the same way the store's own `postPosition` already does for a new order. */
function toUpdatePayload(patch: Partial<PortfolioPosition>): Record<string, unknown> | null {
  const body: Record<string, unknown> = {};
  if ('stop' in patch) body.stop = patch.stop;
  if ('structuralStop' in patch) body.structuralStop = patch.structuralStop;
  if ('targets' in patch) body.targets = patch.targets;
  if ('contracts' in patch) {
    body.qty = patch.contracts;
    body.portfolioValue = accountValue();
  }
  return Object.keys(body).length > 0 ? body : null;
}

async function patchPosition(
  recId: string,
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; detail?: string; adjustedQty?: number }> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio/${recId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const body = await res.json().catch(() => ({}));
      const adjustedQty = (body as { adjustedQty?: number }).adjustedQty;
      return typeof adjustedQty === 'number' ? { ok: true, adjustedQty } : { ok: true };
    }
    const body = await res.json().catch(() => ({}));
    return { ok: false, detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    return { ok: false, detail: 'Could not reach the backend — edit was not saved.' };
  }
}

const REMOTE_PATCH_DEBOUNCE_MS = 600;

type PendingPatch = {
  timer: ReturnType<typeof setTimeout>;
  payload: Record<string, unknown>;
  symbol: string;
  contract: string;
};

// Debounces `updatePosition` edits per recId so rapid keystrokes in the drawer
// coalesce into one PATCH instead of one per keystroke. Module-level (not store
// state) — timers are not serializable Zustand state, and this is purely
// network-scheduling plumbing, not UI state.
const _pendingPatches = new Map<string, PendingPatch>();

// Tracks the in-flight PATCH request for a recId, from the moment it leaves
// `_pendingPatches` (debounce fired) until its response settles. Two jobs:
//  1. A second edit arriving mid-flight awaits this promise before sending its
//     own PATCH, so responses can never resolve out of order and silently let
//     an older edit overwrite a newer one.
//  2. `syncFromBackend`'s poll guard checks this alongside `_pendingPatches` —
//     without it, the poll's stale-value protection ends the instant the
//     debounce timer fires, not once the request actually completes.
const _inFlightPatches = new Map<string, Promise<void>>();

async function _flushOne(recId: string): Promise<void> {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  _pendingPatches.delete(recId);

  const previous = _inFlightPatches.get(recId);

  const run = async (): Promise<void> => {
    if (previous) await previous.catch(() => {});
    const result = await patchPosition(recId, entry.payload);
    if (!result.ok) {
      usePortfolioStore.setState({
        lastSyncError: {
          symbol: entry.symbol,
          contract: entry.contract,
          detail: result.detail ?? 'Edit could not be saved',
          at: Date.now(),
        },
      });
      // The optimistic update `updatePosition` already applied locally was
      // never true — the backend rejected it (e.g. the exposure gate on a qty
      // increase). Force a resync so the drawer/table snap back to whatever
      // the backend actually holds, rather than keeping the rejected value
      // on screen until the next 30s poll happens to run.
      void usePortfolioStore.getState().syncFromBackend(true);
      return;
    }
    if (result.adjustedQty != null) {
      // The backend's exposure gate approved the qty increase at a SMALLER size
      // than requested (mirrors addPosition's own adjustedQty handling above).
      // Correct the local value immediately rather than leaving the drawer show
      // the requested size until the next 30s sync poll silently snaps it back
      // with no explanation — same failure mode Step 4 below prevents for an
      // in-flight edit, but this is a resolved edit the poll would otherwise
      // still be free to overwrite without warning.
      usePortfolioStore.setState((s) => ({
        positions: s.positions.map((p) =>
          p.recId === recId ? { ...p, contracts: result.adjustedQty } : p
        ),
        lastSyncError: {
          symbol: entry.symbol,
          contract: entry.contract,
          detail: `Size reduced to ${result.adjustedQty} contracts to fit your exposure limit.`,
          at: Date.now(),
        },
      }));
    }
  };

  const promise = run().finally(() => {
    if (_inFlightPatches.get(recId) === promise) _inFlightPatches.delete(recId);
  });
  _inFlightPatches.set(recId, promise);
  return promise;
}

function scheduleRemotePositionPatch(
  recId: string,
  symbol: string,
  contract: string,
  payload: Record<string, unknown>,
): void {
  const existing = _pendingPatches.get(recId);
  if (existing) clearTimeout(existing.timer);
  const merged = { ...(existing?.payload ?? {}), ...payload };
  const timer = setTimeout(() => { void _flushOne(recId); }, REMOTE_PATCH_DEBOUNCE_MS);
  _pendingPatches.set(recId, { timer, payload: merged, symbol, contract });
}

/** Sends a pending debounced edit immediately instead of waiting out the
 *  debounce window — called when the drawer closes (or switches to editing a
 *  different row) so a fast edit-then-navigate is never silently dropped.
 *  With no `recId`, flushes every pending edit. */
export function flushPendingPositionPatches(recId?: string): void {
  const ids = recId ? [recId] : Array.from(_pendingPatches.keys());
  for (const id of ids) {
    const entry = _pendingPatches.get(id);
    if (!entry) continue;
    clearTimeout(entry.timer);
    void _flushOne(id);
  }
}

/** Drops a pending debounced edit without sending it — used when the position
 *  is being deleted (closePosition/closePositionRemote), so a stale PATCH
 *  never races a DELETE for the same recId. */
function cancelPendingPositionPatch(recId: string): void {
  const entry = _pendingPatches.get(recId);
  if (!entry) return;
  clearTimeout(entry.timer);
  _pendingPatches.delete(recId);
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

/** Persist migration. Legacy rows (persisted before sync tracking existed) have
 *  no syncStatus. Tag them synced with syncedAt=0 so the authoritative reconcile
 *  drops them if the backend does not have them (clears old phantom rows), while
 *  a row the backend DOES have is simply confirmed on the next sync. */
export function migratePortfolioPersist(state: unknown, _version: number): unknown {
  const s = state as { positions?: unknown } | undefined;
  if (!s || !Array.isArray(s.positions)) return state;
  return {
    ...s,
    positions: s.positions.map((p) => {
      const po = p as Record<string, unknown>;
      return po.syncStatus
        ? po
        : { ...po, syncStatus: 'synced', syncedAt: 0 };
    }),
  };
}

// Dedupes concurrent closePositionRemote calls for the same recId — without
// this, a double-click or slow-network retry can send two overlapping close
// requests; the second one's 404-drift-recovery branch can then re-persist
// the position the first call just closed.
const _inFlightCloses = new Map<string, Promise<{ ok: boolean; detail?: string }>>();

// Dedupes overlapping syncFromBackend calls. The reconcile now awaits POST
// retries for pending rows, so two concurrent syncs (portfolio + dashboard 30s
// intervals, or two tabs) could each read the same snapshot and clobber each
// other's final write. A single shared in-flight promise serializes them.
let _syncInFlight: Promise<boolean> | null = null;

export const usePortfolioStore = create<PortfolioStoreState>()(
  persist(
    (set) => ({
      positions: [],
      lastSyncError: null,
      clearSyncError: () => set({ lastSyncError: null }),
      hydrate: (positions) =>
        set({
          positions: positions.map((p) =>
            (p as PortfolioPosition).recId ? p : { ...p, recId: generateRecId() }
          ),
        }),
      addPosition: async (p, opts) => {
        const recId = (p as PortfolioPosition & { recId?: string }).recId || generateRecId();
        const value = accountValue();

        // Capture — inside the optimistic set — which row to promote on success
        // and exactly how to undo the mutation on a hard rejection:
        //  - insert  → remove the new row (identified by recId)
        //  - replace → restore the prior row that shared this recId
        //  - merge   → restore the prior same-contract row (undoes the count bump)
        // Capturing closures here avoids reading a nested-reassigned flag in the
        // outer scope (which TS narrows to its initializer).
        let promoteRecId = recId;
        let didMerge = false;
        let rollback: (positions: PortfolioPosition[]) => PortfolioPosition[] =
          (positions) => positions.filter((x) => x.recId !== recId);

        set((s) => {
          const incoming: PortfolioPosition = {
            ...p, recId, syncStatus: 'pending', syncPendingSince: Date.now(),
          };

          const idxByRecId = s.positions.findIndex((x) => x.recId === recId);
          if (idxByRecId >= 0) {
            const prev = s.positions[idxByRecId]!;
            promoteRecId = recId;
            rollback = (positions) => positions.map((x) => (x.recId === prev.recId ? prev : x));
            const next = [...s.positions];
            next[idxByRecId] = { ...prev, ...incoming };
            return { positions: next };
          }
          const idxByKey = s.positions.findIndex(
            (x) => x.symbol === incoming.symbol && x.contract === incoming.contract,
          );
          if (idxByKey >= 0) {
            // eslint-disable-next-line no-console
            console.warn('[portfolioStore] merging duplicate position for', incoming.symbol, incoming.contract);
            const prev = s.positions[idxByKey]!;
            promoteRecId = prev.recId;
            didMerge = true;
            rollback = (positions) => positions.map((x) => (x.recId === prev.recId ? prev : x));
            const next = [...s.positions];
            next[idxByKey] = { ...prev, contracts: (prev.contracts ?? 0) + (incoming.contracts ?? 0) };
            return { positions: next };
          }
          promoteRecId = recId;
          rollback = (positions) => positions.filter((x) => x.recId !== recId);
          return { positions: [...s.positions, incoming] };
        });

        if (opts?.skipPost) {
          // Caller already got a genuine, backend-confirmed successful response
          // from its own persistPosition call (never the offline-optimistic
          // fallback — see persistPosition's `offline` field) — just promote
          // the optimistic row to synced without a second POST.
          set((s) => ({
            positions: s.positions.map((x) =>
              x.recId === promoteRecId
                ? { ...x, syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined }
                : x
            ),
          }));
          return { ok: true, status: 'ok' as const };
        }

        const outcome = await postPosition({ ...p, recId } as PortfolioPosition, value);

        // A 409 on a MERGE means the backend refused a scale-in (it keeps one open
        // position per contract — no add-to-existing). Don't report the local qty
        // bump as saved: roll it back and surface it, so the UI never shows a
        // quantity the backend rejected (which the next sync would silently revert).
        const scaleInRefused = outcome.kind === 'duplicate' && didMerge;

        if ((outcome.kind === 'ok' || outcome.kind === 'duplicate') && !scaleInRefused) {
          const adjustedQty = outcome.kind === 'ok' ? outcome.adjustedQty : undefined;
          set((s) => ({
            positions: s.positions.map((x) =>
              x.recId === promoteRecId
                ? {
                    ...x,
                    syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined,
                    // The backend's risk check auto-reduced the size to fit exposure
                    // limits — reflect the persisted quantity locally, don't keep
                    // showing what was requested. Skipped on a MERGE: the POST only
                    // ever sends the incoming increment (not the locally-summed
                    // total), so adjustedQty there describes that increment alone —
                    // overwriting the already-merged `contracts` with it would be
                    // wrong, not just imprecise. The caller is still told via the
                    // returned adjustedQty below; only the merged local total is left
                    // untouched, same as before this fix, to be corrected by the next
                    // authoritative sync.
                    ...(adjustedQty != null && !didMerge ? { contracts: adjustedQty } : {}),
                  }
                : x,
            ),
          }));
          return { ok: true, status: 'ok' as const, adjustedQty };
        }
        if (outcome.kind === 'rejected' || scaleInRefused) {
          const detail = outcome.kind === 'rejected'
            ? outcome.detail
            : 'A position for this contract is already open — scale-in is not supported.';
          set((s) => ({
            positions: rollback(s.positions),
            lastSyncError: { symbol: p.symbol, contract: p.contract, detail, at: Date.now() },
          }));
          return { ok: false, status: 'rejected' as const, detail };
        }
        // network — leave the row pending; the reconcile retries it. Never silently dropped.
        return { ok: false, status: 'pending' as const, detail: 'queued — will retry when the backend is reachable' };
      },
      updatePosition: (contract, patch) => {
        // Capture the pre-patch row during the set() updater (the same closure
        // pattern closePosition below already uses), but fire the network side
        // effect AFTER set() returns rather than from inside the updater —
        // every other action in this file (closePosition, addPosition) does
        // its network call after the state update, not inside it.
        let target: PortfolioPosition | undefined;
        set((s) => {
          target = s.positions.find((r) => r.contract === contract);
          return {
            positions: s.positions.map((r) =>
              r.contract === contract ? { ...r, ...patch } : r
            ),
          };
        });
        if (target) {
          const payload = toUpdatePayload(patch);
          if (payload) scheduleRemotePositionPatch(target.recId, target.symbol, target.contract, payload);
        }
      },
      closePosition: (contract) => {
        let closedRecId: string | undefined;
        set((s) => {
          closedRecId = s.positions.find((r) => r.contract === contract)?.recId;
          return { positions: s.positions.filter((r) => r.contract !== contract) };
        });
        if (closedRecId) {
          cancelPendingPositionPatch(closedRecId);
          deletePosition(closedRecId);
        }
      },
      closePositionRemote: async (recId, opts) => {
        const existing = _inFlightCloses.get(recId);
        if (existing) return existing;

        const run = async (): Promise<{ ok: boolean; detail?: string }> => {
          cancelPendingPositionPatch(recId);
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
            // Force a fresh GET that post-dates this close — must not be satisfied
            // by an in-flight sync whose GET predates it (would resurrect the row).
            const synced = await usePortfolioStore.getState().syncFromBackend(true);
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
        };

        const promise = run().finally(() => _inFlightCloses.delete(recId));
        _inFlightCloses.set(recId, promise);
        return promise;
      },
      syncFromBackend: async (force = false) => {
        const run = async (): Promise<boolean> => {
          const fetchStartedAt = Date.now();
          try {
            const res = await fetch(`${_BASE_URL()}/api/portfolio`);
            if (!res.ok) return false;
            const remote: BackendPosition[] = await res.json();
            const localForPending = usePortfolioStore.getState().positions;
            const remotePositions = remote.map(fromBackend).map((rp) => {
              if (!_pendingPatches.has(rp.recId) && !_inFlightPatches.has(rp.recId)) return rp;
              // An edit for this row is debounced, or its PATCH is still in
              // flight, and hasn't been confirmed by the backend yet — keep
              // the local value instead of snapping a focused input back to
              // what the server still has.
              return localForPending.find((p) => p.recId === rp.recId) ?? rp;
            });
            const remoteContracts = new Set(remotePositions.map((p) => p.contract));

            const snapshot = usePortfolioStore.getState().positions;
            const snapshotRecIds = new Set(snapshot.map((p) => p.recId));
            const localAbsent = snapshot.filter(
              (p) => p.recId && !remoteContracts.has(p.contract),
            );

            const keep: PortfolioPosition[] = [];
            for (const p of localAbsent) {
              if (p.syncStatus === 'pending') {
                // Retry the save. Never silently drop a pending row: on success
                // promote it, on a hard rejection surface it, on network keep it.
                const outcome = await postPosition(p, accountValue());
                if (outcome.kind === 'ok' || outcome.kind === 'duplicate') {
                  keep.push({ ...p, syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined });
                } else if (outcome.kind === 'rejected') {
                  set({ lastSyncError: { symbol: p.symbol, contract: p.contract, detail: outcome.detail, at: Date.now() } });
                  // dropped — do not push
                } else {
                  keep.push(p); // network — stays pending, retried next cycle
                }
              } else if (typeof p.syncedAt === 'number' && p.syncedAt >= fetchStartedAt) {
                // Confirmed after this GET's snapshot could have been taken — keep
                // (the GET simply predates it); avoids the 30s-poll race dropping it.
                keep.push(p);
              } else {
                // A synced row confirmed before this snapshot but absent from the
                // backend is a genuine phantom (e.g. legacy row, DB reset) — drop it,
                // and cancel any edit still debounced for it so a stale PATCH doesn't
                // fire against a rec_id we just forgot.
                cancelPendingPositionPatch(p.recId);
              }
            }

            // Preserve any row inserted into the store DURING the awaited retry
            // loop above so a concurrent addPosition is not clobbered by our final
            // write. Key on recId (NOT contract): a legitimate re-add of a contract
            // that was a phantom in this run's snapshot has a NEW recId, so it must
            // survive even though its contract was in the snapshot.
            const accountedRecIds = new Set([...remotePositions, ...keep].map((x) => x.recId));
            set((s) => {
              const addedDuringSync = s.positions.filter(
                (x) => x.recId && !snapshotRecIds.has(x.recId) && !accountedRecIds.has(x.recId),
              );
              return { positions: dedupePositions([...remotePositions, ...keep, ...addedDuringSync]) };
            });
            return true;
          } catch {
            // network unavailable — keep localStorage state untouched
            return false;
          }
        };

        // Concurrent-sync dedup. A non-forced caller (the 30s interval pollers)
        // shares any in-flight run. A forced caller (closePositionRemote, which
        // must observe a GET that post-dates its own write) SERIALIZES a fresh
        // run after the in-flight one rather than reusing its stale result.
        // NOTE: `_syncInFlight` must hold the SAME promise the finally callback
        // compares against, so attach `.finally` as a side-effect and store/return
        // the original promise — do not store the value `.finally()` returns.
        if (_syncInFlight && !force) return _syncInFlight;

        const started: Promise<boolean> = _syncInFlight
          ? _syncInFlight.catch(() => false).then(() => run()) // forced: chain after in-flight
          : run();
        _syncInFlight = started;
        started.finally(() => { if (_syncInFlight === started) _syncInFlight = null; });
        return started;
      },
      syncToBackend: async () => {
        // Push all local positions to the backend (409 = already there, safe to ignore).
        const { positions } = usePortfolioStore.getState();
        const value = accountValue();
        await Promise.all(positions.map((p) => postPosition(p, value)));
      },
    }),
    {
      name: 'bamendjou-portfolio-v1',
      version: 2,
      skipHydration: true,
      migrate: migratePortfolioPersist,
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
