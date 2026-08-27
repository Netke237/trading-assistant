import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditDrawer } from '../page';
import { api } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
    getExitPlan: jest.fn(),
  },
}));

function makeStockPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
    stop: 182, targets: [
      { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
      { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
    ],
    status: 'PASS', contracts: 10, recId: 'REC-1',
    tradeCardSnapshot: { stock_score: 78, horizon: 'Swing (5–15d)', strategy: { strategy: 'pullback_ema' } },
    ...overrides,
  };
}

function makeOptionPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL 220C 05/16', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
    entryPrice: 4.2, currentPrice: 4.5, currentStockPrice: 195,
    pnlDollar: 30, pnlPct: 7.1, stop: 185, targets: [], status: 'PASS',
    delta: 0.5, contracts: 2, recId: 'REC-2',
    tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
    ...overrides,
  };
}

describe('EditDrawer Monte Carlo estimate', () => {
  const noop = () => {};

  it('calls getStockFirstPassage with target/stop prices and horizon from the snapshot for a stock position', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [
        { price: 205, probability: 0.6, expectedDays: 8 },
        { price: 215, probability: 0.3, expectedDays: 15 },
      ],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    // `runEstimate` always passes a real AbortSignal as the 2nd argument (see
    // Task 2 Step 4's AbortController pattern) — `toHaveBeenCalledWith` fails
    // outright on an unexpected extra argument, not just a mismatched one, so
    // the 2nd matcher below is required, not optional decoration.
    await waitFor(() => expect(api.getStockFirstPassage).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', horizon: 'Swing', strategy: 'pullback_ema',
      stock_price: 195, stop_price: 182, targets: [205, 215], trend_score: 78,
    }), expect.any(AbortSignal)));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(await screen.findByText('30%')).toBeInTheDocument();
    expect(screen.getByText(/10 trading days/)).toBeInTheDocument();
  });

  it('renders modelCaveat when the backend flags a poor model fit', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.4, expectedDays: 10 }],
      invalidation: { probability: 0.2, expectedDays: null },
      horizonDays: 10,
      modelCaveat: 'This model assumes directional drift; mean-reversion strategies may not fit well.',
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText(/may not fit well/)).toBeInTheDocument();
  });

  it('calls getFirstPassageEstimate with strike/trend from the snapshot and settings-store target percents for an option position', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 },
        { pct: 0.5, stockPrice: 230, optionPrice: 6.75, probability: 0.4, expectedDays: 10 },
        { pct: 1.0, stockPrice: 250, optionPrice: 9.0, probability: 0.35, expectedDays: 18 },
      ],
      invalidation: { probability: 0.10, expectedDays: null },
    });
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', stock_price: 195, strike: 220,
      dte: 20, premium: 4.5, delta: 0.5, trend_score: 72, invalidation_price: 185,
      t1_pct: expect.any(Number), t2_pct: expect.any(Number), t3_pct: expect.any(Number),
    }), expect.any(AbortSignal)));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(await screen.findByText('35%')).toBeInTheDocument();
    expect(await screen.findByText('10%')).toBeInTheDocument();
  });

  it('disables Estimate for a stock position with no targets captured', () => {
    render(<EditDrawer position={makeStockPosition({ targets: [] })} onClose={noop} onChange={noop} onRemove={noop} />);
    // NOT screen.getByText('Estimate').toBeDisabled() — the button's label is
    // rendered via <Text> (defaults to a nested <span>), and jest-dom's
    // toBeDisabled() does not see through an ancestor <button disabled> to a
    // descendant element the way a naive read might suggest; only the queried
    // element itself (or a `<fieldset disabled>` ancestor) counts. Query the
    // actual <button> via its accessible role/name instead.
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('disables Estimate for an option position missing strike in its snapshot', () => {
    render(<EditDrawer position={makeOptionPosition({ tradeCardSnapshot: {} })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('re-derives the option strike from position.contract even when the buy-time snapshot has no strike (pre-existing positions)', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 }],
      invalidation: { probability: 0.1, expectedDays: null },
    });
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C', tradeCardSnapshot: { stockBreakdown: { trend: 72 } } });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).not.toBeDisabled();
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(expect.objectContaining({
      strike: 220,
    }), expect.any(AbortSignal)));
  });

  it('prefers the exact snapshot strike over the contract id, which the backend truncates to an integer', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 }],
      invalidation: { probability: 0.1, expectedDays: null },
    });
    // backend/app/routers/scan.py builds the contract id as
    // f"{symbol}|{int(strike)}|..." — a real $187.50 strike position has
    // contract "AAPL|187|..." (rounded down) but the buy-time snapshot
    // captured the exact 187.5. The snapshot must win; falling back to the
    // contract-derived value here would silently mis-price every fractional
    // strike.
    const position = makeOptionPosition({
      contract: 'AAPL|187|2026-09-16|C',
      tradeCardSnapshot: { strike: 187.5, stockBreakdown: { trend: 72 } },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(expect.objectContaining({
      strike: 187.5,
    }), expect.any(AbortSignal)));
  });

  it('clears a stale Monte Carlo result when the user edits the stop after estimating', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    const onChange = jest.fn();
    const { rerender } = render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={onChange} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('60%')).toBeInTheDocument();

    // Simulate the store update an edited stop would produce — EditDrawer re-renders
    // with the SAME position identity but a changed `stop`, exactly as the real
    // parent does when `onChange` writes through to the store.
    rerender(<EditDrawer position={makeStockPosition({ stop: 175 })} onClose={noop} onChange={onChange} onRemove={noop} />);

    await waitFor(() => expect(screen.queryByText('60%')).not.toBeInTheDocument());
  });

  it('flags a Monte Carlo result as stale when the user edits the Current Price field after estimating, but not before', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={jest.fn()} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('60%')).toBeInTheDocument();

    // Fresh estimate, nothing has changed yet — no staleness note, and the
    // numbers are still shown (this is purely additive, not a replacement
    // for the clearing effect above).
    expect(screen.queryByText('Price has changed since this estimate was computed.')).not.toBeInTheDocument();

    // Actually interact with the "Current price" EditField, the real
    // user-edit path — NOT a re-render with a changed `position` prop.
    // Staleness is deliberately keyed off this explicit edit, never off a
    // live-price-value comparison: portfolioStore's syncFromBackend() also
    // rewrites position.currentPrice every 30s independent of any user
    // action, and a value-comparison approach was tried and reverted
    // specifically because it fired "stale" on that routine tick too (see
    // priceEditedSinceEstimate's declaration in page.tsx for the full story).
    fireEvent.change(screen.getByLabelText(/Current price/), { target: { value: '210' } });

    expect(await screen.findByText('Price has changed since this estimate was computed.')).toBeInTheDocument();
    // The existing numbers must still be visible — additive warning, not a
    // clear/hide of the result.
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  it('does NOT flag a Monte Carlo result as stale from a live price-sync re-render alone (no user edit)', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 205, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    // Simulates the parent's 30s syncFromBackend() poll rewriting
    // position.currentPrice on the SAME open drawer with no user
    // interaction — this must NOT be mistaken for an explicit edit.
    const { rerender } = render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={jest.fn()} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('60%')).toBeInTheDocument();

    rerender(<EditDrawer position={makeStockPosition({ currentPrice: 196 })} onClose={noop} onChange={jest.fn()} onRemove={noop} />);

    expect(screen.queryByText('Price has changed since this estimate was computed.')).not.toBeInTheDocument();
  });

  it('flags an option Monte Carlo result as stale when the user edits Current Price (the premium), even though the underlying price is unchanged', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 }],
      invalidation: { probability: 0.10, expectedDays: null },
    });
    // For an option position, the shared "Current price" EditField edits the
    // PREMIUM (position.currentPrice), not the underlying (currentStockPrice)
    // — this must invalidate the estimate too, since `premium` is a real
    // input to getFirstPassageEstimate.
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={jest.fn()} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(screen.queryByText('Price has changed since this estimate was computed.')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Current price/), { target: { value: '5.0' } });

    expect(await screen.findByText('Price has changed since this estimate was computed.')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  it('does not get stuck showing "Estimating…" if the stop changes while a request is in flight', async () => {
    let resolveEstimate: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveEstimate = resolve; });
    (api.getStockFirstPassage as jest.Mock).mockReturnValueOnce(pending);

    const { rerender } = render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    expect(await screen.findByText('Estimating…')).toBeInTheDocument();

    // Edit lands while the request is still pending.
    rerender(<EditDrawer position={makeStockPosition({ stop: 175 })} onClose={noop} onChange={noop} onRemove={noop} />);

    // Now let the original (now-abandoned) request settle.
    resolveEstimate!({
      targets: [{ price: 205, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });

    // The button must recover — not be stuck disabled/"Estimating…" forever.
    await waitFor(() => expect(screen.getByText('Estimate')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Estimate' })).not.toBeDisabled();
  });
});

describe('ExitPlanEditor', () => {
  const noop = () => {};

  it('computes and renders an exit plan with stop/target rows on click', async () => {
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 180, source: 'structural', contractPrice: 2.5,
        rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8,
      },
      targets: [
        {
          rrRatio: 2, arithmeticPrice: 230, price: 230, tpSource: 'arithmetic', structuralPrice: null,
          contractPrice: 7.2, rrModel: 'BS repriced (IV-derived)', probability: 0.55, expectedDays: 6,
          qualityGood: true, qualityReasons: [],
        },
      ],
      atr: 3.1,
    });
    // Pipe-delimited contract id (the real runtime format — see the strike-
    // derivation tests above) so `position.contract.split('|')[1]` in
    // ExitPlanEditor's compute() actually yields the strike.
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C' });
    // ExitPlanEditor reads `position.exitPlan` from props, not local state —
    // the computed result only appears once `onChange`'s patch has been
    // written through and the position re-rendered with it, exactly as the
    // real store round-trip does. Same rerender pattern as the stale-Monte-
    // Carlo tests above.
    const onChange = jest.fn();
    const { rerender } = render(<EditDrawer position={position} onClose={noop} onChange={onChange} onRemove={noop} />);
    fireEvent.click(screen.getByText('Compute Exit Plan'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      exitPlan: expect.objectContaining({ stop: expect.objectContaining({ source: 'structural' }) }),
    })));
    expect(api.getExitPlan).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', strike: 220, dte: 20, premium: 4.5, trend_score: 50,
    }));
    const patch = onChange.mock.calls[0][0];
    rerender(<EditDrawer position={{ ...position, ...patch }} onClose={noop} onChange={onChange} onRemove={noop} />);
    expect(screen.getByText('Stop (structural)')).toBeInTheDocument();
    expect(screen.getByText('2R ✓')).toBeInTheDocument();
    expect(screen.getByText('$230.00')).toBeInTheDocument();
  });

  it('shows an error message when the exit-plan request fails', async () => {
    (api.getExitPlan as jest.Mock).mockRejectedValueOnce(new Error('network'));
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C' });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Compute Exit Plan'));
    expect(await screen.findByText(/Couldn.t compute an exit plan/)).toBeInTheDocument();
  });
});

