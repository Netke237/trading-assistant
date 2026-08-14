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
});
