import { BEARISH_UNVALIDATED_MESSAGE } from '@/lib/unvalidated';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { sendStockSaveFirst, removeNoteRow } from '@/lib/stockDirectSend';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { STOCK_VALIDATION_UNAVAILABLE } from '@/lib/stockExecutionSession';
jest.mock('@/lib/api', () => ({ api: { postStockOrder: jest.fn(), deletePortfolioPosition: jest.fn().mockResolvedValue(undefined) } }));
const originalFetch = global.fetch;
beforeEach(() => {
  jest.clearAllMocks(); global.fetch = jest.fn();
  usePortfolioStore.setState({ positions: [], syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  useDirectSendNotesStore.setState({ notes: [] });
});
afterEach(() => { global.fetch = originalFetch; });
it.each(['Bullish', 'Bearish'] as const)('denies %s new orders even when hydrated fields claim permission or stale provenance', async direction => {
  (useScanStore.setState as (value: unknown) => void)({ stockValidation: { available: true, verdict: 'PASS', allowed: true, scanId: 'prior', strategy: 'other', direction: 'other' }, executionEligible: true });
  const addPosition = jest.fn();
  const outcome = await sendStockSaveFirst({ pos: buildPaperStockPosition('AAPL', 150, 30, direction), broker: 'ibkr_paper', orderType: 'LMT', limitPrice: 150, action: direction === 'Bullish' ? 'BUY' : 'SELL', addPosition, earningsVeto: false });
  expect(outcome).toEqual(direction === 'Bearish'
    ? { kind: 'not-placed', message: BEARISH_UNVALIDATED_MESSAGE }
    : { kind: 'refused', message: STOCK_VALIDATION_UNAVAILABLE });
  expect(global.fetch).not.toHaveBeenCalled();
  expect(api.postStockOrder).not.toHaveBeenCalled(); expect(addPosition).not.toHaveBeenCalled();
});
it('keeps existing unknown-order recovery/removal available with validation unavailable', async () => {
  const note = { recId: 'existing', kind: 'order-unknown', label: 'AAPL 30 sh', brokerLabel: 'IBKR Paper', orderId: 'prior-order', status: null, removing: false } as const;
  useDirectSendNotesStore.getState().addNote(note);
  await removeNoteRow(note, () => true);
  expect(api.deletePortfolioPosition).toHaveBeenCalledWith('existing');
  expect(useDirectSendNotesStore.getState().notes).toEqual([]);
  expect(api.postStockOrder).not.toHaveBeenCalled();
});
