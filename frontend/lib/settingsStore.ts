/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists the Custom tab's score weights (customW) and indicator
 * parameters (customParams) across page refreshes. All other settings
 * tabs (Broker, Appearance, Alerts) use local component state and are
 * NOT persisted here.
 *
 * Default values mirror the Swing preset so Custom starts populated.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const SETTINGS_STORAGE_KEY = 'bamendjou-settings';

export type WeightKey = 'Trend' | 'Pullback' | 'Trigger' | 'Event' | 'Volatility';
export type CustomWeights = Record<WeightKey, number>;
export type CustomParams  = Record<WeightKey, Record<string, number>>;

// Default weights — mirror WEIGHT_DEFAULTS in settings/page.tsx
const DEFAULT_WEIGHTS: CustomWeights = {
  Trend:      25,
  Pullback:   20,
  Trigger:    20,
  Event:      15,
  Volatility: 20,
};

// Default params — mirror initCustomParams() output (Swing preset values)
const DEFAULT_PARAMS: CustomParams = {
  Trend:      { longMa: 200, medMa: 50, adxPeriod: 14 },
  Pullback:   { shortMa: 20, rsiPeriod: 14 },
  Trigger:    { volLookback: 20, volMultiplier: 1.5 },
  Event:      { earningsBuffer: 7, fomcBuffer: 3, divBuffer: 3 },
  Volatility: { ivRankLookback: 252, hvLookback: 20 },
};

interface SettingsState {
  customW:      CustomWeights;
  customParams: CustomParams;
  setCustomW:        (w: CustomWeights) => void;
  setCustomParams:   (p: CustomParams) => void;
  resetToDefaults:   () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      customW:      { ...DEFAULT_WEIGHTS },
      customParams: structuredClone(DEFAULT_PARAMS),
      setCustomW: (w) => set({ customW: w }),
      setCustomParams: (p) => set({ customParams: p }),
      resetToDefaults: () => set({
        customW:      { ...DEFAULT_WEIGHTS },
        customParams: structuredClone(DEFAULT_PARAMS),
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<SettingsState> | null) ?? {};
        if (version < 1) {
          return {
            customW:      prev.customW      ?? { ...DEFAULT_WEIGHTS },
            customParams: prev.customParams ?? structuredClone(DEFAULT_PARAMS),
          } as SettingsState;
        }
        return prev as SettingsState;
      },
    }
  )
);
