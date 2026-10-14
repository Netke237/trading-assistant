import '@testing-library/jest-dom';
import * as React from 'react';
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { api } from '@/lib/api';
import { useRiskStore } from '@/lib/riskStore';
import { useScanStore } from '@/lib/scanStore';
import { premiumStopDollarToSend } from '@/lib/premiumStop';
import type { TradeCardData, StopCostOut } from '@/types/domain';

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
  ScoreCardPanel: jest.fn(({ title }: { title: string }) => (
    <div data-testid="score-panel">{title}</div>
  )),
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
  // IDEMPOTENT. The section's toggle collapses it again, and its collapsed
  // state persists to localStorage, so a bare click is only "expand" if you
  // know what every earlier call in the file did. Round 7 finding 17 is the
  // same hazard in the page-level suite.
  // P2-21 (R1-1): the Exit Plan is always visible now, so the sentinel is a
  // heading that still lives INSIDE the collapsible group.
  if (screen.queryByText('Sell-to-Close Plan')) return;
  fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
}

describe('TradeCard', () => {
  beforeEach(() => {
    // CollapsibleSection persists `bamendjou:tradecard-ladder-collapsed`, and
    // jest.setup.ts never clears storage between tests, so without this the
    // ladder's starting state depends on test ORDER.
    localStorage.clear();
  });

  it('shows one initial ladder ahead of order inputs and preserves restored collapse preference', () => {
    const { unmount } = render(<TradeCard data={mockTradeCard} />);
    const ladder = screen.getByRole('region', { name: 'Fixed ladder targets' });
    const order = screen.getByRole('region', { name: 'Order inputs & risk budget' });
    expect(ladder.compareDocumentPosition(order) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Edit target stock price for TP1' })).toHaveLength(1);
    expect(within(ladder).getByText(/Scan-plan targets and stored option estimates/)).toBeInTheDocument();
    unmount();
    localStorage.setItem('bamendjou:tradecard-ladder-collapsed', '1');
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.queryByRole('region', { name: 'Fixed ladder targets' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Fixed % Ladder Plan/ })).toHaveAttribute('aria-expanded', 'false');
  });

  it.each([
    [5.0049, '$750.00', '$250.00'],
    [1, '$-450.00', '$-150.00'],
    [2.5, '$0.00', '$0.00'],
    [0, '$-750.00', '$-250.00'],
    [undefined, 'Unavailable', 'Unavailable'],
  ])('keeps full-position and rung outcomes separate for option premium %s', (premium, full, rung) => {
    const data = { ...mockTradeCard, exit: { ...mockTradeCard.exit, targets: [{
      ...mockTradeCard.exit.targets[0], estimatedOptionPrice: premium, contractsToSell: 1,
    }] } };
    render(<TradeCard data={data} contracts={3} />);
    const ladder = screen.getByRole('region', { name: 'Fixed ladder targets' });
    expect(within(ladder).getByText('Full-position outcome (3 contracts × 100 shares)').parentElement).toHaveTextContent(full);
    expect(within(ladder).getByText('Rung outcome (1 contracts × 100 shares)').parentElement).toHaveTextContent(rung);
    expect(within(ladder).getByText('Scale out: sell 1 of 3')).toBeInTheDocument();
    expect(within(ladder).getByText(/do not add alternative outcomes/)).toBeInTheDocument();
  });

  it('does not assume a rung allocation when the restored plan has none', () => {
    const data = { ...mockTradeCard, exit: { ...mockTradeCard.exit, targets: [{
      ...mockTradeCard.exit.targets[0], contractsToSell: undefined,
    }] } };
    render(<TradeCard data={data} contracts={3} />);
    expect(screen.getByText('Rung outcome (allocation unavailable)').parentElement).toHaveTextContent('Unavailable');
  });

  it('keeps the same editable ladder state and local pricing approximation without running a model', () => {
    const onEditsChange = jest.fn();
    jest.clearAllMocks();
    render(<TradeCard data={mockTradeCard} contracts={3} onEditsChange={onEditsChange} />);
    const ladder = screen.getByRole('region', { name: 'Fixed ladder targets' });
    fireEvent.click(within(ladder).getByRole('button', { name: 'Edit target stock price for TP1' }));
    const input = within(ladder).getByRole('spinbutton', { name: 'Edit target stock price for TP1' });
    fireEvent.change(input, { target: { value: '201' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(within(ladder).getByText('edited')).toBeInTheDocument();
    expect(onEditsChange).toHaveBeenCalledWith(expect.objectContaining({ targets: [201] }), expect.anything());
    // Existing local formula: 2.5 + 0.5 * abs(201 - 185.2) = 10.40.
    expect(within(ladder).getByText('Full-position outcome (3 contracts × 100 shares)').parentElement).toHaveTextContent('$2370.00');
    expect(api.getExitPlan).not.toHaveBeenCalled();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
  });

  it('shows a negative per-target R:R instead of hiding the row (M2 parity)', () => {
    // Mirrors the backend's reward_risk.py M2 fix: a target priced below
    // entry (estimatedOptionPrice=1.0 < entry.limit=2.5, reward=-1.5,
    // rr=-1.5/full premium(2.5)=-0.6) is a real loss the trader should see,
    // not silently omitted the way `rr > 0`-gated rendering used to.
    // Re-pinned by TRADING-REVIEW-PHASE-C-RR: the risk leg is the full premium
    // (was -1.5/premiumStop(1.5) = -1.0x).
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
    expect(screen.getByText('-0.6x')).toBeInTheDocument();
  });

  it('keeps contract snapshot basis and numeric details together in selected context', () => {
    render(<TradeCard data={mockTradeCard} liveMid={7.5} liveStockPrice={220} />);
    const context = screen.getByRole('region', { name: 'Selected stock and contract' });
    expect(within(context).getByTestId('symbol-header')).toHaveTextContent('AAPL — Apple Inc.');
    expect(within(context).getByText('Contract Details')).toBeInTheDocument();
    expect(within(context).getByText('Contract snapshot')).toBeInTheDocument();
    expect(within(context).getByText('IV RANK')).toBeInTheDocument();
    expect(within(context).getByText('45')).toBeInTheDocument();
    const mid = within(context).getByText('MID').parentElement!;
    expect(mid).toHaveTextContent('$2.50');
    expect(mid).not.toHaveTextContent('$7.50');
    expect(within(context).getByText('CAR').parentElement).toHaveTextContent('$250');
  });

  it('preserves absolute IV and missing details without substituting rank or live mid', () => {
    const { rerender } = render(<TradeCard data={{ ...mockTradeCard, contractDetails: {
      ...mockTradeCard.contractDetails!, ivRank: null, iv: 38,
    } }} />);
    const context = screen.getByRole('region', { name: 'Selected stock and contract' });
    expect(within(context).getByText('IV')).toBeInTheDocument();
    expect(within(context).getByText('38.0%')).toBeInTheDocument();
    expect(within(context).queryByText('IV RANK')).not.toBeInTheDocument();
    rerender(<TradeCard data={{ ...mockTradeCard, contractDetails: undefined }} liveMid={7.5} />);
    expect(within(context).getAllByText(mockTradeCard.contract).length).toBeGreaterThan(0);
    expect(within(context).queryByText('Contract Details')).not.toBeInTheDocument();
    expect(within(context).queryByText('CAR')).not.toBeInTheDocument();
  });

  it('keeps conditional spread values and alternative reasons in the same selected context', () => {
    const spread: TradeCardData = {
      ...mockTradeCard, spreadType: 'bear_put',
      legs: [
        { action: 'BUY', qty: 1, strike: 190, right: 'P', expiry: '2026-05-15', bid: 5, ask: 5.2 },
        { action: 'SELL', qty: 1, strike: 180, right: 'P', expiry: '2026-05-15', bid: 2.2, ask: 2.4 },
      ],
      netDebitCredit: 0, maxProfit: 725, maxLoss: 275, breakeven: 187.25,
      alternatives: [{
        symbol: 'AAPL', strike: 195, right: 'C', expiry: '2026-05-15', dte: 24,
        mid: 1.75, delta: 0.35, theta: -0.07, ivRank: 0, score: 65,
        contractConfidence: 'CAUTION', contractBreakdown: mockTradeCard.contractBreakdown,
        rrRatio: 2.1, rrModel: 'Heston repriced', reason: 'Lower premium with a smaller delta',
      }],
    };
    render(<TradeCard data={spread} />);
    const context = screen.getByRole('region', { name: 'Selected stock and contract' });
    expect(within(context).getByText(/Spread Legs/)).toHaveTextContent('Bear Put Spread');
    for (const value of ['$725.00', '$275.00', '$187.25', '+$0.00']) {
      expect(within(context).getByText(value)).toBeInTheDocument();
    }
    expect(within(context).getByText('BUY')).toBeInTheDocument();
    expect(within(context).getByText('SELL')).toBeInTheDocument();
    const alternatives = within(context).getByRole('button', { name: /ALTERNATIVES/ });
    expect(alternatives).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(alternatives);
    expect(within(context).getByText('Lower premium with a smaller delta')).toBeInTheDocument();
    expect(within(context).getByText('0')).toBeInTheDocument();
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

  it('places the folded score group directly between identity and Fundamental Health', () => {
    render(<TradeCard data={mockTradeCard} />);
    const toggle = screen.getByRole('button', { name: /Stock & contract scores/ });
    const group = toggle.closest('section')!;
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(group.previousElementSibling).toContainElement(screen.getByTestId('symbol-header'));
    expect(group.nextElementSibling).toHaveTextContent('Fundamental Health');
    expect(within(group).getAllByTestId('score-panel')).toHaveLength(2);
    expect(screen.getAllByTestId('score-panel')).toHaveLength(2);
    const panels = within(group).getAllByTestId('score-panel');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(panels[0]).not.toBeVisible();
    expect(panels[1]).not.toBeVisible();
    expect(localStorage.getItem('bamendjou:tradecard-scores-collapsed')).toBe('1');
    fireEvent.click(toggle);
    expect(within(group).getAllByTestId('score-panel')[0]).toBe(panels[0]);
  });

  it('keeps real stock and contract evidence independent and mounted across outer toggles', async () => {
    const panelMock = ScoreCardPanel as jest.Mock;
    const original = panelMock.getMockImplementation();
    panelMock.mockImplementation(jest.requireActual('@/components/molecules/ScoreCardPanel').ScoreCardPanel);
    const captured: TradeCardData = {
      ...mockTradeCard,
      stockExplanation: {
        version: 1, symbol: 'AAPL', direction: 'Bullish', horizon: 'Swing',
        scoring_mode: 'options', iv_basis: 'rank', evaluated_at: '2026-10-04T00:00:00Z',
        score: 82, status: 'PASS', raw_status: 'PASS', unrounded_score: 82,
        rounding: 'python_round_ties_to_even', pass_threshold: 70, caution_threshold: 50,
        weights: {}, caps: [], gate_config: {}, components: {},
      },
    };
    const before = JSON.stringify(captured);
    const estimateCalls = (api.getFirstPassageEstimate as jest.Mock).mock.calls.length;
    const planCalls = (api.getExitPlan as jest.Mock).mock.calls.length;
    const view = render(<TradeCard data={captured} />);
    try {
      await act(async () => { await Promise.resolve(); });
      const outer = screen.getByRole('button', { name: /Stock & contract scores/ });
      const group = outer.closest('section')!;
      expect(outer).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(outer);
      const stock = within(group).getByRole('button', { name: /Captured stock scoring evidence/ });
      const contract = within(group).getByRole('button', { name: /Captured contract scoring evidence/ });
      expect(outer).toHaveAttribute('aria-expanded', 'true');
      expect(stock).toHaveAttribute('aria-expanded', 'false');
      expect(contract).toHaveAttribute('aria-expanded', 'false');
      const evidence = within(group).getByText(/Captured AAPL evidence/);
      expect(evidence).not.toBeVisible();
      fireEvent.click(stock);
      expect(evidence).toBeVisible();
      expect(contract).toHaveAttribute('aria-expanded', 'false');
      const summary = within(group).getByText('Effective gate configuration and weights');
      fireEvent.click(summary);
      const details = summary.closest('details')!;
      expect(details.open).toBe(true);
      fireEvent.click(outer);
      expect(evidence).not.toBeVisible();
      fireEvent.click(outer);
      expect(within(group).getByText(/Captured AAPL evidence/)).toBe(evidence);
      expect(stock).toHaveAttribute('aria-expanded', 'true');
      expect(details.open).toBe(true);
      fireEvent.click(contract);
      fireEvent.click(stock);
      expect(contract).toHaveAttribute('aria-expanded', 'true');
      expect(stock).toHaveAttribute('aria-expanded', 'false');
      expect(localStorage.getItem('bamendjou:tradecard:stock:scoring-evidence:collapsed')).toBe('1');
      expect(localStorage.getItem('bamendjou:tradecard:contract:scoring-evidence:collapsed')).toBe('0');
      expect(within(group).getAllByRole('progressbar')).toHaveLength(10);
      expect(JSON.stringify(captured)).toBe(before);
      expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(estimateCalls);
      expect(api.getExitPlan).toHaveBeenCalledTimes(planCalls);
    } finally {
      view.unmount();
      panelMock.mockImplementation(original);
    }
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

  it('keeps handling controls before evidence and the latest result after method cards', () => {
    render(<TradeCard data={mockTradeCard} />);
    const order = screen.getByRole('region', { name: 'Order Entry' });
    const exit = screen.getByRole('region', { name: 'Exit Plan' });
    const latest = screen.getByText('Latest calculation');
    const arithmetic = screen.getByText('Arithmetic Profit Target');
    expect(order.compareDocumentPosition(exit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(exit.compareDocumentPosition(latest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(arithmetic.compareDocumentPosition(latest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const label of ['Edit Limit', 'Edit Contracts', 'Edit Invalidation', 'Edit Premium stop']) {
      expect(screen.getAllByLabelText(label)).toHaveLength(1);
    }
    expect(screen.getByText(/No method explicitly run/)).toBeVisible();
    expect(screen.getByText('Sell-to-Close Plan')).toBeVisible();
    expect(within(exit).getByText('Time exit')).toBeVisible();
  });

  it('renders the Order Entry strip (Feature 6 — Entry Plan card was folded into this strip)', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.getByText('Order type')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument();
    // Max fill is READ-ONLY (round 7 finding 3): nothing outside its own input
    // ever consumed it, and rendering it with the same click-to-edit affordance
    // as the three fields that DO reach the broker made the two
    // indistinguishable. See the row's own comment in TradeCard.
    expect(screen.queryByLabelText('Edit Max fill')).not.toBeInTheDocument();
    expect(screen.getByText('Max fill')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
  });

  // ── Piece 4 — the premium stop the card SHOWS is the one it reports ──────
  //
  // The field's value and the value the parent posts are two different pieces
  // of state (the overlay here, `premiumStopByContract` there), and `patch()`
  // reports the WHOLE overlay on every call. Both bugs below came from those
  // two drifting apart with nothing pinning them together.

  it('restores an edited premium stop when the same contract comes back', () => {
    // The reset on a contract change deliberately does not call onEditsChange,
    // so the parent's cache keeps the edit. Without seeding the field from that
    // cache the card displayed its SEED while both send paths posted the cached
    // edit: Prev to another candidate and back, and $1.50 was on screen while
    // $0.90 went to the broker.
    const { rerender } = render(<TradeCard data={mockTradeCard} initialPremiumStop={0.9} />);
    expandLadder();
    // EditableKV renders a click-to-edit span until it is focused, so the
    // displayed dollar amount is its text, not an input value.
    const shown = () => screen.getByLabelText('Edit Premium stop').textContent;
    expect(shown()).toBe('$0.90');

    // Away to another candidate and back — the actual path.
    const other = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT|400|2026-05-16|C' };
    rerender(<TradeCard data={other} initialPremiumStop={null} />);
    expect(shown()).toBe(`$${mockTradeCard.exit.premiumStop.toFixed(2)}`);   // its own seed
    rerender(<TradeCard data={mockTradeCard} initialPremiumStop={0.9} />);
    expect(shown()).toBe('$0.90');
  });

  it('follows a seed that moves under an untouched field, and stops following once edited', () => {
    // A Step 6 contract override changes `contract` immediately but leaves
    // `exit` as the auto-pick's; `mergePlan` swaps `exit` in a round-trip later
    // WITHOUT touching `contract`, so nothing re-ran and the field kept the old
    // seed. One unrelated patch() then cached it under the new contract's key,
    // `premiumStopDollarToSend` saw it differ from the new seed and let it
    // through, and the router derived a premium stop nobody chose.
    const onEditsChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />,
    );
    expandLadder();
    const shown = () => screen.getByLabelText('Edit Premium stop').textContent;
    const typeInto = (label: string, v: string) => {
      fireEvent.click(screen.getByLabelText(`Edit ${label}`));
      const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
      fireEvent.change(input, { target: { value: v } });
      fireEvent.blur(input);
    };

    // mergePlan: same contract, recomputed exit.
    const merged = { ...mockTradeCard, exit: { ...mockTradeCard.exit, premiumStop: 0.8 } };
    rerender(<TradeCard data={merged} onEditsChange={onEditsChange} />);
    expect(shown()).toBe('$0.80');

    // An unrelated edit now reports the CURRENT seed, not the stale one.
    typeInto('Contracts', '3');
    expect(onEditsChange.mock.calls.at(-1)![0].premiumStop).toBe(0.8);

    // Once the user types in the field, the seed stops overriding them.
    typeInto('Premium stop', '0.5');
    const moved = { ...merged, exit: { ...merged.exit, premiumStop: 0.65 } };
    rerender(<TradeCard data={moved} onEditsChange={onEditsChange} />);
    expect(shown()).toBe('$0.50');
  });

  // ── The same two properties for the OTHER two threaded fields ────────────
  //
  // Round 7 finding 10: `initialEntryLimit` and `initialInvalidation` and their
  // two follow-the-seed effects shipped with zero unit coverage --
  // `grep -c "initialEntryLimit\|initialInvalidation"` over this file returned
  // 0 -- while the premium stop they were modelled on had both a restore test
  // and a seed-following one. The page-level integration test exercised the
  // restore direction only.

  it('restores an edited entry limit and invalidation when the same contract comes back', () => {
    const { rerender } = render(
      <TradeCard data={mockTradeCard} initialEntryLimit={2.71} initialInvalidation={175.5} />,
    );
    const limit = () => screen.getByLabelText('Edit Limit').textContent;
    const invalidation = () => screen.getByLabelText('Edit Invalidation').textContent;
    expandLadder();
    expect(limit()).toBe('$2.71');
    expect(invalidation()).toBe('$175.50');

    // Away to another candidate — it shows ITS OWN seeds, not the cached edits.
    const other = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT|400|2026-05-16|C' };
    rerender(<TradeCard data={other} initialEntryLimit={null} initialInvalidation={null} />);
    expect(limit()).toBe(`$${mockTradeCard.entry.limit.toFixed(2)}`);
    expandLadder();
    expect(invalidation()).toBe(`$${mockTradeCard.exit.invalidation!.toFixed(2)}`);

    // ...and back.
    rerender(<TradeCard data={mockTradeCard} initialEntryLimit={2.71} initialInvalidation={175.5} />);
    expect(limit()).toBe('$2.71');
    expandLadder();
    expect(invalidation()).toBe('$175.50');
  });

  it('restoring an edit also restores its TOUCHED flag, so the page keeps caching it', () => {
    // The half a display assertion cannot see. If the flag came back false, the
    // next patch() would report `touched: false` and the page would drop the
    // cached edit to null -- the card would show 2.71 and the order would post
    // the seed, which is the round-trip defect wearing a different hat.
    const onEditsChange = jest.fn();
    render(
      <TradeCard
        data={mockTradeCard}
        initialEntryLimit={2.71}
        initialInvalidation={175.5}
        onEditsChange={onEditsChange}
      />,
    );
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const input = screen.getByLabelText('Edit Contracts') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '3' } });
    fireEvent.blur(input);

    const last = onEditsChange.mock.calls.at(-1)!;
    expect(last[1]).toEqual({ touched: { entryLimit: true, invalidation: true, premiumStop: false } });
    expect(last[0].entryLimit).toBe(2.71);
    expect(last[0].invalidation).toBe(175.5);
  });

  it('an UNTOUCHED entry limit and invalidation follow a seed that mergePlan moves', () => {
    // The opposite direction, and the one the two effects added on 2026-09-05
    // exist for: an untouched field caches `null` at the page level, so the
    // send path already resolves to the card's CURRENT value. A stale seed left
    // on screen means the card DISPLAYS the old level while the order uses the
    // new one.
    const onEditsChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />,
    );
    const limit = () => screen.getByLabelText('Edit Limit').textContent;
    const invalidation = () => screen.getByLabelText('Edit Invalidation').textContent;

    // Same contract, recomputed entry/exit — mergePlan's exact shape.
    const merged = {
      ...mockTradeCard,
      entry: { ...mockTradeCard.entry, limit: 2.9 },
      exit: { ...mockTradeCard.exit, invalidation: 181.2 },
    };
    rerender(<TradeCard data={merged} onEditsChange={onEditsChange} />);
    expect(limit()).toBe('$2.90');
    expandLadder();
    expect(invalidation()).toBe('$181.20');

    // Once typed, the seed stops overriding the user.
    const typeInto = (label: string, v: string) => {
      fireEvent.click(screen.getByLabelText(`Edit ${label}`));
      const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
      fireEvent.change(input, { target: { value: v } });
      fireEvent.blur(input);
    };
    typeInto('Limit', '3.10');
    typeInto('Invalidation', '176.00');
    const movedAgain = {
      ...merged,
      entry: { ...merged.entry, limit: 3.4 },
      exit: { ...merged.exit, invalidation: 182.9 },
    };
    rerender(<TradeCard data={movedAgain} onEditsChange={onEditsChange} />);
    expect(limit()).toBe('$3.10');
    expect(invalidation()).toBe('$176.00');
  });

  it('a HALF-TYPED number is not a clear, and does not throw away the committed edit', () => {
    // ROUND 8, and a regression the clear-to-inherit gesture introduced.
    // `<input type="number">` sanitizes its value: `e.target.value` is "" for
    // "132." and ".5" as well as for an actually empty field. So a user with a
    // committed 2.71 who reopened the field to make it 2.75, typed "2.7" then
    // "2." on the way, and tabbed away, had the field jump back to the plan's
    // $2.50, the touched flag cleared, and the order posted 2.50. The two
    // cases are the same string, so no check on the draft can separate them --
    // the input is type="text" now, which is what this pins.
    //
    // ROUND 9 corrected the other half: surviving to `parseFloat` is not the
    // same as being a number. See the assertions at the bottom.
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
    const limit = () => screen.getByLabelText('Edit Limit').textContent;

    fireEvent.click(screen.getByLabelText('Edit Limit'));
    let input = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2.71' } });
    fireEvent.blur(input);
    expect(limit()).toBe('$2.71');

    // Reopen and leave a trailing decimal point in the field.
    fireEvent.click(screen.getByLabelText('Edit Limit'));
    input = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2.' } });
    fireEvent.blur(input);

    // ROUND 9 finding 4. It must not revert to the seed (round 8's point) AND
    // it must not commit the truncation either. `parseFloat('2.')` is 2, which
    // sits inside [0.63, 7.50], so the value went straight through as a
    // deliberate $2.00 -- shown on the card, marked touched, and posted as
    // `limit_price` on a live BUY/OPEN order. An interrupted literal is a
    // no-op: the previously committed edit stands.
    expect(limit()).toBe('$2.71');
    expect(limit()).not.toBe('$2.00');
    expect(limit()).not.toBe(`$${mockTradeCard.entry.limit.toFixed(2)}`);
    expect(onEditsChange.mock.calls.at(-1)![1].touched.entryLimit).toBe(true);
    expect(onEditsChange.mock.calls.at(-1)![0].entryLimit).toBe(2.71);
  });

  it('bounds the invalidation on the BEARISH side too', () => {
    // ROUND 8 finding 12: only the bullish branch had a test, and the bearish
    // branch inverts both bounds independently -- a swap there would clamp
    // every bearish stop to the wrong side of spot, which is the silent
    // never-fires failure the bounds exist to prevent.
    const bearish = {
      ...mockTradeCard,
      direction: 'Bearish' as const,
      // A bearish stop sits ABOVE spot; price 185.20 -> [187.05, 277.80].
      exit: { ...mockTradeCard.exit, invalidation: 190 },
    };
    render(<TradeCard data={bearish} />);
    expandLadder();
    const shown = () => screen.getByLabelText('Edit Invalidation').textContent;
    expect(shown()).toBe('$190.00');

    // BELOW spot — the wrong side, and the one that can never fire. Rejected.
    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    let input = screen.getByLabelText('Edit Invalidation') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '180' } });
    fireEvent.blur(input);
    expect(shown()).toBe('$190.00');

    // A real bearish stop inside the window still lands.
    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    input = screen.getByLabelText('Edit Invalidation') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '195' } });
    fireEvent.blur(input);
    expect(shown()).toBe('$195.00');
  });

  it('anchors the bounds on the LIVE price when the page supplies one', () => {
    // ROUND 8 finding 3: `data.price` comes off a scanResult that scanStore
    // persists to localStorage, so after a reload it can be days old. AAPL
    // scanned at $185.20 and now trading at $260 had a bound of [92.60,
    // 183.35] -- every sane stop below today's spot rejected, while the page
    // rendered "Live stock: $260.00" three rows away.
    render(<TradeCard data={mockTradeCard} liveStockPrice={260} />);
    expandLadder();
    const shown = () => screen.getByLabelText('Edit Invalidation').textContent;

    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    const input = screen.getByLabelText('Edit Invalidation') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '240' } });  // inside [130, 257.40], outside the stale one
    fireEvent.blur(input);
    expect(shown()).toBe('$240.00');
  });

  it('a resetKey bump resets a touched field, so the card cannot outlive the parent cache', () => {
    // ROUND 8 finding 6. The page clears its three edit caches on a new scan;
    // the card's own reset is gated on symbol/contract identity, which a new
    // scan of the SAME contract does not change. Without this the card kept
    // showing (and kept `touched`) the user's $2.71 while `entryLimitFor` fell
    // back to the new plan's value -- card, button and order disagreeing.
    const { rerender } = render(<TradeCard data={mockTradeCard} resetKey={0} />);
    const limit = () => screen.getByLabelText('Edit Limit').textContent;

    fireEvent.click(screen.getByLabelText('Edit Limit'));
    const input = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2.71' } });
    fireEvent.blur(input);
    expect(limit()).toBe('$2.71');

    // New scan: same symbol, same contract, new plan, caches cleared.
    const rescanned = { ...mockTradeCard, entry: { ...mockTradeCard.entry, limit: 6 } };
    rerender(<TradeCard data={rescanned} resetKey={1} initialEntryLimit={null} />);
    expect(limit()).toBe('$6.00');
  });

  it('CLEARING a threaded field puts it back to inheriting, flag included', () => {
    // Round 7 finding 6 -- `touchedRef` was a one-way latch, so a typed field
    // was pinned for the life of the page and mergePlan could no longer reach
    // it. Clearing the input is the way back (the same gesture the portfolio
    // EditDrawer already uses to mean "inherit the global").
    const onEditsChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />,
    );
    const limit = () => screen.getByLabelText('Edit Limit').textContent;

    fireEvent.click(screen.getByLabelText('Edit Limit'));
    let input = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '3.10' } });
    fireEvent.blur(input);
    expect(limit()).toBe('$3.10');
    expect(onEditsChange.mock.calls.at(-1)![1].touched.entryLimit).toBe(true);

    fireEvent.click(screen.getByLabelText('Edit Limit'));
    input = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);

    expect(limit()).toBe(`$${mockTradeCard.entry.limit.toFixed(2)}`);
    expect(onEditsChange.mock.calls.at(-1)![1].touched.entryLimit).toBe(false);

    // And it inherits again: a moved seed now reaches the field.
    const merged = { ...mockTradeCard, entry: { ...mockTradeCard.entry, limit: 2.95 } };
    rerender(<TradeCard data={merged} onEditsChange={onEditsChange} />);
    expect(limit()).toBe('$2.95');
  });

  it('a click into a Premium stop seeded OUTSIDE the field bounds is still NOT an edit', async () => {
    // ROUND 6. Round 5 bounded this field to 10-99% of the mid, and
    // EditableKV.save clamps BEFORE its no-op guard -- so when the seed itself
    // sits outside the bounds, the clamp alone made `next !== value` and a bare
    // focus-and-blur reported a deliberate edit. That is the stray-click defect
    // of the test below, re-entered through the bounds meant to contain it.
    //
    // Reachable at the top of the allowed range: the seed is
    // `round(mid x global, 2)` and Settings accepts a global of 1.0
    // (risk_settings.py `le=1.0`), so the seed IS the mid ($2.50 here) while
    // the max is 99% of it ($2.48). 1951 of 2000 mids from $0.01 to $20.00 seed
    // above the bound at that setting.
    const atGlobalOne = { ...mockTradeCard, exit: { ...mockTradeCard.exit, premiumStop: 2.5 } };
    const onEditsChange = jest.fn();
    render(<TradeCard data={atGlobalOne} onEditsChange={onEditsChange} />);
    expandLadder();

    const before = onEditsChange.mock.calls.length;
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    fireEvent.blur(screen.getByLabelText('Edit Premium stop') as HTMLInputElement);
    expect(onEditsChange.mock.calls.length).toBe(before);

    // ...and it does not ACCUSE the user either. Round 6 moved the write; the
    // rejection message stayed above the no-op guard, so the same stray click
    // printed "Must be between $0.25 and $2.47 — kept the previous value." for
    // a value nobody typed. Round 2 of the follow-up audit found that half
    // still live.
    expect(screen.queryByText(/kept the previous value/i)).not.toBeInTheDocument();

    // And the field is still reported as untouched, so nothing is posted.
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const contracts = screen.getByLabelText('Edit Contracts') as HTMLInputElement;
    fireEvent.change(contracts, { target: { value: '3' } });
    fireEvent.blur(contracts);
    expect(onEditsChange.mock.calls.at(-1)![1]).toEqual({ touched: { entryLimit: false, invalidation: false, premiumStop: false } });
  });

  it('a click into a Premium stop seeded BELOW the field minimum is not an edit either', () => {
    /* The other side of the same hazard, and this branch WIDENED it.
     * `premiumStopDollarBounds` has to round the minimum UP, or the card's own
     * boundary dollar falls below the 10% floor the Portfolio drawer enforces
     * -- but the seed is `round(mid x global, 2)` (trade_plan.py), rounded to
     * NEAREST. At a global of 0.10, the minimum Settings offers, those two
     * disagree by a cent on 2184 of 4999 cent-mids, against 3 before.
     *
     * $5.24 mid: seed round(0.524, 2) = $0.52, field minimum ceil(524 x 0.10)
     * = $0.53. Clicking the field to read it and clicking away used to print
     * "Must be between $0.53 and $5.18 — kept the previous value." */
    const belowMin = {
      ...mockTradeCard,
      contractDetails: { ...mockTradeCard.contractDetails!, mid: 5.24 },
      exit: { ...mockTradeCard.exit, premiumStop: 0.52 },
    };
    const onEditsChange = jest.fn();
    render(<TradeCard data={belowMin} onEditsChange={onEditsChange} />);
    expandLadder();

    const before = onEditsChange.mock.calls.length;
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    fireEvent.blur(screen.getByLabelText('Edit Premium stop') as HTMLInputElement);
    expect(onEditsChange.mock.calls.length).toBe(before);
    expect(screen.queryByText(/kept the previous value/i)).not.toBeInTheDocument();

    // A value the user DOES type outside the bound is still refused -- the
    // hoisted guard skips the check for a no-op, not for everyone.
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByLabelText('Edit Premium stop') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0.10' } });
    fireEvent.blur(input);
    expect(screen.getByText(/Must be between \$0\.53 and \$5\.18/)).toBeInTheDocument();
  });

  it('REJECTS a value typed past the bound instead of clamping it', () => {
    // ROUND 8 reversed this. It used to assert the clamp ("typing above the max
    // is a deliberate act and must land, clamped") -- but a clamp turns a
    // fat-finger into a plausible-looking WRONG number rather than refusing it,
    // and these three fields now drive an order and two alert thresholds. The
    // portfolio EditDrawer already took the opposite position on the same
    // question ("showing the previous value back is the honest answer"); the
    // card had the unsafe one.
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
    expandLadder();
    const before = onEditsChange.mock.calls.length;
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByLabelText('Edit Premium stop') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '99' } });   // mid 2.50 -> max 2.48
    fireEvent.blur(input);
    // Nothing reported, nothing touched, and the field shows its old value back.
    expect(onEditsChange.mock.calls.length).toBe(before);
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent(
      `$${mockTradeCard.exit.premiumStop.toFixed(2)}`,
    );
  });

  it('accepts a value inside the bound, so the rejection is not swallowing real edits', () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
    expandLadder();
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByLabelText('Edit Premium stop') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2.40' } });  // within [0.25, 2.48]
    fireEvent.blur(input);
    expect(onEditsChange.mock.calls.at(-1)![0].premiumStop).toBe(2.4);
    expect(onEditsChange.mock.calls.at(-1)![1]).toEqual({ touched: { entryLimit: false, invalidation: false, premiumStop: true } });
  });

  it('tracks touched-ness per FIELD, so one field\'s edit does not vouch for another', async () => {
    // The three flags are independent by construction. `patch` reports the
    // whole overlay on every call, so without per-field tracking a Contracts
    // bump would carry an untouched Invalidation and Entry limit down to the
    // page as though the user had chosen them -- the exact shape of the bug
    // that made the seeded premium stop a deliberate 78% stop.
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);

    fireEvent.click(screen.getByLabelText('Edit Limit'));
    const limit = screen.getByLabelText('Edit Limit') as HTMLInputElement;
    fireEvent.change(limit, { target: { value: '2.71' } });   // inside [0.63, 7.50]
    fireEvent.blur(limit);

    expect(onEditsChange.mock.calls.at(-1)![1]).toEqual({
      touched: { entryLimit: true, invalidation: false, premiumStop: false },
    });

    expandLadder();
    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    const inval = screen.getByLabelText('Edit Invalidation') as HTMLInputElement;
    fireEvent.change(inval, { target: { value: '123.45' } });
    fireEvent.blur(inval);

    const last = onEditsChange.mock.calls.at(-1)!;
    expect(last[1]).toEqual({
      touched: { entryLimit: true, invalidation: true, premiumStop: false },
    });
    expect(last[0].entryLimit).toBe(2.71);
    expect(last[0].invalidation).toBe(123.45);
  });

  it('a click into the Invalidation or Limit field and back out is NOT an edit', async () => {
    // Same no-op guard as the Premium stop below, now load-bearing for two
    // more fields: an untouched Invalidation must keep deferring to
    // `data.exit.invalidation`, which `mergePlan` is free to move.
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
    expandLadder();

    for (const label of ['Limit', 'Invalidation']) {
      fireEvent.click(screen.getByLabelText(`Edit ${label}`));
      fireEvent.blur(screen.getByLabelText(`Edit ${label}`) as HTMLInputElement);
    }

    // Nothing changed, so nothing is reported at all; and if a later unrelated
    // edit reports the overlay, neither field is marked touched.
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const contracts = screen.getByLabelText('Edit Contracts') as HTMLInputElement;
    fireEvent.change(contracts, { target: { value: '3' } });
    fireEvent.blur(contracts);

    expect(onEditsChange.mock.calls.at(-1)![1]).toEqual({
      touched: { entryLimit: false, invalidation: false, premiumStop: false },
    });
  });

  it('a click into the Premium stop field and back out is NOT an edit', async () => {
    // THE STRAY CLICK. EditableKV.save runs on every blur, so reading the field
    // emitted onChange(sameValue) -> patch({premiumStop: seed}). While
    // touched-ness was INFERRED by comparing against the seed that was
    // harmless (the reported value equalled the seed and was discarded); once
    // it was TRACKED, the same no-op write marked the field touched and the
    // page posted the seeded default -- $3.12 on a $5.20 mid, re-anchored by
    // the server to a $4.00 fill and stored as a 78% stop nobody chose, with
    // no way back to inheriting the global.
    const onEditsChange = jest.fn();
    render(<TradeCard data={mockTradeCard} onEditsChange={onEditsChange} />);
    expandLadder();

    const before = onEditsChange.mock.calls.length;
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    fireEvent.blur(screen.getByLabelText('Edit Premium stop') as HTMLInputElement);

    // Nothing changed, so nothing is reported at all...
    expect(onEditsChange.mock.calls.length).toBe(before);
    // ...and if a caller does report an unchanged value, it still is not touched.
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const contracts = screen.getByLabelText('Edit Contracts') as HTMLInputElement;
    fireEvent.change(contracts, { target: { value: '3' } });
    fireEvent.blur(contracts);
    const last = onEditsChange.mock.calls.at(-1)!;
    expect(last[1]).toEqual({ touched: { entryLimit: false, invalidation: false, premiumStop: false } });
    expect(premiumStopDollarToSend(last[1].touched.premiumStop ? last[0].premiumStop : null))
      .toBeNull();
  });

  it('reports the premium stop as UNTOUCHED when an unrelated edit precedes the merge', async () => {
    // THE ORDERING THE TEST ABOVE DOES NOT COVER, and the one that actually
    // shipped broken. Above, the merge lands first, so the later patch() reports
    // the current seed and the cache self-heals. Reverse the two and it does
    // not: the patch caches the OLD seed, the re-seed effect then moves the
    // field without telling the parent (deliberately — see its comment), and
    // the page was left holding a stale dollar it had no way to recognise as a
    // default. `premiumStopDollarToSend` compared it against the NEW seed,
    // 1.5 !== 0.8, and posted 1.5 — the card displaying $0.80 while $1.50 went
    // to the server and armed the position at 1.5/entry.
    //
    // What makes it safe is not the value but the flag: an untouched field
    // reports `touched.premiumStop: false` no matter which seed it happens to
    // hold, and the page caches null for it.
    const onEditsChange = jest.fn();
    const seeded = { ...mockTradeCard, exit: { ...mockTradeCard.exit, premiumStop: 1.5 } };
    const { rerender } = render(
      <TradeCard data={seeded} onEditsChange={onEditsChange} />,
    );
    expandLadder();

    // 1. An unrelated edit, BEFORE any merge. The overlay still holds the 1.5
    //    seed and rides along — but it is flagged untouched.
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const contracts = screen.getByLabelText('Edit Contracts') as HTMLInputElement;
    fireEvent.change(contracts, { target: { value: '3' } });
    fireEvent.blur(contracts);
    const afterEdit = onEditsChange.mock.calls.at(-1)!;
    expect(afterEdit[0].premiumStop).toBe(1.5);
    expect(afterEdit[1]).toEqual({ touched: { entryLimit: false, invalidation: false, premiumStop: false } });
    // The page caches null for an untouched field, so nothing is posted.
    expect(premiumStopDollarToSend(afterEdit[1].touched.premiumStop ? afterEdit[0].premiumStop : null))
      .toBeNull();

    // 2. mergePlan now moves the seed under the untouched field.
    const merged = { ...seeded, exit: { ...seeded.exit, premiumStop: 0.8 } };
    rerender(<TradeCard data={merged} onEditsChange={onEditsChange} />);
    expect(screen.getByLabelText('Edit Premium stop').textContent).toBe('$0.80');

    // 3. Still untouched, so still nothing posted — displayed and posted agree.
    //    Under the old value-comparison this posted 1.50 against a $0.80 card.
    const last = onEditsChange.mock.calls.at(-1)!;
    expect(last[1].touched.premiumStop).toBe(false);

    // 4. Only a real edit arms it, and then the typed value is what is posted.
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const stop = screen.getByLabelText('Edit Premium stop') as HTMLInputElement;
    fireEvent.change(stop, { target: { value: '0.5' } });
    fireEvent.blur(stop);
    const armed = onEditsChange.mock.calls.at(-1)!;
    expect(armed[1]).toEqual({ touched: { entryLimit: false, invalidation: false, premiumStop: true } });
    expect(premiumStopDollarToSend(armed[1].touched.premiumStop ? armed[0].premiumStop : null))
      .toBe(0.5);
  });

  it('keeps the exit plan ALWAYS VISIBLE beside the expanded initial ladder', () => {
    render(<TradeCard data={mockTradeCard} />);
    // Both initial ladder and execution exit controls are visible without expanding.
    expect(screen.getByText('Sell-to-Close Plan')).toBeVisible();
    expect(screen.getByText('Exit Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
    // P2-03 (decision Q8): the exit the alert actually makes, read-only.
    expect(screen.queryByLabelText('Edit Time exit')).not.toBeInTheDocument();
    expect(screen.getByText('Time exit')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Exit Plan' })).getByText('3 DTE')).toBeInTheDocument();
    expect(screen.queryByText('Time stop')).not.toBeInTheDocument();
    expect(screen.queryByText(`${mockTradeCard.exit.timeStopDays}d`)).not.toBeInTheDocument();
  });

  beforeEach(() => {
    // Feature 1 wraps Exit Plan / Sell-to-Close Plan / Risk-Reward in a
    // CollapsibleSection whose collapsed state persists to localStorage —
    // clear it so every test starts from the deterministic default-collapsed
    // state (jsdom's window/localStorage persists across tests within one
    // file, unlike a real browser tab per test).
    window.localStorage.clear();
    // The scan context is a module-level zustand store, so a context set by one
    // test survives into the next one in this file (localStorage.clear() above
    // does not touch the in-memory state). It decides the gate's horizon, so
    // leaving it set would make a later test's `horizon_preset` depend on which
    // tests ran before it.
    useScanStore.getState().setContext(null);
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
    // A premium that deliberately differs from contractDetails.mid (2.5), for
    // the same reason as the stock price above: the assertion below has to be
    // able to tell the live quote from the scan-time snapshot. The default mock
    // in beforeEach returns 2.5, which is the same number as the mid — so it
    // could not discriminate, and this test passed all the way through the
    // window in which this call site sent the stale one.
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 3.4, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    expect(api.getStockQuote).toHaveBeenCalledWith('AAPL', expect.any(AbortSignal));
    await waitFor(() => {
      expect(api.getStructuralStop).toHaveBeenCalledWith(
        {
          symbol: 'AAPL', direction: 'Bullish', stock_price: 186.1,
          // The contract travels with the request so the response can carry the
          // stop-vs-premium gate priced at THIS level (B2). All three or none —
          // the endpoint 422s a partial set. The premium is the LIVE mid, in
          // step with the live stock price beside it: this request prices the
          // gate, so a stale premium here is the number the badge prints and
          // the value the server inverts the IV out of.
          strike: 190, dte: 24, premium: 3.4,
          horizon_preset: undefined,
        },
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

  it('falls back to data.price and contractDetails.mid when the live quotes fail', async () => {
    (api.getStockQuote as jest.Mock).mockRejectedValueOnce(new Error('quote unavailable'));
    (api.getContractQuote as jest.Mock).mockRejectedValueOnce(new Error('quote unavailable'));
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(api.getStructuralStop).toHaveBeenCalledWith(
        {
          symbol: 'AAPL', direction: 'Bullish', stock_price: 185.2,
          strike: 190, dte: 24, premium: 2.5, horizon_preset: undefined,
        },
        expect.any(AbortSignal),
      );
    });
  });

  // ---- The gate's two inputs that B2 got wrong, pinned. -------------------
  //
  // Both are "the badge prints a number that is not the one it claims", which
  // is the only class of defect this project's audit gate treats as blocking,
  // and neither had a test that could fail: the premium assertion could not
  // discriminate (the default contract-quote mock returns the same 2.5 as the
  // scan-time mid), and no test set a scan context at all.

  it('sends the SAME premium to the gate from Check structure and Compute Arithmetic Plan', async () => {
    // The defect: computeExitPlan had always sent the live mid, while both
    // structural call sites sent the scan-time `cd.mid`. Same contract, same
    // stop, same card — the badge read one premium, one loss and one verdict
    // after "Check structure" and a different set after "Compute Arithmetic
    // Plan", decided only by which button was pressed last. On a contract whose
    // mid had moved 8.10 -> 12.96 that is CAUTION/"total loss" against PASS/64%.
    const liveQuote = { price: 3.4, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100 };
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce(liveQuote).mockResolvedValueOnce(liveQuote);
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 177.0, source: 'atr_floor' as const, contractPrice: 1.2,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 178.5, atrFloorPrice: 177.0, distanceDollar: 1.5,
      },
      targets: [],
      atr: 3.5,
    });
    render(<TradeCard data={mockTradeCard} />);

    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => expect(api.getStructuralStop).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => expect(api.getExitPlan).toHaveBeenCalled());

    const structuralPremium = (api.getStructuralStop as jest.Mock).mock.calls.at(-1)![0].premium;
    const exitPlanPremium   = (api.getExitPlan as jest.Mock).mock.calls.at(-1)![0].premium;
    expect(structuralPremium).toBe(3.4);
    expect(exitPlanPremium).toBe(3.4);
    expect(structuralPremium).toBe(exitPlanPremium);
  });

  it('sends the live premium from the Estimate click\'s structural sub-fetch too', async () => {
    // The third call site, and the one where the defect was most visible in the
    // source: `estimateFirstPassage` resolved the live premium into a local and
    // then sent `cd.mid` fifty lines later, so the gate disagreed with the
    // Barrier Race card rendered directly beneath it off the same click.
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 3.4, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [], stopHitPct: null, medianDaysToStop: null, sampleSize: 0,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /estimate/i }));
    await waitFor(() => expect(api.getStructuralStop).toHaveBeenCalled());
    expect((api.getStructuralStop as jest.Mock).mock.calls.at(-1)![0].premium).toBe(3.4);
    // The click's own Monte Carlo dispatch is awaited and then cleared: this
    // file's mocks are never reset between tests (no clearMocks in
    // jest.config.ts), so an in-flight estimate would otherwise land during a
    // LATER test and break its `not.toHaveBeenCalled()` precondition.
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalled());
    (api.getFirstPassageEstimate as jest.Mock).mockClear();
  });

  it('grades a Custom hold range at the horizon the rest of the card shows, not at Swing', async () => {
    // The defect: B2 sent `context.horizonPreset` raw, and the backend's
    // _PRESET_TO_HORIZON maps a bare `custom` to `swing` because the request
    // carries no hold range to resolve with. A Custom 60-185d scan is labelled
    // "Position (60-185d)" on this very card and uses Position's parameter row
    // in Step 3, but its stop cost was graded against Swing's 0.70 instead of
    // Position's 0.60 — and the badge echoed passMaxFraction 0.70 beside it.
    // Pre-B2 the card resolved this itself and got it right.
    useScanStore.getState().setContext({
      universe: 'SP500', direction: 'Bullish',
      horizon: 'Position (60–185d)', horizonPreset: 'Custom',
      holdMin: 60, holdMax: 185,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => expect(api.getStructuralStop).toHaveBeenCalled());
    expect((api.getStructuralStop as jest.Mock).mock.calls.at(-1)![0].horizon_preset).toBe('Position');
  });

  it('leaves every non-Custom preset key untouched, so Quarterly stays Quarterly', async () => {
    // The guard on the fix. Quarterly/SemiAnnual/Annual all collapse to
    // `position` server-side already, and the barrier race keys its repricing
    // table on the SEVEN-key preset — repricing a 200-day hold like a 20-day
    // one is the error that table exists to avoid. `resolveParamsHorizon`
    // touches Custom and nothing else; if it ever starts collapsing the rest,
    // this fails.
    useScanStore.getState().setContext({
      universe: 'SP500', direction: 'Bullish',
      horizon: 'Position (45–60d)', horizonPreset: 'Quarterly',
      holdMin: 45, holdMax: 60,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => expect(api.getStructuralStop).toHaveBeenCalled());
    expect((api.getStructuralStop as jest.Mock).mock.calls.at(-1)![0].horizon_preset).toBe('Quarterly');
  });

  // A8, open_questions[52]. The two other call sites of the same horizon fix:
  // only Check structure was pinned, so reverting either of these to the raw
  // preset regressed silently -- a Custom 60-185d plan or estimate graded at
  // Swing's threshold while the card beside it said Position.
  const CUSTOM_POSITION = {
    universe: 'SP500', direction: 'Bullish' as const,
    horizon: 'Position (60–185d)', horizonPreset: 'Custom' as const,
    holdMin: 60, holdMax: 185,
  };

  it('sends the resolved horizon from Compute Arithmetic Plan, not the raw Custom preset', async () => {
    useScanStore.getState().setContext(CUSTOM_POSITION as any);
    (api.getExitPlan as jest.Mock).mockResolvedValueOnce({
      stop: {
        price: 177.0, source: 'atr_floor' as const, contractPrice: 1.2,
        rrModel: 'Heston repriced' as const, structuralSource: 'order_block' as const, structuralConfidence: 80,
        structuralPrice: 178.5, atrFloorPrice: 177.0, distanceDollar: 1.5,
      },
      targets: [],
      atr: 3.5,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => expect(api.getExitPlan).toHaveBeenCalled());
    expect((api.getExitPlan as jest.Mock).mock.calls.at(-1)![0].horizon_preset).toBe('Position');
  });

  it('sends the resolved horizon from the Estimate click\'s structural sub-fetch', async () => {
    useScanStore.getState().setContext(CUSTOM_POSITION as any);
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [], stopHitPct: null, medianDaysToStop: null, sampleSize: 0,
    });
    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /estimate/i }));
    await waitFor(() => expect(api.getStructuralStop).toHaveBeenCalled());
    expect((api.getStructuralStop as jest.Mock).mock.calls.at(-1)![0].horizon_preset).toBe('Position');
    // Same cleanup as the live-premium estimate test above.
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalled());
    (api.getFirstPassageEstimate as jest.Mock).mockClear();
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

  it('sends the premium-stop barrier ONLY once the field has been edited', async () => {
    // ROUND 9 finding 13, the other direction. A TOUCHED field is a real
    // choice and must reach the race -- converted against the fresh premium,
    // which is the point of computing it at send time. $0.90 typed on a card
    // whose live premium is $2.75 is a 32.7% barrier.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [], invalidation: { probability: 0.30, expectedDays: 4 },
    });
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();

    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByLabelText('Edit Premium stop') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0.90' } });
    fireEvent.blur(input);

    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));

    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalled());
    const sent = (api.getFirstPassageEstimate as jest.Mock).mock.calls.at(-1)![0];
    expect(sent.premium_stop_pct).toBeCloseTo(0.9 / 2.75, 10);
    // And specifically NOT the seed-over-fresh-premium conflation.
    expect(sent.premium_stop_pct).not.toBeCloseTo(1.5 / 2.75, 10);
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
          // ROUND 9 finding 13. The barrier race's third barrier is sent ONLY
          // when the user has edited the Premium stop field. Untouched, as
          // here, `overlay.premiumStop` is just the seed
          // `round(scan_mid x global, 2)` -- the global wearing a dollar sign
          // -- and dividing that scan-time dollar by the FRESHLY FETCHED
          // premium ($2.75 here, against a $2.50 scan mid) produced a third
          // number that is neither: the race simulated 1.50/2.75 = 54.5% and
          // the row read "from the editable field above" for a field nobody
          // touched. `undefined` is what makes the documented fallback to
          // risk_rules.yaml's premium_stop_pct reachable; before this it was
          // dead except on a degenerate seed.
          premium_stop_pct: undefined,
          // No scan context in this test, so the backend's own Swing default
          // applies rather than a guessed preset.
          horizon_preset: undefined,
          hold_min: undefined,
          hold_max: undefined,
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
    expect(screen.getByText('~5 calendar days')).toBeInTheDocument();       // T20% Expected time
    expect(screen.getByText('$193.20')).toBeInTheDocument();   // T35% Stock price
    expect(screen.getByText('not reachable')).toBeInTheDocument(); // T50% Stock price (null)
    // The invalidation row moved off this card to the Barrier Race card
    // (barrier-race spec section 3.4). This mock returns no `race`, so the race card
    // renders nothing and the standalone invalidation numbers are not on
    // screen at all — deliberately, rather than being shown twice in two
    // places that count paths differently.
    expect(screen.queryByText('~4d')).not.toBeInTheDocument();
    // ...and Feature 8's Final Recommendation does not reinstate it. That card
    // carried the standalone probability as its no-race fallback until the
    // readout was removed outright, so 30% is now on screen nowhere — while
    // firstPassage.invalidation still holds it, still feeds BarrierRaceCard,
    // and data.exit.invalidation still hard-blocks the send.
    expect(screen.queryByText('30%')).not.toBeInTheDocument();
    // The round-7 caution note must NOT be here. It said the Fixed % Ladder
    // still back-solved at half the contract's life while "Stock price" above
    // used the resolved holding horizon. Both now call the same resolver
    // (reprice_horizon.display_reprice_years), so that disagreement no longer
    // exists and re-showing the note would tell a trader to discount two
    // numbers that agree. This assertion is deliberately on the WORDING rather
    // than a test id: the note had none, and the failure mode being guarded is
    // someone reinstating the prose, not a component reappearing.
    expect(screen.queryByText(/still back-solves/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/half the contract/i)).not.toBeInTheDocument();
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

    fireEvent.click(screen.getByRole('button', { name: /set trade loss budget/i }));
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

    fireEvent.click(screen.getByRole('button', { name: /set trade loss budget/i }));
    fireEvent.click(screen.getByRole('button', { name: '$' }));
    fireEvent.change(screen.getByLabelText('Max loss override value'), { target: { value: '9999' } });
    // Deliberately do NOT click Apply — switch candidates mid-edit instead.

    const nextCard: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' };
    rerender(<TradeCard data={nextCard} onMaxLossOverrideChange={onMaxLossOverrideChange} />);

    // The editor remounted for the new candidate — back to the closed
    // "Set trade loss budget" state, not still showing the $9999 draft mid-edit.
    expect(screen.getByRole('button', { name: /set trade loss budget/i })).toBeInTheDocument();
    expect(screen.queryByLabelText('Max loss override value')).not.toBeInTheDocument();

    // Opening and applying fresh on the new candidate must not reuse 9999 —
    // a fresh editor's default draft (0, percent mode) applies instead.
    fireEvent.click(screen.getByRole('button', { name: /set trade loss budget/i }));
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
    // The "R:R vs. structural stop" cell this test used to read is gone
    // (barrier-race spec section 3.4). What it was gating on is not: the
    // "Structural level found" cell appears on all three rows only once BOTH
    // the stop and the estimate have been confirmed fresh THIS mount, and it
    // shows the FRESH stop, not the scan-time one.
    await waitFor(() => {
      expect(screen.getAllByText('Structural level found').length).toBe(3);
    });
    expect(screen.getAllByText('$190.00').length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText('R:R vs. structural stop')).not.toBeInTheDocument();
  });

  // REMOVED with the "R:R vs. structural stop" cell (barrier-race spec section 3.4):
  //   - 'shows a negative structural-stop R:R instead of "—" (M2 parity)'
  //   - 'clamps structural-stop risk to the option premium ...'
  // Both asserted on the ratio the cell displayed. The ratio's risk leg was a
  // delta approximation of the stop distance clamped to premium; once the clamp
  // bound — routinely, for a distant stop or a low-delta contract — the ratio
  // reduced to exactly the typed target percentage, the same number on every
  // contract. The arithmetic is deleted, not hidden, so there is nothing left
  // for these to pin. Sign preservation (the M2 half) is covered on the
  // replacement in lib/barrierRace.test.ts.

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
    // "N/A (stop = price)" placeholder rather than a level.
    // Three targets × one line each ("Structural level found", Feature 2) plus
    // the one standalone Check Structure block above (Feature 3) = 4. It was 7
    // until the "R:R vs. structural stop" line was removed alongside it
    // (barrier-race spec section 3.4) — the state itself is unchanged, there is
    // simply one cell per row carrying it now instead of two.
    expect(screen.getAllByText('N/A (stop = price)').length).toBe(4);
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
    await waitFor(() => screen.getAllByText('Structural level found'));

    // The ladder's standalone "Risk / Reward" readout is gone (barrier-race
    // spec section 3.4): its risk leg was premium x a fixed percentage, so premium
    // cancelled and it printed the same ratio on every contract.
    expect(screen.queryByText('Risk / Reward')).not.toBeInTheDocument();
    expect(screen.queryByText('2.5×')).not.toBeInTheDocument();
    // The FIELD it divided by is untouched — it is the premium-stop alert
    // level, not a display. The Sell-to-Close-Plan's own per-target R:R now
    // risks the full premium (2.5): reward=5.0-2.5=2.5, rr=2.5/2.5=1.0.
    // Re-pinned by TRADING-REVIEW-PHASE-C-RR: was 2.5/premiumStop(1.5) = 1.7x.
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
    expect(screen.getByText('1.0x')).toBeInTheDocument();
    expect(screen.queryByText('1.7x')).not.toBeInTheDocument();
  });

  it('renders sell-to-close plan with editable target', () => {
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    expect(screen.getByText('Sell-to-Close Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit target stock price for TP1')).toBeInTheDocument();
  });

  it('no longer renders the ladder R:R readout, but keeps the field it divided by', () => {
    // Removed by the barrier-race spec (section 3.4). It degenerated to the typed
    // target % over the typed stop % — the same number on every contract you
    // could pick — and is replaced by the Barrier Race's stock-stop R:R, whose
    // risk leg is not proportional to premium.
    //
    // overlay.premiumStop is NOT display-only, so removing the readout must
    // not touch the field: rrContribution still reads it, and it is now the
    // barrier race's third barrier too. (computeEditedRR and isDirty were named
    // here as well until the Ladder-DEFAULT copy of the Projected R/R readout
    // went too — that copy was their only caller.)
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    expect(screen.queryByText('Risk / Reward')).not.toBeInTheDocument();
    expect(screen.queryByText('2.5×')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
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

  it('no longer shows the projected R/R readout anywhere on the card', () => {
    // Removed per the schematic: third R:R on one page, reward from a
    // hardcoded +8% stock move nobody chose, risk from a flat percentage of
    // premium. The Ladder's own copy went earlier; this pins the last one,
    // which lived in the Final Recommendation's Ladder-default branch — the
    // state this render is in, before any method has been run.
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.queryByText('Projected R/R (+8% stock move)')).not.toBeInTheDocument();
    expect(screen.queryByText('R:R ratio')).not.toBeInTheDocument();
    // The field the readout divided by is untouched — it is a live risk
    // denominator and the barrier race's third barrier, not a display.
    expandLadder();
    expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
  });

  describe('Arithmetic Profit Target (Feature 3) — additional coverage', () => {
    it('reports uncomputed targets without assuming the configured ratio sequence', () => {
      // The TARGETS still need a plan -- they are arithmetic multiples of the
      // stop distance repriced against a contract. The stop row no longer
      // does; see the piece 3 block below.
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByText('Target estimates — not yet computed —')).toBeInTheDocument();
    });

    describe('the scan\'s own final stop (piece 3)', () => {
      // The stop is resolved AT SCAN TIME now, so this row has something true
      // to say before any button is pressed -- which is the point of piece 3:
      // on a card where Compute Arithmetic Plan is never pressed (the default,
      // since it is user-triggered), the stop used to be a flat percentage and
      // this row read "not yet computed".
      const FINAL_STOP = {
        price: 169.0,
        source: 'final_stop' as const,
        stopSource: 'atr_widened' as const,
        structuralSource: 'swing_low' as const,
        structuralPrice: 182.0,
        atrFloorPrice: 169.0,
        distanceDollar: 13.0,
        atr: 8.0,
        computedAt: '2026-09-09T12:00:00+00:00',
      };
      const withStop = {
        ...mockTradeCard,
        exit: { ...mockTradeCard.exit, invalidation: 169.0, finalStop: FINAL_STOP },
      };

      it('renders the scan-resolved stop, both candidates and the gap, with no plan computed', () => {
        render(<TradeCard data={withStop} />);
        expect(screen.queryByText(/Bottom \(final stop\) — not/)).not.toBeInTheDocument();
        expect(screen.getByText('Bottom (final stop)')).toBeInTheDocument();
        // THREE TIMES: "Price" and "ATR-floor price" in this row -- the same
        // number here precisely because the floor is what decided the stop,
        // which is the case this fixture exists to render -- plus the Exit
        // Plan's Invalidation (169.00 in this fixture), which is always
        // visible since P2-21 moved it out of the collapsed ladder group.
        expect(within(screen.getByRole('region', { name: 'Structure & Stops' })).getAllByText('$169.00')).toHaveLength(3);
        expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('$169.00');
        // The LOSING candidate rides along: the row prints both levels and the
        // gap, so a reader can see the floor was what widened the stop.
        expect(screen.getByText('Structural stop — Swing Low')).toBeInTheDocument();
        expect(screen.getByText('$182.00')).toBeInTheDocument();
        expect(screen.getByText('$13.00')).toBeInTheDocument();
        expect(screen.getByText('$8.00')).toBeInTheDocument();
        expect(screen.getByText(/widened to \$169\.00/)).toBeInTheDocument();
      });

      it('says "—" for the two figures the scan cannot answer, rather than omitting them', () => {
        // Part 2 of the plan. What the stop COSTS needs a contract repriced at
        // it, and the auto-pick does not settle that -- a Step 6 override
        // replaces the contract without moving the stop. An absent row reads
        // as "there is no such thing"; a dash reads as "not computed yet".
        render(<TradeCard data={withStop} />);
        expect(screen.getByText('Contract value at stop')).toBeInTheDocument();
        expect(screen.getByText('Max loss if stopped')).toBeInTheDocument();
        expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
        // And the risk-derived size, which sizes off that contract price, is
        // not offered either.
        expect(screen.queryByText(/Risk-derived size/)).not.toBeInTheDocument();
      });

      it('falls back to "re-run the scan" for a card with no resolved stop', () => {
        // A candidate restored from a scan session persisted before piece 3:
        // the scanStore v15 migration stripped its flat percentage and it
        // carries no provenance block. Never a blank, and never a number.
        render(<TradeCard data={mockTradeCard} />);
        expect(
          screen.getByText('Bottom (final stop) — not computed — re-run the scan'),
        ).toBeInTheDocument();
      });

      it('shows the stripped Invalidation field as not computed, not as zero', () => {
        const stripped = {
          ...mockTradeCard,
          exit: { ...mockTradeCard.exit, invalidation: null },
        };
        render(<TradeCard data={stripped} />);
        expandLadder();
        expect(screen.getByText('not computed — re-run the scan')).toBeInTheDocument();
        // Still editable: typing a stop is the one gesture that makes a
        // restored card orderable without a re-scan.
        expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
      });
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

  it('a Contracts edit still reaches the page-level handler after the shared per-symbol map round-trips the value back down', async () => {
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
    expect(onEditsChange).toHaveBeenCalledWith(
      expect.objectContaining({ contracts: 5 }),
      expect.objectContaining({ touched: expect.objectContaining({ premiumStop: expect.any(Boolean) }) }),
    );

    // Simulate that page-level round-trip: the shared map updates, and the
    // new value flows back down as the `contracts` prop on the next render —
    // exactly what orderContractsBySymbol[symbol] does in production.
    await act(async () => {
      rerender(<TradeCard data={mockTradeCard} contracts={5} onEditsChange={onEditsChange} />);
    });

    // What this test was originally about — isDirty comparing 5 against 5 after
    // the round-trip, so the "edited" flag self-cancelled for a Contracts-only
    // edit — is moot: isDirty and the flag are gone with the Projected R/R
    // readout that was their only consumer. The round-trip itself is real
    // behaviour and is what the assertions above now pin. The line below stays
    // as the removal guard: nothing on this card raises a card-level "edited"
    // flag any more, in this sequence or any other.
    expect(screen.queryAllByText(/edited/).length).toBe(0);
  });

  describe('Final Recommendation (Feature 8)', () => {
    it('empty state — before any method is run, falls back to the Fixed % Ladder Plan\'s live T1/T2/T3 targets, explicitly labeled as a default', () => {
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.getByText('No method explicitly run — showing Fixed % Ladder Plan (default)')).toBeInTheDocument();
      // mockTradeCard's single target: stockPrice/targetPrice 200.02.
      expect(within(screen.getByRole('region', { name: 'Final Recommendation' })).getByText('$200.02')).toBeInTheDocument();
      // The targets, and ONLY the targets. This branch used to carry the
      // Ladder's "Projected R/R (+8% stock move)" as well — the copy that
      // survived the readout's removal from the Ladder section itself, and the
      // one a trader met first, since this is the state the card opens in.
      expect(screen.queryByText('Projected R/R (+8% stock move)')).not.toBeInTheDocument();
      expect(screen.queryByText('2.50x')).not.toBeInTheDocument();
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
      // Max fill is READ-ONLY (round 7 finding 3): nothing outside its own input
    // ever consumed it, and rendering it with the same click-to-edit affordance
    // as the three fields that DO reach the broker made the two
    // indistinguishable. See the row's own comment in TradeCard.
    expect(screen.queryByLabelText('Edit Max fill')).not.toBeInTheDocument();
    expect(screen.getByText('Max fill')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Contracts')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Invalidation')).toBeInTheDocument();
      expect(screen.getByLabelText('Edit Premium stop')).toBeInTheDocument();
      expect(screen.queryByLabelText('Edit Time stop')).not.toBeInTheDocument();
    });

    it('opens inline input when clicking editable limit field', async () => {
      render(<TradeCard data={mockTradeCard} />);
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      expect(screen.getByDisplayValue('2.5')).toBeInTheDocument();
      // TEXT with inputMode="decimal", not type="number" -- ROUND 8. A number
      // input sanitizes its value to "" for any half-typed literal ("2.7",
      // ".5"), and an empty draft is now the gesture that reverts a field to
      // inheriting, so a user mid-keystroke had their committed edit thrown
      // away. The mobile keypad still comes up via inputMode.
      expect(screen.getByDisplayValue('2.5')).toHaveAttribute('type', 'text');
      expect(screen.getByDisplayValue('2.5')).toHaveAttribute('inputmode', 'decimal');
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

    it('prints no R:R model or "edited" caption when the entry limit changes — both went with the readout they captioned', async () => {
      // This test used to assert the opposite: "Heston repriced" before the
      // edit, "Edit (delta approx)" after. Both strings came from
      // computeEditedRR, whose only consumer was the Projected R/R readout, so
      // removing that readout removed the caption and the function behind it.
      // Kept as a removal guard rather than deleted: reinstating either string
      // means the readout came back with it.
      render(<TradeCard data={mockTradeCard} />);
      expect(screen.queryByText('Heston repriced')).not.toBeInTheDocument();
      const limitTrigger = screen.getByLabelText('Edit Limit');
      await act(async () => {
        fireEvent.click(limitTrigger);
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '5.0' } });
        fireEvent.keyDown(input, { key: 'Enter' });
      });
      expect(screen.queryByText(/Edit \(delta approx\)/)).not.toBeInTheDocument();
      // The edit itself still lands — only its caption is gone.
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$5.00');
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

    it('rejects an entry limit below its bound, leaving the old value on screen', async () => {
      // ROUND 8. This used to assert a clamp to $0.01 -- and $0.01 is not a
      // bound on a $2.50 contract, it is a different order. The field is now
      // bounded to [0.25x, 3x] of the mid and refuses anything outside it,
      // because this value becomes the order's `limit_price`.
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
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$2.50');
    });

    it('rejects an entry limit an order of magnitude above the mid', async () => {
      // The CRITICAL of round 8: "25.0" typed for "2.50" posted
      // `limit_price: 25.0` on a BUY/OPEN order, with no bound in the field, no
      // bound in the backend schema, and both risk checks sizing off the mid
      // rather than the limit.
      render(<TradeCard data={mockTradeCard} />);
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Edit Limit'));
      });
      const input = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(input, { target: { value: '25.0' } });   // max is 7.50
        fireEvent.blur(input);
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$2.50');
    });

    it('refuses a contracts value below its minimum, leaving the previous count', async () => {
      // Renamed in ROUND 8 with the clamp->reject change. The assertion is
      // unchanged and passes either way here (the previous value IS 1), but
      // the old name described a mechanism the field no longer uses, and a
      // test name that lies about the rule is how the next reader learns the
      // wrong one.
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
        expect.objectContaining({ touched: expect.objectContaining({ premiumStop: expect.any(Boolean) }) }),
      );
    });

    // WHAT WENT, AND WHAT DID NOT. Three tests stood here covering the
    // card-level "edited" flag: it appeared for any overlay field, it did NOT
    // appear when the `contracts` prop merely seeded a non-default value
    // (Feature 7's isDirty fix), and it DID appear once contracts was
    // hand-edited away from that seed. All three asserted the same string, and
    // that string was rendered in exactly one place — appended to the R:R model
    // caption inside the Projected R/R readout. isDirty existed only to decide
    // whether to append it. Removing the readout removed the flag, the memo and
    // the function together; there is no card-level edited indicator left to
    // test, so the three are replaced by the two guards below.
    //
    // NOT a blanket loss of edit feedback: the Sell-to-Close ladder rows keep
    // their OWN per-row "edited" badge, which never went through isDirty
    // ('shows edited badge in target row when stock price is changed' above
    // still passes). What no longer surfaces anywhere is an edit to Entry
    // limit, Max fill, Contracts, Premium stop, Time stop or Invalidation.
    // That is a consequence of the approved removal, not a separate decision,
    // and it is recorded in PROJECT_STATE.json as a question for Kenneth.
    it('shows no card-level "edited" flag for a non-target field, in either isDirty case', async () => {
      // Case 1: the field that used to raise it — Entry limit.
      const { unmount } = render(<TradeCard data={mockTradeCard} />);
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Edit Limit'));
      });
      const limitInput = screen.getByDisplayValue('2.5');
      await act(async () => {
        fireEvent.change(limitInput, { target: { value: '3.50' } });
        fireEvent.keyDown(limitInput, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('$3.50');
      expect(screen.queryAllByText(/edited/).length).toBe(0);
      unmount();

      // Case 2: the Feature 7 seed case, which used to be the interesting half
      // of the pair — a hand-edit away from a non-default `contracts` prop.
      render(<TradeCard data={mockTradeCard} contracts={4} />);
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Edit Contracts'));
      });
      const contractsInput = screen.getByDisplayValue('4');
      await act(async () => {
        fireEvent.change(contractsInput, { target: { value: '6' } });
        fireEvent.keyDown(contractsInput, { key: 'Enter' });
      });
      expect(screen.getByLabelText('Edit Contracts')).toHaveTextContent('6');
      expect(screen.queryAllByText(/edited/).length).toBe(0);
    });
  });
});
describe('TradeCard — stop-vs-premium gate', () => {
  // B2: the card RENDERS this gate, it does not compute it. The block rides on
  // whichever endpoint produced the stop (`/contracts/structural-stop` here,
  // `/contracts/exit-plan` once an Arithmetic Plan exists), priced with
  // Black-Scholes at today's remaining life. So these tests supply a server
  // block rather than a delta and a mid, and the figures below are the
  // server's, not arithmetic this component can be asked to reproduce.
  //
  // The gate still renders WITHOUT the user having run an Estimate or an
  // Arithmetic plan — a structural stop obtained by "Check structure" carries
  // its own verdict. That early availability is the whole point: a gate that
  // only speaks after two round-trips cannot warn anyone.
  function stopCost(over: Partial<StopCostOut> = {}): StopCostOut {
    return {
      premium: 2.50, valueAtStop: 0.00, lossDollar: 2.50, stopPrice: 178.5,
      fraction: 1.00, status: 'CAUTION', passMaxFraction: 0.70, basis: 'bs_today',
      ...over,
    };
  }

  function cardWithStop(
    stop: { price: number; source: 'order_block' | 'swing_low' | 'swing_high'; confidence: number; distancePct: number; stopCost?: StopCostOut | null },
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

  it('groups matched stop-cost figures separately from execution, quote and order bases', () => {
    const matched = stopCost({ premium: 4, valueAtStop: 1.8, lossDollar: 2.2, fraction: 0.55, status: 'PASS' });
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: matched }, 190)} liveMid={9} contracts={2} />);
    const section = within(screen.getByRole('region', { name: 'Structure & Stops' }));
    expect(section.getByRole('button', { name: 'Check structure' })).toBeVisible();
    expect(section.getByText('Estimated premium remaining per share').parentElement).toHaveTextContent('$1.80/share');
    expect(section.getByText('Premium loss per share').parentElement).toHaveTextContent('$2.20/share');
    expect(section.getByText('Estimated loss per contract').parentElement).toHaveTextContent('$220 per contract');
    expect(section.getByText('Estimated loss for 2 entered contracts').parentElement).toHaveTextContent('$440');
    expect(section.getByText(/Selected contract only.*100 shares/)).toBeVisible();
    expect(section.getByText(/Calculation does not replace/)).toBeVisible();
    expect(section.getByText('Execution stock invalidation').parentElement).toHaveTextContent('$179.64');
    expect(section.getByText(/\$4.00 premium − \$1.80 at \$178.50/)).toBeVisible();
    fireEvent.click(screen.getByLabelText('Edit Limit'));
    fireEvent.change(screen.getByLabelText('Edit Limit'), { target: { value: '8' } });
    fireEvent.blur(screen.getByLabelText('Edit Limit'));
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    fireEvent.change(screen.getByLabelText('Edit Contracts'), { target: { value: '3' } });
    fireEvent.blur(screen.getByLabelText('Edit Contracts'));
    expect(section.getByText('Estimated loss for 3 entered contracts').parentElement).toHaveTextContent('$660');
    expect(section.getByText('Premium loss per share').parentElement).toHaveTextContent('$2.20/share');
  });

  it('keeps missing and zero-width stop costs unavailable in the dedicated section', () => {
    const { rerender } = render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: null }, 190)} />);
    const section = () => within(screen.getByRole('region', { name: 'Structure & Stops' }));
    expect(section().getByText(/Not computed — no priced contract/)).toBeVisible();
    expect(section().queryByText('Premium loss per share')).not.toBeInTheDocument();
    rerender(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, price: 190, distancePct: 0, stopCost: stopCost({ stopPrice: 190, lossDollar: 0, valueAtStop: 2.5 }) }, 190)} resetKey={1} />);
    expect(section().getByText('N/A (stop = price)')).toBeVisible();
    expect(section().queryByText('Premium loss per share')).not.toBeInTheDocument();
  });

  it('hides priced figures while structure refreshes and after its error', async () => {
    let reject!: (reason: Error) => void;
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ price: 190 });
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({ price: 9 });
    (api.getStructuralStop as jest.Mock).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: stopCost() }, 190)} />);
    const section = within(screen.getByRole('region', { name: 'Structure & Stops' }));
    fireEvent.click(section.getByRole('button', { name: 'Check structure' }));
    await waitFor(() => expect(reject).toBeDefined());
    expect(section.getByText('Checking…')).toBeVisible();
    expect(section.queryByText('Premium loss per share')).not.toBeInTheDocument();
    await act(async () => reject(new Error('unavailable')));
    expect(section.getByText(/Couldn't check structure/)).toBeVisible();
    expect(section.queryByText('Premium loss per share')).not.toBeInTheDocument();
  });

  it('flags a stop that costs the whole premium, and shows every input behind it', () => {
    // The contract is worthless at $178.50: nothing of the $2.50 premium
    // survives the stop, so the stop is not a risk control on this contract.
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: stopCost() }, 190.0)} />);

    expect(screen.getByText('MAX LOSS IF THE STOP IS HIT')).toBeInTheDocument();
    expect(screen.getByText('CAUTION · 100% of premium · $0.00/share left')).toBeInTheDocument();
    // Inputs are on screen, not just the verdict — the complaint that produced
    // this gate was a ratio whose inputs were invisible. The premium, the value
    // the contract still holds at the stop, and the stop it was priced at.
    expect(screen.getByText(/\$2\.50 premium − \$0\.00 at \$178\.50 = \$2\.50 of \$2\.50 premium/))
      .toBeInTheDocument();
    // No "(uncapped …)" tail: Black-Scholes cannot exceed the premium for a
    // long option, so there is nothing to cap and nothing to disclose past it.
    expect(screen.queryByText(/uncapped/)).not.toBeInTheDocument();

    // The gate sorts candidates, it never refuses one -- so even a total-loss
    // stop is framed as a sizing input, not a verdict. (The "never REJECT"
    // guarantee itself is asserted on the helper in risk.test.ts; CSS modules
    // mock to {} here so the badge's colour class is not observable in jsdom.)
    expect(screen.getByText(/Not a reason to skip the trade/)).toBeInTheDocument();
  });

  it('PASSes a contract that keeps real value at the same stop', () => {
    // Same stop, a $20 premium: $5.18 of it goes, $14.82 survives.
    const kept = stopCost({ premium: 20.00, valueAtStop: 14.82, lossDollar: 5.18, fraction: 0.26, status: 'PASS' });
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: kept }, 190.0, { mid: 20 })} />);

    expect(screen.getByText('PASS · 26% of premium · $14.82/share left')).toBeInTheDocument();
    expect(screen.getByText(/\$20\.00 premium − \$14\.82 at \$178\.50 = \$5\.18 of \$20\.00 premium/))
      .toBeInTheDocument();
    expect(screen.queryByText(/uncapped/)).not.toBeInTheDocument();
  });

  it('renders the stop-cost readout under the name the race card points at', async () => {
    // The whole rendered surface of the notation rework was unpinned: the
    // formatters had sweeps, but nothing asserted that the header says what
    // BarrierRaceCard tells the reader to go and find, or that the per-contract
    // headline reaches the screen at all. A rename on either side would have
    // left the cross-reference pointing at a row that is nowhere on the page.
    const kept = stopCost({ premium: 20.00, valueAtStop: 14.82, lossDollar: 5.18, fraction: 0.26, status: 'PASS' });
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: kept }, 190.0, { mid: 20 })} />);
    expandLadder();
    // Matches BarrierRaceCard's "Max loss if the stop is hit" cross-reference,
    // case-insensitively (the header is upper-cased in the markup).
    expect(screen.getByText(/MAX LOSS IF THE STOP IS HIT/i)).toBeInTheDocument();
    // And the headline itself: per-contract dollars plus what is left.
    expect(screen.getByText(/per contract — of the \$[\d,]+ premium, \$[\d,]+ left/))
      .toBeInTheDocument();
    // The arithmetic line beneath it, carrying the basis qualifier. Naming the
    // basis is what stops this reading as a contradiction of the barrier race,
    // which reprices the same contract AT THE HORIZON.
    expect(screen.getByText(/premium − .* = .*Black-Scholes, priced today/))
      .toBeInTheDocument();
  });

  it('renders with no Estimate and no Arithmetic plan run', () => {
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: stopCost() }, 190.0)} />);
    // Neither of the two round-trip-gated blocks is present...
    expect(screen.queryByText('Structural level found')).not.toBeInTheDocument();
    expect(screen.queryByText('Bottom (final stop)')).not.toBeInTheDocument();
    // ...but the gate already has its verdict.
    expect(screen.getByText('MAX LOSS IF THE STOP IS HIT')).toBeInTheDocument();
  });

  it('stays hidden when there is no structural stop to measure against', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(screen.queryByText('MAX LOSS IF THE STOP IS HIT')).not.toBeInTheDocument();
  });

  it('stays hidden when the stop sits exactly at the current price', () => {
    // Not a stop, and the structural row above already says so. The server
    // would happily price it (nothing is lost when the stop is where you
    // already are), so the card has to decline rather than print a PASS on a
    // level that controls nothing.
    render(<TradeCard data={cardWithStop(
      { ...ORDER_BLOCK, price: 190.0, distancePct: 0, stopCost: stopCost({ stopPrice: 190.0, valueAtStop: 2.50, lossDollar: 0, fraction: 0, status: 'PASS' }) },
      190.0,
    )} />);
    expect(screen.queryByText('MAX LOSS IF THE STOP IS HIT')).not.toBeInTheDocument();
  });

  it('reads "not computed" when the stop came back with no priced contract', () => {
    // The gate's third state. An endpoint that found a level but could not
    // price it — no contract on the card, an IV that would not invert, an
    // expiring contract — must not leave a blank where the badge was: a
    // contract with no verdict would then read exactly like an unremarkable
    // one, which is the whole failure the third state exists to prevent.
    render(<TradeCard data={cardWithStop({ ...ORDER_BLOCK, stopCost: null }, 190.0)} />);
    expect(screen.getByText('MAX LOSS IF THE STOP IS HIT')).toBeInTheDocument();
    expect(screen.getByText(/Not computed — no priced contract for this stop/)).toBeInTheDocument();
    expect(screen.queryByText(/of premium/)).not.toBeInTheDocument();
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
    (api.getContractQuote as jest.Mock).mockResolvedValueOnce({ price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100 });
    // 1) Check structure — raw structural stop at $178.50, fresh stock price $182.00.
    (api.getStockQuote as jest.Mock).mockResolvedValueOnce({ symbol: 'AAPL', price: 182.0 });
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 178.5, source: 'order_block', confidence: 80, distancePct: 1.92,
      // Priced by the endpoint against ITS OWN stop ($178.50). Deliberately a
      // different verdict from the exit-plan block below, so picking the wrong
      // one is visible rather than a coincidence.
      stopCost: {
        premium: 2.50, valueAtStop: 0.92, lossDollar: 1.58, stopPrice: 178.5,
        fraction: 0.63, status: 'PASS', passMaxFraction: 0.70, basis: 'bs_today',
      },
    });

    render(<TradeCard data={mockTradeCard} />);
    fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    await waitFor(() => {
      expect(screen.getByText(/Structural stop — Order Block/)).toBeInTheDocument();
    });

    // Before any Arithmetic Plan exists, the gate reads the block that came
    // back with the raw structural stop. Sanity-checks the baseline before it
    // changes.
    expect(screen.getByText('PASS · 63% of premium · $0.92/share left')).toBeInTheDocument();

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
        // The SAME gate, priced against the exit plan's wider stop ($170.00)
        // and its own fresh premium ($2.60). The two endpoints disagreeing is
        // the model working, not a bug — a wider stop costs more of the
        // premium (spec §2.2).
        stopCost: {
          premium: 2.60, valueAtStop: 0.00, lossDollar: 2.60, stopPrice: 170.0,
          fraction: 1.00, status: 'CAUTION', passMaxFraction: 0.70, basis: 'bs_today',
        },
      },
      targets: [],
      atr: 3.5,
    });

    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => {
      expect(screen.getAllByText('Bottom (final stop)').length).toBeGreaterThanOrEqual(1);
    });

    // The gate must now read the block the EXIT-PLAN endpoint returned, priced
    // against its own wider stop ($170.00) and its own fresh premium ($2.60):
    // nothing survives, so 100%. If it had stayed on the structural block this
    // would still read 63%.
    expect(screen.getByText('CAUTION · 100% of premium · $0.00/share left')).toBeInTheDocument();
    // The arithmetic line names the exit plan's stop and premium, so which
    // block is on screen is legible without inferring it from the verdict.
    expect(screen.getByText(/\$2\.60 premium − \$0\.00 at \$170\.00 = \$2\.60 of \$2\.60 premium/))
      .toBeInTheDocument();
    expect(screen.queryByText('PASS · 63% of premium · $0.92/share left')).not.toBeInTheDocument();
    const stops = within(screen.getByRole('region', { name: 'Structure & Stops' }));
    expect(stops.getByText('Premium loss per share').parentElement).toHaveTextContent('$2.60/share');
    expect(stops.getByText('Estimated premium remaining per share').parentElement).toHaveTextContent('$0.00/share');
    expect(stops.getByText('Estimated loss for 1 entered contract').parentElement).toHaveTextContent('$260');
    expect(stops.getByText('Arithmetic contract value at stop').parentElement).toHaveTextContent('$1.00/share');
    expect(stops.getByText('Stop-cost source: Arithmetic calculation stop.')).toBeVisible();
    expect(stops.getByText('Execution stock invalidation').parentElement).toHaveTextContent('$179.64');


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
      expect(screen.getByText('Structural level found')).toBeInTheDocument();
    });

    expect(stops.getByText('Premium loss per share').parentElement).toHaveTextContent('$2.60/share');
    expect(stops.getByText('Estimated loss for 1 entered contract').parentElement).toHaveTextContent('$260');

    // The row must quote the EXIT-PLAN stop ($170.00), not the raw structural
    // one ($178.50) — that is Piece 2's whole point, and reading the level
    // directly asserts it more plainly than the ratio derived from it did.
    expect(screen.getAllByText('$170.00').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('$178.50')).not.toBeInTheDocument();

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
          // Deliberately a DIFFERENT verdict from the structural block below,
          // so the gate reading the wrong restored branch is visible rather
          // than a coincidence of matching numbers.
          stopCost: {
            premium: 2.50, valueAtStop: 0.00, lossDollar: 2.50, stopPrice: 185.87,
            fraction: 1.00, status: 'CAUTION', passMaxFraction: 0.70, basis: 'bs_today',
          },
        },
        targets: [],
        atr: 3.5,
      },
      structuralStop: {
        price: 178.5, source: 'order_block', confidence: 80, distancePct: 1.92,
        stopCost: {
          premium: 2.50, valueAtStop: 0.92, lossDollar: 1.58, stopPrice: 178.5,
          fraction: 0.63, status: 'PASS', passMaxFraction: 0.70, basis: 'bs_today',
        },
      },
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
    // `sharedStop` refuses a restored plan with no fresh stock price and falls
    // back to the restored structural stop, so the gate must render THAT
    // branch's block. The exit-plan block on the same card says CAUTION 100%
    // at $185.87; reading it here would be the "two stops on one card"
    // regression, now visible in the verdict AND in the printed stop price.
    expect(screen.getByText('PASS · 63% of premium · $0.92/share left')).toBeInTheDocument();
    expect(screen.getByText(/\$2\.50 premium − \$0\.92 at \$178\.50 = \$1\.58 of \$2\.50 premium/))
      .toBeInTheDocument();
    expect(screen.queryByText('CAUTION · 100% of premium · $0.00/share left')).not.toBeInTheDocument();
  });

  it('reads "not computed" for a plan restored from before the gate moved server-side', () => {
    // Spec test 9's case, on the exit-plan side. `ExitPlan` is persisted
    // (portfolioStore, and the parent's per-contract cache), so a blob written
    // before B2 carries no `stopCost` at all. That must surface as the third
    // state and never as a PASS: a contract with no verdict reading like an
    // unremarkable one is the whole failure the third state exists to prevent.
    // No store migration is needed precisely because absence is already the
    // honest answer here.
    const preB2: TradeCardData = {
      ...restoredCard,
      exit: {
        ...restoredCard.exit,
        exitPlan: { ...restoredCard.exit.exitPlan!, stop: { ...restoredCard.exit.exitPlan!.stop, stopCost: undefined } },
        structuralStop: { ...restoredCard.exit.structuralStop!, stopCost: undefined },
      },
    };
    render(<TradeCard data={preB2} />);
    expect(screen.getByText('MAX LOSS IF THE STOP IS HIT')).toBeInTheDocument();
    expect(screen.getByText(/Not computed — no priced contract for this stop/)).toBeInTheDocument();
    expect(screen.queryByText(/of premium ·/)).not.toBeInTheDocument();
  });
});

