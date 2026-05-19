/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists broker config, alertDeduplicationHours, and IV thresholds.
 * Score weights and indicator parameters live in the D+H Execution Parameters panel.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const SETTINGS_STORAGE_KEY = 'bamendjou-settings';

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
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setIvPassThreshold:           (n: number) => void;
  setIvCautionThreshold:        (n: number) => void;
  resetToDefaults:              () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      broker:                  { ...DEFAULT_BROKER },
      alertDeduplicationHours: 24,
      ivPassThreshold:         34,
      ivCautionThreshold:      55,
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setIvPassThreshold:           (n) => set({ ivPassThreshold: n }),
      setIvCautionThreshold:        (n) => set({ ivCautionThreshold: n }),
      resetToDefaults: () => set({
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        ivPassThreshold:         34,
        ivCautionThreshold:      55,
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 6,
      partialize: (state) => ({
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        ivPassThreshold:         state.ivPassThreshold,
        ivCautionThreshold:      state.ivCautionThreshold,
      }),
      migrate: (persistedState, version) => {
        const prev = (persistedState ?? {}) as Partial<SettingsState>;
        if (version < 6) {
          return {
            broker:                  prev.broker ?? { ...DEFAULT_BROKER },
            alertDeduplicationHours: prev.alertDeduplicationHours ?? 24,
            ivPassThreshold:         34,
            ivCautionThreshold:      55,
          } as unknown as SettingsState;
        }
        return prev as unknown as SettingsState;
      },
    }
  )
);
