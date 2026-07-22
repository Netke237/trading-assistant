import { render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import type { TradeCardData } from '@/types/domain';

function makeCandidate(overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'TST',
    company: 'Test Co',
    price: 100,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 70,
    stockConfidence: 'PASS',
    stockBreakdown: {} as any,
    nextEventDays: null,
    nextEventLabel: null,
    contract: 'TST|100|2026-12-01|C',
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 10, ivPercentile: 10, dte: 90 },
    entry: {} as any,
    exit: {} as any,
    ...overrides,
  } as TradeCardData;
}

function setup(nextEventDays: number, horizon: string) {
  useScanStore.setState({
    scanResult: { candidates: [makeCandidate({ nextEventDays })], rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);
  useIvThresholdsStore.setState({ thresholds: {}, loaded: true } as any);
}

describe('Step 5 Volatility+Events — event proximity gate follows the scan horizon', () => {
  it('Position horizon: an event 8 days out is well inside the 30-day REJECT window, not a PASS', () => {
    setup(8, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('Position horizon: an event 45 days out is inside the 60-day CAUTION window but outside the 30-day REJECT window', () => {
    setup(45, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Position horizon: an event 78 days out is outside both windows -> PASS', () => {
    setup(78, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it("Swing horizon: an event 8 days out is outside Swing's 7-day REJECT window but inside its 21-day CAUTION window", () => {
    setup(8, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });
});
