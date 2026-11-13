import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react';
import { SendToBrokerDialog } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { buildSubmissionDraft } from '@/lib/submissionDraft';
import type { ReviewedTrackingOrder, TrackingSubmitResult } from '@/lib/trackingReview';
import type { TradeCardData, MethodPick } from '@/types/domain';

/*
 * #582 (TC-REVIEW-07) — the basket dialog shows, for every row, the request
 * beside the SERVER-RESOLVED values before it can be confirmed; one-off
 * quantities re-review and re-total without touching the card's quantity;
 * a review-required answer shows the new values and needs another confirm.
 */

const pick = (): MethodPick => ({
  method: 'monte_carlo', rowStockPrice: 165, rowOptionPrice: 4.1, stopBasis: 'stock', pickedAt: '2026-11-08T09:00:00.000Z',
});

function card(symbol: string, mid = 2): TradeCardData {
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish', status: 'PASS',
    stockScore: 80, stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} 150C 05/15`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: mid, maxFill: mid + 0.1, orderType: 'Limit' },
    exit: {
      invalidation: 140, premiumStop: 1.2, timeStopDays: 10, target: 165,
      targets: [{ stockPrice: 160, targetPrice: 160, contractsToSell: 1 }] as never,
      exitPlan: {
        computedAt: '2026-08-27T00:00:00.000Z',
        stop: { price: 140, source: 'structural', contractPrice: 1.5, rrModel: 'BS repriced (IV-derived)', structuralSource: 'swing_low', structuralConfidence: 0.8, structuralPrice: 140, atrFloorPrice: 138, distanceDollar: 5 },
        targets: [], atr: 3,
      },
    },
    rrRatio: 2, rrModel: 'BS repriced (IV-derived)', finalStatus: 'PASS',
  };
}

const draftFor = (c: TradeCardData, contracts: number) => buildSubmissionDraft({
  card: c, contracts, livePrice: null, invalidation: c.exit.invalidation, invalidationIsUserSet: false,
  entryLimit: c.entry.limit, premiumStopDollar: null, structuralStop: null, exitPlan: null,
  maxLossOverride: null, pick: pick(),
}, { broker: null, globalPremiumStopPct: 0.6 });
const stamps = (symbol: string) => ({ entryDate: '2026-11-08', orderedAt: '2026-11-08T10:00:00', recId: `REC-${symbol}` });

/** The server's answer: live entry +0.30, stop re-anchored +1. */
function previewBody(body: Record<string, unknown>, fingerprint = `v1:${body.recId}:${body.qty}`, shift = 0) {
  const entry = Number(body.entryPrice) + 0.3 + shift;
  return {
    fingerprint,
    position: { ...body, id: '', createdAt: '', entryPrice: entry, stop: Number(body.stop) + 1, activeTpMethod: 'monte_carlo', resolvedTpPrice: 165 },
    entryFromLiveQuote: true, inheritedPremiumStopPct: 0.6,
    differences: [
      { field: 'entryPrice', requested: body.entryPrice, effective: entry, reason: 'live_quote' },
      { field: 'stop', requested: body.stop, effective: Number(body.stop) + 1, reason: 'reanchored' },
    ],
  };
}

const originalFetch = global.fetch;
let previewImpl: (body: Record<string, unknown>) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;
beforeEach(() => {
  act(() => {
    usePortfolioStore.setState({ positions: [] });
    useRiskStore.setState({
      limits: {
        maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25, maxConcurrentPositions: 10,
        maxDailyRecommendations: 5, portfolioValue: 100000,
        maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
      },
      dailyRecommendations: 0,
    });
  });
  previewImpl = async (body) => ({ ok: true, status: 200, json: async () => previewBody(body) });
  global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (!String(url).endsWith('/api/portfolio/preview')) throw new Error(`unexpected ${url}`);
    return previewImpl(JSON.parse(String(init!.body)));
  }) as unknown as typeof fetch;
});
afterEach(() => { global.fetch = originalFetch; });

const previewBodies = () => (global.fetch as jest.Mock).mock.calls.map(([, i]) => JSON.parse(String(i.body)));
const region = (symbol: string) => within(screen.getByRole('region', { name: `Server review ${symbol}` }));
const line = (symbol: string, field: string) => screen.getByRole('region', { name: `Server review ${symbol}` }).querySelector(`[data-field="${field}"]`) as HTMLElement;

function renderDialog(onSubmit: (o: ReviewedTrackingOrder[], r: boolean) => Promise<TrackingSubmitResult | void> | void = jest.fn(),
  contractsBySymbol: Record<string, number> = {}, cards = [card('AAA')]) {
  const picks = Object.fromEntries(cards.map((c) => [c.symbol, pick()]));
  return render(<SendToBrokerDialog cards={cards} contractsBySymbol={contractsBySymbol} overridesBySymbol={{}} invalidationBySymbol={{}}
    methodPickBySymbol={picks} trackingDraftFor={draftFor} stampsFor={stamps} globalPremiumStopPct={0.6}
    onClose={() => {}} onSubmit={onSubmit} />);
}

describe('#582 basket dialog — server review before confirmation', () => {
  it('shows requested against server-resolved values, labelled Portfolio tracking with no broker order', async () => {
    renderDialog();
    const submit = screen.getByRole('button', { name: 'Add 1 to Portfolio' });
    expect(submit).toBeDisabled();
    expect(region('AAA').getByText(/Resolving the tracked values/)).toBeInTheDocument();
    await waitFor(() => expect(region('AAA').getByText(/Portfolio tracking · no broker order/)).toBeInTheDocument());
    expect(submit).toBeEnabled();
    expect(line('AAA', 'entry')).toHaveTextContent('$2.00/share');
    expect(line('AAA', 'entry')).toHaveTextContent('$2.30/share · save-time live quote');
    expect(line('AAA', 'entry')).toHaveAttribute('data-adjusted', 'true');
    expect(line('AAA', 'stop')).toHaveTextContent('$140.00 · plan level');
    expect(line('AAA', 'stop')).toHaveTextContent('$141.00');
    expect(line('AAA', 'stop')).toHaveTextContent('Adjusted — re-anchored to the live underlying');
    expect(line('AAA', 'qty')).toHaveAttribute('data-adjusted', 'false');
    expect(line('AAA', 'targetAlert')).toHaveTextContent('Monte Carlo stock level · stock $165.00');
    expect(line('AAA', 'premiumStop')).toHaveTextContent('Inherits global 60.0%');
    expect(screen.getByText(/Pinning only selected these candidates; it froze nothing/)).toBeInTheDocument();
    // The review never calls anything but the side-effect-free preview.
    for (const [u] of (global.fetch as jest.Mock).mock.calls) expect(String(u)).toMatch(/\/api\/portfolio\/preview$/);
  });

  it('a one-off quantity re-reviews and re-totals without touching the card quantity', async () => {
    const shared = Object.freeze({ AAA: 1 });
    const onSubmit = jest.fn();
    renderDialog(onSubmit, shared as Record<string, number>);
    await waitFor(() => expect(screen.getByText(/Server-resolved \$230/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Contracts for AAA'), { target: { value: '3' } });
    expect(screen.getByRole('button', { name: 'Add 1 to Portfolio' })).toBeDisabled();
    await waitFor(() => expect(screen.getByText(/Server-resolved \$690/)).toBeInTheDocument());
    expect(previewBodies().at(-1)).toMatchObject({ qty: 3, recId: 'REC-AAA' });
    expect(line('AAA', 'qty')).toHaveTextContent('3');
    expect(shared).toEqual({ AAA: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Add 1 to Portfolio' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const [[order]] = onSubmit.mock.calls[0];
    expect(order.contracts).toBe(3);
    expect(order.request.contracts).toBe(3);
    expect(order.preview.fingerprint).toBe('v1:REC-AAA:3');
  });

  it('a late answer for an older quantity never replaces the current review', async () => {
    let releaseOld!: () => void;
    previewImpl = async (body) => {
      if (body.qty === 1) await new Promise<void>((r) => { releaseOld = r; });
      return { ok: true, status: 200, json: async () => previewBody(body) };
    };
    renderDialog();
    await waitFor(() => expect(previewBodies()).toHaveLength(1));
    fireEvent.change(screen.getByLabelText('Contracts for AAA'), { target: { value: '2' } });
    await waitFor(() => expect(screen.getByText(/Server-resolved \$460/)).toBeInTheDocument());
    await act(async () => { releaseOld(); await new Promise((r) => setTimeout(r, 10)); });
    expect(screen.getByText(/Server-resolved \$460/)).toBeInTheDocument();
    expect(line('AAA', 'qty')).toHaveTextContent('2');
  });

  it('review-required shows the new server values and needs another confirmation', async () => {
    const onSubmit = jest.fn()
      .mockImplementationOnce(async (orders: ReviewedTrackingOrder[]) => ({
        reviewRequired: { AAA: { ...orders[0]!.preview, fingerprint: 'v1:new', position: { ...orders[0]!.preview.position, entryPrice: 2.9 } } },
      }))
      .mockImplementationOnce(async () => ({ reviewRequired: {} }));
    renderDialog(onSubmit);
    const submit = screen.getByRole('button', { name: 'Add 1 to Portfolio' });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(region('AAA').getByText(/Changed since your review — nothing was saved/)).toBeInTheDocument());
    expect(region('AAA').getByText(/Changed since your review/)).toHaveTextContent('(Tracked entry price, Premium stop, Est. position value)');
    expect(line('AAA', 'entry')).toHaveTextContent('$2.90/share');
    expect(onSubmit).toHaveBeenCalledTimes(1);
    // The re-review is the trader's: a second click confirms the NEW values.
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
    expect(onSubmit.mock.calls[1][0][0].preview.fingerprint).toBe('v1:new');
    expect(onSubmit.mock.calls[1][0][0].request).toBe(onSubmit.mock.calls[0][0][0].request);
  });

  it('a failed review blocks confirmation and can be retried', async () => {
    let fail = true;
    previewImpl = async (body) => (fail
      ? { ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }) }
      : { ok: true, status: 200, json: async () => previewBody(body) });
    renderDialog();
    await waitFor(() => expect(region('AAA').getByText(/Server review failed: single_trade_exposure_too_high/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Add 1 to Portfolio' })).toBeDisabled();
    fail = false;
    fireEvent.click(region('AAA').getByRole('button', { name: 'Review again' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add 1 to Portfolio' })).toBeEnabled());
  });

  it('without the page\'s draft builder nothing can be confirmed', () => {
    render(<SendToBrokerDialog cards={[card('AAA')]} contractsBySymbol={{}} overridesBySymbol={{}} invalidationBySymbol={{}}
      methodPickBySymbol={{ AAA: pick() }} onClose={() => {}} onSubmit={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'Add 1 to Portfolio' })).toBeDisabled();
    expect(region('AAA').getByText(/Server review unavailable/)).toBeInTheDocument();
  });
});

/* #609 (TC-ALIGN-06) — each row's tracking review reads destination-first:
 * Portfolio tracking (no broker order), the contract with its full expiry,
 * quantity and tracked entry; the actual position settings with the ≤3 DTE
 * time-exit alert (alerts, not broker orders); the target-alert basis. The
 * review fingerprint and saved-row id sit in a closed disclosure; the
 * changed-since-review warning stays visible. */
describe('#609 basket row review — concise destination-first arrangement', () => {
  const detailsOf = (symbol: string) => screen.getByRole('region', { name: `Server review ${symbol}` }).querySelector('details[data-review-details]') as HTMLDetailsElement;

  it('groups destination and request, actual position settings and the target-alert basis, all visible', async () => {
    renderDialog();
    await waitFor(() => expect(region('AAA').getByText(/Portfolio tracking · no broker order/)).toBeInTheDocument());
    const dest = within(region('AAA').getByRole('group', { name: 'Destination and request' }));
    expect(dest.getByText(/Portfolio tracking · no broker order/)).toBeVisible();
    for (const f of ['contract', 'qty', 'entry', 'value']) expect(line('AAA', f).closest('[role="group"]')).toHaveAttribute('aria-label', 'Destination and request');
    expect(dest.getByText('Expiry')).toBeVisible();
    expect(dest.getByText('2026-05-15 · 24 DTE')).toBeVisible();

    const settings = within(region('AAA').getByRole('group', { name: 'Position settings' }));
    for (const f of ['stop', 'structuralStop', 'premiumStop']) expect(line('AAA', f).closest('[role="group"]')).toHaveAttribute('aria-label', 'Position settings');
    expect(settings.getByText('Time-exit alert')).toBeVisible();
    expect(settings.getByText(/≤3 days to expiry/)).toBeVisible();
    expect(settings.getByText(/No protective stop-loss or take-profit order is sent to a broker/)).toBeVisible();

    for (const f of ['targets', 'targetAlert']) expect(line('AAA', f).closest('[role="group"]')).toHaveAttribute('aria-label', 'Target alert basis');
    expect(line('AAA', 'targetAlert')).toBeVisible();
  });

  it('keeps the review fingerprint and saved-row id in a closed disclosure, still in the DOM', async () => {
    renderDialog();
    await waitFor(() => expect(region('AAA').getByText(/Portfolio tracking · no broker order/)).toBeInTheDocument());
    const d = detailsOf('AAA');
    expect(d).not.toBeNull();
    expect(d.open).toBe(false);
    expect(within(d).getByText('v1:REC-AAA:1')).not.toBeVisible();
    expect(within(d).getByText('REC-AAA')).not.toBeVisible();
  });

  it('the changed-since-review warning stays visible outside the disclosure', async () => {
    const onSubmit = jest.fn().mockImplementationOnce(async (orders: ReviewedTrackingOrder[]) => ({
      reviewRequired: { AAA: { ...orders[0]!.preview, fingerprint: 'v1:new', position: { ...orders[0]!.preview.position, entryPrice: 2.9 } } },
    }));
    renderDialog(onSubmit);
    const submit = screen.getByRole('button', { name: 'Add 1 to Portfolio' });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    const warning = await waitFor(() => region('AAA').getByText(/Changed since your review — nothing was saved/));
    expect(warning).toBeVisible();
    expect(detailsOf('AAA').contains(warning)).toBe(false);
  });
});
