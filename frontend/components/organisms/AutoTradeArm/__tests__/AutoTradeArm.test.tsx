import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { AutoTradeArm } from '@/components/organisms/AutoTradeArm';
import { useRiskStore } from '@/lib/riskStore';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';

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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" />);
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
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={1.0} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.entry_premium).toBe(2.5);
    expect(payload.premium_stop_pct).toBeCloseTo(0.40, 6);
  });

  it('omits the premium stop entirely when the card carries none, so the auto-trader inherits the global', async () => {
    // undefined, not null: ArmRequest.premium_stop_pct is Optional with a None
    // default, and omitting is what "inherit" means on that endpoint.
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.premium_stop_pct).toBeUndefined();
  });

  it('omits a stop at or above the whole premium rather than sending a fraction the schema rejects', async () => {
    // A total loss is unreachable-by-definition rather than a stop, and the
    // endpoint's bound is lt=1 — sending 1.0 would 422 the arm.
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" premiumStopDollar={2.5} />);
    fireEvent.click(screen.getByText(/^Arm —/));

    await waitFor(() => expect(api.armAutoTrade).toHaveBeenCalled());
    const payload = (api.armAutoTrade as jest.Mock).mock.calls[0][0];
    expect(payload.premium_stop_pct).toBeUndefined();
  });

  it('reflects an already-armed backend state after reload', async () => {
    (api.getAutoTradeStatus as jest.Mock).mockResolvedValueOnce({ armed: true });
    render(<AutoTradeArm card={mockCard} broker="ibkr_paper" />);

    await waitFor(() => expect(screen.getByText('Armed — waiting for next trigger')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Disarm' })).toBeInTheDocument();
  });
});
