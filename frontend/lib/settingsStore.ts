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

export interface ConfidenceGate {
  enabled:      boolean;
  cautionBelow: number;   // confidence < this -> cap at CAUTION
  rejectBelow:  number;   // confidence < this -> cap at REJECT
  atrMult:      number;   // ATR multiple for the backtest win/loss barriers
}

export const DEFAULT_CONFIDENCE_GATE: ConfidenceGate = {
  enabled: true,
  cautionBelow: 50,
  rejectBelow: 35,
  atrMult: 1.5,
};

export interface IbkrPaperConfig {
  baseUrl:   string;
  accountId: string;
}

export interface TradierPaperConfig {
  token:     string;
  accountId: string;
}

export interface IbkrLiveConfig {
  enabled: false;   // always false until manually unlocked in a future release
  note:    string;
}

export interface AlpacaPaperConfig {
  keyId:     string;
  secretKey: string;
}

export interface AlpacaLiveConfig {
  enabled: false;
  note:    string;
}

export const DEFAULT_IBKR_PAPER: IbkrPaperConfig = {
  baseUrl:   'https://localhost:7499/v1/api',
  accountId: '',
};

export const DEFAULT_TRADIER_PAPER: TradierPaperConfig = {
  token:     '',
  accountId: '',
};

export interface TradierLiveConfig {
  token:     string;
  accountId: string;
}

export const DEFAULT_TRADIER_LIVE: TradierLiveConfig = {
  token:     '',
  accountId: '',
};

export const DEFAULT_IBKR_LIVE: IbkrLiveConfig = {
  enabled: false,
  note:    'Live IBKR trading is prepared but not yet activated.',
};

export const DEFAULT_ALPACA_PAPER: AlpacaPaperConfig = {
  keyId:     '',
  secretKey: '',
};

export const DEFAULT_ALPACA_LIVE: AlpacaLiveConfig = {
  enabled: false,
  note:    'Live Alpaca trading is prepared but not yet activated.',
};

interface SettingsState {
  broker:                  BrokerConfig;
  alertDeduplicationHours: number;
  ivPassThreshold:         number;
  ivCautionThreshold:      number;
  markov:                  MarkovConfig;
  shortlistMaxCandidates:      number;
  maxContractsPerChain:        number;
  maxContractPrice:            number;
  premiumStopPct:              number;   // fraction of premium lost at stop (0.60 = 60%)
  confidenceGate:              ConfidenceGate;
  ibkrPaper:                   IbkrPaperConfig;
  tradierPaper:                TradierPaperConfig;
  tradierLive:                 TradierLiveConfig;
  ibkrLive:                    IbkrLiveConfig;
  alpacaPaper:                 AlpacaPaperConfig;
  alpacaLive:                  AlpacaLiveConfig;
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setIvPassThreshold:           (n: number) => void;
  setIvCautionThreshold:        (n: number) => void;
  setMarkov:                    (cfg: MarkovConfig) => void;
  setShortlistMaxCandidates:   (n: number) => void;
  setMaxContractsPerChain:     (n: number) => void;
  setMaxContractPrice:         (n: number) => void;
  setPremiumStopPct:           (n: number) => void;
  setConfidenceGate:           (g: ConfidenceGate) => void;
  setIbkrPaper:                (c: IbkrPaperConfig)    => void;
  setTradierPaper:             (c: TradierPaperConfig) => void;
  setTradierLive:              (c: TradierLiveConfig)  => void;
  setAlpacaPaper:              (c: AlpacaPaperConfig)  => void;
  resetToDefaults:              () => void;
}

/**
 * Cumulative persisted-state migration. Each branch ADDS the fields introduced
 * at that version; branches must stack (no early returns) so a store saved at
 * an old version picks up every field added since — not just the next one.
 */
