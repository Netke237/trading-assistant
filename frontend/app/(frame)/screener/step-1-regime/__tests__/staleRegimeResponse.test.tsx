/**
 * APP-AUDIT-B-REGIME-RACE (#386): an older /api/regime response must not
 * overwrite a newer one that already landed — on the shared gate
 * (`regime`, `regimeDirection`, `combinedRegime`), on Step 1's own banner and
 * on `regimeSentiment`. Ordering counters are module-level and only grow, so
 * every test relies on relative order only.
 */
import '@testing-library/jest-dom';
import { act, render, screen } from '@testing-library/react';
import Step1RegimePage from '../page';
import Step3Page from '../../step-3-direction/page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, MARKOV_PRESETS, DEFAULT_MARKOV } from '@/lib/settingsStore';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-1-regime',
}));
jest.mock('@/components/organisms/CandlestickChart', () => ({ CandlestickChart: () => null }));
jest.mock('@/components/organisms/RunScanButton', () => ({ RunScanButton: () => null }));
jest.mock('@/components/organisms/SearchProfileBar', () => ({ SearchProfileBar: () => null }));
jest.mock('@/components/molecules/NewsCard', () => ({ NewsCard: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/lib/api', () => ({
  api: {
    getRegime: jest.fn(),
    getSectors: jest.fn().mockResolvedValue([]),
    getCandles: jest.fn().mockResolvedValue([]),
    getNews: jest.fn().mockResolvedValue([]),
    getScanStatus: jest.fn().mockResolvedValue(null),
    getLastScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    getEventThresholds: jest.fn().mockResolvedValue(null),
  },
}));

const SWING_CONTEXT = {
  universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)',
  horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
};

const OMM = { p_stay: 0.8, stability: 'Stable', regime_age_days: 12, avg_regime_duration: 20,
  transition_row: [0.8, 0.1, 0.1], state_order: ['Bull', 'Bear', 'Choppy'] };

const REGIME_BULL = {
  overall: 'PASS', headline: 'Bull tide headline', metrics: [], regime_direction: 'BULL',
  omm: { ...OMM, state: 'Bull' }, conviction_pct: 42, conviction_label: 'Moderate',
};
const REGIME_BEAR = {
  overall: 'REJECT', headline: 'Bear tide headline', metrics: [], regime_direction: 'BEAR',
  omm: { ...OMM, state: 'Bear' }, conviction_pct: 10, conviction_label: 'Weak',
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
type D = ReturnType<typeof deferred<unknown>>;

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const answer = async (d: D, v: unknown) => { await act(async () => { d.resolve(v); await d.promise; }); await flush(); };
const fail = async (d: D) => {
  await act(async () => { d.reject(new Error('offline')); await d.promise.catch(() => {}); });
  await flush();
};

const gate = () => {
  const s = useScanStore.getState();
  return { regime: s.regime, regimeDirection: s.regimeDirection, combinedRegime: s.combinedRegime };
};
const BULL_GATE = { regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'PASS' };
const BEAR_GATE = { regime: 'REJECT', regimeDirection: 'BEAR', combinedRegime: 'REJECT' };

describe('Step 1 — the newest applied regime response owns the gate', () => {
  beforeEach(() => {
    (api.getRegime as jest.Mock).mockReset();
    useSettingsStore.setState({ markov: { ...DEFAULT_MARKOV } });
    useScanStore.setState({
      context: SWING_CONTEXT, regime: 'PENDING', regimeDirection: null, combinedRegime: 'PENDING',
      regimeSentiment: null, scanResult: null, screenerMode: 'options',
    } as never);
  });

  it('issue repro: an earlier mount’s Bear answer after a later mount’s Bull answer changes nothing', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step1RegimePage />);
    first.unmount();
    render(<Step1RegimePage />);
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await answer(b, REGIME_BULL);
    expect(gate()).toEqual(BULL_GATE);

    await answer(a, REGIME_BEAR);
    expect(gate()).toEqual(BULL_GATE);
    expect(screen.getByTestId('regime-banner')).toHaveTextContent('Bull tide headline');
  });

  it('in-mount supersede: a Markov change starts B; A answering after B leaves B’s reading', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    render(<Step1RegimePage />);
    act(() => { useSettingsStore.setState({ markov: { preset: 'conservative', ...MARKOV_PRESETS.conservative } }); });
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await answer(b, REGIME_BULL);
    await answer(a, REGIME_BEAR);
    expect(screen.getByTestId('regime-banner')).toHaveTextContent('Bull tide headline');
    expect(useScanStore.getState().regimeSentiment?.state).toBe('Bull');
    expect(gate()).toEqual(BULL_GATE);
  });

  it('in-mount stale failure: A failing after B answered shows no failure and keeps B', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    render(<Step1RegimePage />);
    act(() => { useSettingsStore.setState({ markov: { preset: 'aggressive', ...MARKOV_PRESETS.aggressive } }); });
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await answer(b, REGIME_BULL);
    await fail(a);
    expect(screen.queryByText(/Regime check failed/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Backend not running/)).not.toBeInTheDocument();
    expect(gate()).toEqual(BULL_GATE);
    expect(useScanStore.getState().regimeSentiment?.state).toBe('Bull');
  });

  it('an older answer still fills the gate while the newer request is pending; the newer one then wins', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step1RegimePage />);
    first.unmount();
    render(<Step1RegimePage />);

    await answer(a, REGIME_BEAR);
    expect(gate()).toEqual(BEAR_GATE);
    await answer(b, REGIME_BULL);
    expect(gate()).toEqual(BULL_GATE);
  });

  it('an older answer, then the newer request failing: the gate keeps the older verdict', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step1RegimePage />);
    first.unmount();
    render(<Step1RegimePage />);

    await answer(a, REGIME_BEAR);
    await fail(b);
    expect(gate()).toEqual(BEAR_GATE);
  });

  it('cross-page: Step 1’s older answer does not replace Step 3’s newer one; sentiment is still Step 1’s', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const step1 = render(<Step1RegimePage />);
    step1.unmount();
    render(<Step3Page />);
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await answer(b, REGIME_BULL);
    expect(useScanStore.getState().combinedRegime).toBe('PASS');
    await answer(a, REGIME_BEAR);
    expect(gate()).toEqual(BULL_GATE);
    expect(useScanStore.getState().regimeSentiment?.state).toBe('Bear');
  });
});
