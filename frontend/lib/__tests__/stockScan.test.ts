import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
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
    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE } });
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

  it('sends the full Settings default ATR pair for this horizon when no override is set', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(3.0); // swing default
    expect(arg.confidence_atr_mult_stop).toBe(1.5);
  });

  it('ignores a lone confidence_atr_mult_target override (without a stop) rather than sending a mismatched pair', async () => {
    // Regression: resolving target/stop independently would send the lone
    // override's target paired with the Settings default's stop, silently
    // producing a pair the user never actually configured together and
    // bypassing the backend's both-or-neither guard (which only nulls a pair
    // when it receives an explicit None on one side, not two valid numbers).
    useScanStore.setState({ scanOverrides: { confidence_atr_mult_target: 4.0 } } as any);
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(3.0); // full fallback to swing default, not 4.0
    expect(arg.confidence_atr_mult_stop).toBe(1.5);
  });

  it('uses both override values together when both target and stop are set', async () => {
    useScanStore.setState({
      scanOverrides: { confidence_atr_mult_target: 4.0, confidence_atr_mult_stop: 2.0 },
    } as any);
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.confidence_atr_mult_target).toBe(4.0);
    expect(arg.confidence_atr_mult_stop).toBe(2.0);
  });

  it('forwards mean-reversion-multi params only when that strategy is selected (H4)', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('mean_reversion_multi');
    const multiArg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(multiArg.mean_reversion_variants).toEqual(
      expect.arrayContaining(['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily'])
    );
    expect(multiArg.mean_reversion_min_confirmations).toBe(2);
    expect(multiArg.vwap_lookback).toBe(20);
    expect(multiArg.vwap_deviation_pct).toBe(0.02);

    (api.postStockScan as jest.Mock).mockClear();
    await runStockScan('pullback_ema');
    const singleArg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(singleArg.mean_reversion_variants).toBeUndefined();
    expect(singleArg.mean_reversion_min_confirmations).toBeUndefined();
  });
});
