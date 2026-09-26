import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { api } from '@/lib/api';

/*
 * STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES — plan B5 test 13. The notes are a
 * shared, module-level store, so a note left by ANY save-first send (an
 * options Step-7 send here) is visible on the stock page that hosts the card
 * and the send dialog, and its Remove works there: confirm, then DELETE that
 * note's own rec_id.
 */

jest.mock('@/lib/api', () => ({
  api: { deletePortfolioPosition: jest.fn().mockResolvedValue(undefined) },
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScan: jest.fn(),
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/StrategyParamsPanel', () => ({ StrategyParamsPanel: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

const originalFetch = global.fetch;

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = jest.fn(async () => ({ ok: true, status: 200, json: async () => [] })) as unknown as typeof fetch;
  act(() => {
    useScanStore.setState({
      context: { direction: 'Bullish', universe: 'SP500' } as never,
      activeStrategy: 'pullback_ema',
      stockScanResult: null,
      stockBasket: [],
      stockScanError: null,
    } as never);
    useDirectSendNotesStore.setState({ notes: [] });
    useDirectSendNotesStore.getState().addNote({
      recId: 'REC-OPT', kind: 'order-unknown', label: 'AAPL 185C 09/18',
      brokerLabel: 'Tradier Paper', orderId: null,
    });
  });
});
afterEach(() => { global.fetch = originalFetch; });

it('13. shows a note from an options send and its Remove deletes that rec_id', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
  render(<Step4StocksPage />);

  expect(screen.getByText(/AAPL 185C 09\/18: order status UNKNOWN/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Remove (AAPL 185C 09/18)' }));

  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('ONLY if Tradier Paper'));
  await waitFor(() => expect(api.deletePortfolioPosition).toHaveBeenCalledWith('REC-OPT'));
  await waitFor(() => expect(useDirectSendNotesStore.getState().notes).toHaveLength(0));
  confirm.mockRestore();
});
