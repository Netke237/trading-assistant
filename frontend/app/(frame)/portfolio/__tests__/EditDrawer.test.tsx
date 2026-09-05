import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditDrawer, tpMethodPatch } from '../EditDrawer';
import { api } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useNotesStore } from '@/lib/notesStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { premiumStopThresholdPrice, resolvePremiumStopPct } from '@/lib/premiumStop';
import { scanPortfolio } from '@/lib/alertEngine';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
    getExitPlan: jest.fn(),
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'AAPL', body: '', updatedAt: '2026-08-27T00:00:00Z' }),
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

  it('disables Estimate for an option position with a corrupted strike of 0 in its snapshot', () => {
    // A stored strike of 0 must not pass the `== null` check through to the
    // backend, which rejects strike <= 0 with a raw 422 instead of a
    // disabled button.
    render(<EditDrawer position={makeOptionPosition({ tradeCardSnapshot: { strike: 0 } })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('disables Estimate for an option position with a 0 premium (illiquid/deep-OTM quote)', () => {
    // portfolioStore's fromBackend sets currentPrice = quote.price ?? 0 for a
    // failed/empty quote fetch — a real state, not hypothetical. The backend
    // rejects premium <= 0 with a raw 422 rather than the button disabling.
    render(<EditDrawer position={makeOptionPosition({ currentPrice: 0 })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('disables Estimate and correctly attributes it to a missing price, not the stop or targets, for a stock position with a 0 current price', () => {
    // A 0 current price incidentally satisfies (or fails) the OTHER two
    // caution conditions for the wrong reason — a Bullish position would
    // otherwise misreport "stop on wrong side" and a Bearish one would
    // misreport "every target already reached." Neither is true; the real
    // cause is simply no live price yet.
    render(<EditDrawer position={makeStockPosition({ currentPrice: 0 })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
    expect(screen.getByText(/No live current price yet/)).toBeInTheDocument();
    expect(screen.queryByText(/stop is already on the wrong side/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Every target has already been reached/)).not.toBeInTheDocument();
  });

  it('disables Estimate for an option position with a 0 underlying stock price', () => {
    // currentStockPrice lands on exactly 0.0 (not null) for a bad/halted
    // quote — the old `== null` check alone let it straight through to the
    // backend's stock_price: Field(..., gt=0).
    render(<EditDrawer position={makeOptionPosition({ currentStockPrice: 0 })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
  });

  it('keeps Estimate enabled for a winning stock position that has already cleared its first target', async () => {
    // Regression: a Bullish position at $210 with T1=$205 (cleared) and
    // T2=$215 (still ahead) is a completely normal partial-profit state —
    // targets[].status is never synced to 'HIT' anywhere in this codebase, so
    // this must not be treated as "the position's data needs fixing." Only
    // T2 should be sent to the estimate; T1 must be silently dropped, not
    // block the whole feature.
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 215, probability: 0.4, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    const position = makeStockPosition({
      currentPrice: 210,
      targets: [
        { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
        { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
      ],
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
    await waitFor(() => expect(api.getStockFirstPassage).toHaveBeenCalledWith(
      expect.objectContaining({ targets: [215] }),
      expect.any(AbortSignal),
    ));
    // The backend response is positional (one entry for the one price sent,
    // T2's $215) — it must render labelled "T2", the target's real name, not
    // relabelled "T1" from its position within the filtered request array.
    // "T1"/"T2" also each appear once as the Targets section's own row
    // header regardless of this bug, so assert counts rather than presence:
    // "T2" should appear twice (its own header + the correctly-labelled
    // Monte Carlo result) and "T1" only once (its header alone — the one MC
    // result must not be mislabelled onto it).
    await waitFor(() => expect(screen.getAllByText('T2')).toHaveLength(2));
    expect(screen.getAllByText('T1')).toHaveLength(1);
  });

  it('disables Estimate and explains why when every target has already been reached', () => {
    const position = makeStockPosition({
      currentPrice: 220,
      targets: [
        { id: 'T1', stockPrice: 205, targetPrice: 205, status: 'PENDING' },
        { id: 'T2', stockPrice: 215, targetPrice: 215, status: 'PENDING' },
      ],
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
    expect(screen.getByText(/Every target has already been reached/)).toBeInTheDocument();
  });

  it('disables Estimate and explains why when the stop is on the wrong side of the current price', () => {
    const position = makeStockPosition({ currentPrice: 180, stop: 182 }); // stop above price for a Bullish position
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Estimate' })).toBeDisabled();
    expect(screen.getByText(/stop is already on the wrong side/)).toBeInTheDocument();
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
    // $230.00 renders twice now: once as this exit-plan 2R row's stock price,
    // and once as the "2R plan" option in the Feature D TP-method selector,
    // which reads its price out of this very row. Both are correct, so assert
    // on the pair rather than pinning either one and going ambiguous.
    expect(screen.getAllByText('$230.00')).toHaveLength(2);
  });

  it('shows an error message when the exit-plan request fails', async () => {
    (api.getExitPlan as jest.Mock).mockRejectedValueOnce(new Error('network'));
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C' });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Compute Exit Plan'));
    expect(await screen.findByText(/Couldn.t compute an exit plan/)).toBeInTheDocument();
  });

  it('disables Compute Exit Plan and explains why for a corrupted 0 strike', () => {
    const position = makeOptionPosition({ tradeCardSnapshot: { strike: 0 }, contract: 'AAPL 220C 05/16' });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Compute Exit Plan' })).toBeDisabled();
    expect(screen.getByText(/Missing a valid strike, premium, or entry price/)).toBeInTheDocument();
  });

  it('disables Compute Exit Plan and explains why for a 0 premium', () => {
    const position = makeOptionPosition({ currentPrice: 0 });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Compute Exit Plan' })).toBeDisabled();
    expect(screen.getByText(/Missing a valid strike, premium, or entry price/)).toBeInTheDocument();
  });

  it('disables Compute Exit Plan when the contract id has no parseable strike and no snapshot exists', () => {
    const position = makeOptionPosition({ tradeCardSnapshot: {}, contract: 'not-a-real-contract' });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Compute Exit Plan' })).toBeDisabled();
  });

  it('falls back to entryPrice for entry_price when currentStockPrice is 0, instead of sending 0', async () => {
    // `?? position.entryPrice` alone doesn't fall through on 0 — currentStockPrice
    // lands on exactly 0.0 (not null) for a bad/halted quote, and the backend's
    // entry_price: Field(..., gt=0) would reject a raw 0.
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: { price: 180, source: 'structural', contractPrice: 2.5, rrModel: 'x', structuralSource: 'swing_low', structuralConfidence: 0.8 },
      targets: [], atr: 3.1,
    });
    const position = makeOptionPosition({ contract: 'AAPL|220|2026-09-16|C', currentStockPrice: 0, entryPrice: 3.9 });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Compute Exit Plan' })).toBeEnabled();
    fireEvent.click(screen.getByText('Compute Exit Plan'));
    await waitFor(() => expect(api.getExitPlan).toHaveBeenCalledWith(
      expect.objectContaining({ entry_price: 3.9 }),
    ));
  });

  it('disables Compute Exit Plan when both currentStockPrice and entryPrice are 0', () => {
    const position = makeOptionPosition({ currentStockPrice: 0, entryPrice: 0 });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('button', { name: 'Compute Exit Plan' })).toBeDisabled();
    expect(screen.getByText(/Missing a valid strike, premium, or entry price/)).toBeInTheDocument();
  });
});

describe('MaxLossBanner', () => {
  const noop = () => {};
  const baseExitPlan = {
    computedAt: '2026-08-27T00:00:00.000Z',
    stop: {
      price: 180, source: 'structural' as const, contractPrice: 2.0,
      rrModel: 'BS repriced (IV-derived)' as const, structuralSource: 'swing_low' as const, structuralConfidence: 0.8,
      structuralPrice: 180, atrFloorPrice: 175, distanceDollar: 5,
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

  it('shows the risk-derived recommended contract size, floored, next to the exact decimal', () => {
    // riskPerContract = (10 - 1) * 100 * 1 = $900/contract. limitDollar =
    // $3,750 (account default) -> 3750 / 900 = 4.1666... contracts -> floors
    // to 4; the displayed decimal is truncated (not rounded) to 4.16, not
    // 4.17 -- see formatRecommendedContractSizeRaw's boundary-consistency note.
    const position = makeOptionPosition({
      contract: 'AAPL|220|2026-09-16|C', entryPrice: 10, contracts: 20,
      exitPlan: { ...baseExitPlan, stop: { ...baseExitPlan.stop, contractPrice: 1 } },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText(/Risk-derived size: 4 contracts \(4\.16 exact\)/)).toBeInTheDocument();
  });

  it('does not show a risk-derived size when the stop reprices at or above entry (no real per-contract loss)', () => {
    const position = makeOptionPosition({
      contract: 'AAPL|220|2026-09-16|C', entryPrice: 4.2, contracts: 1,
      exitPlan: { ...baseExitPlan, stop: { ...baseExitPlan.stop, contractPrice: 5.0 } },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.queryByText(/Risk-derived size/)).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------------ *
 * Feature D — active TP method selector + per-position alert overrides
 * (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
 * ------------------------------------------------------------------------ */

describe('tpMethodPatch', () => {
  it('stamps a snapshot price and timestamp for a non-ladder method', () => {
    expect(tpMethodPatch('exit_plan_2r', 230, '2026-08-27T00:00:00.000Z')).toEqual({
      activeTpMethod: 'exit_plan_2r',
      resolvedTpPrice: 230,
      resolvedTpUpdatedAt: '2026-08-27T00:00:00.000Z',
    });
  });

  it('clears the snapshot for the ladder so it keeps tracking its target live', () => {
    // The ladder's targets are edited in this very drawer — a snapshot would
    // go stale the moment the user changed one, so 'ladder' means "no snapshot".
    expect(tpMethodPatch('ladder', 205, '2026-08-27T00:00:00.000Z')).toEqual({
      activeTpMethod: 'ladder',
      resolvedTpPrice: null,
      resolvedTpUpdatedAt: '2026-08-27T00:00:00.000Z',
    });
  });
});

describe('EditDrawer active TP method selector', () => {
  const noop = () => {};

  it('marks the ladder active by default and offers every method', () => {
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: 'Ladder' })).toHaveAttribute('aria-checked', 'true');
    for (const label of ['Monte Carlo', '2R plan', '3R plan']) {
      expect(screen.getByRole('radio', { name: label })).toBeInTheDocument();
    }
  });

  it('shows the ladder its first target price', () => {
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: 'Ladder' })).toHaveTextContent('$205.00');
  });

  it('disables a method whose price cannot be resolved yet', () => {
    // No exit plan computed and no Monte Carlo run — picking either would
    // stamp a null snapshot, which the alert engine silently falls back to the
    // ladder for, i.e. a control that appears to do nothing.
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: '2R plan' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toBeDisabled();
  });

  it('disables the ladder when the position has no targets at all', () => {
    render(<EditDrawer position={makeStockPosition({ targets: [] })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: 'Ladder' })).toBeDisabled();
  });

  it('enables and prices the exit-plan rows once a plan is present', () => {
    const position = makeOptionPosition({
      exitPlan: {
        computedAt: '2026-08-27T00:00:00.000Z',
        atr: 3.1,
        stop: {
          price: 180, source: 'structural', contractPrice: 2.5,
          rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8,
          structuralPrice: 180, atrFloorPrice: 175, distanceDollar: 5,
        },
        targets: [
          {
            rrRatio: 2, arithmeticPrice: 230, price: 230, tpSource: 'arithmetic', structuralPrice: null,
            contractPrice: 7.2, rrModel: 'BS repriced (IV-derived)', probability: 0.55, expectedDays: 6,
            qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1.5,
          },
        ],
      },
    });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    const twoR = screen.getByRole('radio', { name: '2R plan' });
    expect(twoR).toBeEnabled();
    expect(twoR).toHaveTextContent('$230.00');
    // The plan carries no 3R row, so that option stays unpickable.
    expect(screen.getByRole('radio', { name: '3R plan' })).toBeDisabled();
  });

  it('patches the active method and its snapshot on click', () => {
    const onChange = jest.fn();
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={onChange} onRemove={noop} />);
    fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      activeTpMethod: 'ladder',
      resolvedTpPrice: null,
    }));
  });

  it('shows the active Monte Carlo method as enabled and priced from its persisted snapshot on reopen', () => {
    // mcResult (the in-session Monte Carlo estimate) starts null on every mount
    // — before the drawer has been asked to re-estimate anything, the Monte
    // Carlo button must still reflect the position's ALREADY-persisted
    // resolvedTpPrice when that's the active method, not render itself
    // disabled/unresolved just because nothing's been re-run this session.
    render(
      <EditDrawer
        position={makeStockPosition({ activeTpMethod: 'monte_carlo', resolvedTpPrice: 205 })}
        onClose={noop} onChange={noop} onRemove={noop}
      />,
    );
    const mc = screen.getByRole('radio', { name: 'Monte Carlo' });
    expect(mc).toBeEnabled();
    expect(mc).toHaveAttribute('aria-checked', 'true');
    expect(mc).toHaveTextContent('$205.00');
  });

  it('re-stamps the snapshot when the active method is re-estimated', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 208, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    const onChange = jest.fn();
    render(
      <EditDrawer
        position={makeStockPosition({ activeTpMethod: 'monte_carlo', resolvedTpPrice: 205 })}
        onClose={noop} onChange={onChange} onRemove={noop}
      />,
    );
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      activeTpMethod: 'monte_carlo',
      resolvedTpPrice: 208,
    })));
  });

  it('does not re-stamp when a different method is active', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      targets: [{ price: 208, probability: 0.6, expectedDays: 8 }],
      invalidation: { probability: 0.15, expectedDays: null },
      horizonDays: 10,
      modelCaveat: null,
    });
    const onChange = jest.fn();
    render(
      <EditDrawer
        position={makeStockPosition({ activeTpMethod: 'ladder' })}
        onClose={noop} onChange={onChange} onRemove={noop}
      />,
    );
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(screen.getByText(/Chance of reaching/)).toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('EditDrawer per-position alert overrides', () => {
  const noop = () => {};

  it('defaults every type to inherit', () => {
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: /Stop reached: Inherit/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Stop reached: On' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'Stop reached: Off' })).toHaveAttribute('aria-checked', 'false');
  });

  it('labels what the inherit state currently resolves to', () => {
    // Inherit must stay visually distinct from an explicit On even when the
    // global setting is also on — they diverge the moment the global changes.
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByRole('radio', { name: 'Stop reached: Inherit (on)' })).toBeInTheDocument();
  });

  it('writes an explicit false when a type is switched off', () => {
    const onChange = jest.fn();
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={onChange} onRemove={noop} />);
    fireEvent.click(screen.getByRole('radio', { name: 'Stop reached: Off' }));
    expect(onChange).toHaveBeenCalledWith({ alertOverrides: { STOP_REACHED: false } });
  });

  it('deletes the key — never stores undefined — when returning to inherit', () => {
    // Absent key IS the inherit state, and it has to match the backend's
    // alert_overrides JSON shape; a stored `undefined` would round-trip as null.
    const onChange = jest.fn();
    render(
      <EditDrawer
        position={makeStockPosition({ alertOverrides: { STOP_REACHED: false, TP_HIT: true } })}
        onClose={noop} onChange={onChange} onRemove={noop}
      />,
    );
    fireEvent.click(screen.getByRole('radio', { name: /Stop reached: Inherit/ }));
    expect(onChange).toHaveBeenCalledWith({ alertOverrides: { TP_HIT: true } });
    expect(Object.keys(onChange.mock.calls[0][0].alertOverrides)).not.toContain('STOP_REACHED');
  });

  it('leaves the other types untouched when one is changed', () => {
    const onChange = jest.fn();
    render(
      <EditDrawer
        position={makeStockPosition({ alertOverrides: { TP_HIT: false } })}
        onClose={noop} onChange={onChange} onRemove={noop}
      />,
    );
    fireEvent.click(screen.getByRole('radio', { name: 'Time stop: On' }));
    expect(onChange).toHaveBeenCalledWith({ alertOverrides: { TP_HIT: false, TIME_STOP: true } });
  });

  it('shows the price each enabled alert fires against', () => {
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('Fires at stock $205.00.')).toBeInTheDocument();  // TP_HIT — first ladder target
    expect(screen.getByText('Fires at stock $182.00.')).toBeInTheDocument();  // STOP_REACHED
  });

  it('labels PREMIUM_STOP a stock level, not a premium, for a stock position', () => {
    // The backend's PREMIUM_STOP threshold (entry_price * (1 - premiumStopPct))
    // is compared against the position's own contract quote — for a `|STOCK`
    // contract that's the stock price itself (market.py's stock-format branch
    // in fetch_contract_quote_async), never an option premium. Labeling it
    // "premium" here would misattribute a stock-price level as an options
    // concept this position doesn't have. entryPrice 190 * (1 - 0.60) = 76.00.
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('Fires at stock $76.00.')).toBeInTheDocument();
    expect(screen.queryByText(/Fires at premium/)).not.toBeInTheDocument();
  });

  it('labels PREMIUM_STOP a premium for an option position', () => {
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    // entryPrice 4.2 * (1 - 0.60) = 1.68.
    expect(screen.getByText('Fires at premium $1.68.')).toBeInTheDocument();
  });

  it('shows TIME_STOP as not set for a stock position, not the option 3-DTE threshold', () => {
    // Round-7 re-audit finding: alertFiresAgainst's TIME_STOP case unconditionally
    // returned '3 DTE or less' regardless of contract shape, describing a threshold
    // that alertEngine.ts can never actually fire for a stock position (which has
    // no expiry) as if it were live.
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.queryByText(/3 DTE or less/)).not.toBeInTheDocument();
  });

  it('shows the 3-DTE threshold for TIME_STOP on an option position', () => {
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText(/3 DTE or less/)).toBeInTheDocument();
  });

  it('prefers the resolved TP snapshot over the ladder in the fires-at line', () => {
    render(
      <EditDrawer
        position={makeStockPosition({ activeTpMethod: 'exit_plan_2r', resolvedTpPrice: 230 })}
        onClose={noop} onChange={noop} onRemove={noop}
      />,
    );
    expect(screen.getByText('Fires at stock $230.00.')).toBeInTheDocument();
  });

  it('says so when an enabled type has no level set on this position', () => {
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    // No structural stop was ever captured for this position, and TIME_STOP
    // never applies to a stock position (round-7 fix) -- both show "not set."
    expect(screen.getAllByText('On, but no level is set on this position yet.')).toHaveLength(2);
  });

  it('says an explicitly-off type raises nothing', () => {
    render(
      <EditDrawer
        position={makeStockPosition({ alertOverrides: { STOP_REACHED: false } })}
        onClose={noop} onChange={noop} onRemove={noop}
      />,
    );
    expect(screen.getByText('Off — this position raises no alert of this type.')).toBeInTheDocument();
  });
});

