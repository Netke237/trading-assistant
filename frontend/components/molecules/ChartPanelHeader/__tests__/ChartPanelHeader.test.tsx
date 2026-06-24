import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { ChartPanelHeader } from '@/components/molecules/ChartPanelHeader';

jest.mock('@/components/atoms/WatchStar', () => ({
  WatchStar: ({ symbol }: { symbol: string }) => (
    <button aria-label={`Add ${symbol} to watchlist`} />
  ),
}));

jest.mock('@/components/atoms/IconButton', () => ({
  IconButton: ({
    children,
    onClick,
    ...rest
  }: React.HTMLAttributes<HTMLButtonElement>) => (
    <button onClick={onClick} {...rest}>{children}</button>
  ),
}));

describe('ChartPanelHeader', () => {
  it('renders the company name text', () => {
    render(
      <ChartPanelHeader
        symbol="MSFT"
        label="Microsoft Corp"
        onClose={() => {}}
      />
    );
    expect(screen.getByText('Microsoft Corp')).toBeInTheDocument();
  });

  it('renders the ticker symbol', () => {
    render(
      <ChartPanelHeader
        symbol="MSFT"
        label="Microsoft Corp"
        onClose={() => {}}
      />
    );
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('falls back to "Chart" when label prop is omitted', () => {
    render(<ChartPanelHeader symbol="AAPL" onClose={() => {}} />);
    expect(screen.getByText('Chart')).toBeInTheDocument();
  });
});
