// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, OptionContract, TradeCardData, DteWindow } from '@/types/domain';
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';
import type { HorizonKey } from './horizonPresets';
import { migrateLegacyHorizon, presetByKey, horizonDisplayString, resolveParamsHorizon } from './horizonPresets';
import { stripLegacyIvFields, stripLegacyIvDetail } from './ivBasis';
import type { IvBasis } from './ivBasis';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED' | 'PARTIAL' | 'CANCELLED';

/** Local wall-clock timestamp (offset-free) for an arbitrary date input,
 *  matching the convention every scanAt/stockScanAt consumer expects —
 *  mirrors RunScanButton's own nowLocalISO() (frontend/components/organisms/
 *  RunScanButton/index.tsx:27-34). Not imported from there since this store
 *  shouldn't depend on an organism. Exported so callers converting a real
 *  backend UTC-offset timestamp (e.g. StoreHydration's recovery path) reuse
 *  the same formatter instead of re-deriving it. */
export function toLocalWallClock(input: string | Date = new Date()): string {
  const d = typeof input === 'string' ? new Date(input) : input;
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export interface ScanContext {
  universe:      string;      // "SP500" | "NAS100" | ...
  direction:     Direction;
  /**
   * Derived display string, e.g. "Position (90–105d)" — kept for the ~15
   * existing consumers (TopBar, dashboard, ScanLog, stock-mode scan/analyze
   * requests) that parse or display this directly. Always starts with one of
   * 'Intraday' | 'Swing' | 'Position' (the scoring horizon), even for the
   * Position-scored long-dated presets — see horizonDisplayString().
   */
  horizon:       string;
  horizonPreset: HorizonKey;  // 'Swing' | 'Quarterly' | 'Custom' | ...
  holdMin:       number;      // calendar days
  holdMax:       number;      // calendar days
}

export interface RejectedEntry {
  symbol: string;
  reason: string;
  breakdown?: Record<string, number>;
}

export interface OptionsPipeline {
  scanned:           number;
  failed_data:       number;
  failed_pre_screen: number;
  no_chain:          number;
  failed_score:      number;
  failed_contracts:  number;
  candidates:        number;
}

export interface ScanResult {
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected: RejectedEntry[];
  pipeline?: OptionsPipeline;
  direction_banner?: string;
  dte_window?: DteWindow;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeLegacyPricingMethod(value: unknown): unknown {
  if (value === 'heston') return 'Heston repriced';
  if (value === 'delta-approx') return 'BS repriced (IV-derived)';
  if (value === 'manual') return 'Unavailable';
  return value;
}

/** v12 -> v13. Strips the pre-split `ivRank`/`ivPercentile` off a persisted
 *  scan result — see stripLegacyIvFields in lib/ivBasis.ts for why an
 *  unattributable figure is dropped rather than relabelled
 *  (PHASE-A-NULL-IVRANK-2026-09-06).
 *
 *  FOUR places inside a persisted candidate carry the figure: `contractDetails`
 *  (the block the Step 7 trade card renders and the user acts from) and each
 *  `alternatives` entry. `pickedContracts` is a Record<string, string> of
 *  contract IDs and carries no volatility figure at all; `contractsBySymbol`,
 *  which does, is deliberately not persisted (see `partialize`). The other
 *  two are the snake_case score-detail blocks `stockBreakdown.volDetail` and
 *  `contractBreakdown.ivDetail` (round 4 finding 1) — see stripLegacyIvDetail. */
/** ROUND 5 finding 2. The v14 pass must touch ONLY the two score-detail
 *  blocks. `stripLegacyIvFields` nulls camelCase `ivRank`, which on a blob
 *  written POST-split is a legitimate percentile from IBKR/tastytrade — so
 *  re-running the full v13 walk at v14 would destroy good data on exactly the
 *  stores this fix exists to reach. The detail blocks are safe because
 *  stripLegacyIvDetail discriminates on `iv_basis`; contractDetails carries no
 *  such marker (resolveIv derives the basis from which fields are present),
 *  so there is nothing there to discriminate on and it is left alone. */
/** ROUND 6 finding 2. Read the basis off the candidate's CONTRACT block, which
 *  the same per-symbol resolution produced, so an unlabelled-but-valid detail
 *  figure can be relabelled instead of destroyed. A blob written by a pre-split
 *  backend has no `iv` key at all (the field entered the schema at 71e317e5),
 *  and that absence is what still marks a figure as genuinely unattributable. */
function inferredBasisFor(candidate: Record<string, unknown>): IvBasis | undefined {
  const cd = candidate.contractDetails;
  if (!isRecord(cd) || !('iv' in cd)) return undefined;  // pre-split: no marker
  if (cd.ivRank != null) return 'rank';
  if (cd.iv != null) return 'absolute';
  return undefined;                                       // post-split, no reading
}

function stripLegacyIvDetailsFromScanResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return value;
  return {
    ...value,
    candidates: value.candidates.map((candidate) => {
      if (!isRecord(candidate)) return candidate;
      const out: Record<string, unknown> = { ...candidate };
      const inferred = inferredBasisFor(candidate);
      if (isRecord(candidate.stockBreakdown) && isRecord(candidate.stockBreakdown.volDetail)) {
        out.stockBreakdown = {
          ...candidate.stockBreakdown,
          volDetail: stripLegacyIvDetail(candidate.stockBreakdown.volDetail, inferred),
        };
      }
      if (isRecord(candidate.contractBreakdown) && isRecord(candidate.contractBreakdown.ivDetail)) {
        out.contractBreakdown = {
          ...candidate.contractBreakdown,
          ivDetail: stripLegacyIvDetail(candidate.contractBreakdown.ivDetail, inferred),
        };
      }
      return out;
    }),
  };
}

function stripLegacyIvFromScanResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return value;
  return {
    ...value,
    candidates: value.candidates.map((candidate) => {
      if (!isRecord(candidate)) return candidate;
      const out: Record<string, unknown> = { ...candidate };
      if (isRecord(candidate.contractDetails)) {
        out.contractDetails = stripLegacyIvFields(candidate.contractDetails);
      }
      if (Array.isArray(candidate.alternatives)) {
        out.alternatives = candidate.alternatives.map(stripLegacyIvFields);
      }
      // ROUND 4 finding 1. The same figure also sits in the two SCORE-DETAIL
      // blocks, in snake_case, where a missing `iv_basis` defaults to
      // 'absolute' and renders with a '%'. See stripLegacyIvDetail.
      if (isRecord(candidate.stockBreakdown) && isRecord(candidate.stockBreakdown.volDetail)) {
        out.stockBreakdown = {
          ...candidate.stockBreakdown,
          volDetail: stripLegacyIvDetail(candidate.stockBreakdown.volDetail),
        };
      }
      if (isRecord(candidate.contractBreakdown) && isRecord(candidate.contractBreakdown.ivDetail)) {
        out.contractBreakdown = {
          ...candidate.contractBreakdown,
          ivDetail: stripLegacyIvDetail(candidate.contractBreakdown.ivDetail),
        };
      }
      return out;
    }),
  };
}

function normalizePersistedScanResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return value;
  return {
    ...value,
    candidates: value.candidates.map((candidate) => {
      if (!isRecord(candidate) || !isRecord(candidate.exit) || !Array.isArray(candidate.exit.targets)) {
        return candidate;
      }
      return {
        ...candidate,
        exit: {
          ...candidate.exit,
          targets: candidate.exit.targets.map((target) => (
            isRecord(target)
              ? { ...target, pricingMethod: normalizeLegacyPricingMethod(target.pricingMethod) }
              : target
          )),
        },
      };
    }),
  };
}

/** Last-run metadata for a scan session (options or stock mode) — from
 *  GET /api/scan/last-run and /api/stock-scan/last-run. `status` means
 *  different things per mode: for options, "running"/"stopped" reflect the
 *  continuous-scan scheduler's on/off toggle, not a single in-flight scan;
 *  for stock mode, "running" means a scan request is actively executing.
 *  Render each with mode-appropriate copy — don't treat the two as
 *  interchangeable. */
export interface ScanSessionStatus {
  status: 'idle' | 'running' | 'complete' | 'stopped';
  updated_at: string | null;
  universe?: string[] | null;
  direction?: string | null;
  horizon?: string | null;
  strategy?: string | null;
  /** Options mode only. The scan_id of the result GET /api/scan/last returns at
   *  the same instant, so the fields above and the two thresholds below can be
   *  checked to belong to that result rather than to a scan that landed in
   *  between. Null in stock mode and when there is no last result. Read by
   *  backend/scripts/iv_basis_analysis.py; no UI consumes it today. */
  scan_id?: string | null;
  /** Options mode only. The IV cut-offs the last manual scan APPLIED (post
   *  pre-split seeding server-side). Null means unknown — never 50. */
  iv_abs_threshold?: number | null;
  iv_rank_threshold?: number | null;
}

