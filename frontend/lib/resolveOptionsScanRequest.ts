/*
 * Pure options-mode scan-request resolution, extracted from RunScanButton's
 * onClick closure (Part 3 of the scheduler-timezone-awareness plan) so the
 * exact same request-building logic can be reused by the profile-based
 * scan-schedule resolver (scanScheduleResolve.ts) — one resolution path,
 * used by both the manual "Run Scan" button and scheduled entries, never a
 * second reimplementation.
 *
 * `buildOptionsScanRequestBody` takes an already-normalized `ResolvedScanContext`
 * (universe as a resolved string[], not a raw Universe pick/customRaw pair) —
 * the two callers differ only in how they produce that context (RunScanButton
 * reads live Zustand store state; the schedule resolver reads a saved
 * SearchProfile's captured fields), not in how the request body itself is
 * built from it.
 */
import type { Direction } from '@/types/domain';
import type { ConfidenceGate, FundamentalsGate, SpreadsConfig } from '@/lib/settingsStore';
import { atrMultForHorizon } from '@/lib/settingsStore';
import { normalizeWeightOverride, SCORE_WEIGHT_KEYS } from '@/lib/resolveStockScanRequest';
import { sanitizeHoldDays } from '@/lib/horizonPresets';
import { regimeGateOverridesFrom } from '@/lib/regimeGateOverrides';

export interface ResolvedScanContext {
  universe: string[];
  direction: Direction;
  /** Scoring horizon string, e.g. "Swing" — presetByKey(...).scoringHorizon. */
  horizon: string;
  /** The HOLDING preset key the trader picked — HorizonKey, e.g. "Annual".
   *  NOT `horizon` above. That one is collapsed to the three scoring horizons
   *  the scorer understands, so Quarterly/SemiAnnual/Annual all arrive as
   *  "Position"; the backend's repricing table is keyed on this one and would
   *  otherwise give a 200-day hold and a 20-day hold the same repricing time.
   *  /api/contracts/first-passage takes the same key under the same name — if
   *  the two ever send different spellings the Monte Carlo card and the Fixed %
   *  Ladder silently reprice at different horizons (resolve_reprice_days falls
   *  back to Swing on a dict miss without complaining). */
  horizonPreset: string;
  holdMinDays: number;
  holdMaxDays: number;
  /** Raw universe filter strings — '' means "not set". */
  minPriceRaw: string;
  maxPriceRaw: string;
  minCapRaw: string;
  maxCapRaw: string;
  capUnit: 'M' | 'B';
  scanOverrides: Record<string, number | boolean | string>;
  confidenceGate: ConfidenceGate;
  fundamentalsGate: FundamentalsGate;
  shortlistMaxCandidates: number;
  spreads: SpreadsConfig;
}

/** Matches backend `ScanRequest` (backend/app/schemas/__init__.py) field-for-field. */
export interface OptionsScanRequestBody {
  universe: string[];
  direction: string;
  horizon: string;
  /** ScanRequest.horizon_preset — the holding preset key, see ResolvedScanContext. */
  horizon_preset: string;
  overrides: Record<string, number | boolean | string>;
  hold_min_days?: number;
  hold_max_days?: number;
  min_price?: number;
  max_price?: number;
  min_cap_usd?: number;
  max_cap_usd?: number;
  cap_filter_units_version?: 1;
  confidence_caution_below?: number;
  confidence_reject_below?: number;
  confidence_atr_mult_target?: number;
  confidence_atr_mult_stop?: number;
  fundamentals_enabled?: boolean;
  fundamentals_caution_below?: number;
  fundamentals_reject_below?: number;
  fundamentals_de_reject?: number;
  fundamentals_caution_above?: number;
  fundamentals_reject_above?: number;
  /** Step-3 Regime Gate overrides. Added 2026-09-19 — Step 3 has shown these
   *  two in every screener mode since they were built, but only the STOCK scan
   *  request carried them, so setting "Headwind reject %" and running an
   *  options scan did nothing. The auto-trader now snapshots the same two onto
   *  the armed trade, so the options scan has to be applying them or the
   *  snapshot would carry a rule its own scan never used. */
  regime_headwind_caution_pct?: number;
  regime_headwind_reject_pct?: number;
  spread_width?: number;
  short_leg_delta?: number;
  iv_rank_threshold?: number;
  iv_abs_threshold: number;
  min_credit?: number;
  max_debit_pct?: number;
}

