/*
 * Watchlist store — Zustand with localStorage persistence.
 *
 * Single source of truth for which symbols the user is watching. On first run
 * we seed with MOCK_WATCHLIST symbols so the UI shows a populated list, but
 * after that the user is free to add or remove any symbol — base or not.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const WATCHLIST_STORAGE_KEY = 'bamendjou:watchlist';

const SEED_SYMBOLS = ['AAPL', 'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'AMD', 'TSLA', 'NFLX', 'INTC'];

interface WatchlistState {
  /** All watched symbols, uppercased. Seeded on first run. */
  added: string[];
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  isWatched:    (sym: string) => boolean;
}

export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set, get) => ({
      added: SEED_SYMBOLS,
      addSymbol: (sym) => {
        const s = sym.trim().toUpperCase();
        if (!s) return;
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
        return get().added.includes(s);
      },
    }),
    {
      name: WATCHLIST_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<WatchlistState> | null) ?? {};
        if (version < 1) {
          const prevAdded = Array.isArray(prev.added)
            ? prev.added.map((s) => String(s).toUpperCase())
            : [];
          const merged = Array.from(new Set([...SEED_SYMBOLS, ...prevAdded]));
          return { ...prev, added: merged } as WatchlistState;
        }
        return prev as WatchlistState;
      },
    }
  )
);
