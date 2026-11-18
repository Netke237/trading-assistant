/*
 * PORTFOLIO-NUMBERS (#657) shared fixture: the three open positions live
 * GET /api/portfolio returned on 2026-11-17 (plan §2), one option contract
 * each. CMG and NCLH are quoted; BMY has no quote (`quoteUnavailable`), so
 * its 0 price / P&L are defaults and it has no greeks.
 *
 * Lives outside `__tests__` so Jest does not collect it as a suite. Returns
 * fresh objects on every call so a test can mutate its copy freely.
 */

import type { PortfolioPosition } from '@/types/domain';

export function portfolio20261117(): PortfolioPosition[] {
  return [
    {
      symbol: 'CMG', contract: 'CMG|40|2027-06-17|C', direction: 'Bullish',
      entryDate: '2026-11-10', expiry: '2027-06-17', dteRemaining: 212, dteTotal: 219,
      entryPrice: 2.90, currentPrice: 3.03, currentStockPrice: 36.06,
      delta: 0.4452, theta: -0.011,
      pnlDollar: 13, pnlPct: 4.48,
      stop: null, targets: [], status: 'PENDING', contracts: 1, recId: 'REC-CMG',
    },
    {
      symbol: 'NCLH', contract: 'NCLH|20|2027-06-17|C', direction: 'Bullish',
      entryDate: '2026-11-10', expiry: '2027-06-17', dteRemaining: 212, dteTotal: 219,
      entryPrice: 2.41, currentPrice: 1.91, currentStockPrice: 17.70,
      delta: 0.478, theta: -0.0071,
      pnlDollar: -50, pnlPct: -20.75,
      stop: null, targets: [], status: 'PENDING', contracts: 1, recId: 'REC-NCLH',
    },
    {
      symbol: 'BMY', contract: 'BMY|67|2027-03-19|C', direction: 'Bullish',
      entryDate: '2026-11-10', expiry: '2027-03-19', dteRemaining: 122, dteTotal: 129,
      entryPrice: 5.78, currentPrice: 0, currentStockPrice: 60.95,
      pnlDollar: 0, pnlPct: 0, quoteUnavailable: true,
      stop: null, targets: [], status: 'PENDING', contracts: 1, recId: 'REC-BMY',
    },
  ];
}
