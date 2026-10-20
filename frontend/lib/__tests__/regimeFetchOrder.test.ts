/**
 * APP-AUDIT-B-REGIME-RACE (#386): which /api/regime response may write the
 * shared regime gate. Tickets only ever grow and the counters are
 * module-level, so these tests rely on relative order, never absolute values.
 */
import { applyRegimeResponse, beginRegimeFetch, fetchGateRegime } from '@/lib/regimeFetchOrder';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, MARKOV_PRESETS, DEFAULT_MARKOV } from '@/lib/settingsStore';
import type { MarketRegime } from '@/types/domain';

jest.mock('@/lib/api', () => ({ api: { getRegime: jest.fn() } }));

const BULL = { overall: 'PASS', headline: 'Bull', metrics: [], regime_direction: 'BULL', omm: { state: 'Bull' } } as unknown as MarketRegime;
const BEAR = { overall: 'REJECT', headline: 'Bear', metrics: [], regime_direction: 'BEAR', omm: { state: 'Bear' } } as unknown as MarketRegime;

const BULLISH = { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)', horizonPreset: 'Swing', holdMin: 5, holdMax: 15 };
const BEARISH = { ...BULLISH, direction: 'Bearish' };

const gate = () => {
  const s = useScanStore.getState();
  return { regime: s.regime, regimeDirection: s.regimeDirection, combinedRegime: s.combinedRegime };
};

describe('regimeFetchOrder', () => {
  beforeEach(() => {
    useScanStore.setState({ context: BULLISH, regime: 'PENDING', regimeDirection: null, combinedRegime: 'PENDING' } as never);
    useSettingsStore.setState({ markov: { ...DEFAULT_MARKOV } });
    (api.getRegime as jest.Mock).mockReset();
  });

  it('tickets grow; only a response newer than the last applied one writes', () => {
    const a = beginRegimeFetch();
    const b = beginRegimeFetch();
    expect(b).toBeGreaterThan(a);

    // The older response arriving while the newer one is pending still applies.
    expect(applyRegimeResponse(a, BEAR)).toBe(true);
    expect(gate()).toEqual({ regime: 'REJECT', regimeDirection: 'BEAR', combinedRegime: 'REJECT' });
    expect(applyRegimeResponse(b, BULL)).toBe(true);
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'PASS' });

    // The older response arriving after the newer one applied writes nothing.
    const c = beginRegimeFetch();
    const d = beginRegimeFetch();
    expect(applyRegimeResponse(d, BULL)).toBe(true);
    expect(applyRegimeResponse(c, BEAR)).toBe(false);
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'PASS' });

    // The same ticket twice: not newer than the last applied.
    expect(applyRegimeResponse(d, BEAR)).toBe(false);
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'PASS' });
  });

  it('writes all three fields; the verdict uses the context direction at write time', () => {
    const t = beginRegimeFetch();
    useScanStore.setState({ context: BEARISH } as never);
    expect(applyRegimeResponse(t, BULL)).toBe(true);
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'REJECT' });

    const u = beginRegimeFetch();
    useScanStore.setState({ context: null } as never);
    const noDirection = { overall: 'CAUTION', headline: '', metrics: [] } as unknown as MarketRegime;
    expect(applyRegimeResponse(u, noDirection)).toBe(true);
    // No regime_direction → null; no omm → Choppy → CAUTION (direction defaults to Bullish).
    expect(gate()).toEqual({ regime: 'CAUTION', regimeDirection: null, combinedRegime: 'CAUTION' });
  });

  it('fetchGateRegime sends intraday and the Settings Markov values at call time', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue(BULL);
    useSettingsStore.setState({ markov: { preset: 'conservative', ...MARKOV_PRESETS.conservative } });
    await expect(fetchGateRegime()).resolves.toBe(BULL);
    expect(api.getRegime).toHaveBeenCalledWith('intraday', { lookback: 60, threshold: 0.03, smoothing: 0.5 });
  });
});
