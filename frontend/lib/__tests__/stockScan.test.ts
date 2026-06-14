import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: { postStockScan: jest.fn() },
}));

describe('runStockScan', () => {
  beforeEach(() => {
    (api.postStockScan as jest.Mock).mockReset();
    useScanStore.setState({
      context: { universe: 'NAS100', direction: 'Bullish', horizon: 'Swing (5–15d)' },
      scanOverrides: {},
      stockScanResult: null,
      previousStockScanResult: null,
      activeStrategy: null,
      scanState: 'IDLE',
    } as any);
  });

  it('calls postStockScan with the strategy + universe and stores the result', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    expect(api.postStockScan).toHaveBeenCalledTimes(1);
    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.strategy).toBe('pullback_ema');
    expect(arg.universe).toEqual(['NAS100']);
    expect(arg.direction).toBe('Bullish');
    expect(arg.horizon).toBe('Swing');
    expect(useScanStore.getState().stockScanResult).toEqual(fake);
    expect(useScanStore.getState().activeStrategy).toBe('pullback_ema');
  });

  it('sets scanState FAILED when the API throws', async () => {
    (api.postStockScan as jest.Mock).mockRejectedValue(new Error('boom'));
    await runStockScan('pullback_ema');
    expect(useScanStore.getState().scanState).toBe('FAILED');
  });
});
