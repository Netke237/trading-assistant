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

/* ── Stop-vs-premium gate ──────────────────────────────────────────────────
 *
 * How much of the premium a long option loses if the underlying reaches its
 * structural stop. The point of the gate: on a cheap, low-delta contract a
 * far-away structural stop is often BEYOND the point of total premium loss,
 * so the "stop" is not a risk control at all — it is a marker for a position
 * that was already worthless before it got there.
 *
 * This is deliberately the cheap delta-linear estimate (same basis as
 * TradeCard's `structuralRR`), not a Black-Scholes reprice: it must be
 * computable from the scan payload alone, with no "Check structure" /
 * "Estimate" / "Compute Arithmetic Plan" round-trip, or it cannot fire early
 * enough to be a gate. It answers "is this stop roughly a full-premium loss?",
 * a question a 5% error does not change — not "what exactly will I lose",
 * which is what the exit-plan pipeline's repriced `stop.contractPrice` is for.
 */

/** Last-resort threshold, used only when no caller supplies one. The live value
 *  is per-horizon and comes from scoring_rules.yaml via
 *  `stopPremiumThresholdsStore` (which can also carry a per-run override) — this
 *  mirrors the Swing default so a caller that forgets to pass one degrades to a
 *  sane gate rather than to no gate.
 *
 *  ONE threshold, not two, and the verdict is PASS or CAUTION — never REJECT.
 *  The gate exists to sort candidates into "the stop is survivable on this
 *  contract" and "it isn't", so a screener can surface the cheaper-to-be-wrong
 *  trades up front; it is not a verdict on the trade and it blocks nothing.
 *  REJECT is the red badge in this design system, and a red badge on a
 *  contract the user may perfectly well want to trade reads as a refusal. */
export const STOP_PREMIUM_PASS_MAX_FRACTION = 0.8;

export interface StopPremiumRisk {
  stockMove: number;   // $ from the underlying's price to the stop
  delta:     number;   // |delta| actually used (floored, see below)
  rawLoss:   number;   // stockMove x delta, per share — UNCAPPED, may exceed premium
  loss:      number;   // min(rawLoss, premium) — the real per-share max loss
  premium:   number;   // per share
  fraction:  number;   // loss / premium, 0..1
  capped:    boolean;  // rawLoss >= premium — the stop is at/beyond total loss
  status:    Status;
}

/** Returns null when there is no meaningful answer: a non-positive premium, a
 *  stop sitting exactly at the current price (the card already renders that as
 *  "N/A (stop = price)"), or any non-finite input. */
export function stopPremiumRisk(
  stopPrice: number,
  stockPrice: number,
  delta: number,
  premium: number,
  thresholds?: { pass_max_fraction: number } | null,
): StopPremiumRisk | null {
  if (![stopPrice, stockPrice, delta, premium].every(Number.isFinite)) return null;
  if (premium <= 0) return null;

  // A caller passing a non-finite or out-of-range threshold gets the default
  // rather than a gate that silently passes everything. The per-run override in
  // Step 3 is user-editable, so this is a reachable input, not a defensive
  // nicety. Above 1.0 is meaningless (the loss caps at the premium, so nothing
  // could ever exceed it) and would make CAUTION unreachable.
  const passMax =
    thresholds && Number.isFinite(thresholds.pass_max_fraction)
      && thresholds.pass_max_fraction > 0 && thresholds.pass_max_fraction <= 1
      ? thresholds.pass_max_fraction : STOP_PREMIUM_PASS_MAX_FRACTION;

  const stockMove = Math.abs(stopPrice - stockPrice);
  if (stockMove === 0) return null;

  // Floored at 0.05 exactly as TradeCard's `structuralRR` does — a delta at or
  // near zero would otherwise report a rounding artifact as "no risk at the
  // stop", which is the most dangerous direction to be wrong in.
  const usedDelta = Math.max(Math.abs(delta), 0.05);
  const rawLoss = stockMove * usedDelta;
  // A long option cannot lose more than it cost, however far the stop sits.
  const loss = Math.min(rawLoss, premium);
  const fraction = loss / premium;
  // `capped` is a fact about the instrument, not a policy: the uncapped estimate
  // has run past what the contract cost. Kept separate from the threshold (which
  // moved to a single configurable pass line) because `fraction` is pinned at
  // 1.0 for every capped case and so can never distinguish "exactly a total
  // loss" from "twice a total loss" — the formatter surfaces that difference.
  const capped = rawLoss >= premium;

  // Two states by design — see STOP_PREMIUM_PASS_MAX_FRACTION. A contract whose
  // stop costs 85% of premium and one whose stop is twice the premium both read
  // CAUTION; the percentage in the badge and the "(uncapped $X)" tail carry the
  // magnitude, so nothing is hidden by collapsing the verdict.
  const status: Status = fraction < passMax ? 'PASS' : 'CAUTION';

  return { stockMove, delta: usedDelta, rawLoss, loss, premium, fraction, capped, status };
}

