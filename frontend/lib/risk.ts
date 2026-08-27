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
