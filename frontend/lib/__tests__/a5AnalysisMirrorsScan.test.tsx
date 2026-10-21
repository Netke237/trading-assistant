/**
 * A5 — the Analysis page mirrors the LAST STOCK SCAN RUN (decisions
 * A5-ANALYSIS-MIRRORS-SCAN / A5-MIRROR-LAST-SCAN-RUN, 2026-09-24).
 */
import '@testing-library/jest-dom';
import { render, fireEvent, waitFor, act, screen } from '@testing-library/react';
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useAnalysisStore, analysisRequestFor } from '@/lib/analysisStore';
import { StoreHydration } from '@/components/StoreHydration';
import { api } from '@/lib/api';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    analyzeStock: jest.fn(),
    getLastScan: jest.fn(),
    getLastScanStatus: jest.fn(),
    getLastStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    getLastStockScanRequest: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

// Step 4 Stocks page's heavy children, mocked as its own __tests__ do (the
// page writer below renders Step 4 since Step 5 was merged into it).
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));
jest.mock('../../app/(frame)/screener/step-4-stocks/HistoryPrefetchRow', () => ({ HistoryPrefetchRow: () => null }));

const m = (f: unknown) => f as jest.Mock;
const RESULT = (id: string) => ({ scan_id: id, timestamp: '2026-09-24T10:00:00+00:00', rejected: [], candidates: [] });

const STEP3 = {
  weight_trend: 50,
  fast_ema: 12,
  regime_headwind_caution_pct: -10,
  regime_headwind_reject_pct: -11,
  fundamentals_caution_above: 80,
  pullback_require_reversal: true,
  max_delta: 0.4,            // options-only: the scan filters it out; so must Analysis
};

function reset() {
  for (const f of Object.values(api)) m(f).mockReset();
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  m(api.getLastScanStatus).mockResolvedValue({ status: 'idle', updated_at: null });
  m(api.getLastScan).mockResolvedValue(null);
  m(api.analyzeStock).mockResolvedValue({ symbol: 'AAPL' });
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bearish', horizon: 'Position (1–6m)' },
    scanOverrides: { ...STEP3 },
    stockScanResult: null,
    stockScanRequest: null,
    previousStockScanResult: null,
    activeStrategy: 'ma_crossover',
    scanState: 'IDLE',
    stockScanError: null,
  } as never);
  useSettingsStore.setState({
    confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, enabled: true, cautionBelow: 55, rejectBelow: 35 },
  });
  useAnalysisStore.setState({ symbol: '', result: null, basis: null, loading: false, error: null });
}

const without = (o: Record<string, unknown>, ...keys: string[]) =>
  Object.fromEntries(Object.entries(o).filter(([k]) => !keys.includes(k)));

beforeEach(reset);

describe('T-F1 — Analysis replays the last scan run, Step-4 unsaved edits included', () => {
  it('sends the scan body with symbol for universe, even after the live stores change', async () => {
    m(api.postStockScan).mockResolvedValue(RESULT('S-1'));
    // The Step-4 panel's LOCAL edits — never written to scanParamsStore.
    await runStockScan('ma_crossover', { pullbackTolerancePct: 0.03, btMinTrades: 10, btMinWinRate: 0.6 });
    const scanBody = m(api.postStockScan).mock.calls[0][0];
    expect(scanBody.bt_min_trades).toBe(10);
    expect(scanBody.overrides).toEqual({ weight_trend: 0.5, fast_ema: 12 });

    // Everything live moves on after the scan.
    act(() => {
      useScanStore.setState({ scanOverrides: {}, activeStrategy: 'pullback_ema' });
      useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, enabled: false } });
    });

    await useAnalysisStore.getState().analyze('aapl');
    const sent = m(api.analyzeStock).mock.calls[0][0];
    expect(sent).toEqual({ ...without(scanBody, 'universe'), symbol: 'AAPL' });
    expect(sent.horizon).toBe('Position');
    expect(sent.regime_headwind_reject_pct).toBe(-11);
    expect(sent.confidence_caution_below).toBe(55);
    expect(sent.pullback_tolerance_pct).toBe(0.03);
    expect(useAnalysisStore.getState().basis).toBe('last-scan');
  });
});

