import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import Step2Page from '../../step-2-universe/page';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { api } from '@/lib/api';
import type { StockScanResult } from '@/types/stockDomain';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));

jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    startHistoryPrefetch: jest.fn().mockResolvedValue(undefined),
    getHistoryPrefetchStatus: jest.fn().mockResolvedValue({ status: 'idle', total: 0, done: 0, failed: 0, current_symbol: null, elapsed_secs: 0 }),
    getSectors: jest.fn().mockResolvedValue([]),
    getIndexChanges: jest.fn().mockResolvedValue([]),
  },
  getLastDataRefresh: jest.fn().mockResolvedValue({ last_refresh: null }),
  API_BASE_URL: 'http://localhost:8000',
}));

const DUMMY_RESULT: StockScanResult = {
  scan_id: 'scan-1',
  timestamp: new Date().toISOString(),
  candidates: [],
  rejected: [],
  pipeline: {
    scanned: 3,
    failed_history: 0,
    failed_score: 0,
    failed_signal: 0,
    failed_backtest: 0,
    candidates: 0,
  },
  report_run_id: 'test-run-123',
};

describe('Stocks scan custom universe resolution (#343)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useScanStore.setState({
      context: {
        universe: 'SP500',
        direction: 'Bullish',
        horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing',
        holdMin: 5,
        holdMax: 15,
      },
      screenerMode: 'stocks',
      activeStrategy: 'pullback_ema',
      stockScanResult: null,
      stockScanError: null,
      stockManualRunToken: 0,
      scanState: 'IDLE',
    });
    useUniverseStore.setState({
      pick: 'SP500',
      customRaw: '',
      minPriceRaw: '',
      maxPriceRaw: '',
      minCapRaw: '',
      maxCapRaw: '',
      capUnit: 'B',
    });
    useWatchlistStore.setState({
      added: [],
    });
    (api.postStockScan as jest.Mock).mockResolvedValue(DUMMY_RESULT);
  });

  it('resolves Custom universe tickers from universeStore and updates caption accordingly', async () => {
    // User selected Custom with 3 tickers on Step 2
    useUniverseStore.setState({ pick: 'Custom', customRaw: 'MKC, KEY, EMN' });
    useScanStore.setState((s) => ({
      context: s.context ? { ...s.context, universe: 'Custom' } : null,
    }));

    render(<Step4StocksPage />);

    // Header displays accurate scope and sample tickers
    expect(
      screen.getByText('Scanning 3 custom symbols (MKC, KEY, EMN) for stock setups'),
    ).toBeInTheDocument();

    const runBtn = screen.getByRole('button', { name: /Run Stock Scan/i });
    expect(runBtn).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(runBtn);
    });

    await waitFor(() => {
      expect(api.postStockScan).toHaveBeenCalledTimes(1);
    });

    const sentReq = (api.postStockScan as jest.Mock).mock.calls[0][0];
    // Must send the 3 custom tickers, NOT ['SP500'] and NOT ['Custom']
    expect(sentReq.universe).toEqual(['MKC', 'KEY', 'EMN']);
  });

  it('switches to NDX100 and posts [NDX100]', async () => {
    useUniverseStore.setState({ pick: 'NDX100' });
    useScanStore.setState((s) => ({
      context: s.context ? { ...s.context, universe: 'NDX100' } : null,
    }));

    render(<Step4StocksPage />);

    expect(
      screen.getByText('Scanning full Nasdaq 100 universe for stock setups'),
    ).toBeInTheDocument();

    const runBtn = screen.getByRole('button', { name: /Run Stock Scan/i });
    await act(async () => {
      fireEvent.click(runBtn);
    });

    await waitFor(() => {
      expect(api.postStockScan).toHaveBeenCalledTimes(1);
    });

    const sentReq = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(sentReq.universe).toEqual(['NDX100']);
  });

  it('switches to Watchlist and posts starred symbols', async () => {
    useWatchlistStore.setState({ added: ['AAPL', 'MSFT'] });
    useUniverseStore.setState({ pick: 'Watchlist' });
    useScanStore.setState((s) => ({
      context: s.context ? { ...s.context, universe: 'Watchlist' } : null,
    }));

    render(<Step4StocksPage />);

    expect(
      screen.getByText('Scanning 2 watchlist symbols for stock setups'),
    ).toBeInTheDocument();

    const runBtn = screen.getByRole('button', { name: /Run Stock Scan/i });
    await act(async () => {
      fireEvent.click(runBtn);
    });

    await waitFor(() => {
      expect(api.postStockScan).toHaveBeenCalledTimes(1);
    });

    const sentReq = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(sentReq.universe).toEqual(['AAPL', 'MSFT']);
  });

  it('disables run button and blocks scan when Custom universe is empty', async () => {
    useUniverseStore.setState({ pick: 'Custom', customRaw: '   ' });
    useScanStore.setState((s) => ({
      context: s.context ? { ...s.context, universe: 'Custom' } : null,
    }));

    render(<Step4StocksPage />);

    expect(
      screen.getByText('Custom universe is empty — add symbols in Step 2 (Universe)'),
    ).toBeInTheDocument();

    const runBtn = screen.getByRole('button', { name: /Run Stock Scan/i });
    expect(runBtn).toBeDisabled();
    expect(runBtn).toHaveAttribute(
      'title',
      'Custom universe is empty — enter symbols in Step 2 (Universe)',
    );

    // Clicking disabled button does not trigger api call
    fireEvent.click(runBtn);
    expect(api.postStockScan).not.toHaveBeenCalled();
  });

  it('Step 2 editing custom symbols invalidates existing scan results (Fix for F-1 & F2-2)', async () => {
    // Populate an existing scan result
    useScanStore.setState({
      stockScanResult: DUMMY_RESULT,
      context: {
        universe: 'Custom',
        direction: 'Bullish',
        horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing',
        holdMin: 5,
        holdMax: 15,
      },
    });
    useUniverseStore.setState({ pick: 'Custom', customRaw: 'AAPL TSLA' });

    expect(useScanStore.getState().stockScanResult).not.toBeNull();

    render(<Step2Page />);

    const textarea = screen.getByLabelText('Custom ticker list');
    // User types in textarea
    fireEvent.change(textarea, { target: { value: 'AAPL NVDA' } });

    // Modifying custom tickers must clear obsolete stockScanResult
    expect(useScanStore.getState().stockScanResult).toBeNull();
  });

  it('Step 2 chip removal invalidates existing scan results (Fix for F2-2)', async () => {
    useScanStore.setState({
      stockScanResult: DUMMY_RESULT,
      context: {
        universe: 'Custom',
        direction: 'Bullish',
        horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing',
        holdMin: 5,
        holdMax: 15,
      },
    });
    useUniverseStore.setState({ pick: 'Custom', customRaw: 'AAPL TSLA' });

    expect(useScanStore.getState().stockScanResult).not.toBeNull();

    render(<Step2Page />);

    // Click remove button on TSLA chip
    const removeTslaBtn = screen.getByLabelText('Remove TSLA');
    fireEvent.click(removeTslaBtn);

    // Removing chip must clear obsolete stockScanResult
    expect(useScanStore.getState().stockScanResult).toBeNull();
    expect(useUniverseStore.getState().customRaw).toBe('AAPL');
  });
});
