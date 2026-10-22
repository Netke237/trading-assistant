/**
 * STOCK-PRES-P4-STRATEGY Task 3 — the Market Sentiment strip (M10): the
 * compact MarketSentiment fed by Step 1's reading (scanStore.regimeSentiment),
 * with only the horizon label following the current scan context, or the
 * "Market sentiment loads on Step 1" note when there is no reading.
 * The real MarketSentiment is rendered (not mocked).
 * Plan: docs/superpowers/plans/2026-10-10-stock-pres-p4-strategy-plan.md
 */
import '@testing-library/jest-dom';
import { act, render, screen } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import type { SentimentData } from '@/types/domain';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: jest.fn(),
  runStockScan: jest.fn(),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

// The reading Step 1 writes (Task 1's object), stored with Step 1's horizon.
const READING: SentimentData = {
  horizon: 'Swing (5–15d)', timeframe: 'daily', state: 'Bull', p_stay: 0.8, stability: 'Stable',
  regime_age_days: 12, avg_regime_duration: 20, conviction_pct: 42, conviction_label: 'Moderate',
  interpretation: 'Market conviction: Moderate', hmm_state: 'Trending', alignment: 'Aligned',
  insufficient_data: false,
};

const NOTE = 'Market sentiment loads on Step 1';

beforeEach(() => {
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Position (45–60d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
    stockScanFeedback: { error: null, notice: null },
    stockAfterScanIntent: {},
    regimeSentiment: null,
  } as never);
});

describe('Market Sentiment strip (M10)', () => {
  it('no Step 1 reading → the note, no Market Sentiment card, no "insufficient history"', () => {
    render(<Step4StocksPage />);
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    expect(screen.queryByText('Market Sentiment')).toBeNull();
    expect(screen.queryByText(/insufficient history/)).toBeNull();
  });

  it('a Step 1 reading → its numbers unchanged; the horizon label follows the current context', () => {
    useScanStore.setState({ regimeSentiment: READING } as never);
    render(<Step4StocksPage />);
    expect(screen.getByText('Market Sentiment')).toBeInTheDocument();
    expect(screen.getByText('+42%')).toBeInTheDocument();
    expect(screen.getByText('Moderate — Market conviction: Moderate')).toBeInTheDocument();
    expect(screen.getByText('OMM/HMM Aligned')).toBeInTheDocument();
    expect(screen.getByText('Position (45–60d) · daily')).toBeInTheDocument();
    expect(screen.queryByText('Swing (5–15d) · daily')).toBeNull();
    expect(screen.queryByText(NOTE)).toBeNull();
    // The stored reading itself is not rewritten.
    expect(useScanStore.getState().regimeSentiment).toBe(READING);
  });

  it('clearing the reading after render swaps the strip for the note', () => {
    useScanStore.setState({ regimeSentiment: READING } as never);
    render(<Step4StocksPage />);
    expect(screen.getByText('Market Sentiment')).toBeInTheDocument();
    act(() => { useScanStore.setState({ regimeSentiment: null } as never); });
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    expect(screen.queryByText('Market Sentiment')).toBeNull();
    expect(screen.queryByText(/insufficient history/)).toBeNull();
  });
});
