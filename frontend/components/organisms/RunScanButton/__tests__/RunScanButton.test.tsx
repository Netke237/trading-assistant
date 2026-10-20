import { useUniverseStore } from '@/lib/universeStore';
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
  // The '@/lib/stockScan' mock below requireActual's the real module, so its
  // stockScanFailureReason() reads this. No case here reaches the hint today
  // (the rejection path passes reachedRequest = false), but the real module is
  // loaded, so leaving it out would render "the backend at undefined" the
  // moment one does.
  API_BASE_URL: 'http://localhost:8000',
}));

jest.mock('@/lib/stockScan', () => ({
  // requireActual, so the real stockScanFailureReason() runs in the .catch()
  // path under test rather than arriving as undefined.
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: jest.fn(async (...args: unknown[]) => {
    const scan = await jest.requireMock('@/lib/stockScan').runStockScan(...args);
    const store = jest.requireActual('@/lib/scanStore').useScanStore.getState();
    const reason = store.stockScanError ?? 'unknown error';
    store.setStockScanFeedback(store.stockManualRunToken, { error: scan ? null : `Scan failed — ${reason}`, notice: null });
    return scan ? { kind: 'success', token: store.stockManualRunToken, result: scan } : { kind: 'failure', token: store.stockManualRunToken, reason };
  }),
  isStockManualScanCurrent: (outcome: { kind: string; token: number }) => outcome.kind !== 'obsolete' && outcome.token === jest.requireActual('@/lib/scanStore').useScanStore.getState().stockManualRunToken,
  runStockScan: jest.fn(),
}));

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

const mockPostScanBody = api.postScanBody as jest.MockedFunction<typeof api.postScanBody>;

/**
 * Replace a store method with one that throws, and hand back the undo.
 *
 * NOT jest.spyOn: zustand builds the next state object by copying the current
 * one, so a spied method is copied along with it — and mockRestore() then
 * writes the original back onto the OLD object while the live state keeps the
 * spy. A throwing store write installed that way leaks into every later case
 * in the file. Going through setState puts it on (and takes it off) whatever
 * object is live.
 */
function breakStoreWrite(key: 'setScanState' | 'setStockScanError'): () => void {
  const original = useScanStore.getState()[key];
  useScanStore.setState({ [key]: () => { throw new Error('QuotaExceededError'); } } as never);
  return () => useScanStore.setState({ [key]: original } as never);
}

function breakAddToast(): { restore: () => void; calls: number } {
  const original = useAlertStore.getState().addToast;
  const state = { restore: () => useAlertStore.setState({ addToast: original } as never), calls: 0 };
  useAlertStore.setState({
    addToast: () => { state.calls += 1; throw new Error('QuotaExceededError'); },
  } as never);
  return state;
}

function resetStores() {
  useScanStore.setState({
    scanState: 'IDLE',
    scanAt: null,
    context: null,
    scanResult: null,
    conflictedSymbols: [],
    screenerMode: 'options',
    activeStrategy: null,
    stockScanError: null,
  } as any);
  usePortfolioStore.setState({ positions: [] });
}

