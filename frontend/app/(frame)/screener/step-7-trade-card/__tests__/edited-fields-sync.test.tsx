import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is about the edited-field sync
// paths, not the method-pick gate, so every fixture below stamps a satisfied
// pick for every contract key it sends through (base AAA/BBB, and the two
// user-overridden contracts the "never shows... quote" test switches to) or
// the new `pickMissing` check leaves every send path disabled regardless of
// what these tests exercise. `ladder`, not `monte_carlo`: Ladder is the only
// method available with no run, so it is the only pick that survives
// TradeCard's own "clear a stale pick" reset effect with no estimate fetched.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

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
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    }),
    postOptionOrder: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    recomputePlan: jest.fn(),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-AUTO' }),
  },
}));

/* P1b-i -- the direct sends now SAVE FIRST, and a 2xx whose body carries no
 * positive `entryPrice` is treated as unconfirmed (no order is sent). So the
 * persist POST ECHOES its request body back, which carries the `entryPrice`
 * and `recId` the page sent; every other request keeps the old `{}` reply.
 *
 * `premiumStopPct` is answered NULL, as it always was before the card began
 * sending its own fraction (PREMIUM-STOP-FALLBACK-ALIGN): the dropped-stop
 * disclosure tests below rely on this reply reading as "the server stored no
 * per-position stop". What the page POSTS is read off the request instead. */
