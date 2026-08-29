import { render, screen, fireEvent, act } from '@testing-library/react';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useAlertStore } from '@/lib/alertStore';
import { api } from '@/lib/api';
import { runStockScan } from '@/lib/stockScan';

jest.mock('@/lib/api', () => ({
  api: {
    postScanBody: jest.fn(),
  },
}));

jest.mock('@/lib/stockScan', () => ({ runStockScan: jest.fn().mockResolvedValue(null) }));

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));

const mockPostScanBody = api.postScanBody as jest.MockedFunction<typeof api.postScanBody>;

function resetStores() {
  useScanStore.setState({
    scanState: 'IDLE',
    scanAt: null,
    context: null,
    scanResult: null,
    conflictedSymbols: [],
    screenerMode: 'options',
    activeStrategy: null,
  } as any);
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

    mockPostScanBody.mockResolvedValue({
      scan_id: 'SCAN-1',
      timestamp: '2026-05-10T10:00:00',
      candidates: [
        { symbol: 'AAPL', company: 'Apple', price: 185, direction: 'Bullish', status: 'PASS' as const, stockScore: 80, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 80, pullback: 70, trigger: 75, event: 60, volatility: 65 }, contract: 'AAPL|180|2026-05-15|C', contractScore: 75, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 70, delta: 80, ivAttractiveness: 70, liquidity: 80, spread: 75 }, entry: { limit: 5.0, maxFill: 5.5, orderType: 'Limit' as const }, exit: { invalidation: 170, premiumStop: 3.0, timeStopDays: 5, target: 195, targets: [] }, rrRatio: 2.5, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
        { symbol: 'MSFT', company: 'Microsoft', price: 420, direction: 'Bullish', status: 'PASS' as const, stockScore: 70, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 70, pullback: 60, trigger: 65, event: 50, volatility: 55 }, contract: 'MSFT|420|2026-05-15|C', contractScore: 65, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 60, delta: 70, ivAttractiveness: 60, liquidity: 70, spread: 65 }, entry: { limit: 8.0, maxFill: 8.5, orderType: 'Limit' as const }, exit: { invalidation: 410, premiumStop: 5.0, timeStopDays: 5, target: 435, targets: [] }, rrRatio: 2.0, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
      ],
      rejected: [],
    } as any);

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

  it('runs a stock scan when screenerMode is stocks and a strategy is active', async () => {
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as Partial<ReturnType<typeof useScanStore.getState>>);

    render(<RunScanButton />);
    fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));

    expect(runStockScan).toHaveBeenCalledWith('pullback_ema');
  });

  it('shows a toast and does not call runStockScan when Stocks mode has no activeStrategy selected (M6)', async () => {
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: null } as any);
    const addToastSpy = jest.spyOn(useAlertStore.getState(), 'addToast');

    render(<RunScanButton />);
    fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));

    expect(addToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ recId: 'STRATEGY-NOT-SELECTED', alertType: 'SCAN_FAILED' })
    );
    expect(runStockScan).not.toHaveBeenCalled();
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

    mockPostScanBody.mockResolvedValue({
      scan_id: 'SCAN-2',
      timestamp: '2026-05-10T11:00:00',
      candidates: [
        { symbol: 'AAPL', company: 'Apple', price: 185, direction: 'Bullish', status: 'PASS' as const, stockScore: 80, stockConfidence: 'PASS' as const, stockBreakdown: { trend: 80, pullback: 70, trigger: 75, event: 60, volatility: 65 }, contract: 'AAPL|180|2026-05-15|C', contractScore: 75, contractConfidence: 'PASS' as const, contractBreakdown: { dteFit: 70, delta: 80, ivAttractiveness: 70, liquidity: 80, spread: 75 }, entry: { limit: 5.0, maxFill: 5.5, orderType: 'Limit' as const }, exit: { invalidation: 170, premiumStop: 3.0, timeStopDays: 5, target: 195, targets: [] }, rrRatio: 2.5, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const },
      ],
      rejected: [],
    } as any);

    render(<RunScanButton />);

    const button = screen.getByRole('button', { name: /run scan/i });

    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    const conflicted = useScanStore.getState().conflictedSymbols;
    expect(conflicted).toHaveLength(0);
  });

  it('sends Step-3 bearish-fundamentals slider values as top-level body fields for Options scans', async () => {
    useScanStore.setState({
      screenerMode: 'options',
      context: { direction: 'Bearish', horizonPreset: 'Swing', holdMin: 5, holdMax: 15, universe: 'SP500' },
      scanOverrides: { fundamentals_caution_above: 65, fundamentals_reject_above: 85 },
    } as any);
    mockPostScanBody.mockResolvedValue({ scan_id: 'S1', timestamp: 't', candidates: [], rejected: [] } as any);

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan/i }));
      await Promise.resolve();
    });

    const [body] = mockPostScanBody.mock.calls[0];
    expect(body.fundamentals_caution_above).toBe(65);
    expect(body.fundamentals_reject_above).toBe(85);
    expect(body.overrides).not.toHaveProperty('fundamentals_caution_above');
    expect(body.overrides).not.toHaveProperty('fundamentals_reject_above');
  });
});

