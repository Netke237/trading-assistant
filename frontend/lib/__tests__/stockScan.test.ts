import { runStockScan, stockPositionCardKey } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';

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

describe('stockPositionCardKey', () => {
  function card(overrides: Partial<{ symbol: string; entry: number; stop: number; target: number; targets: number[] }> = {}): PositionCardData {
    const { symbol = 'AAPL', entry = 150, stop = 145, target = 160, targets } = overrides;
    return {
      symbol,
      strategy: {
        entry_price: entry, stop_price: stop, target_price: target,
        ...(targets ? { targets } : {}),
      } as PositionCardData['strategy'],
    } as PositionCardData;
  }

  it('changes when the signal changes for the same symbol', () => {
    // The exact scenario an adversarial audit round found: a card stays open
    // (openSymbol) across a same-symbol Run Scan, so the key must change
    // whenever the recomputed signal actually differs, or React reuses the
    // component and its overlay state goes stale.
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ entry: 152 }));
    expect(before).not.toBe(after);
  });

  it('stays the same when the signal is unchanged, even across re-renders', () => {
    expect(stockPositionCardKey(card())).toBe(stockPositionCardKey(card()));
  });

  it('differs by symbol alone when entry/stop/target coincide', () => {
    expect(stockPositionCardKey(card({ symbol: 'AAPL' })))
      .not.toBe(stockPositionCardKey(card({ symbol: 'MSFT' })));
  });

  it('changes when only the stop moves', () => {
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ stop: 143 }));
    expect(before).not.toBe(after);
  });

  it('changes when only the target moves', () => {
    const before = stockPositionCardKey(card());
    const after  = stockPositionCardKey(card({ target: 165 }));
    expect(before).not.toBe(after);
  });

  it('changes when T2/T3 change even though entry/stop/target[0] are identical', () => {
    // A third independent audit round's exact repro: resolve_multi_signal can
    // return the same entry/stop/targets[0] across two scans (e.g. a
    // re-scan that adds a third confirming variant whose own rung is
    // farther than the already-tightest one) while targets[1]/[2] differ.
    // Keying on target_price alone (== targets[0]) would miss this and leave
    // the card un-remounted with a stale T2/T3.
    const before = stockPositionCardKey(card({ target: 103, targets: [103.0, 106.0] }));
    const after  = stockPositionCardKey(card({ target: 103, targets: [103.0, 106.0, 110.0] }));
    expect(before).not.toBe(after);
  });

  it('falls back to target_price when targets is absent or empty, matching defaultOverlay()', () => {
    // `?.length`, not `??` — an empty array must fall back too, same
    // convention StockPositionCard's defaultOverlay() already follows.
    const absent = stockPositionCardKey(card({ target: 160 }));
    const empty  = stockPositionCardKey(card({ target: 160, targets: [] }));
    const single = stockPositionCardKey(card({ target: 160, targets: [160] }));
    expect(absent).toBe(empty);
    expect(absent).toBe(single);
  });
});
