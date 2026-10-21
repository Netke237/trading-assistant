import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { reportingLocalStorage } from './reportingLocalStorage';
import { assertStrategyScanOverrides } from './strategyScanValidation';

/**
 * STOCKS-HORIZON-T1 H5: the strategy fields are OVERRIDES of the backend
 * horizon profile (GET /api/config/strategy-profiles). `null` = follow the
 * profile for the scan's direction x params horizon; a value = an explicit
 * override sent on the request. The other fields (backtest gate, event
 * filter, shortlist cap) are plain settings, always sent.
 */
export interface ScanParams {
  pullbackTolerancePct: number | null;   // fraction: 0.08 = 8%
  pullbackEmaPeriod:    number | null;   // EMA to pull back to (e.g. 50)
  pullbackTrendEma:     number | null;   // trend-confirmation EMA (e.g. 100)
  pullbackMaType:       'EMA' | 'SMA' | null;
  maCrossoverFast:      number | null;   // fast MA period
  maCrossoverSlow:      number | null;   // slow MA period
  maCrossoverLookback:  number | null;   // bars
  breakoutVolumeMult:   number | null;   // multiplier
  rsiPeriod:            number | null;   // RSI look-back period
  rsiOversold:          number | null;   // RSI oversold threshold (bullish rule)
  rsiOverbought:        number | null;   // RSI overbought threshold (bearish rule)
  rsiTrendSma:          number | null;   // trend-confirmation SMA (e.g. 200)
  requireChoppyRegime:  boolean | null;  // mean-reversion RSI only fires in Choppy regime
  btMinTrades:          number;   // count
  btMinWinRate:         number;   // fraction: 0.30 = 30%
  eventFilter: 'include' | 'avoid' | 'only_pre_event';
  stockShortlistMax:    number;   // max stock candidates returned
  meanReversionVariants:    string[] | null;  // active signal variants for mean_reversion_multi
  meanReversionMinConfirm:  number | null;    // min confirmations required
  vwapLookback:             number | null;    // VWAP lookback bars
  vwapDeviationPct:         number | null;    // VWAP deviation fraction (0.02 = 2%)
}

/** The ScanParams fields that override the backend horizon profile. */
export const OVERRIDE_FIELDS = [
  'pullbackTolerancePct', 'pullbackEmaPeriod', 'pullbackTrendEma', 'pullbackMaType',
  'maCrossoverFast', 'maCrossoverSlow', 'maCrossoverLookback', 'breakoutVolumeMult',
  'rsiPeriod', 'rsiOversold', 'rsiOverbought', 'rsiTrendSma', 'requireChoppyRegime',
  'meanReversionVariants', 'meanReversionMinConfirm', 'vwapLookback', 'vwapDeviationPct',
] as const;
export type OverrideField = typeof OVERRIDE_FIELDS[number];

/** Every override field null: follow the profile. */
export const NO_OVERRIDES: Pick<ScanParams, OverrideField> = Object.fromEntries(
  OVERRIDE_FIELDS.map((f) => [f, null]),
) as unknown as Pick<ScanParams, OverrideField>;

/** What a saved search profile stores: the plain settings plus only the
 *  overrides that were set (absent = follow the profile). */
export type SavedScanParams = Omit<ScanParams, OverrideField> & Partial<Pick<ScanParams, OverrideField>>;

const DEFAULTS: ScanParams = {
  ...NO_OVERRIDES,
  btMinTrades:          5,
  btMinWinRate:         0.45,
  eventFilter:          'include' as const,
  stockShortlistMax:    10,
};

interface ScanParamsStore extends ScanParams {
  setParam: <K extends keyof ScanParams>(key: K, value: ScanParams[K]) => void;
  resetToDefaults: () => void;
  /** Restore a saved profile's params: its overrides, every other override
   *  field back to "follow the profile". */
  loadParams: (p: SavedScanParams) => void;
  setMeanReversionVariants:   (v: string[] | null) => void;
  setMeanReversionMinConfirm: (v: number | null) => void;
  setVwapLookback:            (v: number | null) => void;
  setVwapDeviationPct:        (v: number | null) => void;
}

