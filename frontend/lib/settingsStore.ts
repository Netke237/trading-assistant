/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists broker config, alertDeduplicationHours, and IV thresholds.
 * Score weights and indicator parameters live in the D+H Execution Parameters panel.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const SETTINGS_STORAGE_KEY = 'bamendjou-settings';

export type MarkovPreset = 'default' | 'conservative' | 'aggressive';

export interface MarkovConfig {
  preset:    MarkovPreset;
  lookback:  number;   // bars (number of candles)
  threshold: number;   // avg return threshold (e.g. 0.003 = 0.3%)
  smoothing: number;   // EMA weight 0.0–1.0
}

export const MARKOV_PRESETS: Record<MarkovPreset, Omit<MarkovConfig, 'preset'>> = {
  default:      { lookback: 60,  threshold: 0.003, smoothing: 0.7 },
  conservative: { lookback: 120, threshold: 0.005, smoothing: 0.8 },
  aggressive:   { lookback: 20,  threshold: 0.001, smoothing: 0.5 },
};

export const DEFAULT_MARKOV: MarkovConfig = { preset: 'default', ...MARKOV_PRESETS.default };

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
  broker:                  BrokerConfig;
  alertDeduplicationHours: number;
  ivPassThreshold:         number;
  ivCautionThreshold:      number;
  markov:                  MarkovConfig;
  shortlistMaxCandidates:      number;
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setIvPassThreshold:           (n: number) => void;
  setIvCautionThreshold:        (n: number) => void;
  setMarkov:                    (cfg: MarkovConfig) => void;
  setShortlistMaxCandidates:   (n: number) => void;
  resetToDefaults:              () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      broker:                  { ...DEFAULT_BROKER },
      alertDeduplicationHours: 24,
      ivPassThreshold:         34,
      ivCautionThreshold:      55,
      markov:                  { ...DEFAULT_MARKOV },
      shortlistMaxCandidates: 10,
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setIvPassThreshold:           (n) => set({ ivPassThreshold: n }),
      setIvCautionThreshold:        (n) => set({ ivCautionThreshold: n }),
      setMarkov:                    (cfg) => set({ markov: cfg }),
      setShortlistMaxCandidates: (n) => set({ shortlistMaxCandidates: n }),
      resetToDefaults: () => set({
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        ivPassThreshold:         34,
        ivCautionThreshold:      55,
        markov:                  { ...DEFAULT_MARKOV },
        shortlistMaxCandidates: 10,
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 8,
      partialize: (state) => ({
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        ivPassThreshold:         state.ivPassThreshold,
        ivCautionThreshold:      state.ivCautionThreshold,
        markov:                  state.markov,
        shortlistMaxCandidates: state.shortlistMaxCandidates,
      }),
      migrate: (persistedState, version) => {
        const prev = (persistedState ?? {}) as Partial<SettingsState>;
        if (version < 7) {
          return { ...prev, markov: DEFAULT_MARKOV } as unknown as SettingsState;
        }
        if (version < 8) {
          return { ...prev, shortlistMaxCandidates: 10 } as unknown as SettingsState;
        }
        return prev as unknown as SettingsState;
      },
    }
  )
);
