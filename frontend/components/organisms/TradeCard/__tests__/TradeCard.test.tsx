import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import { useRiskStore } from '@/lib/riskStore';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(),
    getStockQuote: jest.fn(),
    getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(),
    getExitPlan: jest.fn(),
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

// Feature 1 — the "Fixed % Ladder Plan" CollapsibleSection (Exit Plan +
// Sell-to-Close Plan + Risk-Reward) defaults to collapsed; any test touching
// content inside it must expand it first.
function expandLadder() {
  fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
}

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
    expandLadder();
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

  it('renders the Order Entry strip (Feature 6 — Entry Plan card was folded into this strip)', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Order type')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Max fill')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
  });

  it('renders exit plan section (inside the collapsed Fixed % Ladder Plan group)', () => {
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    expect(screen.getByText('Exit Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Time stop')).toBeInTheDocument();
  });

  beforeEach(() => {
    // Feature 1 wraps Exit Plan / Sell-to-Close Plan / Risk-Reward in a
    // CollapsibleSection whose collapsed state persists to localStorage —
    // clear it so every test starts from the deterministic default-collapsed
    // state (jsdom's window/localStorage persists across tests within one
    // file, unlike a real browser tab per test).
    window.localStorage.clear();
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
    expandLadder();
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
      expect(screen.getByText('No structural stop found')).toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

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
      // Feature 8 — once an estimate exists, the Final Recommendation card
      // (below) ALSO renders a "T20%" summary row when Monte Carlo was the
      // most recently run method, so this may legitimately match twice.
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();     // T20% Est. option
    expect(screen.getByText('$190.50')).toBeInTheDocument();   // T20% Stock price
    expect(screen.getByText('72%')).toBeInTheDocument();       // T20% Probability
    expect(screen.getByText('~5d')).toBeInTheDocument();       // T20% Expected time
    expect(screen.getByText('$193.20')).toBeInTheDocument();   // T35% Stock price
    expect(screen.getByText('not reachable')).toBeInTheDocument(); // T50% Stock price (null)
    // Feature 8 — the Final Recommendation card also renders an
    // "Invalidation probability" row once Monte Carlo is the most recently
    // run method, so "30%" may legitimately match twice.
    expect(screen.getAllByText('30%').length).toBeGreaterThanOrEqual(1); // Invalidation probability
    expect(screen.getByText('~4d')).toBeInTheDocument();       // Invalidation expected time
    // Purely additive: the premium-based invalidation must be untouched.
    expandLadder();
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$179.64');
  });

  it('sends the exit plan\'s structural+ATR stop as invalidation_price once a plan has been computed, instead of the flat scan-time stop', async () => {
    // Step 1 — compute the Arithmetic plan so exitPlan.stop.price is populated.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    const plan = {
      stop: {
        price: 185.87, source: 'structural' as const, contractPrice: 1.2,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 183.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
      },
      targets: [],
      atr: 3.5,
    };
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce(plan);

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));

    // Wait for the plan to actually land before running the estimate. (Two
    // sections render the stop price once a plan exists — the "Compute
    // Arithmetic Plan" KV list and the Final Recommendation card — so match
    // on all of them rather than assuming a single occurrence.)
    await waitFor(() => {
      expect(screen.getAllByText('$185.87').length).toBeGreaterThanOrEqual(1);
    });

    // Step 2 — run the Monte Carlo estimate. It should now send the exit
    // plan's structural+ATR stop, not the flat scan-time data.exit.invalidation
    // (179.64 on this fixture).
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

    await waitFor(() => {
      expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
        expect.objectContaining({ invalidation_price: 185.87 }),
        expect.any(AbortSignal),
      );
    });
  });

  it('shows an error message when the first-passage request fails', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockRejectedValueOnce(new Error('network error'));
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

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
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
      // Feature 8 — once an estimate exists, the Final Recommendation card
      // (below) ALSO renders a "T20%" summary row when Monte Carlo was the
      // most recently run method, so this may legitimately match twice.
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('$3.30')).toBeInTheDocument();
    // ...the % inputs show the percentages the estimate was RUN at (10, not the
    // 20 the settings default would reset them to)...
    expect(screen.getByLabelText('T1 profit target %')).toHaveValue(10);
    // ...but the structural R:R column does NOT compute from the restored
    // pair: a fifth independent audit round found that structuralBySymbol
    // (symbol-keyed) and estimatesByContract (contract-keyed) in
    // step-7-trade-card/page.tsx are independent parent caches that can each
    // be refreshed on their own schedule, so "both halves came from the same
    // restore" doesn't actually guarantee they were captured together — only
    // that they're both whatever the two caches currently hold. Computing an
    // R:R from a merely-restored pair risked silently combining a stop
    // that's since been refreshed elsewhere with a stale estimate (or the
    // reverse). The gate now requires BOTH sides independently reconfirmed
    // fresh this mount, so the cell falls back to the defensive '—'
    // placeholder instead of a number until the user's next Estimate click.
    // Not "No structural stop found" — that label specifically means
    // structuralStop === null (a completed check that found nothing), which
    // this isn't: a real (merely unconfirmed-fresh) stop is restored and
    // shown in the Exit Plan section below, just not combined into an R:R.
    expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    // Both the pre-existing "R:R vs. structural stop" cell AND Feature 2's new
    // "Structural level found" line share the same gating, so both fall back
    // to the defensive '—' placeholder here — getAllByText, not getByText.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('0.2×')).not.toBeInTheDocument();
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
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });

    // The rows render (the estimate itself succeeded)...
    await waitFor(() => {
      // Feature 8 — once an estimate exists, the Final Recommendation card
      // (below) ALSO renders a "T20%" summary row when Monte Carlo was the
      // most recently run method, so this may legitimately match twice.
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });
    // ...the stale level is gone rather than silently paired with the fresh
    // estimate...
    expect(screen.queryByText(/Structural stop — Order Block/)).not.toBeInTheDocument();
    // ...the failure is visible...
    expect(screen.getByText("Couldn't check structure — try again.")).toBeInTheDocument();
    // ...and the R:R-vs-structural-stop cell falls back to the defensive
    // placeholder instead of showing a number computed from the stale
    // $178.50/$190 pair against the fresh $7.00 estimate (which would render
    // as a specific, plausible-looking, and wrong ratio here). structuralStop
    // is cleared to `null` (not `undefined`) so the parent's cache actually
    // overwrites the stale entry — see the `.catch` handler's comment — which
    // is what makes this cell read as "unavailable" rather than "—". Both the
    // "R:R vs. structural stop" cell AND Feature 2's new "Structural level
    // found" line share this gate, so both render it — getAllByText.
    expect(screen.getAllByText('No structural stop found').length).toBeGreaterThanOrEqual(1);
  });

  it('clears to null (not undefined) so a failed refresh actually overwrites the parent cache, surviving a second navigation', async () => {
    // Regression test for a MEDIUM finding from a third independent audit
    // round: clearing to `undefined` fixed the display for THIS render, but
    // `undefined` is the exact sentinel the parent's cache reducer
    // (cacheStructural) is designed to ignore — so the stale cached entry
    // would survive untouched, and the very next navigate-away-and-back
    // would restore it again, paired with whatever firstPassageContext is
    // cached by then. `null` is a real, cacheable value (the same shape a
    // genuine "nothing found" result produces), so this asserts the
    // onFirstPassageChange-style write-back actually carries `null` out of
    // TradeCard, which is what lets the parent's cache reducer treat it as
    // a real overwrite instead of a no-op.
    const onStructuralStopChange = jest.fn();
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
    const { rerender } = render(
      <TradeCard data={mockTradeCard} onStructuralStopChange={onStructuralStopChange} />,
    );
    rerender(<TradeCard data={cachedCard} onStructuralStopChange={onStructuralStopChange} />);
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });

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
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });

    await waitFor(() => {
      // The last call after the failed refresh must carry `null`, not
      // `undefined` — that's the one distinction the parent's cache
      // reducer actually branches on.
      expect(onStructuralStopChange).toHaveBeenLastCalledWith(null, null);
    });
  });

  it('does not render a mixed-vintage R:R when a FRESH Check-structure lands next to a still-restored estimate', async () => {
    // Regression test for a MEDIUM finding from a fourth independent audit
    // round: rounds 1-3 fixed every path where structuralStop could be the
    // stale half of the pair, but nothing protected the OTHER direction —
    // firstPassage/firstPassageContext restored from cache (never refreshed
    // this visit) sitting next to a structuralStop the user just fetched
    // fresh via "Check structure" alone. structuralRR combined them exactly
    // as readily as the already-fixed cases. Round 4's fix gated structuralRR
    // on both isFreshRefs being true OR a "restored pair" exemption; round 5
    // found that exemption unsound across a second navigation and removed it
    // (see the plan's round 5 audit notes) — structuralRR now requires BOTH
    // isFreshRefs unconditionally, so a fresh check against a stale estimate
    // still satisfies neither, and no R:R renders until the user's own next
    // Estimate click (which auto-skips re-checking structure, already fresh)
    // brings both sides current. This test's assertions still hold under the
    // simplified gate — it exercises the same scenario, just via a gate with
    // one fewer branch.
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
        firstPassageContext: { premium: 2.75, delta: 0.42, targetPct: { t1: 0.20, t2: 0.35, t3: 0.50 } },
      },
    };
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    rerender(<TradeCard data={cachedCard} />);
    await waitFor(() => {
      // Feature 8 — once an estimate exists, the Final Recommendation card
      // (below) ALSO renders a "T20%" summary row when Monte Carlo was the
      // most recently run method, so this may legitimately match twice.
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });

    // A genuinely fresh "Check structure" — a very different stock price
    // than whatever the restored estimate's premium/delta were computed
    // against.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'MSFT', price: 280 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 270.0, source: 'swing_low', confidence: 60, distancePct: 3.6,
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });

    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Swing Low/)).toBeInTheDocument();
    });
    // The fresh stop is real and displayed — but nowhere does the specific
    // computed ratio appear that combining it with the still-stale estimate
    // context would produce. (stockMove=|270-280|=10, deltaEst=0.42,
    // risk=min(4.2,2.75)=2.75, reward=3.3-2.75=0.55 -> if wrongly combined
    // this would render "0.2×" — the top Risk/Reward badge legitimately
    // renders its OWN unrelated ratio elsewhere on the page, so this asserts
    // the specific wrong value's absence, not a page-wide absence of "×".)
    expect(screen.queryByText('0.2×')).not.toBeInTheDocument();
    // And the cell doesn't misreport this as "the stop sits at the current
    // price" (structuralZeroRisk) — that label means something specific and
    // this isn't it.
    expect(screen.queryByText('N/A (stop = price)')).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

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
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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

  it('fetches and surfaces the exit plan to onExitPlanChange on button click, using fresh quotes', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    const plan = {
      stop: {
        price: 180.0, source: 'structural' as const, contractPrice: 1.2,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
      },
      targets: [
        {
          rrRatio: 2.0, arithmeticPrice: 195.0, price: 195.0, tpSource: 'arithmetic' as const,
          structuralPrice: null, contractPrice: 4.5, rrModel: 'Heston repriced' as const,
          probability: 0.6, expectedDays: 8, qualityGood: true, qualityReasons: [],
          distanceDollar: null, toleranceDollar: 1.5,
        },
        {
          rrRatio: 3.0, arithmeticPrice: 204.0, price: 204.0, tpSource: 'arithmetic' as const,
          structuralPrice: null, contractPrice: 6.0, rrModel: 'Heston repriced' as const,
          probability: 0.4, expectedDays: 14, qualityGood: true, qualityReasons: [],
          distanceDollar: null, toleranceDollar: 1.5,
        },
      ],
      atr: 3.5,
    };
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce(plan);

    const onExitPlanChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onExitPlanChange={onExitPlanChange} />);
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));

    await waitFor(() => {
      expect(onExitPlanChange).toHaveBeenCalledWith(
        expect.objectContaining({ stop: expect.objectContaining({ price: 180.0 }), atr: 3.5 }),
      );
    });
    expect(api.getExitPlan).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: 'AAPL', direction: 'Bullish', entry_price: 186.1, premium: 2.75 }),
      expect.anything(),
    );
  });

  it('shows the risk-derived recommended contract size once an exit plan is computed', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    // riskPerContract = (mid 2.5 - stop.contractPrice 1.0) * 100 * 1 = $150.
    // riskBudget (account default) = portfolioValue 100000 * maxLossPerTradePct
    // 0.0375 = $3,750. 3750 / 150 = 25 exactly.
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 180.0, source: 'structural' as const, contractPrice: 1.0,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
      },
      targets: [],
      atr: 3.5,
    });

    render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));

    expect(await screen.findByText(/Risk-derived size: 25 contracts \(25\.00 exact\)/)).toBeInTheDocument();
  });

  it('audit finding 1 regression — Apply never writes contracts:0 into the shared map when the recommended size floors to 0', async () => {
    // recommendedContractSize() only returns null when riskBudget<=0 — a
    // budget that's positive but smaller than one contract's risk legitimately
    // floors `recommended` to 0. Before the fix, the Apply button had no
    // disabled guard and wrote that 0 straight into the shared per-symbol
    // Contracts map via patch()/onEditsChange, which two of the four
    // order-placement paths then read with `?? 1` — a check that does not
    // catch 0. Shrink the account's risk budget below one contract's risk to
    // force this exact scenario.
    const originalLimits = useRiskStore.getState().limits;
    act(() => {
      useRiskStore.setState({ limits: { ...originalLimits, portfolioValue: 100, maxLossPerTradePct: 0.0375 } });
    });
    try {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      // riskPerContract = (mid 2.5 - stop.contractPrice 2.0) * 100 * 1 = $50.
      // riskBudget = portfolioValue 100 * maxLossPerTradePct 0.0375 = $3.75.
      // recommended = floor(3.75 / 50) = 0.
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 180.0, source: 'structural' as const, contractPrice: 2.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [],
        atr: 3.5,
      });
      const onEditsChange = jest.fn();
      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} onEditsChange={onEditsChange} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));

      expect(await screen.findByText(/Risk-derived size: 0 contracts/)).toBeInTheDocument();

      const applyBtn = screen.getByRole('button', { name: 'Apply recommended contract size' });
      expect(applyBtn).toBeDisabled();

      fireEvent.click(applyBtn);
      // A disabled button's onClick never fires — the shared map must never
      // see contracts:0, and the always-visible Contracts field in the Order
      // Entry strip must stay at its untouched default.
      expect(onEditsChange).not.toHaveBeenCalledWith(expect.objectContaining({ contracts: 0 }));
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('1');
    } finally {
      act(() => {
        useRiskStore.setState({ limits: originalLimits });
      });
    }
  });

  it('Feature 5 — feeds an active max-loss override into the risk-derived size immediately, and surfaces it via onMaxLossOverrideChange', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    // riskPerContract = (mid 2.5 - stop.contractPrice 1.0) * 100 * 1 = $150.
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 180.0, source: 'structural' as const, contractPrice: 1.0,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
      },
      targets: [],
      atr: 3.5,
    });
    const onMaxLossOverrideChange = jest.fn();
    render(
      <TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} onMaxLossOverrideChange={onMaxLossOverrideChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    expect(await screen.findByText(/Risk-derived size: 25 contracts/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /set override/i }));
    fireEvent.click(screen.getByRole('button', { name: '$' }));
    const input = screen.getByLabelText('Max loss override value');
    fireEvent.change(input, { target: { value: '1500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply max loss override' }));

    expect(onMaxLossOverrideChange).toHaveBeenCalledWith({ mode: 'dollar', value: 1500 });
    // riskBudget is now the $1500 override, not the account default -> 1500/150 = 10 exactly.
    expect(await screen.findByText(/Risk-derived size: 10 contracts/)).toBeInTheDocument();
  });

  it('Feature 5 regression — does not carry a mid-edit max-loss override draft from the previous candidate into Apply on the new one', () => {
    // Adversarial-audit finding: MaxLossOverrideEditor's local
    // editing/draftMode/draftValue state used to live for as long as
    // TradeCard stayed mounted (it never remounts on Prev/Next — no key at
    // its own call site), so opening the editor, typing a value, and
    // switching candidates BEFORE clicking Apply left that draft sitting in
    // the still-mounted editor instance. A user who then clicked Apply while
    // looking at the NEW candidate would silently apply the OLD candidate's
    // typed value to it. The fix keys MaxLossOverrideEditor to the candidate
    // identity so it fully remounts (clean draft state) on every switch.
    const onMaxLossOverrideChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={mockTradeCard} onMaxLossOverrideChange={onMaxLossOverrideChange} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /set override/i }));
    fireEvent.click(screen.getByRole('button', { name: '$' }));
    fireEvent.change(screen.getByLabelText('Max loss override value'), { target: { value: '9999' } });
    // Deliberately do NOT click Apply — switch candidates mid-edit instead.

    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    rerender(<TradeCard data={nextCard} onMaxLossOverrideChange={onMaxLossOverrideChange} />);

    // The editor remounted for the new candidate — back to the closed
    // "Set override" state, not still showing the $9999 draft mid-edit.
    expect(screen.getByRole('button', { name: /set override/i })).toBeInTheDocument();
    expect(screen.queryByLabelText('Max loss override value')).not.toBeInTheDocument();

    // Opening and applying fresh on the new candidate must not reuse 9999 —
    // a fresh editor's default draft (0, percent mode) applies instead.
    fireEvent.click(screen.getByRole('button', { name: /set override/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply max loss override' }));
    expect(onMaxLossOverrideChange).toHaveBeenLastCalledWith({ mode: 'percent', value: 0 });
  });

  it('never surfaces the previous candidate\'s exit plan under the new contract\'s callback', async () => {
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 180.0, source: 'structural', contractPrice: 1.2, rrModel: 'Heston repriced',
        structuralSource: null, structuralConfidence: null,
        structuralPrice: null, atrFloorPrice: 175.0, distanceDollar: null,
      },
      targets: [],
      atr: 3.5,
    });
    const onChangeForAAPL = jest.fn();
    const { rerender } = render(<TradeCard data={mockTradeCard} onExitPlanChange={onChangeForAAPL} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    });
    await waitFor(() => {
      expect(onChangeForAAPL).toHaveBeenCalledWith(expect.objectContaining({ atr: 3.5 }));
    });

    // Switch to a never-computed candidate with a fresh callback, exactly as
    // the real parent does — the new contract's callback must only ever see
    // the reset sentinel, never AAPL's plan (which would cache AAPL's numbers
    // under MSFT's contract key).
    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    const onChangeForMSFT = jest.fn();
    rerender(<TradeCard data={nextCard} onExitPlanChange={onChangeForMSFT} />);

    await waitFor(() => {
      expect(onChangeForMSFT).toHaveBeenCalled();
    });
    const sawAaplPlan = onChangeForMSFT.mock.calls.some(([plan]) => plan != null);
    expect(sawAaplPlan).toBe(false);
  });

  it('clears the exit plan to null (not undefined) on a failed compute, so the parent cache is actually overwritten', async () => {
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getExitPlan as jest.Mock).mockRejectedValueOnce(new Error('network error'));

    const onExitPlanChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onExitPlanChange={onExitPlanChange} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    });

    await waitFor(() => {
      expect(onExitPlanChange).toHaveBeenLastCalledWith(null);
    });
    expect(screen.getByText(/Couldn't compute an arithmetic plan/i)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
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
    // The standalone Check Structure block (Feature 3) on the Arithmetic card
    // distinguishes this exact degenerate case (found a level, but it
    // resolves to the current price) as its own "N/A (stop = price)" state,
    // rather than rendering the source+price+distance success block.
    await waitFor(() => {
      expect(screen.getByText('N/A (stop = price)')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => {
      // Feature 8 — once an estimate exists, the Final Recommendation card
      // (below) ALSO renders a "T20%" summary row when Monte Carlo was the
      // most recently run method, so this may legitimately match twice.
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });

    // structuralRR is null when stockMove is 0 (division guard in the
    // useMemo), but the structural stop WAS found and both checks HAVE
    // completed — ProfitTargetRow's structuralZeroRisk branch distinguishes
    // this from "not checked yet", so every row shows the explicit
    // "N/A (stop = price)" placeholder rather than an actual ratio. (Not
    // asserting a page-wide absence of "×" text here — the top Risk/Reward
    // badge legitimately renders its own unrelated ratio, e.g. "2.5×".)
    // Three targets × two lines each ("Structural level found" + "R:R vs.
    // structural stop", Feature 2) plus the one standalone Check Structure
    // block above (Feature 3) = 7.
    expect(screen.getAllByText('N/A (stop = price)').length).toBe(7);
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
    expandLadder();
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => screen.getByText(/Structural stop — Order Block/));
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => screen.getAllByText('R:R vs. structural stop'));

    // The top Risk/Reward card (fixed ladder) is untouched.
    expect(screen.getByText('2.5×')).toBeInTheDocument();
    // The Sell-to-Close-Plan's own per-target R:R now uses premiumStop (1.5)
    // as its risk basis: reward=5.0-2.5=2.5, rr=2.5/1.5=1.666...→1.7.
    expect(screen.getByText('1.7x')).toBeInTheDocument();
  });

  it('renders sell-to-close plan with editable target', () => {
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    expect(screen.getByText('Sell-to-Close Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit target stock price for TP1')).toBeInTheDocument();
  });

  it('renders risk/reward ratio', () => {
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
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

  it('Feature 8 — no longer shows the historical-accuracy/contract-confidence rows on the Final Recommendation card (already shown via ScoreCardPanel above)', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.queryByText('Historical accuracy (3×ATR exit)')).not.toBeInTheDocument();
    expect(screen.queryByText('Contract confidence')).not.toBeInTheDocument();
    expect(screen.queryByText('Stock confidence')).not.toBeInTheDocument();
  });

  it('shows projected RR label with method note', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Projected R/R (+8% stock move)')).toBeInTheDocument();
    expect(screen.queryByText('R:R ratio')).not.toBeInTheDocument();
  });

  describe('Arithmetic Profit Target (Feature 3) — additional coverage', () => {
    it('renders placeholder rows for the stop and both target rows before either button is clicked', () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByText('Bottom (final stop) — not yet computed —')).toBeInTheDocument();
      expect(screen.getByText('2:1 target — not yet computed —')).toBeInTheDocument();
      expect(screen.getByText('3:1 target — not yet computed —')).toBeInTheDocument();
    });

    it('renders all 4 distinct target-comparison states, not collapsing "before" into "beyond"', async () => {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 180.0, source: 'structural' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [
          // State 1: no structural level found ahead at all.
          { rrRatio: 2.0, arithmeticPrice: 195.0, price: 195.0, tpSource: 'arithmetic' as const,
            structuralPrice: null, contractPrice: 4.5, rrModel: 'Heston repriced' as const,
            probability: 0.6, expectedDays: 8, qualityGood: true, qualityReasons: [],
            distanceDollar: null, toleranceDollar: 1.5 },
          // State 2: within tolerance -> snapped onto the structural level.
          { rrRatio: 3.0, arithmeticPrice: 204.0, price: 206.0, tpSource: 'structural_snap' as const,
            structuralPrice: 206.0, contractPrice: 6.0, rrModel: 'Heston repriced' as const,
            probability: 0.4, expectedDays: 14, qualityGood: true, qualityReasons: [],
            distanceDollar: 2.0, toleranceDollar: 3.0 },
          // State 3: outside tolerance, but still short of (before) the structural level — quality-fine.
          { rrRatio: 4.0, arithmeticPrice: 210.0, price: 210.0, tpSource: 'arithmetic' as const,
            structuralPrice: 225.0, contractPrice: 7.0, rrModel: 'Heston repriced' as const,
            probability: 0.3, expectedDays: 20, qualityGood: true, qualityReasons: [],
            distanceDollar: 15.0, toleranceDollar: 3.0 },
          // State 4: outside tolerance AND beyond the structural level — the warning case.
          { rrRatio: 5.0, arithmeticPrice: 240.0, price: 240.0, tpSource: 'arithmetic' as const,
            structuralPrice: 225.0, contractPrice: 8.0, rrModel: 'Heston repriced' as const,
            probability: 0.15, expectedDays: 30, qualityGood: false, qualityReasons: ['target_beyond_structural'],
            distanceDollar: 15.0, toleranceDollar: 3.0 },
        ],
        atr: 3.5,
      });

      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
      await screen.findByText('No structural level found ahead — nothing to compare against.');

      // Scoped to the Arithmetic card specifically — Feature 8's Final
      // Recommendation ALSO renders each target row's heading (without the
      // compare-state label or the warning glyph) once Arithmetic is the
      // most recently run method, so an unscoped query can hit ambiguous
      // matches (e.g. "4:1 target" appears in both places).
      const arithmeticSection = screen.getByText('Arithmetic Profit Target').closest('section')!;
      const within_ = within(arithmeticSection);
      expect(within_.getByText('No structural level found ahead — nothing to compare against.')).toBeInTheDocument();
      expect(within_.getByText('Within tolerance — snapped onto the structural level.')).toBeInTheDocument();
      // The distinguishing assertion: "before" must NOT read the same as "beyond".
      expect(within_.getByText('Outside tolerance — using arithmetic price, sits before the next structural level.')).toBeInTheDocument();
      expect(within_.getByText('Target sits beyond the next real structural level.')).toBeInTheDocument();
      // The warning glyph appears only on the 4th (beyond) row's heading.
      // rrRatio is a plain JS number (5.0 === 5), so it renders as "5", not "5.0".
      expect(within_.getByText('5:1 target ⚠')).toBeInTheDocument();
      expect(within_.getByText('4:1 target')).toBeInTheDocument();
    });

    it('stopJustification case 1 — structural found and won: clears the ATR floor, no widening needed', async () => {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 180.0, source: 'structural' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [],
        atr: 3.5,
      });
      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
      // getAllByText — Feature 8's Final Recommendation renders the SAME
      // justification sentence once Arithmetic becomes the most recently run
      // method, so this text legitimately appears twice; the point of this
      // test is that the sentence itself is correct, not that it's singular.
      expect((await screen.findAllByText(
        'Using structural — it already clears the ATR floor by $5.00, no widening needed',
      )).length).toBeGreaterThanOrEqual(1);
    });

    it('stopJustification case 2 — structural found but lost: widened to the ATR floor', async () => {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 175.0, source: 'atr_widened' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 179.0, atrFloorPrice: 175.0, distanceDollar: 4.0,
        },
        targets: [],
        atr: 3.5,
      });
      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
      // getAllByText — see case 1's comment: Final Recommendation renders the
      // same sentence once Arithmetic is the most recently run method.
      expect((await screen.findAllByText(
        'Structural stop $179.00 was inside the ATR floor — widened to $175.00 for a minimum-distance stop',
      )).length).toBeGreaterThanOrEqual(1);
    });

    it('stopJustification case 3 — no structural candidate at all: stop set at the ATR floor', async () => {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 175.0, source: 'atr_widened' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: null, structuralConfidence: null,
          structuralPrice: null, atrFloorPrice: 175.0, distanceDollar: null,
        },
        targets: [],
        atr: 3.5,
      });
      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
      // getAllByText — see case 1's comment: Final Recommendation renders the
      // same sentence once Arithmetic is the most recently run method.
      expect((await screen.findAllByText(
        'No structural stop found nearby — stop set at the ATR floor of $175.00',
      )).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('isDirty regression — a Contracts-only edit self-cancels once the shared per-symbol map round-trips initialContracts back to match (cosmetic-only gap; computeEditedRR never reads overlay.contracts, so R:R numbers are unaffected)', async () => {
    const onEditsChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={mockTradeCard} contracts={1} onEditsChange={onEditsChange} />,
    );

    const contractsTrigger = screen.getByLabelText('Edit Contracts');
    await act(async () => {
      fireEvent.click(contractsTrigger);
    });
    const input = screen.getByDisplayValue('1');
    await act(async () => {
      fireEvent.change(input, { target: { value: '5' } });
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    // onEditsChange fired with the new value — this is what a real page-level
    // handler (step-7-trade-card/page.tsx's handleEditsChange) uses to update
    // the shared per-symbol contracts map.
    expect(onEditsChange).toHaveBeenCalledWith(expect.objectContaining({ contracts: 5 }));

    // Simulate that page-level round-trip: the shared map updates, and the
    // new value flows back down as the `contracts` prop on the next render —
    // exactly what orderContractsBySymbol[symbol] does in production.
    await act(async () => {
      rerender(<TradeCard data={mockTradeCard} contracts={5} onEditsChange={onEditsChange} />);
    });

    // isDirty's contracts check (overlay.contracts !== initialContracts) is
    // now comparing 5 against 5 — it self-cancels. No "edited" indicator
    // appears for this Contracts-only edit, unlike every other overlay field.
    // This is a known, accepted cosmetic gap (confirmed not to affect any
    // rendered number — computeEditedRR never reads overlay.contracts).
    expect(screen.queryAllByText(/edited/).length).toBe(0);
  });

  describe('Final Recommendation (Feature 8)', () => {
    it('empty state — before any method is run, falls back to the Fixed % Ladder Plan\'s live T1/T2/T3 targets AND R:R, explicitly labeled as a default', () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByText('No method explicitly run — showing Fixed % Ladder Plan (default)')).toBeInTheDocument();
      // mockTradeCard's single target: stockPrice/targetPrice 200.02.
      expect(screen.getByText('$200.02')).toBeInTheDocument();
      expect(screen.getByText('Projected R/R (+8% stock move)')).toBeInTheDocument();
      expect(screen.getByText('2.50x')).toBeInTheDocument();
      // Neither method's own content shows.
      expect(screen.queryByText(/computed via:/)).not.toBeInTheDocument();
    });

    it('still renders the finalStatus badge, with tooltip copy that no longer references the dropped confidence rows', () => {
      render(<TradeCard data={mockTradeCard} />);
      const badge = screen.getByTestId('labeled-badge');
      expect(badge).toHaveTextContent('Final Status: PASS');
      expect(screen.queryByText(/the worse of the stock signal's historical accuracy and the contract's quality verdict below/)).not.toBeInTheDocument();
    });

    it('switches to Arithmetic\'s output (with the alert-monitoring caveat) once it is the most recently run method, with a correct HH:MM timestamp', async () => {
      (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
      (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
        price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
      });
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 180.0, source: 'structural' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [
          { rrRatio: 2.0, arithmeticPrice: 195.0, price: 195.0, tpSource: 'arithmetic' as const,
            structuralPrice: null, contractPrice: 4.5, rrModel: 'Heston repriced' as const,
            probability: 0.6, expectedDays: 8, qualityGood: true, qualityReasons: [],
            distanceDollar: null, toleranceDollar: 1.5 },
        ],
        atr: 3.5,
      });
      const fixedNow = new Date('2026-08-30T14:32:00.000Z');
      jest.useFakeTimers().setSystemTime(fixedNow);
      try {
        render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
        fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
        await screen.findByText(/computed via: Arithmetic/);
        const expectedHHMM = `${String(fixedNow.getHours()).padStart(2, '0')}:${String(fixedNow.getMinutes()).padStart(2, '0')}`;
        expect(screen.getByText(`computed via: Arithmetic, ${expectedHHMM}`)).toBeInTheDocument();
        expect(screen.getByText(
          /This stop price is not automatically monitored by alerts unless copied into the position's stop field after opening\./,
        )).toBeInTheDocument();
        // The empty-state Ladder fallback is gone now that a method has run.
        expect(screen.queryByText('No method explicitly run — showing Fixed % Ladder Plan (default)')).not.toBeInTheDocument();
      } finally {
        jest.useRealTimers();
      }
    });

    it('switches to Monte Carlo\'s output once IT is the most recently run method (no alert caveat — that\'s Arithmetic-only)', async () => {
      (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
        targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
        invalidation: { probability: 0.30, expectedDays: 4 },
      });
      render(<TradeCard data={mockTradeCard} />);
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
      await screen.findByText(/computed via: Monte Carlo/);
      expect(screen.queryByText(/not automatically monitored by alerts/)).not.toBeInTheDocument();
      expect(screen.queryByText('No method explicitly run — showing Fixed % Ladder Plan (default)')).not.toBeInTheDocument();
    });

    it('does not build any cross-method comparison — Arithmetic\'s output never references Monte Carlo/Ladder figures or vice versa', async () => {
      (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
        stop: {
          price: 180.0, source: 'structural' as const, contractPrice: 1.0,
          rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
          structuralPrice: 180.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [],
        atr: 3.5,
      });
      render(<TradeCard data={mockTradeCard} onExitPlanChange={jest.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
      await screen.findByText(/computed via: Arithmetic/);
      // No "agree"/"disagree"/"vs." reconciliation language WITHIN the Final
      // Recommendation card specifically — scoped there because the OTHER
      // method cards legitimately carry their own "...they can disagree"
      // disclaimers elsewhere on the page (Features 1/2/3), which is
      // unrelated to this card building its own comparison.
      const finalRecSection = screen.getByText('Final Recommendation').closest('section')!;
      expect(within(finalRecSection).queryByText(/disagree/i)).not.toBeInTheDocument();
      expect(within(finalRecSection).queryByText(/agrees?/i)).not.toBeInTheDocument();
    });
  });

  describe('editable fields', () => {
    it('renders editable fields with aria-label affordance', () => {
      render(<TradeCard data={mockTradeCard} />);
      expandLadder();
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
      expandLadder();
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

    it('does not show an "edited" indicator when the contracts prop seeds a non-default value (Feature 7 isDirty fix)', () => {
      // Regression test: isDirty used to compare overlay.contracts against a
      // hardcoded 1, not the initialContracts prop that seeds overlay.contracts
      // on mount. Once a shared per-symbol contracts map (Feature 7) can pass a
      // non-1 `contracts` prop, the untouched card must NOT be flagged dirty —
      // the R:R sections must show the plain (non-"edited") ratio.
      render(<TradeCard data={mockTradeCard} contracts={4} />);
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('4');
      expect(screen.queryAllByText(/edited/).length).toBe(0);
    });

    it('DOES show an "edited" indicator when contracts is hand-edited away from a non-default initial value', async () => {
      render(<TradeCard data={mockTradeCard} contracts={4} />);
      const contractsTrigger = screen.getByLabelText('Edit Contracts');
      await act(async () => {
        fireEvent.click(contractsTrigger);
      });
      const input = screen.getByDisplayValue('4');
      await act(async () => {
        fireEvent.change(input, { target: { value: '6' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.getAllByText(/edited/).length).toBeGreaterThanOrEqual(1);
    });
  });
});
describe('TradeCard — stop-vs-premium gate', () => {
  // The gate reads scan-time contractDetails (mid/delta) plus whatever
  // structural stop is available, so it renders WITHOUT the user having run an
  // Estimate or an Arithmetic plan. That early availability is the whole point:
  // a gate that only speaks after two round-trips cannot warn anyone.
  function cardWithStop(
    stop: { price: number; source: 'order_block' | 'swing_low' | 'swing_high'; confidence: number; distancePct: number },
    stockPrice: number,
    contractDetails?: Partial<NonNullable<TradeCardData['contractDetails']>>,
  ): TradeCardData {
    return {
      ...mockTradeCard,
      contractDetails: { ...mockTradeCard.contractDetails!, ...contractDetails },
      exit: { ...mockTradeCard.exit, structuralStop: stop, structuralStopStockPrice: stockPrice },
    };
  }

  const ORDER_BLOCK = { price: 178.5, source: 'order_block' as const, confidence: 75, distancePct: 3.6 };

  it('flags a stop that costs the whole premium, and shows every input behind it', () => {
    // 190.0 -> 178.5 is $11.50; x delta 0.45 = $5.175 against a $2.50 premium.
    // You cannot lose $5.18 on a $2.50 option, so it caps at $2.50 = 100%.
    render(<TradeCard data={cardWithStop(ORDER_BLOCK, 190.0)} />);

    expect(screen.getByText('STOP COST')).toBeInTheDocument();
    expect(screen.getByText('100% OF PREMIUM')).toBeInTheDocument();
    // Inputs are on screen, not just the verdict — the complaint that produced
    // this gate was a ratio whose inputs were invisible.
    expect(screen.getByText(/\$11\.50 away × Δ0\.45 = \$2\.50 of \$2\.50 premium/)).toBeInTheDocument();
    // ...including the uncapped figure, so "how far past total loss" is visible.
    // 11.50 * 0.45 === 5.175, which toFixed(2) renders "5.17" — 5.175 is stored
    // just below the exact value in IEEE754 (same class of thing the
    // formatRecommendedContractSizeRaw comments document).
    expect(screen.getByText(/uncapped \$5\.17/)).toBeInTheDocument();
 
    // The gate sorts candidates, it never refuses one -- so even a total-loss
    // stop is framed as a sizing input, not a verdict. (The "never REJECT"
    // guarantee itself is asserted on the helper in risk.test.ts; CSS modules
    // mock to {} here so the badge's colour class is not observable in jsdom.)
    expect(screen.getByText(/Not a reason to skip the trade/)).toBeInTheDocument();
  });

  it('PASSes a contract that keeps real value at the same stop', () => {
    // Same $11.50 move and delta, but a $20 premium: $5.175 / $20 = 26%.
    render(<TradeCard data={cardWithStop(ORDER_BLOCK, 190.0, { mid: 20 })} />);

    expect(screen.getByText('26% OF PREMIUM')).toBeInTheDocument();
    expect(screen.getByText(/\$11\.50 away × Δ0\.45 = \$5.17 of \$20.00 premium/)).toBeInTheDocument();
    expect(screen.queryByText(/uncapped/)).not.toBeInTheDocument();
  });

  it('renders with no Estimate and no Arithmetic plan run', () => {
    render(<TradeCard data={cardWithStop(ORDER_BLOCK, 190.0)} />);
    // Neither of the two round-trip-gated blocks is present...
    expect(screen.queryByText('R:R vs. structural stop')).not.toBeInTheDocument();
    expect(screen.queryByText('Bottom (final stop)')).not.toBeInTheDocument();
    // ...but the gate already has its verdict.
    expect(screen.getByText('STOP COST')).toBeInTheDocument();
  });

  it('stays hidden when there is no structural stop to measure against', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.queryByText('STOP COST')).not.toBeInTheDocument();
  });

  it('stays hidden when the stop sits exactly at the current price', () => {
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, price: 190.0, distancePct: 0 }, 190.0)} />);
    expect(screen.queryByText('STOP COST')).not.toBeInTheDocument();
  });
});

