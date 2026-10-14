import '@testing-library/jest-dom';
import * as React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 3 — the card's half of the control (spec §6.1,
// §6.2). Spec test 13 ("a pick on a stale estimate is cleared") is the
// `clears a monte_carlo pick` case below. The control's own rules are in
// components/molecules/MethodPickSelector/__tests__.

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
  InlineChartPanel: () => <div data-testid="inline-chart" />,
}));
jest.mock('@/components/molecules/SymbolHeader', () => ({
  SymbolHeader: ({ ticker }: { ticker: string }) => <div>{ticker}</div>,
}));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({
  ScoreCardPanel: ({ title }: { title: string }) => <div>{title}</div>,
}));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({
  LabeledStatusBadge: ({ label }: { label: string }) => <div>{label}</div>,
}));

const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 5.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
    ],
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
};

const pick = (over: Partial<MethodPick> = {}): MethodPick => ({
  method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null,
  stopBasis: 'stock', pickedAt: '2026-09-14T09:00:00.000Z', ...over,
});

const radio = (name: string) => screen.getByRole('radio', { name });

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  // The Estimate handler runs a structural-stop fetch first (it races the
  // estimate against the stop that is actually on screen), so an unmocked
  // getStructuralStop leaves `firstPassage` null and every Monte Carlo /
  // Barrier Race case below silently never arrives.
  (api.getStructuralStop as jest.Mock).mockResolvedValue({
    available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
  });
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 185.2 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 2.5 });
});

