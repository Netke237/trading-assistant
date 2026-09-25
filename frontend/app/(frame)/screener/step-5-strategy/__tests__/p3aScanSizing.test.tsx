/**
 * P3a item 1 (decision Q2): every MANUAL scan path sizes from Settings → Risk,
 * and a 0% max loss per trade stops the scan with a message instead of posting
 * a request the backend refuses (decision P3A-SCAN-RISK-ZERO-STOPS-2026-09-25).
 * Four paths: Steps 3/4 runStockScan, Step 5, Analysis (current-settings
 * basis), Step-4 Pre-Breakout pullback.
 */
import '@testing-library/jest-dom';
import { render, fireEvent, waitFor, screen, cleanup } from '@testing-library/react';
import { runStockScan, SCAN_RISK_ZERO_MESSAGE } from '@/lib/stockScan';
import { useAnalysisStore } from '@/lib/analysisStore';
import { useScanStore } from '@/lib/scanStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import Step5 from '../page';
import PreBreakout from '../../step-4-prebreakout/page';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener',
}));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    analyzeStock: jest.fn(),
    prebreakoutScan: jest.fn(),
    fibPullbackScan: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;

function setup(portfolioValue: number, maxLossPerTradePct: number) {
  for (const f of [api.postStockScan, api.getLastStockScanStatus, api.analyzeStock]) m(f).mockReset();
  m(api.postStockScan).mockResolvedValue({ scan_id: 'S', timestamp: '2026-09-25T10:00:00+00:00', rejected: [], candidates: [] });
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  m(api.analyzeStock).mockResolvedValue({ symbol: 'AMD' });
  useScanStore.setState({
    context: { universe: 'NDX100', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    scanOverrides: {}, stockScanResult: null, stockScanRequest: null,
    activeStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
  useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue, maxLossPerTradePct } }));
  useAnalysisStore.setState({ symbol: '', result: null, loading: false, error: null });
}

afterEach(cleanup);

describe('Steps 3/4 — runStockScan', () => {
  it('sends the user\'s account value and max loss', async () => {
    setup(73_000, 0.02);
    await runStockScan('pullback_ema');
    const b = m(api.postStockScan).mock.calls[0][0];
    expect(b.account_size).toBe(73_000);
    expect(b.risk_pct).toBe(0.02);
  });
  it('at 0% posts nothing and reports the message', async () => {
    setup(73_000, 0);
    expect(await runStockScan('pullback_ema')).toBeNull();
    expect(m(api.postStockScan)).not.toHaveBeenCalled();
    expect(useScanStore.getState().stockScanError).toBe(SCAN_RISK_ZERO_MESSAGE);
  });
});

describe('Step 5', () => {
  const pick = () => fireEvent.click(screen.getByText(/^Breakout from tight base$/).closest('button')!);
  it('sends the user\'s account value and max loss', async () => {
    setup(73_000, 0.02);
    render(<Step5 />);
    pick();
    await waitFor(() => expect(m(api.postStockScan)).toHaveBeenCalledTimes(1));
    const b = m(api.postStockScan).mock.calls[0][0];
    expect(b.account_size).toBe(73_000);
    expect(b.risk_pct).toBe(0.02);
  });
  it('at 0% posts nothing and shows the message', async () => {
    setup(73_000, 0);
    render(<Step5 />);
    pick();
    expect(await screen.findByText(SCAN_RISK_ZERO_MESSAGE)).toBeInTheDocument();
    expect(m(api.postStockScan)).not.toHaveBeenCalled();
  });
});

describe('Analysis (current-settings basis)', () => {
  it('sends the user\'s account value and max loss', async () => {
    setup(73_000, 0.02);
    await useAnalysisStore.getState().analyze('amd');
    const r = m(api.analyzeStock).mock.calls[0][0];
    expect(r.account_size).toBe(73_000);
    expect(r.risk_pct).toBe(0.02);
  });
  it('at 0% calls nothing and shows the message', async () => {
    setup(73_000, 0);
    await useAnalysisStore.getState().analyze('amd');
    expect(m(api.analyzeStock)).not.toHaveBeenCalled();
    expect(useAnalysisStore.getState().error).toBe(SCAN_RISK_ZERO_MESSAGE);
  });
});

describe('Step 4 Pre-Breakout — pullback sub-mode', () => {
  const run = () => {
    render(<PreBreakout />);
    fireEvent.click(screen.getByRole('button', { name: /^Pullback to EMA/ }));
    fireEvent.change(screen.getByPlaceholderText(/Leave blank to use universe/), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run Scan' }));
  };
  it('sends the user\'s account value and max loss (snake_case)', async () => {
    setup(73_000, 0.02);
    run();
    await waitFor(() => expect(m(api.postStockScan)).toHaveBeenCalledTimes(1));
    const b = m(api.postStockScan).mock.calls[0][0];
    expect(b.account_size).toBe(73_000);
    expect(b.risk_pct).toBe(0.02);
    expect(b).not.toHaveProperty('accountSize');
  });
  it('at 0% posts nothing and shows the message', async () => {
    setup(73_000, 0);
    run();
    expect(await screen.findByText(SCAN_RISK_ZERO_MESSAGE)).toBeInTheDocument();
    expect(m(api.postStockScan)).not.toHaveBeenCalled();
  });
});