function echoFetch(): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = { ...JSON.parse(String(init.body)), premiumStopPct: null };
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

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
    // Every card a current scan produces carries its resolved regime-gate
    // rule; AutoTradeArm refuses one that does not.
    regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
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
        scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        // Phase G piece 5: the three edit caches this file exercises now live in
        // a SCAN-STAMPED slice on scanStore (lib/cardEdits.ts), so the fixture
        // has to carry the `scan_id` the real type has always declared required
        // — without one there is no stamp, and every edit is dropped. The slices
        // are reset here too: they used to die with the page's useState hooks on
        // unmount, and a persisted store does not.
        optionsCardEdits: {
          ...emptyCardEdits(),
          scanId: 'test-scan',
          picks: { 'AAA|150|2026-05-15|C': pick(), 'BBB|155|2026-05-15|C': pick() },
        },
        stocksCardEdits: emptyCardEdits(),
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
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    (api.armAutoTrade as jest.Mock).mockResolvedValue({ armed: true });
    global.fetch = echoFetch();
    act(() => { useDirectSendNotesStore.setState({ notes: [] }); });
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

  it('a new scan empties the slice AND resets the card, so the two cannot disagree', async () => {
    /* PHASE G piece 5, build step 2 — THE GUARD DEVIATION 3 RESTS ON.
     *
     * The `[scanResult]` effect no longer clears the edit caches; the scan
     * stamp does that. What the effect still does is bump `scanEpoch`, which
     * reaches TradeCard as `resetKey` and makes the card rebuild its overlay.
     * Step 2's audit found that bump was pinned by NOTHING: deleting it left
     * all 24 step-7 tests green.
     *
     * It sits directly on the display-vs-send axis. Without it the store's
     * slice empties on the new scan while the card keeps rendering the value
     * typed against the OLD one — the user reads $2.71, the order carries
     * $2.50. That is the disagreement step 7 spent four rounds closing, and
     * the reason this test asserts BOTH halves in one run: the number on the
     * screen and the number on the wire, after the same scan lands.
     *
     * The second scan reuses the same candidates on purpose. A different card
     * would reset the overlay through the `data.symbol`/`data.contract` branch
     * and prove nothing about `resetKey`. */
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    editField('Limit', String(CARD_LIMIT), '2.71');
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toHaveTextContent('2.71'));

    // A NEW scan lands while the page is mounted — same candidates, new id, so
    // only the stamp has moved.
    act(() => {
      useScanStore.setState({
        scanResult: {
          scan_id: 'test-scan-2',
          timestamp: '2026-09-14T11:00:00',
          candidates: [makeCard('AAA'), makeCard('BBB')],
        } as any,
      } as any);
    });

    // HALF ONE — the screen falls back with the store.
    await waitFor(() =>
      expect(screen.getByLabelText('Edit Limit')).toHaveTextContent(String(CARD_LIMIT)),
    );
    // The slice is still physically present; it is the STAMP that hides it.
    expect(useScanStore.getState().optionsCardEdits.entryLimit).toEqual({ 'AAA|150|2026-05-15|C': 2.71 });

    // Phase G piece 5, build step 4 — the OLD stamp's pick is gone the same
    // way its entryLimit just was (§7.4: a pick from a previous scan is not
    // "old", it is GONE), so the trader has to pick again under the new scan
    // before either send path unblocks. This is a fresh write under the
    // CURRENT stamp, exactly what a real re-pick click would produce — it is
    // deliberately AFTER the raw-entryLimit assertion above, not folded into
    // the scan-landing `setState`, so it cannot be mistaken for something the
    // scan itself carries.
    act(() => {
      useScanStore.setState({
        optionsCardEdits: {
          ...emptyCardEdits(),
          scanId: 'test-scan-2',
          picks: { 'AAA|150|2026-05-15|C': pick(), 'BBB|155|2026-05-15|C': pick() },
        },
      });
    });

    // HALF TWO — and so does the wire. The button label is a promise about
    // what the click will do, so it has to move too.
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @ \$2\.50/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);

    await waitFor(() => expect(api.postOptionOrder as jest.Mock).toHaveBeenCalled());
    expect((api.postOptionOrder as jest.Mock).mock.calls[0][0].limit_price).toBe(CARD_LIMIT);
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

  it('posts NO premium-stop fraction while the premium stop is untouched (inherit the global)', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();
    await placeLimit();
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const posts = (global.fetch as jest.Mock).mock.calls.filter(
      ([url, init]) => String(url).endsWith('/api/portfolio') && (init as RequestInit | undefined)?.method === 'POST',
    );
    const body = JSON.parse((posts[posts.length - 1]![1] as RequestInit).body as string);
    expect([body.premiumStopDollar, body.premiumStopPct]).toEqual([null, null]);
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

  it('arms with the booking fields Place Limit would store: the BUILT contract id and the typed stop', async () => {
    // O4 step 6, test 17. The card's `contract` is the display label
    // ('AAA 150C 05/15'); the position is booked under `toOptionSymbol`'s
    // pipe id. A regression that posts `card.contract`, or derives the id
    // inside AutoTradeArm from anything but the page's `toOptionSymbol`, goes
    // red on the first assertion. The typed stop must travel AND be flagged
    // typed, or the booking re-anchors it by (live - scan).
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();
    editField('Invalidation', String(CARD_INVALIDATION), '132');
    await waitFor(() => expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent('132'));

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));
    fireEvent.click(await screen.findByRole('button', { name: /^Arm —/ }));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const body = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(body.option_symbol).toBe('AAA|150|2026-05-15|C');
    expect(body.stop).toBe(132);
    expect(body.stop_is_user_set).toBe(true);
    expect(body.scan_stock_price).toBe(150);
    expect(body.dte_total).toBe(24);
    expect(body.targets).toEqual([]);
    expect(body.trade_card_snapshot).toEqual(expect.objectContaining({ strike: 150 }));
  });

  it('arms an UNTOUCHED stop as plan-derived, so the booking re-anchors it', async () => {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(await screen.findByText(/armed — fire on next qualifying condition/i));
    fireEvent.click(await screen.findByRole('button', { name: /^Arm —/ }));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const body = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(body.stop).toBe(CARD_INVALIDATION);
    expect(body.stop_is_user_set).toBe(false);
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
        scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        // Phase G piece 5: the three edit caches this file exercises now live in
        // a SCAN-STAMPED slice on scanStore (lib/cardEdits.ts), so the fixture
        // has to carry the `scan_id` the real type has always declared required
        // — without one there is no stamp, and every edit is dropped. The slices
        // are reset here too: they used to die with the page's useState hooks on
        // unmount, and a persisted store does not.
        optionsCardEdits: {
          ...emptyCardEdits(),
          scanId: 'test-scan',
          picks: {
            'AAA|150|2026-05-15|C': pick(), 'BBB|155|2026-05-15|C': pick(),
            // The two user-overridden contracts the quote-leak test switches
            // to — `editKeyFor` reads the EFFECTIVE (overridden) card once
            // `pickedContracts` names one, so a pick keyed only to the base
            // contract would leave that test's send gated on a key nothing
            // ever writes to.
            'AAA|160|2026-05-15|C': pick(), 'BBB|170|2026-05-15|C': pick(),
          },
        },
        stocksCardEdits: emptyCardEdits(),
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
    // ROUND 10 finding 7 -- the LIVE mid must DIFFER from
    // `contractDetails.mid` (2.5), or `expect(basket.entryPrice).toBe(
    // direct.entryPrice)` cannot fail: the direct path takes the live quote
    // and the basket path took the scan mid, and with both set to 2.5 the two
    // were trivially equal. 4.0 makes the divergence visible.
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 4.0, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
    act(() => { useDirectSendNotesStore.setState({ notes: [] }); });
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

  it('never shows or stores another contract\'s live quote after Next-then-Prev', async () => {
    // ROUND 10 finding 1. The quote effect has an early return (the
    // override-already-claimed dedup gate) ABOVE its `setLiveQuote(null)`, so
    // returning to a candidate whose contract was user-picked in step 6 left
    // the OTHER candidate's quote standing. The card printed the wrong mid,
    // buildPaperPosition stored it as this contract's entryPrice, and round
    // 9's own `liveMid` prop carried it into the arm request and into the
    // premium-stop bounds. The quote is keyed to its contract now.
    act(() => {
      useScanStore.setState({
        scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard('AAA'), makeCard('BBB')] } as any,
        // Both contracts USER-PICKED, which is what arms the dedup gate.
        // `pickedContracts` maps symbol -> contract ID and is resolved against
        // `contractsBySymbol`; the id must DIFFER from `card.contract` or
        // applyPickedContract returns the card untouched and `_userOverride`
        // is never set -- in which case the gate never arms and this test
        // silently exercises nothing.
        pickedContracts: { AAA: 'AAA|160|2026-05-15|C', BBB: 'BBB|170|2026-05-15|C' },
        contractsBySymbol: {
          AAA: [{ id: 'AAA|160|2026-05-15|C', strike: 160, expiry: '2026-05-15', right: 'C',
                  price: 2.4, delta: 0.42, theta: -0.08, ivRank: 44, ivPercentile: 40, dte: 24,
                  score: 70, contractConfidence: 'PASS' }],
          BBB: [{ id: 'BBB|170|2026-05-15|C', strike: 170, expiry: '2026-05-15', right: 'C',
                  price: 3.4, delta: 0.41, theta: -0.08, ivRank: 44, ivPercentile: 40, dte: 24,
                  score: 70, contractConfidence: 'PASS' }],
        },
        scanOverrides: {},
      } as any);
    });
    // The dedup gate only stays armed if the recompute SETTLES -- the effect's
    // cleanup deletes an unsettled claim. A bare jest.fn() returning undefined
    // therefore disarms the very gate this test exists to exercise.
    (api.recomputePlan as jest.Mock).mockResolvedValue({
      entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
      exit: { invalidation: CARD_INVALIDATION, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
      rrRatio: 2.0, rrModel: 'Heston repriced',
    });
    // Distinct live mids, so a leak is unmistakable.
    (api.getContractQuote as jest.Mock).mockImplementation((sym: string) =>
      Promise.resolve({
        quoteLive: true, price: sym === 'BBB' ? 7.77 : 2.22,
        delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
      }),
    );

    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/Live mid: \$2\.22/)).toBeInTheDocument());
    // The claim only SURVIVES cleanup once the recompute has settled, and only
    // a surviving claim arms the gate on the way back.
    await waitFor(() => expect((api.recomputePlan as jest.Mock).mock.calls.length).toBeGreaterThan(0));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    // Next to BBB...
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(screen.getByText(/Live mid: \$7\.77/)).toBeInTheDocument());
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

    // ...and back to AAA. The gate fires and no re-fetch happens, so an
    // unkeyed quote would still be BBB's.
    fireEvent.click(screen.getByRole('button', { name: /prev/i }));
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await act(async () => { await new Promise((r) => setTimeout(r, 80)); });
    expect(screen.queryByText(/Live mid: \$7\.77/)).not.toBeInTheDocument();
    // The gate really did fire -- otherwise a re-fetch would mask the defect
    // and this test would pass for the wrong reason.
    expect((api.getContractQuote as jest.Mock).mock.calls.map((c) => c[0]))
      .toEqual(['AAA', 'BBB']);

    // And the order path stores AAA's own premium, never BBB's.
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const [pos] = usePortfolioStore.getState().positions;
    expect(pos.symbol).toBe('AAA');
    expect(pos.entryPrice).not.toBe(7.77);
  });

  it('the direct order path and the basket path store the SAME edited values', async () => {
    // ── Path 1: Place Limit, straight from the active card.
    await editAllThree();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const direct = usePortfolioStore.getState().positions[0]!;
    // P2-06: `premiumStopDollar` is create-only transport and is dropped from
    // the row once the server accepts it, so the dollar each path SENT is read
    // off the POST itself.
    const lastPostedPremiumStop = () => {
      const posts = (global.fetch as jest.Mock).mock.calls.filter(
        ([url, init]) => String(url).endsWith('/api/portfolio') && (init as RequestInit | undefined)?.method === 'POST',
      );
      return JSON.parse((posts[posts.length - 1]![1] as RequestInit).body as string).premiumStopDollar;
    };
    // PREMIUM-STOP-FALLBACK-ALIGN -- the fraction and the entry it is a
    // fraction OF, as POSTED (the echo mock answers premiumStopPct null).
    const lastPostedPct = () => {
      const posts = (global.fetch as jest.Mock).mock.calls.filter(
        ([url, init]) => String(url).endsWith('/api/portfolio') && (init as RequestInit | undefined)?.method === 'POST',
      );
      const b = JSON.parse((posts[posts.length - 1]![1] as RequestInit).body as string);
      return [b.premiumStopPct, b.entryPrice];
    };
    const directPremiumStop = lastPostedPremiumStop();
    const directPct = lastPostedPct();

    cleanup();
    act(() => { usePortfolioStore.setState({ positions: [] }); });

    // ── Path 2: pin AAA to the basket and submit, which goes through
    //    resolveBasketCards -> positionFromOrder, a different card object.
    await editAllThree();
    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const basket = usePortfolioStore.getState().positions[0]!;
    const basketPremiumStop = lastPostedPremiumStop();
    const basketPct = lastPostedPct();
    // Both paths post the user's own fraction against the SAME entry they
    // post: $0.90 of the $4.00 live mid.
    expect(directPct).toEqual([0.9 / 4.0, 4.0]);
    expect(basketPct).toEqual([0.9 / 4.0, 4.0]);

    // The three threaded fields agree across the two paths...
    expect(basket.stop).toBe(direct.stop);
    expect(basketPremiumStop).toBe(directPremiumStop);
    // ...including the entry price, which is the denominator the premium stop
    // is derived against. The live mid (4.0) differs from the scan mid (2.5),
    // so this assertion has something to catch.
    expect(basket.entryPrice).toBe(direct.entryPrice);
    expect(direct.entryPrice).toBe(4.0);
    // ...and the two fields that tell the SERVER how to treat the stop. Round
    // 10 found these diverging silently: the basket path stamped
    // stopIsUserSet:true on untouched positions and omitted scanStockPrice
    // entirely, so neither the re-anchor nor the wrong-side guard ever ran on
    // anything it sent.
    expect(basket.stopIsUserSet).toBe(direct.stopIsUserSet);
    expect(basket.scanStockPrice).toBe(direct.scanStockPrice);
    // ...and they are the EDITED values, not the card's originals. Without
    // this the assertions above would pass on two identically-wrong rows.
    expect(direct.stop).toBe(132);
    expect(directPremiumStop).toBe(0.9);
    expect(basket.stop).toBe(132);
    expect(basketPremiumStop).toBe(0.9);
    expect(basket.stop).not.toBe(CARD_INVALIDATION);
    // Confirmed gap as of build step 4: the send gate blocked an UNPICKED
    // send on both paths, but nothing carried a MADE pick's values onto
    // either `positionFromOrder` (basket) or `buildPaperPosition` (direct) —
    // a real send on either path silently discarded the fixture's `pick()`
    // regardless of the gate passing.
    expect(basket.pickedMethod).toBe(direct.pickedMethod);
    expect(direct.pickedMethod).toBe('ladder');
    expect(basket.pickedRowStockPrice).toBe(direct.pickedRowStockPrice);
    expect(direct.pickedRowStockPrice).toBe(160);
    expect(basket.pickedStopBasis).toBe(direct.pickedStopBasis);
    expect(direct.pickedStopBasis).toBe('stock');
    expect(basket.pickedAt).toBe(direct.pickedAt);
    expect(direct.pickedAt).toBe('2026-09-14T10:00:00.000Z');
  });

  it('does NOT claim an UNTOUCHED basket stop was user-set', async () => {
    // ROUND 10 finding 6. `invalidationFor` falls back to the card's own value
    // and is never null, so `stopIsUserSet: invalidation != null` was true for
    // every basket position -- telling the router to skip re-anchoring a stop
    // that is entirely plan-derived. The direct path used the correct
    // `invalidationIsUserSetFor` all along, so the two disagreed.
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const [pos] = usePortfolioStore.getState().positions;
    expect(pos.stopIsUserSet).toBe(false);
    // ...and it still carries the plan's own stop, plus the anchor the router
    // needs to re-anchor it and to run the wrong-side guard.
    expect(pos.stop).toBe(CARD_INVALIDATION);
    expect(pos.scanStockPrice).toBe(150);
  });

  /* ROUND 12 finding 2 — the basket path's two messages were WRITTEN and never
   * SHOWN. Both `saveNotes` and `orderError` (the basket's rejection banner
   * until A8b split it into `basketError`) rendered inside the
   * `{selectedBroker && ...}` block of the paper-execution section, and the
   * basket never touches BrokerPicker: it is pinned on the card and submitted
   * through SendToBrokerDialog. So a user who sent a basket without also
   * selecting a paper broker got no dropped-stop disclosure and no rejection
   * banner.
   *
   * `selectedBroker` is null in this block's beforeEach and neither of the two
   * tests immediately below clicks a broker, which is the whole point — click one and both pass on the
   * old code too. */
  it('shows the dropped-stop disclosure for a BASKET order with no broker selected', async () => {
    // The mocked POST answers `{}`, i.e. no premiumStopPct, which is exactly
    // what the router returns when the save-time re-anchor could not apply the
    // requested dollar stop and the row silently inherited the global.
    await editAllThree();
    expect(screen.queryByRole('button', { name: /place limit @/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    // The dollar in the note is the one the user typed on the card ($0.90),
    // not the global it fell back to.
    expect(
      await screen.findByText(/AAA: Premium stop of \$0\.90\/share could not be applied/),
    ).toBeInTheDocument();
    // STOP-SEMANTICS: the note names the reason. This mock ECHOES the request
    // (entry $4.00, premiumStopPct null), which a real server never would for
    // a 22.5% stop -- so the reason is premiumStopDropReason's residual branch.
    // What is pinned is that the reason reaches the rendered note.
    expect(screen.getByText(
      'AAA: Premium stop of $0.90/share could not be applied: at the filled premium it would fire below $0.01 — this position inherits the global stop.',
    )).toBeInTheDocument();
  });

  it('keeps the basket\'s dropped-stop disclosure across Prev/Next until the next send (A8, open_questions[61])', async () => {
    // The `[active]` effect clears the per-card notes on every navigation, and
    // the basket's notes used to share that list -- so pressing Next after a
    // basket send destroyed the disclosure before it could be read.
    //
    // Two sends here; the daily-recommendation cap (5) is shared by every
    // basket test in this file and nothing resets it, so give back what this
    // test consumes or the later ones are refused before they send.
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    await editAllThree();
    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    let submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    const NOTE = /AAA: Premium stop of \$0\.90\/share could not be applied/;
    expect(await screen.findByText(NOTE)).toBeInTheDocument();

    // Navigate: the disclosure stays.
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous candidate' }));
    expect(screen.getByText(NOTE)).toBeInTheDocument();

    // The next send (BBB, no typed premium stop) starts by clearing it.
    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket/i }));
    submit = await screen.findByRole('button', { name: /^(Add \d to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(screen.queryByText(NOTE)).not.toBeInTheDocument());
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(2));
    act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
  });

  it('shows the rejection banner for a BASKET order with no broker selected', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: 'single_trade_exposure_too_high' }),
    }) as unknown as typeof fetch;

    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
    const submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    // The row is rolled back, so the ONLY evidence the user has that nothing
    // was saved is this banner.
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(0));
    expect(await screen.findByText(/Some orders were not saved — AAA:/)).toBeInTheDocument();
  });

  it('does not leave the previous submit\'s banner over a successful one', async () => {
    /* Round 1 of the follow-up audit. `handleSubmit` cleared `saveNotes` and
     * not the basket's banner (then `orderError`, `basketError` since A8b),
     * and the only other resets are the two DIRECT paper paths -- which a
     * basket-only user never goes through. Invisible while the banner was
     * gated behind a selected broker; reachable the moment it was hoisted. */
    {
      // ── Submit 1: the backend refuses it.
      global.fetch = jest.fn().mockResolvedValue({
        ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }),
      }) as unknown as typeof fetch;
      render(<Step7TradeCardPage />);
      await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
      fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
      let submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
      await waitFor(() => expect(submit).toBeEnabled());
      fireEvent.click(submit);
      expect(await screen.findByText(/Some orders were not saved/)).toBeInTheDocument();

      // ── Submit 2: the backend accepts it. Same page, same card, no
      //    navigation -- so nothing else clears the banner.
      global.fetch = jest.fn().mockResolvedValue({
        ok: true, json: async () => ({}),
      }) as unknown as typeof fetch;
      fireEvent.click(screen.getByRole('button', { name: /pin to basket/i }));
      fireEvent.click(await screen.findByRole('button', { name: /track basket \(1\)/i }));
      submit = await screen.findByRole('button', { name: /^(Add 1 to Portfolio|Override & Submit)$/ });
      await waitFor(() => expect(submit).toBeEnabled());
      fireEvent.click(submit);

      await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
      expect(screen.queryByText(/Some orders were not saved/)).not.toBeInTheDocument();
    }
  });

  /* A8b (decision A8B-BASKET-BANNER-AND-DEAD-ENDPOINT-2026-09-24). The basket's
   * "Some orders were not saved" banner gets the basket notices' lifetime: it
   * survives Prev/Next and is cleared only when the next send of ANY kind
   * starts. A direct-path error keeps its per-card lifetime.
   *
   * The daily-recommendation cap (5) is shared by every basket test in this
   * file and nothing resets it, so each test gives back what it consumes -- in
   * a `finally`, so a failing assertion (a mutation run) cannot leak a spent
   * slot into the tests after it. */
  const reject422 = () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }),
    }) as unknown as typeof fetch;
  };
  const acceptAll = () => {
    global.fetch = echoFetch();
  };
  async function sendBasket() {
    fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
    fireEvent.click(await screen.findByRole('button', { name: /track basket/i }));
    const submit = await screen.findByRole('button', { name: /^(Add \d to Portfolio|Override & Submit)$/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
  }
  async function renderPage() {
    render(<Step7TradeCardPage />);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
  }
  const BANNER = /Some orders were not saved — AAA:/;

  it('keeps the basket\'s failure banner across Prev/Next until the next send (A8b)', async () => {
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    try {
      reject422();
      await renderPage();
      await sendBasket();
      expect(await screen.findByText(BANNER)).toBeInTheDocument();

      // Navigate: the banner stays.
      fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
      await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
      expect(screen.getByText(BANNER)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Previous candidate' }));
      await waitFor(() => expect(screen.getByText('AAA Inc.')).toBeInTheDocument());
      expect(screen.getByText(BANNER)).toBeInTheDocument();

      // The next basket send (BBB, accepted) starts by clearing it.
      acceptAll();
      fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
      await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
      await sendBasket();
      await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
      expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
    } finally {
      act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
    }
  });

  it('a DIRECT send clears the basket\'s failure banner (A8b)', async () => {
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    try {
      reject422();
      await renderPage();
      await sendBasket();
      expect(await screen.findByText(BANNER)).toBeInTheDocument();

      acceptAll();
      fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
      const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
      await waitFor(() => expect(limitBtn).toBeEnabled());
      fireEvent.click(limitBtn);
      await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
      expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
    } finally {
      act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
    }
  });

  it('a MARKET (Right Now) send clears the basket\'s failure banner too (A8b)', async () => {
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    try {
      reject422();
      await renderPage();
      await sendBasket();
      expect(await screen.findByText(BANNER)).toBeInTheDocument();

      acceptAll();
      fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
      const marketBtn = await screen.findByRole('button', { name: /right now — market/i });
      await waitFor(() => expect(marketBtn).toBeEnabled());
      fireEvent.click(marketBtn);
      await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
      expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
    } finally {
      act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
    }
  });

  it('a DIRECT-path error still clears on Prev/Next (A8b left its lifetime per-card)', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(new Error('broker down'));
    const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    // P1b-i: the position is saved FIRST, so a plain Error from the broker
    // call leaves the order's fate UNKNOWN -- the row is kept and a
    // persistent ORDER-UNKNOWN note is pushed. The banner is `String(e)`.
    expect(await screen.findByText(/Order status UNKNOWN \(Error: broker down\)/)).toBeInTheDocument();
    expect(usePortfolioStore.getState().positions).toHaveLength(1);
    expect(screen.getByText(/order status UNKNOWN \(rec_id REC-/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
    await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
    // The per-card banner goes; the note does not.
    expect(screen.queryByText(/broker down/)).not.toBeInTheDocument();
    expect(screen.getByText(/order status UNKNOWN \(rec_id REC-/)).toBeInTheDocument();
  });

  it('a BASKET send clears a direct-path error (A8b)', async () => {
    // After the split, 'does not leave the previous submit's banner' only
    // runs basket -> basket; this is the test that pins handleSubmit's
    // `setOrderError(null)`.
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    try {
      await renderPage();
      fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
      (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(new Error('broker down'));
      const limitBtn = await screen.findByRole('button', { name: /place limit @/i });
      await waitFor(() => expect(limitBtn).toBeEnabled());
      fireEvent.click(limitBtn);
      expect(await screen.findByText(/broker down/)).toBeInTheDocument();
      // P1b-i: that send KEPT its AAA row (order status unknown). Left in the
      // store, the basket dialog flags it as a duplicate and waits for an
      // override, and a `toHaveLength(1)` would hold either way. The banner is
      // page state, so dropping the row leaves it standing; then wait on the
      // basket's OWN persist POST before reading the banner.
      act(() => { usePortfolioStore.setState({ positions: [] }); });
      expect(screen.getByText(/broker down/)).toBeInTheDocument();
      const portfolioPosts = () => (global.fetch as jest.Mock).mock.calls.filter(
        ([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST',
      ).length;
      const postsBefore = portfolioPosts();

      await sendBasket();
      await waitFor(() => expect(portfolioPosts()).toBeGreaterThan(postsBefore));
      await waitFor(() => expect(screen.queryByText(/broker down/)).not.toBeInTheDocument());
    } finally {
      act(() => { useRiskStore.setState({ dailyRecommendations: dailyBefore }); });
    }
  });

  /* MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25). IBKR's confirmation question is
   * now a 502 carrying it (it used to be an empty-id 200, and both direct
   * handlers then persisted a phantom position). Pinned for BOTH handlers.
   * P1b-i: the position is now saved BEFORE the order, and this 502 is
   * provably pre-submit, so the saved row is DELETED by its rec_id: one
   * persist POST, one delete of that recId, no position left, the error shows. */
  const CONFIRM_502 = () => new Error(
    'API /broker/option-order → 502: IBKR did not place the order: it asked for a ' +
    'confirmation this app does not send. IBKR said: Are you sure you want to submit this order?',
  );
  for (const [label, button] of [
    ['Place Limit', /place limit @/i],
    ['Right Now — Market', /right now — market/i],
  ] as const) {
    it(`an IBKR confirmation question (502) on ${label} shows as an error and creates no position`, async () => {
      acceptAll();
      await renderPage();
      fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
      (api.postOptionOrder as jest.Mock).mockRejectedValueOnce(CONFIRM_502());
      const btn = await screen.findByRole('button', { name: button });
      await waitFor(() => expect(btn).toBeEnabled());
      fireEvent.click(btn);

      expect(await screen.findByText(/IBKR said: Are you sure/)).toBeInTheDocument();
      expect(api.postOptionOrder).toHaveBeenCalledTimes(1);
      const posts = (global.fetch as jest.Mock).mock.calls.filter(
        ([u, init]) => String(u).endsWith('/api/portfolio') && init?.method === 'POST',
      );
      expect(posts).toHaveLength(1);
      const recId = JSON.parse(String(posts[0][1].body)).recId;
      expect(api.deletePortfolioPosition).toHaveBeenCalledWith(recId);
      expect(screen.getByText(/The tracked position was removed/)).toBeInTheDocument();
      expect(usePortfolioStore.getState().positions).toHaveLength(0);
      expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
      // Nothing was placed, so the user can send again.
      await waitFor(() => expect(screen.getByRole('button', { name: button })).toBeEnabled());
    });
  }
  /* Fix #5 (review, D6). The basket places NO broker order: it only saves
   * Portfolio rows. It used to store them `source: 'broker'` and toast "N sent
   * to broker", which made phantom positions that look like live fills. */
  it('an EMPTY basket labels the (disabled) main button "Track basket", never "Send to broker"', async () => {
    acceptAll();
    await renderPage();
    const btn = await screen.findByRole('button', { name: /^Track basket$/ });
    expect(btn).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^Send to broker$/ })).not.toBeInTheDocument();
  });
  it('a basket submit of two saved rows says "added to Portfolio", never "sent to broker", and stores source manual', async () => {
    const dailyBefore = useRiskStore.getState().dailyRecommendations;
    // Record what every basket row hands to addPosition. (`source` is a
    // client-side tag: toBackendPayload does not send it, so the POST body
    // cannot show it; addPosition's argument is where it is decided.)
    const realAddPosition = usePortfolioStore.getState().addPosition;
    const added: Array<{ symbol: string; source?: string }> = [];
    act(() => {
      usePortfolioStore.setState({
        addPosition: ((p: Parameters<typeof realAddPosition>[0]) => {
          added.push({ symbol: p.symbol, source: p.source });
          return realAddPosition(p);
        }) as typeof realAddPosition,
      });
    });
    try {
      acceptAll();
      await renderPage();
      fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
      fireEvent.click(screen.getByRole('button', { name: 'Next candidate' }));
      await waitFor(() => expect(screen.getByText('BBB Inc.')).toBeInTheDocument());
      fireEvent.click(await screen.findByRole('button', { name: /pin to basket/i }));
      fireEvent.click(await screen.findByRole('button', { name: /basket \(2\)/i }));
      const submit = await screen.findByRole('button', { name: /^(Add 2 to Portfolio|Override & Submit)$/ });
      await waitFor(() => expect(submit).toBeEnabled());
      fireEvent.click(submit);

      await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(2));
      expect(await screen.findByText('2 added to Portfolio')).toBeInTheDocument();
      expect(screen.getByText(/No broker order was placed/)).toBeInTheDocument();
      // The toast must say a tracked row RESERVES its contract (it blocks a later card send).
      expect(screen.getByText(/Tracked rows reserve their contract/)).toBeInTheDocument();
      expect(screen.queryByText(/send each one from its card/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/sent to broker/i)).not.toBeInTheDocument();
      // Every basket row was tagged manual, and none was routed to a broker.
      expect(added.map((a) => a.symbol).sort()).toEqual(['AAA', 'BBB']);
      for (const a of added) expect(a.source).toBe('manual');
      for (const p of usePortfolioStore.getState().positions) expect(p.source).toBe('manual');
      expect(api.postOptionOrder).not.toHaveBeenCalled();
    } finally {
      act(() => {
        usePortfolioStore.setState({ addPosition: realAddPosition });
        useRiskStore.setState({ dailyRecommendations: dailyBefore });
      });
    }
  });
});
