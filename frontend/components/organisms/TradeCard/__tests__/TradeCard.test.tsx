import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(),
    getStockQuote: jest.fn(),
    getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(),
  },
}));

jest.mock('@/components/organisms/InlineChartPanel', () => ({
  InlineChartPanel: ({ open }: { open: boolean }) => (
    <div data-testid="inline-chart" data-open={String(open)}>Chart</div>
  ),
}));

jest.mock('@/components/molecules/SymbolHeader', () => ({
  SymbolHeader: ({ ticker, company }: { ticker: string; company: string }) => (
    <div data-testid="symbol-header">{ticker} — {company}</div>
  ),
}))

jest.mock('@/components/molecules/ScoreCardPanel', () => ({
  ScoreCardPanel: ({ title }: { title: string }) => (
    <div data-testid="score-panel">{title}</div>
  ),
}));

jest.mock('@/components/molecules/LabeledStatusBadge', () => ({
  LabeledStatusBadge: ({ label, status }: { label: string; status: string }) => (
    <div data-testid="labeled-badge">{label}: {status}</div>
  ),
}));

const mockTradeCard: TradeCardData = {
  symbol: 'AAPL',
  company: 'Apple Inc.',
  price: 185.2,
  direction: 'Bullish',
  status: 'PASS',
  stockScore: 82,
  stockConfidence: 'PASS',
  stockBreakdown: {
    trend: 85,
    pullback: 78,
    trigger: 72,
    event: 90,
    volatility: 65,
  },
  contract: 'AAPL 190C 05/15',
  contractScore: 70,
  contractConfidence: 'PASS',
  contractBreakdown: {
    dteFit: 80,
    delta: 65,
    ivAttractiveness: 55,
    liquidity: 75,
    spread: 60,
  },
  contractDetails: {
    strike: 190,
    expiry: '2026-05-15',
    right: 'C',
    mid: 2.5,
    delta: 0.45,
    theta: -0.09,
    ivRank: 45,
    dte: 24,
  },
  entry: {
    limit: 2.5,
    maxFill: 2.63,
    orderType: 'Limit',
  },
  exit: {
    invalidation: 179.64,
    premiumStop: 1.5,
    timeStopDays: 10,
    target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 5.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
    ],
  },
  rrRatio: 2.5,
  rrModel: 'Heston repriced',
  finalStatus: 'PASS',
};

