/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists broker config (per-broker paper/live credentials), alertDeduplicationHours,
 * markov regime config, shortlist/contract/price limits, premiumStopPct, targetProfitPct,
 * confidenceGate, fundamentalsGate, spreads config, and scheduleConfig. IV rank/percentile
 * thresholds moved to ivThresholdsStore.ts in the v18 migration and no longer live here.
 * Score weights and indicator parameters live in the D+H Execution Parameters panel.
 */

import { create } from 'zustand';
import { persist, createJSONStorage, type StateStorage } from 'zustand/middleware';
import { reportingLocalStorage } from './reportingLocalStorage';

export const SETTINGS_STORAGE_KEY = 'bamendjou-settings';

/**
 * Deep equality helper for settings store states and nested configuration objects.
 * Handles primitives, NaN, arrays (atomic equality), and plain objects.
 */
export function isSettingsEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || a === null || typeof b !== 'object' || b === null) {
    return false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) {
    return false;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!isSettingsEqual(a[i], b[i])) return false;
    }
    return true;
  }
  const aObj = a as Record<string, unknown>;
  const bObj = b as Record<string, unknown>;
  const aKeys = Object.keys(aObj);
  const bKeys = Object.keys(bObj);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (!Object.prototype.hasOwnProperty.call(bObj, key)) return false;
    if (!isSettingsEqual(aObj[key], bObj[key])) return false;
  }
  return true;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * Recursive leaf-property three-way merge.
 * Traverses nested configuration objects and resolves at scalar/leaf level:
 * - tabChanged && !diskChanged => incoming
 * - diskChanged && !tabChanged => disk
 * - tabChanged && diskChanged => incoming (active user action wins conflict)
 * - neither changed => disk !== undefined ? disk : incoming
 */
export function mergeLeafProperties(
  incoming: unknown,
  disk: unknown,
  baseline: unknown,
): unknown {
  if (isPlainObject(incoming) && isPlainObject(disk)) {
    const baseObj = isPlainObject(baseline) ? baseline : {};
    const allKeys = new Set([
      ...Object.keys(incoming),
      ...Object.keys(disk),
      ...Object.keys(baseObj),
    ]);
    const result: Record<string, unknown> = {};
    for (const key of allKeys) {
      const mergedVal = mergeLeafProperties(incoming[key], disk[key], baseObj[key]);
      if (mergedVal !== undefined) {
        result[key] = mergedVal;
      }
    }
    return result;
  }
  const tabChanged = !isSettingsEqual(incoming, baseline);
  const diskChanged = !isSettingsEqual(disk, baseline);
  if (tabChanged && !diskChanged) return incoming;
  if (diskChanged && !tabChanged) return disk;
  if (tabChanged && diskChanged) return incoming;
  return disk !== undefined ? disk : incoming;
}

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
  ivRankThreshold:    number;   // sell-premium cut-off when an IV RANK is in hand
  // Sell-premium cut-off when only an ABSOLUTE IV is in hand — which is most
  // chains, since a real rank needs IBKR or tastytrade to answer. Separate from
  // ivRankThreshold because "50% IV" and "the 50th percentile" are different
  // claims; defaulted to the same 50 so nothing changed on the day it shipped.
  ivAbsThreshold:     number;
  minCredit:          number;   // minimum credit received (credit spreads)
  maxDebitPctOfWidth: number;   // maximum debit as % of width (debit spreads)
}

