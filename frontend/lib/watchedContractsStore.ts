/*
 * Watched-contracts store — Zustand with localStorage persistence + backend sync.
 *
 * Separate from watchlistStore on purpose: starring a stock and starring a
 * specific option contract are different intents. This store holds the
 * canonical contract id and, per id, the grading Step 6 used when it was
 * starred (WATCHLIST-SCAN-CONTRACT-RULES), so the Watchlist grades it as the
 * scan did. An id with no grading is graded on contract_rules.yaml.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { api } from '@/lib/api';
import type { ContractGrading } from '@/types/domain';
import { isValidGrading, stableStringify } from '@/lib/contractGrading';

export const WATCHED_CONTRACTS_STORAGE_KEY = 'bamendjou-watched-contracts-v1';

interface WatchedContractsState {
  /** Canonical contract ids, e.g. "AAPL|190|2026-05-15|C". */
  ids: string[];
  /** The grading each id was starred with. No key = none (YAML-graded). */
  grading: Record<string, ContractGrading>;
  /** Adds the id (if absent) and records `grading` when given, INCLUDING when
   *  the id is already present (a rollback restoring a grading). */
  add:               (id: string, grading?: ContractGrading) => void;
  remove:            (id: string) => void;
  /** Drops only the id's grading (the 422-retry path: the star stays, YAML-graded). */
  clearGrading:      (id: string) => void;
  isWatched:         (id: string) => boolean;
  syncFromBackend:   () => Promise<void>;
}

type Persisted = Pick<WatchedContractsState, 'ids' | 'grading'>;

function isId(x: unknown): x is string {
  return typeof x === 'string' && x !== '';
}

/** Repairs a stored blob: ids kept only as non-empty strings, grading only as
 *  a plain object. Shared by migrate and merge, since persist() calls migrate
 *  only when the stored version differs and a hand-edited v3 blob skips it. */
export function sanitizePersisted(persisted: unknown): Persisted {
  const p = (persisted ?? {}) as { ids?: unknown; grading?: unknown };
  const ids = Array.isArray(p.ids) ? p.ids.filter(isId) : [];
  const g = p.grading;
  const rawGrading = g && typeof g === 'object' && !Array.isArray(g) ? (g as Record<string, unknown>) : {};
  const idSet = new Set(ids);
  const grading: Record<string, ContractGrading> = {};
  for (const [k, v] of Object.entries(rawGrading)) {
    if (idSet.has(k) && isValidGrading(v)) {
      grading[k] = v;
    }
  }
  return { ids, grading };
}

export function migrateWatchedContracts(persisted: unknown, version: number): Persisted {
  const { ids, grading } = sanitizePersisted(persisted);
  // v1/v2 → v3: ids unchanged; stars made before gradings existed have none.
  return { ids, grading: version < 3 ? {} : grading };
}

function withoutKey<T>(rec: Record<string, T>, key: string): Record<string, T> {
  if (!(key in rec)) return rec;
  const next = { ...rec };
  delete next[key];
  return next;
}

function sameIds(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

function sameGrading(a: Record<string, ContractGrading>, b: Record<string, ContractGrading>): boolean {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => k in b && stableStringify(a[k]) === stableStringify(b[k]));
}

export const useWatchedContractsStore = create<WatchedContractsState>()(
  persist(
    (set, get) => ({
      ids: [],
      grading: {},
      add: (id, grading) => {
        if (!id) return;
        const { ids, grading: map } = get();
        const nextIds = ids.includes(id) ? ids : [...ids, id];
        const nextMap = grading !== undefined ? { ...map, [id]: grading } : map;
        if (nextIds === ids && nextMap === map) return;
        set({ ids: nextIds, grading: nextMap });
      },
      remove: (id) => {
        set({ ids: get().ids.filter((x) => x !== id), grading: withoutKey(get().grading, id) });
      },
      clearGrading: (id) => {
        const map = get().grading;
        const next = withoutKey(map, id);
        if (next !== map) set({ grading: next });
      },
      isWatched: (id) => get().ids.includes(id),
      syncFromBackend: async () => {
        let ids: string[];
        let grading: Record<string, ContractGrading>;
        try {
          const rows = await api.getWatchedContractsDetail();
          if (!Array.isArray(rows)) throw new Error('bad /detail');
          ids = rows.map((r) => r?.contract_id).filter(isId);
          grading = {};
          for (const r of rows) {
            if (r?.contract_id && r.grading != null) grading[r.contract_id] = r.grading;
          }
        } catch {
          // Older backend or a failed /detail: ids only, and the local grading
          // of every id that is still present survives.
          try {
            const raw = await api.getWatchedContracts();
            if (!Array.isArray(raw)) return;
            ids = (raw as unknown[]).filter(isId);
          } catch {
            return;  // both failed: keep state
          }
          const local = get().grading;
          grading = {};
          for (const id of ids) if (id in local) grading[id] = local[id]!;
        }
        const cur = get();
        // A no-op sync must not set: the Watchlist refetches on a new reference.
        if (sameIds(cur.ids, ids) && sameGrading(cur.grading, grading)) return;
        set({ ids, grading });
      },
    }),
    {
      name: WATCHED_CONTRACTS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (state) => ({ ids: state.ids, grading: state.grading }),
      version: 3,
      migrate: (persisted, version) => migrateWatchedContracts(persisted, version) as unknown as WatchedContractsState,
      // Nothing stored (persisted undefined) leaves the current state alone.
      merge: (persisted, current) =>
        persisted && typeof persisted === 'object' ? { ...current, ...sanitizePersisted(persisted) } : current,
    }
  )
);
