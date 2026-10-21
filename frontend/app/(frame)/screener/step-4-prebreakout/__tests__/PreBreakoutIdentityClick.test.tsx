import { act, fireEvent, render, screen } from '@testing-library/react';
import Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';

jest.mock('@/lib/api', () => ({
  api: {
    getCandles: jest.fn(),
    prebreakoutScan: jest.fn(),
    fibPullbackScan: jest.fn(),
    postStockScan: jest.fn(),
    addWatchlist: jest.fn(),
    removeWatchlist: jest.fn(),
    getCompositeWatchDefaults: jest.fn(),
    getSymbolRegimeSnapshot: jest.fn(),
    addCompositeWatch: jest.fn(),
    addCompositeAlertRule: jest.fn(),
  },
}));
jest.mock('@/components/organisms/SavedScanReportInspector', () => ({ SavedScanReportInspector: () => null }));
jest.mock('@/components/organisms/CandlestickChart', () => ({
  CandlestickChart: () => <div data-testid="candles" />,
}));
jest.mock('@/components/organisms/CompositeAlertDialog', () => ({
  CompositeAlertDialog: () => null,
}));

const preRow = (symbol: string) => ({
  symbol,
  direction: 'Bullish',
  confidence: 85,
  metrics: { atr_ratio: 0.6, vol_ratio: 0.7, proximity_pct: 1.2 },
});

const fibRow = (symbol: string) => ({
  symbol,
  direction: 'Bullish',
  confidence: 80,
  fib_level_hit: '38.2',
  fib_dist_pct: 0.4,
  at_level: true,
  fib_swing: { low: 100, high: 200 },
});

const pullRow = (symbol: string) => ({
  symbol,
  direction: 'Bullish',
  stock_score: 75,
  price: 150.0,
  confidence: 82,
});

describe('Pre-Breakout identity cell selection clicks (#364)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useUniverseStore.setState({ pick: 'SP500' });
    useWatchlistStore.setState({ added: [] });
    useScanStore.setState({
      context: { direction: 'Bullish', horizon: 'Swing' } as never,
      preBreakoutResults: [preRow('PRE1'), preRow('PRE2')],
      fibPullbackResults: [fibRow('FIB1'), fibRow('FIB2')],
    });
    (api.getCandles as jest.Mock).mockResolvedValue([
      { time: '2026-10-01', open: 100, high: 105, low: 95, close: 100, volume: 1000 },
    ]);
    (api.postStockScan as jest.Mock).mockResolvedValue({
      candidates: [pullRow('PULL1'), pullRow('PULL2')],
    });
    (api.addWatchlist as jest.Mock).mockResolvedValue(undefined);
    (api.removeWatchlist as jest.Mock).mockResolvedValue(undefined);
    window.open = jest.fn();
  });

  describe('Pullback mode', () => {
    it('clicking identity-cell whitespace selects candidate row', async () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Pullback to EMA 50' }));
      await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' })));

      const pull1Row = screen.getByRole('button', { name: 'Select PULL1' });
      expect(pull1Row).toHaveAttribute('aria-pressed', 'false');

      // Click directly on the identity cell container (whitespace outside buttons and text)
      const identityCell = screen.getByLabelText('Identity for PULL1');
      fireEvent.click(identityCell);

      expect(pull1Row).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByLabelText('Selected setup')).toHaveTextContent('PULL1');
    });

    it('clicking WatchStar toggles watch without selecting the candidate', async () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Pullback to EMA 50' }));
      await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' })));

      const pull1Row = screen.getByRole('button', { name: 'Select PULL1' });
      const star = screen.getByRole('button', { name: /Add PULL1 to watchlist/i });

      fireEvent.click(star);
      expect(pull1Row).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByLabelText('Selected setup')).toHaveTextContent('Select a candidate');
    });

    it('clicking chart button opens chart tab without selecting the candidate', async () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Pullback to EMA 50' }));
      await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' })));

      const pull1Row = screen.getByRole('button', { name: 'Select PULL1' });
      const chartBtn = screen.getByRole('button', { name: 'Open PULL1 chart in a new tab' });

      fireEvent.click(chartBtn);
      expect(window.open).toHaveBeenCalled();
      expect(pull1Row).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByLabelText('Selected setup')).toHaveTextContent('Select a candidate');
    });

    it('clicking alert button opens alert target without selecting the candidate', async () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Pullback to EMA 50' }));
      await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' })));

      const pull1Row = screen.getByRole('button', { name: 'Select PULL1' });
      const alertBtns = screen.getAllByRole('button', { name: 'Alert' });

      fireEvent.click(alertBtns[0]);
      expect(pull1Row).toHaveAttribute('aria-pressed', 'false');
    });
  });

  describe('Pre-Breakout mode', () => {
    it('clicking identity-cell whitespace selects candidate row', () => {
      render(<Page />);
      const pre1Row = screen.getByRole('button', { name: 'Select PRE1' });
      expect(pre1Row).toHaveAttribute('aria-pressed', 'false');

      const identityCell = screen.getByLabelText('Identity for PRE1');
      fireEvent.click(identityCell);

      expect(pre1Row).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByLabelText('Selected setup')).toHaveTextContent('PRE1');
    });

    it('clicking chart button on PRE row opens chart without selecting', () => {
      render(<Page />);
      const pre1Row = screen.getByRole('button', { name: 'Select PRE1' });
      const chartBtn = screen.getByRole('button', { name: 'Open PRE1 chart in a new tab' });

      fireEvent.click(chartBtn);
      expect(window.open).toHaveBeenCalled();
      expect(pre1Row).toHaveAttribute('aria-pressed', 'false');
    });
  });

  describe('Fib Pullback mode', () => {
    it('clicking identity-cell whitespace selects candidate row', () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Fib Pullback' }));

      const fib1Row = screen.getByRole('button', { name: 'Select FIB1' });
      expect(fib1Row).toHaveAttribute('aria-pressed', 'false');

      const identityCell = screen.getByLabelText('Identity for FIB1');
      fireEvent.click(identityCell);

      expect(fib1Row).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByLabelText('Selected setup')).toHaveTextContent('FIB1');
    });

    it('clicking WatchStar on FIB row does not select', () => {
      render(<Page />);
      fireEvent.click(screen.getByRole('button', { name: 'Fib Pullback' }));

      const fib1Row = screen.getByRole('button', { name: 'Select FIB1' });
      const star = screen.getByRole('button', { name: /Add FIB1 to watchlist/i });

      fireEvent.click(star);
      expect(fib1Row).toHaveAttribute('aria-pressed', 'false');
    });
  });
});
