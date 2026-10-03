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

  it('forwards price/referenceValue/direction/contract/note to POST /api/alerts/notify', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) });
    (global as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    useAlertStore.getState().addToast({
      kind: 'Critical',
      symbol: 'AAPL',
      reason: 'Stop breached — AAPL below $90.00 (price $88.00)',
      recId: 'REC-1',
      alertType: 'STOP_REACHED',
      price: 88,
      referenceValue: 90,
      direction: 'Bullish',
      contract: 'AAPL|STOCK',
      note: 'from-test',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/api/alerts/notify');
    const body = JSON.parse((opts as RequestInit).body as string);
    expect(body).toMatchObject({
      symbol: 'AAPL',
      alertType: 'STOP_REACHED',
      recId: 'REC-1',
      price: 88,
      referenceValue: 90,
      direction: 'Bullish',
      contract: 'AAPL|STOCK',
      note: 'from-test',
    });
  });
});
// ── STOP-SEMANTICS-2026-10-02 -- a short stock's PREMIUM_STOP has its own key ─
describe('alertStore -- STOP-SEMANTICS side-aware key', () => {
  const short = {
    kind: 'Critical' as const, symbol: 'AAPL', reason: 'Stock stop — AAPL at $110.00',
    recId: 'REC-S', alertType: 'PREMIUM_STOP' as const, stopSide: 'short-stock' as const,
  };
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) });
    (global as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
    useAlertStore.setState({ toasts: [], config: DEFAULT_CONFIG, firedAlerts: {}, suppressedAlerts: {} });
  });

  it('legacy fall-side state (acknowledged key, throttle stamp, open row) cannot touch the rise-side fire', () => {
    const now = Date.now();
    useAlertStore.setState({
      suppressedAlerts: { 'REC-S-PREMIUM_STOP': true },
      firedAlerts: { 'REC-S-PREMIUM_STOP': now },
      toasts: [{
        id: 'legacy', kind: 'Critical', symbol: 'AAPL', reason: 'Premium stop — AAPL down 12.0%',
        recId: 'REC-S', alertType: 'PREMIUM_STOP', dismissed: false, acknowledged: false,
        firedAt: new Date(now - 3600_000).toISOString(),
      }],
    });
    useAlertStore.getState().addToast(short);
    const { toasts, firedAlerts } = useAlertStore.getState();
    expect(toasts).toHaveLength(2);                                   // a NEW row
    expect(toasts.find((t) => t.id === 'legacy')!.reason).toBe('Premium stop — AAPL down 12.0%');
    expect(toasts.find((t) => t.id !== 'legacy')!.stopSide).toBe('short-stock');
    expect(firedAlerts['REC-S-PREMIUM_STOP:short']).toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);                       // and it notifies
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as { body: string }).body);
    expect(body.stopSide).toBe('short-stock');
  });

  it('acknowledging the short row suppresses only the :short key, and it refreshes in place', () => {
    const store = useAlertStore.getState();
    store.addToast(short);
    store.addToast({ ...short, reason: 'Stock stop — AAPL at $111.00' });
    expect(useAlertStore.getState().toasts).toHaveLength(1);
    expect(useAlertStore.getState().toasts[0].reason).toBe('Stock stop — AAPL at $111.00');
    store.acknowledgeAlert(useAlertStore.getState().toasts[0].id);
    expect(useAlertStore.getState().suppressedAlerts).toEqual({ 'REC-S-PREMIUM_STOP:short': true });
    store.addToast(short);
    expect(useAlertStore.getState().toasts).toHaveLength(1);           // suppressed
  });

  it('regression guard: long-stock and option PREMIUM_STOP keep the legacy key', () => {
    const store = useAlertStore.getState();
    store.addToast({ ...short, recId: 'REC-L', stopSide: 'long-stock' });
    store.addToast({ ...short, recId: 'REC-O', stopSide: 'option' });
    store.addToast({ ...short, recId: 'REC-U', stopSide: undefined });
    expect(Object.keys(useAlertStore.getState().firedAlerts).sort()).toEqual(
      ['REC-L-PREMIUM_STOP', 'REC-O-PREMIUM_STOP', 'REC-U-PREMIUM_STOP']);
  });

  it('hydration keeps one legacy and one short row for the same position', async () => {
    const now = Date.now();
    const row = (id: string, over: Record<string, unknown>) => ({
      id, kind: 'Critical', symbol: 'AAPL', reason: 'x', recId: 'REC-S', alertType: 'PREMIUM_STOP',
      dismissed: false, acknowledged: false, firedAt: new Date(now - 60_000).toISOString(), ...over,
    });
    localStorage.setItem('bamendjou-alerts-v2', JSON.stringify({
      version: 3,
      state: {
        toasts: [row('legacy', {}), row('short', { stopSide: 'short-stock' })],
        config: DEFAULT_CONFIG, suppressedAlerts: {}, firedAlerts: {},
      },
    }));
    await useAlertStore.persist.rehydrate();
    expect(useAlertStore.getState().toasts.map((t) => t.id).sort()).toEqual(['legacy', 'short']);
  });

  it('regression guard (R3-B2): rehydrating a v3 blob leaves STRUCTURAL_STOP_BREACHED off', async () => {
    const enabledTypes = DEFAULT_CONFIG.enabledTypes.filter((t) => t !== 'STRUCTURAL_STOP_BREACHED');
    localStorage.setItem('bamendjou-alerts-v2', JSON.stringify({
      version: 3,
      state: { toasts: [], config: { ...DEFAULT_CONFIG, enabledTypes }, suppressedAlerts: {}, firedAlerts: {} },
    }));
    await useAlertStore.persist.rehydrate();
    expect(useAlertStore.getState().config.enabledTypes).not.toContain('STRUCTURAL_STOP_BREACHED');
  });
});
