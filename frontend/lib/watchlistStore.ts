/*
 * Watchlist store — Zustand with localStorage persistence.
 *
 * Tracks user-added symbols on top of MOCK_WATCHLIST. Anywhere in the app
 * we can call `addSymbol(sym)` / `removeSymbol(sym)` / read `isWatched(sym)`.
 *
 * v1 stores just the symbol. Enrichment (company name, score, etc.) stays
 * with MOCK_WATCHLIST until there's a backend.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';

export const WATCHLIST_STORAGE_KEY = 'bamendjou:watchlist';

interface WatchlistState {
  /** User-added symbols, uppercased. */
  added: string[];
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  /** True for both the bundled mock list and user-added symbols. */
  isWatched:    (sym: string) => boolean;
}

const BASE_SYMBOLS = new Set(MOCK_WATCHLIST.map((r) => r.symbol.toUpperCase()));

export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set, get) => ({
      added: [],
      addSymbol: (sym) => {
        const s = sym.trim().toUpperCase();
        if (!s) return;
        if (BASE_SYMBOLS.has(s)) return;
        const list = get().added;
        if (list.includes(s)) return;
        set({ added: [...list, s] });
      },
      removeSymbol: (sym) => {
        const s = sym.trim().toUpperCase();
        set({ added: get().added.filter((x) => x !== s) });
      },
      isWatched: (sym) => {
        const s = sym.trim().toUpperCase();
        return BASE_SYMBOLS.has(s) || get().added.includes(s);
      },
    }),
    {
      name: WATCHLIST_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
    }
  )
);
