/*
 * Watchlist page UI state shared between the page's main column and its
 * @contextRail sidebar (a separate parallel-route component, so it can't
 * read the page's local `selected` state directly). Not persisted — purely
 * ephemeral "which row is currently selected" state for this one page.
 *
 * Deliberately its own store rather than reusing chartStore's `symbol`:
 * chartStore defaults to 'AAPL' and is persisted to localStorage, so it
 * never actually represents "nothing selected" — it would leave the rail
 * showing a stale or default symbol's note on a fresh page load where no
 * row has been clicked. Mirrors portfolioUiStore's selectedSymbol pattern.
 */

import { create } from 'zustand';

interface WatchlistUiState {
  selectedSymbol: string | null;
  setSelectedSymbol: (symbol: string | null) => void;
}

export const useWatchlistUiStore = create<WatchlistUiState>()((set) => ({
  selectedSymbol: null,
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
}));
