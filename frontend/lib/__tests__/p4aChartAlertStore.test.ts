/**
 * P4a (chart alert rules) -- A1 body builder, A2 refusal mark, A3 toggle PATCH,
 * A4 last_triggered_at stamps. Plan:
 * docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md
 */
import { act } from '@testing-library/react';
import {
  useChartAlertStore, ruleBodyForApi, OFFLINE_SAVE_REASON, __resetChartAlertSyncGenForTests,
} from '@/lib/chartAlertStore';
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
beforeEach(() => {
  __resetChartAlertSyncGenForTests();
  act(() => { useChartAlertStore.setState({ rules: [], unsavedRules: {} } as never); });
});
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

  it('offline (network error or 5xx) marks OFFLINE_SAVE_REASON and keeps an existing mark verbatim', async () => {
    act(() => { useChartAlertStore.setState({ rules: [rule(), rule({ id: 'r2' })], unsavedRules: { r2: 'old' } } as never); });
    mockServer([], 'throw');
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ r1: OFFLINE_SAVE_REASON, r2: 'old' });
    act(() => { useChartAlertStore.setState({ unsavedRules: { r2: 'old' } } as never); });
    mockServer([], res(503));
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ r1: OFFLINE_SAVE_REASON, r2: 'old' });
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

/** A fetch whose POSTs to each id are answered by the test, one at a time. */
function manualServer(server: () => AlertRule[]) {
  const pending: { id: string; resolve: (r: Response | 'throw') => void }[] = [];
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    const m = init?.method ?? 'GET';
    if (m === 'GET') return Promise.resolve(res(200, server()));
    if (m === 'POST') {
      const id = JSON.parse(init!.body as string).id as string;
      return new Promise<Response>((ok, fail) => {
        pending.push({ id, resolve: (r) => (r === 'throw' ? fail(new Error('offline')) : ok(r)) });
      });
    }
    return Promise.resolve(res(200));
  }) as unknown as typeof fetch;
  /** Answer a pending POST for `id`: the oldest ('first', addRule's when a
   *  sync re-POSTs the same id later) or the newest ('last'). */
  return async (id: string, r: Response | 'throw', pick: 'first' | 'last' = 'first') => {
    const i = pick === 'first'
      ? pending.findIndex((p) => p.id === id)
      : pending.map((p) => p.id).lastIndexOf(id);
    if (i < 0) throw new Error(`no pending POST for ${id}`);
    pending.splice(i, 1)[0]!.resolve(r);
    await flush();
  };
}

describe('CHART-RULE-OFFLINE-SAVE-MARK -- an unconfirmed save is marked', () => {
  it('T1: addRule + network error or 503 marks OFFLINE_SAVE_REASON', async () => {
    mockServer([], 'throw');
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    await flush();
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ n1: OFFLINE_SAVE_REASON });
    act(() => { useChartAlertStore.setState({ rules: [], unsavedRules: {} } as never); });
    mockServer([], res(503));
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n2' })); });
    await flush();
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ n2: OFFLINE_SAVE_REASON });
  });

  it.each([[res(201)], [res(409)]])('T3: a later re-POST accepted clears an offline mark', async (post) => {
    act(() => { useChartAlertStore.setState({ rules: [rule()], unsavedRules: { r1: OFFLINE_SAVE_REASON } } as never); });
    mockServer([], post);
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it('T3: a sync whose GET returns the rule clears an offline mark', async () => {
    act(() => { useChartAlertStore.setState({ rules: [rule()], unsavedRules: { r1: OFFLINE_SAVE_REASON } } as never); });
    mockServer([rule()]);
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it.each([['throw' as const], [res(422, { detail: 'nope' })]])(
    'T4: a rule deleted before its POST settles leaves no key', async (post) => {
      const answer = manualServer(() => []);
      act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
      act(() => { useChartAlertStore.getState().deleteRule('n1'); });
      await answer('n1', post);
      expect(useChartAlertStore.getState().unsavedRules).toEqual({});
    },
  );

  it('T5c: a late offline addRule answer does not mark a rule a sync proved saved (GET lists it)', async () => {
    let server: AlertRule[] = [];
    const answer = manualServer(() => server);
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    server = [rule({ id: 'n1' })];
    await act(async () => { await useChartAlertStore.getState().syncRules(); });
    await answer('n1', 'throw');
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it('T5c: a late offline addRule answer does not mark a rule a sync re-POSTed with 201', async () => {
    const answer = manualServer(() => []);
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    const sync = useChartAlertStore.getState().syncRules();
    await flush();
    await answer('n1', res(201), 'last'); // the sync's re-POST
    await act(async () => { await sync; });
    await answer('n1', 'throw', 'first'); // addRule's, late
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it.each([
    ['201', res(201), {}],
    ['409', res(409), {}],
    ['201 over a prior refusal', res(201), { n1: 'old' }],
  ])('T5d: addRule settles %s after a sync marked it offline -> no key', async (_l, post, prior) => {
    const answer = manualServer(() => []);
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    act(() => { useChartAlertStore.setState({ unsavedRules: prior } as never); });
    const sync = useChartAlertStore.getState().syncRules();
    await flush();
    await answer('n1', 'throw', 'last');
    await act(async () => { await sync; });
    expect(useChartAlertStore.getState().unsavedRules.n1).toBeDefined();
    await answer('n1', post, 'first');
    expect(useChartAlertStore.getState().unsavedRules).toEqual({});
  });

  it.each([[true], [false]])('T5e: addRule 201 before the sync final write (%s) drops the sync offline mark', async (addRuleOk) => {
    const answer = manualServer(() => []);
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    act(() => { useChartAlertStore.setState((s) => ({ rules: [...s.rules, rule({ id: 'r2' })] })); });
    const sync = useChartAlertStore.getState().syncRules();
    await flush();
    await answer('n1', res(500), 'last'); // the sync's re-POST races addRule's insert
    if (addRuleOk) await answer('n1', res(201), 'first');
    await answer('r2', res(201)); // the sync's last re-POST -> its final write
    await act(async () => { await sync; });
    expect(useChartAlertStore.getState().unsavedRules).toEqual(addRuleOk ? {} : { n1: OFFLINE_SAVE_REASON });
  });

  it('T5c control: with no sync in between, the late offline answer does mark', async () => {
    const answer = manualServer(() => []);
    act(() => { useChartAlertStore.getState().addRule(rule({ id: 'n1' })); });
    await answer('n1', 'throw');
    expect(useChartAlertStore.getState().unsavedRules).toEqual({ n1: OFFLINE_SAVE_REASON });
  });
});
