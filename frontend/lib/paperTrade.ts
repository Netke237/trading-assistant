import type { Direction, PortfolioPosition } from '@/types/domain';
import type { PositionCardData } from '@/types/stockDomain';

// The "why was this bought" snapshot for the stocks path — attached once at
// buy time so it survives independent of later scans overwriting scanStore.
export function stockCardSnapshotOf(c: PositionCardData): Record<string, unknown> {
  return {
    stock_score: c.stock_score,
    stock_status: c.stock_status,
    strategy: c.strategy,
    backtest: c.backtest,
    confidence: c.confidence,
    confidence_text: c.confidence_text,
    sector_rs_pct: c.sector_rs_pct,
    fundamentals: c.fundamentals,
  };
}

export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
  direction: Direction,
  snapshot?: Record<string, unknown>,
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction,
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
    tradeCardSnapshot: snapshot,
  };
}
