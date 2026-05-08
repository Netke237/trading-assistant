/*
 * Watched-contracts store — Zustand with localStorage persistence.
 *
 * Separate from watchlistStore on purpose: starring a stock and starring a
 * specific option contract are different intents. This store holds just the
 * canonical contract id; the backend resolves the id back into a row.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const WATCHED_CONTRACTS_STORAGE_KEY = 'bamendjou-watched-contracts-v1';

interface WatchedContractsState {
  /** Canonical contract ids, e.g. "AAPL|190|2026-05-15|C". */
  ids: string[];
  add:        (id: string) => void;
  remove:     (id: string) => void;
  toggle:     (id: string) => void;
  isWatched:  (id: string) => boolean;
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
    }),
    {
      name: WATCHED_CONTRACTS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ ids: state.ids }),
      version: 1,
    }
  )
);