describe('TradeCard', () => {
  it('shows a negative per-target R:R instead of hiding the row (M2 parity)', () => {
    // Mirrors the backend's reward_risk.py M2 fix: a target priced below
    // entry (estimatedOptionPrice=1.0 < entry.limit=2.5, reward=-1.5,
    // rr=-1.5/premiumStop(1.5)=-1.0) is a real loss the trader should see,
    // not silently omitted the way `rr > 0`-gated rendering used to.
    const dataWithLosingTarget: TradeCardData = {
      ...mockTradeCard,
      exit: {
        ...mockTradeCard.exit,
        targets: [
          { id: 'tp1', stockPrice: 195.0, targetPrice: 195.0, estimatedOptionPrice: 1.0, contractsToSell: 1, status: 'PENDING', rrContribution: -1.0 },
        ],
      },
    };
    render(<TradeCard data={dataWithLosingTarget} />);
    expect(screen.getByText('-1.0x')).toBeInTheDocument();
  });

  it('renders symbol and company in header', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByTestId('symbol-header')).toHaveTextContent('AAPL — Apple Inc.');
  });

  it('renders stock and contract score panels', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Stock Scorecard')).toBeInTheDocument();
    expect(screen.getByText('Contract — AAPL 190C 05/15')).toBeInTheDocument();
  });

  it('renders contract details when provided', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Contract Details')).toBeInTheDocument();
    expect(screen.getByText('$190')).toBeInTheDocument();
    expect(screen.getByText('2026-05-15')).toBeInTheDocument();
    expect(screen.getByText('Call')).toBeInTheDocument();
    expect(screen.getByText('0.45')).toBeInTheDocument();
    expect(screen.getByText('$-0.09')).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('24d')).toBeInTheDocument();
    const mids = screen.getAllByText('$2.50');
    expect(mids.length).toBeGreaterThanOrEqual(1);
  });

  it('renders entry plan section', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Entry Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Max fill')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
  });

  it('renders exit plan section', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Exit Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Time stop')).toBeInTheDocument();
  });

  beforeEach(() => {
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: mockTradeCard.price });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    // Default: no structural stop found. Estimate now auto-triggers this
    // fetch (Task 4) whenever it hasn't already been fetched, so every test
    // that clicks "Estimate" needs a resolvable mock even if it doesn't care
    // about structural-stop content. Individual tests override with their
    // own mockResolvedValueOnce for the structural-stop-specific assertions.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
  });

  it('renders a Check structure button that does not fire on its own', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByRole('button', { name: /check structure/i })).toBeInTheDocument();
    expect(api.getStructuralStop).not.toHaveBeenCalled();
  });

  it('fetches and displays the structural stop on button click, using a fresh stock quote', async () => {
    // A price that deliberately differs from mockTradeCard.price (185.2), so the
    // assertion below proves the LIVE quote is used, not the scan-time snapshot.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    expect(api.getStockQuote).toHaveBeenCalledWith('AAPL', expect.any(AbortSignal));
    await waitFor(() => {
      expect(api.getStructuralStop).toHaveBeenCalledWith(
        { symbol: 'AAPL', direction: 'Bullish', stock_price: 186.1 },
        expect.any(AbortSignal),
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    expect(screen.getByText('$178.50 (3.6% away)')).toBeInTheDocument();
    // Purely additive: the premium-based invalidation must be untouched.
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
  });

  it('falls back to data.price when the live stock quote fetch fails', async () => {
    (api.getStockQuote as jest.Mock).mockRejectedValueOnce(new Error('quote unavailable'));
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(api.getStructuralStop).toHaveBeenCalledWith(
        { symbol: 'AAPL', direction: 'Bullish', stock_price: 185.2 },
        expect.any(AbortSignal),
      );
    });
  });

  it('shows a not-found message when no structural level is available', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/No order block or swing level found/)).toBeInTheDocument();
    });
  });

  it('shows an error message when the structural stop request fails', async () => {
    (api.getStructuralStop as jest.Mock).mockRejectedValueOnce(new Error('network error'));
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Couldn.t check structure/)).toBeInTheDocument();
    });
  });

  it('does not apply a stale structural-stop response after the contract changes', async () => {
    let resolveFirst!: (value: unknown) => void;
    const firstRequest = new Promise((resolve) => { resolveFirst = resolve; });
    (api.getStructuralStop as jest.Mock).mockReturnValueOnce(firstRequest);

    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
      // Flush the (already-resolved, per the default beforeEach mock) live
      // stock-quote fetch so getStructuralStop is actually in flight before
      // the contract switch below — otherwise the abort would fire during
      // the stock-quote leg and getStructuralStop would never even be
      // reached, which would test the wrong thing.
      await new Promise((r) => setTimeout(r, 0));
    });

    // Simulate CandidateNav switching to a different contract before the
    // in-flight request for the old one has resolved.
    const nextCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
    };
    rerender(<TradeCard data={nextCard} />);

    // The stale request now settles — it must be ignored, not shown for MSFT.
    await act(async () => {
      resolveFirst({ available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 });
    });

    expect(screen.queryByText(/Structural stop — Order Block/)).not.toBeInTheDocument();
  });

  it('does not surface the previous candidate\'s structural stop to the new one after switching', async () => {
    // Regression test: the parent (step-7-trade-card/page.tsx) passes a fresh
    // onStructuralStopChange closure on every render, bound to whichever
    // symbol is currently active — CandidateNav's Prev/Next changes `data`
    // AND that closure in the same commit, one render before the
    // contract-change effect resets local `structuralStop` state back to
    // undefined. A version of this wiring that read the callback straight out
    // of props (instead of via a ref updated in its own effect) fired the
    // surfacing effect using THAT commit's new-symbol callback together with
    // the STILL-STALE old-symbol structuralStop value, silently attaching the
    // previous candidate's price to the new one.
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    const onChangeForAAPL = jest.fn();
    const { rerender } = render(<TradeCard data={mockTradeCard} onStructuralStopChange={onChangeForAAPL} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });
    await waitFor(() => {
      // Second arg is the fresh stock price the level was measured against —
      // 185.2 here, from the default getStockQuote mock in beforeEach. The
      // parent caches the pair, so this assertion pins both halves.
      expect(onChangeForAAPL).toHaveBeenCalledWith(expect.objectContaining({ price: 178.5 }), 185.2);
    });

    // Switch to a different, never-checked candidate — a fresh callback,
    // exactly as the real parent would pass.
    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    const onChangeForMSFT = jest.fn();
    rerender(<TradeCard data={nextCard} onStructuralStopChange={onChangeForMSFT} />);

    await waitFor(() => {
      expect(onChangeForMSFT).toHaveBeenCalled();
    });
    // Asserted over the recorded calls rather than with `.not.toHaveBeenCalledWith`,
    // which matches on the full argument list and would therefore pass vacuously
    // for any future arity change — the exact way this regression test could go
    // quietly dead.
    const sawAaplStop = onChangeForMSFT.mock.calls.some(
      ([stop]) => (stop as { price?: number } | null | undefined)?.price === 178.5,
    );
    expect(sawAaplStop).toBe(false);
  });

  it('renders an Estimate button that does not fire on its own', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByRole('button', { name: /^estimate$/i })).toBeInTheDocument();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
  });

  it('fetches and displays the first-passage estimate on button click, using fresh quotes', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 },
        { pct: 0.35, stockPrice: 193.2, optionPrice: 3.71, probability: 0.55, expectedDays: 9 },
        { pct: 0.50, stockPrice: null, optionPrice: 4.13, probability: 0.10, expectedDays: null },
      ],
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));

    await waitFor(() => {
      expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
        {
          symbol: 'AAPL',
          direction: 'Bullish',
          stock_price: 186.1,
          strike: 190,
          dte: 24,
          premium: 2.75,
          delta: 0.42,
          trend_score: 85,
          invalidation_price: 179.64,
          t1_pct: 0.20,
          t2_pct: 0.35,
          t3_pct: 0.50,
        },
        expect.any(AbortSignal),
      );
    });
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();     // T20% Est. option
    expect(screen.getByText('$190.50')).toBeInTheDocument();   // T20% Stock price
    expect(screen.getByText('72%')).toBeInTheDocument();       // T20% Probability
    expect(screen.getByText('~5d')).toBeInTheDocument();       // T20% Expected time
    expect(screen.getByText('$193.20')).toBeInTheDocument();   // T35% Stock price
    expect(screen.getByText('not reachable')).toBeInTheDocument(); // T50% Stock price (null)
    expect(screen.getByText('30%')).toBeInTheDocument();       // Invalidation probability
    expect(screen.getByText('~4d')).toBeInTheDocument();       // Invalidation expected time
    // Purely additive: the premium-based invalidation must be untouched.
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
  });

  it('shows an error message when the first-passage request fails', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockRejectedValueOnce(new Error('network error'));
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getByText(/Couldn.t compute an estimate/)).toBeInTheDocument();
    });
  });

  it('lets the user edit T1/T2/T3 percentages before estimating', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.10, stockPrice: 188.0, optionPrice: 2.75, probability: 0.8, expectedDays: 3 },
        { pct: 0.35, stockPrice: 193.2, optionPrice: 3.71, probability: 0.55, expectedDays: 9 },
        { pct: 0.50, stockPrice: 196.0, optionPrice: 4.13, probability: 0.30, expectedDays: 14 },
      ],
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.change(screen.getByLabelText('T1 profit target %'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));

    await waitFor(() => {
      expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
        expect.objectContaining({ t1_pct: 0.10, t2_pct: 0.35, t3_pct: 0.50 }),
        expect.any(AbortSignal),
      );
    });
  });

  it('does not apply a stale first-passage response after the contract changes', async () => {
    let resolveFirst!: (value: unknown) => void;
    const firstRequest = new Promise((resolve) => { resolveFirst = resolve; });
    (api.getFirstPassageEstimate as jest.Mock).mockReturnValueOnce(firstRequest);

    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
      await new Promise((r) => setTimeout(r, 0));
    });

    const nextCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
    };
    rerender(<TradeCard data={nextCard} />);

    await act(async () => {
      resolveFirst({
        targets: [
          { pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 },
          { pct: 0.35, stockPrice: 193.2, optionPrice: 3.71, probability: 0.55, expectedDays: 9 },
          { pct: 0.50, stockPrice: 196.0, optionPrice: 4.13, probability: 0.30, expectedDays: 14 },
        ],
        invalidation: { probability: 0.30, expectedDays: 4 },
      });
    });

    expect(screen.queryByText('T20%')).not.toBeInTheDocument();
  });

  it('restores a cached first-passage estimate from data.exit on a contract switch, without refetching', async () => {
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    // The api mocks in this file are NEVER cleared between tests (no
    // clearMocks in jest.config.ts, no jest.clearAllMocks() in beforeEach), so
    // `expect(api.X).not.toHaveBeenCalled()` would fail here purely because
    // EARLIER tests in this file already called all three. Snapshot the counts
    // and assert they don't move — which is the real claim anyway: restoring
    // from the cache issues no NEW request.
    const callsBefore = {
      firstPassage:   (api.getFirstPassageEstimate as jest.Mock).mock.calls.length,
      structuralStop: (api.getStructuralStop as jest.Mock).mock.calls.length,
      stockQuote:     (api.getStockQuote as jest.Mock).mock.calls.length,
    };

    // Simulate CandidateNav switching to a contract the parent HAS a cached
    // estimate for — the parent splices it (and its context) into exit.*, the
    // exact fields TradeCard's contract-change reset already reads.
    const cachedCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        firstPassage: {
          targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
          invalidation: { probability: 0.30, expectedDays: 4 },
        },
        firstPassageContext: { premium: 2.75, delta: 0.42, targetPct: { t1: 0.10, t2: 0.35, t3: 0.50 } },
        structuralStop: { price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 },
        structuralStopStockPrice: 190.0,
      },
    };
    rerender(<TradeCard data={cachedCard} />);

    // Rows are back. The restore happens inside the contract-change useEffect,
    // whose setState schedules a further render — waitFor rather than a bare
    // sync assertion, matching how every other post-effect assertion in this
    // file is written.
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();
    // ...the % inputs show the percentages the estimate was RUN at (10, not the
    // 20 the settings default would reset them to)...
    expect(screen.getByLabelText('T1 profit target %')).toHaveValue(10);
    // ...and the structural R:R column is computed, not stuck on the
    // "not yet checked" placeholder: stockMove = |178.5 - 190| = 11.5,
    // deltaEst = 0.42, risk = min(11.5 * 0.42, 2.75) = min(4.83, 2.75) = 2.75
    // (clamped to premium), reward = 3.3 - 2.75 = 0.55 -> rr = 0.2.
    expect(screen.getByText('0.2×')).toBeInTheDocument();
    // Nothing was re-fetched to get any of that back.
    expect((api.getFirstPassageEstimate as jest.Mock).mock.calls.length).toBe(callsBefore.firstPassage);
    expect((api.getStructuralStop as jest.Mock).mock.calls.length).toBe(callsBefore.structuralStop);
    expect((api.getStockQuote as jest.Mock).mock.calls.length).toBe(callsBefore.stockQuote);
  });

  it('does not let a restored (possibly stale) structural stop suppress a fresh re-check on the next Estimate click', async () => {
    // Regression test for a HIGH finding from independent post-implementation
    // review: estimateFirstPassage's auto-trigger for the structural-stop
    // fetch used to gate on `structuralStop === undefined`, which was only
    // ever true for "genuinely never fetched" before caching existed. Once a
    // cached value can populate that field on restore, the same condition is
    // false for a value that could be hours old, so the auto-trigger silently
    // stopped refreshing it — the eventual R:R-vs-structural-stop calc then
    // permanently combined a stale check-time price with a fresh
    // estimate-time premium. structuralIsFreshRef fixes this: a restored
    // value still renders immediately (no blank flash) but is never treated
    // as "already fetched this mount", so the next Estimate click always
    // fires a real refresh.
    const cachedCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        structuralStop: { price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 },
        structuralStopStockPrice: 190.0,
      },
    };
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    rerender(<TradeCard data={cachedCard} />);

    // The restored (possibly stale) level is on screen immediately.
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });

    const callsBefore = (api.getStructuralStop as jest.Mock).mock.calls.length;

    // A fresh check, at a very different price, is what a real re-check
    // would now find.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'MSFT', price: 300 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 40, spread: 0.1, volume: 50,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 295.0, source: 'swing_low', confidence: 60, distancePct: 1.7,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.20, stockPrice: 310, optionPrice: 7.0, probability: 0.6, expectedDays: 6 }],
      invalidation: { probability: 0.25, expectedDays: 5 },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    });

    // The restored value's presence did NOT suppress the refetch — this is
    // the actual regression: before the fix this call count would never move.
    await waitFor(() => {
      expect((api.getStructuralStop as jest.Mock).mock.calls.length).toBe(callsBefore + 1);
    });
    // The stale $178.50 order-block level is fully replaced by the fresh
    // $295 swing-low level, not merely appended alongside it.
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Swing Low/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Structural stop — Order Block/)).not.toBeInTheDocument();
  });

  it('does not render a mixed-vintage R:R when the post-restore refresh fails', async () => {
    // Companion regression test, found in a follow-up independent audit of
    // the fix above: the auto-refresh's failure path must not leave the
    // stale, cache-restored structuralStop sitting next to firstPassageContext
    // once THAT has moved on to this click's fresh premium/delta — otherwise
    // structuralRR silently combines an hours-old stock move with a
    // seconds-old option price, which is the exact bug the fix exists to
    // prevent, just reachable via the error path instead of the happy path.
    const cachedCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        structuralStop: { price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6 },
        structuralStopStockPrice: 190.0,
      },
    };
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    rerender(<TradeCard data={cachedCard} />);
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });

    // The refresh this Estimate click triggers fails; the estimate itself
    // still succeeds, so firstPassageContext gets a fresh premium/delta
    // while the structural refresh comes back empty-handed.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'MSFT', price: 300 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 40, spread: 0.1, volume: 50,
    });
    (api.getStructuralStop as jest.Mock).mockRejectedValueOnce(new Error('network error'));
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.20, stockPrice: 310, optionPrice: 7.0, probability: 0.6, expectedDays: 6 }],
      invalidation: { probability: 0.25, expectedDays: 5 },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    });

    // The rows render (the estimate itself succeeded)...
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });
    // ...the stale level is gone rather than silently paired with the fresh
    // estimate...
    expect(screen.queryByText(/Structural stop — Order Block/)).not.toBeInTheDocument();
    // ...the failure is visible...
    expect(screen.getByText("Couldn't check structure — try again.")).toBeInTheDocument();
    // ...and the R:R-vs-structural-stop cell falls back to the defensive
    // placeholder instead of showing a number computed from the stale
    // $178.50/$190 pair against the fresh $7.00 estimate (which would render
    // as a specific, plausible-looking, and wrong ratio here).
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('surfaces a completed first-passage estimate and its context to onFirstPassageChange', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    const estimate = {
      targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
      invalidation: { probability: 0.30, expectedDays: 4 },
    };
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce(estimate);

    const onFirstPassageChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onFirstPassageChange={onFirstPassageChange} />);
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));

    await waitFor(() => {
      expect(onFirstPassageChange).toHaveBeenCalledWith(
        expect.objectContaining({ targets: estimate.targets }),
        // Fresh quote values, plus the % trio the request actually carried —
        // this pair is what the parent caches per contract.
        { premium: 2.75, delta: 0.42, targetPct: { t1: 0.20, t2: 0.35, t3: 0.50 } },
      );
    });
  });

  it('never surfaces the previous candidate\'s estimate under the new contract\'s callback', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
      invalidation: { probability: 0.30, expectedDays: 4 },
    });
    const onChangeForAAPL = jest.fn();
    const { rerender } = render(<TradeCard data={mockTradeCard} onFirstPassageChange={onChangeForAAPL} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    });
    await waitFor(() => {
      expect(onChangeForAAPL).toHaveBeenCalledWith(
        expect.objectContaining({ targets: expect.any(Array) }),
        expect.objectContaining({ premium: expect.any(Number) }),
      );
    });

    // Switch to a never-estimated candidate with a fresh callback, exactly as
    // the real parent does — the new contract's callback must only ever see the
    // reset sentinel, never AAPL's estimate (which would cache AAPL's premiums
    // under MSFT's contract key).
    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    const onChangeForMSFT = jest.fn();
    rerender(<TradeCard data={nextCard} onFirstPassageChange={onChangeForMSFT} />);

    await waitFor(() => {
      expect(onChangeForMSFT).toHaveBeenCalled();
    });
    const sawAaplEstimate = onChangeForMSFT.mock.calls.some(([estimate]) => estimate != null);
    expect(sawAaplEstimate).toBe(false);
  });

  it('shows no Profit Targets rows (and no stale two-click hint) until Estimate has been run', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    // Check structure alone (no Estimate click yet) — no Profit Targets rows,
    // no leftover "click both" hint text (removed as part of this redesign).
    expect(screen.queryByText(/Check structure and Estimate first/)).not.toBeInTheDocument();
    expect(screen.queryByText(/R:R vs\. structural stop/)).not.toBeInTheDocument();
    expect(screen.queryByText('T20%')).not.toBeInTheDocument();
  });

  it('computes R:R vs structural stop using the FRESH quotes, not the stale scan-time values', async () => {
    // Deliberately different from mockTradeCard.price (185.2) and
    // contractDetails.mid/delta (2.5/0.45) — if the component fell back to
    // those stale values instead of the fresh ones both handlers fetch, the
    // R:R below would come out as 4.2x (stale price) or 2.5x (stale premium)
    // instead of the correct 2.0x.
    (api.getStockQuote as jest.Mock)
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 })   // checkStructure's fetch
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 });  // estimateFirstPassage's fetch
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 190.0, source: 'order_block', confidence: 80, distancePct: 5.0,
    });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 50, spread: 0.1, volume: 10,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 15.0, probability: 0.6, expectedDays: 5 },
        { pct: 0.35, stockPrice: 220.0, optionPrice: 18.0, probability: 0.4, expectedDays: 9 },
        { pct: 0.50, stockPrice: 230.0, optionPrice: 21.0, probability: 0.2, expectedDays: 14 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getAllByText('R:R vs. structural stop').length).toBe(3);
    });

    // stockMove = |190 - 200| = 10; deltaEst = 0.5; risk = 5.0
    // T1: reward = 15.0 - 5.0 = 10.0 -> rr = 2.0
    // T2: reward = 18.0 - 5.0 = 13.0 -> rr = 2.6
    // T3: reward = 21.0 - 5.0 = 16.0 -> rr = 3.2
    expect(screen.getByText('2.0×')).toBeInTheDocument();
    expect(screen.getByText('2.6×')).toBeInTheDocument();
    expect(screen.getByText('3.2×')).toBeInTheDocument();
  });

  it('shows a negative structural-stop R:R instead of "—" (M2 parity)', async () => {
    // Mirrors the backend's reward_risk.py M2 fix: a target whose estimated
    // option price falls below the premium paid (a real loss against the
    // structural stop) must show the negative ratio, not "—" (which reads as
    // "not yet computed" — indistinguishable from the two-checks-pending hint
    // shown before Check Structure/Estimate have even run).
    (api.getStockQuote as jest.Mock)
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 })
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 190.0, source: 'order_block', confidence: 80, distancePct: 5.0,
    });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 50, spread: 0.1, volume: 10,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 3.0, probability: 0.6, expectedDays: 5 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getAllByText('R:R vs. structural stop').length).toBeGreaterThanOrEqual(1);
    });

    // stockMove = |190 - 200| = 10; deltaEst = 0.5; risk = 5.0
    // reward = 3.0 - 5.0 = -2.0 -> rr = -0.4
    expect(screen.getByText('-0.4×')).toBeInTheDocument();
  });

  it('clamps structural-stop risk to the option premium instead of the uncapped delta approximation', async () => {
    // stockMove = |150 - 200| = 50; deltaEst = 0.5 -> uncapped risk = 25.0,
    // which is more than a long option could ever actually lose (premium
    // paid = 5.0). If the clamp regressed to the uncapped value, T1's R:R
    // would read 0.4x instead of 2.0x -- these are far enough apart that a
    // clamp regression can't hide as a rounding difference.
    (api.getStockQuote as jest.Mock)
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 })   // checkStructure's fetch
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 });  // estimateFirstPassage's fetch
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 150.0, source: 'order_block', confidence: 80, distancePct: 25.0,
    });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 50, spread: 0.1, volume: 10,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 15.0, probability: 0.6, expectedDays: 5 },
        { pct: 0.35, stockPrice: 220.0, optionPrice: 18.0, probability: 0.4, expectedDays: 9 },
        { pct: 0.50, stockPrice: 230.0, optionPrice: 21.0, probability: 0.2, expectedDays: 14 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getAllByText('R:R vs. structural stop').length).toBeGreaterThanOrEqual(1);
    });

    // risk = min(50 * 0.5, 5.0) = 5.0 (clamped, not 25.0)
    // T1: reward = 15.0 - 5.0 = 10.0 -> rr = 10.0 / 5.0 = 2.0
    expect(screen.getByText('2.0×')).toBeInTheDocument();
    expect(screen.queryByText('0.4×')).not.toBeInTheDocument();
  });

  it('shows — instead of dividing by zero when the structural stop equals the fresh stock price', async () => {
    (api.getStockQuote as jest.Mock)
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 190.0 })
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 190.0 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 190.0, source: 'order_block', confidence: 80, distancePct: 0.0,
    });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 50, spread: 0.1, volume: 10,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 15.0, probability: 0.6, expectedDays: 5 },
        { pct: 0.35, stockPrice: 220.0, optionPrice: 18.0, probability: 0.4, expectedDays: 9 },
        { pct: 0.50, stockPrice: 230.0, optionPrice: 21.0, probability: 0.2, expectedDays: 14 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => {
      expect(screen.getByText('T20%')).toBeInTheDocument();
    });

    // structuralRR is null when stockMove is 0 (division guard in the
    // useMemo), but the structural stop WAS found and both checks HAVE
    // completed — ProfitTargetRow's structuralZeroRisk branch distinguishes
    // this from "not checked yet", so every row shows the explicit
    // "N/A (stop = price)" placeholder rather than an actual ratio. (Not
    // asserting a page-wide absence of "×" text here — the top Risk/Reward
    // badge legitimately renders its own unrelated ratio, e.g. "2.5×".)
    expect(screen.getAllByText('N/A (stop = price)').length).toBe(3);
  });

  it('does not affect the original R:R card or the sell-to-close R:R column', async () => {
    (api.getStockQuote as jest.Mock)
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 })
      .mockResolvedValueOnce({ symbol: 'AAPL', price: 200.0 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 190.0, source: 'order_block', confidence: 80, distancePct: 5.0,
    });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 5.0, delta: 0.5, theta: -0.1, ivRank: 50, spread: 0.1, volume: 10,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 15.0, probability: 0.6, expectedDays: 5 },
        { pct: 0.35, stockPrice: 220.0, optionPrice: 18.0, probability: 0.4, expectedDays: 9 },
        { pct: 0.50, stockPrice: 230.0, optionPrice: 21.0, probability: 0.2, expectedDays: 14 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => screen.getByText(/Structural stop — Order Block/));
    fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
    await waitFor(() => screen.getAllByText('R:R vs. structural stop'));

    // The top Risk/Reward card (fixed ladder) is untouched.
    expect(screen.getByText('2.5×')).toBeInTheDocument();
    // The Sell-to-Close-Plan's own per-target R:R now uses premiumStop (1.5)
    // as its risk basis: reward=5.0-2.5=2.5, rr=2.5/1.5=1.666...→1.7.
    expect(screen.getByText('1.7x')).toBeInTheDocument();
  });

  it('renders sell-to-close plan with editable target', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Sell-to-Close Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit target stock price for TP1')).toBeInTheDocument();
  });

  it('renders risk/reward ratio', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Risk / Reward')).toBeInTheDocument();
    expect(screen.getByText('2.5×')).toBeInTheDocument();
  });

  it('renders final status', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByTestId('labeled-badge')).toHaveTextContent('Final Status: PASS');
  });

  it('shows send-to-broker button disabled when no handler provided', () => {
    render(<TradeCard data={mockTradeCard} />);
    const btn = screen.getByRole('button', { name: /send to broker/i });
    expect(btn).toBeDisabled();
  });

  it('shows send-to-broker button enabled when handler provided', () => {
    const onSend = jest.fn();
    render(<TradeCard data={mockTradeCard} onSendToBroker={onSend} />);
    const btn = screen.getByRole('button', { name: /send to broker/i });
    expect(btn).toBeEnabled();
  });

  it('uses custom send label when provided', () => {
    render(<TradeCard data={mockTradeCard} onSendToBroker={() => {}} sendLabel="Send (3)" />);
    expect(screen.getByRole('button', { name: /send \(3\)/i })).toBeInTheDocument();
  });

  it('toggles chart visibility on button click', async () => {
    render(<TradeCard data={mockTradeCard} />);
    const chart = screen.getByTestId('inline-chart');
    expect(chart).toHaveAttribute('data-open', 'false');

    const btn = screen.getByRole('button', { name: /view chart/i });
    await act(async () => {
      btn.click();
    });

    expect(screen.getByTestId('inline-chart')).toHaveAttribute('data-open', 'true');
    expect(screen.getByRole('button', { name: /hide chart/i })).toBeInTheDocument();
  });

  it('shows historical accuracy label for confidence row', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Historical accuracy (3×ATR exit)')).toBeInTheDocument();
    expect(screen.queryByText('Stock confidence')).not.toBeInTheDocument();
  });

  it('shows projected RR label with method note', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Projected R/R (+8% stock move)')).toBeInTheDocument();
    expect(screen.queryByText('R:R ratio')).not.toBeInTheDocument();
  });

  describe('editable fields', () => {
    it('renders editable fields with aria-label affordance', () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Max fill')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Time stop')).toBeInTheDocument();
    });

    it('opens inline input when clicking editable limit field', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      expect(screen.getByDisplayValue('2.5')).toBeInTheDocument();
      expect(screen.getByDisplayValue('2.5')).toHaveAttribute('type', 'number');
    });

    it('saves edited value on blur', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.50' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$3.50');
    });

    it('saves edited value on Enter key', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '4.00' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$4.00');
    });

    it('cancels edit on Escape key', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '99.99' } });
        fireEvent.keyDown(input, { key: 'Escape' });
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$2.50');
    });

    it('updates R:R section to show edited model when entry limit changes', async () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getAllByText('Heston repriced').length).toBeGreaterThanOrEqual(1);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '5.0' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getAllByText(/Edit \(delta approx\)/).length).toBeGreaterThanOrEqual(1);
    });

    it('shows edited badge in target row when stock price is changed', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const targetTrigger = screen.getByLabelText('Edit target stock price for TP1');
      await act(async () => {
        fireEvent.click(targetTrigger);
      });
      const input = screen.getByDisplayValue('200.02');
      await act(async () => {
        fireEvent.change(input, { target: { value: '210.00' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByText('edited')).toBeInTheDocument();
    });

    it('updates contracts display', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const contractsTrigger = screen.getByLabelText('Edit Contracts');
      await act(async () => {
        fireEvent.click(contractsTrigger);
      });
      const input = screen.getByDisplayValue('1');
      await act(async () => {
        fireEvent.change(input, { target: { value: '5' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('5');
    });

    it('clamps entry limit to minimum 0.01 on save', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '0.001' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$0.01');
    });

    it('clamps contracts to minimum 1 on save', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const contractsTrigger = screen.getByLabelText('Edit Contracts');
      await act(async () => {
        fireEvent.click(contractsTrigger);
      });
      const input = screen.getByDisplayValue('1');
      await act(async () => {
        fireEvent.change(input, { target: { value: '0' } });
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('1');
    });

    it('fires onEditsChange callback when overlay changes', async () => {
      const onEditsChange = jest.fn();
      render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.0' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(onEditsChange).toHaveBeenCalledWith(
        expect.objectContaining({ entryLimit: 3.0 }),
      );
    });

    it('shows edited indicator in R:R sections when values differ from original', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '3.50' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      const editedLabels = screen.getAllByText(/edited/);
      expect(editedLabels.length).toBeGreaterThanOrEqual(1);
    });
  });
});