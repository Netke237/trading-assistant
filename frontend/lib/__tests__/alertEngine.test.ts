import { scanPortfolio, type AlertPosition } from '@/lib/alertEngine';
import { useScanStore } from '@/lib/scanStore';

function pos(overrides: Partial<AlertPosition> = {}): AlertPosition {
  return {
    recId: 'r1',
    symbol: 'NVDA',
    contract: 'NVDA|100|2026-12-18|C',
    currentPrice: 90,
    entryPrice: 5,
    stop: 95,          // currentPrice 90 <= stop 95  => STOP_REACHED
    targets: [],
    dteRemaining: 30,
    dteTotal: 60,
    pnlPct: 0,
    ...overrides,
  };
}

describe('scanPortfolio', () => {
  it('fires STOP_REACHED even when the symbol is flagged as a scan conflict', () => {
    useScanStore.getState().setConflictedSymbols(['NVDA']);
    const out = scanPortfolio([pos()]);
    expect(out.some((a) => a.symbol === 'NVDA' && a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('fires PREMIUM_STOP when option is down 40%+', () => {
    const out = scanPortfolio([pos({ stop: 0, pnlPct: -45 })]);
    expect(out.some((a) => a.alertType === 'PREMIUM_STOP')).toBe(true);
  });
});