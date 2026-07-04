import { renderHook, act } from '@testing-library/react';
import { useChartAlertStore, HISTORY_LIMIT } from '@/lib/chartAlertStore';
import type { AlertRule, AlertHistory, PriceCondition } from '@/types/alerts';

function makeRule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r1',
    name: 'Test Rule',
    symbol: 'AAPL',
    interval: '1D',
    enabled: true,
    group: {
      logic: 'AND',
      conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition],
    },
    cooldown_minutes: 60,
    expiry_date: null,
    created_at: new Date().toISOString(),
    last_triggered_at: null,
    ...overrides,
  };
}

function makeHistory(overrides: Partial<AlertHistory> = {}): AlertHistory {
  return {
    id: 'h1',
    rule_id: 'r1',
    symbol: 'AAPL',
    interval: '1D',
    triggered_at: new Date().toISOString(),
    candle: { time: '2024-01-05', open: 184, high: 187, low: 183, close: 186, volume: 10000 },
    trigger_values: { close: 186 },
    reason: 'Price > 185',
    ...overrides,
  };
}

describe('chartAlertStore', () => {
  beforeEach(() => {
    useChartAlertStore.setState({ rules: [], history: [], toasts: [], newSinceView: 0 });
  });

  it('adds a rule', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    expect(result.current.rules).toHaveLength(1);
    expect(result.current.rules[0].name).toBe('Test Rule');
  });

  it('blocks duplicate rule (same symbol, interval, conditions)', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    act(() => result.current.addRule(makeRule({ id: 'r2' })));
    expect(result.current.rules).toHaveLength(1);
  });

  it('allows rules with same symbol/interval but different conditions', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    act(() =>
      result.current.addRule(
        makeRule({
          id: 'r2',
          group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<', value: 170 } as PriceCondition] },
        }),
      ),
    );
    expect(result.current.rules).toHaveLength(2);
  });

  it('blocks duplicate even when logic differs (same conditions = duplicate)', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() =>
      result.current.addRule(
        makeRule({ id: 'r1', group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition] } }),
      ),
    );
    act(() =>
      result.current.addRule(
        makeRule({ id: 'r2', group: { logic: 'OR', conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition] } }),
      ),
    );
    expect(result.current.rules).toHaveLength(1);
  });

  it('blocks duplicate rule even when conditions carry different ids', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() =>
      result.current.addRule(
        makeRule({ id: 'r1', group: { logic: 'AND', conditions: [{ kind: 'price', id: 'cond-a', operator: '>', value: 185 } as PriceCondition] } }),
      ),
    );
    act(() =>
      result.current.addRule(
        makeRule({ id: 'r2', group: { logic: 'AND', conditions: [{ kind: 'price', id: 'cond-b', operator: '>', value: 185 } as PriceCondition] } }),
      ),
    );
    // Same symbol/interval/operator/value — only the per-condition `id` differs.
    // Must still be treated as a duplicate, or every rule created through the UI
    // (which now generates a fresh id per condition) would defeat this check.
    expect(result.current.rules).toHaveLength(1);
  });

  it('updates a rule', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    act(() => result.current.updateRule('r1', { name: 'Updated' }));
    expect(result.current.rules[0].name).toBe('Updated');
  });

  it('updating a composite rule sends rule_type/composite_def in the PUT body, not group', async () => {
    // Regression: a composite rule's `group` is only ever the display placeholder
    // {logic:'AND', conditions:[]} (see _rule_to_dict on the backend). Sending that
    // placeholder as the PUT body's `group` on a plain toggle overwrites the real
    // composite_def on the server, silently corrupting the rule into a dead
    // standard rule with zero conditions.
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    global.fetch = fetchMock as unknown as typeof fetch;

    const compositeRule = makeRule({
      id: 'cmp1',
      rule_type: 'composite',
      composite_def: { primary: { model: 'OMM', to_state: 'Bull' }, confirmations: [] },
      group: { logic: 'AND', conditions: [] },
    });
    act(() => useChartAlertStore.setState({ rules: [compositeRule] }));
    act(() => useChartAlertStore.getState().updateRule('cmp1', { enabled: false }));

    await act(async () => {}); // flush the fire-and-forget fetch promise

    const putCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/alerts/rules/cmp1'));
    expect(putCall).toBeDefined();
    const body = JSON.parse(putCall![1].body as string);
    expect(body.rule_type).toBe('composite');
    expect(body.composite_def).toEqual({ primary: { model: 'OMM', to_state: 'Bull' }, confirmations: [] });
    expect(body.group).toBeUndefined();
  });

  it('deletes a rule and cascades to history', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule({ id: 'r1' })));
    act(() => result.current.addRule(makeRule({ id: 'r2', name: 'Rule B', group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<', value: 170 } as PriceCondition] } })));
    act(() => result.current.addHistory(makeHistory({ rule_id: 'r1' })));
    act(() => result.current.addHistory(makeHistory({ rule_id: 'r2', id: 'h2' })));
    act(() => result.current.deleteRule('r1'));
    expect(result.current.rules).toHaveLength(1);
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0].id).toBe('h2');
  });

  it('adds history entry with newSinceView increment', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    expect(result.current.history).toHaveLength(1);
    expect(result.current.newSinceView).toBe(1);
  });

  it('markViewed resets newSinceView to 0', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.addHistory(makeHistory({ id: 'h2' })));
    expect(result.current.newSinceView).toBe(2);
    act(() => result.current.markViewed());
    expect(result.current.newSinceView).toBe(0);
  });

  it('enforces history limit of 200 entries', () => {
    const { result } = renderHook(() => useChartAlertStore());
    for (let i = 0; i < 210; i++) {
      act(() => result.current.addHistory(makeHistory({ id: `h${i}` })));
    }
    expect(result.current.history).toHaveLength(HISTORY_LIMIT);
  });

  it('clears history', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.clearHistory());
    expect(result.current.history).toHaveLength(0);
  });

  it('dismisses history entry by id', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.dismissHistory('h1'));
    expect(result.current.history).toHaveLength(0);
  });

  it('pushToast adds a toast and dismissToast removes it', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.pushToast({ id: 't1', message: 'Alert!', timestamp: Date.now() }));
    expect(result.current.toasts).toHaveLength(1);
    act(() => result.current.dismissToast('t1'));
    expect(result.current.toasts).toHaveLength(0);
  });
});
