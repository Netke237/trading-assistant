/*
 * Portfolio page UI state shared between the page's main column and its
 * @contextRail sidebar (a separate parallel-route component, so it can't
 * read the page's local `editing` state directly). Not persisted — purely
 * ephemeral "what's currently selected" state for this one page.
 */

import { create } from 'zustand';

interface PortfolioUiState {
  selectedSymbol: string | null;
  setSelectedSymbol: (symbol: string | null) => void;
}

export const usePortfolioUiStore = create<PortfolioUiState>()((set) => ({
  selectedSymbol: null,
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
}));
