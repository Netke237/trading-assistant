import { defaultStockOverlay, stockExecutionIdentity, type StockExecutionRecord, type StockScanFeedback } from './stockExecutionSession';
// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, OptionContract, TradeCardData, DteWindow, SentimentData } from '@/types/domain';
import type { StockScanResult, PositionCardData, PreBreakoutResultRow, FibPullbackResultRow } from '@/types/stockDomain';
import type { StockScanRequestBody } from './resolveStockScanRequest';
import type { HorizonKey } from './horizonPresets';
import { migrateLegacyHorizon, presetByKey, horizonDisplayString, resolveParamsHorizon } from './horizonPresets';
import { stripLegacyIvFields, stripLegacyIvDetail } from './ivBasis';
import type { IvBasis } from './ivBasis';
import {
  // Aliased: the store has an ACTION named `clearCardPick` that calls this.
  clearCardPick as clearCardPickIn, clearPicksForSymbol, currentScanIdFor, emptyCardEdits,
  normalizeCardEdits, persistableCardEdits, writeCardEdit,
} from './cardEdits';
import type { CardEditField, CardEditMode, CardEditSlice, CardEditValue } from './cardEdits';

/** localStorage whose `setItem` cannot throw out of a `set()` (G2-12).
 *
 *  zustand v5's persist has no try/catch around `storage.setItem`, so a
 *  QuotaExceededError propagated out of EVERY `set()` on this store -- including
 *  `setCardEdit` inside a React event handler. The in-memory state had already
 *  changed and the previous blob survives either way; what the throw added was
 *  a crashed handler. It now warns instead. Reads and removes pass through.
 *  `lib/stockScan.ts` keeps its own guard around `runStockScan`. */
function quotaSafeLocalStorage(): Storage {
  const ls = localStorage;
  return {
    get length() { return ls.length; },
    clear: () => ls.clear(),
    key: (i: number) => ls.key(i),
    getItem: (k: string) => ls.getItem(k),
    removeItem: (k: string) => ls.removeItem(k),
    setItem: (k: string, v: string) => {
      try {
        ls.setItem(k, v);
      } catch (e) {
        console.warn(`[scanStore] could not persist '${k}' (storage full?); the previous save is kept`, e);
      }
    },
  };
}

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
  // The residual — exceptions and any reason matching no other bucket.
  other_rejected?:   number;
  // Undefined means ABSENT, not zero: a scan result persisted before these
  // existed has no value for them, and its `candidates` was counted before the
  // direction gate and the shortlist cap ran. The funnel hides a stage whose
  // counter is absent rather than rendering a zero it cannot vouch for.
  failed_direction?: number;
  failed_shortlist?: number;
  // The direction gate's "no data" removals (trend unmeasured), dropped right
  // after the pre-screen and before the chain fetch — apart from
  // failed_direction, a measured trend below the floor. Absent on a result
  // stored before it existed (its failed_direction then includes them).
  failed_direction_unmeasured?: number;
  /** The direction-conviction floor this scan applied; null/absent = exempt. */
  direction_min_trend?: number | null;
  candidates:        number;
}

export interface ScanResult {
  report_run_id?: string | null;
  report_generation?: number | null;
  report_persistence?: 'saved' | 'unavailable' | null;
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected: RejectedEntry[];
  pipeline?: OptionsPipeline;
  direction_banner?: string;
  dte_window?: DteWindow;
  /** The earnings/dividend window the scan's event rule applied (horizon
   *  default, replaced by any Step-3 override). Absent on results from before
   *  2026-09-29. Step 5 gates on it. */
  event_window?: { reject_days: number; caution_days: number; veto_days?: number | null };
  /** The contract-rule overrides the scan graded contracts with (Step-3
   *  liquidity, spread, delta, IV and min-stock-score rules; `{}` when it
   *  overrode none). Absent, or null from the backend, on results from before
   *  2026-09-29 or when the scan could not record them. Step 6 sends it to
   *  /api/contracts so its table grades with the trade cards' rules. */
  contract_rules?: Record<string, number> | null;
  /** The Reward/Risk overrides (rr_* keys) the scan priced its plans with;
   *  `{}` when it overrode none. Absent, or null, on results from before
   *  2026-10-02. Step 7's recompute-plan sends these, not live scanOverrides
   *  (STEP3-PARAM-REACH) -- see rrOverridesForPlan. */
  rr_overrides?: Record<string, number> | null;
  /** The Entry Quality overrides (entry_* keys) the scan priced its plans with;
   *  `{}` when it overrode none. Absent, or null, on results from before
   *  2026-10-21. Step 7's recompute-plan sends these (APP-AUDIT-B-ENTRY-OVERRIDES)
   *  -- see entryOverridesForPlan. */
  entry_overrides?: Record<string, number> | null;
  /** The request fields the result was produced from. Absent, or null, on
   *  results from before 2026-10-02. A result restored into an empty browser
   *  rebuilds its ScanContext from this (contextFromScanRequest). */
  request_context?: ScanRequestContext | null;
}

