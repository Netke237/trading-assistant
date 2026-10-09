/*
 * Open-position totals shared by every screen that sums the portfolio
 * (Portfolio footer, Dashboard card, the Dashboard / Portfolio rails and
 * RailQuickLook).
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

/** The note shown beside a total that left positions out, or null when none were. */
export function unquotedNote(unquoted: number): string | null {
  if (unquoted <= 0) return null;
  return `Excludes ${unquoted} position${unquoted === 1 ? '' : 's'} without a quote`;
}