// -- The Barrier Race, driven through the real card ---------------------------
//
// Spec section 4 tests 12 and 13 were previously satisfied by rendering
// BarrierRaceCard with `barriersChanged` / `isFresh` set by hand — which proves
// the card honours a prop, and nothing about whether TradeCard ever computes
// that prop correctly. Every first-passage mock in this file returned a
// response with no `race` key at all, so no test in the suite had ever rendered
// the race through the component that owns it. Both of the bugs below were
// reachable by a ten-line test and shipped anyway.

const RACE_RESPONSE = {
  // ONE real `estimate_first_passage` call, whole: targets, invalidation and
  // race together (186.1 spot / 190 strike / 24 DTE / $2.75 premium / stop 180 /
  // premium_stop_pct 1.5/2.75, seed 7).
  //
  // Regenerating only the race block left two states the backend cannot
  // produce. `invalidation.expectedDays` and `daysAnyPathReachedStop` are
  // literally the same variable (`stop_expected_days`) — a backend test asserts
  // the identity over the wire — and the fixture had them 13 days apart, so the
  // card rendered "(median ~4d)" in the barriers block and "repriced at 17d —
  // the median day any path reaches the stop" in the risk chain. And
  // `targets[2].optionPrice` read 4.13 where the race's own
  // `targetOptionPrice` read 4.12; both are `round(2.75 * 1.50, 2)`, which is
  // 4.12 under Python's banker's rounding.
  targets: [
    { pct: 0.20, stockPrice: 189.04, optionPrice: 3.30, probability: 0.566, expectedDays: 4 },
    { pct: 0.35, stockPrice: 189.86, optionPrice: 3.71, probability: 0.440, expectedDays: 7 },
    { pct: 0.50, stockPrice: 190.62, optionPrice: 4.12, probability: 0.3455, expectedDays: 10 },
  ],
  invalidation: { probability: 0.0585, expectedDays: 17 },
  race: {
    outcomes: [
      {
        targetPct: 0.20, targetOptionPrice: 3.30,
        pTargetFirst: 0.5495, pStockStopFirst: 0.0, pPremiumStopFirst: 0.4415, pNeither: 0.009,
        daysTarget: 4, daysStockStop: null, daysPremiumStop: 11, daysAnyPathReachedStop: 17,
        weightTargetFirst: 0.55, weightStockStopFirst: 0.0,
        weightPremiumStopFirst: 0.44, weightNeither: 0.01,
        terminalMean: 2.41, rewardDollar: 0.55, repriceDaysStockStop: 17,
        stopRepricedValue: 0.09, riskStockStop: 2.66, riskPremiumStop: 1.5,
        rrStockStop: 0.2067669172932331, rrPremiumStop: 0.3666666666666667,
        edgePerContract: -36.0,
      },
      {
        targetPct: 0.35, targetOptionPrice: 3.71,
        pTargetFirst: 0.427, pStockStopFirst: 0.0, pPremiumStopFirst: 0.55, pNeither: 0.023,
        daysTarget: 7, daysStockStop: null, daysPremiumStop: 12, daysAnyPathReachedStop: 17,
        weightTargetFirst: 0.43, weightStockStopFirst: 0.0,
        weightPremiumStopFirst: 0.55, weightNeither: 0.02,
        terminalMean: 2.51, rewardDollar: 0.96, repriceDaysStockStop: 17,
        stopRepricedValue: 0.09, riskStockStop: 2.66, riskPremiumStop: 1.5,
        rrStockStop: 0.3609022556390977, rrPremiumStop: 0.6416666666666667,
        edgePerContract: -42.0,
      },
      {
        targetPct: 0.50, targetOptionPrice: 4.12,
        pTargetFirst: 0.3355, pStockStopFirst: 0.0, pPremiumStopFirst: 0.616, pNeither: 0.0485,
        daysTarget: 9, daysStockStop: null, daysPremiumStop: 13, daysAnyPathReachedStop: 17,
        weightTargetFirst: 0.33, weightStockStopFirst: 0.0,
        weightPremiumStopFirst: 0.62, weightNeither: 0.05,
        terminalMean: 2.69, rewardDollar: 1.37, repriceDaysStockStop: 17,
        stopRepricedValue: 0.09, riskStockStop: 2.66, riskPremiumStop: 1.5,
        rrStockStop: 0.5150375939849624, rrPremiumStop: 0.9166666666666667,
        edgePerContract: -48.0,
      },
    ],
    premiumStopPrice: 1.25,
    premiumStopPct: 1.5 / 2.75,
    stockStopPrice: 180.0,
    premiumUsed: 2.75,
    ivSolved: true,
    nPaths: 2000,
  },
};

