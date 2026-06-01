import { scanPortfolio, type AlertPosition } from '@/lib/alertEngine';
import { useScanStore } from '@/lib/scanStore';

function makePosition(overrides: Partial<AlertPosition> = {}): AlertPosition {
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

// Keep the old alias for the existing test
const pos = makePosition;

describe('scanPortfolio', () => {
  it('fires STOP_REACHED even when the symbol is flagged as a scan conflict', () => {
    useScanStore.getState().setConflictedSymbols(['NVDA']);
    const out = scanPortfolio([pos()]);
    expect(out.some((a) => a.symbol === 'NVDA' && a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('fires PREMIUM_STOP when pnlPct crosses the 60% stop threshold', () => {
    const position = makePosition({ pnlPct: -65 });  // beyond -60% threshold
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(true);
  });

  it('does NOT fire PREMIUM_STOP when loss is below threshold', () => {
    const position = makePosition({ pnlPct: -50 });  // not yet at -60%
    const results = scanPortfolio([position], { premiumStopPct: 0.60 });
    expect(results.some(r => r.alertType === 'PREMIUM_STOP')).toBe(false);
  });
});
