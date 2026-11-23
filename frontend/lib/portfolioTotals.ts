/*
 * Open-position totals shared by every screen that sums the portfolio
 * (Portfolio footer, Dashboard card, the Dashboard / Portfolio rails and
 * RailQuickLook), and the per-row mark the exposure checks value a row at.
 *
 * NO-LIVE-QUOTE NLQ-1: a position GET /api/portfolio got no quote for carries
 * `quoteUnavailable`, and its `currentPrice` / `pnlDollar` are 0 defaults, not
 * a price. Adding them would silently understate Deployed and Open P&L, so the
 * totals leave such rows out and `unquotedNote` says how many were left out.
 *
 * PORTFOLIO-NUMBERS (#657): `openPnLPct` is the return on COST BASIS (open P&L
 * over what the quoted rows cost to open), the same base as each row's P&L %.
 * The Portfolio footer ("Return on cost") and the Dashboard "Portfolio" card's
 * "Return" stat both read it. `aggregateGreeks` sums the rail's greeks per
 * position as greek x multiplier x contracts. The multiplier is the local
 * `|STOCK ? 1 : 100` rule (same as `positionMultiplier` in lib/risk.ts, which
 * cannot be imported here: risk.ts imports `exposureMark` from this file).
 */

import type { PortfolioPosition } from '@/types/domain';

export interface OpenTotals {
  /** Market value of the quoted positions (premium x 100 per option contract). */
  deployed: number;
  openPnL: number;
  /** Σ entryPrice × multiplier × contracts over the quoted rows. */
  costBasis: number;
  /** openPnL / costBasis in percent (return on cost), 0 when costBasis ≤ 0. */
  openPnLPct: number;
  winners: number;
  losers: number;
  /** Positions the totals cover. */
  quoted: number;
  /** Positions left out because they have no quote. */
  unquoted: number;
}

function multiplier(p: PortfolioPosition): number {
  return p.contract.endsWith('|STOCK') ? 1 : 100;
}

export function openTotals(positions: PortfolioPosition[]): OpenTotals {
  const quoted = positions.filter((p) => !p.quoteUnavailable);
  const deployed = quoted.reduce(
    (s, p) => s + p.currentPrice * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1),
    0,
  );
  const costBasis = quoted.reduce((s, p) => s + p.entryPrice * multiplier(p) * (p.contracts ?? 1), 0);
  const openPnL = quoted.reduce((s, p) => s + p.pnlDollar, 0);
  return {
    deployed,
    openPnL,
    costBasis,
    openPnLPct: costBasis > 0 ? (openPnL / costBasis) * 100 : 0,
    winners: quoted.filter((p) => p.pnlDollar > 0).length,
    losers: quoted.filter((p) => p.pnlDollar < 0).length,
    quoted: quoted.length,
    unquoted: positions.length - quoted.length,
  };
}

/** One position's theta in dollars per day (theta × multiplier × contracts),
 *  or null when its theta is not a finite number (null and absent included). */
export function positionThetaDollars(p: PortfolioPosition): number | null {
  const theta = p.theta as number | null | undefined;
  if (theta == null || !Number.isFinite(theta)) return null;
  return theta * multiplier(p) * (p.contracts ?? 1);
}

export interface GreekTotals {
  /** Σ delta × multiplier × contracts (share-equivalent delta); null when no
   *  position has a delta or a theta. */
  deltaShares: number | null;
  /** Σ theta in dollars per day; null when no position has a delta or a theta. */
  thetaDollars: number | null;
  /** Σ delta × multiplier × contracts × underlying price over the rows that
   *  have both a finite delta and an underlying price > 0; null when none do. */
  deltaDollars: number | null;
  /** Positions left out of `deltaDollars`. */
  deltaDollarsExcluded: number;
}

/** The underlying price "Δ in dollars" values a row at: the stock's own price
 *  for a `|STOCK` row (NaN when it has no quote), else the live underlying. */
function underlyingPrice(p: PortfolioPosition): number | undefined {
  if (p.contract.endsWith('|STOCK')) return p.quoteUnavailable ? NaN : p.currentPrice;
  return p.currentStockPrice;
}

