/*
 * Risk — pure helpers for capital-at-risk, exposure %, and portfolio metrics.
 */

import type {
  PortfolioPosition,
  RiskLimits,
  PortfolioRiskMetrics,
  TradeCardData,
  RiskCheckResult,
  MaxLossOverride,
} from '@/types/domain';
import type { Status } from '@/lib/status';
import { worstStatus } from '@/lib/status';

export function capitalAtRisk(mid: number, contracts: number): number {
  return mid * contracts * 100;
}

export function exposurePct(notional: number, portfolioValue: number): number {
  if (portfolioValue <= 0) return 0;
  return notional / portfolioValue;
}

export function checkInvalidation(invalidation: number | undefined): boolean {
  return invalidation !== undefined && invalidation > 0;
}

export const hasInvalidation = checkInvalidation;

export function positionMultiplier(p: PortfolioPosition): number {
  return p.contract.endsWith('|STOCK') ? 1 : 100;
}

export function totalNotional(positions: PortfolioPosition[]): number {
  return positions.reduce(
    (sum, p) => sum + p.currentPrice * positionMultiplier(p) * (p.contracts ?? 1),
    0,
  );
}

export function computePortfolioRiskMetrics(
  positions: PortfolioPosition[],
  limits: RiskLimits,
  dailyRecommendations: number,
): PortfolioRiskMetrics {
  const portfolioValue = limits.portfolioValue || 1;
  const notional = totalNotional(positions);
  const totalExposurePct = notional / portfolioValue;
  const concurrentPositions = positions.length;

  let largestConcentrationPct = 0;
  let largestConcentrationSymbol = '—';
  for (const p of positions) {
    const posNotional = p.currentPrice * positionMultiplier(p) * (p.contracts ?? 1);
    const posPct = posNotional / portfolioValue;
    if (posPct > largestConcentrationPct) {
      largestConcentrationPct = posPct;
      largestConcentrationSymbol = p.symbol;
    }
  }

  const statuses: Status[] = [];

  if (totalExposurePct > limits.maxTotalExposurePct) {
    statuses.push('REJECT');
  } else if (totalExposurePct > limits.maxTotalExposurePct * 0.8) {
    statuses.push('CAUTION');
  } else {
    statuses.push('PASS');
  }

  if (concurrentPositions >= limits.maxConcurrentPositions) {
    statuses.push('REJECT');
  } else if (concurrentPositions >= Math.floor(limits.maxConcurrentPositions * 0.8)) {
    statuses.push('CAUTION');
  }

  if (dailyRecommendations >= limits.maxDailyRecommendations) {
    statuses.push('REJECT');
  } else if (dailyRecommendations >= limits.maxDailyRecommendations * 0.8) {
    statuses.push('CAUTION');
  }

  const status = worstStatus(...statuses);

  return {
    totalExposurePct,
    concurrentPositions,
    dailyRecommendations,
    largestConcentrationPct,
    largestConcentrationSymbol,
    status,
  };
}

/** Feature C (exit-plan pipeline plan) — $ loss projected if the position is
 *  stopped out at the exit-plan pipeline's final stop: entry premium minus
 *  the stop-repriced contract price (floored at 0 — a repriced value at or
 *  above entry means the "stop" isn't actually a loss for this leg), times
 *  contracts. Options-only, mirroring the exit-plan pipeline itself. */
export function maxLossAtStop(
  entryPremium: number,
  stopContractPrice: number,
  contracts: number,
): number {
  return Math.max(0, entryPremium - stopContractPrice) * contracts * 100;
}

/** Resolves the $ threshold `maxLossAtStop` is checked against — a per-trade
 *  override (fixed dollar or percent of portfolioValue) if one is set,
 *  otherwise the global `maxLossPerTradePct` default. */
export function resolveMaxLossLimitDollar(
  portfolioValue: number,
  globalPct: number,
  override?: MaxLossOverride | null,
): number {
  if (override) {
    return override.mode === 'dollar' ? override.value : portfolioValue * override.value;
  }
  return portfolioValue * globalPct;
}

/** Risk-derived contract size: how many whole contracts the given risk
 *  budget affords at the given per-contract risk (typically the exit-plan
 *  pipeline's `maxLossAtStop(entryPremium, stop.contractPrice, 1)`), rounded
 *  down. Returns both the floored recommendation and the raw decimal so the
 *  UI can show "3 contracts (3.71 exact)" rather than just the rounded
 *  number. Returns null when there's no meaningful answer — a non-positive
 *  budget, or a non-positive per-contract risk (the stop reprices at or
 *  above entry premium, i.e. not actually a loss on this leg).
 *
 *  `recommended` floors `raw + FLOOR_EPSILON` rather than `raw` directly —
 *  `riskPerContract` is a subtraction of two dollar floats (entry premium
 *  minus a repriced stop price, see `maxLossAtStop`), which routinely lands
 *  a few ULPs off the exact cent value (e.g. 1.00 - 0.41 === 0.5900000000000001
 *  in IEEE754). At an exact-multiple budget that noise pushes `raw` to
 *  0.9999999999999999 instead of 1.0, silently under-recommending by a
 *  whole contract. The epsilon is far too small to change any real,
 *  intentionally-fractional recommendation. */
