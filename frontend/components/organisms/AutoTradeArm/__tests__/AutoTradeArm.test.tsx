import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { AutoTradeArm } from '@/components/organisms/AutoTradeArm';
import { useRiskStore } from '@/lib/riskStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PortfolioPosition } from '@/types/domain';
import { api } from '@/lib/api';
import { MISSING_REGIME_GATE_SNAPSHOT_TITLE } from '@/lib/regimeGateOverrides';
import type { TradeCardData, MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — every render below must supply a pick, or
// the new `pickMissing` gate disables Arm regardless of what each test is
// actually isolating (the same reason SendToBrokerDialog's suite needed one).
const pick = (): MethodPick => ({
  method: 'monte_carlo',
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

// O4 step 6 — the two REQUIRED booking props, spread into every render so
// the tests below keep isolating what they isolated. `optionSymbol` is
// deliberately NOT `mockCard.contract`, so a regression to posting
// `card.contract` goes red.
const BOOKING = { optionSymbol: 'AAPL|190|2026-05-15|C', stopIsUserSet: false } as const;

jest.mock('@/lib/api', () => ({
  api: {
    armAutoTrade: jest.fn().mockResolvedValue({ armed: true }),
    disarmAutoTrade: jest.fn().mockResolvedValue({ armed: false }),
    fireAutoTrade: jest.fn().mockResolvedValue({ order_id: 'ORD-1' }),
    getAutoTradeStatus: jest.fn().mockResolvedValue({ armed: false }),
  },
}));

const mockCard: TradeCardData = {
  symbol: 'AAPL',
  company: 'Apple Inc.',
  price: 185.2,
  direction: 'Bullish',
  status: 'PASS',
  stockScore: 82,
  stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15',
  contractScore: 70,
  contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: {
    strike: 190, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09,
    ivRank: 45, dte: 24,
  },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 5.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
    ],
  },
  rrRatio: 2.5,
  rrModel: 'Heston repriced',
  // The rule the card's scan resolved. Every card a current scan produces
  // carries one; a card without it is refused at Arm (see the regime-gate
  // describe at the bottom).
  regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 },
} as TradeCardData;

describe('AutoTradeArm — backend payload portfolio_value', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it('handleArm posts the riskStore-configured portfolio_value, not the backend default', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.portfolio_value).toBe(73_000);
  });

  // Piece 4 — the field existed on ArmRequest, on ArmedStrategy, on the schema
  // bound and at both resolve_premium_stop_pct call sites in auto_trader.py,
  // and NOTHING could set it: api.armAutoTrade's request type did not declare
  // it, so every armed strategy sized off the auto_trade global. The backend
  // test covered the plumbing and never that anything fills the pipe.
  it('posts the card\'s premium stop as a fraction of the entry_premium it books', async () => {
    // $1.00 of a $2.50 mid = 0.40. Derived against entry_premium specifically:
    // anchoring it to any other premium is the bug piece 4's router fix exists
    // to prevent.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.entry_premium).toBe(2.5);
    expect(payload.premium_stop_pct).toBeCloseTo(0.40, 6);
  });

  it('omits the premium stop entirely when the card carries none, so the auto-trader inherits the global', async () => {
    // undefined, not null: ArmRequest.premium_stop_pct is Optional with a None
    // default, and omitting is what "inherit" means on that endpoint.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.premium_stop_pct).toBeUndefined();
  });

  it('omits a stop at or above the whole premium rather than sending a fraction the schema rejects', async () => {
    // A total loss is unreachable-by-definition rather than a stop, and the
    // endpoint's bound is lt=1 — sending 1.0 would 422 the arm.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={2.5} methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.premium_stop_pct).toBeUndefined();
  });

  it('books the LIVE mid as entry_premium, not the scan-time snapshot', async () => {
    // ROUND 9 finding 5. `card.contractDetails.mid` comes off a scanResult that
    // scanStore persists to localStorage, so after a reload it can be days old
    // -- the staleness round 8 fixed for the card's own bounds and did not
    // carry here. It is booked as the entry, it is the denominator the stop
    // fraction is derived against, and the backend's _check_daily_loss sizes
    // the full premium `entry_premium * quantity * 100` off it (since A6).
    //
    // Scanned at $2.50, reopened at $6.00, with a $1.00 dollar stop:
    //   stale -> entry 2.50, pct 0.400  (gate books 2.4x too little risk)
    //   live  -> entry 6.00, pct 0.1667
    render(
      <AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={6.0} methodPick={pick()} />,
    );
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.entry_premium).toBe(6.0);
    expect(payload.entry_premium).not.toBe(2.5);
    expect(payload.premium_stop_pct).toBeCloseTo(1.0 / 6.0, 6);
  });

  it('falls back to the scan-time mid when no live quote has been fetched', async () => {
    // The prop is additive: a page that has not fetched a quote yet behaves
    // exactly as it did before.
    render(
      <AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={null} methodPick={pick()} />,
    );
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    expect((api.armAutoTrade as jest.Mock).mock.calls[0][0].entry_premium).toBe(2.5);
  });

  it('reflects an already-armed backend state after reload', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValueOnce({ armed: true });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);

    await waitFor(() => expect(screen.getByText('Armed — waiting for next trigger')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Disarm' })).toBeInTheDocument();
  });
});

