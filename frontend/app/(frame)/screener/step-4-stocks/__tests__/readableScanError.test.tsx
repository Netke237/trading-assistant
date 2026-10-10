/**
 * A5d — a Step-4 scan that fails says why in plain English (decision
 * A5D-READABLE-MESSAGE-2026-09-25). A throw while building the request (most
 * likely a malformed saved setting) shows STOCK_SCAN_SETTINGS_INVALID; a
 * failure after the request was sent reuses stockScanFailureReason. Ported
 * from step-5-strategy/__tests__/a5dReadableScanError.test.tsx when the
 * mapping moved into the shared runStockScan (Stocks step merge, Stage 1,
 * Task 1). Plans:
 * docs/superpowers/plans/2026-09-25-a5d-step5-readable-scan-error-plan.md,
 * docs/superpowers/plans/2026-10-04-stocks-step-merge-stage1-plan.md
 */
import '@testing-library/jest-dom';
import { render, fireEvent, waitFor, screen, cleanup, within } from '@testing-library/react';
import { stockScanFailureReason, STOCK_SCAN_SETTINGS_INVALID } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import Step4StocksPage from '../page';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));

// Heavy children, mocked as scanFailureMessage.test.tsx does. StrategyParamsPanel
// and runStockScan are deliberately NOT mocked: this test needs the real ones.
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    startHistoryPrefetch: jest.fn(() => Promise.resolve()),
    getHistoryPrefetchStatus: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;

// The owner-decided wording, pinned literally so an edit to the constant goes red.
const DECIDED_MESSAGE =
  "Couldn't read your saved scan settings. Open Settings and press Reset to restore the defaults (this also resets your broker accounts, regime and gate settings).";

const PREFIX = 'runStockScan: building the stock-scan request failed';

let consoleError: jest.SpyInstance;

function reset() {
  mockPush.mockReset();
  m(api.postStockScan).mockReset();
  m(api.postStockScan).mockResolvedValue({ scan_id: 'S', timestamp: '2026-09-25T10:00:00+00:00', rejected: [], candidates: [] });
  m(api.getLastStockScanStatus).mockReset();
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    // No confidence_atr_mult_* keys: the builder must reach atrMultForHorizon.
    scanOverrides: {},
    stockScanResult: null,
    stockScanRequest: null,
    activeStrategy: null,
  } as never);
  useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
}

function button(): HTMLButtonElement {
  const el = screen.getAllByText(/^Breakout from tight base$/)
    .map((e) => e.closest('button')).find((b) => b !== null);
  if (!el) throw new Error('no breakout_base button');
  return el as HTMLButtonElement;
}

function runButton() { return screen.getByRole('button', { name: /Run Stock Scan|Running backtest scan/ }) as HTMLButtonElement; }

/** Select the card, click Run, and wait for runStockScan's `finally` (its status refresh) to have run `calls` times. */
async function clickAndSettle(calls: number) {
  fireEvent.click(button());
  fireEvent.click(runButton());
  await waitFor(() => expect(m(api.getLastStockScanStatus)).toHaveBeenCalledTimes(calls));
  await waitFor(() => expect(runButton()).not.toBeDisabled());
}

beforeEach(() => {
  reset();
  consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  consoleError.mockRestore();
});

describe('A5d — Step 4 scan failure messages', () => {
  it('T1 — confidenceGate: null shows the settings message, not a TypeError', async () => {
    useSettingsStore.setState({ confidenceGate: null } as never);
    render(<Step4StocksPage />);
    await clickAndSettle(1);

    expect(screen.getByText(`Scan failed — ${STOCK_SCAN_SETTINGS_INVALID}`)).toBeInTheDocument();
    expect(STOCK_SCAN_SETTINGS_INVALID).toBe(DECIDED_MESSAGE);
    expect(screen.queryByText(/TypeError|Cannot read/)).toBeNull();
    expect(m(api.postStockScan)).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledTimes(1);
    expect(consoleError.mock.calls[0][0]).toBe(PREFIX);
    expect(consoleError.mock.calls[0][1]).toBeInstanceOf(TypeError);
  });

  it('T2 — a non-null malformed gate { enabled: true } shows the same message', async () => {
    useSettingsStore.setState({ confidenceGate: { enabled: true } } as never);
    render(<Step4StocksPage />);
    await clickAndSettle(1);

    expect(screen.getByText(`Scan failed — ${STOCK_SCAN_SETTINGS_INVALID}`)).toBeInTheDocument();
    expect(m(api.postStockScan)).not.toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledTimes(1);
    expect(consoleError.mock.calls[0][0]).toBe(PREFIX);
  });

  it('T3 — an API error after the request shows the API line, no "Error: " prefix', async () => {
    m(api.postStockScan).mockRejectedValue(new Error('API /api/stock-scan → 422: universe is empty'));
    render(<Step4StocksPage />);
    await clickAndSettle(1);

    expect(m(api.postStockScan)).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Scan failed — API /api/stock-scan → 422: universe is empty')).toBeInTheDocument();
    expect(screen.queryByText(/Scan failed — Error: /)).toBeNull();
    expect(screen.queryByText(STOCK_SCAN_SETTINGS_INVALID, { exact: false })).toBeNull();
    expect(consoleError).not.toHaveBeenCalled();
  });

  it('T4 — a transport TypeError after the request gets the backend hint, not the settings message', async () => {
    m(api.postStockScan).mockRejectedValue(new TypeError('Failed to fetch'));
    render(<Step4StocksPage />);
    await clickAndSettle(1);

    const expected = stockScanFailureReason(new TypeError('Failed to fetch'));
    expect(expected).toContain('could not reach the backend at http://localhost:8000');
    expect(screen.getByText(`Scan failed — ${expected}`)).toBeInTheDocument();
    expect(screen.queryByText(STOCK_SCAN_SETTINGS_INVALID, { exact: false })).toBeNull();
    expect(consoleError).not.toHaveBeenCalled();
  });

  it('T5 — after a failure, restoring a valid gate lets the next scan through and clears the error', async () => {
    useSettingsStore.setState({ confidenceGate: null } as never);
    render(<Step4StocksPage />);
    await clickAndSettle(1);
    expect(screen.getByText(`Scan failed — ${STOCK_SCAN_SETTINGS_INVALID}`)).toBeInTheDocument();

    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
    await clickAndSettle(2);

    expect(m(api.postStockScan)).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(STOCK_SCAN_SETTINGS_INVALID, { exact: false })).toBeNull();
    // A clean success: no other failure text replaced the message. (Step 4 does
    // not navigate on success in Stage 1, so there is no mockPush assertion.)
    expect(within(screen.getByRole('complementary', { name: 'Scan actions' })).queryByText(/could not|failed|Error|API \//i)).toBeNull();
  });
});
