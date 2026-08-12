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

export interface AtrMultPair {
  target: number;   // win barrier = target × ATR
  stop:   number;   // loss barrier = stop × ATR
}

export interface AtrMultByHorizon {
  intraday: AtrMultPair;
  swing:    AtrMultPair;
  position: AtrMultPair;
}

export interface ConfidenceGate {
  enabled:      boolean;
  cautionBelow: number;   // confidence < this -> cap at CAUTION
  rejectBelow:  number;   // confidence < this -> cap at REJECT
  // Per-horizon backtest win/loss ATR barriers — a single symmetric multiple
  // can't represent backend/config/scoring_rules.yaml's calibrated per-horizon
  // ASYMMETRIC atr_mult_target/atr_mult_stop (e.g. swing targets ~3 ATR but
  // risks only ~1.5 ATR stop), so each horizon gets its own target/stop pair.
  atrMult: AtrMultByHorizon;
}

export const DEFAULT_ATR_MULT_BY_HORIZON: AtrMultByHorizon = {
  intraday: { target: 2.0, stop: 1.5 },
  swing:    { target: 3.0, stop: 1.5 },
  position: { target: 2.5, stop: 1.5 },
};

export const DEFAULT_CONFIDENCE_GATE: ConfidenceGate = {
  enabled: true,
  cautionBelow: 50,
  rejectBelow: 35,
  atrMult: { ...DEFAULT_ATR_MULT_BY_HORIZON },
};

/**
 * Resolve the per-horizon ATR target/stop pair for a scan's horizon string
 * (e.g. "Swing", "Intraday", "Position", or a full display string like
 * "Swing (5-15d)" — only the first word is matched, case-insensitively).
 * Falls back to the swing pair for any unrecognized horizon (Quarterly/
 * SemiAnnual/Annual all resolve to "Position" upstream via scoringHorizon,
 * so this should only miss on a genuinely new/typo'd horizon name).
 */
export function atrMultForHorizon(gate: ConfidenceGate, horizon: string): AtrMultPair {
  const key = horizon.trim().split(/\s+/)[0]?.toLowerCase();
  if (key === 'intraday') return gate.atrMult.intraday;
  if (key === 'position') return gate.atrMult.position;
  return gate.atrMult.swing;
}

/**
 * Clamps a paired cautionBelow/rejectBelow threshold edit into a valid range:
 * both within [0,100], and rejectBelow <= cautionBelow. status_cap() in
 * backend/app/scoring/signal_confidence.py assumes this ordering — a gate
 * configured backwards makes the REJECT tier unreachable or inverted.
 * `edited` identifies which field the caller just changed (it wins the
 * boundary; the OTHER stored field is pulled into range if needed).
 */
export function clampGateThresholds(
  edited: 'cautionBelow' | 'rejectBelow',
  newValue: number,
  otherValue: number,
): { cautionBelow: number; rejectBelow: number } {
  const clamped = Math.max(0, Math.min(100, newValue));
  if (edited === 'cautionBelow') {
    return { cautionBelow: clamped, rejectBelow: Math.min(otherValue, clamped) };
  }
  return { cautionBelow: Math.max(otherValue, clamped), rejectBelow: clamped };
}

export interface TargetProfitPct {
  t1: number;   // fraction of premium (0.20 = 20%)
  t2: number;
  t3: number;
}

export const DEFAULT_TARGET_PROFIT_PCT: TargetProfitPct = {
  t1: 0.20,
  t2: 0.35,
  t3: 0.50,
};

export interface FundamentalsGate {
  enabled:      boolean;
  cautionBelow: number;   // health score < this -> cap at CAUTION
  rejectBelow:  number;   // health score < this -> cap at REJECT
  deReject:     number;   // D/E ratio above which a safety reject fires
}

export const DEFAULT_FUNDAMENTALS_GATE: FundamentalsGate = {
  enabled: true,
  cautionBelow: 45,
  rejectBelow: 30,
  deReject: 3.0,
};

export interface ScheduleConfig {
  enabledOptions:  boolean;
  enabledStocks:   boolean;
  cadenceMinutes:  number;
  daysOfWeek:      number[];
  windowStartHour: number;
  windowEndHour:   number;
  timezoneName:    string;
}

export const DEFAULT_SCHEDULE_CONFIG: ScheduleConfig = {
  enabledOptions:  false,
  enabledStocks:   false,
  cadenceMinutes:  60,
  daysOfWeek:      [0, 1, 2, 3, 4],
  windowStartHour: 9,
  windowEndHour:   17,
  timezoneName:    'America/New_York',
};

export interface SpreadsConfig {
  shortLegDelta:      number;   // delta of the short leg (e.g. 0.30 = 30Δ)
  widthPoints:        number;   // spread width in strike points
  ivRankThreshold:    number;   // minimum IV rank % to enter
  minCredit:          number;   // minimum credit received (credit spreads)
  maxDebitPctOfWidth: number;   // maximum debit as % of width (debit spreads)
}

