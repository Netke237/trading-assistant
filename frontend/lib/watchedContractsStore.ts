/*
 * Watched-contracts store — Zustand with localStorage persistence + backend sync.
 *
 * Separate from watchlistStore on purpose: starring a stock and starring a
 * specific option contract are different intents. This store holds just the
 * canonical contract id; the backend resolves the id back into a row.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { api } from '@/lib/api';

export const WATCHED_CONTRACTS_STORAGE_KEY = 'bamendjou-watched-contracts-v1';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface WatchedContractsState {
  /** Canonical contract ids, e.g. "AAPL|190|2026-05-15|C". */
  ids: string[];
  add:               (id: string) => void;
  remove:            (id: string) => void;
  toggle:            (id: string) => void;
  isWatched:         (id: string) => boolean;
  syncFromBackend:   () => Promise<void>;
}

export const useWatchedContractsStore = create<WatchedContractsState>()(
  persist(
    (set, get) => ({
      ids: [],
      add: (id) => {
        if (!id) return;
        const list = get().ids;
        if (list.includes(id)) return;
        set({ ids: [...list, id] });
      },
      remove: (id) => {
        set({ ids: get().ids.filter((x) => x !== id) });
      },
      toggle: (id) => {
        const list = get().ids;
        if (list.includes(id)) set({ ids: list.filter((x) => x !== id) });
        else                   set({ ids: [...list, id] });
      },
      isWatched: (id) => get().ids.includes(id),
      syncFromBackend: async () => {
        try {
          const res = await fetch(`${BASE_URL}/api/watched-contracts`);
          if (!res.ok) return;
          const ids: string[] = await res.json();
          if (!Array.isArray(ids)) return;
          set({ ids: ids.filter(Boolean) });
        } catch {}
      },
    }),
    {
      name: WATCHED_CONTRACTS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (state) => ({ ids: state.ids }),
      version: 2,
      migrate: (persisted, version) => {
        if (version < 2) {
          // v1 → v2: no shape change; just keep existing ids intact
          return persisted as WatchedContractsState;
        }
        return persisted as WatchedContractsState;
      },
    }
  )
);