describe('TradeCard — Piece 2: shared stop unifies the gate and structuralRR', () => {
  // Both a raw structural stop (via Check structure) AND an exit plan (via
  // Compute Arithmetic Plan) exist for this contract, with DELIBERATELY
  // different stop.price values (178.50 raw vs. 170.00 exit-plan) and
  // different paired stock prices, so the two branches produce materially
  // different numbers if either consumer picks the wrong one. Before this
  // fix, the gate (stopRisk) and structuralRR each read the raw structural
  // pair directly — a "fifth stop" no one asked for once an Arithmetic Plan
  // existed. After the fix, both should agree on the exit-plan's stop once
  // one has been computed this mount.
  it('gate and structuralRR both use the exit-plan stop, not the raw structural stop, once an Arithmetic Plan is computed', async () => {
    // 1) Check structure — raw structural stop at $178.50, fresh stock price $182.00.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 182.0 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 80, distancePct: 1.92,
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });

    // Before any Arithmetic Plan exists, the gate reads the raw structural
    // pair: |178.50 - 182.00| = 3.50 away x delta 0.45 = $1.575 of $2.50
    // premium = 63%. Sanity-checks the pre-fix baseline before it changes.
    expect(screen.getByText('63% OF PREMIUM')).toBeInTheDocument();

    // 2) Compute Arithmetic Plan — exit-plan stop at $170.00, a DIFFERENT
    // fresh stock price ($190.00) than Check structure captured.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 190.0 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.6, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 170.0, source: 'structural' as const, contractPrice: 1.0,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 170.0, atrFloorPrice: 165.0, distanceDollar: 5.0,
      },
      targets: [],
      atr: 3.5,
    });

    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => {
      expect(screen.getAllByText('Bottom (final stop)').length).toBeGreaterThanOrEqual(1);
    });

    // The gate must now read the exit-plan pair, not the raw structural pair:
    // |170.00 - 190.00| = 20.00 away x delta 0.45 = $9.00 (uncapped) against a
    // $2.50 premium -> capped at 100%. If it had stayed on the raw pair this
    // would still read 63%.
    expect(screen.getByText('100% OF PREMIUM')).toBeInTheDocument();
    expect(screen.getByText(/\$20\.00 away × Δ0\.45 = \$2\.50 of \$2\.50 premium \(uncapped \$9\.00\)/)).toBeInTheDocument();
    expect(screen.queryByText('63% OF PREMIUM')).not.toBeInTheDocument();

    // 3) Run Monte Carlo Estimate — fresh premium/delta for firstPassageContext.
    // structuralIsFreshRef is already true from step 1, so this does NOT
    // re-fetch the structural stop.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 190.0 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 25, delta: 0.5, theta: -0.05, ivRank: 50, spread: 0.1, volume: 50,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 210.0, optionPrice: 45.0, probability: 0.6, expectedDays: 5 },
      ],
      invalidation: { probability: 0.3, expectedDays: 4 },
    });

    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => {
      expect(screen.getByText('R:R vs. structural stop')).toBeInTheDocument();
    });

    // structuralRR must also use the exit-plan pair: stockMove = |170.00 -
    // 190.00| = 20.00, deltaEst = 0.5, risk = min(20.00*0.5, 25) = 10.00,
    // reward = 45.00 - 25.00 = 20.00 -> rr = 2.0. Had it stayed on the raw
    // structural pair (178.50 vs. 182.00), stockMove would be 3.50, risk =
    // min(3.50*0.5, 25) = 1.75, giving rr = 20.00 / 1.75 = 11.4 instead.
    expect(screen.getByText('2.0×')).toBeInTheDocument();
    expect(screen.queryByText('11.4×')).not.toBeInTheDocument();

    // The "Structural level found" line (ProfitTargetRow) must also show the
    // exit-plan's price, not the raw structural stop's — "$170.00" appears at
    // least twice: once in the Arithmetic card's own "Bottom (final stop)"
    // block, once in ProfitTargetRow's "Structural level found" line.
    expect(screen.getAllByText('$170.00').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('$178.50')).not.toBeInTheDocument();
  });
});