// The identity the backend asserts over the wire, mirrored here so this fixture
// cannot drift back into a shape the endpoint cannot produce.
it('RACE_RESPONSE is a shape the backend can actually return', () => {
  expect(RACE_RESPONSE.invalidation.expectedDays)
    .toBe(RACE_RESPONSE.race.outcomes[0].daysAnyPathReachedStop);
  RACE_RESPONSE.race.outcomes.forEach((o, i) => {
    expect(o.targetOptionPrice).toBe(RACE_RESPONSE.targets[i].optionPrice);
    const weights = [o.weightTargetFirst, o.weightStockStopFirst,
      o.weightPremiumStopFirst, o.weightNeither];
    expect(Math.round(weights.reduce((a, b) => a + b, 0) * 100)).toBe(100);
  });
});

describe('the barrier race, through the card that owns it', () => {
  beforeEach(() => {
    // expandLadder() is a TOGGLE and CollapsibleSection persists its collapsed
    // state to localStorage, so without this a prior test in this describe can
    // leave it expanded and the click here collapses it instead.
    window.localStorage.clear();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    // A structural stop that DIFFERS from the flat scan-time invalidation
    // (179.64). That difference is the whole point: it is what the estimate
    // used to race against itself over.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
  });

  it('renders the race on the FIRST estimate click of a mount', async () => {
    // THE BUG: the auto structural refresh was fired without being awaited, so
    // the estimate went out carrying the flat scan stop (179.64), the race
    // snapshotted that same level, the structural fetch then landed at 180.0
    // and `raceBarriersMoved` flipped true. The first click rendered
    // "Barriers changed - re-run the estimate" and no bars at all, and the
    // estimate really had been computed against the wrong stop.
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });

    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });
    expect(screen.queryByText(/Barriers changed/)).not.toBeInTheDocument();
    // And it raced against the structural stop, not the flat scan-time one.
    expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
      expect.objectContaining({ invalidation_price: 180.0 }),
      expect.any(AbortSignal),
    );
  });

  it('clears the race, rather than re-sorting it, when the premium stop is edited', async () => {
    // Spec section 3.3: both barriers are live and user-movable, and every bar
    // on the card was measured against the values at request time. Watching the
    // bars re-sort must require a click; it must never appear to happen on its
    // own. Driven here through the real editable field, not a prop.
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });

    expandLadder();
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    });
    const input = screen.getByDisplayValue('1.5');
    await act(async () => {
      fireEvent.change(input, { target: { value: '0.90' } });
      fireEvent.blur(input);
    });

    expect(screen.getByText(/Barriers changed/)).toBeInTheDocument();
    expect(screen.queryAllByTestId('segment-Target first')).toHaveLength(0);
  });

  it('prints no race numbers anywhere for a restored, never-refetched estimate', async () => {
    // THE OTHER BUG. `firstPassage` is seeded from the parent's per-contract
    // cache at mount and `raceBarriers` is null then, so nothing looked
    // "moved": BarrierRaceCard correctly refused to render, while the Final
    // Recommendation printed that same arbitrarily-old race's armed stop and
    // dollar edge — and suppressed the un-stale invalidation fallback beneath
    // it. A stale armed level and a stale dollar edge, in the one place on the
    // card a number is most likely to be acted on.
    const cachedCard: TradeCardData = {
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        firstPassage: { ...RACE_RESPONSE, computedAt: '2026-08-01T10:00:00.000Z' },
        firstPassageContext: { premium: 2.75, delta: 0.42, targetPct: { t1: 0.20, t2: 0.35, t3: 0.50 } },
      },
    };
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    rerender(<TradeCard data={cachedCard} />);
    await waitFor(() => {
      expect(screen.getAllByText('T20%').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryAllByTestId('segment-Target first')).toHaveLength(0);
    expect(screen.queryByText(/Armed stop/)).not.toBeInTheDocument();
    expect(screen.queryByText(/T20% edge/)).not.toBeInTheDocument();
    // ...and NOTHING replaces them. The fallback this bug used to suppress —
    // the standalone invalidation probability — has since been removed
    // outright, so the summary shows its targets and stops. That is the
    // stronger version of the same guarantee: round 9 fixed a stale reading
    // that hid a fresh one, and with no fallback underneath, a stale race can
    // no longer hide anything at all.
    expect(screen.queryByText('Invalidation probability')).not.toBeInTheDocument();
  });
});

