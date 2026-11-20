import '@testing-library/jest-dom';
import { render, screen, within, fireEvent, act } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import type { ExitPlan, PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../../../test-utils/portfolioFixture20261117';

// PORTFOLIO-RISK-VIEW T4 (#682): stop-breach banner + "Risk at stops" footer.

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('../EditDrawer', () => ({ EditDrawer: () => <div data-testid="editor-open" /> }));
jest.mock('@/components/organisms/ClosePositionDrawer', () => ({
  ClosePositionDrawer: () => <div data-testid="close-open" />,
}));

const plan = (c: number) => ({ stop: { contractPrice: c } }) as unknown as ExitPlan;

function fixtures(): PortfolioPosition[] {
  const [cmg, nclh, bmy] = portfolio20261117();
  return [
    { ...cmg, stop: 33.35, structuralStop: 35.66, targets: [{ stockPrice: 40.71 } as never], exitPlan: plan(0.84) },
    { ...nclh, stop: 16.0, structuralStop: null, targets: [{ stockPrice: 21 } as never], exitPlan: plan(0.33) },
    { ...bmy, stop: 64.13, structuralStop: null, targets: [{ stockPrice: 70 } as never] },
  ];
}

function renderWith(positions: PortfolioPosition[]) {
  usePortfolioStore.setState({ positions, syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  });
  usePortfolioUiStore.setState({ selectedSymbol: null });
  return render(<PortfolioPage />);
}

const BMY_TEXT =
  'BMY 67C · 19 Mar 27: stop breached. Underlying $60.95 is below your stop $64.13 (−5.2%). ' +
  'The option has had no quote since the last sync, so its P&L and risk are unknown.';

describe('stop-breach banner', () => {
  it('BMY: exact sentence with the no-quote sentence, role alert, no dismiss button', () => {
    renderWith(fixtures());
    const banner = screen.getByText(BMY_TEXT).closest('[role="alert"]') as HTMLElement;
    expect(banner).not.toBeNull();
    expect(within(banner).queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument();
    // CMG (caution) and NCLH (pass) get no banner.
    expect(screen.getAllByText(/stop breached\./)).toHaveLength(1);
  });

  it('bearish breach: positive figure and "above"', () => {
    const [, nclh] = fixtures();
    renderWith([{ ...nclh, direction: 'Bearish', stop: 16.0 }]);
    expect(
      screen.getByText('NCLH 20C · 17 Jun 27: stop breached. Underlying $17.70 is above your stop $16.00 (+9.6%).'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no quote since the last sync/)).not.toBeInTheDocument();
  });

  it('structural variant names the structural stop', () => {
    const [cmg] = fixtures();
    renderWith([{ ...cmg, structuralStop: 37.0 }]);
    expect(
      screen.getByText(
        'CMG 40C · 17 Jun 27: structural stop breached. Underlying $36.06 is below your structural stop $37.00 (−2.6%).',
      ),
    ).toBeInTheDocument();
  });

  it('no banner without a breach', () => {
    const [cmg, nclh] = fixtures();
    renderWith([cmg, nclh]);
    expect(screen.queryByText(/stop breached\./)).not.toBeInTheDocument();
  });

  it('banner goes away when the breach no longer holds', () => {
    renderWith(fixtures());
    expect(screen.getByText(BMY_TEXT)).toBeInTheDocument();
    const bmy = fixtures()[2];
    act(() => { usePortfolioStore.setState({ positions: [{ ...bmy, currentStockPrice: 70 }] }); });
    expect(screen.queryByText(/stop breached\./)).not.toBeInTheDocument();
  });

  it('Review opens the editor, selects the symbol and shows the Open tab', () => {
    renderWith(fixtures());
    fireEvent.click(screen.getByText('History (0)'));
    fireEvent.click(screen.getByRole('button', { name: 'Review BMY' }));
    expect(screen.getByTestId('editor-open')).toBeInTheDocument();
    expect(usePortfolioUiStore.getState().selectedSymbol).toBe('BMY');
  });

  it('Close position… opens the close dialog', () => {
    renderWith(fixtures());
    expect(screen.queryByTestId('close-open')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close position…' }));
    expect(screen.getByTestId('close-open')).toBeInTheDocument();
  });
});

describe('footer Risk at stops', () => {
  it('fixtures: $414 and +1 unpriced', () => {
    renderWith(fixtures());
    const group = screen.getByText('Risk at stops').parentElement as HTMLElement;
    expect(group).toHaveTextContent('$414');
    expect(group).toHaveTextContent('+1 unpriced');
  });

  it('no unpriced note when every position is priced', () => {
    const [cmg, nclh] = fixtures();
    renderWith([cmg, nclh]);
    const group = screen.getByText('Risk at stops').parentElement as HTMLElement;
    expect(group).toHaveTextContent('$414');
    expect(screen.queryByText(/unpriced/)).not.toBeInTheDocument();
  });
});
