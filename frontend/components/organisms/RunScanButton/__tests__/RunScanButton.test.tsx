import { render, screen, fireEvent, act } from '@testing-library/react';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    postScan: jest.fn(),
  },
}));

const mockPostScan = api.postScan as jest.MockedFunction<typeof api.postScan>;

function resetStores() {
  useScanStore.setState({
    scanState: 'IDLE',
    scanAt: null,
    context: null,
    scanResult: null,
    conflictedSymbols: [],
  });
  usePortfolioStore.setState({ positions: [] });
}

describe('RunScanButton — conflict suppression wiring', () => {
  beforeEach(() => {
    resetStores();
    jest.clearAllMocks();
  });

  it('populates conflictedSymbols when scan candidate overlaps portfolio', async () => {
    usePortfolioStore.getState().addPosition({
      recId: 'REC-TEST-1',
      symbol: 'AAPL',
      contract: 'AAPL|180|2026-05-15|C',
      direction: 'Bullish',
      entryPrice: 5.0,
      currentPrice: 5.0,
      pnlDollar: 0,
      pnlPct: 0,
      stop: 170,
      targets: [],
      status: 'PENDING',
      entryDate: '2026-05-10',
      expiry: '2026-05-15',
      dteRemaining: 5,
      dteTotal: 10,
    } as any);

    mockPostScan.mockResolvedValue({
      scan_id: 'SCAN-1',
      timestamp: '2026-05-10T10:00:00',
      candidates: [
        { symbol: 'AAPL', company: 'Apple', price: 185, direction: 'Bullish', status: 'PASS' as const, stockScore: 80, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 80, pullback: 70, trigger: 75, event: 60, volatility: 65 }, contract: 'AAPL|180|2026-05-15|C', contractScore: 75, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 70, delta: 80, ivAttractiveness: 70, liquidity: 80, spread: 75 }, entry: { limit: 5.0, maxFill: 5.5, orderType: 'Limit' as const }, exit: { invalidation: 170, premiumStop: 3.0, timeStopDays: 5, target: 195, targets: [] }, rrRatio: 2.5, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
        { symbol: 'MSFT', company: 'Microsoft', price: 420, direction: 'Bullish', status: 'PASS' as const, stockScore: 70, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 70, pullback: 60, trigger: 65, event: 50, volatility: 55 }, contract: 'MSFT|420|2026-05-15|C', contractScore: 65, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 60, delta: 70, ivAttractiveness: 60, liquidity: 70, spread: 65 }, entry: { limit: 8.0, maxFill: 8.5, orderType: 'Limit' as const }, exit: { invalidation: 410, premiumStop: 5.0, timeStopDays: 5, target: 435, targets: [] }, rrRatio: 2.0, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
      ],
      rejected: [],
    });

    render(<RunScanButton />);

    const button = screen.getByRole('button', { name: /run scan/i });

    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    const conflicted = useScanStore.getState().conflictedSymbols;
    expect(conflicted).toContain('AAPL');
    expect(conflicted).not.toContain('MSFT');
    expect(conflicted).toHaveLength(1);
  });

  it('clears conflictedSymbols when no overlap exists', async () => {
    usePortfolioStore.getState().addPosition({
      recId: 'REC-TEST-2',
      symbol: 'GOOGL',
      contract: 'GOOGL|140|2026-05-15|C',
      direction: 'Bullish',
      entryPrice: 3.0,
      currentPrice: 3.0,
      pnlDollar: 0,
      pnlPct: 0,
      stop: 135,
      targets: [],
      status: 'PENDING',
      entryDate: '2026-05-10',
      expiry: '2026-05-15',
      dteRemaining: 5,
      dteTotal: 10,
    } as any);

    mockPostScan.mockResolvedValue({
      scan_id: 'SCAN-2',
      timestamp: '2026-05-10T11:00:00',
      candidates: [
        { symbol: 'AAPL', company: 'Apple', price: 185, direction: 'Bullish', status: 'PASS' as const, stockScore: 80, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 80, pullback: 70, trigger: 75, event: 60, volatility: 65 }, contract: 'AAPL|180|2026-05-15|C', contractScore: 75, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 70, delta: 80, ivAttractiveness: 70, liquidity: 80, spread: 75 }, entry: { limit: 5.0, maxFill: 5.5, orderType: 'Limit' as const }, exit: { invalidation: 170, premiumStop: 3.0, timeStopDays: 5, target: 195, targets: [] }, rrRatio: 2.5, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
      ],
      rejected: [],
    });

    render(<RunScanButton />);

    const button = screen.getByRole('button', { name: /run scan/i });

    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    const conflicted = useScanStore.getState().conflictedSymbols;
    expect(conflicted).toHaveLength(0);
  });
});