export function migrateSettings(
  persistedState: unknown,
  version: number,
): SettingsState {
  const next = { ...((persistedState ?? {}) as Partial<SettingsState>) };
  if (version < 7) next.markov = DEFAULT_MARKOV;
  if (version < 8) next.shortlistMaxCandidates = 10;
  if (version < 9) {
    next.maxContractsPerChain = 10;
    next.maxContractPrice = 50;
  }
  if (version < 10) next.premiumStopPct = 0.60;
  if (version < 11) next.confidenceGate = { ...DEFAULT_CONFIDENCE_GATE };
  if (version < 12) next.confidenceGate = { ...DEFAULT_CONFIDENCE_GATE, ...(next.confidenceGate ?? {}) };
  if (version < 13) {
    next.ibkrPaper    = { ...DEFAULT_IBKR_PAPER };
    next.tradierPaper = { ...DEFAULT_TRADIER_PAPER };
    next.ibkrLive     = { ...DEFAULT_IBKR_LIVE };
  }
  if (version < 14) {
    next.alpacaPaper = { ...DEFAULT_ALPACA_PAPER };
    next.alpacaLive  = { ...DEFAULT_ALPACA_LIVE };
  }
  if (version < 15) {
    next.tradierLive = { ...DEFAULT_TRADIER_LIVE };
  }
  return next as unknown as SettingsState;
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
      maxContractPrice:     50,
      premiumStopPct:       0.60,
      confidenceGate:       { ...DEFAULT_CONFIDENCE_GATE },
      ibkrPaper:            { ...DEFAULT_IBKR_PAPER },
      tradierPaper:         { ...DEFAULT_TRADIER_PAPER },
      tradierLive:          { ...DEFAULT_TRADIER_LIVE },
      ibkrLive:             { ...DEFAULT_IBKR_LIVE },
      alpacaPaper:          { ...DEFAULT_ALPACA_PAPER },
      alpacaLive:           { ...DEFAULT_ALPACA_LIVE },
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setIvPassThreshold:           (n) => set({ ivPassThreshold: n }),
      setIvCautionThreshold:        (n) => set({ ivCautionThreshold: n }),
      setMarkov:                    (cfg) => set({ markov: cfg }),
      setShortlistMaxCandidates: (n) => set({ shortlistMaxCandidates: n }),
      setMaxContractsPerChain: (n) => set({ maxContractsPerChain: n }),
      setMaxContractPrice:     (n) => set({ maxContractPrice: n }),
      setPremiumStopPct:       (n) => set({ premiumStopPct: n }),
      setConfidenceGate:       (g) => set({ confidenceGate: g }),
      setIbkrPaper:    (c) => set({ ibkrPaper: c }),
      setTradierPaper: (c) => set({ tradierPaper: c }),
      setTradierLive:  (c) => set({ tradierLive: c }),
      setAlpacaPaper:  (c) => set({ alpacaPaper: c }),
      resetToDefaults: () => set({
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        ivPassThreshold:         34,
        ivCautionThreshold:      55,
        markov:                  { ...DEFAULT_MARKOV },
        shortlistMaxCandidates: 10,
        maxContractsPerChain: 10,
        maxContractPrice:     50,
        premiumStopPct:       0.60,
        confidenceGate:       { ...DEFAULT_CONFIDENCE_GATE },
        ibkrPaper:   { ...DEFAULT_IBKR_PAPER },
        tradierPaper: { ...DEFAULT_TRADIER_PAPER },
        tradierLive:  { ...DEFAULT_TRADIER_LIVE },
        alpacaPaper:  { ...DEFAULT_ALPACA_PAPER },
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 15,
      partialize: (state) => ({
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        ivPassThreshold:         state.ivPassThreshold,
        ivCautionThreshold:      state.ivCautionThreshold,
        markov:                  state.markov,
        shortlistMaxCandidates: state.shortlistMaxCandidates,
        maxContractsPerChain:   state.maxContractsPerChain,
        maxContractPrice:       state.maxContractPrice,
        premiumStopPct:         state.premiumStopPct,
        confidenceGate:         state.confidenceGate,
        ibkrPaper:    state.ibkrPaper,
        tradierPaper: state.tradierPaper,
        tradierLive:  state.tradierLive,
        alpacaPaper:  state.alpacaPaper,
      }),
      migrate: (persistedState, version) => migrateSettings(persistedState, version),
    }
  )
);
