/*
 * Alerts feed — Phase 5 mock.
 * Drives the Dashboard "Alerts" card and the TopBar bell (Phase 6).
 */

import type { AlertItem } from '@/types/domain';

export const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', kind: 'Critical', symbol: 'META', reason: 'Broke trail stop', timestamp: '09:38' },
  { id: 'a2', kind: 'Action',   symbol: 'NVDA', reason: 'Earnings in 3 days — roll or close', timestamp: '09:41' },
  { id: 'a3', kind: 'Action',   symbol: 'AAPL', reason: 'Target 80% reached',        timestamp: '09:47' },
  { id: 'a4', kind: 'Info',     symbol: 'SPY',  reason: 'Regime flipped to PASS',     timestamp: '09:15' },
  { id: 'a5', kind: 'Info',     symbol: 'TSLA', reason: 'IV rank > 70',               timestamp: '09:02' },
];
