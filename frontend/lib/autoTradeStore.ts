import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Direction } from '@/types/domain';

export type OptionsBroker = 'ibkr_paper' | 'tradier_paper' | 'tastytrade_paper';
export type AutoTradeMode = 'manual' | 'post_scan' | 'armed';

export interface AutoTradeState {
  selectedBroker:    OptionsBroker | null;
  autoMode:          AutoTradeMode;
  armed:             boolean;
  /** The direction the BACKEND reports for the armed trade, read back from
   *  /auto-trade/status -- not the local card's. Null when nothing is armed.
   *  Lives here rather than in AutoTradeArm's local state for the same reason
   *  `armed` does: it is server-owned armed-window state, and the two must not
   *  be able to disagree. */
  armedDirection:    Direction | null;
  lastOrderId:       string | null;
  setSelectedBroker: (b: OptionsBroker | null) => void;
  setAutoMode:       (m: AutoTradeMode) => void;
  /** The ONLY way to change `armed` / `armedDirection`. Standalone setters
   *  were removed rather than left beside this one: keeping them would have
   *  made the half-state merely discouraged instead of unconstructible, and
   *  three of the four original call sites set `armed` alone.
   *
   *  Apply a /auto-trade/status read ATOMICALLY. `armed` and `armedDirection`
   *  are one fact from one response: setting them through two separate actions
   *  publishes an intermediate state where the trade reads as armed with no
   *  direction (or vice versa), which is exactly the ambiguity this pair was
   *  added to remove. One `set`, one render, no half-state. */
  applyArmedStatus: (armed: boolean, d: Direction | null) => void;
  setLastOrderId:    (id: string | null) => void;
}

export function migrateAutoTrade(
  persistedState: unknown,
  _version: number,
): Partial<AutoTradeState> {
  const prev = (persistedState as Partial<AutoTradeState> | null) ?? {};
  return {
    ...prev,
    autoMode: prev.autoMode === 'post_scan' ? 'post_scan' : 'manual',
  };
}

export const useAutoTradeStore = create<AutoTradeState>()(
  persist(
    (set) => ({
      selectedBroker: null,
      autoMode:       'manual',
      armed:          false,
      armedDirection: null,
      lastOrderId:    null,
      setSelectedBroker: (b) => set({ selectedBroker: b }),
      setAutoMode:       (m) => set({ autoMode: m }),
      applyArmedStatus: (armed, d) => set({ armed, armedDirection: armed ? d : null }),
      setLastOrderId:    (id) => set({ lastOrderId: id }),
    }),
    {
      name: 'bamendjou-auto-trade',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 2,
      migrate: migrateAutoTrade,
      // Deliberate: `armed`, `armedDirection` and `lastOrderId` are NOT
      // persisted — auto-trade must never resume "armed" across a browser
      // restart (an armed order firing on the next scan after a reload would be
      // a surprise trade). The backend's /auto-trade/status endpoint is the
      // source of truth. `armedDirection` is excluded by the same partialize,
      // so NO version bump is needed for it: CLAUDE.md's bump-and-migrate rule
      // is about new PERSISTED fields, and a stale persisted direction is
      // exactly the surprise this exclusion exists to prevent.
      partialize: (s) => ({
        selectedBroker: s.selectedBroker,
        autoMode: s.autoMode === 'armed' ? 'manual' : s.autoMode,
      }),
    }
  )
);