// -- Round 2: the two button sequences the awaited refresh did not cover ------
//
// Awaiting the auto structural refresh inside the estimate handler closed the
// case where nothing had been fetched yet. It did not cover a fetch the USER
// started first, and both of those are ordinary sequences on this card: the
// handler skipped its own refresh (structuralLoading already true) or read an
// exit plan that landed after the estimate was already in flight. Either way
// the race cleared itself with "Barriers changed" on a click just made, and the
// Monte Carlo probability had been measured against a stop other than the one
// on screen.

describe('the estimate never races a level it depends on', () => {
  beforeEach(() => {
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
  });

  it('cannot be started while a structural-stop fetch the user began is still in flight', async () => {
    let releaseStructural: (v: unknown) => void = () => {};
    (api.getStructuralStop as jest.Mock).mockReturnValueOnce(
      new Promise((resolve) => { releaseStructural = resolve; }),
    );
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });

    // The estimate must be unavailable, not merely slow: dispatching here sent
    // the flat scan stop (179.64) and then watched the structural land at 180.
    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeDisabled();
    expect(screen.getByText(/Waiting for the stop this estimate races against/)).toBeInTheDocument();

    await act(async () => {
      releaseStructural({
        available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
      });
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });
    expect(screen.queryByText(/Barriers changed/)).not.toBeInTheDocument();
    expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
      expect.objectContaining({ invalidation_price: 180.0 }),
      expect.any(AbortSignal),
    );
  });

  it('cannot be started while an Arithmetic Plan the user began is still in flight', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    let releasePlan: (v: unknown) => void = () => {};
    (api.getExitPlan as jest.Mock).mockReturnValueOnce(
      new Promise((resolve) => { releasePlan = resolve; }),
    );
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    });

    // The plan supplies sharedStop's higher-precedence branch, so an estimate
    // dispatched now races it: the plan lands afterwards, sharedStop switches
    // to exit_plan, and the race clears itself.
    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeDisabled();

    await act(async () => {
      releasePlan({
        stop: {
          price: 176.5, source: 'structural', contractPrice: 1.2, rrModel: 'Heston repriced',
          structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 176.5,
          atrFloorPrice: 175.0, distanceDollar: 8.6,
        },
        targets: [],
        atr: 3.5,
      });
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });
    expect(screen.queryByText(/Barriers changed/)).not.toBeInTheDocument();
    expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
      expect.objectContaining({ invalidation_price: 176.5 }),
      expect.any(AbortSignal),
    );
  });

  it('drops the previous contract\'s race numbers when the contract changes', async () => {
    // The reset effect is what this pins. The narrower hazard it is paired
    // with — firstPassageIsFreshRef is cleared inside that effect, which runs
    // AFTER commit, so for one painted frame the ref still reads true beside
    // the previous contract's values — is NOT observable here: React Testing
    // Library flushes effects inside `rerender`, so the intermediate frame
    // never reaches an assertion. `raceBarriers.contract === data.contract` in
    // raceIsShowable closes it from state rather than from a ref, and is
    // deliberately kept as defence in depth even though only this coarser
    // behaviour can be tested.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });
    expect(screen.getByText(/Armed stop/)).toBeInTheDocument();

    rerender(
      <TradeCard data={{ ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' }} />,
    );
    expect(screen.queryByText(/Armed stop/)).not.toBeInTheDocument();
    expect(screen.queryAllByTestId('segment-Target first')).toHaveLength(0);
  });
});

