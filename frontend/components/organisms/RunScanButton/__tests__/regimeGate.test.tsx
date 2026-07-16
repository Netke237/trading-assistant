import { render, screen, fireEvent } from '@testing-library/react';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    postScan: jest.fn(),
  },
}));

jest.mock('@/lib/stockScan', () => ({ runStockScan: jest.fn().mockResolvedValue(null) }));

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));

function resetStores(direction: 'Bullish' | 'Bearish' = 'Bullish') {
  useScanStore.setState({
    scanState: 'IDLE',
    scanAt: null,
    context: { direction, horizon: 'Swing (5–15d)' },
    scanResult: null,
    conflictedSymbols: [],
    screenerMode: 'options',
    activeStrategy: null,
    regime: 'REJECT',
    combinedRegime: 'REJECT',
  } as any);
  usePortfolioStore.setState({ positions: [] });
}

describe('RunScanButton — regime gate fires for both directions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows confirm dialog for Bullish scan when combinedRegime is REJECT', () => {
    resetStores('Bullish');
    render(<RunScanButton />);

    fireEvent.click(screen.getByRole('button', { name: /run scan/i }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getAllByText(/REJECT/).length).toBeGreaterThanOrEqual(1);
  });

  it('shows confirm dialog for Bearish scan when combinedRegime is REJECT', () => {
    resetStores('Bearish');
    render(<RunScanButton />);

    fireEvent.click(screen.getByRole('button', { name: /run scan/i }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getAllByText(/REJECT/).length).toBeGreaterThanOrEqual(1);
  });

  it('dialog body text reflects the current direction', () => {
    resetStores('Bearish');
    render(<RunScanButton />);

    fireEvent.click(screen.getByRole('button', { name: /run scan/i }));

    const body = screen.getByText(/carries elevated risk/i);
    expect(body.textContent).toMatch(/Bearish/);
  });

  it('does NOT show dialog when combinedRegime is PASS', () => {
    useScanStore.setState({
      scanState: 'IDLE',
      scanAt: null,
      context: { direction: 'Bearish', horizon: 'Swing (5–15d)' },
      scanResult: null,
      conflictedSymbols: [],
      screenerMode: 'options',
      activeStrategy: null,
      regime: 'PASS',
      combinedRegime: 'PASS',
    } as any);
    usePortfolioStore.setState({ positions: [] });

    (api.postScan as jest.Mock).mockResolvedValue({
      scan_id: 'SCAN-X',
      timestamp: '2026-06-17T10:00:00',
      candidates: [],
      rejected: [],
    });

    render(<RunScanButton />);
    fireEvent.click(screen.getByRole('button', { name: /run scan/i }));

    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
