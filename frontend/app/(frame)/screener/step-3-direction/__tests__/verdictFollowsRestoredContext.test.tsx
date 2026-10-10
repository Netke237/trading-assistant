/**
 * STEP3-PARAM-REACH (code round 4): Step 3 recomputes the regime verdict when
 * its context changes from outside the page (StoreHydration restoring a
 * scan's context after Step 3's own regime fetch resolved). Only
 * handleDirChange recomputed it before, so a Bearish restore kept the Bullish
 * verdict on the Step-7 pre-trade rail.
 */
import '@testing-library/jest-dom';
import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import Step3Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';

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

const BEARISH = {
  universe: 'SP500', direction: 'Bearish', horizon: 'Position (45–60d)',
  horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60,
};

describe('Step 3 — the regime verdict follows a context restored from outside', () => {
  beforeEach(() => {
    useScanStore.setState({ context: null, combinedRegime: 'PENDING', scanResult: null, screenerMode: 'options' } as never);
  });

  it('Bull regime answered first, Bearish context restored after → REJECT', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({ overall: 'PASS', omm: { state: 'Bull' } });
    render(<Step3Page />);
    await waitFor(() => expect(useScanStore.getState().combinedRegime).toBe('PASS'));
    act(() => { useScanStore.setState({ context: BEARISH } as never); });
    await waitFor(() => expect(useScanStore.getState().combinedRegime).toBe('REJECT'));
  });

  it('a context change before the regime answers does not compute a verdict on the default descriptor', async () => {
    (api.getRegime as jest.Mock).mockReturnValue(new Promise(() => {}));
    render(<Step3Page />);
    act(() => { useScanStore.setState({ context: BEARISH } as never); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(useScanStore.getState().combinedRegime).toBe('PENDING');
  });
});
