import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step7TradeCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { emptyCardEdits } from '@/lib/cardEdits';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is isolating the INVALIDATION
// gate, so every fixture also needs a satisfied METHOD PICK gate or the new
// `pickMissing` check would leave both direct buttons disabled regardless of
// what these tests are exercising. Keyed to match `makeCard`'s contract
// details via `contractKeyFor` (AAA|150|2026-05-15|C) and stamped with the
// same `scan_id` `mount()` seeds, since `selectCardEdits` returns empty on a
// stamp mismatch.
const CONTRACT_KEY = 'AAA|150|2026-05-15|C';
// `ladder`, not `monte_carlo`: Ladder is the only method available with no
// run (§2.2) — a Monte Carlo pick with no fetched estimate would be cleared
// as stale by TradeCard's own reset effect the instant it mounts, which
// would make every "enabled" assertion below fail for a reason unrelated to
// what this suite (or direct-send-stop-gate.test.tsx as a whole) tests.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

/*
 * DIRECT-SEND-STOP-GATE-2026-09-09.
 *
 * A candidate restored from a scan session persisted BEFORE piece 3 carries
 * `exit.invalidation: null` — the scanStore v15 migration strips the flat
 * percentage it used to hold rather than leaving a number the app would now
 * read as structural. `checkTradeRisk` refuses such a card as
 * `missing_invalidation`, but it runs ONLY inside SendToBrokerDialog, so the
 * two DIRECT buttons on this page placed the order anyway and stored
 * `PortfolioPosition.stop = null`. Nothing then fired at a wrong level — both
 * alert engines skip a null stop — the position simply went UNWATCHED while
 * looking entirely normal in the portfolio list.
 *
 * What these tests pin, and what a weaker version of them would miss:
 *
 *   - The refusal is on the ORDER, not only on the button. Asserting
 *     `toBeDisabled()` alone passes against a build that greys the button and
 *     still posts on click, so every refusal case also asserts that
 *     `api.postOptionOrder` was never called AND that no position was stored.
 *   - A TYPED stop unblocks it. This is the half that makes the gate a gate
 *     rather than a wall: typing a stop is the one gesture that fixes a
 *     restored card, and reading `card.exit.invalidation` instead of the
 *     resolved value would refuse it forever. That mistake is the reason C2
 *     gave `checkTradeRisk` its `resolvedInvalidation` parameter, and this is
 *     the same mistake one screen along.
 *   - The control: an ordinary card is untouched by any of it.
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
 * and `recId` the page sent; every other request keeps the old `{}` reply. */
function echoFetch(): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 201, json: async () => body };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}

const LIMIT = 2.5;
const TYPED_STOP = 138;

/* The WHOLE sentence, not a fragment. The Invalidation field carries its own
 * explanatory prose that quotes "Invalidation stop required" back at the user,
 * so a loose match finds that help text and an absence assertion against it can
 * never pass — it would report the gate as always-on. */
const REFUSAL = 'Invalidation stop required — define an invalidation level before submitting.';

function makeCard(invalidation: number | null, extra: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'AAA',
    company: 'AAA Inc.',
    price: 150,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: { trend: 80, pullback: 80, trigger: 80, event: 80, volatility: 80 },
    contract: 'AAA 150C 05/15',
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
    contractDetails: { strike: 150, expiry: '2026-05-15', right: 'C', mid: LIMIT, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
    entry: { limit: LIMIT, maxFill: 2.63, orderType: 'Limit' },
    exit: { invalidation, premiumStop: 1.5, timeStopDays: 10, target: 160, targets: [] },
    rrRatio: 2.0,
    rrModel: 'Heston repriced',
    finalStatus: 'PASS',
    ...extra,
  };
}

const originalFetch = global.fetch;

