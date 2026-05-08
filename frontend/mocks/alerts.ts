import type { AlertItem } from '@/types/domain';

export const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', kind: 'Critical', symbol: 'META', reason: 'Broke trail stop', timestamp: '09:38', recId: 'REC-META-001', alertType: 'STOP_REACHED' },
  { id: 'a2', kind: 'Action',   symbol: 'NVDA', reason: 'Earnings in 3 days — roll or close', timestamp: '09:41', recId: 'REC-NVDA-001', alertType: 'EVENT_RISK' },
  { id: 'a3', kind: 'Action',   symbol: 'AAPL', reason: 'Target 80% reached', timestamp: '09:47', recId: 'REC-AAPL-001', alertType: 'TP_HIT' },
  { id: 'a4', kind: 'Info',     symbol: 'SPY',  reason: 'Regime flipped to PASS', timestamp: '09:15', recId: 'REC-SPY-001', alertType: 'REGIME_CHANGE' },
  { id: 'a5', kind: 'Info',     symbol: 'TSLA', reason: 'IV rank > 70', timestamp: '09:02', recId: 'REC-TSLA-001', alertType: 'SCAN_COMPLETE' },
];
