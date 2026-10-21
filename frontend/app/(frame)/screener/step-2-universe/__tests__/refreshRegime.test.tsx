/**
 * APP-AUDIT-B-REGIME-RACE (#386): Step 2's "Refresh regime" sends the same
 * gate request as Step 1 (Settings Markov values), writes all three gate
 * fields, and an older refresh cannot overwrite a newer one that landed.
 * Ordering counters are module-level and only grow, so tests rely on
 * relative order only.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import Step2Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useSettingsStore, MARKOV_PRESETS, DEFAULT_MARKOV } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => ({
  api: {
    getRegime: jest.fn(),
    getSectors: jest.fn().mockResolvedValue([]),
    getIndexChanges: jest.fn().mockResolvedValue([]),
    getHistoryPrefetchStatus: jest.fn().mockResolvedValue({
      status: 'idle', total: 0, done: 0, failed: 0, current_symbol: null, elapsed_secs: 0,
    }),
    startHistoryPrefetch: jest.fn(),
  },
  getLastDataRefresh: jest.fn().mockResolvedValue({ last_refresh: null }),
}));

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

const gate = () => {
  const s = useScanStore.getState();
  return { regime: s.regime, regimeDirection: s.regimeDirection, combinedRegime: s.combinedRegime };
};

describe('Step 2 — Refresh regime writes the gate in request order', () => {
  beforeEach(() => {
    (api.getRegime as jest.Mock).mockReset();
    useSettingsStore.setState({ markov: { ...DEFAULT_MARKOV } });
    useScanStore.setState({
      context: BULLISH, regime: 'PENDING', regimeDirection: null, combinedRegime: 'PENDING',
    } as never);
  });

  it('an earlier mount’s refresh answering after a later mount’s refresh landed changes nothing', async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);

    const first = render(<Step2Page />);
    await flush();
    fireEvent.click(within(first.container).getByRole('button', { name: 'Refresh regime data' }));
    first.unmount();
    const second = render(<Step2Page />);
    await flush();
    fireEvent.click(within(second.container).getByRole('button', { name: 'Refresh regime data' }));
    expect(api.getRegime).toHaveBeenCalledTimes(2);

    await act(async () => { b.resolve(REGIME_BULL); await b.promise; });
    await flush();
    expect(useScanStore.getState().regime).toBe('PASS');

    await act(async () => { a.resolve(REGIME_BEAR); await a.promise; });
    await flush();
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'PASS' });
  });

  it('sends the Settings Markov values, writes all three gate fields, and clears Refreshing when not applied', async () => {
    useSettingsStore.setState({ markov: { preset: 'aggressive', ...MARKOV_PRESETS.aggressive } });
    useScanStore.setState({ context: { ...BULLISH, direction: 'Bearish' } } as never);
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    (api.getRegime as jest.Mock).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);

    // Two mounted pages: the first's refresh (A) is older than the second's (B).
    const first = render(<Step2Page />);
    const second = render(<Step2Page />);
    await flush();
    fireEvent.click(within(first.container).getByRole('button', { name: 'Refresh regime data' }));
    fireEvent.click(within(second.container).getByRole('button', { name: 'Refresh regime data' }));
    expect(api.getRegime).toHaveBeenNthCalledWith(1, 'intraday', { lookback: 10, threshold: 0.01, smoothing: 0 });
    expect(api.getRegime).toHaveBeenNthCalledWith(2, 'intraday', { lookback: 10, threshold: 0.01, smoothing: 0 });

    await act(async () => { b.resolve(REGIME_BULL); await b.promise; });
    await flush();
    // Bearish context against a Bull reading.
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'REJECT' });
    expect(within(second.container).getByText(/^Updated /)).toBeInTheDocument();

    await act(async () => { a.resolve(REGIME_BEAR); await a.promise; });
    await flush();
    expect(gate()).toEqual({ regime: 'PASS', regimeDirection: 'BULL', combinedRegime: 'REJECT' });
    const firstButton = within(first.container).getByRole('button', { name: 'Refresh regime data' });
    expect(firstButton).toHaveTextContent('Refresh regime');
    expect(firstButton).not.toBeDisabled();
    expect(within(first.container).queryByText(/^Updated /)).not.toBeInTheDocument();
    expect(screen.queryAllByText('Refresh failed')).toHaveLength(0);
  });
});