describe('EditDrawer Notes section gating', () => {
  const noop = () => {};

  // `editable` on the Notes field is computed from the real watchlist/held
  // gate (useIsSymbolHeld + useWatchlistStore.isWatched), not hardcoded —
  // seed both stores explicitly per test rather than relying on whatever
  // default/persisted state the singleton stores happen to carry.
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [] });
    useWatchlistStore.setState({ added: [] });
    useNotesStore.setState({ notes: {} });
  });

  it('renders the note editor (not the gating placeholder) for a genuinely held position', async () => {
    const position = makeStockPosition();
    usePortfolioStore.setState({ positions: [position] });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);

    expect(await screen.findByLabelText(`Note for ${position.symbol}`)).toBeInTheDocument();
    expect(screen.queryByText(/star this symbol or open a position/i)).not.toBeInTheDocument();
  });

  it('renders the note editor via the watchlist gate alone, independent of the held gate', async () => {
    const position = makeStockPosition();
    // Deliberately NOT added to usePortfolioStore's positions — only the
    // watchlist gate should be doing the work in this case.
    useWatchlistStore.setState({ added: [position.symbol] });
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);

    expect(await screen.findByLabelText(`Note for ${position.symbol}`)).toBeInTheDocument();
  });
});

// ── Piece 4: the per-position premium stop editor ───────────────────────────
//
// Spec §8 test #10, and the two defects that reached round 3 because the ~90
// lines of draft-then-commit UI below had no coverage at all: the pure
// formatter was tested, the editor was not.