describe('TradeCard — piece 1/2 gap: cache-restored exit plan with no fresh click this mount', () => {
  // Reproduces the CandidateNav Next-then-Prev scenario from the handoff doc:
  // the parent (step-7-trade-card/page.tsx) splices a previously-computed
  // exit plan AND a previously-fetched structural stop back into `data.exit`
  // on remount, but neither "Compute Arithmetic Plan" nor "Check structure"
  // has been clicked THIS mount, so `arithmeticLiveStockPrice` is still null
  // and `structuralIsFreshRef`/`firstPassageIsFreshRef` are both false.
  // Before the fix, the Monte Carlo request read `exitPlan?.stop.price`
  // directly and would send the restored exit-plan stop (185.87) even though
  // `sharedStop` — already used by the gate and structuralRR — refuses a
  // restored plan with no fresh stock price and falls back to the restored
  // structural stop (178.50) instead. That mismatch is exactly the "two
  // stops on one card" regression this test guards against.
  const restoredCard: TradeCardData = {
    ...mockTradeCard,
    exit: {
      ...mockTradeCard.exit,
      exitPlan: {
        computedAt: '2026-08-30T12:00:00.000Z',
        stop: {
          price: 185.87, source: 'structural', contractPrice: 1.2,
          rrModel: 'Heston repriced', structuralSource: 'order_block', structuralConfidence: 80,
          structuralPrice: 183.0, atrFloorPrice: 175.0, distanceDollar: 5.0,
        },
        targets: [],
        atr: 3.5,
      },
      structuralStop: { price: 178.5, source: 'order_block', confidence: 80, distancePct: 1.92 },
      structuralStopStockPrice: 182.0,
    },
  };

  it('sends the restored structural stop, not the restored exit-plan stop, as invalidation_price', async () => {
    // structuralIsFreshRef starts false (the structural stop above is a
    // restore, not a fetch this mount), so clicking Estimate auto-fires a
    // structural-stop sub-fetch alongside the main request — give it a
    // resolvable mock even though this test doesn't care about its result.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 80, distancePct: 1.92,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 },
      ],
      invalidation: { probability: 0.30, expectedDays: 4 },
    });

    render(<TradeCard data={restoredCard} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

    await waitFor(() => {
      expect(api.getFirstPassageEstimate).toHaveBeenCalled();
    });
    // Assert on THIS test's own call specifically (the mock's call history is
    // shared across the whole file, so `.not.toHaveBeenCalledWith` on the
    // restored exit-plan price would spuriously fail if an earlier,
    // unrelated test happened to send that same number).
    const [lastCallArgs] = (api.getFirstPassageEstimate as jest.Mock).mock.calls.at(-1)!;
    expect(lastCallArgs.invalidation_price).toBe(178.5);
  });

  it('agrees with the gate on the same restored stop', () => {
    render(<TradeCard data={restoredCard} />);
    // stopRisk: |178.50 - 182.00| = 3.50 away x delta 0.45 = $1.575 of $2.50
    // premium = 63%. If the gate had instead picked up the restored exit-plan
    // stop (185.87) it would read a different percentage here.
    expect(screen.getByText('63% OF PREMIUM')).toBeInTheDocument();
  });
});
