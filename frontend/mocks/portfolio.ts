/*
 * Portfolio mock — open positions. Phase 5 / Round 1.
 * DTE totals used by DTEProgressBar (status via dteStatus helper).
 * Now includes options-specific fields: IV rank, delta, theta, vega, contracts.
 */

import type { PortfolioPosition } from '@/types/domain';
import { dteStatus } from '@/lib/date';

function pos(p: Omit<PortfolioPosition, 'status'>): PortfolioPosition {
  return { ...p, status: dteStatus(p.dteRemaining, p.dteTotal) };
}

export const MOCK_PORTFOLIO: PortfolioPosition[] = [
  pos({
    symbol: 'AAPL', contract: 'AAPL 190C 05/16',
    direction: 'Bullish',
    entryDate: '2026-04-08', expiry: '2026-05-16',
    dteRemaining: 28, dteTotal: 38,
    entryPrice: 4.15, currentPrice: 5.02,
    pnlDollar: 870, pnlPct: 20.96,
    stop: 180.00, target: 198.00,
    ivRank: 42, delta: 0.58, theta: -0.08, vega: 0.22, contracts: 2,
  }),
  pos({
    symbol: 'NVDA', contract: 'NVDA 920C 04/25',
    direction: 'Bullish',
    entryDate: '2026-04-14', expiry: '2026-04-25',
    dteRemaining: 7, dteTotal: 11,
    entryPrice: 12.80, currentPrice: 14.25,
    pnlDollar: 725, pnlPct: 11.33,
    stop: 875.00, target: 960.00,
    ivRank: 71, delta: 0.62, theta: -0.24, vega: 0.18, contracts: 1,
  }),
  pos({
    symbol: 'MSFT', contract: 'MSFT 420C 06/20',
    direction: 'Bullish',
    entryDate: '2026-04-10', expiry: '2026-06-20',
    dteRemaining: 63, dteTotal: 71,
    entryPrice: 8.20, currentPrice: 8.85,
    pnlDollar: 325, pnlPct: 7.93,
    stop: 408.00, target: 445.00,
    ivRank: 28, delta: 0.54, theta: -0.05, vega: 0.34, contracts: 2,
  }),
  pos({
    symbol: 'META', contract: 'META 510C 05/02',
    direction: 'Bullish',
    entryDate: '2026-04-15', expiry: '2026-05-02',
    dteRemaining: 14, dteTotal: 17,
    entryPrice: 9.40, currentPrice: 8.10,
    pnlDollar: -390, pnlPct: -13.83,
    stop: 498.00, target: 540.00,
    ivRank: 55, delta: 0.46, theta: -0.14, vega: 0.26, contracts: 1,
  }),
  pos({
    symbol: 'TSLA', contract: 'TSLA 170P 04/22',
    direction: 'Bearish',
    entryDate: '2026-04-16', expiry: '2026-04-22',
    dteRemaining: 4, dteTotal: 6,
    entryPrice: 3.10, currentPrice: 3.78,
    pnlDollar: 340, pnlPct: 21.94,
    stop: 180.00, target: 160.00,
    ivRank: 82, delta: -0.52, theta: -0.31, vega: 0.12, contracts: 3,
  }),
];