describe('MaxLossBanner', () => {
  const noop = () => {};
  const baseExitPlan = {
    computedAt: '2026-08-27T00:00:00.000Z',
    stop: {
      price: 180, source: 'structural' as const, contractPrice: 2.0,
      rrModel: 'BS repriced (IV-derived)' as const, structuralSource: 'swing_low' as const, structuralConfidence: 0.8,
    },
    targets: [],
    atr: 3.1,
  };

  it('renders nothing when entryPrice is 0 (data-integrity guard), even with a computed exit plan', () => {
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C', entryPrice: 0, exitPlan: baseExitPlan });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.queryByText('Max loss at stop')).not.toBeInTheDocument();
  });

  it('flags REJECT when the loss at stop exceeds the account default limit', () => {
    // lossAtStop = (10 - 1) * 100 * 20 = $18,000, well over the $3,750 default limit
    // (portfolioValue 100000 * maxLossPerTradePct 0.0375, riskStore's DEFAULT_LIMITS).
    const position = makeOptionPosition({
      contract: 'AAPL|220|2026-09-16|C', entryPrice: 10, contracts: 20,
      exitPlan: { ...baseExitPlan, stop: { ...baseExitPlan.stop, contractPrice: 1 } },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('Max loss at stop')).toBeInTheDocument();
    expect(screen.getByText('REJECT')).toBeInTheDocument();
    expect(screen.getByText('$18,000')).toBeInTheDocument();
  });

  it('shows PASS when the loss at stop is within the account default limit', () => {
    // lossAtStop = (4.2 - 3.5) * 100 * 1 = $70, well within the $3,750 default limit.
    const position = makeOptionPosition({
      contract: 'AAPL|220|2026-09-16|C', entryPrice: 4.2, contracts: 1,
      exitPlan: { ...baseExitPlan, stop: { ...baseExitPlan.stop, contractPrice: 3.5 } },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });
});