interface ScanStoreState {
  scanState:  ScanState;
  /** ISO-ish local timestamp, e.g. "2026-04-21T09:42:00" (no TZ suffix). */
  scanAt:          string | null;
  /** Elapsed milliseconds for the last completed/failed scan. Not persisted. */
  scanDurationMs:  number | null;
  context:         ScanContext | null;
  regime:          Status;
  combinedRegime:  Status;
  scanResult:      ScanResult | null;
  /** Previous scan result for delta calculation (rankDelta / scoreDelta). */
  previousRun:     ScanResult | null;
  selectedSymbol:  string | null;
  conflictedSymbols: string[];
  rejectedLog: { symbol: string; reason: string }[];
  scanOverrides: Record<string, number | boolean | string>;
  pickedContracts:    Record<string, string>;
  contractsBySymbol:  Record<string, OptionContract[]>;
  setScanState:    (s: ScanState, at?: string, durationMs?: number) => void;
  setContext:      (c: ScanContext | null) => void;
  setRegime:       (r: Status) => void;
  setCombinedRegime: (r: Status) => void;
  setScanResult:   (r: ScanResult | null) => void;
  setPreviousRun:  (r: ScanResult | null) => void;
  setSelectedSymbol: (s: string) => void;
  setConflictedSymbols: (symbols: string[]) => void;
  setRejectedLog:  (entries: { symbol: string; reason: string }[]) => void;
  setScanOverrides: (o: Record<string, number | boolean | string>) => void;
  setPickedContract:    (symbol: string, contractId: string) => void;
  clearPickedContracts: () => void;
  setContractsBySymbol: (map: Record<string, OptionContract[]>) => void;
  screenerMode:        'options' | 'stocks' | 'prebreakout';
  setScreenerMode:     (m: 'options' | 'stocks' | 'prebreakout') => void;
  stockScanResult:          StockScanResult | null;
  /** Previous stock scan result for delta calculation (rankDelta / scoreDelta). */
  previousStockScanResult:  StockScanResult | null;
  /** ISO-ish local timestamp of the last completed stock scan. */
  stockScanAt:         string | null;
  /** ISO-ish local timestamp of the last completed options scan. */
  optionsScanAt:       string | null;
  setOptionsScanAt:    (at: string) => void;
  setStockScanResult:  (r: StockScanResult | null) => void;
  stockBasket:           PositionCardData[];
  addToStockBasket:      (card: PositionCardData) => void;
  removeFromStockBasket: (symbol: string) => void;
  clearStockBasket:      () => void;
  activeStrategy:      string | null;
  setActiveStrategy:   (s: string | null) => void;
  /** Last-run status for the options-mode scan session, as reported by the
   *  backend (GET /api/scan/last-run) — distinct from `scanAt`/`scanState`,
   *  which reflect this browser's own local scan lifecycle. */
  lastOptionsScanStatus:    string | null;
  lastOptionsScanUpdatedAt: string | null;
  /** Last-run status for the stock-mode scan session (GET /api/stock-scan/last-run). */
  lastStockScanStatus:      string | null;
  lastStockScanUpdatedAt:   string | null;
  /** Strategy used by the last completed/running stock scan, per the backend —
   *  distinct from `activeStrategy`, which reflects the user's *currently
   *  selected* strategy for the *next* scan. Do not conflate the two. */
  lastStockScanStrategy:    string | null;
  setLastOptionsScanMeta: (status: string | null, updatedAt: string | null) => void;
  setLastStockScanMeta:   (status: string | null, updatedAt: string | null, strategy: string | null) => void;
  /** Session-only — not persisted; cleared on page load. */
  regimeDirection:    'BULL' | 'BEAR' | 'MIXED' | null;
  setRegimeDirection: (d: 'BULL' | 'BEAR' | 'MIXED' | null) => void;
  preBreakoutResults: Array<{ symbol: string; confidence: number; direction: string; metrics: Record<string, number> }>;
  setPreBreakoutResults: (results: Array<{ symbol: string; confidence: number; direction: string; metrics: Record<string, number> }>) => void;
  fibPullbackResults: Array<{
    symbol: string;
    direction: string;
    fib_level_hit: string;
    fib_dist_pct: number | null;
    at_level: boolean;
    confidence: number;
  }>;
  setFibPullbackResults: (results: Array<{
    symbol: string;
    direction: string;
    fib_level_hit: string;
    fib_dist_pct: number | null;
    at_level: boolean;
    confidence: number;
  }>) => void;
}

