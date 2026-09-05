import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';

/*
 * The card's edits have to REACH the order. Piece 4 threaded the Premium stop
 * through `handleEditsChange`; Invalidation and Entry limit were left behind,
 * and every send path read the card's ORIGINAL values instead:
 *
 *   - `stop: card.exit.invalidation` in both position builders, so editing
 *     Invalidation from 140 to 132 stored a position whose stop was still 140
 *     and STOP_REACHED fired 8 points early, at a level nothing on screen
 *     still showed. `stop` is an UNDERLYING price compared against the live
 *     stock price (alertEngine.ts), which is what makes this a wrong-trade
 *     defect rather than a cosmetic one.
 *   - `limit_price: card.entry.limit` on the quick Place Limit path and in
 *     AutoTradeArm, and the same value in the button's own label — so an
 *     edited limit was shown, promised, and then not sent.
 *
 * The edits were never wired; the schematic removals deleted `isDirty()`,
 * which was the last code reading them, and that is what made it invisible.
 *
 * Max fill and Time stop are deliberately NOT covered: nothing consumes
 * either one anywhere (TIME_STOP fires on a hardcoded `dteRemaining <= 3`),
 * so there is no send path for a test to pin. Threading those is a build.
 */

jest.mock('@/lib/api', () => ({
  api: {
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
    getContractQuote: jest.fn().mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-AUTO' }),
  },
}));

const CARD_INVALIDATION = 140;
const CARD_LIMIT = 2.5;
/* The SECOND candidate's values differ from the first's in every field the
 * three caches key on or carry. Round 7 flagged that AAA and BBB were
 * byte-identical apart from the symbol, which made the round-trip test blind
 * to the failure it most needs to catch: if `entryLimitByContract` or
 * `invalidationBySymbol` leaked AAA's edit onto BBB, every assertion still
 * passed, because AAA's edited 2.71/132 and BBB's inherited values were being
 * compared against the same numbers. Distinct strikes matter too -- a shared
 * strike means a shared contract key, so a leak could not be told apart from a
 * legitimate cache hit. */
const BBB_INVALIDATION = 120;
const BBB_LIMIT = 3.3;
const BBB_STRIKE = 155;

function makeCard(symbol: string): TradeCardData {
  const isSecond = symbol === 'BBB';
  const limit = isSecond ? BBB_LIMIT : CARD_LIMIT;
  const invalidation = isSecond ? BBB_INVALIDATION : CARD_INVALIDATION;
  const strike = isSecond ? BBB_STRIKE : 150;
  return {
    symbol,
    company: `${symbol} Inc.`,
    price: 150,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: `${symbol} ${strike}C 05/15`,
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike, expiry: '2026-05-15', right: 'C', mid: limit, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
  };
}

const originalFetch = global.fetch;

