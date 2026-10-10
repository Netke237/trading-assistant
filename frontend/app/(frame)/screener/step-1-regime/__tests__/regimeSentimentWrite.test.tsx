/**
 * STOCK-PRES-P4-STRATEGY Task 1 — Step 1 writes `scanStore.regimeSentiment`
 * inside `fetchRegime` (not by an effect): null when a fetch starts, the
 * reading when it answers (even after Step 1 unmounted), null when it fails.
 * The full MarketSentiment on Step 1 receives exactly what it did before.
 */
import '@testing-library/jest-dom';
import { act, render, waitFor } from '@testing-library/react';
import Step1RegimePage from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import type { SentimentData } from '@/types/domain';

const sentimentProps: Array<SentimentData | null> = [];

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-1-regime',
}));
jest.mock('@/components/organisms/CandlestickChart', () => ({ CandlestickChart: () => null }));
jest.mock('@/components/organisms/RunScanButton', () => ({ RunScanButton: () => null }));
jest.mock('@/components/molecules/NewsCard', () => ({ NewsCard: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({
  MarketSentiment: ({ s }: { s: SentimentData | null }) => { sentimentProps.push(s); return null; },
}));
jest.mock('@/lib/api', () => ({
  api: {
    getRegime: jest.fn(),
    getSectors: jest.fn().mockResolvedValue([]),
    getCandles: jest.fn().mockResolvedValue([]),
    getNews: jest.fn().mockResolvedValue([]),
  },
}));

const SWING_CONTEXT = {
  universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)',
  horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
};

const REGIME_B = {
  overall: 'PASS', regime_direction: 'BULL',
  omm: { state: 'Bull', p_stay: 0.8, stability: 'Stable', regime_age_days: 12,
    avg_regime_duration: 20, transition_row: [0.8, 0.1, 0.1], state_order: ['Bull', 'Bear', 'Choppy'] },
  conviction_pct: 42, conviction_label: 'Moderate', alignment: 'Aligned', hmm_state: 'Trending',
};

const SENTIMENT_B: SentimentData = {
  horizon: 'Swing (5–15d)', timeframe: 'daily', state: 'Bull', p_stay: 0.8, stability: 'Stable',
  regime_age_days: 12, avg_regime_duration: 20, conviction_pct: 42, conviction_label: 'Moderate',
  interpretation: 'Market conviction: Moderate', hmm_state: 'Trending', alignment: 'Aligned',
  insufficient_data: false,
};

const SENTIMENT_A: SentimentData = {
  horizon: 'Position (45–60d)', timeframe: 'daily', state: 'Bear', p_stay: 0.6, stability: 'Fragile',
  regime_age_days: 3, avg_regime_duration: 9, conviction_pct: 10, conviction_label: 'Weak',
  interpretation: 'Market conviction: Weak', hmm_state: null, alignment: 'Diverging',
  insufficient_data: false,
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe('Step 1 — writes scanStore.regimeSentiment from the regime fetch', () => {
  beforeEach(() => {
    sentimentProps.length = 0;
    (api.getRegime as jest.Mock).mockReset();
    useScanStore.setState({ context: SWING_CONTEXT, combinedRegime: 'PENDING', regimeSentiment: null } as never);
  });

  it('a response with omm ends with its sentiment, built with the context horizon', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue(REGIME_B);
    render(<Step1RegimePage />);
    await waitFor(() => expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B));
  });

  it('a response without omm ends with null', async () => {
    useScanStore.setState({ regimeSentiment: SENTIMENT_A } as never);
    const { omm: _omm, ...noOmm } = REGIME_B;
    (api.getRegime as jest.Mock).mockResolvedValue(noOmm);
    render(<Step1RegimePage />);
    await waitFor(() => expect(useScanStore.getState().combinedRegime).not.toBe('PENDING'));
    expect(useScanStore.getState().regimeSentiment).toBeNull();
  });

  it('a rejected fetch ends with null', async () => {
    useScanStore.setState({ regimeSentiment: SENTIMENT_A } as never);
    (api.getRegime as jest.Mock).mockRejectedValue(new Error('offline'));
    const { findByText } = render(<Step1RegimePage />);
    await findByText(/Regime check failed/);
    expect(useScanStore.getState().regimeSentiment).toBeNull();
  });

  it('while the fetch is pending the store holds null, not the older reading', async () => {
    useScanStore.setState({ regimeSentiment: SENTIMENT_A } as never);
    (api.getRegime as jest.Mock).mockReturnValue(new Promise(() => {}));
    render(<Step1RegimePage />);
    await flush();
    expect(useScanStore.getState().regimeSentiment).toBeNull();
  });

  it('unmount before the response: the store still ends with the new reading', async () => {
    useScanStore.setState({ regimeSentiment: SENTIMENT_A } as never);
    const d = deferred<typeof REGIME_B>();
    (api.getRegime as jest.Mock).mockReturnValue(d.promise);
    const { unmount } = render(<Step1RegimePage />);
    unmount();
    await act(async () => { d.resolve(REGIME_B); await d.promise; });
    await flush();
    expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B);
  });

  it('an older request answering after a newer one does not overwrite the newer reading', async () => {
    const REGIME_A = {
      ...REGIME_B,
      omm: { ...REGIME_B.omm, state: 'Bear', p_stay: 0.6, stability: 'Fragile', regime_age_days: 3,
        avg_regime_duration: 9 },
      conviction_pct: 10, conviction_label: 'Weak', alignment: 'Diverging', hmm_state: null,
    };
    const a = deferred<typeof REGIME_A>();
    const b = deferred<typeof REGIME_B>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step1RegimePage />);
    first.unmount();
    render(<Step1RegimePage />);
    expect(api.getRegime).toHaveBeenCalledTimes(2);
    await act(async () => { b.resolve(REGIME_B); await b.promise; });
    await flush();
    expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B);
    await act(async () => { a.resolve(REGIME_A); await a.promise; });
    await flush();
    expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B);
  });

  it('an older request failing after a newer one answered does not clear the newer reading', async () => {
    const a = deferred<typeof REGIME_B>();
    const b = deferred<typeof REGIME_B>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step1RegimePage />);
    first.unmount();
    render(<Step1RegimePage />);
    expect(api.getRegime).toHaveBeenCalledTimes(2);
    await act(async () => { b.resolve(REGIME_B); await b.promise; });
    await flush();
    expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B);
    await act(async () => { a.reject(new Error('offline')); await a.promise.catch(() => {}); });
    await flush();
    expect(useScanStore.getState().regimeSentiment).toEqual(SENTIMENT_B);
  });

  it('the full MarketSentiment receives the same object it did before', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue(REGIME_B);
    render(<Step1RegimePage />);
    await waitFor(() => expect(sentimentProps[sentimentProps.length - 1]).toEqual(SENTIMENT_B));
    expect(sentimentProps[0]).toBeNull();
  });
});