export function buildOptionsScanRequestBody(ctx: ResolvedScanContext): OptionsScanRequestBody {
  const filters: Record<string, number | boolean> = {};
  const minPrice = Number(ctx.minPriceRaw);
  const maxPrice = Number(ctx.maxPriceRaw);
  const minCap = Number(ctx.minCapRaw);
  const maxCap = Number(ctx.maxCapRaw);
  const capMultiplier = ctx.capUnit === 'B' ? 1e9 : 1e6;

  if (Number.isFinite(minPrice) && ctx.minPriceRaw !== '') filters.min_price = minPrice;
  if (Number.isFinite(maxPrice) && ctx.maxPriceRaw !== '') filters.max_price = maxPrice;
  if (Number.isFinite(minCap) && ctx.minCapRaw !== '') filters.min_cap_usd = minCap * capMultiplier;
  if (Number.isFinite(maxCap) && ctx.maxCapRaw !== '') filters.max_cap_usd = maxCap * capMultiplier;

  const scanOverrides = ctx.scanOverrides;
  // Confidence gate keys live in scanOverrides for Step-3 panel editing, but
  // they must go in top-level filters, NOT in the score overrides dict.
  const { confidence_caution_below: _cb, confidence_reject_below: _rb,
          confidence_atr_mult_target: _amt, confidence_atr_mult_stop: _ams,
          fundamentals_caution_above: _fca, fundamentals_reject_above: _fra,
          // Same reason as the six above: top-level request fields, not score
          // overrides. They were landing in `overrides` before 2026-09-19 —
          // harmless, because stock_scorer ignores keys it does not know, but
          // it meant the Step-3 value was being posted to a place nothing read.
          regime_headwind_caution_pct: _rhc, regime_headwind_reject_pct: _rhr,
          // Stocks-mode only (its Step-3 hint says the Options scan does not
          // read it). When it was forwarded, contract_validator's
          // _CONTRACT_OVERRIDES applied it as the contract hard-reject floor
          // in place of contract_rules.yaml's 55 (open question #57).
          min_stock_score: _mss,
          ...scoreOnlyOverrides } = scanOverrides;
  const normalizedScoreOverrides: Record<string, number | boolean | string> = Object.fromEntries(
    Object.entries(scoreOnlyOverrides).map(([k, v]) => [k, SCORE_WEIGHT_KEYS.has(k) ? normalizeWeightOverride(v) : v]),
  );
  const effectiveOverrides = { ...normalizedScoreOverrides, shortlist_max_candidates: ctx.shortlistMaxCandidates };

  const gate = ctx.confidenceGate;
  const cautionOv = scanOverrides.confidence_caution_below;
  const rejectOv = scanOverrides.confidence_reject_below;
  if (gate.enabled) {
    filters.confidence_caution_below = typeof cautionOv === 'number' ? cautionOv : gate.cautionBelow;
    filters.confidence_reject_below = typeof rejectOv === 'number' ? rejectOv : gate.rejectBelow;
  } else {
    filters.confidence_caution_below = 0;
    filters.confidence_reject_below = 0;
  }
  const hasFullAtrOverride =
    typeof scanOverrides.confidence_atr_mult_target === 'number' &&
    typeof scanOverrides.confidence_atr_mult_stop === 'number';
  const atrPair = hasFullAtrOverride
    ? { target: scanOverrides.confidence_atr_mult_target as number, stop: scanOverrides.confidence_atr_mult_stop as number }
    : atrMultForHorizon(gate, ctx.horizon);
  filters.confidence_atr_mult_target = atrPair.target;
  filters.confidence_atr_mult_stop = atrPair.stop;

  const fGate = ctx.fundamentalsGate;
  filters.fundamentals_enabled = fGate.enabled;
  filters.fundamentals_caution_below = fGate.cautionBelow;
  filters.fundamentals_reject_below = fGate.rejectBelow;
  filters.fundamentals_de_reject = fGate.deReject;

  if (typeof scanOverrides.fundamentals_caution_above === 'number') {
    filters.fundamentals_caution_above = scanOverrides.fundamentals_caution_above;
  }
  if (typeof scanOverrides.fundamentals_reject_above === 'number') {
    filters.fundamentals_reject_above = scanOverrides.fundamentals_reject_above;
  }

  // One reading, shared with the stocks resolver and the arm payload — see
  // lib/regimeGateOverrides.ts for why that matters.
  const regimeGate = regimeGateOverridesFrom(scanOverrides);
  if (regimeGate.regime_headwind_caution_pct !== undefined) {
    filters.regime_headwind_caution_pct = regimeGate.regime_headwind_caution_pct;
  }
  if (regimeGate.regime_headwind_reject_pct !== undefined) {
    filters.regime_headwind_reject_pct = regimeGate.regime_headwind_reject_pct;
  }

  const hold = sanitizeHoldDays(ctx.holdMinDays, ctx.holdMaxDays);

  return {
    cap_filter_units_version: 1,
    universe: ctx.universe,
    direction: ctx.direction,
    horizon: ctx.horizon,
    horizon_preset: ctx.horizonPreset,
    ...hold,
    overrides: effectiveOverrides,
    ...filters,
    spread_width: ctx.spreads.widthPoints,
    short_leg_delta: ctx.spreads.shortLegDelta,
    iv_rank_threshold: ctx.spreads.ivRankThreshold,
    iv_abs_threshold: ctx.spreads.ivAbsThreshold,
    min_credit: ctx.spreads.minCredit,
    max_debit_pct: ctx.spreads.maxDebitPctOfWidth,
  };
}
