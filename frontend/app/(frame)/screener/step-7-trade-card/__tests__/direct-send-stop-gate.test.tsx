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

const LIMIT = 2.5;
const TYPED_STOP = 138;

/* The WHOLE sentence, not a fragment. The Invalidation field carries its own
 * explanatory prose that quotes "Invalidation stop required" back at the user,
 * so a loose match finds that help text and an absence assertion against it can
 * never pass — it would report the gate as always-on. */
const REFUSAL = 'Invalidation stop required — define an invalidation level before submitting.';

function makeCard(invalidation: number | null): TradeCardData {
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
  };
}

const originalFetch = global.fetch;

function mount(invalidation: number | null, { withPick = true }: { withPick?: boolean } = {}) {
  localStorage.clear();
  act(() => {
    useScanStore.setState({
      scanResult: { scan_id: 'test-scan', timestamp: '2026-09-14T10:00:00', candidates: [makeCard(invalidation)] } as any,
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
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
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
      price: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.postOptionOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
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
