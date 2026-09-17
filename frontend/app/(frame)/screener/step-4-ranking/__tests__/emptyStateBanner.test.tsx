import '@testing-library/jest-dom';
import React from 'react';
import { render, screen } from '@testing-library/react';
import Step4Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import type { ScanResult } from '@/lib/scanStore';

/**
 * The reported bug's user-visible half. When the direction-conviction gate
 * strips every candidate the backend sends a `direction_banner` explaining it,
 * but the page returns early on an empty candidate list — and the banner used
 * to render only AFTER that return, so the one scan it exists for never showed
 * it. The user saw a bare "No candidates matched the current scan criteria."
 */

jest.mock('@/lib/api', () => ({
  api: { getCandles: jest.fn().mockResolvedValue([]) },
}));

const BANNER =
  'No confirmed bearish setups in this universe. All candidates were removed — '
  + 'market structure does not support short-side entries.';

function setScanResult(result: ScanResult | null) {
  useScanStore.setState({ scanResult: result ?? undefined, previousRun: undefined });
}

describe('Step 4 ranking — empty state explains itself', () => {
  afterEach(() => setScanResult(null));

  it('shows the direction banner when the gate stripped every candidate', () => {
    setScanResult({
      scan_id: 'REC-20260915-AAAAAAAA',
      timestamp: '2026-09-15T21:33:00+00:00',
      candidates: [],
      rejected: [],
      direction_banner: BANNER,
    });

    render(<Step4Page />);

    expect(screen.getByText(BANNER)).toBeInTheDocument();
  });

  it('still says a scan ran, so an empty table is not mistaken for no scan', () => {
    setScanResult({
      scan_id: 'REC-20260915-AAAAAAAA',
      timestamp: '2026-09-15T21:33:00+00:00',
      candidates: [],
      rejected: [],
      direction_banner: BANNER,
    });

    render(<Step4Page />);

    expect(screen.getByText('No candidates matched the current scan criteria.')).toBeInTheDocument();
  });

  it('prompts for a scan, with no banner, before anything has run', () => {
    setScanResult(null);

    render(<Step4Page />);

    expect(screen.getByText('Run a scan to see ranked candidates.')).toBeInTheDocument();
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });
});
