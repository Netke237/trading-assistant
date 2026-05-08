import { scanPortfolio } from '@/lib/alertEngine';
import type { AlertPosition } from '@/lib/alertEngine';

describe('alertEngine.scanPortfolio', () => {
  const base: AlertPosition = {
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

  it('returns empty array when no conditions met', () => {
    expect(scanPortfolio([base])).toEqual([]);
  });

  it('generates TP_HIT when currentPrice >= target stockPrice', () => {
    const pos = { ...base, currentPrice: 115 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Action');
    expect(alerts[0].symbol).toBe('TEST');
    expect(alerts[0].reason).toContain('Target reached');
  });

  it('generates STOP_REACHED when currentPrice < stop', () => {
    const pos = { ...base, currentPrice: 85 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Critical');
    expect(alerts[0].reason).toContain('Stop breached');
  });

  it('generates PREMIUM_STOP when pnlPct <= -50', () => {
    const pos = { ...base, pnlPct: -55 };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Critical');
    expect(alerts[0].reason).toContain('Premium stop');
  });

  it('generates TIME_STOP_APPROACHING when dteRemaining <= 30% of dteTotal', () => {
    const pos = { ...base, dteRemaining: 8, dteTotal: 30 };
    const alerts = scanPortfolio([pos]);
    expect(alerts.some((a) => a.reason.includes('Time stop approaching'))).toBe(true);
  });

  it('generates EARNINGS_APPROACHING when nextEventDays <= 3', () => {
    const pos = { ...base, nextEventDays: 2, nextEventLabel: 'Earnings' };
    const alerts = scanPortfolio([pos]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe('Action');
    expect(alerts[0].reason).toContain('Earnings in 2 days');
  });

  it('generates EXPIRATION_APPROACHING when dteRemaining <= 3', () => {
    const pos = { ...base, dteRemaining: 2 };
    const alerts = scanPortfolio([pos]);
    expect(alerts.some((a) => a.reason.includes('Expiration approaching'))).toBe(true);
  });

  it('can generate multiple alerts for one position', () => {
    const pos = { ...base, currentPrice: 85, pnlPct: -55, dteRemaining: 2 };
    const alerts = scanPortfolio([pos]);
    expect(alerts.length).toBeGreaterThanOrEqual(3);
    expect(alerts.some((a) => a.reason.includes('Stop breached'))).toBe(true);
    expect(alerts.some((a) => a.reason.includes('Premium stop'))).toBe(true);
    expect(alerts.some((a) => a.reason.includes('Expiration approaching'))).toBe(true);
  });
});