describe('RunScanButton — conflict suppression wiring', () => {
  afterEach(() => {
    // Several cases below spy on a zustand store method and make it THROW.
    // clearAllMocks does not undo an implementation, and a case that fails
    // before its own mockRestore() would otherwise leave that throwing method
    // installed for every case after it.
    jest.restoreAllMocks();
  });

  beforeEach(() => {
    resetStores();
    jest.clearAllMocks();
    // AFTER clearAllMocks (and surviving a future clearMocks/resetMocks in
    // jest.config) so the tests that swap this implementation cannot leak
    // into the ones that don't.
    (runStockScan as jest.Mock).mockResolvedValue(null);
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

  it('toasts the stored reason when a stock scan fails (this path has no inline error area)', async () => {
    // Fire-and-forget means a null return was the ONLY signal here, and nothing
    // read it — a failed stock scan from step 3 left the FAILED pill as its
    // entire explanation.
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as any);
    (runStockScan as jest.Mock).mockImplementation(async () => {
      useScanStore.setState({ stockScanError: 'API /api/stock-scan → 422: rsi_oversold must be < 50' } as any);
      return null;
    });
    const addToastSpy = jest.spyOn(useAlertStore.getState(), 'addToast');

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
    });

    expect(addToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        recId: 'STOCK-SCAN-FAILED',
        alertType: 'SCAN_FAILED',
        reason: 'Stock scan failed — API /api/stock-scan → 422: rsi_oversold must be < 50',
      }),
    );
  });

  it('gates the toast on the returned result, not on whatever stockScanError holds', async () => {
    // A successful scan with an OLD reason still sitting in the store must not
    // toast — pins that the handler branches on `res`, which belongs to this
    // run, rather than on a store field that could outlive a previous one.
    useScanStore.setState({
      screenerMode: 'stocks',
      activeStrategy: 'pullback_ema',
      stockScanError: 'API /api/stock-scan → 500: a previous run',
    } as any);
    (runStockScan as jest.Mock).mockResolvedValue({ scan_id: 'S-1', candidates: [], rejected: [] });
    const addToastSpy = jest.spyOn(useAlertStore.getState(), 'addToast');

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
    });

    expect(addToastSpy).not.toHaveBeenCalled();
  });

  it('toasts the thrown reason when runStockScan rejects outright', async () => {
    // runStockScan converts its own failures into a null return, but a throw
    // from setScanState itself still escapes. Without the rejection handler
    // that is an unhandled rejection and the user sees nothing — the silent
    // failure again. The mock enters SCANNING before throwing, as the real one
    // does, because clearing that state is half of what the handler is for.
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as any);
    (runStockScan as jest.Mock).mockImplementation(async () => {
      useScanStore.setState({ scanState: 'SCANNING' } as any);
      throw new Error('store is not hydrated');
    });
    const addToastSpy = jest.spyOn(useAlertStore.getState(), 'addToast');

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
    });

    expect(addToastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'Stock scan failed — store is not hydrated' }),
    );
    // The throw happens with SCANNING already set. Leaving it there disables
    // the Run button for the rest of the session — telling the user why it
    // failed and then not letting them retry is the worse bug.
    expect(useScanStore.getState().scanState).toBe('FAILED');
  });

  it('still toasts when the store write is itself what failed', async () => {
    // Same load-bearing order as the step-4 belt: this handler exists for a
    // store write throwing, so it must not do a store write before the toast.
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as any);
    (runStockScan as jest.Mock).mockRejectedValue(new Error('QuotaExceededError'));
    // setScanState, because that is the write the old order performed FIRST —
    // mocking one the old order never called would have left this green
    // against the very reordering it is here to pin.
    const undo = breakStoreWrite('setScanState');
    const addToastSpy = jest.spyOn(useAlertStore.getState(), 'addToast');

    try {
      render(<RunScanButton />);
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
      });

      expect(addToastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ reason: 'Stock scan failed — QuotaExceededError' }),
      );
    } finally { undo(); }
  });

  it('still reaches FAILED when the reason write is what threw', async () => {
    // Same one-try-each split as the step-4 belt: the first write throwing
    // must not skip the FAILED reset that re-enables the Run button.
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as any);
    (runStockScan as jest.Mock).mockRejectedValue(new Error('QuotaExceededError'));
    const undo = breakStoreWrite('setStockScanError');

    try {
      render(<RunScanButton />);
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
      });

      expect(useScanStore.getState().scanState).toBe('FAILED');
    } finally { undo(); }
  });

  it('does not leave an unhandled rejection when the toast itself fails', async () => {
    // runStockScan catches its own store writes, so under blocked storage it
    // RETURNS NULL rather than rejecting — the null branch is the one that
    // runs, and addToast writes a persist()ed store, so it can throw there
    // too. Unguarded, that throw escapes a void-discarded chain entirely.
    useScanStore.setState({
      screenerMode: 'stocks', activeStrategy: 'pullback_ema',
      stockScanError: 'API /api/stock-scan → 500: boom',
    } as any);
    (runStockScan as jest.Mock).mockResolvedValue(null);
    const toast = breakAddToast();
    const rejections: unknown[] = [];
    const onRejection = (e: unknown) => { rejections.push(e); };
    process.on('unhandledRejection', onRejection);

    try {
      render(<RunScanButton />);
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));
      });
      // A macrotask turn: node emits 'unhandledRejection' after the microtask
      // queue drains, so a same-tick flush would miss it. (jsdom has no
      // setImmediate.)
      await new Promise((resolve) => { setTimeout(resolve, 0); });

      expect(toast.calls).toBe(1);
      expect(rejections).toHaveLength(0);
    } finally {
      process.off('unhandledRejection', onRejection);
      toast.restore();
    }
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


