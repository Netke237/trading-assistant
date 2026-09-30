import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, within, fireEvent } from '@testing-library/react';
import Step4Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import type { TradeCardData } from '@/types/domain';

/**
 * The backend ranks options candidates by finalStatus, then stock score, so a
 * PASS 72 comes back ahead of a CAUTION 95. The table used to default to
 * SCORE descending, which put the CAUTION 95 on top -- above the row the page
 * auto-selects (list[0], the backend's rank 1). The default is now the scan's
 * own order.
 */

jest.mock('@/lib/api', () => ({
  api: { getCandles: jest.fn().mockResolvedValue([]) },
}));

function card(symbol: string, status: 'PASS' | 'CAUTION', stockScore: number): TradeCardData {
  return {
    symbol, company: `${symbol} Inc`, price: 100, direction: 'Bullish',
    status, stockScore, stockConfidence: status,
    stockBreakdown: { trend: 50, pullback: 50, trigger: 50, event: 50, volatility: 50 } as any,
    contract: `${symbol}|100|2027-04-16|C`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: {} as any, entry: {} as any, exit: {} as any,
    nextEventDays: null, nextEventLabel: null, rrRatio: 2, rrModel: 'BS repriced (IV-derived)', finalStatus: status,
  } as TradeCardData;
}

describe('Step 4 ranking — default order is the scan rank', () => {
  afterEach(() => useScanStore.setState({ scanResult: undefined, previousRun: undefined } as any));

  it('lists the backend rank-1 PASS above a higher-scoring CAUTION', () => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'REC-1', timestamp: 't', rejected: [],
        candidates: [card('PASSCO', 'PASS', 72), card('CAUTCO', 'CAUTION', 95)],
      },
      previousRun: undefined,
      context: { direction: 'Bullish', horizon: 'Position (90–105d)' },
    } as any);

    render(<Step4Page />);

    const table = screen.getByRole('table');
    const order = within(table).getAllByText(/^(PASSCO|CAUTCO)$/).map((el) => el.textContent);
    expect(order).toEqual(['PASSCO', 'CAUTCO']);
  });

  // Three rows so that neither score direction reproduces the rank order
  // (score asc = LOWCO, PASSCO, CAUTCO; desc = CAUTCO, PASSCO, LOWCO) -- the
  // two-row case above passes a score-ASC default by coincidence -- and a
  // sort away and back to "#" must restore it. (rank is list index + 1 and
  // sortRows re-sorts the original list, so the rank key cannot be told
  // apart from list order here; the backend order is pinned in
  // backend/tests/test_shortlist.py.)
  it('orders by rank, not by either score direction, and "#" restores it', () => {
    useScanStore.setState({
      scanResult: {
        scan_id: 'REC-1', timestamp: 't', rejected: [],
        candidates: [card('PASSCO', 'PASS', 72), card('LOWCO', 'PASS', 60), card('CAUTCO', 'CAUTION', 95)],
      },
      previousRun: undefined,
      context: { direction: 'Bullish', horizon: 'Position (90–105d)' },
    } as any);

    render(<Step4Page />);
    const order = () => within(screen.getByRole('table'))
      .getAllByText(/^(PASSCO|LOWCO|CAUTCO)$/).map((el) => el.textContent);
    expect(order()).toEqual(['PASSCO', 'LOWCO', 'CAUTCO']);

    fireEvent.click(screen.getByRole('button', { name: /^SYM/i }));
    expect(order()).not.toEqual(['PASSCO', 'LOWCO', 'CAUTCO']);
    fireEvent.click(screen.getByRole('button', { name: /scan rank/i }));
    expect(order()).toEqual(['PASSCO', 'LOWCO', 'CAUTCO']);
  });

  it('gives the rank header an accessible name', () => {
    useScanStore.setState({
      scanResult: { scan_id: 'REC-1', timestamp: 't', rejected: [], candidates: [card('PASSCO', 'PASS', 72)] },
      previousRun: undefined,
      context: { direction: 'Bullish', horizon: 'Position (90–105d)' },
    } as any);
    render(<Step4Page />);
    expect(screen.getByRole('button', { name: /scan rank/i })).toBeInTheDocument();
  });
});