describe('TradeCard — the method-pick control (§6.1)', () => {
  it('offers all four methods, with the three that need a run disabled and reasoned', () => {
    render(<TradeCard data={card} />);
    // Ladder needs no run — it is the card's own live T1/T2/T3.
    expect(radio('Ladder')).toBeEnabled();
    expect(radio('Arithmetic')).toBeDisabled();
    expect(radio('Monte Carlo')).toBeDisabled();
    expect(radio('Barrier Race')).toBeDisabled();
    expect(screen.getByText('Compute Arithmetic Plan first')).toBeInTheDocument();
    expect(screen.getAllByText('Run Monte Carlo Estimate first')).toHaveLength(2);
  });

  it('seeds from initialMethodPick and round-trips a click back to the parent', () => {
    const onMethodPickChange = jest.fn();
    render(
      <TradeCard data={card} initialMethodPick={pick()} onMethodPickChange={onMethodPickChange} />,
    );
    expect(radio('Ladder')).toHaveAttribute('aria-checked', 'true');
    // The stored row is recovered by price pair, so the ladder's TP1 lights up.
    expect(radio('TP1')).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(radio('Premium stop'));
    expect(onMethodPickChange).toHaveBeenCalledWith(expect.objectContaining({
      method: 'ladder', stopBasis: 'premium', rowStockPrice: 200.02,
    }));
  });

  it('a ladder pick is NOT cleared on mount — the ladder needs no run', () => {
    const onMethodPickChange = jest.fn();
    render(
      <TradeCard data={card} initialMethodPick={pick()} onMethodPickChange={onMethodPickChange} />,
    );
    // The mirror of test 13 below. Without it, "clears on mount" would pass
    // just as well for a card that clears EVERY pick on every mount.
    expect(onMethodPickChange).not.toHaveBeenCalled();
  });

  it('TEST 13 — clears a monte_carlo pick whose estimate is not fresh this mount', async () => {
    // `estimateIsFresh` is `raceBarriers?.contract === data.contract`, which is
    // false on every mount until Estimate is clicked. So a restored estimate
    // reinstates no rows — the Final Recommendation prints "Not re-run this
    // session" instead — and a pick naming one of those rows is a judgement
    // about numbers that are not on screen.
    const withEstimate: TradeCardData = {
      ...card,
      exit: {
        ...card.exit,
        firstPassage: {
          targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
          invalidation: { probability: 0.3, expectedDays: 5 },
          computedAt: '2026-09-13T00:00:00.000Z',
        },
      },
    };
    const onMethodPickChange = jest.fn();
    render(
      <TradeCard
        data={withEstimate}
        initialMethodPick={pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 })}
        onMethodPickChange={onMethodPickChange}
      />,
    );
    await waitFor(() => expect(onMethodPickChange).toHaveBeenCalledWith(null));
    expect(radio('Monte Carlo')).toHaveAttribute('aria-checked', 'false');
  });

  it('clears an arithmetic pick once its plan is gone', async () => {
    const onMethodPickChange = jest.fn();
    render(
      <TradeCard
        data={card}
        initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 210.5 })}
        onMethodPickChange={onMethodPickChange}
      />,
    );
    await waitFor(() => expect(onMethodPickChange).toHaveBeenCalledWith(null));
  });

  it('does NOT clear the incoming contract’s pick during a candidate switch', async () => {
    // THE SETTLING GUARD. On the commit that switches contract, `data` and
    // `initialMethodPick` are already the new candidate's while `exitPlan`
    // state still holds the OLD one's — here, nothing. An unguarded clear
    // effect measures the new pick against the old candidate's absent plan and
    // wipes a pick the user made seconds ago.
    (api.getExitPlan as jest.Mock).mockResolvedValue({
      stop: { price: 178, source: 'atr_widened' as const, contractPrice: 1.2, rrModel: 'Heston repriced' as const,
                 structuralSource: null, structuralConfidence: null, structuralPrice: null,
                 atrFloorPrice: 178, distanceDollar: null },
      targets: [{ rrRatio: 2, arithmeticPrice: 210.5, price: 210.5, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
      atr: 4,
    });
    const other: TradeCardData = { ...card, contract: 'AAPL 195C 05/15' };
    const onMethodPickChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={card} initialMethodPick={null} onMethodPickChange={onMethodPickChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /compute arithmetic plan/i }));
    await waitFor(() => expect(radio('Arithmetic')).toBeEnabled());

    // Switch to a candidate that ALSO has a stored arithmetic pick. `data.exit`
    // carries the plan for the incoming contract, so the reset effect splices
    // it straight in — but not until after this commit.
    const incoming: TradeCardData = {
      ...other,
      exit: {
        ...other.exit,
        exitPlan: {
          stop: { price: 178, source: 'atr_widened' as const, contractPrice: 1.2, rrModel: 'Heston repriced' as const,
                 structuralSource: null, structuralConfidence: null, structuralPrice: null,
                 atrFloorPrice: 178, distanceDollar: null },
          targets: [{ rrRatio: 2, arithmeticPrice: 211, price: 211, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
          atr: 4,
          computedAt: '2026-09-14T08:00:00.000Z',
        },
      },
    };
    onMethodPickChange.mockClear();
    rerender(
      <TradeCard
        data={incoming}
        initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 211 })}
        onMethodPickChange={onMethodPickChange}
      />,
    );
    await waitFor(() => expect(radio('Arithmetic')).toHaveAttribute('aria-checked', 'true'));
    expect(onMethodPickChange).not.toHaveBeenCalledWith(null);
  });

  it('an OUTGOING monte_carlo pick does not wipe the INCOMING candidate’s own pick', async () => {
    // Round-1 audit finding (2026-09-14), CONFIRMED BY REPRODUCTION. Unlike the
    // test above, the OUTGOING candidate here genuinely has a local
    // `methodPick` of `monte_carlo` — set by actually clicking the radio, not
    // left null. On the commit that switches contract, `pickEstimateIsFresh`
    // (`raceBarriers.contract === prevContractRef.current`) would read false
    // if it compared against the `data.contract` PROP instead of the ref:
    // `data.contract` is already new on that render while `raceBarriers`
    // state is still the outgoing candidate's, which would make the stale
    // `monte_carlo` pick look gone in that one transitional render, and the
    // clearing effect's `onMethodPickChange(null)` would fire bound to the
    // INCOMING candidate, deleting that candidate's own unrelated, valid
    // ladder pick from the persisted store. Comparing against
    // `prevContractRef.current` (state, updated in lockstep with
    // `raceBarriers` by the same reset effect) instead keeps both sides of
    // that comparison mutually consistent on the transitional render, so
    // nothing looks spuriously gone.
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({
      targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
      invalidation: { probability: 0.3, expectedDays: 5 },
      race: null,
    });
    const onMethodPickChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={card} initialMethodPick={null} onMethodPickChange={onMethodPickChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => expect(radio('Monte Carlo')).toBeEnabled());
    fireEvent.click(radio('Monte Carlo'));
    fireEvent.click(screen.getByRole('radio', { name: 'T20%' }));
    await waitFor(() => expect(radio('Monte Carlo')).toHaveAttribute('aria-checked', 'true'));

    const incoming: TradeCardData = {
      ...card,
      contract: 'AAPL 195C 05/15',
      exit: { ...card.exit, targets: [
        { id: 'tp1', stockPrice: 211, targetPrice: 211, estimatedOptionPrice: 5.4, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
      ] },
    };
    onMethodPickChange.mockClear();
    rerender(
      <TradeCard
        data={incoming}
        initialMethodPick={pick({ method: 'ladder', rowStockPrice: 211 })}
        onMethodPickChange={onMethodPickChange}
      />,
    );
    await waitFor(() => expect(radio('Ladder')).toHaveAttribute('aria-checked', 'true'));
    expect(onMethodPickChange).not.toHaveBeenCalledWith(null);
  });

  it('DOES clear the INCOMING candidate’s own restored monte_carlo pick on a switch', async () => {
    // Round-2 audit finding (2026-09-14) against the round-1 fix's first
    // attempt (a hand-off ref between the reset effect and the clearing
    // effect): that ref was set unconditionally on every reset, but the
    // clearing effect only runs on `useEffect([pickedMethodGone])` actually
    // CHANGING value between commits. When the outgoing candidate's own pick
    // was already null (`pickedMethodGone` already false, as in THIS
    // scenario), the clearing effect never fired on the transitional render,
    // so the ref was never consumed — left stuck `true`, ready to wrongly
    // swallow a LATER, unrelated, genuinely-real clear. The fix that replaced
    // it (comparing `pickEstimateIsFresh` against `prevContractRef.current`
    // instead of the `data.contract` prop) carries no such memory between
    // renders, so this case — an outgoing pick of null, switching to a
    // candidate whose OWN restored pick is `monte_carlo` and must still be
    // cleared per §6.1 (a restored estimate is never "fresh this mount") —
    // must keep working correctly on its own, not merely by accident of the
    // previous test's outgoing-pick shape.
    const onMethodPickChange = jest.fn();
    const { rerender } = render(
      <TradeCard data={card} initialMethodPick={null} onMethodPickChange={onMethodPickChange} />,
    );

    const incoming: TradeCardData = {
      ...card,
      contract: 'AAPL 195C 05/15',
      exit: {
        ...card.exit,
        firstPassage: {
          targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
          invalidation: { probability: 0.3, expectedDays: 5 },
          computedAt: '2026-09-13T00:00:00.000Z',
        },
      },
    };
    onMethodPickChange.mockClear();
    rerender(
      <TradeCard
        data={incoming}
        initialMethodPick={pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 })}
        onMethodPickChange={onMethodPickChange}
      />,
    );
    await waitFor(() => expect(onMethodPickChange).toHaveBeenCalledWith(null));
    expect(radio('Monte Carlo')).toHaveAttribute('aria-checked', 'false');
  });

  it('a Monte Carlo row records the UNDERLYING as rowStockPrice while rendering the PREMIUM', async () => {
    // §6.1's trap, end to end through the card. The row the trader clicks reads
    // $6.24 — the premium — and the field that may seed `resolved_tp_price` is
    // the $197.50 underlying beside it. One shared field would make
    // `price >= 6.24` true on the first tick.
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({
      targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
      invalidation: { probability: 0.3, expectedDays: 5 },
      race: null,
    });
    const onMethodPickChange = jest.fn();
    render(<TradeCard data={card} onMethodPickChange={onMethodPickChange} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => expect(radio('Monte Carlo')).toBeEnabled());
    fireEvent.click(radio('Monte Carlo'));
    fireEvent.click(screen.getByRole('radio', { name: 'T20%' }));
    expect(onMethodPickChange).toHaveBeenLastCalledWith(expect.objectContaining({
      method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
    }));
  });

  it('a Barrier Race row records a NULL stock price, never the option price', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({
      targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
      invalidation: { probability: 0.3, expectedDays: 5 },
      race: {
        premiumStopPrice: 1.5, stockStopPrice: 179.64, nPaths: 2000,
        outcomes: [{
          targetPct: 0.2, targetOptionPrice: 6.24,
          pTargetFirst: 0.4, pStockStopFirst: 0.3, pPremiumStopFirst: 0.2, pNeither: 0.1,
          daysTarget: 9, daysStockStop: 12, daysPremiumStop: 8,
          edgePerContract: 120, rrStockStop: 1.8,
        }],
      },
    });
    const onMethodPickChange = jest.fn();
    render(<TradeCard data={card} onMethodPickChange={onMethodPickChange} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => expect(radio('Barrier Race')).toBeEnabled());
    fireEvent.click(radio('Barrier Race'));
    fireEvent.click(screen.getByRole('radio', { name: 'T20%' }));
    // `BarrierRaceOutcome` carries no stock level at all — which is exactly why
    // §4.3 maps every race pick to ('ladder', NULL).
    expect(onMethodPickChange).toHaveBeenLastCalledWith(expect.objectContaining({
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 6.24,
    }));
  });

  it('race shortcut selects the authoritative row, preserves premium basis and clears on contract switch', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({
      targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
      invalidation: { probability: 0.3, expectedDays: 5 },
      race: {
        premiumStopPrice: 1.5, stockStopPrice: 179.64, nPaths: 2000,
        outcomes: [{
          targetPct: 0.2, targetOptionPrice: 6.24,
          pTargetFirst: 0.4, pStockStopFirst: 0.3, pPremiumStopFirst: 0.2, pNeither: 0.1,
          daysTarget: 9, daysStockStop: 12, daysPremiumStop: 8,
          edgePerContract: 120, rrStockStop: 1.8,
        }],
      },
    });
    const onMethodPickChange = jest.fn();
    const { rerender } = render(<TradeCard data={card} initialMethodPick={pick({ stopBasis: 'premium' })} onMethodPickChange={onMethodPickChange} />);
    expect(screen.queryByRole('button', { name: 'Use Barrier Race T20%' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    const shortcut = await screen.findByRole('button', { name: 'Use Barrier Race T20%' });
    fireEvent.click(shortcut);
    expect(onMethodPickChange).toHaveBeenLastCalledWith(expect.objectContaining({
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 6.24, stopBasis: 'premium',
    }));
    expect(radio('Barrier Race')).toHaveAttribute('aria-checked', 'true');
    expect(radio('T20%')).toHaveAttribute('aria-checked', 'true');
    expect(shortcut).toHaveAttribute('aria-pressed', 'true');
    expect(Number.isFinite(Date.parse(onMethodPickChange.mock.calls.at(-1)[0].pickedAt))).toBe(true);
    rerender(<TradeCard data={{ ...card, contract: 'AAPL 195C 05/15' }} onMethodPickChange={onMethodPickChange} />);
    expect(screen.queryByRole('button', { name: 'Use Barrier Race T20%' })).not.toBeInTheDocument();
  });

  it('renders one controlled selector in the execution anchor and retains its decision when the anchor settles', () => {
    const anchor = document.createElement('div');
    document.body.appendChild(anchor);
    const onMethodPickChange = jest.fn();
    const { container, rerender, unmount } = render(<TradeCard data={card} decisionTarget={anchor} onMethodPickChange={onMethodPickChange} />);
    expect(within(container).queryByRole('radio', { name: 'Ladder' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('radio', { name: 'Ladder' })).toHaveLength(1);
    fireEvent.click(within(anchor).getByRole('radio', { name: 'Ladder' }));
    fireEvent.click(within(anchor).getByRole('radio', { name: 'TP1' }));
    fireEvent.click(within(anchor).getByRole('radio', { name: 'Premium stop' }));
    expect(onMethodPickChange).toHaveBeenLastCalledWith(expect.objectContaining({ method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null, stopBasis: 'premium' }));
    rerender(<TradeCard data={card} decisionTarget={null} onMethodPickChange={onMethodPickChange} />);
    expect(screen.queryByRole('radio', { name: 'Ladder' })).not.toBeInTheDocument();
    rerender(<TradeCard data={card} decisionTarget={anchor} onMethodPickChange={onMethodPickChange} />);
    expect(within(anchor).getByRole('radio', { name: 'TP1' })).toHaveAttribute('aria-checked', 'true');
    expect(within(anchor).getByRole('radio', { name: 'Premium stop' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getAllByRole('radio', { name: 'Ladder' })).toHaveLength(1);
    unmount();
    expect(anchor).toBeEmptyDOMElement();
    anchor.remove();
  });

  it('shows the selected ladder without claiming a default fallback', () => {
    // G adds a pick ON TOP OF the fallback; it does not delete it. The fallback
    // is what a trader sees before they have picked, and it must keep working.
    render(<TradeCard data={card} initialMethodPick={pick()} />);
    expect(screen.getByText('Selected method: Fixed % Ladder Plan')).toBeInTheDocument();
  });
});


// Scope assertions to the recommendation so calculator cards cannot mask
// unrelated/stale targets in the selected-method summary.
const recommendation = () => within(screen.getByRole('region', { name: 'Final Recommendation' }).lastElementChild as HTMLElement);
const arithmeticPlan: NonNullable<TradeCardData['exit']['exitPlan']> = {
  stop: { price: 178, source: 'atr_widened', contractPrice: 1.2, rrModel: 'Heston repriced',
    structuralSource: null, structuralConfidence: null, structuralPrice: null,
    atrFloorPrice: 178, distanceDollar: null },
  targets: [{ rrRatio: 2, arithmeticPrice: 210.5, price: 210.5, tpSource: 'arithmetic',
    structuralPrice: null, contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4,
    expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
  atr: 4, computedAt: '2026-01-01T00:00:00.000Z',
};
const estimate = {
  targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
  invalidation: { probability: 0.3, expectedDays: 5 },
  race: {
    premiumStopPrice: 1.5, stockStopPrice: 179.64, nPaths: 2000,
    premiumStopPct: 0.4, premiumUsed: 2.5, ivSolved: true,
    outcomes: [{ targetPct: 0.2, targetOptionPrice: 7.25, pTargetFirst: 0.25,
      pStockStopFirst: 0.3, pPremiumStopFirst: 0.2, pNeither: 0.25,
      daysTarget: 9, daysStockStop: 12, daysPremiumStop: 8,
      daysAnyPathReachedStop: 5, weightTargetFirst: 0.25, weightStockStopFirst: 0.3,
      weightPremiumStopFirst: 0.2, weightNeither: 0.25, terminalMean: 2.5,
      rewardDollar: 4.75, repriceDaysStockStop: 5, stopRepricedValue: 1.2,
      riskStockStop: 1.3, riskPremiumStop: 1, rrPremiumStop: 0.5,
      edgePerContract: 120, rrStockStop: 1.8 }],
  },
};
const runEstimate = async (race = true) => {
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({ ...estimate, race: race ? estimate.race : null });
  fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
  await waitFor(() => expect(radio('Monte Carlo')).toBeEnabled());
};

describe('TC-UI-02 selected recommendation', () => {
  it('race dollar outcome follows edited entered quantity without another simulation or changing per-contract edge', async () => {
    render(<TradeCard data={card} contracts={2} />);
    await runEstimate();
    const race = within(screen.getByText('Which barrier is reached first').closest('section')!);
    expect(race.getByText('$950.00')).toBeVisible();
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const input = screen.getByLabelText('Edit Contracts');
    fireEvent.change(input, { target: { value: '3' } });
    fireEvent.blur(input);
    expect(race.getByText('$1425.00')).toBeVisible();
    expect(race.getByText('$120.00')).toBeVisible();
    expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(1);
  });

  it('places the selector after method evidence and preserves initial ladder defaults with no pick', () => {
    render(<TradeCard data={card} />);
    const heading = screen.getByText('Final Recommendation');
    expect(within(heading.parentElement!).getByRole('radio', { name: 'Ladder' })).toBeVisible();
    expect(screen.getByRole('button', { name: /Fixed % Ladder Plan/ }).compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Arithmetic Profit Target' }).compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(recommendation().getByText(/No method explicitly run/)).toBeVisible();
    expect(recommendation().getByText('$200.02')).toBeVisible();
  });

  it.each(['arithmetic', 'monte_carlo'] as const)('selected ladder overrides latest %s without computing or editing', (latest) => {
    const data = { ...card, exit: { ...card.exit,
      ...(latest === 'arithmetic' ? { exitPlan: arithmeticPlan } : {
        firstPassage: { ...estimate, computedAt: '2026-02-01T00:00:00.000Z' },
      }),
    } };
    const onEditsChange = jest.fn();
    const onMethodPickChange = jest.fn();
    render(<TradeCard data={data} onEditsChange={onEditsChange} onMethodPickChange={onMethodPickChange} />);
    fireEvent.click(radio('Ladder'));
    expect(recommendation().getByText('$200.02')).toBeVisible();
    expect(recommendation().queryByText(/computed via:/)).not.toBeInTheDocument();
    expect(onMethodPickChange).toHaveBeenCalledWith(expect.objectContaining({ method: 'ladder' }));
    expect(api.getExitPlan).not.toHaveBeenCalled();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    expect(onEditsChange).not.toHaveBeenCalled();
  });

  it('selected arithmetic overrides latest fresh MC; choosing does not compute or edit', async () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} onEditsChange={onEditsChange} />);
    await runEstimate();
    expect(recommendation().getByText(/computed via: Monte Carlo/)).toBeVisible();
    onEditsChange.mockClear();
    fireEvent.click(radio('Arithmetic'));
    expect(recommendation().getByText(/computed via: Arithmetic/)).toBeVisible();
    expect(recommendation().getByText('$210.50 (40%)')).toBeVisible();
    expect(recommendation().queryByText(/Armed stop/)).not.toBeInTheDocument();
    expect(recommendation().queryByText(/T20%/)).not.toBeInTheDocument();
    expect(api.getExitPlan).not.toHaveBeenCalled();
    expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(1);
    expect(onEditsChange).not.toHaveBeenCalled();
  });

  it.each([true, false])('selected MC shows independent targets only (race present: %s)', async (race) => {
    render(<TradeCard data={card} />);
    await runEstimate(race);
    fireEvent.click(radio('Monte Carlo'));
    expect(recommendation().getByText('$6.24 (40%)')).toBeVisible();
    expect(recommendation().queryByText(/Armed stop|edge|target first/)).not.toBeInTheDocument();
    expect(recommendation().queryByText(/7.25/)).not.toBeInTheDocument();
  });

  it('selected race shows its own premiums, exclusive probability, armed stop and edge only', async () => {
    render(<TradeCard data={card} />);
    await runEstimate();
    fireEvent.click(radio('Barrier Race'));
    expect(recommendation().getByText(/computed via: Barrier Race/)).toBeVisible();
    expect(recommendation().getByText(/\$7.25 option \(25% target first\)/)).toBeVisible();
    expect(recommendation().getByText(/\$1.50 option \/ \$179.64 stock/)).toBeVisible();
    expect(recommendation().queryByText(/6.24|40%|computed via: Monte Carlo/)).not.toBeInTheDocument();
  });

  it('selected race labels target-first with the allocated weight, not the re-rounded raw share', async () => {
    // Raw 0.35% rounds to 0%, but the backend's largest-remainder allocation
    // gives target-first 1% — the weight edgePerContract and BarrierRaceCard use.
    const [outcome] = estimate.race.outcomes;
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({ ...estimate, race: { ...estimate.race,
      outcomes: [{ ...outcome, pTargetFirst: 0.0035, pStockStopFirst: 0, pPremiumStopFirst: 0.0935,
        pNeither: 0.903, weightTargetFirst: 0.01, weightStockStopFirst: 0,
        weightPremiumStopFirst: 0.09, weightNeither: 0.9 }],
    } });
    render(<TradeCard data={card} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => expect(radio('Barrier Race')).toBeEnabled());
    fireEvent.click(radio('Barrier Race'));
    expect(recommendation().getByText(/\$7.25 option \(1% target first\)/)).toBeVisible();
    expect(recommendation().queryByText(/0% target first/)).not.toBeInTheDocument();
  });

  it.each(['arithmetic', 'monte_carlo', 'barrier_race'] as const)('missing selected %s clears persistence and retains a prompt instead of unrelated defaults', async (method) => {
    const onMethodPickChange = jest.fn();
    const data = method === 'arithmetic' ? card : { ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } };
    render(<TradeCard data={data} initialMethodPick={pick({ method })} onMethodPickChange={onMethodPickChange} />);
    await waitFor(() => expect(onMethodPickChange).toHaveBeenCalledWith(null));
    expect(recommendation().getByText(/Selected method results unavailable/)).toBeVisible();
    expect(recommendation().queryByText(/computed via:|No method explicitly run/)).not.toBeInTheDocument();
    fireEvent.click(radio('Ladder'));
    expect(recommendation().getByText('$200.02')).toBeVisible();
  });

  it.each(['monte_carlo', 'barrier_race'] as const)('cached stale %s pick shows a prompt even after rerun until deliberate selection', async (method) => {
    const data = { ...card, exit: { ...card.exit, exitPlan: arithmeticPlan,
      firstPassage: { ...estimate, computedAt: '2026-02-01T00:00:00.000Z' } } };
    render(<TradeCard data={data} initialMethodPick={pick({ method })} />);
    expect(recommendation().getByText(/Selected method results unavailable/)).toBeVisible();
    await runEstimate();
    expect(recommendation().getByText(/Selected method results unavailable/)).toBeVisible();
    expect(recommendation().queryByText(/computed via:/)).not.toBeInTheDocument();
    fireEvent.click(radio(method === 'monte_carlo' ? 'Monte Carlo' : 'Barrier Race'));
    expect(recommendation().queryByText(/Selected method results unavailable/)).not.toBeInTheDocument();
  });

  it.each([
    ['monte_carlo', 'Premium stop', '0.90'],
    ['barrier_race', 'Premium stop', '0.90'],
    ['monte_carlo', 'Stock stop', '170'],
    ['barrier_race', 'Stock stop', '170'],
  ] as const)('moving %s’s %s preserves MC targets but invalidates a selected race', async (method, field, value) => {
    const onMethodPickChange = jest.fn();
    render(<TradeCard data={card} onMethodPickChange={onMethodPickChange} />);
    await runEstimate();
    fireEvent.click(radio(method === 'monte_carlo' ? 'Monte Carlo' : 'Barrier Race'));
    fireEvent.click(radio('Premium stop'));
    onMethodPickChange.mockClear();
    if (field === 'Stock stop') {
      // The race used the structural stop, so move that actual barrier.
      // Editing the separate invalidation field must not replace its basis.
      (api.getStructuralStop as jest.Mock).mockResolvedValueOnce({
        available: true, price: Number(value), source: 'swing_low', confidence: 60, distancePct: 8.6,
      });
      fireEvent.click(screen.getByRole('button', { name: /check structure/i }));
      await waitFor(() => expect(screen.getByText(/Barriers changed/)).toBeVisible());
    } else {
      fireEvent.click(screen.getByLabelText(`Edit ${field}`));
      const input = screen.getByLabelText(`Edit ${field}`);
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);
    }
    if (method === 'barrier_race') {
      await waitFor(() => expect(onMethodPickChange).toHaveBeenCalledWith(null));
      expect(recommendation().getByText(/Selected method results unavailable/)).toBeVisible();
      expect(recommendation().queryByText(/7.25|Armed stop|6.24/)).not.toBeInTheDocument();
    } else {
      expect(onMethodPickChange).not.toHaveBeenCalledWith(null);
      expect(recommendation().getByText('$6.24 (40%)')).toBeVisible();
      expect(radio('Premium stop')).toHaveAttribute('aria-checked', 'true');
    }
    expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(1);
  });

  it('no selection preserves the latest arithmetic then MC with accompanying race fallback', async () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} />);
    expect(recommendation().getByText(/computed via: Arithmetic/)).toBeVisible();
    await runEstimate();
    expect(recommendation().getByText(/computed via: Monte Carlo/)).toBeVisible();
    expect(recommendation().getByText('$6.24 (40%)')).toBeVisible();
    expect(recommendation().getByText('Armed stop (whichever fires first)')).toBeVisible();
  });

  it('candidate and scan resets discard invalidation memory and restore that card’s no-pick fallback', () => {
    const { rerender } = render(<TradeCard data={card} initialMethodPick={pick({ method: 'arithmetic' })} />);
    expect(recommendation().getByText(/Selected method results unavailable/)).toBeVisible();
    rerender(<TradeCard data={card} resetKey={1} />);
    expect(recommendation().getByText(/No method explicitly run/)).toBeVisible();
    rerender(<TradeCard data={{ ...card, contract: 'AAPL 195C 05/15', exit: { ...card.exit, exitPlan: arithmeticPlan } }} />);
    expect(recommendation().getByText(/computed via: Arithmetic/)).toBeVisible();
  });
});