function mount(
  invalidation: number | null,
  { withPick = true, extra = {} }: { withPick?: boolean; extra?: Partial<TradeCardData> } = {},
) {
  localStorage.clear();
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard(invalidation, extra)] } as any,
      // Phase G piece 5: the three edit caches this file exercises now live in
      // a SCAN-STAMPED slice on scanStore (lib/cardEdits.ts), so the fixture
      // has to carry the `scan_id` the real type has always declared required
      // — without one there is no stamp, and every edit is dropped. The slices
      // are reset here too: they used to die with the page's useState hooks on
      // unmount, and a persisted store does not.
      //
      // Build step 4 (§7.1) — `withPick` defaults true so this suite's own
      // invalidation-gate tests stay isolated from the newer method-pick
      // gate; the method-pick gate's own tests below pass `false`.
      optionsCardEdits: {
        ...emptyCardEdits(),
        scanId: 'test-scan',
        picks: withPick ? { [CONTRACT_KEY]: pick() } : {},
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
  return render(<Step7TradeCardPage />);
}

/** Pick the paper broker, which is what reveals the two direct buttons. */
async function selectBroker() {
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
  await screen.findByRole('button', { name: /place limit/i });
}

/** The Invalidation field lives inside the collapsed ladder section. */
function expandLadder() {
  if (screen.queryByLabelText('Edit Invalidation')) return;
  fireEvent.click(screen.getByRole('button', { name: /fixed % ladder plan/i }));
}