it('routes a current successful empty stock scan to Backtest exactly once', async () => {
  jest.clearAllMocks();
  useScanStore.setState({ scanState: 'IDLE', screenerMode: 'stocks', activeStrategy: 'pullback_ema' });
  (runStockScan as jest.Mock).mockResolvedValue({ scan_id: 'empty', timestamp: 't', candidates: [], rejected: [] });
  render(<RunScanButton />);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i })));
  expect(mockPush).toHaveBeenCalledTimes(1);
  expect(mockPush).toHaveBeenCalledWith('/screener/step-6-backtest');
});
it('does not route or toast an obsolete stock continuation', async () => {
  jest.clearAllMocks();
  useScanStore.setState({ scanState: 'IDLE', screenerMode: 'stocks', activeStrategy: 'pullback_ema' });
  const runner = await import('@/lib/stockScan');
  (runner.runStockScanWithContinuation as jest.Mock).mockResolvedValueOnce({ kind: 'obsolete', token: useScanStore.getState().stockManualRunToken - 1 });
  const toast = jest.spyOn(useAlertStore.getState(), 'addToast');
  try {
    render(<RunScanButton />);
    await act(async () => fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i })));
    expect(mockPush).not.toHaveBeenCalled(); expect(toast).not.toHaveBeenCalled();
  } finally { toast.mockRestore(); }
});

describe('Options manual cap units (#368)', () => {
  it.each([
    ['M', '25', 25_000_000], ['B', '2', 2_000_000_000],
    ['M', '0.5', 500_000], ['B', '0.25', 250_000_000],
    ['M', '0', 0], ['B', '0', 0],
    ['M', '', undefined], ['B', '', undefined],
  ] as const)('posts %s %s as %s USD for both bounds', async (capUnit, raw, usd) => {
    jest.clearAllMocks();
    resetStores();
    useScanStore.setState({ combinedRegime: 'PASS', regime: 'PASS' });
    useUniverseStore.setState({ pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: raw, maxCapRaw: raw, capUnit });
    mockPostScanBody.mockResolvedValue({ scan_id: 'CAP', timestamp: '2026-01-01T00:00:00Z', candidates: [], rejected: [] } as any);
    render(<RunScanButton />);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /run scan/i })); });
    expect(mockPostScanBody).toHaveBeenCalledTimes(1);
    const req = mockPostScanBody.mock.calls[0][0];
    expect(req.min_cap_usd).toBe(usd);
    expect(req.max_cap_usd).toBe(usd);
    expect(req).toMatchObject({ cap_filter_units_version: 1 });
    if (usd === undefined) {
      expect(req).not.toHaveProperty('min_cap_usd');
      expect(req).not.toHaveProperty('max_cap_usd');
    }
    useUniverseStore.getState().clearFilters();
  });
});