const chosenSummary = () => within(screen.getByRole('region', { name: 'Chosen method and target' }));
const summaryValue = (label: string) => chosenSummary().getByText(label).parentElement!;

describe('OPT-PRES-08 explicit decision summary', () => {
  it('method-only, row, basis, method change and Clear record choices without changing execution fields', () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={card} contracts={3} onEditsChange={onEditsChange} />);
    expect(chosenSummary().getByText(/latest-calculation fallback is not a choice/)).toBeVisible();
    fireEvent.click(radio('Ladder'));
    expect(chosenSummary().getByText('Target not selected')).toBeVisible();
    expect(chosenSummary().queryByText('Matched result option premium')).not.toBeInTheDocument();
    fireEvent.click(radio('TP1'));
    expect(within(summaryValue('Recorded stock target')).getByText('$200.02 stock')).toBeVisible();
    expect(within(summaryValue('Matched result option premium')).getByText('$5.00 /share')).toBeVisible();
    // Card-level Heston is not evidence for this ladder snapshot.
    expect(chosenSummary().getByText('Unavailable — no result model evidence')).toBeVisible();
    expect(chosenSummary().getByText(/3 entered contracts.*ladder rung allocation 1 contracts/)).toBeVisible();
    fireEvent.click(radio('Premium stop'));
    expect(within(summaryValue('Judged on basis')).getByText('Premium stop')).toBeVisible();
    expect(within(summaryValue('Execution stock stop')).getByText('$179.64 stock')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(chosenSummary().getByText(/latest-calculation fallback is not a choice/)).toBeVisible();
    expect(onEditsChange).not.toHaveBeenCalled();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    expect(api.getExitPlan).not.toHaveBeenCalled();
  });

  it('arithmetic uses returned R:R row premium, probability, calendar time and its own model', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} />);
    fireEvent.click(radio('Arithmetic'));
    expect(chosenSummary().getByText('Target not selected')).toBeVisible();
    fireEvent.click(radio('2:1'));
    expect(within(summaryValue('Recorded stock target')).getByText('$210.50 stock')).toBeVisible();
    expect(within(summaryValue('Matched result option premium')).getByText('$5.00 /share')).toBeVisible();
    expect(within(summaryValue('Result pricing model')).getByText('Heston repriced')).toBeVisible();
    expect(chosenSummary().getByText('~9 calendar days')).toBeVisible();
    expect(chosenSummary().getByText('40%')).toBeVisible();
    fireEvent.click(radio('Ladder'));
    expect(chosenSummary().getByText('Target not selected')).toBeVisible();
    expect(chosenSummary().queryByText('40%')).not.toBeInTheDocument();
  });

  it('MC and race summaries retain separate stock/premium spaces and distinct event probability', async () => {
    render(<TradeCard data={card} />);
    await runEstimate();
    fireEvent.click(radio('Monte Carlo'));
    fireEvent.click(radio('T20%'));
    expect(within(summaryValue('Recorded stock target')).getByText('$197.50 stock')).toBeVisible();
    expect(within(summaryValue('Recorded option target')).getByText('$6.24 /share')).toBeVisible();
    expect(chosenSummary().getByText('Independent target probability before expiry')).toBeVisible();
    expect(chosenSummary().getByText('40%')).toBeVisible();
    expect(chosenSummary().getByText('BS repriced (IV-derived)')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Use Barrier Race T20%' }));
    expect(chosenSummary().getByText('Not supplied by Barrier Race')).toBeVisible();
    expect(within(summaryValue('Recorded option target')).getByText('$7.25 /share')).toBeVisible();
    expect(chosenSummary().getByText('Allocated target-first probability')).toBeVisible();
    expect(chosenSummary().getByText('25%')).toBeVisible();
    expect(chosenSummary().queryByText('$197.50 stock')).not.toBeInTheDocument();
    expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(1);
  });

  it('changing arithmetic rows replaces all target evidence with the returned row', () => {
    const second = { ...arithmeticPlan.targets[0], rrRatio: 3, price: 225, contractPrice: 7,
      probability: 0.2, expectedDays: null, rrModel: 'Delta approximation' as const };
    render(<TradeCard data={{ ...card, exit: { ...card.exit,
      exitPlan: { ...arithmeticPlan, targets: [...arithmeticPlan.targets, second] } } }} />);
    fireEvent.click(radio('Arithmetic'));
    fireEvent.click(radio('2:1'));
    fireEvent.click(radio('3:1'));
    expect(chosenSummary().getByText('$225.00 stock')).toBeVisible();
    expect(chosenSummary().getByText('$7.00 /share')).toBeVisible();
    expect(chosenSummary().getByText('20%')).toBeVisible();
    expect(chosenSummary().getByText('Delta approximation')).toBeVisible();
    expect(chosenSummary().queryByText('~9 calendar days')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('Heston repriced')).not.toBeInTheDocument();
  });

  it('selected race median preserves a fractional calendar day with the shared formatter', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue({ ...estimate,
      race: { ...estimate.race, outcomes: [{ ...estimate.race.outcomes[0], daysTarget: 2.5 }] } });
    render(<TradeCard data={card} />);
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    await waitFor(() => expect(radio('Barrier Race')).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Use Barrier Race T20%' }));
    expect(chosenSummary().getByText('~2.5d (calendar days)')).toBeVisible();
    expect(chosenSummary().queryByText('~3 calendar days')).not.toBeInTheDocument();
  });

  it('duplicate returned price pairs cannot supply one row’s probability or model to a stored decision', () => {
    const second = { ...arithmeticPlan.targets[0], rrRatio: 3, probability: 0.2,
      expectedDays: 15, rrModel: 'Delta approximation' as const };
    render(<TradeCard data={{ ...card, exit: { ...card.exit,
      exitPlan: { ...arithmeticPlan, targets: [...arithmeticPlan.targets, second] } } }}
      initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 210.5 })} />);
    expect(chosenSummary().getByText(/multiple result rows match; evidence unavailable/)).toBeVisible();
    expect(chosenSummary().getByText('$210.50 stock')).toBeVisible();
    expect(chosenSummary().queryByText('40%')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('20%')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('Heston repriced')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('Delta approximation')).not.toBeInTheDocument();
  });

  it('MC without result model evidence does not inherit the card Heston label', async () => {
    render(<TradeCard data={card} />);
    await runEstimate(false);
    fireEvent.click(radio('Monte Carlo'));
    fireEvent.click(radio('T20%'));
    expect(chosenSummary().getByText('Unavailable — no result model evidence')).toBeVisible();
    expect(chosenSummary().queryByText('Heston repriced')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('BS repriced (IV-derived)')).not.toBeInTheDocument();
  });

  it('an unmatched stored target retains recorded price without borrowing current result evidence', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }}
      initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 220 })} />);
    expect(chosenSummary().getByText('Recorded target — matching result unavailable')).toBeVisible();
    expect(chosenSummary().getByText('$220.00 stock')).toBeVisible();
    expect(chosenSummary().queryByText('40%')).not.toBeInTheDocument();
    expect(chosenSummary().queryByText('Heston repriced')).not.toBeInTheDocument();
    expect(chosenSummary().getByText('2026-09-14T09:00:00.000Z')).toBeVisible();
  });
});
