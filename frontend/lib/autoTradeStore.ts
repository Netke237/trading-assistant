import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type OptionsBroker = 'ibkr_paper' | 'tradier_paper' | 'tastytrade_paper';
export type AutoTradeMode = 'manual' | 'post_scan' | 'armed';

export interface AutoTradeState {
  selectedBroker:    OptionsBroker | null;
  autoMode:          AutoTradeMode;
  armed:             boolean;
  lastOrderId:       string | null;
  setSelectedBroker: (b: OptionsBroker | null) => void;
  setAutoMode:       (m: AutoTradeMode) => void;
  setArmed:          (a: boolean) => void;
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
      lastOrderId:    null,
      setSelectedBroker: (b) => set({ selectedBroker: b }),
      setAutoMode:       (m) => set({ autoMode: m }),
      setArmed:          (a) => set({ armed: a }),
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
      // Deliberate: `armed` and `lastOrderId` are NOT persisted — auto-trade
      // must never resume "armed" across a browser restart (an armed order
      // firing on the next scan after a reload would be a surprise trade).
      // The backend's /auto-trade/status endpoint is the source of truth.
      partialize: (s) => ({
        selectedBroker: s.selectedBroker,
        autoMode: s.autoMode === 'armed' ? 'manual' : s.autoMode,
      }),
    }
  )
);