/**
 * Branches must accumulate — no early returns — mirrors scanStore.ts's migrate():
 * a store frozen at any old version must receive every intermediate field
 * addition in one migration pass, not just the single lowest-numbered branch
 * that would have matched an early-return waterfall.
 *
 * Exception: the btMinWinRate 0.30 (forced at the original v7->v8 transition)
 * -> 0.45 (corrected at the original v8->v9 transition) pair is deliberately
 * NOT made cumulative across every v<8/v<9 — it's guarded on the ORIGINAL
 * persisted version being exactly 7 (force) / exactly 8 (correction) so a
 * store frozen further back (e.g. v3) that never actually went through the
 * v7/v8 bug window keeps its real value untouched, instead of the correction
 * silently overwriting a value the user set deliberately at some later
 * version. This preserves the old code's exact narrow targeting for this one
 * field while making every other field addition genuinely cumulative.
 */
export function migrateScanParams(state: unknown, v: number): ScanParams {
  let s: Record<string, unknown> = { ...DEFAULTS, ...(state as Partial<ScanParams>) };

  if (v < 4) {
    s = { ...s, pullbackMaType: 'EMA' as const };
  }
  if (v < 5) {
    s = { ...s, eventFilter: 'include' as const };
  }
  if (v < 6) {
    s = { ...s, pullbackTolerancePct: 0.08, btMinTrades: 5 };
  }
  if (v < 7) {
    s = { ...s, stockShortlistMax: 10 };
  }
  if (v === 7) {
    s = { ...s, btMinWinRate: 0.30 };
  }
  if (v === 8 && s.btMinWinRate === 0.30) {
    s = { ...s, btMinWinRate: 0.45 };
  }
  if (v < 10) {
    s = { ...s, requireChoppyRegime: false };
  }
  if (v < 11) {
    s = {
      ...s,
      meanReversionVariants:   ['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily'],
      meanReversionMinConfirm: 2,
      vwapLookback:            20,
      vwapDeviationPct:        0.02,
    };
  }
  if (v < 12) {
    // STOCKS-HORIZON-T1 H5: strategy fields became overrides of the backend
    // horizon profile. Every stored value was a copy of an old hardcoded
    // default (or a hand edit of one) that would mask the profile on every
    // scan, so all of them reset to "follow the profile".
    s = { ...s, ...NO_OVERRIDES };
  }

  return s as unknown as ScanParams;
}

export const useScanParamsStore = create<ScanParamsStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setParam: (key, value) => {
        if (key === 'pullbackTolerancePct' || key === 'maCrossoverLookback' || key === 'breakoutVolumeMult') {
          if (value !== null && value !== undefined) {
            assertStrategyScanOverrides({ [key]: value });
          }
        }
        set({ [key]: value });
      },
      resetToDefaults: () => set({ ...DEFAULTS }),
      loadParams: (p) => {
        assertStrategyScanOverrides({
          pullbackTolerancePct: p.pullbackTolerancePct,
          maCrossoverLookback: p.maCrossoverLookback,
          breakoutVolumeMult: p.breakoutVolumeMult,
        });
        set({ ...NO_OVERRIDES, ...p });
      },
      setMeanReversionVariants:   (v) => set({ meanReversionVariants: v }),
      setMeanReversionMinConfirm: (v) => set({ meanReversionMinConfirm: v }),
      setVwapLookback:            (v) => set({ vwapLookback: v }),
      setVwapDeviationPct:        (v) => set({ vwapDeviationPct: v }),
    }),
    {
      name: 'bamendjou:scan-params',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return reportingLocalStorage('Strategy scan parameters (this browser)');
      }),
      skipHydration: true,
      version: 12,
      migrate: migrateScanParams,
    },
  ),
);

export { DEFAULTS as SCAN_PARAM_DEFAULTS };