export const DEFAULT_SPREADS: SpreadsConfig = {
  shortLegDelta:      0.30,
  widthPoints:        5,
  ivRankThreshold:    50,
  ivAbsThreshold:     50,
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
  if (version < 23) {
    // atrMult restructured: a single symmetric multiple always overrode
    // compute_confidence's calibrated per-horizon ASYMMETRIC atr_mult_target/
    // atr_mult_stop config (see confidence_backtest in backend/config/
    // scoring_rules.yaml) — replaced with a target/stop pair per horizon.
    // Deliberately version<23, not <22: an earlier build shipped at version 22
    // and DELETED atrMult entirely (rather than nesting it), so a store
    // already persisted at exactly 22 must still run this branch — gating on
    // <22 would make persist() skip migrate() outright for that case (version
    // equality means no migration runs at all), leaving atrMult permanently
    // undefined and crashing every reader.
    const gate = { ...(next.confidenceGate ?? DEFAULT_CONFIDENCE_GATE) } as Partial<ConfidenceGate> & { atrMult?: unknown };
    if (typeof gate.atrMult !== 'object' || gate.atrMult === null) {
      gate.atrMult = { ...DEFAULT_ATR_MULT_BY_HORIZON };
    }
    next.confidenceGate = gate as ConfidenceGate;
  }
  if (version < 24) {
    // PHASE-A-SPREAD-BASIS-2026-09-06 split the spread picker's single
    // sell-premium cut-off in two, because `ivRankThreshold` was being applied
    // to an absolute IV on most chains -- "50% IV" judged as though it were
    // "the 50th percentile". A blob persisted at <=23 has no ivAbsThreshold.
    //
    // Benign by luck (undefined omits the field, and the backend's own default
    // is the same 50), and stated rather than left to be re-derived: CLAUDE.md
    // asks for the bump and the branch, and this store is where round 10
    // finding 16 caught the same omission before.
    //
    // Seeded from the user's OWN ivRankThreshold, not the constant: someone
    // who moved the old single knob meant that for the chains they actually
    // see, which are the absolute ones.
    const sp = { ...(next.spreads ?? DEFAULT_SPREADS) } as Record<string, unknown>;
    if (sp.ivAbsThreshold === undefined) {
      sp.ivAbsThreshold = typeof sp.ivRankThreshold === 'number'
        ? sp.ivRankThreshold
        : DEFAULT_SPREADS.ivAbsThreshold;
    }
    next.spreads = sp as unknown as SpreadsConfig;
  }
  return next as unknown as SettingsState;
}

export function getDefaultPersistedSettings(): Record<string, unknown> {
  return {
    broker:                  { ...DEFAULT_BROKER },
    alertDeduplicationHours: 24,
    markov:                  { ...DEFAULT_MARKOV },
    shortlistMaxCandidates: 10,
    maxContractsPerChain:   10,
    maxContractPrice:       50,
    premiumStopPct:         0.60,
    targetProfitPct:        { ...DEFAULT_TARGET_PROFIT_PCT },
    confidenceGate:         {
      ...DEFAULT_CONFIDENCE_GATE,
      atrMult: { ...DEFAULT_ATR_MULT_BY_HORIZON },
    },
    fundamentalsGate:       { ...DEFAULT_FUNDAMENTALS_GATE },
    ibkrPaper:              { ...DEFAULT_IBKR_PAPER },
    tradierPaper:           { ...DEFAULT_TRADIER_PAPER },
    tradierLive:            { ...DEFAULT_TRADIER_LIVE },
    alpacaPaper:            { ...DEFAULT_ALPACA_PAPER },
    tastytradePaper:        { ...DEFAULT_TASTYTRADE_PAPER },
    spreads:                { ...DEFAULT_SPREADS },
    scheduleConfig:         { ...DEFAULT_SCHEDULE_CONFIG },
  };
}

let lastCommittedSettings: Record<string, unknown> | null = initializeLastCommittedSettings();
let isMerging = false;
let isSyncing = false;

function initializeLastCommittedSettings(): Record<string, unknown> {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return getDefaultPersistedSettings();
  }
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return getDefaultPersistedSettings();
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && parsed.state && typeof parsed.state === 'object') {
      if (typeof parsed.version === 'number' && parsed.version < 24) {
        return migrateSettings(parsed.state, parsed.version) as unknown as Record<string, unknown>;
      }
      return parsed.state as Record<string, unknown>;
    }
  } catch {
    // malformed disk contents
  }
  return getDefaultPersistedSettings();
}

export function getLastCommittedSettings(): Record<string, unknown> | null {
  return lastCommittedSettings;
}

export function setLastCommittedSettings(baseline: Record<string, unknown> | null): void {
  lastCommittedSettings = baseline;
}

export function syncSettingsFromStorage(raw?: string | null): void {
  if (raw === undefined && typeof localStorage !== 'undefined') {
    try {
      raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    } catch {
      raw = null;
    }
  }
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || typeof parsed.state !== 'object') {
      return;
    }
    let migrated = parsed.state as Record<string, unknown>;
    if (typeof parsed.version === 'number' && parsed.version < 24) {
      migrated = migrateSettings(parsed.state, parsed.version) as unknown as Record<string, unknown>;
    }
    lastCommittedSettings = migrated;
    isSyncing = true;
    try {
      useSettingsStore.setState(migrated as Partial<SettingsState>, false);
    } finally {
      isSyncing = false;
    }
  } catch {
    // malformed payload
  }
}