describe('T-F2 — the snapshot pairs only with its own result', () => {
  it('with no snapshot, builds exactly what runStockScan(activeStrategy) would send, labelled current-settings', async () => {
    const { req, basis } = analysisRequestFor('MSFT');
    m(api.postStockScan).mockResolvedValue(RESULT('S-2'));
    await runStockScan('ma_crossover');
    const scanBody = m(api.postStockScan).mock.calls[0][0];
    expect(req).toEqual({ ...without(scanBody, 'universe'), symbol: 'MSFT' });
    expect(req).not.toHaveProperty('universe');
    expect(req.overrides).not.toHaveProperty('max_delta');
    expect(basis).toBe('current-settings');
  });

  it('a result written without its request (backend recovery) stores null', () => {
    act(() => useScanStore.getState().setStockScanResult(RESULT('S-3') as never, { strategy: 'x' } as never));
    act(() => useScanStore.getState().setStockScanResult(RESULT('S-4') as never));
    expect(useScanStore.getState().stockScanRequest).toBeNull();
  });

  it('clearing the result clears the request', () => {
    act(() => useScanStore.getState().setStockScanResult(RESULT('S-3') as never, { strategy: 'x' } as never));
    act(() => useScanStore.getState().setStockScanResult(null, { strategy: 'y' } as never));
    expect(useScanStore.getState().stockScanRequest).toBeNull();
  });

  it('a context change clears it with the result', () => {
    act(() => useScanStore.getState().setStockScanResult(RESULT('S-3') as never, { strategy: 'x' } as never));
    act(() => useScanStore.getState().setContext({ universe: 'NDX100', direction: 'Bearish', horizon: 'Position (1–6m)' } as never));
    expect(useScanStore.getState().stockScanResult).toBeNull();
    expect(useScanStore.getState().stockScanRequest).toBeNull();
  });

  it('a failed scan leaves no request behind', async () => {
    act(() => useScanStore.getState().setStockScanResult(RESULT('S-3') as never, { strategy: 'x' } as never));
    m(api.postStockScan).mockRejectedValue(new Error('boom'));
    await runStockScan('ma_crossover');
    expect(useScanStore.getState().stockScanRequest).toBeNull();
    expect(analysisRequestFor('AAPL').basis).toBe('current-settings');
  });
});

describe('T-F3 — persist migration v16 → v17', () => {
  it('adds stockScanRequest: null beside a stored result', async () => {
    localStorage.setItem('bamendjou-scan-store', JSON.stringify({
      version: 16,
      state: { stockScanResult: RESULT('OLD'), context: null },
    }));
    await act(async () => { await useScanStore.persist.rehydrate(); });
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('OLD');
    expect(useScanStore.getState().stockScanRequest).toBeNull();
    localStorage.clear();
  });

  it('persists the request next to its result', () => {
    act(() => useScanStore.getState().setStockScanResult(RESULT('P') as never, { strategy: 'z' } as never));
    const stored = JSON.parse(localStorage.getItem('bamendjou-scan-store') ?? '{}');
    // Re-pinned by TRADING-REVIEW-PHASE-C-RR: scanStore v18 (full-premium R/R)
    // moved the configured version; this test needs only "at or past v17".
    expect(stored.version).toBeGreaterThanOrEqual(17);
    expect(stored.state.stockScanRequest).toEqual({ strategy: 'z' });
    localStorage.clear();
  });
});

describe('T-F4 — StoreHydration attaches the backend record only on scan_id match', () => {
  async function hydrate(heldId: string | null, rec: unknown, fail = false) {
    // Before the seed: this set() is itself persisted and would overwrite it.
    useScanStore.setState({ stockScanResult: null, stockScanRequest: null } as never);
    localStorage.clear();
    if (heldId) {
      localStorage.setItem('bamendjou-scan-store', JSON.stringify({
        version: 17, state: { stockScanResult: RESULT(heldId), stockScanRequest: null, context: null },
      }));
    }
    m(api.getLastStockScan).mockResolvedValue(heldId ? null : RESULT('BK'));
    if (fail) m(api.getLastStockScanRequest).mockRejectedValue(new Error('down'));
    else m(api.getLastStockScanRequest).mockResolvedValue(rec);
    render(<StoreHydration />);
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalled());
  }

  it('match (recovered from the backend) → attached', async () => {
    await hydrate(null, { scan_id: 'BK', request: { strategy: 'breakout_base', direction: 'Bullish', horizon: 'Swing' } });
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('BK');
    expect(useScanStore.getState().stockScanRequest).toEqual({ strategy: 'breakout_base', direction: 'Bullish', horizon: 'Swing' });
  });

  it('match (persisted pre-v17 result) → attached', async () => {
    await hydrate('OLD', { scan_id: 'OLD', request: { strategy: 'a' } });
    expect(useScanStore.getState().stockScanRequest).toEqual({ strategy: 'a' });
  });

  it('mismatch → stays null', async () => {
    await hydrate('OLD', { scan_id: 'NEWER', request: { strategy: 'a' } });
    expect(useScanStore.getState().stockScanResult?.scan_id).toBe('OLD');
    expect(useScanStore.getState().stockScanRequest).toBeNull();
  });

  it('null record / fetch failure → stays null', async () => {
    await hydrate('OLD', null);
    expect(useScanStore.getState().stockScanRequest).toBeNull();
    m(api.getLastStockScanStatus).mockClear();
    await hydrate('OLD', null, true);
    expect(useScanStore.getState().stockScanRequest).toBeNull();
  });

  it('a result that already has its request → no fetch', async () => {
    localStorage.setItem('bamendjou-scan-store', JSON.stringify({
      version: 17, state: { stockScanResult: RESULT('H'), stockScanRequest: { strategy: 'h' }, context: null },
    }));
    render(<StoreHydration />);
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalled());
    expect(api.getLastStockScanRequest).not.toHaveBeenCalled();
    expect(useScanStore.getState().stockScanRequest).toEqual({ strategy: 'h' });
    localStorage.clear();
  });
});

