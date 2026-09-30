import { useScanStore } from '../scanStore';

// P6 (G2-12). zustand v5's persist has no try/catch around storage.setItem, so
// a QuotaExceededError used to throw out of EVERY set() on this store --
// including setCardEdit inside a React event handler. The storage adapter now
// catches it; the in-memory update still lands and the previous blob is kept.

describe('scanStore storage: a full localStorage does not throw out of set()', () => {
  let setItem: jest.SpyInstance;
  let warn: jest.SpyInstance;

  beforeEach(() => {
    setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError');
    });
    warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    setItem.mockRestore();
    warn.mockRestore();
  });

  it('setCardEdit applies in memory and warns instead of throwing', () => {
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-q', timestamp: '2026-09-30T09:00:00Z' } as never,
    });
    const pick = {
      method: 'ladder' as const, rowStockPrice: 160, rowOptionPrice: null,
      stopBasis: 'stock' as const, pickedAt: '2026-09-30T09:00:00.000Z',
    };
    expect(() => useScanStore.getState().setCardEdit('stocks', 'picks', 'AAPL', pick)).not.toThrow();
    expect(useScanStore.getState().stocksCardEdits.picks.AAPL).toEqual(pick);
    expect(setItem).toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });
});
