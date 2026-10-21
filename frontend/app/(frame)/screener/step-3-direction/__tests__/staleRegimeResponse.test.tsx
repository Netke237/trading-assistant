/**
 * APP-AUDIT-B-REGIME-RACE (#386): Step 3's mount fetch sends the same gate
 * request as Step 1 (Settings Markov values) and an earlier mount's answer
 * cannot overwrite a later mount's. Ordering counters are module-level and
 * only grow, so tests rely on relative order only.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Step3Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, MARKOV_PRESETS, DEFAULT_MARKOV } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => ({
  api: {
    getRegime: jest.fn(),
    getScanStatus: jest.fn().mockResolvedValue(null),
    getLastScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    getEventThresholds: jest.fn().mockResolvedValue(null),
  },
}));
jest.mock('@/components/organisms/RunScanButton', () => ({ RunScanButton: () => null }));
jest.mock('@/components/organisms/SearchProfileBar', () => ({ SearchProfileBar: () => null }));

const BULLISH = {
  universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)',
  horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
};
const REGIME_BULL = { overall: 'PASS', regime_direction: 'BULL', omm: { state: 'Bull' } };
const REGIME_BEAR = { overall: 'REJECT', regime_direction: 'BEAR', omm: { state: 'Bear' } };

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe('Step 3 — the newest applied regime response owns the gate', () => {
  beforeEach(() => {
    (api.getRegime as jest.Mock).mockReset();
    useSettingsStore.setState({ markov: { ...DEFAULT_MARKOV } });
    useScanStore.setState({
      context: BULLISH, regime: 'PENDING', regimeDirection: null, combinedRegime: 'PENDING',
      scanResult: null, screenerMode: 'options',
    } as never);
  });

  it('an earlier mount’s Bear answer after a later mount’s Bull answer changes nothing; the direction toggle uses the later reading', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = render(<Step3Page />);
    first.unmount();
    render(<Step3Page />);
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await act(async () => { b.resolve(REGIME_BULL); await b.promise; });
    await flush();
    expect(useScanStore.getState().combinedRegime).toBe('PASS');

    await act(async () => { a.resolve(REGIME_BEAR); await a.promise; });
    await flush();
    expect(useScanStore.getState().combinedRegime).toBe('PASS');
    expect(useScanStore.getState().regime).toBe('PASS');

    fireEvent.click(screen.getByRole('button', { name: 'Bearish' }));
    await flush();
    expect(useScanStore.getState().combinedRegime).toBe('REJECT');
  });

  it('sends intraday with the Settings Markov values and writes regimeDirection', async () => {
    useSettingsStore.setState({ markov: { preset: 'conservative', ...MARKOV_PRESETS.conservative } });
    (api.getRegime as jest.Mock).mockResolvedValue(REGIME_BULL);
    render(<Step3Page />);
    await flush();
    expect(api.getRegime).toHaveBeenCalledWith('intraday', { lookback: 60, threshold: 0.03, smoothing: 0.5 });
    expect(useScanStore.getState().regimeDirection).toBe('BULL');
    expect(useScanStore.getState().combinedRegime).toBe('PASS');
  });
});
