import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import { RiskPanel } from '.';
import { useRiskStore } from '@/lib/riskStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PortfolioPosition } from '@/types/domain';

/* STOCK-SENDS (plan C3): the dashboard shows options and stocks each against
 * their own caps, from riskStore.computeMetrics (the panel's own source). */

const pos = (symbol: string, contract: string, currentPrice: number, contracts: number): PortfolioPosition => ({
  symbol, contract, direction: 'Bullish', entryDate: '2026-09-01', expiry: '', dteRemaining: 0, dteTotal: 0,
  entryPrice: currentPrice, currentPrice, pnlDollar: 0, pnlPct: 0, stop: null, targets: [], status: 'PASS',
  contracts, recId: `R-${symbol}`,
} as PortfolioPosition);

beforeEach(() => {
  act(() => {
    useRiskStore.setState({
      limits: {
        maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25, maxConcurrentPositions: 10,
        maxDailyRecommendations: 5, portfolioValue: 100_000, maxLossPerTradePct: 0.0375,
        maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
      },
      dailyRecommendations: 0,
    });
  });
});

it('a $60k stock row alone: option exposure stays 0 and PASS; the stock bands carry it', () => {
  act(() => { usePortfolioStore.setState({ positions: [pos('AAPL', 'AAPL|STOCK', 200, 300)] }); });
  render(<RiskPanel />);
  const m = useRiskStore.getState().metrics;
  expect(m.totalExposurePct).toBe(0);
  expect(m.stockExposurePct).toBeCloseTo(0.6);
  expect(m.largestStockConcentrationSymbol).toBe('AAPL');
  expect(screen.getByText('Option exposure').nextSibling).toHaveTextContent('0.0%');
  expect(screen.getByText('Stock exposure').nextSibling).toHaveTextContent('60.0%');
  expect(screen.getByText('Largest stock').nextSibling).toHaveTextContent('60.0% AAPL');
  // 60% single stock > the 20% stock cap -> the badge is REJECT, from the stock band.
  expect(m.status).toBe('REJECT');
});

it('an $18k stock row is inside the stock caps and does not move the option bands', () => {
  act(() => {
    usePortfolioStore.setState({ positions: [
      pos('AAPL', 'AAPL|STOCK', 200, 90),            // $18,000 = 18% (stock)
      pos('MSFT', 'MSFT|300|2026-12-18|C', 10, 2),   // $2,000 = 2% (option)
    ] });
  });
  render(<RiskPanel />);
  const m = useRiskStore.getState().metrics;
  expect(m.totalExposurePct).toBeCloseTo(0.02);
  expect(m.largestConcentrationSymbol).toBe('MSFT');
  expect(m.stockExposurePct).toBeCloseTo(0.18);
  expect(m.status).toBe('CAUTION'); // 18% is above 80% of the 20% stock single cap
});