/** ScanResult.request_context -- the backend's ScanRequestContext. */
export interface ScanRequestContext {
  universe:       string[];
  direction:      string;
  horizon:        string;
  horizon_preset?: string | null;
  hold_min_days?:  number | null;
  hold_max_days?:  number | null;
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

function stripLegacyStopFromScanResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return value;
  return {
    ...value,
    candidates: value.candidates.map((candidate) => {
      if (!isRecord(candidate) || !isRecord(candidate.exit)) return candidate;
      // A blob written by piece 3 or later already carries a provenance block
      // for the stop it stored, so its `invalidation` is the resolved level
      // and must be left alone. Only a stop with no block behind it is the
      // legacy flat percentage. Idempotent, which matters: v13's own history
      // is that a branch was edited after shipping and had to be re-run under
      // a new version, and this one has to survive that.
      if (candidate.exit.finalStop != null) return candidate;
      const exit: Record<string, unknown> = { ...candidate.exit };
      exit.invalidation = null;
      return { ...candidate, exit };
    }),
  };
}

/** scanStore v18 (TRADING-REVIEW-PHASE-C-RR): an options result is kept only
 *  when EVERY candidate's R/R was computed on the full-premium basis. */
function discardPreFullPremiumScanResult(value: unknown): unknown {
  if (!isRecord(value) || !Array.isArray(value.candidates)) return value;
  const allFullPremium = value.candidates.every(
    (candidate) => isRecord(candidate) && isRecord(candidate.exit) && candidate.exit.rrRiskBasis === 'full_premium',
  );
  return allFullPremium ? value : null;
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
  stockExecutionGeneration: number;
  stockManualRunToken: number;
  stockExecution: Record<string, StockExecutionRecord>;
  stockBasketSources: Record<string, string | null>;
  stockAfterScanIntent: Record<string, boolean>;
  stockScanFeedback: StockScanFeedback;
  stockAfterScanOutcomes: Record<string, { token: number; symbol: string; status: 'saving' | 'ok' | 'pending' | 'rejected'; detail?: string; adjustedQty?: number }>;
  recordStockAfterScanOutcome: (key: string, outcome: ScanStoreState['stockAfterScanOutcomes'][string]) => void;
  beginStockManualRun: () => number;
  isStockExecutionCurrent: (identity: string) => boolean;
  patchStockExecution: (identity: string, patch: Partial<StockExecutionRecord>) => void;
  setStockAfterScanIntent: (symbol: string, enabled: boolean) => void;
  setStockScanFeedback: (token: number, feedback: StockScanFeedback) => void;
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
  /** Phase G piece 5 — the per-scan card-edit slices (spec §5). One per mode,
   *  each stamped with the `scan_id` its edits belong to.
   *
   *  NEVER READ THESE TWO FIELDS DIRECTLY. Go through `selectCardEdits(state,
   *  mode)` in lib/cardEdits.ts, which returns an EMPTY slice when the stamp
   *  does not match the scan currently in this store. A direct read skips that
   *  check and is the one defect this whole design exists to prevent — it would
   *  show a previous scan's typed entry limit, premium stop, invalidation level
   *  or picked target row on a card built from new prices. */
  optionsCardEdits: CardEditSlice;
  stocksCardEdits:  CardEditSlice;
  /** Write one card edit, stamped with the scan currently in the store. The
   *  stamp is derived here rather than passed in — see `currentScanIdFor`.
   *  Covers all five maps including `picks`, so the spec's `setCardPick(mode,
   *  key, pick)` is `setCardEdit(mode, 'picks', key, pick)`. */
  setCardEdit: <F extends CardEditField>(
    mode: CardEditMode, field: F, key: string, value: CardEditValue<F>,
  ) => void;
  /** Phase G piece 5, build step 3 — REMOVE one pick. `setCardEdit` cannot
   *  express this: `picks` is `Record<string, MethodPick>` precisely so that a
   *  present key means a human picked, so "no pick" is an absent key, not a
   *  stored null. See `clearCardPick` in lib/cardEdits.ts. */
  clearCardPick: (mode: CardEditMode, key: string) => void;
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
  /** A5 (decision A5-MIRROR-LAST-SCAN-RUN-2026-09-24). The exact request that
   *  produced `stockScanResult`, so the Analysis page replays the scan the user
   *  is looking at. Written ONLY by `setStockScanResult`, in the same `set()` as
   *  the result, so it can never pair with a different one: a writer that does
   *  not know the request (StoreHydration's backend recovery) stores null, and
   *  clearing the result clears it. StoreHydration may attach the backend's
   *  record afterwards, but only when its `scan_id` matches this result. */
  stockScanRequest:    StockScanRequestBody | null;
  setStockScanResult:  (r: StockScanResult | null, request?: StockScanRequestBody | null) => void;
  /** Why the last stock scan failed, as one human-readable line — null when
   *  the last run succeeded, was cleared at the start of a new run, or none
   *  has run yet. Written only by `runStockScan()` (lib/stockScan.ts).
   *
   *  Ephemeral and deliberately NOT in `partialize`: `scanState: 'FAILED'`
   *  IS persisted so the pill survives a reload, but the reason behind it
   *  describes one HTTP request this browser made in a session that is now
   *  over. Restoring it would caption a stale pill with a stale explanation
   *  (e.g. "backend unreachable" long after the backend came back). */
  stockScanError:      string | null;
  setStockScanError:   (message: string | null) => void;
  stockBasket:           PositionCardData[];
  addToStockBasket:      (card: PositionCardData) => void;
  removeFromStockBasket: (symbol: string) => void;
  clearStockBasket:      () => void;
  /** Explicitly wipe obsolete scan results and candidate artifacts when scan scope changes (e.g. custom tickers edited). */
  clearScanResults:      () => void;
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
  /** Market sentiment built from the regime response Step 1 already fetched.
   *  Written only by Step 1 (`fetchRegime`: null when a fetch starts, the
   *  reading when it answers, null when it fails); read by the Stocks Strategy
   *  page's Market Sentiment strip. Deliberately NOT in `partialize`: a stored
   *  sentiment would show stale numbers after a reload — the strip then shows
   *  "loads on Step 1" instead. */
  regimeSentiment:    SentimentData | null;
  setRegimeSentiment: (s: SentimentData | null) => void;
  preBreakoutResults: PreBreakoutResultRow[];
  setPreBreakoutResults: (results: PreBreakoutResultRow[]) => void;
  fibPullbackResults: FibPullbackResultRow[];
  setFibPullbackResults: (results: FibPullbackResultRow[]) => void;
}

