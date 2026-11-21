import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import PortfolioContextRail from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import type { ExitPlan, PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../../../../test-utils/portfolioFixture20261117';

// PORTFOLIO-RISK-VIEW T4 (#682): rail Totals "Risk at stops".

jest.mock('@/lib/api', () => ({
  api: {
    getSymbolNote: jest.fn().mockResolvedValue({ symbol: 'X', body: '', updatedAt: null }),
    putSymbolNote: jest.fn().mockResolvedValue({ symbol: 'X', body: '', updatedAt: null }),
  },
}));
jest.mock('@/components/organisms/ContextRail/QuickLook', () => ({ RailQuickLook: () => null }));

const plan = (c: number) => ({ stop: { contractPrice: c } }) as unknown as ExitPlan;

function fixtures(): PortfolioPosition[] {
  const [cmg, nclh, bmy] = portfolio20261117();
  return [{ ...cmg, exitPlan: plan(0.84) }, { ...nclh, exitPlan: plan(0.33) }, bmy];
}

describe('rail Risk at stops', () => {
  beforeEach(() => usePortfolioUiStore.setState({ selectedSymbol: null }));

  it('shows $414 and +1 unpriced', () => {
    usePortfolioStore.setState({ positions: fixtures() });
    render(<PortfolioContextRail />);
    const row = screen.getByText('Risk at stops').parentElement!.parentElement as HTMLElement;
    expect(row).toHaveTextContent('$414');
    expect(row).toHaveTextContent('+1 unpriced');
  });

  it('no unpriced note when all priced', () => {
    usePortfolioStore.setState({ positions: fixtures().slice(0, 2) });
    render(<PortfolioContextRail />);
    expect(screen.getByText('Risk at stops').parentElement).toHaveTextContent('$414');
    expect(screen.queryByText(/unpriced/)).not.toBeInTheDocument();
  });
});
