/*
 * Open-position totals shared by every screen that sums the portfolio
 * (Portfolio footer, Dashboard card, the Dashboard / Portfolio rails and
 * RailQuickLook), and the per-row mark the exposure checks value a row at.
 *
 * NO-LIVE-QUOTE NLQ-1: a position GET /api/portfolio got no quote for carries
 * `quoteUnavailable`, and its `currentPrice` / `pnlDollar` are 0 defaults, not
 * a price. Adding them would silently understate Deployed and Open P&L, so the
 * totals leave such rows out and `unquotedNote` says how many were left out.
 */

import type { PortfolioPosition } from '@/types/domain';

export interface OpenTotals {
  /** Market value of the quoted positions (premium x 100 per option contract). */
  deployed: number;
  openPnL: number;
  /** openPnL / deployed in percent, 0 when nothing is deployed. */
  openPnLPct: number;
  winners: number;
  losers: number;
  /** Positions the totals cover. */
  quoted: number;
  /** Positions left out because they have no quote. */
  unquoted: number;
}

export function openTotals(positions: PortfolioPosition[]): OpenTotals {
  const quoted = positions.filter((p) => !p.quoteUnavailable);
  const deployed = quoted.reduce(
    (s, p) => s + p.currentPrice * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1),
    0,
  );
  const openPnL = quoted.reduce((s, p) => s + p.pnlDollar, 0);
  return {
    deployed,
    openPnL,
    openPnLPct: deployed > 0 ? (openPnL / deployed) * 100 : 0,
    winners: quoted.filter((p) => p.pnlDollar > 0).length,
    losers: quoted.filter((p) => p.pnlDollar < 0).length,
    quoted: quoted.length,
    unquoted: positions.length - quoted.length,
  };
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