export function aggregateGreeks(positions: PortfolioPosition[]): GreekTotals {
  const hasGreeks = positions.some((p) => p.delta != null || p.theta != null);
  const deltaShares = hasGreeks
    ? positions.reduce((s, p) => s + (p.delta ?? 0) * multiplier(p) * (p.contracts ?? 1), 0)
    : null;
  const thetaDollars = hasGreeks
    ? positions.reduce((s, p) => s + (positionThetaDollars(p) ?? 0), 0)
    : null;
  const included: { p: PortfolioPosition; delta: number; underlying: number }[] = [];
  for (const p of positions) {
    const delta = p.delta as number | null | undefined;
    const underlying = underlyingPrice(p);
    if (delta == null || !Number.isFinite(delta)) continue;
    if (underlying == null || !Number.isFinite(underlying) || underlying <= 0) continue;
    included.push({ p, delta, underlying });
  }
  const deltaDollars = included.length
    ? included.reduce((s, r) => s + r.delta * multiplier(r.p) * (r.p.contracts ?? 1) * r.underlying, 0)
    : null;
  return {
    deltaShares,
    thetaDollars,
    deltaDollars,
    deltaDollarsExcluded: positions.length - included.length,
  };
}

/** The note shown beside "Δ in dollars" when it left positions out, or null. */
export function deltaDollarsNote(excluded: number): string | null {
  if (excluded <= 0) return null;
  return `Δ in dollars excludes ${excluded} position${excluded === 1 ? '' : 's'} without delta or underlying price`;
}

/** The price an EXPOSURE / notional computation values one open position at.
 *
 *  The live mark when there is one; otherwise the entry price (cost basis) --
 *  for a row flagged `quoteUnavailable`, and defensively for any row whose
 *  `currentPrice` is not a finite number > 0. Never 0: a $0 mark understates
 *  exposure, and the pre-trade limit check (`checkTradeRisk`) would then
 *  approve an order past `maxTotalExposurePct`. Unlike the DISPLAY totals
 *  above, which leave such a row out and say so, a limit check must count it.
 *  Used by lib/risk.ts (`totalNotional`, `computePortfolioRiskMetrics`) and
 *  lib/riskStore.ts (`computeMetrics`). */
export function exposureMark(p: PortfolioPosition): number {
  if (!p.quoteUnavailable && Number.isFinite(p.currentPrice) && p.currentPrice > 0) return p.currentPrice;
  return p.entryPrice;
}

/** The note shown beside a total that left positions out, or null when none were. */
export function unquotedNote(unquoted: number): string | null {
  if (unquoted <= 0) return null;
  return `Excludes ${unquoted} position${unquoted === 1 ? '' : 's'} without a quote`;
}

/** One open option's loss if the underlying reaches its exit-plan stop, in
 *  dollars; null for a stock, a row with no exit plan, or `entryPrice <= 0`
 *  (a data glitch, not a real 0-loss trade).
 *
 *  The single implementation behind `riskAtStopOf` (lib/risk.ts, the editor's
 *  rule) and `riskAtStopTotal`. It lives HERE, not in risk.ts, because risk.ts
 *  imports `exposureMark` from this file and a back-import would be a cycle.
 *  The arithmetic is the same as `maxLossAtStop` (lib/risk.ts); risk.test.ts
 *  pins their equality. */
export function riskAtStopDollars(p: PortfolioPosition, contractsOverride?: number): number | null {
  if (!p.exitPlan || p.contract.endsWith('|STOCK') || !(p.entryPrice > 0)) return null;
  const contracts = contractsOverride ?? p.contracts ?? 1;
  return Math.max(0, p.entryPrice - p.exitPlan.stop.contractPrice) * contracts * 100;
}

export interface RiskAtStopTotal {
  total: number;
  /** Positions with a risk figure. */
  priced: number;
  /** Positions without one (no exit plan, or a stock). A quote is not needed. */
  unpriced: number;
}

export function riskAtStopTotal(positions: PortfolioPosition[]): RiskAtStopTotal {
  let total = 0;
  let priced = 0;
  for (const p of positions) {
    const r = riskAtStopDollars(p);
    if (r == null) continue;
    total += r;
    priced += 1;
  }
  return { total, priced, unpriced: positions.length - priced };
}