export const DEFAULT_SPREADS: SpreadsConfig = {
  shortLegDelta:      0.30,
  widthPoints:        5,
  ivRankThreshold:    50,
  minCredit:          0.50,
  maxDebitPctOfWidth: 40,
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

export interface TastytradePaperConfig {
  clientSecret: string;
  refreshToken: string;
  accountId:    string;
}

export interface TastytradeLiveConfig {
  enabled: false;   // always false until manually unlocked in a future release
  note:    string;
}

export const DEFAULT_TASTYTRADE_PAPER: TastytradePaperConfig = {
  clientSecret: '',
  refreshToken: '',
  accountId:    '',
};

export const DEFAULT_TASTYTRADE_LIVE: TastytradeLiveConfig = {
  enabled: false,
  note:    'Live tastytrade trading is prepared but not yet activated.',
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
  markov:                  MarkovConfig;
  shortlistMaxCandidates:      number;
  maxContractsPerChain:        number;
  maxContractPrice:            number;
  premiumStopPct:              number;   // fraction of premium lost at stop (0.60 = 60%)
  targetProfitPct:             TargetProfitPct;
  confidenceGate:              ConfidenceGate;
  fundamentalsGate:            FundamentalsGate;
  ibkrPaper:                   IbkrPaperConfig;
  tradierPaper:                TradierPaperConfig;
  tradierLive:                 TradierLiveConfig;
  ibkrLive:                    IbkrLiveConfig;
  alpacaPaper:                 AlpacaPaperConfig;
  alpacaLive:                  AlpacaLiveConfig;
  tastytradePaper:             TastytradePaperConfig;
  tastytradeLive:              TastytradeLiveConfig;
  spreads:                     SpreadsConfig;
  scheduleConfig:              ScheduleConfig;
  setBroker:                    (b: BrokerConfig) => void;
  setAlertDeduplicationHours:   (h: number) => void;
  setMarkov:                    (cfg: MarkovConfig) => void;
  setShortlistMaxCandidates:   (n: number) => void;
  setMaxContractsPerChain:     (n: number) => void;
  setMaxContractPrice:         (n: number) => void;
  setPremiumStopPct:           (n: number) => void;
  setTargetProfitPct:          (t: TargetProfitPct) => void;
  setConfidenceGate:           (g: ConfidenceGate) => void;
  setFundamentalsGate:         (g: FundamentalsGate) => void;
  setSpreads:                  (s: Partial<SpreadsConfig>) => void;
  setScheduleConfig:           (c: ScheduleConfig) => void;
  setIbkrPaper:                (c: IbkrPaperConfig)    => void;
  setTradierPaper:             (c: TradierPaperConfig) => void;
  setTradierLive:              (c: TradierLiveConfig)  => void;
  setAlpacaPaper:              (c: AlpacaPaperConfig)  => void;
  setTastytradePaper:          (c: TastytradePaperConfig) => void;
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
  if (version < 16) {
    next.fundamentalsGate = { ...DEFAULT_FUNDAMENTALS_GATE };
  }
  if (version < 17) {
    next.spreads = { ...DEFAULT_SPREADS };
  }
  if (version < 18) {
    delete (next as Record<string, unknown>).ivPassThreshold;
    delete (next as Record<string, unknown>).ivCautionThreshold;
  }
  if (version < 19) {
    (next as Record<string, unknown>).scheduleConfig = { ...DEFAULT_SCHEDULE_CONFIG };
  }
  if (version < 20) {
    next.tastytradePaper = { ...DEFAULT_TASTYTRADE_PAPER };
    next.tastytradeLive  = { ...DEFAULT_TASTYTRADE_LIVE };
  }
  if (version < 21) {
    next.targetProfitPct = { ...DEFAULT_TARGET_PROFIT_PCT };
  }
  if (version < 22) {
    // atrMult restructured: a single symmetric multiple always overrode
    // compute_confidence's calibrated per-horizon ASYMMETRIC atr_mult_target/
    // atr_mult_stop config (see confidence_backtest in backend/config/
    // scoring_rules.yaml) — replaced with a target/stop pair per horizon.
    const gate = { ...(next.confidenceGate ?? DEFAULT_CONFIDENCE_GATE) } as Partial<ConfidenceGate> & { atrMult?: unknown };
    if (typeof gate.atrMult !== 'object' || gate.atrMult === null) {
      gate.atrMult = { ...DEFAULT_ATR_MULT_BY_HORIZON };
    }
    next.confidenceGate = gate as ConfidenceGate;
  }
  return next as unknown as SettingsState;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      broker:                  { ...DEFAULT_BROKER },
      alertDeduplicationHours: 24,
      markov:                  { ...DEFAULT_MARKOV },
      shortlistMaxCandidates: 10,
      maxContractsPerChain: 10,
      maxContractPrice:     50,
      premiumStopPct:       0.60,
      targetProfitPct:      { ...DEFAULT_TARGET_PROFIT_PCT },
      confidenceGate:       { ...DEFAULT_CONFIDENCE_GATE },
      fundamentalsGate:     { ...DEFAULT_FUNDAMENTALS_GATE },
      ibkrPaper:            { ...DEFAULT_IBKR_PAPER },
      tradierPaper:         { ...DEFAULT_TRADIER_PAPER },
      tradierLive:          { ...DEFAULT_TRADIER_LIVE },
      ibkrLive:             { ...DEFAULT_IBKR_LIVE },
      alpacaPaper:          { ...DEFAULT_ALPACA_PAPER },
      alpacaLive:           { ...DEFAULT_ALPACA_LIVE },
      tastytradePaper:      { ...DEFAULT_TASTYTRADE_PAPER },
      tastytradeLive:       { ...DEFAULT_TASTYTRADE_LIVE },
      spreads:              { ...DEFAULT_SPREADS },
      scheduleConfig:       { ...DEFAULT_SCHEDULE_CONFIG },
      setBroker:                    (b) => set({ broker: b }),
      setAlertDeduplicationHours:   (h) => set({ alertDeduplicationHours: h }),
      setMarkov:                    (cfg) => set({ markov: cfg }),
      setShortlistMaxCandidates: (n) => set({ shortlistMaxCandidates: n }),
      setMaxContractsPerChain: (n) => set({ maxContractsPerChain: n }),
      setMaxContractPrice:     (n) => set({ maxContractPrice: n }),
      setPremiumStopPct:       (n) => set({ premiumStopPct: n }),
      setTargetProfitPct:      (t) => set({ targetProfitPct: t }),
      setConfidenceGate:       (g) => set({ confidenceGate: g }),
      setFundamentalsGate:     (g) => set({ fundamentalsGate: g }),
      setSpreads:              (s) => set((state) => ({ spreads: { ...state.spreads, ...s } })),
      setScheduleConfig:       (c) => set({ scheduleConfig: c }),
      setIbkrPaper:    (c) => set({ ibkrPaper: c }),
      setTradierPaper: (c) => set({ tradierPaper: c }),
      setTradierLive:  (c) => set({ tradierLive: c }),
      setAlpacaPaper:  (c) => set({ alpacaPaper: c }),
      setTastytradePaper: (c) => set({ tastytradePaper: c }),
      resetToDefaults: () => set({
        broker:                  { ...DEFAULT_BROKER },
        alertDeduplicationHours: 24,
        markov:                  { ...DEFAULT_MARKOV },
        shortlistMaxCandidates: 10,
        maxContractsPerChain: 10,
        maxContractPrice:     50,
        premiumStopPct:       0.60,
        targetProfitPct:      { ...DEFAULT_TARGET_PROFIT_PCT },
        confidenceGate:       { ...DEFAULT_CONFIDENCE_GATE },
        fundamentalsGate:     { ...DEFAULT_FUNDAMENTALS_GATE },
        ibkrPaper:    { ...DEFAULT_IBKR_PAPER },
        tradierPaper: { ...DEFAULT_TRADIER_PAPER },
        tradierLive:  { ...DEFAULT_TRADIER_LIVE },
        ibkrLive:     { ...DEFAULT_IBKR_LIVE },
        alpacaPaper:  { ...DEFAULT_ALPACA_PAPER },
        alpacaLive:   { ...DEFAULT_ALPACA_LIVE },
        tastytradePaper: { ...DEFAULT_TASTYTRADE_PAPER },
        tastytradeLive:  { ...DEFAULT_TASTYTRADE_LIVE },
        spreads:        { ...DEFAULT_SPREADS },
        scheduleConfig: { ...DEFAULT_SCHEDULE_CONFIG },
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 22,
      partialize: (state) => ({
        broker:                  state.broker,
        alertDeduplicationHours: state.alertDeduplicationHours,
        markov:                  state.markov,
        shortlistMaxCandidates: state.shortlistMaxCandidates,
        maxContractsPerChain:   state.maxContractsPerChain,
        maxContractPrice:       state.maxContractPrice,
        premiumStopPct:         state.premiumStopPct,
        targetProfitPct:        state.targetProfitPct,
        confidenceGate:         state.confidenceGate,
        fundamentalsGate:       state.fundamentalsGate,
        ibkrPaper:    state.ibkrPaper,
        tradierPaper:   state.tradierPaper,
        tradierLive:    state.tradierLive,
        alpacaPaper:    state.alpacaPaper,
        tastytradePaper: state.tastytradePaper,
        spreads:        state.spreads,
        scheduleConfig: state.scheduleConfig,
      }),
      migrate: (persistedState, version) => migrateSettings(persistedState, version),
    }
  )
);