const FLOOR_EPSILON = 1e-9;

export interface RecommendedContractSize {
  raw: number;
  recommended: number;
}

export function recommendedContractSize(
  riskBudget: number,
  riskPerContract: number,
): RecommendedContractSize | null {
  if (riskBudget <= 0 || riskPerContract <= 0) return null;
  const raw = riskBudget / riskPerContract;
  return { raw, recommended: Math.floor(raw + FLOOR_EPSILON) };
}

/** Formats `recommendedContractSize`'s `raw` decimal for display, truncated
 *  (not rounded) to 2 places — plain `toFixed(2)` rounds, which can cross
 *  the same floor boundary `recommended` already floored down from (e.g.
 *  raw=0.9975 rounds to "1.00" while recommended is 0), producing a
 *  self-contradictory "0 contracts (1.00 exact)" display. Truncating keeps
 *  the two numbers consistent at that boundary — but `raw * 100` is itself
 *  a float multiplication that can land a few ULPs under an integer (e.g. a
 *  true 87 computed as 86.99999999999999), the same fp-noise class
 *  `FLOOR_EPSILON` exists to absorb, just one decimal place over. Applying
 *  the identical epsilon here (scaled ×100, same units as the truncation
 *  step) before flooring keeps this function's output consistent with
 *  `recommended` at every boundary, not just the one the plain-toFixed bug
 *  originally covered. */
export function formatRecommendedContractSizeRaw(raw: number): string {
  return (Math.floor(raw * 100 + FLOOR_EPSILON * 100) / 100).toFixed(2);
}

export function checkTradeRisk(
  card: TradeCardData,
  proposedContracts: number,
  limits: RiskLimits,
  positions: PortfolioPosition[],
  dailyRecommendations: number,
): RiskCheckResult {
  const reasons: string[] = [];
  let approved = true;

  const mid = card.contractDetails?.mid ?? 0;
  const car = capitalAtRisk(mid, proposedContracts);
  const singleExposure = exposurePct(car, limits.portfolioValue);
  const currentNotional = totalNotional(positions);
  const totalExposure = exposurePct(currentNotional + car, limits.portfolioValue);

  if (!checkInvalidation(card.exit.invalidation)) {
    reasons.push('missing_invalidation');
    approved = false;
  }

  if (singleExposure > limits.maxSingleTradeExposurePct) {
    reasons.push('single_trade_exposure_too_high');
    approved = false;
  }

  if (totalExposure > limits.maxTotalExposurePct) {
    reasons.push('total_exposure_limit_reached');
    approved = false;
  }

  if (positions.length >= limits.maxConcurrentPositions) {
    reasons.push('max_concurrent_positions_reached');
    approved = false;
  }

  if (positions.some((p) => p.symbol === card.symbol)) {
    reasons.push('duplicate_symbol');
    approved = false;
  }

  if (dailyRecommendations >= limits.maxDailyRecommendations) {
    reasons.push('max_daily_recommendations_reached');
    approved = false;
  }

  // No per-trade override exists pre-trade — that field lives on
  // PortfolioPosition, set only after the position is open — so this always
  // checks against the global default. Skipped entirely when no exit plan
  // has been computed yet (nothing to reprice against).
  let lossAtStop: number | undefined;
  let lossLimitDollar: number | undefined;
  const exitPlan = card.exit.exitPlan;
  if (exitPlan) {
    // `cd.mid` is the scan-time snapshot, while `exitPlan.stop.contractPrice`
    // came from a fresh quote fetched when "Compute Exit Plan" ran (see the
    // comment on TradeCard's computeExitPlan) — the two don't share a
    // baseline if premium moved between scan and click. Same limitation as
    // `capitalAtRisk(mid, ...)` above, which this mirrors deliberately
    // rather than inventing a second, inconsistent convention; `ExitPlan`
    // doesn't currently carry the fresh premium it was computed against, so
    // fixing this for real means threading that value through as a new
    // field, which is out of scope here.
    const entryPremium = card.contractDetails?.mid ?? 0;
    lossAtStop = maxLossAtStop(entryPremium, exitPlan.stop.contractPrice, proposedContracts);
    lossLimitDollar = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct);
    if (lossAtStop > lossLimitDollar) {
      reasons.push('max_loss_per_trade_exceeded');
      approved = false;
    }
  }

  return {
    approved,
    reasons,
    singleExposurePct: singleExposure,
    totalExposurePct: totalExposure,
    capitalAtRisk: car,
    maxLossAtStop: lossAtStop,
    maxLossLimitDollar: lossLimitDollar,
  };
}
