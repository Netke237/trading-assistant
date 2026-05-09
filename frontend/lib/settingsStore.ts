/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists the Custom tab's score weights (customW) and indicator
 * parameters (customParams) across page refreshes. Also persists broker
 * config, alertDeduplicationHours, and IV thresholds.
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

const DEFAULT_BROKER: BrokerConfig = {
  broker:       'Interactive Brokers',
  account:      '',
  apiToken:     '',
  paperTrading: true,
};

export interface BrokerConfig {
  broker:       string;
  account:      string;
  apiToken:     string;
  paperTrading: boolean;
}

interface SettingsState {
  customW:                 CustomWeights;
  customParams:            CustomParams;
  broker:                  BrokerConfig;
  alertDeduplicationHours: number;
  ivPassThreshold:         number;
  ivCautionThreshold:      number;
  setCustomW:                   (w: CustomWeights) => void;
  setCustomParams:              (p: CustomParams) => void;
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setIvPassThreshold:           (n: number) => void;
  setIvCautionThreshold:        (n: number) => void;
  resetToDefaults:              () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      customW:                 { ...DEFAULT_WEIGHTS },
      customParams:            JSON.parse(JSON.stringify(DEFAULT_PARAMS)) as CustomParams,
      broker:                  { ...DEFAULT_BROKER },
      alertDeduplicationHours: 24,
      ivPassThreshold:         60,
      ivCautionThreshold:      35,
      setCustomW:                   (w) => set({ customW: w }),
      setCustomParams:              (p) => set({ customParams: p }),
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setIvPassThreshold:           (n) => set({ ivPassThreshold: n }),
      setIvCautionThreshold:        (n) => set({ ivCautionThreshold: n }),
      resetToDefaults: () => set({
        customW:                 { ...DEFAULT_WEIGHTS },
        customParams:            JSON.parse(JSON.stringify(DEFAULT_PARAMS)) as CustomParams,
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        ivPassThreshold:         60,
        ivCautionThreshold:      35,
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 4,
      partialize: (state) => ({
        customW:                 state.customW,
        customParams:            state.customParams,
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        ivPassThreshold:         state.ivPassThreshold,
        ivCautionThreshold:      state.ivCautionThreshold,
      }),
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<SettingsState> | null) ?? {};
        if (version < 2) {
          return {
            customW:                 prev.customW      ?? { ...DEFAULT_WEIGHTS },
            customParams:            prev.customParams ?? JSON.parse(JSON.stringify(DEFAULT_PARAMS)) as CustomParams,
            broker:                  prev.broker       ?? { ...DEFAULT_BROKER },
            alertDeduplicationHours: prev.alertDeduplicationHours ?? 24,
            ivPassThreshold:         60,
            ivCautionThreshold:      35,
          } as SettingsState;
        }
        if (version < 3) {
          return {
            ...prev,
            alertDeduplicationHours: prev.alertDeduplicationHours ?? 24,
            ivPassThreshold:         60,
            ivCautionThreshold:      35,
          } as SettingsState;
        }
        if (version < 4) {
          return {
            ...prev,
            ivPassThreshold:    60,
            ivCautionThreshold: 35,
          } as SettingsState;
        }
        return prev as SettingsState;
      },
    }
  )
);