/* DIRECT-SEND-STOP-GATE-2026-09-09.
 *
 * Gating step 7's two direct buttons and leaving Arm open beside them would
 * not have closed the hole -- it would have relabelled it, and put the way
 * around the refusal directly under the refusal. This path is the worse door
 * of the two: an auto-trade fill creates no PortfolioPosition at all
 * (auto_trader.fire), so a card with no stop armed here yields a filled order
 * carrying no stop, no premium stop and no time stop.
 *
 * The arm REQUEST still sends no stop level; `resolvedInvalidation` is a gate,
 * not a payload, and no assertion below expects it on the wire.
 */
describe('AutoTradeArm — refuses to arm a card with no invalidation stop', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  const noStopCard = { ...mockCard, exit: { ...mockCard.exit, invalidation: null } } as TradeCardData;

  it('disables Arm and posts NOTHING when the resolved stop is null', async () => {
    render(<AutoTradeArm {...BOOKING} card={noStopCard} broker="ibkr_paper" resolvedInvalidation={null} methodPick={pick()} />);
    const arm = screen.getByText(/^Arm —/).closest('button')!;
    expect(arm).toBeDisabled();

    // Disabled is not the claim. A build that greys the button and still posts
    // on click satisfies the line above and fails this one.
    fireEvent.click(arm);
    await Promise.resolve();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('arms normally once the user has typed a stop, even though the CARD still has none', async () => {
    // The half that makes this a gate rather than a wall, and the one a
    // `card.exit.invalidation` implementation fails: typing a stop is the
    // single gesture that fixes a restored candidate, and the caller resolves
    // it exactly as every send path does.
    render(<AutoTradeArm {...BOOKING} card={noStopCard} broker="ibkr_paper" resolvedInvalidation={185} methodPick={pick()} />);
    const arm = screen.getByText(/^Arm —/).closest('button')!;
    expect(arm).toBeEnabled();

    fireEvent.click(arm);
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    // A gate, not a payload: the arm request still carries no stop level.
    expect((api.armAutoTrade as jest.Mock).mock.calls[0][0]).not.toHaveProperty('invalidation');
  });

  it('falls back to the card when the prop is omitted, matching checkTradeRisk', async () => {
    // `undefined` means "no overlay to consult", not "no gate" -- the same
    // contract `checkTradeRisk.resolvedInvalidation` documents. A card with no
    // stop is still refused; the ordinary card is still armable.
    const { unmount } = render(<AutoTradeArm {...BOOKING} card={noStopCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.getByText(/^Arm —/).closest('button')!).toBeDisabled();
    unmount();

    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.getByText(/^Arm —/).closest('button')!).toBeEnabled();
  });
});

/* Phase G piece 5, build step 4 (§7.1, O4). Same treatment `stopMissing` gets,
 * one prop along — see the `methodPick` prop's own doc on AutoTradeArmProps
 * for why this control needed the check at all at the time step 4 added it,
 * before build step 5 (arming) wired the pick onto the request. Step 5 has
 * since wired it; the block below this one covers the payload half. */
describe('AutoTradeArm — refuses to arm a card with no method pick (spec test 9, O4)', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it('disables Arm and posts NOTHING when no methodPick is supplied', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" />);
    const arm = screen.getByText(/^Arm —/).closest('button')!;
    expect(arm).toBeDisabled();

    fireEvent.click(arm);
    await Promise.resolve();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('arms normally once a pick is supplied', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    const arm = screen.getByText(/^Arm —/).closest('button')!;
    expect(arm).toBeEnabled();

    fireEvent.click(arm);
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
  });
});

/* Phase G piece 5, BUILD STEP 5 (§8, arming) — the payload half of O4.
 *
 * Step 4 made this control REFUSE an unpicked card. Step 4 did not make it
 * SEND anything, and the send-path wiring gap closed at c41145ba is the
 * standing proof that those are two separate defects: seven other paths passed
 * their gate cleanly for a whole build step while writing `picked_method =
 * NULL` on every position they created. This block is the same check applied
 * to the eighth path before it can repeat it. */
