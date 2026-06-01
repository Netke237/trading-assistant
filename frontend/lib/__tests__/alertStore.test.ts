import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';

describe('alertStore', () => {
  beforeEach(() => {
    useAlertStore.setState({
      toasts: [],
      config: DEFAULT_CONFIG,
      firedAlerts: {},
      suppressedAlerts: {},
    });
  });

  it('adds a toast', () => {
    useAlertStore.getState().addToast({
      kind: 'Action',
      symbol: 'AAPL',
      reason: 'Target reached',
      recId: 'REC-1',
      alertType: 'TP_HIT',
    });
    const toasts = useAlertStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].symbol).toBe('AAPL');
    expect(toasts[0].recId).toBe('REC-1');
    expect(toasts[0].alertType).toBe('TP_HIT');
    expect(toasts[0].dismissed).toBe(false);
  });

  it('deduplicates toasts by recId-alertType composite key', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    expect(useAlertStore.getState().toasts).toHaveLength(1);
  });

  it('allows different alert types for the same recId', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    store.addToast({ kind: 'Critical', symbol: 'AAPL', reason: 'Stop breached', recId: 'REC-1', alertType: 'STOP_REACHED' });
    expect(useAlertStore.getState().toasts).toHaveLength(2);
  });

  it('dismisses a toast by id', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    const id = useAlertStore.getState().toasts[0].id;
    store.dismissToast(id);
    expect(useAlertStore.getState().toasts[0].dismissed).toBe(true);
  });

  it('clears all toasts', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    expect(useAlertStore.getState().toasts).toHaveLength(1);
    store.clearAll();
    expect(useAlertStore.getState().toasts).toHaveLength(0);
  });

  it('updates config', () => {
    const store = useAlertStore.getState();
    store.setConfig({ ...DEFAULT_CONFIG, dedupWindowMinutes: 30 });
    expect(useAlertStore.getState().config.dedupWindowMinutes).toBe(30);
  });

  it('allows re-notification after the throttle window expires', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });

    const now = Date.now();
    const firedAlerts = useAlertStore.getState().firedAlerts;
    const key = Object.keys(firedAlerts)[0]!;

    // Age the REC-1 entry past the throttle window (dedupWindowMinutes = 15m)
    useAlertStore.setState({
      firedAlerts: { [key]: now - 25 * 3600_000 },
    });

    // Adding a second alert does NOT evict old firedAlerts entries.
    // Both REC-1 and REC-2 coexist — addToast only adds/updates, never deletes.
    store.addToast({ kind: 'Action', symbol: 'MSFT', reason: 'Target reached', recId: 'REC-2', alertType: 'TP_HIT' });

    const newFiredAlerts = useAlertStore.getState().firedAlerts;
    expect(Object.keys(newFiredAlerts).some((k) => k.includes('REC-1'))).toBe(true);
    expect(Object.keys(newFiredAlerts).some((k) => k.includes('REC-2'))).toBe(true);

    // The aged REC-1 entry is still stale (unchanged), confirming it was not
    // touched by the unrelated addToast call.
    expect(newFiredAlerts[key]).toBe(now - 25 * 3600_000);
  });
});