// Was 'Step 5 writer'; retargeted to Step 4 when Step 5 was merged into it
// (STOCKS-STEP-MERGE-S1). Selecting a card no longer scans, so Run is clicked.
describe('Step 4 writer', () => {
  it('stores the exact body it posted with its result', async () => {
    const Step4 = (await import('../../app/(frame)/screener/step-4-stocks/page')).default;
    m(api.postStockScan).mockResolvedValue(RESULT('S4'));
    render(<Step4 />);
    // Bearish context: Step 4 labels breakout_base by direction.
    fireEvent.click(screen.getByText(/^Breakdown from tight base$/).closest('button')!);
    fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' }));
    await waitFor(() => expect(useScanStore.getState().stockScanResult?.scan_id).toBe('S4'));
    const body = m(api.postStockScan).mock.calls[0][0];
    expect(useScanStore.getState().stockScanRequest).toEqual(body);
    expect(body.strategy).toBe('breakout_base');
  });
});

describe('T-F5 — the page says which settings it ran on', () => {
  it('renders the basis caption', async () => {
    const Page = (await import('../../app/(frame)/analysis/page')).default;
    act(() => useAnalysisStore.setState({ result: null, basis: 'current-settings' }));
    const { rerender } = render(<Page />);
    expect(screen.queryByText(/Settings:/)).not.toBeInTheDocument();
    act(() => useAnalysisStore.setState({ result: FULL as never, basis: 'current-settings' }));
    rerender(<Page />);
    expect(screen.getByText(/current Step-3 and saved settings/)).toBeInTheDocument();
    act(() => useAnalysisStore.setState({ basis: 'last-scan' }));
    rerender(<Page />);
    expect(screen.getByText(/the last stock scan/)).toBeInTheDocument();
  });
});

const FULL = {
  symbol: 'AAPL', company: 'Apple', price: 100, direction: 'Bullish', stock_score: 60,
  stock_status: 'PASS', is_index: false, strategy: null, backtest: null, confidence: null,
  confidence_text: null, sentiment: null, fundamentals: null, next_event_days: null,
  next_event_label: null, rules: [], gate_flags: [], ema_trend: null, iv_rank: null,
  regime_by_horizon: {}, sector: null, sector_rs: null, market_backdrop: null,
};

describe('B6 (STOCKS-HORIZON-P0B) — Analysis sends the scan\'s hold', () => {
  it('current-settings: a Custom 60-185 context sends hold_max_days 185', () => {
    act(() => useScanStore.setState({
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Position (60–185d)',
        horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
    } as never));
    const { req, basis } = analysisRequestFor('MSFT');
    expect(basis).toBe('current-settings');
    expect(req.horizon).toBe('Position');
    expect(req.hold_max_days).toBe(185);
  });

  it('last-scan: replays the scan body\'s hold_max_days', async () => {
    act(() => useScanStore.setState({
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Position (60–185d)',
        horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
    } as never));
    m(api.postStockScan).mockResolvedValue(RESULT('S-B6'));
    await runStockScan('ma_crossover');
    expect(m(api.postStockScan).mock.calls[0][0].hold_max_days).toBe(185);
    const { req, basis } = analysisRequestFor('AAPL');
    expect(basis).toBe('last-scan');
    expect(req.hold_max_days).toBe(185);
  });
});