describe('AutoTradeArm — carries the pick onto the arm request (spec test 6, §8)', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it('posts all five picked_* fields, snake_case, from the supplied pick', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.picked_method).toBe('monte_carlo');
    expect(payload.picked_row_stock_price).toBe(197.5);
    expect(payload.picked_row_option_price).toBe(6.24);
    expect(payload.picked_stop_basis).toBe('stock');
    expect(payload.picked_at).toBe('2026-09-14T10:00:00.000Z');
  });

  it('posts snake_case keys and NOT the portfolio path\'s camelCase ones', async () => {
    // THIS TEST IS THE ONLY GUARD, which is why it asserts the absence rather
    // than trusting the presence assertions above it. Sending camelCase here
    // fails SILENTLY at both ends: `ArmRequest` inherits pydantic's
    // `extra='ignore'` (measured — a camelCase body returns 200 and arms with
    // all five NULL), and on this side `tsc --noEmit` stays silent too, because
    // spreading the wrong mapping into an object literal bypasses TS's
    // excess-property check. `POST /api/portfolio` takes the camelCase
    // spelling, this endpoint does not, and one mapping serving both is how
    // that gets confused — into an armed trade whose pick was discarded.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload).not.toHaveProperty('pickedMethod');
    expect(payload).not.toHaveProperty('pickedRowStockPrice');
    expect(payload).not.toHaveProperty('pickedRowOptionPrice');
    expect(payload).not.toHaveProperty('pickedStopBasis');
    expect(payload).not.toHaveProperty('pickedAt');
  });

  it('puts the premium and the underlying in their own named slots', async () => {
    // THE UNITS TEST on this path. The two numbers are far apart on purpose:
    // only `picked_row_stock_price` may ever seed `resolved_tp_price`, and a
    // $6.24 premium landing there makes `price >= 6.24` true on the first tick.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.picked_row_stock_price).not.toBe(6.24);
    expect(payload.picked_row_option_price).not.toBe(197.5);
  });

  it('sends the row prices a barrier-race pick leaves null as null, not as 0', async () => {
    // A `?? 0` anywhere in the mapping would pass the `gt=0` bound as a 422
    // rather than as a stored zero — so this fails LOUDLY on the wire rather
    // than silently. It is still wrong here: null means "this method quotes no
    // level in that space", and 0 means a price of zero.
    const racePick: MethodPick = {
      method: 'barrier_race', rowStockPrice: null, rowOptionPrice: 7.1,
      stopBasis: 'premium', pickedAt: '2026-09-14T11:00:00.000Z',
    };
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={racePick} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.picked_method).toBe('barrier_race');
    expect(payload.picked_row_stock_price).toBeNull();
    expect(payload.picked_row_option_price).toBe(7.1);
  });
});

