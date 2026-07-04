import { compositeWatchSummary } from '../compositeWatchSummary';

describe('compositeWatchSummary', () => {
  it('summarizes primary model + target state', () => {
    expect(compositeWatchSummary({
      primary: { model: 'OMM', to_state: 'Bull' },
      confirmations: [], strategy_confirmations: [],
    })).toBe('OMM → Bull');
  });

  it('appends confirmation and strategy counts', () => {
    expect(compositeWatchSummary({
      primary: { model: 'HMM_daily', to_state: 'Trending' },
      confirmations: [{}, {}], strategy_confirmations: [{}],
    })).toBe('HMM_daily → Trending · 2 confirmations · 1 strategy');
  });

  it('handles "any" model and missing state', () => {
    expect(compositeWatchSummary({
      primary: { model: 'any' },
      confirmations: [], strategy_confirmations: [],
    })).toBe('any model → any state');
  });

  it('never throws on a malformed def', () => {
    expect(compositeWatchSummary({})).toBe('any model → any state');
    expect(compositeWatchSummary(null as unknown as Record<string, unknown>)).toBe('—');
  });
});
