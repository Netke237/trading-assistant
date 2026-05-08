import { scanPortfolio } from '@/lib/alertEngine';
import type { AlertPosition } from '@/lib/alertEngine';
import { useScanStore } from '@/lib/scanStore';

describe('alertEngine.scanPortfolio', () => {
  const base: AlertPosition = {
    recId: 'REC-1',
    symbol: 'TEST',
    contract: 'TEST 100C 12/20',
    currentPrice: 100,
    entryPrice: 5,
    stop: 90,
    targets: [{ id: 'tp1', stockPrice: 110, contractsToSell: 1, status: 'PENDING' }],
    dteRemaining: 20,
    dteTotal: 30,
    pnlPct: 10,
  };

  beforeEach(() => {
    useScanStore.getState().setConflictedSymbols([]);
  });

  it('returns empty array when no conditions met', () => {
    expect(scanPortfolio([base])).toEqual([]);
  });

  it('generates TP_HIT when currentPrice >= target stockPrice', () => {
    const pos = { ...base, currentPrice: 115 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Action');
    expect(alerts[0].alertType).toBe('TP_HIT');
    expect(alerts[0].symbol).toBe('TEST');
    expect(alerts[0].recId).toBe('REC-1');
    expect(alerts[0].reason).toContain('Target reached');
  });

  it('generates STOP_REACHED when currentPrice <= stop', () => {
    const pos = { ...base, currentPrice: 85 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Critical');
    expect(alerts[0].alertType).toBe('STOP_REACHED');
    expect(alerts[0].reason).toContain('Stop breached');
  });

  it('generates PREMIUM_STOP when pnlPct <= -40', () => {
    const pos = { ...base, pnlPct: -45 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Critical');
    expect(alerts[0].alertType).toBe('PREMIUM_STOP');
    expect(alerts[0].reason).toContain('Premium stop');
  });

  it('generates TIME_STOP when dteRemaining <= 3', () => {
    const pos = { ...base, dteRemaining: 2 };
    const alerts = scanPortfolio([pos]);
    expect(alerts.some((a) => a.alertType === 'TIME_STOP')).toBe(true);
    expect(alerts.some((a) => a.reason.includes('Time stop'))).toBe(true);
  });

  it('generates EVENT_RISK when nextEventDays <= 3', () => {
    const pos = { ...base, nextEventDays: 2, nextEventLabel: 'Earnings' };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Action');
    expect(alerts[0].alertType).toBe('EVENT_RISK');
    expect(alerts[0].reason).toContain('Earnings in 2 days');
  });

  it('can generate multiple alerts for one position', () => {
    const pos = { ...base, currentPrice: 85, pnlPct: -45, dteRemaining: 2 };
    const alerts = scanPortfolio([pos]);
    expect(alerts.length).toBeGreaterThanOrEqual(3);
    expect(alerts.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
    expect(alerts.some((a) => a.alertType === 'PREMIUM_STOP')).toBe(true);
    expect(alerts.some((a) => a.alertType === 'TIME_STOP')).toBe(true);
  });

  it('skips conflicted symbols', () => {
    useScanStore.getState().setConflictedSymbols(['TEST']);
    const pos = { ...base, currentPrice: 115 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(0);
  });

  it('does not skip non-conflicted symbols', () => {
    useScanStore.getState().setConflictedSymbols(['OTHER']);
    const pos = { ...base, currentPrice: 115 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
  });
});