// -- Round 4: a request that never settles must not strand the card ----------
//
// `lib/api.ts` sets no timeout on fetch. That was survivable while each request
// only drove its own spinner, and stopped being survivable once the Estimate
// button was disabled on structuralLoading || exitPlanLoading. The first
// attempt at a timeout made it worse: it aborted the request's own controller,
// which every handler here reads as "superseded by a newer request", so the
// catch returned silently AND the finally skipped clearing the loading flag.
// The request was cancelled and the spinner became permanent.

describe('a request that never settles', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
  });
  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  /** Rejects when the caller's signal aborts, the way a real fetch does. */
  function neverSettles() {
    return jest.fn((..._args: unknown[]) => {
      const signal = _args.find((a): a is AbortSignal => a instanceof AbortSignal);
      return new Promise((_resolve, reject) => {
        signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    });
  }

  it('gives "Check structure" back after the deadline, and says it failed', async () => {
    (api.getStructuralStop as jest.Mock).mockImplementation(neverSettles());
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });
    expect(screen.getByRole('button', { name: /checking structure/i })).toBeDisabled();

    await act(async () => {
      jest.advanceTimersByTime(21_000);
    });

    expect(screen.getByRole('button', { name: /check structure/i })).toBeEnabled();
    // And the Estimate button, which this one's loading flag also gates.
    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
    // The test name promises this; it used to assert only the buttons.
    expect(screen.getByText(/Couldn.t check structure/)).toBeInTheDocument();
  });

  it('reports a deadline that lands while the quote sub-fetches are hanging', async () => {
    // The estimate's two quote fetches `.catch(() => null)`, so an abort never
    // throws — it arrives at an early return instead. A bare `if (aborted)
    // return` there skipped the error AND left firstPassage `undefined`, which
    // the parent's cache reads as "in flight, don't touch", so the previous
    // estimate for this contract survived and reappeared later.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    (api.getStockQuote as jest.Mock).mockImplementation(neverSettles());
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await act(async () => {
      jest.advanceTimersByTime(21_000);
    });

    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
    expect(screen.getByText(/Couldn.t compute an estimate/)).toBeInTheDocument();
  });

  it('gives the Estimate button back after the deadline', async () => {
    // The slowest request on the card, and the one left unbounded entirely.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockImplementation(neverSettles());
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    expect(screen.getByRole('button', { name: /estimating/i })).toBeDisabled();

    await act(async () => {
      jest.advanceTimersByTime(21_000);
    });

    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
    expect(screen.getByText(/Couldn.t compute an estimate/)).toBeInTheDocument();
  });

  it('reports a deadline that lands on the structural refresh inside an Estimate', async () => {
    // A DIFFERENT guard from the sub-fetch one above: that hangs getStockQuote,
    // which trips the first check. This hangs the auto structural refresh,
    // whose .then().catch().finally() chain can never reject — so the deadline
    // arrives at the check AFTER it, the one that runs on the first Estimate
    // click of every mount. Without a deadline-aware guard there, the estimate
    // dies with no error and firstPassage left `undefined`, which the parent's
    // cache reads as "in flight, don't touch".
    (api.getStructuralStop as jest.Mock).mockImplementation(neverSettles());
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
    // This file does not clear mocks between tests, and the call COUNT is the
    // assertion here.
    (api.getFirstPassageEstimate as jest.Mock).mockClear();
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await act(async () => {
      jest.advanceTimersByTime(21_000);
    });

    // It never got as far as dispatching the simulation...
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    // ...and it said so, rather than re-enabling the button in silence.
    expect(screen.getByText(/Couldn.t compute an estimate/)).toBeInTheDocument();
  });

  it('gives "Compute Arithmetic Plan" back after the deadline', async () => {
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    (api.getExitPlan as jest.Mock).mockImplementation(neverSettles());
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    });
    expect(screen.getByRole('button', { name: /computing arithmetic plan/i })).toBeDisabled();

    await act(async () => {
      jest.advanceTimersByTime(21_000);
    });

    expect(screen.getByRole('button', { name: /compute arithmetic plan/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /run monte carlo estimate/i })).toBeEnabled();
  });

  it('stays silent when a newer request supersedes an older one', async () => {
    // The one abort that must NOT surface as an error: two clicks in a row.
    let resolveSecond: (v: unknown) => void = () => {};
    (api.getStructuralStop as jest.Mock)
      .mockImplementationOnce(neverSettles())
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });
    await act(async () => {
      jest.advanceTimersByTime(5_000);
    });
    expect(screen.queryByText(/Couldn.t check structure/)).not.toBeInTheDocument();

    await act(async () => {
      resolveSecond({
        available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
      });
    });
    expect(screen.queryByText(/Couldn.t check structure/)).not.toBeInTheDocument();
  });
});

