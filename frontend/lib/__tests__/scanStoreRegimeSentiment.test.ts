// STOCK-PRES-P4-STRATEGY Task 1 — `scanStore.regimeSentiment`: written by
// Step 1 from the regime response, read by the Stocks Strategy page's strip.
// Deliberately NOT persisted: a stored sentiment would show stale numbers
// after a reload.

import { act } from '@testing-library/react';
import { useScanStore } from '@/lib/scanStore';
import type { SentimentData } from '@/types/domain';

const READING: SentimentData = {
  horizon: 'Swing (5–15d)', timeframe: 'daily', state: 'Bull', p_stay: 0.8,
  stability: 'Stable', regime_age_days: 12, avg_regime_duration: 20,
  conviction_pct: 42, conviction_label: 'Moderate',
  interpretation: 'Market conviction: Moderate', hmm_state: 'Trending',
  alignment: 'Aligned', insufficient_data: false,
};

describe('scanStore.regimeSentiment', () => {
  it('is null initially', () => {
    expect(useScanStore.getInitialState().regimeSentiment).toBeNull();
    expect(useScanStore.getState().regimeSentiment).toBeNull();
  });

  it('setRegimeSentiment stores the value, and null clears it', () => {
    act(() => { useScanStore.getState().setRegimeSentiment(READING); });
    expect(useScanStore.getState().regimeSentiment).toEqual(READING);
    act(() => { useScanStore.getState().setRegimeSentiment(null); });
    expect(useScanStore.getState().regimeSentiment).toBeNull();
  });

  it('is not in partialize — never written to localStorage', () => {
    act(() => { useScanStore.getState().setRegimeSentiment(READING); });
    const persisted = useScanStore.persist.getOptions().partialize!(useScanStore.getState());
    expect(persisted).not.toHaveProperty('regimeSentiment');
    act(() => { useScanStore.getState().setRegimeSentiment(null); });
  });
});