describe('RunScanButton — hold days', () => {
  beforeEach(() => {
    resetStores();
    jest.clearAllMocks();
  });

  it('sends hold days and the derived scoring horizon, never min_dte/max_dte overrides', async () => {
    useScanStore.setState({
      context: {
        universe: 'SP500', direction: 'Bullish',
        horizon: 'Position (120–370d)', horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
      },
    } as any);
    mockPostScanBody.mockResolvedValue({
      scan_id: 'SCAN-1', timestamp: '2026-07-10T10:00:00', candidates: [], rejected: [],
    } as any);

    render(<RunScanButton />);
    const button = screen.getByRole('button', { name: /run scan/i });
    await act(async () => {
      fireEvent.click(button);
    });

    const [body] = mockPostScanBody.mock.calls[0];
    expect(body.horizon).toBe('Position');   // scoringHorizonForHold(185) === 'Position'
    expect(body.hold_min_days).toBe(60);
    expect(body.hold_max_days).toBe(185);
    expect(body.overrides).not.toHaveProperty('min_dte');
    expect(body.overrides).not.toHaveProperty('max_dte');
  });
});

describe('RunScanButton — confidence ATR override both-or-neither', () => {
  beforeEach(() => {
    resetStores();
    jest.clearAllMocks();
    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
  });

  async function runAndGetBody() {
    mockPostScanBody.mockResolvedValue({
      scan_id: 'SCAN-ATR', timestamp: '2026-07-10T10:00:00', candidates: [], rejected: [],
    } as any);
    render(<RunScanButton />);
    const button = screen.getByRole('button', { name: /run scan/i });
    await act(async () => {
      fireEvent.click(button);
    });
    const [body] = mockPostScanBody.mock.calls[0];
    return body;
  }

  it('sends the full Settings default ATR pair for the resolved horizon when no override is set', async () => {
    useScanStore.setState({
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing' },
    } as any);
    const body = await runAndGetBody();
    expect(body.confidence_atr_mult_target).toBe(3.0); // swing default
    expect(body.confidence_atr_mult_stop).toBe(1.5);
  });

  it('ignores a lone confidence_atr_mult_stop override (without a target) rather than sending a mismatched pair', async () => {
    // Regression: resolving target/stop independently would send the lone
    // override's stop paired with the Settings default's target, silently
    // producing a pair the user never actually configured together and
    // bypassing the backend's both-or-neither guard.
    useScanStore.setState({
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing' },
      scanOverrides: { confidence_atr_mult_stop: 0.5 },
    } as any);
    const body = await runAndGetBody();
    expect(body.confidence_atr_mult_target).toBe(3.0); // full fallback to swing default, not mixed
    expect(body.confidence_atr_mult_stop).toBe(1.5);
  });

  it('uses both override values together when both target and stop are set', async () => {
    useScanStore.setState({
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing' },
      scanOverrides: { confidence_atr_mult_target: 2.5, confidence_atr_mult_stop: 0.5 },
    } as any);
    const body = await runAndGetBody();
    expect(body.confidence_atr_mult_target).toBe(2.5);
    expect(body.confidence_atr_mult_stop).toBe(0.5);
  });
});