describe('RunScanButton — cross-mode regime REJECT gate (#387)', () => {
  beforeEach(() => {
    resetStores();
    jest.clearAllMocks();
  });

  it('shows REJECT dialog in stocks mode and halts execution until confirmed', async () => {
    useScanStore.setState({
      screenerMode: 'stocks',
      activeStrategy: 'pullback_ema',
      combinedRegime: 'REJECT',
      context: { direction: 'Bullish', horizon: 'Swing (5–15d)' },
    } as any);

    (runStockScan as jest.Mock).mockResolvedValue({
      scan_id: 'stock-scan-1',
      timestamp: 't',
      candidates: [],
      rejected: [],
    });

    render(<RunScanButton />);
    const runBtn = screen.getByRole('button', { name: /run stock scan/i });

    // Initial click prompts dialog; does NOT run scan or navigate
    await act(async () => {
      fireEvent.click(runBtn);
    });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Market regime is REJECT')).toBeInTheDocument();
    expect(runStockScan).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();

    // Click Cancel -> dialog closes; still nothing run or navigated
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    await act(async () => {
      fireEvent.click(cancelBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(runStockScan).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();

    // Click Run Stock Scan again -> dialog reappears
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Click Proceed anyway -> runs stock scan and navigates to step-6-backtest
    const proceedBtn = screen.getByRole('button', { name: /proceed anyway/i });
    await act(async () => {
      fireEvent.click(proceedBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(runStockScan).toHaveBeenCalledWith('pullback_ema');
    expect(mockPush).toHaveBeenCalledWith('/screener/step-6-backtest');
  });

  it('shows REJECT dialog in prebreakout mode and halts routing until confirmed', async () => {
    useScanStore.setState({
      screenerMode: 'prebreakout',
      combinedRegime: 'REJECT',
      context: { direction: 'Bullish', horizon: 'Swing (5–15d)' },
    } as any);

    render(<RunScanButton />);
    const runBtn = screen.getByRole('button', { name: /go to setup scanner/i });

    // Initial click prompts dialog; does NOT navigate
    await act(async () => {
      fireEvent.click(runBtn);
    });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Market regime is REJECT')).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();

    // Click Cancel -> dialog closes; still not navigated
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    await act(async () => {
      fireEvent.click(cancelBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPush).not.toHaveBeenCalled();

    // Click again -> dialog reappears
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Click Proceed anyway -> navigates to /screener/step-4-prebreakout
    const proceedBtn = screen.getByRole('button', { name: /proceed anyway/i });
    await act(async () => {
      fireEvent.click(proceedBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPush).toHaveBeenCalledWith('/screener/step-4-prebreakout');
  });

  it('shows REJECT dialog in options mode and halts options scan POST until confirmed', async () => {
    useScanStore.setState({
      screenerMode: 'options',
      combinedRegime: 'REJECT',
      context: { direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing' },
    } as any);

    mockPostScanBody.mockResolvedValue({
      scan_id: 'SCAN-1',
      timestamp: '2026-05-10T10:00:00',
      candidates: [],
      rejected: [],
    } as any);

    render(<RunScanButton />);
    const runBtn = screen.getByRole('button', { name: /run scan/i });

    // Initial click prompts dialog; does NOT fire scan POST
    await act(async () => {
      fireEvent.click(runBtn);
    });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Market regime is REJECT')).toBeInTheDocument();
    expect(mockPostScanBody).not.toHaveBeenCalled();

    // Click Cancel -> dialog closes; does NOT fire scan POST
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    await act(async () => {
      fireEvent.click(cancelBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPostScanBody).not.toHaveBeenCalled();

    // Click again -> dialog reappears
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Click Proceed anyway -> fires options scan POST
    const proceedBtn = screen.getByRole('button', { name: /proceed anyway/i });
    await act(async () => {
      fireEvent.click(proceedBtn);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPostScanBody).toHaveBeenCalled();
  });

  it('does not show dialog and executes directly when combinedRegime is PASS', async () => {
    // Stocks mode with PASS
    useScanStore.setState({
      screenerMode: 'stocks',
      activeStrategy: 'pullback_ema',
      combinedRegime: 'PASS',
    } as any);
    (runStockScan as jest.Mock).mockResolvedValue({ scan_id: 's', timestamp: 't', candidates: [], rejected: [] });

    const { unmount } = render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(runStockScan).toHaveBeenCalledWith('pullback_ema');
    unmount();

    // Prebreakout mode with PASS
    jest.clearAllMocks();
    useScanStore.setState({
      screenerMode: 'prebreakout',
      combinedRegime: 'PASS',
    } as any);

    const { unmount: unmount2 } = render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /go to setup scanner/i }));
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPush).toHaveBeenCalledWith('/screener/step-4-prebreakout');
    unmount2();

    // Options mode with PASS
    jest.clearAllMocks();
    useScanStore.setState({
      screenerMode: 'options',
      combinedRegime: 'PASS',
      context: { direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing' },
    } as any);
    mockPostScanBody.mockResolvedValue({ scan_id: 's', timestamp: 't', candidates: [], rejected: [] } as any);

    render(<RunScanButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run scan/i }));
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockPostScanBody).toHaveBeenCalled();
  });

  it('re-prompts on subsequent click after confirmed run when combinedRegime remains REJECT', async () => {
    useScanStore.setState({
      screenerMode: 'prebreakout',
      combinedRegime: 'REJECT',
      context: { direction: 'Bullish', horizon: 'Swing (5–15d)' },
    } as any);

    render(<RunScanButton />);
    const runBtn = screen.getByRole('button', { name: /go to setup scanner/i });

    // First run: prompt and proceed
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /proceed anyway/i }));
    });
    expect(mockPush).toHaveBeenCalledTimes(1);

    // Second click: must re-prompt because regimeConfirmedRef was reset to false
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(mockPush).toHaveBeenCalledTimes(1); // not called again without confirm
  });
});
