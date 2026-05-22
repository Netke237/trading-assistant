/*
 * Watchlist store — Zustand with localStorage persistence.
 *
 * Single source of truth for which symbols the user is watching.
 * The user is free to add or remove any symbol — base or not.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const WATCHLIST_STORAGE_KEY = 'bamendjou-watchlist-v1';

const SEED_SYMBOLS: string[] = [];

interface WatchlistState {
  /** All watched symbols, uppercased. Empty by default. */
  added: string[];
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  isWatched:    (sym: string) => boolean;
  syncFromBackend: () => Promise<void>;
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
      syncFromBackend: async () => {
        try {
          const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
          const res = await fetch(`${BASE_URL}/api/watchlist`);
          if (!res.ok) return;
          const symbols: string[] = await res.json();
          if (symbols.length === 0) return; // don't overwrite localStorage when backend has no data
          set({ added: symbols.map((s) => s.toUpperCase()) });
        } catch {
          // network unavailable — keep localStorage state
        }
      },
    }),
    {
      name: WATCHLIST_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ added: state.added }),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<WatchlistState> | null) ?? {};
        if (version < 1) {
          const prevAdded = Array.isArray(prev.added)
            ? prev.added.map((s) => String(s).toUpperCase())
            : [];
          return { ...prev, added: prevAdded } as WatchlistState;
        }
        return prev as WatchlistState;
      },
    }
  )
);