export const useScanStore = create<ScanStoreState>()(
  persist(
    (set, get) => ({
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
            stockScanRequest:  null,
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
      regimeSentiment:    null,
      setRegimeSentiment: (s) => set({ regimeSentiment: s }),
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
      optionsCardEdits: emptyCardEdits(),
      stocksCardEdits:  emptyCardEdits(),
      setCardEdit: (mode, field, key, value) => {
        const s = get();
        const sliceKey = mode === 'options' ? 'optionsCardEdits' : 'stocksCardEdits';
        const next = writeCardEdit(s[sliceKey], currentScanIdFor(s, mode), field, key, value);
        // `writeCardEdit` returns the SAME object when nothing changed, and an
        // unchanged write then calls `set` NOT AT ALL. It matters that this
        // returns early rather than setting an empty partial: zustand's setState
        // notifies on every call whose argument is not the state object itself
        // (vanilla.js -- `Object.assign({}, state, {})` is a NEW object and the
        // listeners fire), so `set({})` would still churn a fresh top-level state
        // and re-render anything subscribing without a selector. The step-7 card
        // reports its whole overlay on every patch, so that is a render cascade
        // on every keystroke rather than a quiet store.
        if (next === s[sliceKey]) return;
        set({ [sliceKey]: next });
      },
      clearCardPick: (mode, key) => {
        const s = get();
        const sliceKey = mode === 'options' ? 'optionsCardEdits' : 'stocksCardEdits';
        const next = clearCardPickIn(s[sliceKey], currentScanIdFor(s, mode), key);
        // Same early return as `setCardEdit` above, for the same reason: a
        // no-op clear must not churn a fresh top-level state. It fires from an
        // effect (the card clearing a pick whose numbers left the screen), so
        // a `set` on every render would be a loop, not merely churn.
        if (next === s[sliceKey]) return;
        set({ [sliceKey]: next });
      },
      setPickedContract:    (symbol, contractId) => set(s => {
        // TEST 12. Switching the contract in step 6 drops the method pick made
        // against the contract being left behind: the pick names one target row
        // out of THAT contract's plan, and the card is about to show another
        // one's. Keying alone would hide the stale pick but not remove it, so it
        // would come back if the user switched back -- against numbers a
        // recompute has since replaced. The two typed-price caches are
        // deliberately NOT cleared here; see `clearPicksForSymbol`.
        // OPTIONS SLICE UNCONDITIONALLY, not `screenerMode`'s slice: step 6 is
        // an options-path route (the stocks path goes 4-stocks -> 5-strategy ->
        // 6-backtest and has no contracts at all), so this action only ever
        // fires under options. Reading `screenerMode` here would make the clear
        // depend on a toggle that has no bearing on which slice owns the pick.
        return {
          pickedContracts:  { ...s.pickedContracts, [symbol]: contractId },
          optionsCardEdits: clearPicksForSymbol(s.optionsCardEdits, symbol, contractId),
        };
      }),
      clearPickedContracts: () => set({ pickedContracts: {} }),
      setContractsBySymbol: (map) => set({ contractsBySymbol: map }),
      screenerMode:             'options',
      stockScanResult:          null,
      stockScanRequest:         null,
      stockScanError:           null,
      previousStockScanResult:  null,
      stockScanAt:              null,
      optionsScanAt:            null,
      stockBasket:           [],
      stockExecutionGeneration: 0,
      stockManualRunToken: 0,
      stockExecution: {},
      stockBasketSources: {},
      stockAfterScanIntent: {},
      stockScanFeedback: { error: null, notice: null },
      stockAfterScanOutcomes: {},
      recordStockAfterScanOutcome: (key, outcome) => set(state => ({ stockAfterScanOutcomes: { ...state.stockAfterScanOutcomes, [key]: outcome } })),
      beginStockManualRun: () => {
        const token = get().stockManualRunToken + 1;
        set({ stockManualRunToken: token, stockScanFeedback: { error: null, notice: null } });
        return token;
      },
      isStockExecutionCurrent: (identity) => {
        const state = get();
        try {
          const [, , symbol] = JSON.parse(identity);
          return typeof symbol === 'string' && stockExecutionIdentity(state, symbol) === identity;
        } catch { return false; }
      },
      patchStockExecution: (identity, patch) => {
        const state = get();
        // Retired numeric evidence cannot be resurrected by late analytics.
        // Started mutations retain their originating record for bookkeeping.
        const mutationKeys = ['placingType', 'orderId', 'orderMsg', 'adding', 'added', 'queued', 'err', 'warning'];
        if (!state.isStockExecutionCurrent(identity) && !Object.keys(patch).every(k => mutationKeys.includes(k))) return;
        const previous = state.stockExecution[identity] ?? {};
        let invalidated: Partial<StockExecutionRecord> = {};
        if (patch.overlay) {
          const symbol = JSON.parse(identity)[2];
          const candidate = state.stockScanResult?.candidates?.find(c => c.symbol === symbol);
          const old = previous.overlay ?? (candidate ? defaultStockOverlay(candidate) : undefined);
          const entryChanged = !old || old.entry !== patch.overlay.entry;
          const estimateChanged = entryChanged || !old || ['stop', 't1', 't2', 't3'].some(k =>
            old[k as keyof typeof old] !== patch.overlay![k as keyof typeof old]);
          if (estimateChanged) invalidated = {
            estimate: null, estimateErr: null, estimating: false,
            estimateRevision: (previous.estimateRevision ?? 0) + 1,
          };
          if (entryChanged) invalidated = { ...invalidated,
            plan: null, planErr: null, planning: false,
            structural: null, structuralErr: null, checkingStructure: false,
            entryRevision: (previous.entryRevision ?? 0) + 1,
            structuralRevision: (previous.structuralRevision ?? 0) + 1,
          };
        }
        set({ stockExecution: { ...state.stockExecution, [identity]: { ...previous, ...invalidated, ...patch } } });
      },
      setStockAfterScanIntent: (symbol, enabled) => set(state => ({
        stockAfterScanIntent: { ...state.stockAfterScanIntent, [symbol]: enabled },
      })),
      setStockScanFeedback: (token, feedback) => {
        if (get().stockManualRunToken === token) set({ stockScanFeedback: feedback });
      },
      activeStrategy:           null,
      lastOptionsScanStatus:    null,
      lastOptionsScanUpdatedAt: null,
      lastStockScanStatus:      null,
      lastStockScanUpdatedAt:   null,
      lastStockScanStrategy:    null,
      setScreenerMode:     (m) => set({ screenerMode: m }),
      setOptionsScanAt:    (at) => set({ optionsScanAt: at }),
      setStockScanResult: (r, request) => set(state => {
        const replacement = r !== state.stockScanResult;
        // Keep mutation ownership across scans; retire overlays/evidence and
        // picks even for equal-price/equal-id replacement result objects.
        const retained: Record<string, StockExecutionRecord> = {};
        if (replacement) for (const [identity, record] of Object.entries(state.stockExecution)) {
          if (record.placingType || record.orderId || record.adding || record.queued || record.added) {
            retained[identity] = {
              placingType: record.placingType, orderId: record.orderId, orderMsg: record.orderMsg,
              adding: record.adding, added: record.added, queued: record.queued,
              err: record.err, warning: record.warning,
            };
          }
        }
        if (replacement && r) {
          const generation = state.stockExecutionGeneration + 1;
          for (const candidate of r.candidates ?? []) {
            const identity = stockExecutionIdentity({ stockScanResult: r, stockExecutionGeneration: generation }, candidate.symbol);
            if (identity) retained[identity] = {
              validationAvailability: 'unavailable',
              provenance: { identity, symbol: candidate.symbol, strategy: candidate.strategy.strategy, direction: candidate.direction, request: request ?? null },
            };
          }
        }
        return {
          stockScanResult: r,
          stockScanRequest: r !== null ? (request === undefined && !replacement ? state.stockScanRequest : request ?? null) : null,
          previousStockScanResult: r !== null && replacement ? state.stockScanResult : state.previousStockScanResult,
          stockScanAt: r !== null ? toLocalWallClock() : state.stockScanAt,
          ...(replacement ? {
            stockExecutionGeneration: state.stockExecutionGeneration + 1,
            stockExecution: retained,
            stocksCardEdits: { ...state.stocksCardEdits, picks: {} },
          } : request !== undefined ? {
            stockExecution: Object.fromEntries(Object.entries(state.stockExecution).map(([identity, record]) => [identity,
              record.provenance && state.isStockExecutionCurrent(identity) ? { ...record, provenance: { ...record.provenance, request: request ?? null } } : record,
            ])),
          } : {}),
        };
      }),
      addToStockBasket:      (card) => set((s) => ({
        stockBasket: [...s.stockBasket.filter((c) => c.symbol !== card.symbol), card],
        stockBasketSources: { ...s.stockBasketSources, [card.symbol]: s.stockScanResult?.candidates?.includes(card) ? stockExecutionIdentity(s, card.symbol) : null },
      })),
      removeFromStockBasket: (symbol) => set((s) => ({
        stockBasket: s.stockBasket.filter((c) => c.symbol !== symbol),
        stockBasketSources: Object.fromEntries(Object.entries(s.stockBasketSources).filter(([key]) => key !== symbol)),
      })),
      clearStockBasket:      () => set({ stockBasket: [], stockBasketSources: {} }),
      clearScanResults:      () => set({
        previousRun:             null,
        previousStockScanResult: null,
        scanResult:              null,
        stockScanResult:         null,
        stockScanRequest:        null,
        stockScanAt:             null,
        optionsScanAt:           null,
        rejectedLog:             [],
        conflictedSymbols:       [],
      }),
      setStockScanError:   (message) => set({ stockScanError: message }),
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
        return quotaSafeLocalStorage();
      }),
      skipHydration: true,
       version: 19,
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
          // Phase A split `ivRank` (an IV rank) from `iv` (the absolute
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
        // NO BRANCH FOR PHASE B3, and that is a decision rather than an
        // oversight. B3 adds `stopCostPct`/`stopCostStatus` to each persisted
        // CANDIDATE, but the pair is purely additive and optional: a blob
        // written before B3 simply lacks it, `cardToRow` collapses the absent
        // value to null, and the ranking table renders "not computed — re-run
        // the scan". That is the behaviour the spec asks for (gate-basis spec
        // test 9), reached without touching the stored blob at all.
        //
        // The store's rule is to bump for a BREAKING shape change, and the
        // migrations above are the shape of one: v13/v14 both DELETE a field
        // whose stored value had become a wrong number under a new reading.
        // Nothing B3 added is wrong on an old blob -- it is merely missing,
        // and missing already renders honestly.
        if (version < 15) {
          // PIECE 3. `exit.invalidation` USED to be a flat percentage move off
          // the stock price -- the same -3% on every symbol in the universe.
          // It is now the resolved structural+ATR stop, and the field did not
          // change name. So a blob written before piece 3 holds a flat stop
          // under the resolved one's name: the same v13/v14 shape, a stored
          // value that became a wrong number under a new reading.
          //
          // NOT COSMETIC, and this is why it is deleted rather than left to
          // render as stale-but-harmless. `buildPaperPosition` stores that
          // field as `PortfolioPosition.stop` -- the level STOP_REACHED fires
          // against and the position card displays -- so a user placing an
          // order from a restored candidate would arm a -3% stop believing it
          // to be structural, up to 3x tighter than the level the rest of the
          // app now claims a position's stop is.
          //
          // Deleted, not guessed: the resolved stop needs a bar feed, which
          // the client does not have. Null renders "not computed — re-run the
          // scan" on the Invalidation field and fails `checkInvalidation`, so
          // the card cannot be sent until a fresh scan refills it -- or until
          // the user types a stop, which is threaded into the risk check for
          // exactly that reason (lib/risk.ts `resolvedInvalidation`).
          s = {
            ...s,
            scanResult: stripLegacyStopFromScanResult(s.scanResult),
            previousRun: stripLegacyStopFromScanResult(s.previousRun),
          };
        }
        if (version < 16) {
          // PHASE G piece 5, build step 2. The two card-edit slices are new
          // fields, so an older blob simply has neither. Added EMPTY rather
          // than left to `merge`'s spread, per CLAUDE.md's rule for a persisted
          // shape change -- and because "left to the default merge" is how a
          // field arrives as `undefined` on a store that declares it non-null.
          //
          // EMPTY, NOT MIGRATED, and there is nothing to migrate FROM. Before
          // this version these edits lived in four `useState` hooks on
          // step-7-trade-card/page.tsx and were never persisted at all, so no
          // stored blob has ever carried one. The empty slices land with
          // `scanId: null`, which reads as EMPTY and never as "matches
          // everything" -- see selectCardEdits.
          s = { ...s, optionsCardEdits: emptyCardEdits(), stocksCardEdits: emptyCardEdits() };
        }
        if (version < 17) {
          // A5. No stored result has a known request: null, which Analysis
          // reads as "use current settings, and say so" -- StoreHydration may
          // then attach the backend's record when its scan_id matches.
          s = { ...s, stockScanRequest: null };
        }
        if (version < 18) {
          // TRADING-REVIEW-PHASE-C-RR (review M7, D5). Options R/R now risks
          // the FULL premium: no protective stop order is ever placed. Every
          // `rrRatio` / `rrContribution` stored before that divided reward by
          // the premium stop (premium x 0.60) or the captured stock-stop loss,
          // under the same field names -- the v13-v15 shape, a stored value
          // that became a wrong number under a new reading. The header, the
          // rail and AlternativeContractRow would print it at least 1/0.6 too
          // high. Discarded rather than recomputed, as v13-v15 delete rather
          // than guess: the whole options result goes when any
          // candidate's `exit.rrRiskBasis` is not 'full_premium'; the user
          // re-runs the scan. previousRun goes by the same rule, and the
          // one-time loss of Δrank against it is accepted. The backend refuses
          // the same blobs (SCAN_RESULT_SCHEMA_VERSION 3), so StoreHydration
          // cannot refill them from /scan/last. stockScanResult is untouched.
          s = {
            ...s,
            scanResult: discardPreFullPremiumScanResult(s.scanResult),
            previousRun: discardPreFullPremiumScanResult(s.previousRun),
          };
        }
        if (version < 19) {
          // Durable report linkage is additive. Preserve legacy evidence and
          // mark unknown identities explicitly; never infer one from scan_id.
          const withReportIdentity = (result: unknown): unknown => {
            if (!result || typeof result !== 'object' || Array.isArray(result)) return result;
            const value = result as Record<string, unknown>;
            return {...value,report_run_id:value.report_run_id??null,report_generation:value.report_generation??null,report_persistence:value.report_persistence??null};
          };
          s = {...s,scanResult:withReportIdentity(s.scanResult),previousRun:withReportIdentity(s.previousRun),stockScanResult:withReportIdentity(s.stockScanResult),previousStockScanResult:withReportIdentity(s.previousStockScanResult)};
        }
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
        stockScanRequest:         state.stockScanRequest,
        previousStockScanResult:  state.previousStockScanResult,
        stockScanAt:              state.stockScanAt,
        optionsScanAt:            state.optionsScanAt,
        stockBasket:     state.stockBasket,
        lastOptionsScanStatus:    state.lastOptionsScanStatus,
        lastOptionsScanUpdatedAt: state.lastOptionsScanUpdatedAt,
        lastStockScanStatus:      state.lastStockScanStatus,
        lastStockScanUpdatedAt:   state.lastStockScanUpdatedAt,
        lastStockScanStrategy:    state.lastStockScanStrategy,
        // Phase G piece 5. THE STAMP AND THE PICKS ONLY -- `persistableCardEdits`
        // drops the three typed price maps and the max-loss override on the way
        // out. Kenneth's call on step 2's audit finding G2-5: the stamp detects
        // a NEW SCAN, not the passage of TIME, so persisting a typed entry
        // limit let it survive indefinitely under one `scan_id` and promise a
        // price against a mid that had since moved. Q3 asked for the PICK to
        // survive a reload, not the typed prices. In-session behaviour is
        // unchanged -- all four still live in the store while the tab is open.
        // Safe to persist at all ONLY because of the stamp: a restored slice is
        // readable just while its `scanId` still matches the restored result,
        // and StoreHydration restores that result. The fetched caches these sit
        // next to on the page (`estimatesByContract`, `structuralBySymbol`,
        // `exitPlanByContract`, `plansBySymbol`) are deliberately NOT here --
        // they are re-fetchable results rather than user edits, they are large,
        // and a restored Monte Carlo estimate would reintroduce exactly the
        // stale-vintage class that `estimateIsFresh` exists to suppress (§5).
        optionsCardEdits:         persistableCardEdits(state.optionsCardEdits),
        stocksCardEdits:          persistableCardEdits(state.stocksCardEdits),
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
        // Phase G piece 5 -- coerce both slices at the boundary rather than
        // trusting the blob. A slice that came back missing or malformed (an
        // older build, a hand-edited or truncated localStorage entry) would
        // otherwise reach `selectCardEdits` as `undefined` and throw, or reach
        // it with a non-string stamp. `normalizeCardEdits` guarantees five
        // objects and a string-or-null stamp; the stamp still gates every read.
        return {
          ...current,
          ...p,
          scanState: restoredState,
          // Same-version forged persisted fields are ignored too.
          stockExecutionGeneration: current.stockExecutionGeneration + 1,
          stockManualRunToken: current.stockManualRunToken + 1,
          stockExecution: {},
          stockBasketSources: {},
          stockAfterScanIntent: {},
          stockScanFeedback: { error: null, notice: null },
          stockAfterScanOutcomes: {},
          optionsCardEdits: normalizeCardEdits(p.optionsCardEdits),
          stocksCardEdits:  normalizeCardEdits(p.stocksCardEdits),
        };
      },
    },
  ),
);