// -- Round 6: gates that were described at length and pinned by nothing -------
//
// Five mutations survived the entire suite. Each of these kills one.

describe('the race gates, mutation-pinned', () => {
  beforeEach(() => {
    // This file does not clear mocks between tests (see jest.config.ts), and a
    // describe above installs persistent never-settling implementations and
    // fake timers. Reset both here rather than depend on execution order.
    jest.useRealTimers();
    // The ladder's collapsed state persists to localStorage, so expandLadder()
    // is a no-op if a previous test in this describe already expanded it.
    window.localStorage.clear();
    (api.getStockQuote as jest.Mock).mockReset();
    (api.getContractQuote as jest.Mock).mockReset();
    (api.getStructuralStop as jest.Mock).mockReset();
    (api.getFirstPassageEstimate as jest.Mock).mockReset();
    (api.getExitPlan as jest.Mock).mockReset();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180.0, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
  });

  it('does not print "expires today" for a RESTORED refusal from another contract', () => {
    // The persistent version of the same hazard, and the one that is actually
    // observable: `firstPassage` is seeded from the parent's per-contract cache
    // at mount, so a restored 0-DTE estimate rendered "Not simulated — contract
    // expires today" indefinitely, not for one frame.
    //
    // The rerender-based test below cannot pin this: RTL flushes the
    // contract-change reset effect inside `rerender`, so the un-gated read is
    // already `undefined` by the time anything is asserted.
    render(<TradeCard data={{
      ...mockTradeCard,
      symbol: 'MSFT',
      contract: 'MSFT 300C 06/19',
      exit: {
        ...mockTradeCard.exit,
        firstPassage: {
          targets: [],
          invalidation: { probability: 0.30, expectedDays: 4 },
          race: null,
          computedAt: '2026-01-01T00:00:00.000Z',
        },
      },
    }}
    />);
    expect(screen.queryByText(/Not simulated/)).not.toBeInTheDocument();
  });

  it('drops the "expires today" refusal when the contract changes', async () => {
    // `race: null` is the backend refusing to simulate a 0-DTE contract. The
    // card renders that copy before any freshness check, so an un-gated
    // `race={firstPassage?.race}` put "Not simulated — contract expires today"
    // under the NEXT contract's header for the frame between the switch and the
    // reset effect. The gate was added with a comment and no test.
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({
      ...RACE_RESPONSE, race: null,
    });
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    expect(screen.getByText(/Not simulated/)).toBeInTheDocument();

    rerender(
      <TradeCard data={{ ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT 300C 06/19' }} />,
    );
    expect(screen.queryByText(/Not simulated/)).not.toBeInTheDocument();
  });

  it('stops printing race numbers in the Final Recommendation once a barrier moves', async () => {
    // raceIsShowable = raceIsFresh && !raceBarriersMoved. Dropping the second
    // term left every test green, because the card has its own
    // barriers-changed branch and the Final Recommendation does not.
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    expect(screen.getByText(/Armed stop/)).toBeInTheDocument();

    expandLadder();
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    });
    const input = screen.getByDisplayValue('1.5');
    await act(async () => {
      fireEvent.change(input, { target: { value: '0.90' } });
      fireEvent.blur(input);
    });

    expect(screen.queryByText(/Armed stop/)).not.toBeInTheDocument();
    // The gate's whole job now: show the race's numbers or show none. It no
    // longer swaps in a standalone invalidation probability, which counted
    // paths that touched the stock stop even where the premium stop had
    // already fired days earlier.
    expect(screen.queryByText('Invalidation probability')).not.toBeInTheDocument();
  });

  it('credits the default, not the field, when the field could not set the barrier', async () => {
    // premiumStopFromField is snapshotted at REQUEST time from the premium the
    // request used. Hard-coding it true made the card claim the editable field
    // set a barrier the backend had actually defaulted.
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      // A premium BELOW the $1.50 dollar stop, so the fraction is >= 1 and
      // nothing is sent.
      price: 1.20, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });

    expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(
      expect.objectContaining({ premium_stop_pct: undefined }),
      expect.any(AbortSignal),
    );
    expect(screen.getByText(/the default/)).toBeInTheDocument();
    expect(screen.queryByText(/from the editable field above/)).not.toBeInTheDocument();
  });

  it('keeps the stock-stop probability only when the STOCK stop is the one that held', async () => {
    // "The stock-stop probability is unaffected by the premium stop" is only
    // true when the premium stop is what moved. One boolean for both barriers
    // printed it after a Check-structure click too, quoting a probability
    // measured against a level no longer shown anywhere.
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RACE_RESPONSE);
    render(<TradeCard data={mockTradeCard} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => {
      expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3);
    });

    // Move the STOCK stop, by checking structure again at a different level.
    (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
      available: true, price: 170.0, source: 'swing_low', confidence: 60, distancePct: 8.6,
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
    });

    expect(screen.getByText(/Barriers changed/)).toBeInTheDocument();
    expect(screen.queryByText(/unaffected by the premium stop/)).not.toBeInTheDocument();
  });
});

