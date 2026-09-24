/*
 * Step 7 (Trade Card) UI state shared between the page's main column and its
 * @contextRail sidebar (a separate parallel-route component, so it can't read
 * the page's local state directly). Not persisted — purely ephemeral.
 *
 * `activeCard` is the card Step 7 is SHOWING: the Step-6 pick applied and, once
 * it has arrived, the recomputed plan merged in (`effectiveCard` on the page).
 * The rail's pre-trade checklist reads this and nothing else. It used to rebuild
 * its gates from the raw scan candidate, so after a Step-6 pick it graded the
 * AUTO-PICKED contract's IV, score, spread and R:R beside a card showing another
 * contract (A8, open_questions[64]). Publishing the one card, rather than having
 * the rail re-derive it, is deliberate: the recomputed plan lives only in the
 * page's local state, and two derivations of "the card" is how they drift.
 *
 * `rrPending` is true while the card's `rrRatio` still belongs to the auto-pick:
 * an overridden contract whose plan has not arrived, or failed.
 */

import { create } from 'zustand';
import type { TradeCardData } from '@/types/domain';

export interface PublishedTradeCard {
  card:      TradeCardData;
  rrPending: boolean;
}

interface TradeCardUiState {
  activeCard: PublishedTradeCard | null;
  setActiveCard: (active: PublishedTradeCard | null) => void;
}

export const useTradeCardUiStore = create<TradeCardUiState>()((set) => ({
  activeCard: null,
  setActiveCard: (activeCard) => set({ activeCard }),
}));
