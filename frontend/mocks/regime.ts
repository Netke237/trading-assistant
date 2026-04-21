/*
 * Market regime snapshot — Phase 5.
 * Drives Dashboard regime banner + Screener Step 3.
 */

import type { Status } from '@/lib/status';

export interface RegimeMetric {
  label: string;
  value: string;
  status: Status;
}

export interface MarketRegime {
  overall: Status;
  headline: string;
  metrics: RegimeMetric[];
}

export const MOCK_REGIME: MarketRegime = {
  overall: 'PASS',
  headline: 'Trend + breadth constructive; VIX contained',
  metrics: [
    { label: 'SPX trend (200 EMA)', value: 'Above',    status: 'PASS'    },
    { label: 'NDX trend (200 EMA)', value: 'Above',    status: 'PASS'    },
    { label: 'Breadth (A/D)',       value: '+412',     status: 'PASS'    },
    { label: 'VIX',                 value: '14.8',     status: 'PASS'    },
    { label: '10Y yield',           value: '4.28%',    status: 'CAUTION' },
    { label: 'DXY (USD)',           value: '104.6',    status: 'PASS'    },
    { label: 'HY credit spread',    value: '312 bp',   status: 'CAUTION' },
    { label: 'Put/Call (5d avg)',   value: '0.84',     status: 'PASS'    },
  ],
};
