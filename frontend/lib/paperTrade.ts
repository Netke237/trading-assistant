import type { PortfolioPosition } from '@/types/domain';

export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction:    'Bullish',
    entryPrice:   price,
    contracts:    shares,
    entryDate:    today,
    expiry:       '',
    stop:         0,
    targets:      [],
    dteTotal:     0,
    dteRemaining: 0,
    status:       'PENDING',
    recId:        'PAPER-' + Date.now().toString(36),
    currentPrice: price,
    pnlDollar:    0,
    pnlPct:       0,
    source:       'paper',
  };
}