describe('step-7-trade-card — edited card fields reach the order', () => {
  beforeEach(() => {
    // CollapsibleSection persists `bamendjou:tradecard-ladder-collapsed`, and
    // jest.setup.ts never clears storage, so whether the ladder starts open
    // depended on which earlier test had clicked the toggle. `expandLadder`'s
    // idempotence guard made the suite pass over that rather than removing it.
    localStorage.clear();
    act(() => {
      useScanStore.setState({
        scanResult: { candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        pickedContracts: {},
        contractsBySymbol: {},
        scanOverrides: {},
      } as any);
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
      useSettingsStore.setState((s) => ({
        ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      }) as any);
      useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    });
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    (api.armAutoTrade as jest.Mock).mockResolvedValue({ armed: true });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  /** The Invalidation / Premium stop / Time stop fields live inside the
   *  collapsed ladder section. */
  function expandLadder() {
    // Idempotent: the section's own toggle collapses it again, and whether it
    // starts open varies with what else has re-rendered the card.
    if (screen.queryByLabelText('Edit Invalidation')) return;
    fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
  }

  /** Type a new value into one of the card's EditableKV fields and commit it. */
  function editField(label: string, from: string, to: string) {
    fireEvent.click(screen.getByLabelText(`Edit ${label}`));
    const input = screen.getByDisplayValue(from);
    fireEvent.change(input, { target: { value: to } });
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  async function placeLimit() {
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
  }

  it('sends the EDITED invalidation as the position stop, not the card\'s original', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    await placeLimit();

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const [pos] = usePortfolioStore.getState().positions;
    expect(pos.stop).toBe(132);
    expect(pos.stop).not.toBe(CARD_INVALIDATION);
  });

  it('leaves an UNTOUCHED invalidation on the card\'s own value', async () => {
    // The control. An untouched field caches null rather than a snapshot of the
    // seed, precisely so `mergePlan` moving `exit.invalidation` underneath it
    // still wins.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    await placeLimit();

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(CARD_INVALIDATION);
  });

  it('posts the EDITED entry limit as the order\'s limit_price, and says so on the button', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    // The label is a promise about what the click will do; it has to move too.
    const limitBtn = await screen.findByRole('button', { name: /place limit @ \$2\.71/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: 2.71, order_type: 'LMT' }),
    ));
  });

  it('keeps the card, the button and the order agreeing after navigating away and back', async () => {
    // THE ROUND-TRIP DEFECT, found by round 7's scratch probe. TradeCard resets
    // its overlay AND its touched flags on a candidate change and deliberately
    // does not call onEditsChange, so the page-level caches kept the edit while
    // the card put the seed back on screen. Prev/Next and back gave:
    //   card $2.50, button "Place Limit @ $2.71", order limit_price 2.71
    //   invalidation field $140.00, stored stop 132
    // The user saw one trade and got another. `initialPremiumStop` already
    // round-tripped for exactly this reason; the two fields threaded on
    // 2026-09-05 were added without the matching props.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));
    expandLadder();
    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    fireEvent.click(screen.getByLabelText('Next candidate'));
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    // BBB shows ITS OWN untouched values, not AAA's edits. This is the half the
    // round-trip test was missing: with identical fixtures a leak of 2.71/132
    // onto the second candidate was indistinguishable from a correct restore.
    expect(screen.getByLabelText('Edit Limit')).toHaveTextContent(BBB_LIMIT.toFixed(2));
    expandLadder();
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent(BBB_INVALIDATION.toFixed(2));

    fireEvent.click(screen.getByLabelText('Previous candidate'));
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    // The card still SHOWS the edits...
    expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71');
    expandLadder();
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132');

    // ...the button PROMISES them...
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @ \$2\.71/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    // ...and the order and the position USE them.
    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: 2.71 }),
    ));
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(132);
  });

  it('arms auto-trade at the EDITED entry limit', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));
    fireEvent.click(await screen.findByRole('button', { name: /^Arm —/ }));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: 2.71 }),
    ));
  });

  it('does not leak an edit from one candidate onto the other', async () => {
    // The leak direction the round-trip test cannot cover on its own: edit AAA,
    // then place the order on BBB. BBB must post its OWN limit and store its
    // OWN stop.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));
    expandLadder();
    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    fireEvent.click(screen.getByLabelText('Next candidate'));
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: new RegExp(`place limit @ \\$${BBB_LIMIT.toFixed(2)}`, 'i') });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: BBB_LIMIT }),
    ));
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(BBB_INVALIDATION);
  });

  it('CLEARING a field goes back to inheriting the plan, and the order follows', async () => {
    // Round 7 finding 6: `touchedRef` was a one-way latch. Once typed, a field
    // was pinned for the life of the page with no way back to inheriting --
    // the outcome round 6's own note calls the bad one.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    // Clear it.
    fireEvent.click(screen.getByLabelText('Edit Limit'));
    const input = screen.getByDisplayValue('2.71');
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent(CARD_LIMIT.toFixed(2)));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @ \$2\.50/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder).toHaveBeenCalledWith(
      expect.objectContaining({ limit_price: CARD_LIMIT }),
    ));
  });

  it('REJECTS a fat-fingered invalidation instead of storing a wrong stop', async () => {
    // Round 7 bounded this field; ROUND 8 changed the response from clamp to
    // reject, and the difference is the whole point. On a $150 bullish card,
    // "1400" typed for "140" clamped to $148.50 -- 1% below spot -- which
    // `buildPaperPosition` stores as `PortfolioPosition.stop` and
    // `alertEngine` fires STOP_REACHED Critical on at the first ordinary
    // intraday wiggle, Gmail and Telegram behind it, while the user believes
    // their stop is 7% away. "14" clamped to $75.00, a 50% stop, just as
    // silently. A clamp does not refuse a fat-finger, it renames it.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '1400');
    // Unchanged -- the field shows the value it already had.
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation'))
      .toHaveTextContent(CARD_INVALIDATION.toFixed(2)));

    // ...and the other direction.
    editField('Invalidation', String(CARD_INVALIDATION), '14');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation'))
      .toHaveTextContent(CARD_INVALIDATION.toFixed(2)));

    await placeLimit();
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(CARD_INVALIDATION);
  });

  it('SAYS SO when it rejects, instead of silently showing the old number back', async () => {
    // ROUND 9 finding 17. Round 8's reject-don't-clamp policy is right -- a
    // clamp renames a fat-finger rather than refusing it -- but it shipped
    // with no feedback of any kind: `setEditing(false)` and the field showed
    // the previous value again. A user who typed 1400 and looked away could
    // not tell a refusal from an acceptance, and nothing pointed at the range
    // a legitimately wide stop would have to sit in.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '1400');

    const note = await screen.findByText(/kept the previous value/i);
    expect(note).toBeInTheDocument();
    // It names the range, so the user learns what WOULD be accepted.
    expect(note.textContent).toMatch(/between \$\d/);
    // ...and the field genuinely kept the plan's value.
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent(String(CARD_INVALIDATION));
  });

  it('retires the rejection note once a value inside the bound is accepted', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '1400');
    await screen.findByText(/kept the previous value/i);

    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() =>
      expect(screen.queryByText(/kept the previous value/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132');
  });

  it('accepts an invalidation inside the bound', async () => {
    // The control for the test above: the rejection must not swallow a stop the
    // user legitimately moved. Price 150 bullish -> [75.00, 148.50].
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    await placeLimit();
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(132);
  });
});