/** The gate's inputs on one line, so the verdict is auditable at a glance:
 *  "$11.50 away × Δ0.45 = $2.50 of $2.50 premium (uncapped $5.18)".
 *
 *  A formatter rather than inline JSX because interpolating this many values
 *  into markup splits it across text nodes — unreadable in the DOM and
 *  untestable by `getByText`. Same reasoning as
 *  `formatRecommendedContractSizeRaw`. The uncapped tail appears only when the
 *  cap actually bound, where it answers "how far past a total loss is this?" —
 *  a question `loss` alone cannot, since it is pinned to `premium`. */
export function formatStopPremiumRisk(r: StopPremiumRisk): string {
  const base =
    `$${r.stockMove.toFixed(2)} away × Δ${r.delta.toFixed(2)} = ` +
    `$${r.loss.toFixed(2)} of $${r.premium.toFixed(2)} premium`;
  return r.capped ? `${base} (uncapped $${r.rawLoss.toFixed(2)})` : base;
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

/** Formats a `recommendedContractSize` result for display as "N.dd" — always
 *  showing `size.recommended` as the whole part, by construction. Two
 *  earlier versions independently re-derived a floored/truncated decimal
 *  from `raw` (once via bare `toFixed`, once via a second, separately-
 *  epsilon-adjusted floor) — each fixed a real IEEE754 boundary disagreement
 *  with `recommended`, and each was later shown to have its own, narrower
 *  boundary where the two could still disagree, since two independent
 *  floating-point computations over the same input can be tuned to agree at
 *  every practically-reachable boundary but never proven to agree at every
 *  boundary. Deriving the decimal from `size.recommended` (already the
 *  authoritative, epsilon-corrected integer) instead of re-flooring `raw`
 *  a third time eliminates that whole bug class rather than patching the
 *  next boundary: the whole part can never disagree with `recommended`
 *  because it never comes from anywhere else. `Math.max(0, ...)` guards the
 *  fractional remainder against the same sub-epsilon negative noise
 *  `FLOOR_EPSILON` exists to absorb (e.g. raw fractionally *below*
 *  `recommended` by a few ULPs). */
export function formatRecommendedContractSizeRaw(size: RecommendedContractSize): string {
  const fractionCents = Math.min(99, Math.floor(Math.max(0, size.raw - size.recommended) * 100));
  return `${size.recommended}.${String(fractionCents).padStart(2, '0')}`;
}

export function checkTradeRisk(
  card: TradeCardData,
  proposedContracts: number,
  limits: RiskLimits,
  positions: PortfolioPosition[],
  dailyRecommendations: number,
  /** Feature 5 (Arithmetic Profit Target card) — the active PRE-trade
   *  max-loss override for this symbol, if the user has set one via the
   *  Arithmetic card. `undefined`/`null` inherits the global
   *  `maxLossPerTradePct` default, same as no override at all. */
  maxLossOverride?: MaxLossOverride | null,
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

  // Feature 5 — a per-trade PRE-trade override now can exist (set on the
  // Arithmetic card, passed in via `maxLossOverride` above), resolved through
  // the same shared `resolveMaxLossLimitDollar` the post-trade override
  // (PortfolioPosition.maxLossOverride, via the Portfolio EditDrawer) already
  // uses — one resolution function, not two subtly different ones. Absent an
  // override, this still falls back to the global default. Skipped entirely
  // when no exit plan has been computed yet (nothing to reprice against).
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
    lossLimitDollar = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride);
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