describe("the armed payload carries the CARD's direction", () => {
  /* THE ONE THING THIS WHOLE PIECE EXISTS TO GUARANTEE, and until now nothing
   * pinned it. The backend sizes off `direction`; if the browser never sends it,
   * or sends a constant, the fix is inert — and a missing field would be caught
   * only by `tsc`, and only until someone writes `card.direction ?? 'Bullish'`,
   * which typechecks and silently restores the exact defect: every bearish trade
   * sized off the bullish frame.
   *
   * Both directions are asserted on purpose. A single Bullish case would pass
   * against a hardcoded 'Bullish' literal, which is the failure mode worth
   * catching — the old code hardcoded `action: 'BUY'` and that is what made
   * `action` useless as a direction signal in the first place. */

  beforeEach(() => {
    // Same setup the sibling describes use: the Arm button only renders in
    // 'armed' auto-mode, and portfolioValue must be set or the exposure check
    // short-circuits before the payload is built.
    act(() => {
      useRiskStore.setState((st) => ({ limits: { ...st.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it.each([['Bullish'], ['Bearish']] as const)(
    'sends direction=%s when that is what the card says',
    async (direction) => {
      render(
        <AutoTradeArm {...BOOKING}
          card={{ ...mockCard, direction }}
          broker="ibkr_paper"
          methodPick={pick()}
        />,
      );
      fireEvent.click(screen.getByText(/^Arm —/));

      await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
      expect((api.armAutoTrade as jest.Mock).mock.calls[0][0].direction).toBe(direction);
    },
  );
});

describe('the ARMED state shows what the BACKEND has armed', () => {
  /* ROUND 1 finding 6 added `direction` to /auto-trade/status; ROUND 2 findings
   * 2, 3 and 4 are why this block was rewritten.
   *
   * The values rendered are the SERVER's. Echoing the card would redisplay what
   * this component sent, which cannot disagree with itself and so could never
   * catch a mis-arm. Symbol and direction must come from the SAME source: step-7
   * renders this component with no `key`, so CandidateNav swaps `card` without
   * remounting, and a server direction paired with a local `card.symbol` asserts
   * "Armed TSLA Bullish" for a trade armed on AAPL. */

  beforeEach(() => {
    act(() => {
      useRiskStore.setState((st) => ({ limits: { ...st.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({
        autoMode: 'armed', armed: false, armedDirection: null, armedSymbol: null, lastOrderId: null,
      });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it('renders the backend symbol AND direction, not the card it was rendered with', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValueOnce({
      armed: true, symbol: 'NVDA', option: null, broker: 'ibkr_paper',
      direction: 'Bearish', history_count: 0, last_order: null,
    });

    // Card disagrees on BOTH axes. Asserted as one exact string rather than a
    // regex with `.*` between the parts — the earlier version of this test used
    // /Armed .*Bearish.*/ and rendered "Armed AAPL Bearish" while passing,
    // which is the whole bug it was supposed to be guarding.
    render(
      <AutoTradeArm {...BOOKING} card={{ ...mockCard, symbol: 'AAPL', direction: 'Bullish' }}
                    broker="ibkr_paper" methodPick={pick()} />,
    );

    expect(await screen.findByText('Armed NVDA Bearish — waiting for next trigger')).toBeInTheDocument();
    expect(screen.queryByText(/Armed AAPL/)).not.toBeInTheDocument();
  });

  it.each([
    ['direction is null',   { armed: true, symbol: 'NVDA', direction: null }],
    ['direction is absent', { armed: true, symbol: 'NVDA' }],
    ['symbol is absent',    { armed: true, direction: 'Bearish' }],
  ])('falls back to the bare label when %s', async (_label, status) => {
    // The absent-key rows are the "backend predates the field" case the rollout
    // note contemplates — `undefined`, not null. Both names come from the
    // server or neither does, so a half-answer renders the bare label rather
    // than "Armed undefined Bearish".
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValueOnce(status);

    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);

    expect(await screen.findByText('Armed — waiting for next trigger')).toBeInTheDocument();
  });

  it('re-reads the backend after arming instead of trusting the card', async () => {
    /* ROUND 2 finding 4. The mount effect's deps are referentially-stable store
     * actions, so it runs once per mount and never re-reads. Without an explicit
     * refetch on the arm path, the label showed `card.direction` on exactly the
     * path that matters — the user having just armed — while the comments and
     * tests claimed it showed the backend's. */
    (api.getAutoTradeStatus as jest.Mock)
      .mockResolvedValueOnce({ armed: false })                                    // mount
      .mockResolvedValueOnce({ armed: true, symbol: 'NVDA', direction: 'Bearish' }); // after arm

    render(
      <AutoTradeArm {...BOOKING} card={{ ...mockCard, symbol: 'AAPL', direction: 'Bullish' }}
                    broker="ibkr_paper" methodPick={pick()} />,
    );
    fireEvent.click(await screen.findByText(/^Arm —/));

    // The server's values win over the optimistic card echo.
    expect(await screen.findByText('Armed NVDA Bearish — waiting for next trigger')).toBeInTheDocument();
  });

  it('does NOT let a status read issued before arming clobber the armed state', async () => {
    /* ROUND 2 finding 3, the most dangerous of the three: the operator sees an
     * "Arm" button and believes nothing is armed, while the backend is armed and
     * will fire on the next trigger. The old `active` flag guarded unmount only,
     * which is a different race entirely. */
    let releaseMountRead: (v: unknown) => void = () => {};
    const pendingMountRead = new Promise((resolve) => { releaseMountRead = resolve; });

    (api.getAutoTradeStatus as jest.Mock)
      .mockReturnValueOnce(pendingMountRead)                                       // mount: held open
      .mockResolvedValueOnce({ armed: true, symbol: 'AAPL', direction: 'Bullish' }); // post-arm

    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(await screen.findByText(/^Arm —/));
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());

    // Now the mount read lands, stale, insisting nothing is armed.
    await act(async () => {
      releaseMountRead({ armed: false, direction: null, symbol: null });
      await pendingMountRead;
    });

    expect(useAutoTradeStore.getState().armed).toBe(true);
    expect(screen.queryByText(/^Arm —/)).not.toBeInTheDocument();
  });
});

// ── The regime gate's inputs, frozen at arm ─────────────────────────────────
// AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19. The backend measures this
// symbol's OWN regime at fire time instead of reading a cached market-wide
// number, and it needs two things from the card to reproduce what the scan
// measured: the horizon (which window) and the Step-3 thresholds (which rule).
// The backend enforces `horizon`'s presence with a 422; what NOTHING but a test
// here enforces is that the frontend actually fills the pipe — the same gap
// piece 4 found, where `premium_stop_pct` existed end to end on the backend and
// no caller could set it.
describe('AutoTradeArm — regime gate inputs', () => {
  beforeEach(() => {
    act(() => {
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
      useScanStore.setState({ scanOverrides: {} });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
  });

  it.each([
    ['Intraday (0–2d)',     'Intraday'],
    ['Swing (5–15d)',       'Swing'],
    ['Position (15–45d)',   'Position'],
    // The long-dated presets all SCORE as Position — scoring_rules.yaml has no
    // `regime.quarterly` block, and the backend Literal would 422 the label.
    ['Position (90–105d)',  'Position'],
  ])('collapses the %s scan context to horizon=%s', async (contextHorizon, expected) => {
    act(() => {
      useScanStore.setState({
        context: {
          universe: 'SP500', direction: 'Bullish', horizon: contextHorizon,
          horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
        },
      });
    });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    expect((api.armAutoTrade as jest.Mock).mock.calls[0][0].horizon).toBe(expected);
  });

  it("sends the thresholds the CARD'S scan resolved, not the live Step-3 store", async () => {
    // Arm-door round 1, F1 -- the exact interleaving: the scan ran at the
    // YAML -40, then Step 3 was edited WITHOUT re-scanning (context untouched,
    // so the card survives), then Arm. The trade must be judged by -40.
    act(() => {
      useScanStore.setState({
        scanOverrides: { regime_headwind_caution_pct: -25, regime_headwind_reject_pct: -80 },
      });
    });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.regime_headwind_caution_pct).toBe(-15);
    expect(payload.regime_headwind_reject_pct).toBe(-40);
  });

  it('is unaffected by a Step-3 reset to defaults after the scan', async () => {
    // The scan ran under a tightened -10 reject; 'Reset to defaults' empties
    // scanOverrides. The card still says -10, and -10 is what is sent.
    act(() => { useScanStore.setState({ scanOverrides: {} }); });
    const card = { ...mockCard, regimeGate: { headwindCautionPct: -5, headwindRejectPct: -10 } };
    render(<AutoTradeArm {...BOOKING} card={card} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.regime_headwind_caution_pct).toBe(-5);
    expect(payload.regime_headwind_reject_pct).toBe(-10);
  });

  it('omits a threshold the resolved block did not carry, so the backend reads its YAML', async () => {
    // undefined, not 0 and not null: omitted is what "the scan read the config
    // value" means on this endpoint, and 0 is a REAL threshold there.
    const card = { ...mockCard, regimeGate: { headwindCautionPct: null, headwindRejectPct: null } };
    render(<AutoTradeArm {...BOOKING} card={card} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.regime_headwind_caution_pct).toBeUndefined();
    expect(payload.regime_headwind_reject_pct).toBeUndefined();
  });

  it('sends a zero threshold rather than dropping it as falsy', async () => {
    // 0 sits inside the Step-3 control's own -100..0 range and means "cap on
    // any headwind at all". A truthiness test anywhere along this path would
    // silently substitute the YAML -40 — 40 points looser than asked for.
    const card = { ...mockCard, regimeGate: { headwindCautionPct: 0, headwindRejectPct: 0 } };
    render(<AutoTradeArm {...BOOKING} card={card} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.regime_headwind_caution_pct).toBe(0);
    expect(payload.regime_headwind_reject_pct).toBe(0);
  });

  it.each([
    ['absent', undefined],
    ['null',   null],
  ])('refuses to arm a card whose regimeGate is %s, and says why', (_label, gate) => {
    // A card from before the snapshot existed. Falling back to the live
    // Step-3 store would re-open F1, so the button is disabled instead --
    // even with Step 3 holding values that LOOK plausible.
    act(() => {
      useScanStore.setState({
        scanOverrides: { regime_headwind_caution_pct: -25, regime_headwind_reject_pct: -80 },
      });
    });
    const card = { ...mockCard, regimeGate: gate } as TradeCardData;
    render(<AutoTradeArm {...BOOKING} card={card} broker="ibkr_paper" methodPick={pick()} />);
    const btn = screen.getByText(/^Arm —/).closest('button')!;
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', MISSING_REGIME_GATE_SNAPSHOT_TITLE);
    expect(screen.getAllByText(MISSING_REGIME_GATE_SNAPSHOT_TITLE).length).toBeGreaterThan(0);
    fireEvent.click(btn);
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });
});


// ── O4 step 6 ─────────────────────────────────────────────────────────────
describe('AutoTradeArm — O4 step 6: the arm carries the booking fields', () => {
  beforeEach(() => {
    act(() => {
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
      usePortfolioStore.setState({ positions: [] });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  });

  async function armedPayload() {
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    return (api.armAutoTrade as jest.Mock).mock.calls[0][0];
  }

  it('7. posts the ten, with `stop` = resolvedInvalidation when given', async () => {
    render(
      <AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()}
        resolvedInvalidation={176.5} structuralStop={175} premiumStopDollar={1.0}
        exitPlan={{ method: 'x' } as never} maxLossOverride={{ maxLoss: 300 } as never} />,
    );
    fireEvent.click(screen.getByText(/^Arm —/));
    const p = await armedPayload();
    expect(p.stop).toBe(176.5);
    expect(p.stop_is_user_set).toBe(false);
    expect(p.scan_stock_price).toBe(185.2);
    expect(p.structural_stop).toBe(175);
    expect(p.exit_plan).toEqual({ method: 'x' });
    expect(p.targets).toEqual(mockCard.exit.targets);
    expect(p.dte_total).toBe(24);
    expect(p.premium_stop_dollar).toBe(1.0);
    expect(p.max_loss_override).toEqual({ maxLoss: 300 });
    expect(p.trade_card_snapshot).toEqual(expect.objectContaining({ strike: 190, stockScore: 82 }));
  });

  it('7b. `stop` falls back to the card\'s own invalidation — the value the gate read', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    expect((await armedPayload()).stop).toBe(179.64);
  });

  it('8. posts option_symbol = the optionSymbol prop, not card.contract', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    const p = await armedPayload();
    expect(p.option_symbol).toBe('AAPL|190|2026-05-15|C');
    expect(p.option_symbol).not.toBe(mockCard.contract);
  });

  it('9. posts stop_is_user_set: true when the stop was typed', async () => {
    render(<AutoTradeArm {...BOOKING} stopIsUserSet card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    expect((await armedPayload()).stop_is_user_set).toBe(true);
  });
});

describe('AutoTradeArm — O4 step 6: arming a contract already held warns, does not block', () => {
  const held = (contract: string): PortfolioPosition =>
    ({ symbol: 'AAPL', contract, contracts: 3, entryPrice: 2.4, recId: 'REC-1' } as PortfolioPosition);

  beforeEach(() => {
    act(() => {
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  });
  afterEach(() => { act(() => { usePortfolioStore.setState({ positions: [] }); }); });

  it('10a. shows the held size and entry, and does not arm until "Arm anyway"', async () => {
    act(() => { usePortfolioStore.setState({ positions: [held(BOOKING.optionSymbol)] }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(`You already hold ${BOOKING.optionSymbol}`)).toBeInTheDocument();
    expect(screen.getByText(/3 contracts at \$2\.40/)).toBeInTheDocument();
    expect(api.armAutoTrade).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Arm anyway' }));
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('10b. Cancel arms nothing', async () => {
    act(() => { usePortfolioStore.setState({ positions: [held(BOOKING.optionSymbol)] }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('10c. a position on a DIFFERENT contract shows no dialog', async () => {
    act(() => { usePortfolioStore.setState({ positions: [held('AAPL|195|2026-05-15|C')] }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('10d. the warning does not survive a switch to another contract', async () => {
    act(() => { usePortfolioStore.setState({ positions: [held(BOOKING.optionSymbol)] }); });
    const { rerender } = render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    rerender(<AutoTradeArm {...BOOKING} optionSymbol="AAPL|195|2026-05-15|C" card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });
});

describe('AutoTradeArm — O4 step 6: reading the /fire result', () => {
  const sync = jest.fn().mockResolvedValue(true);
  let realSync: ReturnType<typeof usePortfolioStore.getState>['syncFromBackend'];

  beforeEach(() => {
    realSync = usePortfolioStore.getState().syncFromBackend;
    sync.mockClear();
    act(() => {
      usePortfolioStore.setState({ syncFromBackend: sync });
      useAutoTradeStore.setState({ autoMode: 'armed', armed: true, lastOrderId: null });
    });
    (api.getAutoTradeStatus as jest.Mock).mockClear();
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAPL', direction: 'Bullish' });
  });
  afterEach(() => {
    act(() => { usePortfolioStore.setState({ syncFromBackend: realSync }); });
    (api.fireAutoTrade as jest.Mock).mockReset();
    (api.fireAutoTrade as jest.Mock).mockResolvedValue({ order_id: 'ORD-1' });
  });

  async function fire(res: unknown, reject = false) {
    if (reject) (api.fireAutoTrade as jest.Mock).mockRejectedValueOnce(res);
    else (api.fireAutoTrade as jest.Mock).mockResolvedValueOnce(res);
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Fire now' }));
    await waitFor(() => expect(api.fireAutoTrade).toHaveBeenCalled());
  }

  it('11. booked === false renders a caution naming the reason, and does not sync', async () => {
    await fire({ order_id: '888', status: 'ok', broker: 'ibkr_paper', booked: false, rec_id: null,
                 book_error: 'no invalidation was armed', over_exposure: false });
    expect(await screen.findByText(/No position was recorded for this fire: no invalidation was armed/)).toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  it('12. booked === true syncs the portfolio once, with no caution', async () => {
    await fire({ order_id: '888', status: 'ok', broker: 'ibkr_paper', booked: true, rec_id: 'REC-AT-1',
                 book_error: null, over_exposure: false });
    await waitFor(() => expect(sync).toHaveBeenCalledTimes(1));
    expect(sync).toHaveBeenCalledWith(true);
    expect(screen.queryByText(/No position was recorded/)).not.toBeInTheDocument();
    expect(screen.queryByText(/past your exposure limit/)).not.toBeInTheDocument();
  });

  it('13. over_exposure renders a caution naming the booking, and still syncs', async () => {
    await fire({ order_id: '888', status: 'ok', broker: 'ibkr_paper', booked: true, rec_id: 'REC-AT-1',
                 book_error: null, over_exposure: true });
    expect(await screen.findByText(/Booked as REC-AT-1 at the ordered size, which is past your exposure limit/)).toBeInTheDocument();
    expect(sync).toHaveBeenCalledWith(true);
  });

  it('14. a pre-O4 response (no `booked` key) is neither "not booked" nor synced', async () => {
    await fire({ order_id: '1', status: 'ok' });
    expect(await screen.findByText(/Order ID: 1/)).toBeInTheDocument();
    expect(screen.queryByText(/No position was recorded/)).not.toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  it('15a. a transport failure is UNKNOWN: caution, status re-read, portfolio synced', async () => {
    await fire(new TypeError('Failed to fetch'), true);
    expect(await screen.findByText(/may or may not have been placed/)).toBeInTheDocument();
    await waitFor(() => expect(sync).toHaveBeenCalledWith(true));
    // Once on mount, once after the unknown.
    await waitFor(() => expect(api.getAutoTradeStatus).toHaveBeenCalledTimes(2));
  });

  it('15b. a 400 "Order failed:" is UNKNOWN too — the broker call was made', async () => {
    await fire(new Error('API /auto-trade/fire → 400: Order failed: read timeout'), true);
    expect(await screen.findByText(/may or may not have been placed/)).toBeInTheDocument();
  });

  it('15c. a plain 400 refusal renders red as before and does not sync', async () => {
    await fire(new Error('API /auto-trade/fire → 400: AutoTrader not armed — cannot fire'), true);
    expect(await screen.findByText(/AutoTrader not armed/)).toBeInTheDocument();
    expect(screen.queryByText(/may or may not have been placed/)).not.toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  // open_questions[98] / A9: a refusal re-reads the backend's armed state.
  const ARMED = { armed: true, symbol: 'AAPL', direction: 'Bullish' };
  const REFUSED = new Error('API /auto-trade/fire → 400: Daily loss limit reached: 500 at risk vs limit 400');

  it('15d. a refusal after the disarm re-reads status and drops the armed banner', async () => {
    (api.getAutoTradeStatus as jest.Mock)
      .mockResolvedValueOnce(ARMED)              // mount
      .mockResolvedValueOnce({ armed: false });  // after the refusal
    await fire(REFUSED, true);
    await waitFor(() => expect(api.getAutoTradeStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Fire now' })).not.toBeInTheDocument());
    expect(screen.queryByText(/^Armed AAPL/)).not.toBeInTheDocument();
    expect(screen.getByText(/^Arm —/)).toBeInTheDocument();
    expect(screen.getByText(/Daily loss limit reached/)).toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  it('15e. a refusal that PRESERVED the arm keeps the armed banner', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue(ARMED);
    await fire(new Error('API /auto-trade/fire → 400: Market closed or AAPL halted — armed state preserved for retry'), true);
    await waitFor(() => expect(api.getAutoTradeStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('button', { name: 'Fire now' })).toBeInTheDocument();
    expect(screen.getByText(/Market closed or AAPL halted/)).toBeInTheDocument();
  });

  it('15f. a pre-fire status read landing AFTER the refusal read cannot re-arm the panel', async () => {
    let resolveMount: (v: unknown) => void = () => {};
    (api.getAutoTradeStatus as jest.Mock)
      .mockImplementationOnce(() => new Promise((r) => { resolveMount = r; }))  // mount, held
      .mockResolvedValueOnce({ armed: false });                                 // after the refusal
    await fire(REFUSED, true);
    await waitFor(() => expect(api.getAutoTradeStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText(/^Arm —/)).toBeInTheDocument());
    // The stale mount read now arrives with the pre-fire truth.
    await act(async () => { resolveMount(ARMED); });
    expect(screen.getByText(/^Arm —/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fire now' })).not.toBeInTheDocument();
  });

  it('15g. the same race on the UNKNOWN branch: a stale pre-fire read cannot re-arm the panel', async () => {
    let resolveMount: (v: unknown) => void = () => {};
    (api.getAutoTradeStatus as jest.Mock)
      .mockImplementationOnce(() => new Promise((r) => { resolveMount = r; }))  // mount, held
      .mockResolvedValueOnce({ armed: false });                                 // after the unknown
    await fire(new TypeError('Failed to fetch'), true);
    await waitFor(() => expect(api.getAutoTradeStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText(/^Arm —/)).toBeInTheDocument());
    await act(async () => { resolveMount(ARMED); });
    expect(screen.getByText(/^Arm —/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fire now' })).not.toBeInTheDocument();
  });
});

describe('AutoTradeArm — O4 step 6: the caution under the buttons', () => {
  it('16. no longer says an auto-trade fill is not tracked as a position', () => {
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.queryByText(/not tracked as a position/)).not.toBeInTheDocument();
    expect(screen.getByText(/booked as a position with the invalidation you typed/)).toBeInTheDocument();
  });
});

// ── P2-18 (plan 2026-09-25-p2-premium-stop-position-editing-plan.md) ────────
describe('AutoTradeArm — P2-18 premium-stop caution, unbooked fire, booking wording', () => {
  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
      useSettingsStore.setState({ premiumStopPct: 0.6 });
    });
  });

  it('(a) a dollar stop at or above today\'s premium explains what the booking will do', () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={3.0} liveMid={2.5} methodPick={pick()} />);
    expect(screen.getByText(
      "Your $3.00 premium stop is at or above today's $2.50 premium. If the fill is at or below $3.00, "
      + 'the booked position inherits the global stop (60%); above it, your $3.00 stop applies.',
    )).toBeInTheDocument();
  });

  it('(a) no caution below the premium, or with no typed stop', () => {
    const { unmount } = render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={2.5} methodPick={pick()} />);
    expect(screen.queryByText(/at or above today's/)).not.toBeInTheDocument();
    unmount();
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.queryByText(/at or above today's/)).not.toBeInTheDocument();
  });

  it('STOP-SEMANTICS (F3): a sub-cent stop at today\'s premium is WARNED, and Arm stays enabled', () => {
    // $0.02 on a $0.03 premium: the threshold is a few ulps under a cent.
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={0.02} liveMid={0.03} methodPick={pick()} />);
    expect(screen.getByText(
      "Your $0.02 premium stop leaves a threshold below $0.01 at today's $0.03 premium, so it could never fire. "
      + 'If it is still below $0.01 at the fill, the booked position inherits the global stop (60%).',
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Arm —/ })).toBeEnabled();
  });

  it('STOP-SEMANTICS (F3): no sub-cent warning for an ordinary stop', () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={2.5} methodPick={pick()} />);
    expect(screen.queryByText(/below \$0\.01/)).not.toBeInTheDocument();
  });

  it('(b) an unbooked fire shows the order id in caution, never "Auto-trade fired"', async () => {
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: true, lastOrderId: null }); });
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAPL', direction: 'Bullish' });
    (api.fireAutoTrade as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-9', booked: false, book_error: 'x' });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Fire now' }));
    expect(await screen.findByText(/Order sent — ID: ORD-9 \(not booked\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Auto-trade fired/)).not.toBeInTheDocument();
  });

  it('(c) the booking note names the invalidation rule book_fired_order applies', () => {
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.getByText(/the invalidation you typed, or the plan's invalidation moved with the stock price at booking/)).toBeInTheDocument();
    expect(screen.queryByText(/with the invalidation, premium stop and exit\s+plan this card had/)).not.toBeInTheDocument();
  });
});

/* Task 10c (Kenneth, 2026-10-03). An earnings-vetoed card used to HIDE this
 * whole component, which also hid Disarm for a strategy already armed. Now the
 * caller always renders it and passes `armBlockedReason`: Arm and Fire now are
 * refused on it, Disarm never is. */
describe('AutoTradeArm — armBlockedReason (earnings-vetoed card)', () => {
  const REASON = 'Earnings inside the reject window — no send';

  beforeEach(() => {
    act(() => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue: 73_000 } }));
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, lastOrderId: null });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
    (api.disarmAutoTrade as jest.Mock).mockClear();
    (api.fireAutoTrade as jest.Mock).mockClear();
    (api.getAutoTradeStatus as jest.Mock).mockReset().mockResolvedValue({ armed: false });
  });

  it('vetoed + unarmed: Arm is disabled, carries the reason, and posts nothing', async () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} armBlockedReason={REASON} />);
    const arm = screen.getByRole('button', { name: /^Arm —/ });
    expect(arm).toBeDisabled();
    expect(arm).toHaveAttribute('title', REASON);
    fireEvent.click(arm);
    await act(async () => { await Promise.resolve(); });
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('vetoed + armed on this card: Disarm stays enabled and works, Fire now is refused', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAPL', direction: 'Bullish' });
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: true, lastOrderId: null }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} armBlockedReason={REASON} />);

    const disarm = await screen.findByRole('button', { name: 'Disarm' });
    const fire = screen.getByRole('button', { name: 'Fire now' });
    await waitFor(() => expect(fire).toBeDisabled());
    expect(fire).toHaveAttribute('title', REASON);
    expect(disarm).toBeEnabled();

    fireEvent.click(fire);
    await act(async () => { await Promise.resolve(); });
    expect(api.fireAutoTrade).not.toHaveBeenCalled();

    fireEvent.click(disarm);
    await waitFor(() => expect(api.disarmAutoTrade).toHaveBeenCalledTimes(1));
  });

  it('vetoed card while ANOTHER symbol is armed: Fire now is not blocked by this card\'s veto', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'NVDA', direction: 'Bearish' });
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: true, lastOrderId: null }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} armBlockedReason={REASON} />);
    await screen.findByText(/Armed NVDA Bearish/);
    expect(screen.getByRole('button', { name: 'Fire now' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Disarm' })).toBeEnabled();
  });

  it('un-vetoed + unarmed: Arm is unchanged', () => {
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} armBlockedReason={null} />);
    const arm = screen.getByRole('button', { name: /^Arm —/ });
    expect(arm).toBeEnabled();
    expect(arm).not.toHaveAttribute('title');
  });

  it('un-vetoed + armed: Disarm and Fire now are unchanged', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: true, symbol: 'AAPL', direction: 'Bullish' });
    act(() => { useAutoTradeStore.setState({ autoMode: 'armed', armed: true, lastOrderId: null }); });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    const fire = await screen.findByRole('button', { name: 'Fire now' });
    expect(fire).toBeEnabled();
    expect(fire).not.toHaveAttribute('title');
    expect(screen.getByRole('button', { name: 'Disarm' })).toBeEnabled();
    fireEvent.click(fire);
    await waitFor(() => expect(api.fireAutoTrade).toHaveBeenCalledTimes(1));
  });
});


describe('AutoTradeArm — P0B B3: the actual scan hold travels on the arm', () => {
  let previousContext: ReturnType<typeof useScanStore.getState>['context'];

  beforeEach(() => {
    previousContext = useScanStore.getState().context;
    act(() => {
      useAutoTradeStore.setState({ autoMode: 'armed', armed: false, armedSymbol: null, lastOrderId: null });
      usePortfolioStore.setState({ positions: [] });
    });
    (api.armAutoTrade as jest.Mock).mockClear();
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValue({ armed: false });
  });

  afterEach(() => { act(() => { useScanStore.setState({ context: previousContext }); }); });

  it.each([
    ['Position (60–185d)', 'Custom', 60, 185, 185],
    ['Swing (5–15d)', 'Swing', 5, 15, 15],
    ['Position (60–185d)', 'Custom', 60.4, 184.6, 185],
    ['Position (60–185d)', 'Custom', 185, 60, 185],
  ] as const)('posts the sanitized context hold for %s / %s (%s–%s)', async (horizon, horizonPreset, holdMin, holdMax, expected) => {
    act(() => {
      useScanStore.setState({ context: { universe: 'SP500', direction: 'Bullish', horizon,
        horizonPreset, holdMin, holdMax } });
    });
    render(<AutoTradeArm {...BOOKING} card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));
    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalledTimes(1));
    expect((api.armAutoTrade as jest.Mock).mock.calls[0][0].hold_max_days).toBe(expected);
  });
});