describe('spec §8 #8 — the two send paths cannot disagree', () => {
  /* ROUND 9 finding 8. This property had a test in premiumStop.test.ts that
   * could not fail: it called `premiumStopDollarToSend(cache[KEY])` twice,
   * assigned the results to names suggesting two different code paths, and
   * compared them to each other. One pure function, one argument, two calls --
   * a tautology under every possible mutation, in the block whose own header
   * called it "the mandated test that shipped missing". Neither
   * `buildPaperPosition` nor `positionFromOrder` was imported there.
   *
   * The two paths take their card from DIFFERENT sources -- `effectiveCard` on
   * the direct path, `o.card` out of `resolveBasketCards` on the basket path --
   * which is exactly why "they read the same map on adjacent lines" was never
   * enough. This drives BOTH through the real page and compares what each
   * actually stored.
   */
  const originalFetch2 = global.fetch;
  beforeEach(() => {
    localStorage.clear();
    act(() => {
      useScanStore.setState({
        scanResult: { candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        pickedContracts: {}, contractsBySymbol: {}, scanOverrides: {},
      } as any);
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
      useSettingsStore.setState((s) => ({
        ibkrPaper: { ...s.ibkrPaper, accountId: 'ACC', baseUrl: 'https://localhost:7499/v1/api' },
      }) as any);
      useAutoTradeStore.setState({ selectedBroker: null, autoMode: 'manual', armed: false, lastOrderId: null });
    });
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
  });
  afterEach(() => { global.fetch = originalFetch2; });

  function expandLadder() {
    if (screen.queryByLabelText('Edit Invalidation')) return;
    fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
  }
  /** Click the field open and commit a value. Addresses the input by its own
   *  label rather than by its current display text, so it does not depend on
   *  how each field happens to render its seed. */
  function editField(label: string, to: string) {
    fireEvent.click(screen.getByLabelText(`Edit ${label}`));
    const input = screen.getByLabelText(`Edit ${label}`) as HTMLInputElement;
    fireEvent.change(input, { target: { value: to } });
    fireEvent.keyDown(input, { key: 'Enter' });
  }

  /** Edit all three threaded fields on AAA, identically in both runs. */
  async function editAllThree() {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();
    editField('Invalidation', '132');
    editField('Premium stop', '0.90');
    editField('Limit', '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));
  }

  it('the direct order path and the basket path store the SAME edited values', async () => {
    // ── Path 1: Place Limit, straight from the active card.
    await editAllThree();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const direct = usePortfolioStore.getState().positions[0]!;

    cleanup();
    act(() => { usePortfolioStore.setState({ positions: [] }); });

    // ── Path 2: pin AAA to the basket and submit, which goes through
    //    resolveBasketCards -> positionFromOrder, a different card object.
    await editAllThree();
    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /send basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Submit 1 order|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const basket = usePortfolioStore.getState().positions[0]!;

    // The three threaded fields agree across the two paths...
    expect(basket.stop).toBe(direct.stop);
    expect(basket.premiumStopDollar).toBe(direct.premiumStopDollar);
    expect(basket.entryPrice).toBe(direct.entryPrice);
    // ...and they are the EDITED values, not the card's originals. Without
    // this the assertions above would pass on two identically-wrong rows.
    expect(direct.stop).toBe(132);
    expect(direct.premiumStopDollar).toBe(0.9);
    expect(basket.stop).toBe(132);
    expect(basket.premiumStopDollar).toBe(0.9);
    expect(basket.stop).not.toBe(CARD_INVALIDATION);
  });
});
