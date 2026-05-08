import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';

describe('alertStore', () => {
  beforeEach(() => {
    useAlertStore.setState({
      toasts: [],
      unreadCount: 0,
      config: DEFAULT_CONFIG,
    });
  });

  it('adds a toast', () => {
    useAlertStore.getState().addToast({
      kind: 'Action',
      symbol: 'AAPL',
      reason: 'Target reached',
    });
    const toasts = useAlertStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].symbol).toBe('AAPL');
    expect(toasts[0].dismissed).toBe(false);
  });

  it('deduplicates toasts within the configured window', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached' });
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached' });
    expect(useAlertStore.getState().toasts).toHaveLength(1);
  });

  it('allows different reasons for the same symbol', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached' });
    store.addToast({ kind: 'Critical', symbol: 'AAPL', reason: 'Stop breached' });
    expect(useAlertStore.getState().toasts).toHaveLength(2);
  });

  it('dismisses a toast by id', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached' });
    const id = useAlertStore.getState().toasts[0].id;
    store.dismissToast(id);
    expect(useAlertStore.getState().toasts[0].dismissed).toBe(true);
  });

  it('clears unread count', () => {
    const store = useAlertStore.getState();
    store.addToast({ kind: 'Action', symbol: 'AAPL', reason: 'Target reached' });
    expect(useAlertStore.getState().unreadCount).toBe(1);
    store.clearAll();
    expect(useAlertStore.getState().unreadCount).toBe(0);
  });

  it('updates config', () => {
    const store = useAlertStore.getState();
    store.setConfig({ ...DEFAULT_CONFIG, dedupWindowMinutes: 30 });
    expect(useAlertStore.getState().config.dedupWindowMinutes).toBe(30);
  });
});