describe('step-7-trade-card — the direct buttons refuse a card with no stop', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });


  it('B4 refuses Bearish direct sends and arm before saving anything', async () => {
    mount(140, { extra: { direction: 'Bearish', isEtf: true, regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 } } });
    await selectBroker();
    for (const name of [/place limit/i, /right now — market/i]) {
      const button = screen.getByRole('button', { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('title', BEARISH_REASON);
      fireEvent.click(button);
    }
    fireEvent.click(screen.getByRole('button', { name: 'Armed — fire on next qualifying condition' }));
    expect(screen.getByRole('button', { name: /^Arm —/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^Arm —/ })).toHaveAttribute('title', BEARISH_REASON);
    expect(screen.getAllByText(BEARISH_REASON).length).toBeGreaterThan(0);
    await act(async () => {});
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
    expect((global.fetch as jest.Mock).mock.calls.filter(([url, init]) => String(url).endsWith('/api/portfolio') && init?.method === 'POST')).toHaveLength(0);
    expect(usePortfolioStore.getState().positions).toEqual([]);
  });

  it('disables Place Limit and Right Now — Market, and places NO order, when the stop is null', async () => {
    mount(null);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    const limitBtn  = screen.getByRole('button', { name: /place limit/i });
    const marketBtn = screen.getByRole('button', { name: /right now — market/i });
    expect(limitBtn).toBeDisabled();
    expect(marketBtn).toBeDisabled();

    // Disabled is not the claim — not ordering is. A build that greys the
    // button and still posts on click passes the two assertions above.
    fireEvent.click(limitBtn);
    fireEvent.click(marketBtn);
    await Promise.resolve();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('says why, rather than only greying the buttons', async () => {
    mount(null);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    // The same sentence the basket dialog shows, from the same constant.
    expect(screen.getByText(REFUSAL)).toBeInTheDocument();
  });

  it('UNBLOCKS both buttons once the user types a stop, and sends the typed level', async () => {
    // The half that keeps this a gate rather than a wall. Reading
    // `card.exit.invalidation` instead of the resolved value passes every
    // refusal test above and fails this one.
    mount(null);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    expandLadder();

    fireEvent.click(screen.getByLabelText('Edit Invalidation'));
    // The span and the input carry the SAME aria-label, and only one is
    // mounted at a time -- so this second read is the input.
    const input = screen.getByLabelText('Edit Invalidation');
    fireEvent.change(input, { target: { value: String(TYPED_STOP) } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit Invalidation')).toHaveTextContent(String(TYPED_STOP)));

    await selectBroker();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    expect(screen.getByRole('button', { name: /right now — market/i })).toBeEnabled();
    expect(screen.queryByText(REFUSAL)).not.toBeInTheDocument();

    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(TYPED_STOP);
  });

  it('leaves an ordinary card alone — the buttons order and the refusal is absent', async () => {
    // The control. Without it the three tests above are also satisfied by a
    // build that disables the buttons unconditionally.
    mount(140);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    expect(screen.queryByText(REFUSAL)).not.toBeInTheDocument();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());

    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(usePortfolioStore.getState().positions[0].stop).toBe(140);
  });
});

/* Phase G piece 5, build step 4 (§7.1, O2/O3, spec test 9). Same shape as the
 * invalidation-gate suite above, one field along: a card with a real stop but
 * no explicit method pick is refused on the SAME two buttons, and the send
 * handlers early-return before either posts an order. */
describe('step-7-trade-card — the direct buttons refuse a card with no method pick', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('disables Place Limit and Right Now — Market, and places NO order, when no pick has been made', async () => {
    mount(140, { withPick: false });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    const limitBtn  = screen.getByRole('button', { name: /place limit/i });
    const marketBtn = screen.getByRole('button', { name: /right now — market/i });
    expect(limitBtn).toBeDisabled();
    expect(marketBtn).toBeDisabled();

    fireEvent.click(limitBtn);
    fireEvent.click(marketBtn);
    await Promise.resolve();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('says why', async () => {
    mount(140, { withPick: false });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    expect(screen.getByText('Method pick required — choose which method this trade is judged on before submitting.')).toBeInTheDocument();
  });

  it('leaves an ordinary card (with a stop AND a pick) alone', async () => {
    mount(140, { withPick: true });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
  });

  it('the direct Place Limit button carries the pick onto the created position', async () => {
    // Confirmed gap as of build step 4: the gate above blocked an UNPICKED
    // send, but nothing carried a MADE pick's actual values into the position
    // this button creates — `buildPaperPosition` built a `PortfolioPosition`
    // with no `pickedMethod`/`pickedRowStockPrice`/etc at all, so a real send
    // silently discarded the trader's decision even when the gate passed.
    mount(140, { withPick: true });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const created = usePortfolioStore.getState().positions[0]!;
    expect(created.pickedMethod).toBe('ladder');
    expect(created.pickedRowStockPrice).toBe(160);
    expect(created.pickedRowOptionPrice).toBeNull();
    expect(created.pickedStopBasis).toBe('stock');
    expect(created.pickedAt).toBe('2026-09-14T10:00:00.000Z');
  });
});

/* Fix #3 (review, High). Earnings inside the scan's reject window veto the
 * trade: the backend sets `earningsVeto` and forces finalStatus REJECT, and
 * Step 7 must then refuse the send -- both direct buttons and the pin -- and
 * SAY why, rather than leave a greyed button with no reason beside it. Same
 * shape as the stop and method-pick suites above: the refusal is asserted on
 * the ORDER (`postOptionOrder` never called, no position stored), and an
 * ordinary card is the control. */
describe('step-7-trade-card — earnings veto blocks the send', () => {
  const VETO_REASON = 'Earnings inside the reject window — no send';

  beforeEach(() => {
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('disables Place Limit, Right Now — Market and Pin to basket, places NO order, and says why', async () => {
    // A real stop and a real pick: the veto is the ONLY reason for the refusal.
    mount(140, { extra: { earningsVeto: true, finalStatus: 'REJECT' } });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    const limitBtn  = screen.getByRole('button', { name: /place limit/i });
    const marketBtn = screen.getByRole('button', { name: /right now — market/i });
    expect(limitBtn).toBeDisabled();
    expect(marketBtn).toBeDisabled();
    expect(screen.getByRole('button', { name: /pin to basket/i })).toBeDisabled();
    expect(screen.getByText(VETO_REASON)).toBeInTheDocument();
    // The stop and pick gates are satisfied, so theirs are not the reasons shown.
    expect(screen.queryByText(REFUSAL)).not.toBeInTheDocument();
    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();

    // Disabled is not the claim -- not ordering is.
    fireEvent.click(limitBtn);
    fireEvent.click(marketBtn);
    await Promise.resolve();
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('keeps Disarm reachable for a strategy already armed on the vetoed card, and refuses Arm-side fires', async () => {
    // Task 10c (Kenneth, 2026-10-03): the vetoed card used to hide the whole
    // auto-trade control, Disarm included.
    // The backend says AAA is armed; the component's status read switches the
    // panel to armed mode on its own (mount() resets the store to manual).
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAA', direction: 'Bullish' });
    mount(140, { extra: { earningsVeto: true, finalStatus: 'REJECT' } });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    const disarm = await screen.findByRole('button', { name: 'Disarm' });
    expect(disarm).toBeEnabled();
    const fire = screen.getByRole('button', { name: 'Fire now' });
    expect(fire).toBeDisabled();
    expect(fire).toHaveAttribute('title', VETO_REASON);

    fireEvent.click(disarm);
    await waitFor(() => expect(api.disarmAutoTrade).toHaveBeenCalledTimes(1));
  });

  it('shows Arm disabled with the veto reason when nothing is armed', async () => {
    mount(140, { extra: { earningsVeto: true, finalStatus: 'REJECT' } });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    // mount() resets the store to manual mode; Arm shows in armed mode only.
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed' }); });

    const arm = await screen.findByRole('button', { name: /^Arm —/ });
    expect(arm).toBeDisabled();
    expect(arm).toHaveAttribute('title', VETO_REASON);
    fireEvent.click(arm);
    await Promise.resolve();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('leaves an ordinary card alone when earningsVeto is false', async () => {
    mount(140, { extra: { earningsVeto: false } });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    expect(screen.queryByText(VETO_REASON)).not.toBeInTheDocument();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    expect(screen.getByRole('button', { name: /right now — market/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /pin to basket/i })).toBeEnabled();
  });

  it('leaves an ordinary card alone when earningsVeto is absent, and still sends', async () => {
    mount(140);
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();

    expect(screen.queryByText(VETO_REASON)).not.toBeInTheDocument();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    await waitFor(() => expect(limitBtn).toBeEnabled());
    expect(screen.getByRole('button', { name: /pin to basket/i })).toBeEnabled();

    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
  });
});

/* Audit round 1, F4 (Kenneth: age it client-side) — the veto is a scan-time
 * snapshot, and the scan result is persisted. The auditor's example: a Swing
 * scan on Monday sees earnings 23 days out against the 21-day window (no
 * veto); reopened on Thursday the print is 20 days out. Step 7 ages
 * `earningsDays` by the scan's age in calendar days and judges that.
 *
 * F8 — a single stock with UNKNOWN earnings: every fire would be refused, so
 * the Arm is refused up front. A manual send stays allowed (D4: CAUTION). */
describe('audit round 1 F4/F8 — the earnings gate is judged as of today', () => {
  const VETO_REASON = 'Earnings inside the reject window — no send';
  const UNKNOWN_ARM = /Earnings date unknown — auto-trade will not fire a single stock/;

  /** Local wall-clock timestamp `days` calendar days before today. */
  function daysAgo(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() - days);
    d.setHours(10, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00:00`;
  }

  function mountScannedAgo(ago: number, extra: Partial<TradeCardData>) {
    const view = mount(140, { extra });
    act(() => {
      useScanStore.setState((s: any) => ({
        scanResult: { ...s.scanResult, timestamp: daysAgo(ago), event_window: { reject_days: 21, caution_days: 45 } },
      }));
    });
    return view;
  }

  beforeEach(() => {
    jest.clearAllMocks();
    (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 150 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      quoteLive: true, price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = echoFetch();
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('Thursday: a Monday card at 23d has aged to 20d — both direct buttons and the pin are refused', async () => {
    mountScannedAgo(3, { earningsDays: 23, earningsVeto: false, isEtf: false });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    expect(limitBtn).toBeDisabled();
    expect(screen.getByRole('button', { name: /right now — market/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /pin to basket/i })).toBeDisabled();
    expect(screen.getByText(VETO_REASON)).toBeInTheDocument();
  });

  it('Monday (same day): the same card at 23d still sends', async () => {
    mountScannedAgo(0, { earningsDays: 23, earningsVeto: false, isEtf: false });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    expect(screen.queryByText(VETO_REASON)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit/i })).toBeEnabled());
  });

  it('F8: a single stock with unknown earnings cannot be armed, but can still be sent manually', async () => {
    mountScannedAgo(0, { earningsDays: null, earningsUnknown: true, isEtf: false, finalStatus: 'CAUTION' });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed' }); });
    const arm = await screen.findByRole('button', { name: /^Arm —/ });
    expect(arm).toBeDisabled();
    expect(arm.getAttribute('title')).toMatch(UNKNOWN_ARM);
    expect(screen.getByText(UNKNOWN_ARM)).toBeInTheDocument();
    fireEvent.click(arm);
    await Promise.resolve();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
    expect(screen.queryByText(VETO_REASON)).not.toBeInTheDocument();
  });

  it('F8: Disarm stays reachable on that card', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAA', direction: 'Bullish' });
    mountScannedAgo(0, { earningsDays: null, earningsUnknown: true, isEtf: false, finalStatus: 'CAUTION' });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    const disarm = await screen.findByRole('button', { name: 'Disarm' });
    expect(disarm).toBeEnabled();
    fireEvent.click(disarm);
    await waitFor(() => expect(api.disarmAutoTrade).toHaveBeenCalledTimes(1));
  });

  it('F8 control: an ETF with unknown earnings can be armed', async () => {
    mountScannedAgo(0, { earningsDays: null, earningsUnknown: true, isEtf: true });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed' }); });
    const arm = await screen.findByRole('button', { name: /^Arm —/ });
    expect(arm.getAttribute('title') ?? '').not.toMatch(UNKNOWN_ARM);
  });

  /* STOCKS-HORIZON-P0B B7 — the veto window covers the hold. Step 7 judges
   * against `event_window.veto_days`; a result persisted before B5 has none,
   * so it falls back to max(reject_days, the scan's hold) from ScanContext. */
  function mountWithWindow(
    eventWindow: { reject_days: number; caution_days: number; veto_days?: number | null },
    context: { horizonPreset: string; holdMin: number; holdMax: number } | null,
    extra: Partial<TradeCardData>,
  ) {
    const view = mount(140, { extra });
    act(() => {
      useScanStore.setState((s: any) => ({
        scanResult: { ...s.scanResult, timestamp: daysAgo(0), event_window: eventWindow },
        context: context ? { universe: 'SP500', direction: 'Bullish', horizon: 'Position (60–185d)', ...context } : null,
      }) as any);
    });
    return view;
  }

  async function expectVetoed() {
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    const limitBtn = screen.getByRole('button', { name: /place limit/i });
    expect(limitBtn).toBeDisabled();
    expect(limitBtn).toHaveAttribute('title', VETO_REASON);
    expect(screen.getByRole('button', { name: /right now — market/i })).toBeDisabled();
    expect(screen.getByText(VETO_REASON)).toBeInTheDocument();
    fireEvent.click(limitBtn);
    await act(async () => {});
    expect(api.postOptionOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toEqual([]);
  }

  it('B7: passes event_window.veto_days -- earnings 40d against reject 30 / veto 60 is refused', async () => {
    mountWithWindow({ reject_days: 30, caution_days: 60, veto_days: 60 }, null,
      { earningsDays: 40, earningsVeto: false, isEtf: false });
    await expectVetoed();
  });

  it('B7: without veto_days it falls back to max(reject_days, the scan hold) -- Custom 60-185 -> 185', async () => {
    mountWithWindow({ reject_days: 30, caution_days: 60 },
      { horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
      { earningsDays: 120, earningsVeto: false, isEtf: false });
    await expectVetoed();
  });

  it('B7 control: earnings beyond the Custom 60-185 hold still sends', async () => {
    mountWithWindow({ reject_days: 30, caution_days: 60 },
      { horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
      { earningsDays: 190, earningsVeto: false, isEtf: false });
    await waitFor(() => expect(screen.getByLabelText('Edit Limit')).toBeInTheDocument());
    await selectBroker();
    expect(screen.queryByText(VETO_REASON)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit/i })).toBeEnabled());
  });
});

const BEARISH_REASON = 'Bearish setups are Unvalidated: no bearish strategy has passed validation yet (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; no PASS, no auto-trade, no opening order.';
