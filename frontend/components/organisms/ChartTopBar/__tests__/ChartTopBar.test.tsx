import '@testing-library/jest-dom';
import { render, screen, act } from '@testing-library/react';
import ChartTopBar from '@/components/organisms/ChartTopBar';
import { useChartStore } from '@/lib/chartStore';

jest.mock('@/components/atoms/WatchStar', () => ({
  WatchStar: ({ symbol }: { symbol: string }) => (
    <button data-testid="watch-star" aria-label={`Add ${symbol} to watchlist`} />
  ),
}));

jest.mock('@/lib/api', () => ({
  api: {
    getSymbolInfo: jest.fn().mockResolvedValue({ symbol: 'AAPL', name: 'Apple Inc.' }),
  },
}));

beforeEach(() => {
  useChartStore.setState({
    symbol: 'AAPL',
    symbolName: 'Apple Inc.',
    interval: '1D',
    chartType: 'candle',
  } as any);
});

describe('ChartTopBar', () => {
  const noop = () => {};

  it('renders WatchStar for the active symbol', async () => {
    await act(async () => {
      render(<ChartTopBar onToggleIndicators={noop} onToggleStructure={noop} />);
    });
    const star = screen.getByTestId('watch-star');
    expect(star).toBeInTheDocument();
    expect(star).toHaveAttribute('aria-label', 'Add AAPL to watchlist');
  });

  it('renders WatchStar before the symbol input in the DOM', async () => {
    await act(async () => {
      render(<ChartTopBar onToggleIndicators={noop} onToggleStructure={noop} />);
    });
    const input = screen.getByRole('textbox', { name: 'Symbol' });
    const bar = input.parentElement!;
    const children = Array.from(bar.children);
    const starIdx  = children.findIndex(
      (el) => el.getAttribute('data-testid') === 'watch-star',
    );
    const inputIdx = children.indexOf(input);
    expect(starIdx).toBeGreaterThanOrEqual(0);
    expect(inputIdx).toBeGreaterThanOrEqual(0);
    expect(starIdx).toBeLessThan(inputIdx);
  });
});
