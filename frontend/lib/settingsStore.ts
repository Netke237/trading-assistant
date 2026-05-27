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
  lookback:  number;   // daily trading bars for the rolling return window
  threshold: number;   // Bull/Bear return threshold (e.g. 0.02 = 2%)
  smoothing: number;   // EMA weight on return signal (0 = no smoothing)
}

export const MARKOV_PRESETS: Record<MarkovPreset, Omit<MarkovConfig, 'preset'>> = {
  default:      { lookback: 20,  threshold: 0.02,  smoothing: 0.0 },
  conservative: { lookback: 60,  threshold: 0.03,  smoothing: 0.5 },
  aggressive:   { lookback: 10,  threshold: 0.01,  smoothing: 0.0 },
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
  maxContractsPerChain:        number;
  maxContractPrice:            number;
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setIvPassThreshold:           (n: number) => void;
  setIvCautionThreshold:        (n: number) => void;
  setMarkov:                    (cfg: MarkovConfig) => void;
  setShortlistMaxCandidates:   (n: number) => void;
  setMaxContractsPerChain:     (n: number) => void;
  setMaxContractPrice:         (n: number) => void;
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
      maxContractsPerChain: 10,
      maxContractPrice:     500,
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setIvPassThreshold:           (n) => set({ ivPassThreshold: n }),
      setIvCautionThreshold:        (n) => set({ ivCautionThreshold: n }),
      setMarkov:                    (cfg) => set({ markov: cfg }),
      setShortlistMaxCandidates: (n) => set({ shortlistMaxCandidates: n }),
      setMaxContractsPerChain: (n) => set({ maxContractsPerChain: n }),
      setMaxContractPrice:     (n) => set({ maxContractPrice: n }),
      resetToDefaults: () => set({
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        ivPassThreshold:         34,
        ivCautionThreshold:      55,
        markov:                  { ...DEFAULT_MARKOV },
        shortlistMaxCandidates: 10,
        maxContractsPerChain: 10,
        maxContractPrice:     500,
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 9,
      partialize: (state) => ({
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        ivPassThreshold:         state.ivPassThreshold,
        ivCautionThreshold:      state.ivCautionThreshold,
        markov:                  state.markov,
        shortlistMaxCandidates: state.shortlistMaxCandidates,
        maxContractsPerChain:   state.maxContractsPerChain,
        maxContractPrice:       state.maxContractPrice,
      }),
      migrate: (persistedState, version) => {
        const prev = (persistedState ?? {}) as Partial<SettingsState>;
        if (version < 7) {
          return { ...prev, markov: DEFAULT_MARKOV } as unknown as SettingsState;
        }
        if (version < 8) {
          return { ...prev, shortlistMaxCandidates: 10 } as unknown as SettingsState;
        }
        if (version < 9) {
          return { ...prev, maxContractsPerChain: 10, maxContractPrice: 50 } as unknown as SettingsState;
        }
        return prev as unknown as SettingsState;
      },
    }
  )
);