// ── EDITED-FLAG-2026-09-04 — the card-level "edited" indicator ──────────────
//
// The rule itself is unit-tested in lib/__tests__/tradeCardEdits.test.ts, where
// the mergePlan regression is pinned against a sabotaged value-only rule. These
// tests pin the WIRING: that the card feeds that rule its real overlay, its
// real plan, and a record of edits that patch() and revert() both maintain.
describe('TradeCard — the card-level edited indicator', () => {
  beforeEach(() => localStorage.clear());

  const badge = () => screen.queryByText('Edited');
  // The badge's OWN tooltip, by its own opening words — `getByRole('tooltip')`
  // is ambiguous the moment the ladder is expanded and the card's other
  // tooltips mount.
  const badgeTip = () => screen.getByText(/^Edited on this card/);
  const typeInto = (label: string, v: string) => {
    fireEvent.click(screen.getByLabelText(`Edit ${label}`));
    const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
    fireEvent.change(input, { target: { value: v } });
    fireEvent.blur(input);
  };

  it('does not render on a card nobody has touched', () => {
    render(<TradeCard data={mockTradeCard} />);
    expect(badge()).not.toBeInTheDocument();
  });

  it('appears once a field is edited, and names that field', () => {
    render(<TradeCard data={mockTradeCard} />);
    typeInto('Contracts', '3');
    expect(badge()).toBeInTheDocument();
    expect(badgeTip()).toHaveTextContent('Contracts');
  });

  it('names several edited fields at once, in card order', () => {
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    typeInto('Premium stop', '0.9');
    typeInto('Limit', '2.1');
    typeInto('Contracts', '4');
    expect(badgeTip()).toHaveTextContent('Entry limit, Contracts, Premium stop');
  });

  it('does NOT appear when mergePlan moves the plan under an untouched card', () => {
    // THE REGRESSION, through the card. Same contract, recomputed exit — the
    // window the contract-change reset does not cover. Every one of these four
    // fields lacks a follow-the-seed effect, so the overlay keeps its old seed
    // while `data` moves; a value-only indicator would call this "Edited".
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    const merged: TradeCardData = {
      ...mockTradeCard,
      entry: { ...mockTradeCard.entry, limit: 3.4, maxFill: 3.6 },
      exit: {
        ...mockTradeCard.exit,
        premiumStop: 0.8,
        invalidation: 171.2,
        timeStopDays: 21,
        targets: [{ ...mockTradeCard.exit.targets[0], targetPrice: 211.5, stockPrice: 211.5 }],
      },
    };
    rerender(<TradeCard data={merged} />);
    expect(badge()).not.toBeInTheDocument();
  });

  it('clears when the user clears the input back to inheriting the plan', () => {
    // CLEAR-TO-INHERIT-2026-09-05's gesture, which this badge exists to make
    // discoverable: an empty field means "follow the plan again".
    render(<TradeCard data={mockTradeCard} />);
    expandLadder();
    typeInto('Premium stop', '0.9');
    expect(badge()).toBeInTheDocument();
    typeInto('Premium stop', '');
    expect(badge()).not.toBeInTheDocument();
  });

  it('clears when the user retypes the plan value by hand', () => {
    render(<TradeCard data={mockTradeCard} />);
    typeInto('Contracts', '3');
    expect(badge()).toBeInTheDocument();
    typeInto('Contracts', '1');
    expect(badge()).not.toBeInTheDocument();
  });

  it('appears on mount for an edit the parent restored from its cache', () => {
    render(<TradeCard data={mockTradeCard} initialEntryLimit={2.71} />);
    expect(badge()).toBeInTheDocument();
    expect(badgeTip()).toHaveTextContent('Entry limit');
  });

  it('does not appear for a restored value that matches the plan anyway', () => {
    // Restored-and-identical is inheriting, whatever the cache says.
    render(<TradeCard data={mockTradeCard} initialEntryLimit={mockTradeCard.entry.limit} />);
    expect(badge()).not.toBeInTheDocument();
  });

  it('resets with the card when the user navigates to another candidate', () => {
    const { rerender } = render(<TradeCard data={mockTradeCard} />);
    typeInto('Contracts', '3');
    expect(badge()).toBeInTheDocument();
    const other: TradeCardData = { ...mockTradeCard, symbol: 'MSFT', contract: 'MSFT|400|2026-05-16|C' };
    rerender(<TradeCard data={other} />);
    expect(badge()).not.toBeInTheDocument();
  });

  // ── ROUND 1 FINDING: the Contracts round-trip ───────────────────────────
  //
  // step-7-trade-card/page.tsx writes `orderContractsBySymbol` from
  // `handleEditsChange` UNCONDITIONALLY and feeds it straight back as the
  // card's `contracts` prop — unlike the three caches beside it, which write
  // `null` unless `meta.touched` says the user typed. A baseline taken from
  // that prop is therefore the user's own edit, and can never differ from
  // itself: the badge stayed silent on the one field whose count reaches a
  // broker order. `ParentHarness` reproduces that wiring; without it the
  // gesture passes and the defect is invisible, which is exactly how it
  // shipped past the first round of tests.
  function ParentHarness({ data = mockTradeCard }: { data?: TradeCardData }) {
    const [orderContractsBySymbol, setMap] = React.useState<Record<string, number>>({});
    return (
      <TradeCard
        data={data}
        contracts={orderContractsBySymbol[data.symbol] ?? 1}
        onEditsChange={(overlay) => {
          setMap((prev) => (prev[data.symbol] === overlay.contracts
            ? prev
            : { ...prev, [data.symbol]: overlay.contracts }));
        }}
      />
    );
  }

  it('raises on a Contracts edit even when the parent echoes it back as the prop', () => {
    render(<ParentHarness />);
    expect(badge()).not.toBeInTheDocument();
    typeInto('Contracts', '7');
    expect(badge()).toBeInTheDocument();
    expect(badgeTip()).toHaveTextContent('Contracts');
  });

  it('clears again when the user types the planned size back, echo and all', () => {
    render(<ParentHarness />);
    typeInto('Contracts', '7');
    expect(badge()).toBeInTheDocument();
    typeInto('Contracts', '1');
    expect(badge()).not.toBeInTheDocument();
  });

  it('still raises for the threaded fields under the same wiring', () => {
    // A control: the round-trip is specific to `contracts`, and fixing it must
    // not have been a change to how the other fields are measured.
    render(<ParentHarness />);
    typeInto('Limit', '3.1');
    expect(badge()).toBeInTheDocument();
    expect(badgeTip()).toHaveTextContent('Entry limit');
  });

  it('treats a card mounted at a non-default size as resuming that edit', () => {
    // The count reaches the card only through `orderContractsBySymbol`, whose
    // sole writer is a user edit — so a restored 4 IS an edit, the same
    // reading initialEntryLimit gets.
    render(<TradeCard data={mockTradeCard} contracts={4} />);
    expect(badge()).toBeInTheDocument();
    expect(badgeTip()).toHaveTextContent('Contracts');
  });

  it('does not raise on a card mounted at the planned size', () => {
    render(<TradeCard data={mockTradeCard} contracts={1} />);
    expect(badge()).not.toBeInTheDocument();
  });
});