export const useScanStore = create<ScanStoreState>()(
  persist(
    (set) => ({
      scanState:       'IDLE',
      scanAt:          null,
      scanDurationMs:  null,
      context:         null,
      regime:          'PENDING',
      combinedRegime:  'PENDING',
      scanResult:      null,
      previousRun:     null,
      selectedSymbol:  null,
      conflictedSymbols: [],
      rejectedLog: [],
      scanOverrides:   {},
      pickedContracts:    {},
      contractsBySymbol:  {},
      setScanState:    (s, at, durationMs) => set({ scanState: s, scanAt: at ?? null, scanDurationMs: durationMs ?? null }),
      setContext:      (c) => set((state) => {
        if (c === null) return { context: null };
        const prev = state.context;
        const contextChanged = !prev
          || prev.universe  !== c.universe
          || prev.direction !== c.direction
          || prev.horizon   !== c.horizon;
        return {
          context: c,
          ...(contextChanged ? {
            previousRun:             null,
            previousStockScanResult: null,
            // Stale results from the old universe/direction/horizon must not linger —
            // Step 4 would otherwise render the previous context's candidates with no
            // indicator that they no longer match the selected universe/direction.
            scanResult:        null,
            stockScanResult:   null,
            stockScanAt:       null,
            optionsScanAt:     null,
            rejectedLog:       [],
            conflictedSymbols: [],
          } : {}),
        };
      }),
      setRegime:       (r) => set({ regime: r }),
      setCombinedRegime: (r) => set({ combinedRegime: r }),
      regimeDirection:    null,
      setRegimeDirection: (d) => set({ regimeDirection: d }),
      preBreakoutResults: [],
      setPreBreakoutResults: (results) => set({ preBreakoutResults: results }),
      fibPullbackResults: [],
      setFibPullbackResults: (results) => set({ fibPullbackResults: results }),
      setScanResult:   (r) => set((state) => ({
        scanResult: r,
        previousRun: r !== null ? state.scanResult : state.previousRun,
      })),
      setPreviousRun:  (r) => set({ previousRun: r }),
      setSelectedSymbol: (s) => set({ selectedSymbol: s }),
      setConflictedSymbols: (symbols) => set({ conflictedSymbols: symbols }),
      setRejectedLog: (entries) => set({ rejectedLog: entries }),
      setScanOverrides: (o) => set({ scanOverrides: o }),
      setPickedContract:    (symbol, contractId) => set(s => ({ pickedContracts: { ...s.pickedContracts, [symbol]: contractId } })),
      clearPickedContracts: () => set({ pickedContracts: {} }),
      setContractsBySymbol: (map) => set({ contractsBySymbol: map }),
      screenerMode:             'options',
      stockScanResult:          null,
      previousStockScanResult:  null,
      stockScanAt:              null,
      optionsScanAt:            null,
      stockBasket:           [],
      activeStrategy:           null,
      lastOptionsScanStatus:    null,
      lastOptionsScanUpdatedAt: null,
      lastStockScanStatus:      null,
      lastStockScanUpdatedAt:   null,
      lastStockScanStrategy:    null,
      setScreenerMode:     (m) => set({ screenerMode: m }),
      setOptionsScanAt:    (at) => set({ optionsScanAt: at }),
      setStockScanResult:  (r) => set((state) => ({
        stockScanResult: r,
        previousStockScanResult: r !== null ? state.stockScanResult : state.previousStockScanResult,
        stockScanAt: r !== null ? toLocalWallClock() : state.stockScanAt,
      })),
      addToStockBasket:      (card) => set((s) => ({
        stockBasket: [...s.stockBasket.filter((c) => c.symbol !== card.symbol), card],
      })),
      removeFromStockBasket: (symbol) => set((s) => ({
        stockBasket: s.stockBasket.filter((c) => c.symbol !== symbol),
      })),
      clearStockBasket:      () => set({ stockBasket: [] }),
      setActiveStrategy:   (s) => set({ activeStrategy: s }),
      setLastOptionsScanMeta: (status, updatedAt) => set({
        lastOptionsScanStatus: status, lastOptionsScanUpdatedAt: updatedAt,
      }),
      setLastStockScanMeta: (status, updatedAt, strategy) => set({
        lastStockScanStatus: status, lastStockScanUpdatedAt: updatedAt, lastStockScanStrategy: strategy,
      }),
    }),
    {
      name: 'bamendjou-scan-store',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
       version: 14,
      migrate: (persistedState, version) => {
        // Branches must accumulate — no early returns — so a store at any old
        // version receives ALL intermediate field additions in one migration pass.
        let s = { ...((persistedState ?? {}) as Record<string, unknown>) };
        if (version < 2) s = { ...s, pickedContracts: {} };
        if (version < 3) s = { ...s, scanDurationMs: null };
        if (version < 4) s = { ...s, screenerMode: 'options', stockScanResult: null, activeStrategy: null };
        if (version < 5) s = { ...s, previousStockScanResult: null, stockBasket: [] };
        if (version < 6) s = { ...s, stockScanAt: null };
        if (version < 7) s = { ...s, optionsScanAt: null };
        if (version < 8) s = { ...s, preBreakoutResults: [] };
        if (version < 9) s = { ...s, fibPullbackResults: [] };
        if (version < 10) {
          const ctx = s.context as { universe?: string; direction?: string; horizon?: string } | null | undefined;
          s = {
            ...s,
            context: ctx
              ? (() => {
                  const legacy = migrateLegacyHorizon(ctx.horizon);
                  // Equivalent to the old ternary for every horizonPreset value (same
                  // reasoning as page.tsx's weightsKey/scoringHz and RunScanButton's horizon).
                  const scoringHz = presetByKey(resolveParamsHorizon(legacy.horizonPreset, legacy.holdMax)).scoringHorizon;
                  return {
                    universe:  ctx.universe  ?? 'SP500',
                    direction: ctx.direction ?? 'Bullish',
                    ...legacy,
                    horizon: horizonDisplayString(scoringHz, legacy.holdMin, legacy.holdMax),
                  };
                })()
              : null,
          };
        }
        if (version < 11) {
          s = {
            ...s,
            lastOptionsScanStatus: null,
            lastOptionsScanUpdatedAt: null,
            lastStockScanStatus: null,
            lastStockScanUpdatedAt: null,
            lastStockScanStrategy: null,
          };
        }
        if (version < 12) {
          s = {
            ...s,
            scanResult: normalizePersistedScanResult(s.scanResult),
            previousRun: normalizePersistedScanResult(s.previousRun),
          };
        }
        if (version < 13) {
          // Phase A split `ivRank` (a true percentile) from `iv` (the absolute
          // level). A blob stored before that carries one number of unknown
          // basis under the percentile's name, and rehydrating it prints
          // "IV rank 45" for a 45% absolute IV on the card the user acts from
          // — the very defect Phase A removes. Dropped, not guessed; the next
          // scan refills it. See lib/ivBasis.ts.
          s = {
            ...s,
            scanResult: stripLegacyIvFromScanResult(s.scanResult),
            previousRun: stripLegacyIvFromScanResult(s.previousRun),
          };
        }
        if (version < 14) {
          // ROUND 5 finding 2. The two SCORE-DETAIL blocks were added to the
          // `version < 13` branch above NINE COMMITS AFTER v13 shipped, so any
          // browser that ran this branch in between holds a blob already
          // stamped 13 — and zustand only calls migrate when the stored version
          // DIFFERS from the configured one, so that fix could never reach the
          // stores that needed it. Re-run under a new version.
          //
          // Safe on a blob written post-split, and safe to run twice:
          // stripLegacyIvDetail strips only where `iv_basis` is absent, which
          // no post-split writer emits. See lib/ivBasis.ts.
          s = {
            ...s,
            scanResult: stripLegacyIvDetailsFromScanResult(s.scanResult),
            previousRun: stripLegacyIvDetailsFromScanResult(s.previousRun),
          };
        }
        // NO v15 BRANCH FOR PHASE B3, and that is a decision rather than an
        // oversight. B3 adds `stopCostPct`/`stopCostStatus` to each persisted
        // CANDIDATE, but the pair is purely additive and optional: a blob
        // written before B3 simply lacks it, `cardToRow` collapses the absent
        // value to null, and the ranking table renders "not computed — re-run
        // the scan". That is the behaviour the spec asks for (gate-basis spec
        // test 9), reached without touching the stored blob at all.
        //
        // The store's rule is to bump for a BREAKING shape change, and the two
        // migrations above are the shape of one: v13/v14 both DELETE a field
        // whose stored value had become a wrong number under a new reading.
        // Nothing here is wrong on an old blob -- it is merely missing, and
        // missing already renders honestly. Bumping anyway would push every
        // user's store through a migration pass that changes nothing, and
        // would put a no-op branch in this chain for the next reader to
        // mistake for a real one.
        return s;
      },
      partialize: (state) => ({
        scanResult:      state.scanResult,
        previousRun:     state.previousRun,
        context:         state.context,
        scanAt:          state.scanAt,
        scanDurationMs:  state.scanDurationMs,
        pickedContracts: state.pickedContracts,
        // Persist terminal states so the COMPLETED/FAILED pill survives a restart.
        // SCANNING / IDLE are never persisted — they'd be stale after reload.
        scanState:       state.scanState,
        screenerMode:             state.screenerMode,
        activeStrategy:           state.activeStrategy,
        stockScanResult:          state.stockScanResult,
        previousStockScanResult:  state.previousStockScanResult,
        stockScanAt:              state.stockScanAt,
        optionsScanAt:            state.optionsScanAt,
        stockBasket:     state.stockBasket,
        lastOptionsScanStatus:    state.lastOptionsScanStatus,
        lastOptionsScanUpdatedAt: state.lastOptionsScanUpdatedAt,
        lastStockScanStatus:      state.lastStockScanStatus,
        lastStockScanUpdatedAt:   state.lastStockScanUpdatedAt,
        lastStockScanStrategy:    state.lastStockScanStrategy,
      }),
      merge: (persisted, current) => {
        // `persisted` is undefined on a first visit (nothing in localStorage yet)
        // and whenever the stored blob is absent. Dereferencing it directly threw
        // a TypeError that zustand swallows in its internal catch, so
        // onFinishHydration never fired and persist.hasHydrated() stayed false
        // forever — which left ScreenerStepGate's grace timer to bounce every
        // deep step URL to step-1-regime. Guard exactly as `migrate` above does.
        const p = (persisted ?? {}) as Partial<ScanStoreState>;
        const lastState = p.scanState;
        // Restore only terminal states; an in-progress state from before a crash
        // or server restart is meaningless — reset to IDLE.
        const restoredState: ScanState =
          lastState === 'COMPLETED' || lastState === 'PARTIAL' || lastState === 'FAILED'
            ? lastState
            : 'IDLE';
        return { ...current, ...p, scanState: restoredState };
      },
    },
  ),
);