describe('PremiumStopEditor', () => {
  const noop = () => {};

  beforeEach(() => {
    useSettingsStore.setState({ premiumStopPct: 0.60 });
  });

  const openStop = (position: PortfolioPosition, onChange = noop) => {
    render(<EditDrawer position={position} onClose={noop} onChange={onChange} onRemove={noop} />);
    return screen.getByLabelText('Premium stop percent') as HTMLInputElement;
  };

  it('labels an inheriting position with the global, and a set one with its own', () => {
    const { unmount } = render(
      <EditDrawer position={makeOptionPosition({ premiumStopPct: null })}
                  onClose={noop} onChange={noop} onRemove={noop} />,
    );
    // "(global)" is the whole point: an inherited value that looks set is how a
    // user comes to believe they have per-position control they do not have.
    expect(screen.getByText(/Premium stop — 60% \(global\)/)).toBeInTheDocument();
    unmount();

    render(
      <EditDrawer position={makeOptionPosition({ premiumStopPct: 0.45 })}
                  onClose={noop} onChange={noop} onRemove={noop} />,
    );
    expect(screen.getByText('Premium stop — 45%')).toBeInTheDocument();
  });

  it('refuses a value that ROUNDS to 0 or 1, which the (0,1) column contract forbids', () => {
    // The guard used to run on the TYPED value and the rounding after it, so
    // 0.004 passed `pct > 0` and committed 0.0000, and 99.996 passed
    // `pct < 100` and committed 1.0000. Both 422 server-side, and
    // updatePosition writes optimistically with no revert -- so the rejected
    // value lived in local state for up to 30s. A stored 0 puts the threshold
    // at `entry * (1 - 0)` = the entry itself, raising a Critical PREMIUM_STOP
    // toast for EVERY position at or below entry, every 30s, with no backend
    // alert behind it.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.45 }), onChange);
    for (const bad of ['0.004', '99.996']) {
      fireEvent.change(input, { target: { value: bad } });
      fireEvent.blur(input);
      expect(onChange).not.toHaveBeenCalled();
      expect(input.value).toBe('45');    // reverted, not cleared
    }
  });

  it('does NOT rewrite a server-derived stop that no decimal count round-trips', () => {
    // The stored fraction is premiumStopDollar / entry_price -- 2.00 / 4.13 =
    // 0.48426150121065376. Rendering "48.43" and committing 0.4843 still
    // differs from it, so comparing values could never make a bare
    // focus-and-blur a no-op; only tracking whether the user typed can.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 2.0 / 4.13 }), onChange);
    expect(input.value).toBe('48.43');
    fireEvent.focus(input);
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does NOT rewrite a stored stop when the field is merely focused and blurred', () => {
    // THE DEFECT. `add_position` stores premiumStopDollar / entry_price, so a
    // server-derived stop is almost never a whole percent: 2.00 / 4.13 =
    // 0.4843. The editor rendered "48", committed 0.48 on blur and PATCHed it
    // — the stop silently rewritten by reading it, moving the threshold on a
    // $4.13 premium from $2.130 to $2.148.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.4843 }), onChange);
    expect(input.value).toBe('48.43');       // shown at the precision it is stored
    fireEvent.focus(input);
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('a REVERTED entry does not leave the field armed to rewrite itself on the next blur', () => {
    // ROUND 5. The two revert paths returned early without clearing dirtyRef,
    // so the flag that means "the user typed something" survived a rejected
    // edit. The value used here is the one the file's own comment is about:
    // 2.00 / 4.13 = 0.48426150121065376, which no fixed decimal count
    // round-trips, so the second commit's `next !== own` comparison is true and
    // the PATCH fires.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 2.0 / 4.13 }), onChange);
    expect(input.value).toBe('48.43');

    // 1) Type an out-of-range value and blur. It reverts, correctly, and must
    //    not PATCH.
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '100' } });
    fireEvent.blur(input);
    expect(input.value).toBe('48.43');
    expect(onChange).not.toHaveBeenCalled();

    // 2) Now merely click into the field to read it, and click away. Nothing
    //    was typed, so nothing may be written -- this used to PATCH 0.4843 over
    //    a stored 0.484261..., rewriting a live risk setting by looking at it.
    fireEvent.focus(input);
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  // ROUND 9 finding 11. This comment used to say the `!Number.isFinite(pct)`
  // branch was unreachable "because the field is `type=\"number\"`, and a
  // browser reports a non-numeric entry as an EMPTY value". Round 8 changed
  // the input to `type="text" inputMode="decimal"` -- in the same commit --
  // so the premise was false about the shipped input from the moment it was
  // written, and it was arguing for skipping a branch that a user reaches by
  // typing any non-numeric character. Tested now, along with the half-typed
  // literal that reaches the same revert through the round-9 guard.

  it.each([
    ['abc',   'a non-numeric entry'],
    ['1.2.3', 'a malformed number'],
    ['48.',   'a literal the user was still typing'],
  ])('reverts on %s (%s) rather than PATCHing a truncation', (typed) => {
    // `Number("48.")` is 48, so before round 9 the last case silently PATCHed
    // a live per-position alert threshold to 0.48 for a user on their way to
    // 48.5. The other two took the non-finite branch the comment above claimed
    // could not be reached.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.45 }), onChange);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: typed } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe('45');   // the stored value, shown back
  });

  it('a real edit still PATCHes after a reverted one', () => {
    // The guard must not be so eager that it swallows a genuine edit made
    // straight after a rejected one.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 2.0 / 4.13 }), onChange);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '100' } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '35' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith({ premiumStopPct: 0.35 });
  });

  it('round-trips a sub-1% stop instead of showing an unre-committable 0', () => {
    // The card's premium-stop field has min={0.01}, so a $0.01 stop on a $5.20
    // premium derives 0.0019. That rendered "0" — which `commit` itself
    // rejects (it bounds at 0 < pct < 100) — so the field sat showing a value
    // it would not accept back.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.0019 }), onChange);
    expect(input.value).toBe('0.19');
    expect(screen.getByText('Premium stop — 0.19%')).toBeInTheDocument();
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('round-trips a >=99.5% stop instead of labelling it a total loss', () => {
    // 0.997 rendered "100%" — the label for a total loss — for a stop that is
    // not one, and "100" is likewise unre-committable.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.997 }), onChange);
    expect(input.value).toBe('99.7');
    expect(screen.getByText('Premium stop — 99.7%')).toBeInTheDocument();
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('commits a real edit, and clearing the field goes back to inheriting', () => {
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.45 }), onChange);

    fireEvent.change(input, { target: { value: '30' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith({ premiumStopPct: 0.30 });

    onChange.mockClear();
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);
    // NULL, not the global's number: the position must resume tracking the
    // global rather than freeze at whatever it happens to be today.
    expect(onChange).toHaveBeenCalledWith({ premiumStopPct: null });
  });

  it('reverts an out-of-range entry rather than silently clearing the override', () => {
    // Typing 100 -- the natural way to ask for "hold it to zero" -- used to
    // drop the override and hand the position back to the (tighter) global.
    const onChange = jest.fn();
    const input = openStop(makeOptionPosition({ premiumStopPct: 0.45 }), onChange);
    fireEvent.change(input, { target: { value: '100' } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe('45');
  });
});

// ── Spec §8 test #6: the three premium-stop paths agree ─────────────────────

describe('the drawer preview, the alert engine and the backend fire at one price', () => {
  const noop = () => {};

  it.each([
    ['a set stop',      0.45, 4.20],
    ['an inherited one', null, 4.20],
  ])('%s', (_label, own, entry) => {
    useSettingsStore.setState({ premiumStopPct: 0.60 });
    const position = makeOptionPosition({ premiumStopPct: own, entryPrice: entry });

    // (1) The shared rule, which the BACKEND also implements
    //     (premium_stop.py::premium_stop_threshold_price, verified against it
    //     in backend/tests/test_premium_stop_per_position.py).
    const expected = premiumStopThresholdPrice(
      entry, resolvePremiumStopPct(own, 0.60),
    );

    // (2) The drawer's "fires at" preview, read off the rendered component.
    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText(new RegExp(`premium \\$${expected.toFixed(2)}`))).toBeInTheDocument();

    // (3) The alert engine's own threshold, which is what actually fires.
    const alerts = scanPortfolio(
      [{ ...position, currentPrice: expected }],
      { premiumStopPct: 0.60 } as Parameters<typeof scanPortfolio>[1],
    ).filter((a) => a.alertType === 'PREMIUM_STOP');
    expect(alerts).toHaveLength(1);
  });

  it('the PRINTED price is one that actually fires, when floor and round differ', () => {
    // ROUND 9 finding 9. Round 6's fix was to FLOOR this preview, because both
    // engines compare `currentPrice <= threshold` at full precision and a
    // rounded-up price advertises a level that fires nothing. The fix shipped
    // with no coverage: the two cases above both land on thresholds where
    // floor and round agree (4.20 x 0.55 = 2.31, 4.20 x 0.40 = 1.68), and step
    // (3) feeds `scanPortfolio` the UNFLOORED `expected` rather than the string
    // it just asserted -- so mutating `Math.floor` to `Math.round` in
    // EditDrawer.tsx left all 69 tests green.
    //
    // 5.20 at 0.4855 gives 2.6754: floor 2.67, round 2.68. Only 2.67 fires.
    useSettingsStore.setState({ premiumStopPct: 0.60 });
    const position = makeOptionPosition({ premiumStopPct: 0.4855, entryPrice: 5.20 });
    const exact = premiumStopThresholdPrice(5.20, 0.4855);
    expect(exact).toBeGreaterThan(2.67);
    expect(exact).toBeLessThan(2.68);   // the two candidates genuinely differ

    render(<EditDrawer position={position} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText(/premium \$2\.67/)).toBeInTheDocument();
    expect(screen.queryByText(/premium \$2\.68/)).not.toBeInTheDocument();

    // Read the price back OFF THE SCREEN and check the engine fires at it --
    // the property the preview actually promises. Feeding the unrounded
    // threshold here, as the cases above do, cannot catch a rounding defect.
    const printed = Number(
      /premium \$(\d+\.\d{2})/.exec(
        screen.getByText(/premium \$\d+\.\d{2}/).textContent ?? '',
      )![1],
    );
    const firesAtPrinted = scanPortfolio(
      [{ ...position, currentPrice: printed }],
      { premiumStopPct: 0.60 } as Parameters<typeof scanPortfolio>[1],
    ).filter((a) => a.alertType === 'PREMIUM_STOP');
    expect(firesAtPrinted).toHaveLength(1);

    // And the rounded-up price it must NOT print would have fired nothing.
    const firesAtRounded = scanPortfolio(
      [{ ...position, currentPrice: 2.68 }],
      { premiumStopPct: 0.60 } as Parameters<typeof scanPortfolio>[1],
    ).filter((a) => a.alertType === 'PREMIUM_STOP');
    expect(firesAtRounded).toHaveLength(0);
  });
});
