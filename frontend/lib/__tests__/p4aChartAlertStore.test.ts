/**
 * P4a (chart alert rules) -- A1 body builder, A2 refusal mark, A3 toggle PATCH,
 * A4 last_triggered_at stamps. Plan:
 * docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md
 */
import { act } from '@testing-library/react';
import { useChartAlertStore, ruleBodyForApi } from '@/lib/chartAlertStore';
import type { AlertRule, PriceCondition } from '@/types/alerts';

const rule = (o: Partial<AlertRule> = {}): AlertRule => ({
  id: 'r1', name: 'Test Rule', symbol: 'AAPL', interval: '15min', enabled: true,
  group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition] },
  cooldown_minutes: 60, expiry_date: null, created_at: '2026-09-01T00:00:00', last_triggered_at: null,
  ...o,
});
const composite = (o: Partial<AlertRule> = {}) => rule({
  id: 'c1', rule_type: 'composite',
  composite_def: { primary: { model: 'OMM', to_state: 'Bull' }, confirmations: [] },
  group: { logic: 'AND', conditions: [] }, ...o,
});
const res = (status: number, body: unknown = {}) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
const calls = () => (global.fetch as jest.Mock).mock.calls as [string, RequestInit | undefined][];
const bodyOf = (method: string, urlPart: string) => {
  const c = calls().find(([u, i]) => (i?.method ?? 'GET') === method && String(u).includes(urlPart));
  return c ? JSON.parse(c[1]!.body as string) : undefined;
};
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

/** GET returns `server`; POST answers with `post`. */
function mockServer(server: AlertRule[], post: Response | 'throw' = res(201)) {
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    const m = init?.method ?? 'GET';
    if (m === 'GET') return Promise.resolve(res(200, server));
    if (m === 'POST') return post === 'throw' ? Promise.reject(new Error('offline')) : Promise.resolve(post);
    return Promise.resolve(res(200));
  }) as unknown as typeof fetch;
}

const originalFetch = global.fetch;
beforeEach(() => { act(() => { useChartAlertStore.setState({ rules: [], unsavedRules: {} } as never); }); });
afterEach(() => { global.fetch = originalFetch; });

describe('A1 -- one body builder for POST and PUT', () => {
  it('a composite body carries rule_type/composite_def and no group; a standard one carries group', () => {
    const c = ruleBodyForApi(composite());
    expect(c).toMatchObject({ rule_type: 'composite', composite_def: { primary: { model: 'OMM', to_state: 'Bull' }, confirmations: [] } });
    expect(c.group).toBeUndefined();
    const s = ruleBodyForApi(rule());
    expect(s.group).toEqual(rule().group);
    expect(s.rule_type).toBeUndefined();
  });

  it('syncRules re-POSTs a local-only COMPOSITE rule intact, with its client id', async () => {
    act(() => { useChartAlertStore.setState({ rules: [composite()] } as never); });
    mockServer([]);
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    const body = bodyOf('POST', '/alerts/rules');
    expect(body).toMatchObject({ id: 'c1', rule_type: 'composite' });
    expect(body.composite_def).toEqual(composite().composite_def);
    expect(body.group).toBeUndefined();
  });
});

describe('A2 -- a refused re-POST keeps the rule and marks it', () => {
  it('422 with a string detail: kept locally, marked with the detail', async () => {
    act(() => { useChartAlertStore.setState({ rules: [composite()] } as never); });
    mockServer([], res(422, { detail: 'HMM_intraday needs an intraday interval' }));
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    const s = useChartAlertStore.getState();
    expect(s.rules.map((r) => r.id)).toEqual(['c1']);
    expect(s.unsavedRules).toEqual({ c1: 'HMM_intraday needs an intraday interval' });
  });

  it('a pydantic array detail is stored as text', async () => {
    act(() => { useChartAlertStore.setState({ rules: [rule()] } as never); });
    mockServer([], res(422, { detail: [{ loc: ['body', 'name'], msg: 'field required' }] }));
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(typeof useChartAlertStore.getState().unsavedRules.r1).toBe('string');
    expect(useChartAlertStore.getState().unsavedRules.r1).toContain('field required');
  });

  it.each([[res(201)], [res(409)]])('an accepted POST clears an old mark', async (post) => {
    act(() => { useChartAlertStore.setState({ rules: [rule()], unsavedRules: { r1: 'old' } } as never); });
    mockServer([], post);
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it('offline (network error or 5xx) marks nothing new and keeps an existing mark', async () => {
    act(() => { useChartAlertStore.setState({ rules: [rule(), rule({ id: 'r2' })], unsavedRules: { r2: 'old' } } as never); });
    mockServer([], 'throw');
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ r2: 'old' });
    mockServer([], res(503));
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ r2: 'old' });
  });

  it('addRule marks a refusal too', async () => {
    mockServer([], res(422, { detail: 'nope' }));
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    await flush();
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ n1: 'nope' });
  });

  it('the mark is not persisted', () => {
    const opts = (useChartAlertStore as unknown as { persist: { getOptions: () => { partialize: (s: unknown) => Record<string, unknown> } } }).persist.getOptions();
    expect(Object.keys(opts.partialize(useChartAlertStore.getState()))).not.toContain('unsavedRules');
  });
});

describe('A3 -- the toggle PATCHes {enabled} only', () => {
  it('sends PATCH with exactly {enabled}, never PUT, whatever the local interval', async () => {
    global.fetch = jest.fn().mockResolvedValue(res(200)) as unknown as typeof fetch;
    act(() => { useChartAlertStore.setState({ rules: [composite({ interval: '1D' })] } as never); });
    act(() => { useChartAlertStore.getState().setRuleEnabled('c1', false); });
    await flush();
    expect(useChartAlertStore.getState().rules[0]!.enabled).toBe(false);
    expect(calls().some(([, i]) => i?.method === 'PUT')).toBe(false);
    expect(bodyOf('PATCH', '/alerts/rules/c1')).toEqual({ enabled: false });
  });
});

describe('A4 -- last_triggered_at stamps', () => {
  it('persist: false (the backend already wrote it) sends nothing', async () => {
    global.fetch = jest.fn().mockResolvedValue(res(200)) as unknown as typeof fetch;
    act(() => { useChartAlertStore.setState({ rules: [rule()] } as never); });
    act(() => { useChartAlertStore.getState().stampRuleTriggered('r1', '2026-09-26T14:00:00.000Z', { persist: false }); });
    await flush();
    expect(useChartAlertStore.getState().rules[0]!.last_triggered_at).toBe('2026-09-26T14:00:00.000Z');
    expect(calls()).toHaveLength(0);
  });

  it('persist: true PATCHes exactly {last_triggered_at} with the stamp UNCHANGED', async () => {
    global.fetch = jest.fn().mockResolvedValue(res(200)) as unknown as typeof fetch;
    act(() => { useChartAlertStore.setState({ rules: [rule()] } as never); });
    act(() => { useChartAlertStore.getState().stampRuleTriggered('r1', '2026-09-26T14:00:00.000Z', { persist: true }); });
    await flush();
    expect(bodyOf('PATCH', '/alerts/rules/r1')).toEqual({ last_triggered_at: '2026-09-26T14:00:00.000Z' });
    expect(calls().some(([, i]) => i?.method === 'PUT')).toBe(false);
  });
});