// ── TARGET-VINTAGE-2026-09-04 — the Monte Carlo target rows are gated ───────
//
// `firstPassage` is restored from the parent's per-contract cache on mount and
// `lastRunMethod` is derived from `computedAt` alone, so before this gate a
// restored estimate reinstated the whole monte_carlo branch at whatever vintage
// it was cached at. With the invalidation fallback removed, those rows are the
// only numbers left in the branch — so an ungated vintage WAS the branch.
describe('TradeCard — Final Recommendation target rows gate on freshness', () => {
  beforeEach(() => {
    localStorage.clear();
    // estimateFirstPassage awaits getStructuralStop before it ever reaches
    // getFirstPassageEstimate, so leaving it unmocked fails the estimate and
    // the branch never returns.
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: false, price: null, source: null, confidence: null, distancePct: null,
    });
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.75, delta: 0.42, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
  });

  const ESTIMATE = {
    targets: [{ pct: 0.20, stockPrice: 190.5, optionPrice: 3.3, probability: 0.72, expectedDays: 5 }],
    invalidation: { probability: 0.30, expectedDays: 4 },
  };

  // A card arriving with a cached estimate spliced into exit — exactly what
  // withCachedEstimate does on a Prev/Next return, and the only way to reach
  // lastRunMethod === 'monte_carlo' without clicking Estimate this mount.
  const restored: TradeCardData = {
    ...mockTradeCard,
    exit: {
      ...mockTradeCard.exit,
      firstPassage: { ...ESTIMATE, race: null, computedAt: '2026-09-07T14:32:00.000Z' },
    },
  } as unknown as TradeCardData;

  const staleNotice = () => screen.queryByText(/Not re-run this session/);
  // SCOPED TO THE FINAL RECOMMENDATION, deliberately. The standalone Monte
  // Carlo card above renders the same restored `firstPassage.targets` ungated —
  // that is its own readout and outside TARGET-VINTAGE's scope — so a
  // document-wide query for the option price matches THAT row and would pass
  // whatever this branch does. `computed via:` is unique to this card.
  const finalRec = () => within(
    screen.getByText(/computed via: Monte Carlo/).closest('div') as HTMLElement,
  );

  it('names Monte Carlo as the last method but does NOT print its target numbers', () => {
    render(<TradeCard data={restored} />);
    // The branch is still selected — this is not a change to lastRunMethod.
    expect(screen.getByText(/computed via: Monte Carlo/)).toBeInTheDocument();
    // THE REGRESSION: yesterday's option price and probability, printed here as
    // if they described the premium on screen today.
    expect(finalRec().queryByText(/\$3\.30/)).not.toBeInTheDocument();
    expect(finalRec().queryByText('T20%')).not.toBeInTheDocument();
    expect(staleNotice()).toBeInTheDocument();
  });

  it('prints them once Estimate has actually been clicked this mount', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce(ESTIMATE);
    render(<TradeCard data={restored} />);
    expect(staleNotice()).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    // The in-flight state clears `firstPassage`, so the branch unmounts and
    // remounts — wait for it to come BACK before reading inside it.
    await screen.findByText(/computed via: Monte Carlo/);
    expect(finalRec().getByText('T20%')).toBeInTheDocument();
    expect(staleNotice()).not.toBeInTheDocument();
  });

  it('goes back to withholding them when the user navigates to another candidate', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce(ESTIMATE);
    const { rerender } = render(<TradeCard data={restored} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await screen.findByText(/computed via: Monte Carlo/);
    expect(finalRec().getByText('T20%')).toBeInTheDocument();

    // Away to another candidate carrying ITS OWN cached estimate. Freshness is
    // per-mount, so the incoming card starts stale however fresh this one was.
    const other: TradeCardData = {
      ...restored, symbol: 'MSFT', contract: 'MSFT|400|2026-05-16|C',
    };
    rerender(<TradeCard data={other} />);
    expect(finalRec().queryByText('T20%')).not.toBeInTheDocument();
    expect(staleNotice()).toBeInTheDocument();
  });
});

describe('AREA3 captured stock-risk freshness', () => {
  it('reports moved stop and restoration without automatically repricing', () => {
    const report = jest.fn();
    const card = { ...mockTradeCard, exit: { ...mockTradeCard.exit, stockStopLoss: 0.5, stockStopLossAt: 179.64 } };
    const { rerender } = render(<TradeCard data={card} onRrStaleChange={report} />);
    expect(report).toHaveBeenLastCalledWith(false);
    const moved = { ...card, exit: { ...card.exit, invalidation: 179.65 } };
    rerender(<TradeCard data={moved} onRrStaleChange={report} />);
    expect(report).toHaveBeenLastCalledWith(true);
    rerender(<TradeCard data={card} onRrStaleChange={report} />);
    expect(report).toHaveBeenLastCalledWith(false);
  });
  it('legacy cards without captured loss never claim a stale captured ratio', () => {
    const report = jest.fn();
    render(<TradeCard data={mockTradeCard} initialInvalidation={170} onRrStaleChange={report} />);
    expect(report).toHaveBeenLastCalledWith(false);
  });
});

// Re-pinned by TRADING-REVIEW-PHASE-C-RR: the captured stock-stop loss is no
// longer an R/R risk leg, so a moved stock stop no longer swaps the ladder onto
// the premium stop (was 5.0x -> 1.7x -> 5.0x). The backend ratio is served
// only when it was computed on the full-premium basis; a captured ratio on the
// old basis is recomputed on the full premium: (5.0 - 2.5) / 2.5 = 1.0x.
it('AREA3 ladder serves the full-premium backend ratio whether or not the stock stop moves', () => {
  const card = { ...mockTradeCard, exit: { ...mockTradeCard.exit, stockStopLoss: 0.5, stockStopLossAt: 179.64,
    rrRiskBasis: 'full_premium' as const,
    targets: [{ ...mockTradeCard.exit.targets[0], rrContribution: 5.0 }] } };
  const { rerender } = render(<TradeCard data={card} />);
  expandLadder();
  expect(screen.getByText('5.0x')).toBeInTheDocument();
  rerender(<TradeCard data={{ ...card, exit: { ...card.exit, invalidation: 179.65 } }} />);
  expect(screen.getByText('5.0x')).toBeInTheDocument();
  expect(screen.queryByText('1.7x')).not.toBeInTheDocument();
  rerender(<TradeCard data={{ ...card, exit: { ...card.exit, rrRiskBasis: 'stock_stop' } }} />);
  expect(screen.getByText('1.0x')).toBeInTheDocument();
  expect(screen.queryByText('5.0x')).not.toBeInTheDocument();
});


it('presentation wires each qualification panel to its unchanged result and bars', () => {
  (ScoreCardPanel as jest.Mock).mockClear();
  render(<TradeCard data={mockTradeCard} />);
  const calls = (ScoreCardPanel as jest.Mock).mock.calls.map(([props]) => props);
  expect(calls.find((props) => props.title === 'Stock Scorecard')).toMatchObject({
    qualification: { card: mockTradeCard, kind: 'stock' }, total: mockTradeCard.stockScore,
    confidence: mockTradeCard.stockConfidence, bars: [{ value: 85 }, { value: 78 }, { value: 72 }, { value: 90 }, { value: 65 }],
  });
  expect(calls.find((props) => props.title === `Contract — ${mockTradeCard.contract}`)).toMatchObject({
    qualification: { card: mockTradeCard, kind: 'contract' }, total: mockTradeCard.contractScore,
    confidence: mockTradeCard.contractConfidence,
  });
  expect(screen.getByText('$190 Call · 2026-05-15')).toBeInTheDocument();
  expect(screen.getByText(mockTradeCard.contract)).toBeInTheDocument();
});

it('presentation can hand market context to the page without mounting a second card', () => {
  const { rerender } = render(<TradeCard data={mockTradeCard} showMarketSentiment={false} />);
  expect(screen.queryByText(/Market sentiment — insufficient history/)).not.toBeInTheDocument();
  rerender(<TradeCard data={mockTradeCard} />);
  expect(screen.getByText(/Market sentiment — insufficient history/)).toBeInTheDocument();
});

// ── TRADING-REVIEW-PHASE-C-RR (review M7, D5): full-premium R/R ─────────────
//
// No protective option order is ever placed, so the whole premium is at risk:
// every Sell-to-Close row divides by `overlay.entryLimit`, never by the premium
// stop (an alert level) or the captured stock-stop loss. Premium 2.00, estimate
// 3.50: 1.50 / 2.00 = 0.75 → 0.8x (on the old 1.20 premium-stop basis: 1.3x).
describe('Phase C RR: the ladder risks the full premium', () => {
  beforeEach(() => { localStorage.clear(); });

  const RR_CARD: TradeCardData = {
    ...mockTradeCard,
    contractDetails: { ...mockTradeCard.contractDetails!, mid: 2.0 },
    entry: { ...mockTradeCard.entry, limit: 2.0 },
    exit: {
      ...mockTradeCard.exit,
      premiumStop: 1.2,
      rrRiskBasis: 'full_premium',
      targets: [
        { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 3.5, contractsToSell: 1, status: 'PENDING', rrContribution: 0.75 },
      ],
    },
  };
  const CAPTION = 'R/R risk: full premium (no protective stop order).';

  it('(i) an un-edited row with no stock-stop loss divides by the full premium', () => {
    render(<TradeCard data={RR_CARD} />);
    expandLadder();
    expect(screen.getByText('0.8x')).toBeInTheDocument();
    expect(screen.queryByText('1.3x')).not.toBeInTheDocument();
    expect(screen.getByText(CAPTION)).toBeInTheDocument();
  });

  it('serves the backend ratio on an un-edited full-premium row', () => {
    // 0.74 would be 0.7x; the recomputation would print 0.8x.
    const card = { ...RR_CARD, exit: { ...RR_CARD.exit, targets: [{ ...RR_CARD.exit.targets[0], rrContribution: 0.74 }] } };
    render(<TradeCard data={card} />);
    expandLadder();
    expect(screen.getByText('0.7x')).toBeInTheDocument();
  });

  it('(ii) an edited target row divides by the full premium', async () => {
    render(<TradeCard data={RR_CARD} />);
    expandLadder();
    await act(async () => { fireEvent.click(screen.getByLabelText('Edit target stock price for TP1')); });
    const input = screen.getByDisplayValue('200.02');
    await act(async () => {
      fireEvent.change(input, { target: { value: '200.00' } });
      fireEvent.keyDown(input, { key: 'Enter' });
    });
    // Above the 190 strike: delta 0.5 x (200 - 185.2) = 7.40 over entry.
    // 7.40 / 2.00 = 3.7x (on the 1.20 premium stop: 6.2x).
    expect(screen.getByText('3.7x')).toBeInTheDocument();
    expect(screen.queryByText('6.2x')).not.toBeInTheDocument();
  });

  it('(iii) a captured stock risk does not set the risk leg once the entry limit is edited', () => {
    const card = { ...RR_CARD, exit: { ...RR_CARD.exit, stockStopLoss: 0.5, stockStopLossAt: 179.64 } };
    render(<TradeCard data={card} initialEntryLimit={2.5} />);
    expandLadder();
    // (3.50 - 2.50) / 2.50 = 0.4x (on the 0.50 stock-stop loss: 2.0x).
    expect(screen.getByText('0.4x')).toBeInTheDocument();
    expect(screen.queryByText('2.0x')).not.toBeInTheDocument();
  });

  it('(iv) a moved stock stop (rrStale) changes nothing about the ladder R/R', () => {
    const card = { ...RR_CARD, exit: { ...RR_CARD.exit, stockStopLoss: 0.5, stockStopLossAt: 179.64, invalidation: 179.65 } };
    const report = jest.fn();
    render(<TradeCard data={card} onRrStaleChange={report} />);
    expandLadder();
    expect(report).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('0.8x')).toBeInTheDocument();
    expect(screen.queryByText('1.3x')).not.toBeInTheDocument();
    expect(screen.queryByText(/R\/R uses the premium stop/)).not.toBeInTheDocument();
    expect(screen.getByText(CAPTION)).toBeInTheDocument();
  });

  it('(v) a saved pre-RR candidate is recomputed on the full premium, never shown at its old ratio', () => {
    const card = { ...RR_CARD, exit: { ...RR_CARD.exit, rrRiskBasis: 'premium_stop' as const,
      targets: [{ ...RR_CARD.exit.targets[0], rrContribution: 1.25 }] } };
    render(<TradeCard data={card} />);
    expandLadder();
    // The figure on screen is the full-premium recomputation, so the caption
    // naming the full premium describes the number it sits above.
    expect(screen.getByText('0.8x')).toBeInTheDocument();
    expect(screen.queryByText('1.3x')).not.toBeInTheDocument();
    expect(screen.getByText(CAPTION)).toBeInTheDocument();
  });
});
