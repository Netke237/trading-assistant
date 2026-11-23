import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => <div data-testid="chart" /> }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => <div data-testid="heatmap" /> }));
jest.mock('@/components/organisms/BrokerAttemptPanel', () => ({ BrokerAttemptPanel: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

beforeEach(() => {
  usePortfolioStore.setState({
    positions: [], syncFromBackend: jest.fn().mockResolvedValue(undefined),
    lastSyncAt: 1, lastSyncFailedAt: null, firstSyncAt: 1,
  } as never);
  usePerformanceStore.setState({
    history: [],
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  } as never);
});

const open = () => screen.getByRole('tab', { name: 'Open (0)' });
const hist = () => screen.getByRole('tab', { name: 'History (0)' });

describe('Portfolio tabs accessibility', () => {
  it('exposes a labelled tablist with two tabs and a tabpanel labelled by the selected tab', () => {
    render(<PortfolioPage />);
    expect(screen.getByRole('tablist', { name: 'Portfolio views' })).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveAttribute('id', 'portfolio-panel-open');
    expect(panel).toHaveAttribute('aria-labelledby', 'portfolio-tab-open');
    expect(open()).toHaveAttribute('aria-controls', 'portfolio-panel-open');
  });

  it('aria-selected and roving tabIndex follow the selection', () => {
    render(<PortfolioPage />);
    expect(open()).toHaveAttribute('aria-selected', 'true');
    expect(hist()).toHaveAttribute('aria-selected', 'false');
    expect(open()).toHaveAttribute('tabindex', '0');
    expect(hist()).toHaveAttribute('tabindex', '-1');
    fireEvent.click(hist());
    expect(hist()).toHaveAttribute('aria-selected', 'true');
    expect(open()).toHaveAttribute('aria-selected', 'false');
    expect(hist()).toHaveAttribute('tabindex', '0');
    expect(open()).toHaveAttribute('tabindex', '-1');
  });

  it('history content lives in the history panel', () => {
    render(<PortfolioPage />);
    fireEvent.click(hist());
    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveAttribute('id', 'portfolio-panel-history');
    expect(panel).toHaveAttribute('aria-labelledby', 'portfolio-tab-history');
    expect(panel).toContainElement(screen.getByTestId('heatmap'));
    expect(panel).toHaveTextContent('No closed trades yet.');
  });

  it('ArrowRight / ArrowLeft switch tabs with wrap-around and focus follows', () => {
    render(<PortfolioPage />);
    open().focus();
    fireEvent.keyDown(open(), { key: 'ArrowRight' });
    expect(hist()).toHaveAttribute('aria-selected', 'true');
    expect(hist()).toHaveFocus();
    fireEvent.keyDown(hist(), { key: 'ArrowRight' });
    expect(open()).toHaveAttribute('aria-selected', 'true');
    expect(open()).toHaveFocus();
    fireEvent.keyDown(open(), { key: 'ArrowLeft' });
    expect(hist()).toHaveAttribute('aria-selected', 'true');
    expect(hist()).toHaveFocus();
  });

  it('Home and End select the first and last tab', () => {
    render(<PortfolioPage />);
    fireEvent.keyDown(open(), { key: 'End' });
    expect(hist()).toHaveAttribute('aria-selected', 'true');
    expect(hist()).toHaveFocus();
    fireEvent.keyDown(hist(), { key: 'Home' });
    expect(open()).toHaveAttribute('aria-selected', 'true');
    expect(open()).toHaveFocus();
  });

  it('Enter selects a focused tab (native button activation)', () => {
    render(<PortfolioPage />);
    // jsdom does not synthesize click from Enter/Space; the tab is a real
    // <button>, so the browser does. Pin the element type that guarantees it.
    expect(hist().tagName).toBe('BUTTON');
    expect(hist()).toHaveAttribute('type', 'button');
  });
});
