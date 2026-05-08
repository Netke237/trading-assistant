import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';

describe('alertStore', () => {
  beforeEach(() => {
    useAlertStore.setState({
      toasts: [],
      unreadCount: 0,
      config: DEFAULT_CONFIG,
      firedAlerts: {},
    });
    useSettingsStore.setState({ alertDeduplicationHours: 24 });
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

  it('clears unread count', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });
    expect(useAlertStore.getState().unreadCount).toBe(1);
    store.clearAll();
    expect(useAlertStore.getState().unreadCount).toBe(0);
  });

  it('updates config', () => {
    const store = useAlertStore.getState();
    store.setConfig({ ...DEFAULT_CONFIG, dedupWindowMinutes: 30 });
    expect(useAlertStore.getState().config.dedupWindowMinutes).toBe(30);
  });

  it('evicts expired alerts from firedAlerts', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached', recId: 'REC-1', alertType: 'TP_HIT' });

    const now = Date.now();
    const firedAlerts = useAlertStore.getState().firedAlerts;
    const key = Object.keys(firedAlerts)[0]!;

    useAlertStore.setState({
      firedAlerts: { [key]: now - 25 * 3600_000 },
    });

    useSettingsStore.setState({ alertDeduplicationHours: 24 });

    store.addToast({ kind: 'Action', symbol: 'MSFT', reason: 'Target reached', recId: 'REC-2', alertType: 'TP_HIT' });

    const newFiredAlerts = useAlertStore.getState().firedAlerts;
    expect(Object.keys(newFiredAlerts).some((k) => k.includes('REC-1'))).toBe(false);
    expect(Object.keys(newFiredAlerts).some((k) => k.includes('REC-2'))).toBe(true);
  });
});