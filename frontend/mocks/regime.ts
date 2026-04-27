/*
 * Market regime snapshot — Phase 5.
 * Drives Dashboard regime banner + Screener Step 3.
 */

import type { Status } from '@/lib/status';

export interface RegimeMetric {
  label:  string;
  value:  string;
  status: Status;
  /** Direction of the metric vs the previous scan — for the trend arrow. */
  trend?: 'up' | 'flat' | 'down';
}

export interface MarketRegime {
  overall:  Status;
  headline: string;
  metrics:  RegimeMetric[];
}

export const MOCK_REGIME: MarketRegime = {
  overall: 'PASS',
  headline: 'Trend + breadth constructive; VIX contained',
  metrics: [
    { label: 'SPX trend (200 EMA)', value: 'Above',    status: 'PASS',    trend: 'up'   },
    { label: 'NDX trend (200 EMA)', value: 'Above',    status: 'PASS',    trend: 'up'   },
    { label: 'Breadth (A/D)',       value: '+412',     status: 'PASS',    trend: 'up'   },
    { label: 'VIX',                 value: '14.8',     status: 'PASS',    trend: 'down' },
    { label: '10Y yield',           value: '4.28%',    status: 'CAUTION', trend: 'up'   },
    { label: 'DXY (USD)',           value: '104.6',    status: 'PASS',    trend: 'flat' },
    { label: 'HY credit spread',    value: '312 bp',   status: 'CAUTION', trend: 'up'   },
    { label: 'Put/Call (5d avg)',   value: '0.84',     status: 'PASS',    trend: 'down' },
  ],
};
