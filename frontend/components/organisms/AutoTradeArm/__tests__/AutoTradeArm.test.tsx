import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { AutoTradeArm } from '@/components/organisms/AutoTradeArm';
import { useRiskStore } from '@/lib/riskStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.entry_premium).toBe(2.5);
    expect(payload.premium_stop_pct).toBeCloseTo(0.40, 6);
  });

  it('omits the premium stop entirely when the card carries none, so the auto-trader inherits the global', async () => {
    // undefined, not null: ArmRequest.premium_stop_pct is Optional with a None
    // default, and omitting is what "inherit" means on that endpoint.
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.premium_stop_pct).toBeUndefined();
  });

  it('omits a stop at or above the whole premium rather than sending a fraction the schema rejects', async () => {
    // A total loss is unreachable-by-definition rather than a stop, and the
    // endpoint's bound is lt=1 — sending 1.0 would 422 the arm.
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={2.5} methodPick={pick()} />);
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
    // `entry_premium * quantity * 100 * stop_pct` off it.
    //
    // Scanned at $2.50, reopened at $6.00, with a $1.00 dollar stop:
    //   stale -> entry 2.50, pct 0.400  (gate books 2.4x too little risk)
    //   live  -> entry 6.00, pct 0.1667
    render(
      <AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={6.0} methodPick={pick()} />,
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
      <AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} liveMid={null} methodPick={pick()} />,
    );
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    expect((api.armAutoTrade as jest.Mock).mock.calls[0][0].entry_premium).toBe(2.5);
  });

  it('reflects an already-armed backend state after reload', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValueOnce({ armed: true });
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);

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
    render(<AutoTradeArm card={noStopCard} broker="ibkr_paper" resolvedInvalidation={null} methodPick={pick()} />);
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
    render(<AutoTradeArm card={noStopCard} broker="ibkr_paper" resolvedInvalidation={185} methodPick={pick()} />);
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
    const { unmount } = render(<AutoTradeArm card={noStopCard} broker="ibkr_paper" methodPick={pick()} />);
    expect(screen.getByText(/^Arm —/).closest('button')!).toBeDisabled();
    unmount();

    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" />);
    const arm = screen.getByText(/^Arm —/).closest('button')!;
    expect(arm).toBeDisabled();

    fireEvent.click(arm);
    await Promise.resolve();
    expect(api.armAutoTrade).not.toHaveBeenCalled();
  });

  it('arms normally once a pick is supplied', async () => {
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    // `ArmRequest` has no aliases and `ArmedStrategy(**req.model_dump())` keys
    // off its field NAMES, so `pickedMethod` would not be quietly ignored the
    // way an extra key usually is — it would raise TypeError at the dataclass.
    // `POST /api/portfolio` takes the camelCase spelling, this endpoint does
    // not, and one mapping serving both is how that gets confused.
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={pick()} />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" methodPick={racePick} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.picked_method).toBe('barrier_race');
    expect(payload.picked_row_stock_price).toBeNull();
    expect(payload.picked_row_option_price).toBe(7.1);
  });
});