export function createSettingsStateStorage(): StateStorage {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
  const reportingStorage = reportingLocalStorage('Settings (this browser)');
  return {
    getItem: (key: string): string | null => {
      const raw = reportingStorage.getItem(key);
      if (!raw) {
        lastCommittedSettings = getDefaultPersistedSettings();
        return null;
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && parsed.state && typeof parsed.state === 'object') {
          if (typeof parsed.version === 'number' && parsed.version < 24) {
            lastCommittedSettings = migrateSettings(parsed.state, parsed.version) as unknown as Record<string, unknown>;
          } else {
            lastCommittedSettings = parsed.state as Record<string, unknown>;
          }
        }
      } catch {
        lastCommittedSettings = getDefaultPersistedSettings();
      }
      return raw;
    },
    setItem: (key: string, valueString: string): void => {
      if (isMerging || isSyncing) return;
      try {
        isMerging = true;
        let incoming: { state: Record<string, unknown>; version?: number };
        try {
          incoming = JSON.parse(valueString);
        } catch {
          reportingStorage.setItem(key, valueString);
          return;
        }
        if (!incoming || typeof incoming !== 'object' || typeof incoming.state !== 'object') {
          reportingStorage.setItem(key, valueString);
          return;
        }

        let currentDiskRaw: string | null = null;
        try {
          currentDiskRaw = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
        } catch {
          // localStorage access error
        }

        if (!currentDiskRaw) {
          reportingStorage.setItem(key, valueString);
          lastCommittedSettings = incoming.state;
          return;
        }

        let currentDisk: { state: Record<string, unknown>; version?: number };
        try {
          currentDisk = JSON.parse(currentDiskRaw);
        } catch {
          reportingStorage.setItem(key, valueString);
          lastCommittedSettings = incoming.state;
          return;
        }

        if (!currentDisk || typeof currentDisk !== 'object' || typeof currentDisk.state !== 'object') {
          reportingStorage.setItem(key, valueString);
          lastCommittedSettings = incoming.state;
          return;
        }

        let diskState = currentDisk.state;
        if (typeof currentDisk.version === 'number' && currentDisk.version < 24) {
          diskState = migrateSettings(currentDisk.state, currentDisk.version) as unknown as Record<string, unknown>;
        }

        const baseline = lastCommittedSettings ?? getDefaultPersistedSettings();
        const mergedState = mergeLeafProperties(
          incoming.state,
          diskState,
          baseline,
        ) as Record<string, unknown>;

        // Re-clamp confidenceGate and fundamentalsGate to maintain rejectBelow <= cautionBelow
        if (
          mergedState.confidenceGate &&
          typeof mergedState.confidenceGate === 'object' &&
          typeof (mergedState.confidenceGate as ConfidenceGate).cautionBelow === 'number' &&
          typeof (mergedState.confidenceGate as ConfidenceGate).rejectBelow === 'number'
        ) {
          const gate = mergedState.confidenceGate as ConfidenceGate;
          const clamped = clampGateThresholds(
            'cautionBelow',
            Math.max(0, Math.min(100, gate.cautionBelow)),
            Math.max(0, Math.min(100, gate.rejectBelow)),
          );
          gate.cautionBelow = clamped.cautionBelow;
          gate.rejectBelow = clamped.rejectBelow;
        }
        if (
          mergedState.fundamentalsGate &&
          typeof mergedState.fundamentalsGate === 'object' &&
          typeof (mergedState.fundamentalsGate as FundamentalsGate).cautionBelow === 'number' &&
          typeof (mergedState.fundamentalsGate as FundamentalsGate).rejectBelow === 'number'
        ) {
          const gate = mergedState.fundamentalsGate as FundamentalsGate;
          const clamped = clampGateThresholds(
            'cautionBelow',
            Math.max(0, Math.min(100, gate.cautionBelow)),
            Math.max(0, Math.min(100, gate.rejectBelow)),
          );
          gate.cautionBelow = clamped.cautionBelow;
          gate.rejectBelow = clamped.rejectBelow;
        }

        const serialized = JSON.stringify({
          state: mergedState,
          version: incoming.version ?? 24,
        });
        reportingStorage.setItem(key, serialized);
        lastCommittedSettings = mergedState;

        const hasDiffFromIncoming = !isSettingsEqual(mergedState, incoming.state);
        if (hasDiffFromIncoming) {
          useSettingsStore.setState(mergedState as Partial<SettingsState>, false);
        }
      } finally {
        isMerging = false;
      }
    },
    removeItem: (key: string): void => {
      reportingStorage.removeItem(key);
      lastCommittedSettings = getDefaultPersistedSettings();
    },
  };
}

const settingsStateStorage: StateStorage = createSettingsStateStorage();

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
      storage: createJSONStorage(() => settingsStateStorage),
      skipHydration: true,
      version: 24,
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

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e: StorageEvent) => {
    if (e.key === SETTINGS_STORAGE_KEY) {
      syncSettingsFromStorage(e.newValue);
    }
  });
}
