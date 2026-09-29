/**
 * CHART-RULES-SYNC-CONCURRENCY (piece B) -- syncRules against concurrent
 * addRule / deleteRule / edits and overlapping syncs. Plan:
 * docs/superpowers/plans/2026-09-28-chart-rules-sync-concurrency-plan.md
 */
import { act } from '@testing-library/react';
import {
  useChartAlertStore, OFFLINE_SAVE_REASON, SYNC_FETCH_TIMEOUT_MS, __resetChartAlertSyncGenForTests,
} from '@/lib/chartAlertStore';
import type { AlertRule, PriceCondition } from '@/types/alerts';

const KEY = 'bamendjou:alert-tombstones';

/** A rule whose symbol is its id, so addRule never sees two as duplicates. */
const rule = (id: string, o: Partial<AlertRule> = {}): AlertRule => ({
  id, name: `Rule ${id}`, symbol: id.toUpperCase(), interval: '15min', enabled: true,
  group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition] },
  cooldown_minutes: 60, expiry_date: null, created_at: '2026-09-01T00:00:00', last_triggered_at: null,
  ...o,
});
const res = (status: number, body: unknown = {}) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;

/** Microtask-only flush: works under real and fake timers alike. */
const flush = () => act(async () => { for (let i = 0; i < 50; i++) await Promise.resolve(); });

type Answer = Response | 'throw';

/** A fetch whose GETs (optionally) and POSTs are answered by the test, and
 *  whose DELETEs answer `del` (default 200) and are recorded by id. */
function harness(opts: { manualGet?: boolean; del?: Answer | 'never' | Answer[] } = {}) {
  let server: AlertRule[] = [];
  const gets: { resolve: (r: Answer) => void; signal?: AbortSignal }[] = [];
  const posts: { id: string; init: RequestInit; resolve: (r: Answer) => void }[] = [];
  const deletes: string[] = [];
  const postIds: string[] = [];
  let getCount = 0;
  const settle = (r: Answer) => (r === 'throw' ? Promise.reject(new Error('offline')) : Promise.resolve(r));
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    const m = init?.method ?? 'GET';
    if (m === 'GET') {
      getCount += 1;
      if (!opts.manualGet) return Promise.resolve(res(200, server));
      return new Promise<Response>((ok, fail) => {
        gets.push({ signal: init?.signal ?? undefined, resolve: (r) => (r === 'throw' ? fail(new Error('offline')) : ok(r)) });
      });
    }
    if (m === 'POST') {
      const id = JSON.parse(init!.body as string).id as string;
      postIds.push(id);
      return new Promise<Response>((ok, fail) => {
        posts.push({ id, init: init!, resolve: (r) => (r === 'throw' ? fail(new Error('offline')) : ok(r)) });
      });
    }
    if (m === 'DELETE') {
      deletes.push(decodeURIComponent(String(url).split('/').pop()!));
      const d = opts.del ?? res(200);
      if (d === 'never') return new Promise<Response>(() => {});
      if (Array.isArray(d)) return settle(d[deletes.length - 1] ?? res(200));
      return settle(d);
    }
    return Promise.resolve(res(200));
  }) as unknown as typeof fetch;
  return {
    setServer: (s: AlertRule[]) => { server = s; },
    gets, posts, deletes, postIds,
    getCount: () => getCount,
    /** Answer the oldest (or newest) pending POST for `id`. */
    answer: async (id: string, r: Answer, pick: 'first' | 'last' = 'first') => {
      const i = pick === 'first' ? posts.findIndex((p) => p.id === id) : posts.map((p) => p.id).lastIndexOf(id);
      if (i < 0) throw new Error(`no pending POST for ${id}`);
      posts.splice(i, 1)[0]!.resolve(r);
      await flush();
    },
    answerGet: async (r: Answer = res(200, server)) => {
      const g = gets.shift();
      if (!g) throw new Error('no pending GET');
      g.resolve(r);
      await flush();
    },
  };
}

const st = () => useChartAlertStore.getState();
const ids = () => st().rules.map((r) => r.id);
const setRules = (rules: AlertRule[], unsavedRules: Record<string, string> = {}) =>
  act(() => { useChartAlertStore.setState({ rules, unsavedRules } as never); });
const count = (xs: string[], id: string) => xs.filter((x) => x === id).length;
const stored = () => JSON.parse(localStorage.getItem(KEY) ?? 'null');

const originalFetch = global.fetch;
beforeEach(() => {
  __resetChartAlertSyncGenForTests();
  localStorage.removeItem(KEY);
  act(() => { useChartAlertStore.setState({ rules: [], unsavedRules: {}, history: [] } as never); });
});
afterEach(() => {
  global.fetch = originalFetch;
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe('T1 (G1) -- a rule added mid-sync is kept', () => {
  it.each([
    ['offline before the final write', 'before' as const, 'throw' as Answer, { n1: OFFLINE_SAVE_REASON }],
    ['offline after the final write', 'after' as const, 'throw' as Answer, { n1: OFFLINE_SAVE_REASON }],
    ['201', 'before' as const, res(201) as Answer, {}],
  ])('%s', async (_l, when, post, marks) => {
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().addRule(rule('n1')); });
    if (when === 'before') await h.answer('n1', post);
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    if (when === 'after') await h.answer('n1', post);
    expect(ids()).toEqual(['r1', 'n1']);
    expect(st().unsavedRules).toEqual(marks);
  });
});

describe('T2 (G2) -- a rule deleted mid-sync stays deleted', () => {
  it('(i) a local-only snapshot rule', async () => {
    const h = harness();
    setRules([rule('r1'), rule('r2')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().deleteRule('r1'); });
    await h.answer('r1', res(201));
    await h.answer('r2', res(201));
    await act(async () => { await sync; });
    expect(ids()).toEqual(['r2']);
    expect(st().unsavedRules).toEqual({});
  });

  it('(ii) a server snapshot rule', async () => {
    const h = harness();
    h.setServer([rule('s1')]);
    setRules([rule('s1'), rule('r1')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().deleteRule('s1'); });
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(ids()).toEqual(['r1']);
    expect(st().unsavedRules).toEqual({});
  });

  it('(iii) a rule a GET lists, deleted after it entered rules, while the GET is in flight', async () => {
    const h = harness({ manualGet: true });
    setRules([rule('s2')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().deleteRule('s2'); });
    await h.answerGet(res(200, [rule('s2')]));
    await act(async () => { await sync; });
    expect(ids()).toEqual([]);
    expect(st().unsavedRules).toEqual({});
    expect(count(h.deletes, 's2')).toBe(2); // deleteRule's + the sync's
  });
});

describe('T3 (G2) -- no DELETE answer brings a deleted rule back', () => {
  it.each([
    ['404', res(404) as Answer | 'never'],
    ['a network error', 'throw' as const],
    ['never settles', 'never' as const],
  ])('DELETE %s, then a sync whose GET still lists the rule', async (_l, del) => {
    const h = harness({ del });
    h.setServer([rule('r1')]);
    setRules([rule('r1')]);
    act(() => { st().deleteRule('r1'); });
    await flush();
    await act(async () => { await st().syncRules(); });
    expect(ids()).toEqual([]);
    expect(st().unsavedRules).toEqual({});
    expect(count(h.deletes, 'r1')).toBe(2);
  });

  it('two DELETEs settle 2xx then a network error', async () => {
    const h = harness({ del: [res(200), 'throw'] });
    h.setServer([rule('r1')]);
    setRules([rule('r1')]);
    act(() => { st().deleteRule('r1'); st().deleteRule('r1'); });
    await flush();
    await act(async () => { await st().syncRules(); });
    expect(ids()).toEqual([]);
    expect(count(h.deletes, 'r1')).toBe(3);
  });
});

describe('T4 (G3) -- a POST in flight when the rule is deleted is answered with a DELETE', () => {
  it.each([
    ['201', res(201) as Answer, 2],
    ['409', res(409) as Answer, 2],
    ['offline', 'throw' as Answer, 2],
    ['refused', res(422, { detail: 'nope' }) as Answer, 1],
  ])('addRule POST settles %s', async (_l, post, deletes) => {
    const h = harness();
    act(() => { st().addRule(rule('n1')); });
    act(() => { st().deleteRule('n1'); });
    expect(count(h.deletes, 'n1')).toBe(1);
    await h.answer('n1', post);
    expect(count(h.deletes, 'n1')).toBe(deletes);
    expect(ids()).toEqual([]);
    expect(st().unsavedRules).toEqual({});
  });

  it.each([
    ['201', res(201) as Answer, 2],
    ['409', res(409) as Answer, 2],
    ['offline', 'throw' as Answer, 2],
    ['refused', res(422, { detail: 'nope' }) as Answer, 1],
  ])('sync re-POST settles %s', async (_l, post, deletes) => {
    const h = harness();
    setRules([rule('n1')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().deleteRule('n1'); });
    await h.answer('n1', post);
    await act(async () => { await sync; });
    expect(count(h.deletes, 'n1')).toBe(deletes);
    expect(ids()).toEqual([]);
    expect(st().unsavedRules).toEqual({});
  });

  it('T4b: a snapshot rule deleted before its turn is never POSTed', async () => {
    const h = harness();
    setRules([rule('r1'), rule('r2')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().deleteRule('r2'); });
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(h.postIds).toEqual(['r1']);
    expect(ids()).toEqual(['r1']);
  });
});

describe('T4c -- tombstones survive a reload; late re-POST answers', () => {
  it('a simulated reload keeps the tombstone', async () => {
    const h = harness();
    setRules([rule('r1')]);
    act(() => { st().deleteRule('r1'); });
    __resetChartAlertSyncGenForTests(); // memory only; storage kept
    h.setServer([rule('r1')]);
    await act(async () => { await st().syncRules(); });
    expect(ids()).toEqual([]);
    expect(count(h.deletes, 'r1')).toBe(2);
  });

  it('a re-POST past the deadline that later settles 201 for a deleted rule -> DELETE', async () => {
    jest.useFakeTimers();
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    await act(async () => { await jest.advanceTimersByTimeAsync(SYNC_FETCH_TIMEOUT_MS); });
    await act(async () => { await sync; });
    expect(st().unsavedRules).toEqual({ r1: OFFLINE_SAVE_REASON });
    act(() => { st().deleteRule('r1'); });
    expect(count(h.deletes, 'r1')).toBe(1);
    await h.answer('r1', res(201));
    expect(count(h.deletes, 'r1')).toBe(2);
  });

  it('a late 201 for a rule not deleted clears its offline mark', async () => {
    jest.useFakeTimers();
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    await act(async () => { await jest.advanceTimersByTimeAsync(SYNC_FETCH_TIMEOUT_MS); });
    await act(async () => { await sync; });
    expect(st().unsavedRules).toEqual({ r1: OFFLINE_SAVE_REASON });
    await h.answer('r1', res(201));
    expect(st().unsavedRules).toEqual({});
    expect(h.deletes).toEqual([]);
    expect(ids()).toEqual(['r1']);
  });
});

describe('T4d -- tombstones written by another tab', () => {
  it("this tab's deleteRule keeps another tab's tombstones", () => {
    harness();
    localStorage.setItem(KEY, JSON.stringify(['x', 'y']));
    act(() => { st().deleteRule('z'); });
    expect(stored()).toEqual(['x', 'y', 'z']);
  });

  it('a tombstone written while a re-POST is pending: 201 -> DELETE, and not in rules', async () => {
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    localStorage.setItem(KEY, JSON.stringify(['r1']));
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(count(h.deletes, 'r1')).toBe(1);
    expect(ids()).toEqual([]);
  });

  it('(i) a server rule tombstoned between the GET and the final write', async () => {
    const h = harness();
    h.setServer([rule('s1')]);
    setRules([rule('s1'), rule('r1')]);
    const sync = st().syncRules();
    await flush();
    localStorage.setItem(KEY, JSON.stringify(['s1']));
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(ids()).toEqual(['r1']);
  });

  it('(ii) a re-POST past the deadline, tombstoned in storage only, late 201 -> DELETE', async () => {
    jest.useFakeTimers();
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    await act(async () => { await jest.advanceTimersByTimeAsync(SYNC_FETCH_TIMEOUT_MS); });
    await act(async () => { await sync; });
    localStorage.setItem(KEY, JSON.stringify(['r1']));
    await h.answer('r1', res(201));
    expect(count(h.deletes, 'r1')).toBe(1);
  });

  it('(iii) 501 deletes keep the 500 most recent, oldest first', () => {
    harness();
    act(() => { for (let i = 0; i <= 500; i++) st().deleteRule(`d${i}`); });
    const s = stored() as string[];
    expect(s).toHaveLength(500);
    expect(s[0]).toBe('d1');
    expect(s[499]).toBe('d500');
  });

  it.each([['not json'], ['{}']])('(iv) stored %s: deleteRule still writes, and a sync drops the id', async (bad) => {
    const h = harness();
    localStorage.setItem(KEY, bad);
    act(() => { st().deleteRule('x'); });
    expect(stored()).toEqual(['x']);
    __resetChartAlertSyncGenForTests();
    h.setServer([rule('x')]);
    await act(async () => { await st().syncRules(); });
    expect(ids()).toEqual([]);
  });

  it('(v) a rule added mid-sync, tombstoned in storage before the final write', async () => {
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().addRule(rule('n1')); st().addRule(rule('n2')); });
    localStorage.setItem(KEY, JSON.stringify(['n1']));
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(ids()).toEqual(['r1', 'n2']);
  });
});

describe('T5/T6 (G4) -- sync runs are serial', () => {
  it('T5: the second GET waits for the first run; a third call shares the follow-up', async () => {
    const h = harness({ manualGet: true });
    let done = 0;
    const calls = [st().syncRules(), st().syncRules(), st().syncRules()].map((p) => p.then(() => { done += 1; }));
    await flush();
    expect(h.getCount()).toBe(1);
    await h.answerGet(res(200, []));
    expect(h.getCount()).toBe(2);
    await h.answerGet(res(200, []));
    await act(async () => { await Promise.all(calls); });
    expect(done).toBe(3);
    expect(h.getCount()).toBe(2);
  });

  it('T6: the queued run proves n1 saved after the first run marked it offline', async () => {
    const h = harness();
    setRules([rule('n1')]);
    const a = st().syncRules();
    await flush();
    const b = st().syncRules();
    await h.answer('n1', 'throw');
    await act(async () => { await a; });
    await h.answer('n1', res(201));
    await act(async () => { await b; });
    expect(h.getCount()).toBe(2);
    expect(ids()).toEqual(['n1']);
    expect(st().unsavedRules).toEqual({});
  });
});

describe('T7 (G5) -- bounded waits', () => {
  it('a GET that never settles: the call resolves after the timeout, and the queued call sends its GET', async () => {
    jest.useFakeTimers();
    const h = harness({ manualGet: true });
    setRules([rule('r1')]);
    let aDone = false;
    const a = st().syncRules().then(() => { aDone = true; });
    const b = st().syncRules();
    await flush();
    expect(h.getCount()).toBe(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(SYNC_FETCH_TIMEOUT_MS); });
    await act(async () => { await a; });
    expect(aDone).toBe(true);
    expect(h.gets[0]!.signal?.aborted).toBe(true);
    expect(h.getCount()).toBe(2);
    expect(ids()).toEqual(['r1']); // the timed-out run wrote nothing
    h.gets.shift(); // the aborted first GET
    await h.answerGet(res(200, [rule('r1')]));
    await act(async () => { await b; });
  });

  it('a re-POST that never settles: marked offline after the timeout, POST not aborted', async () => {
    jest.useFakeTimers();
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    await act(async () => { await jest.advanceTimersByTimeAsync(SYNC_FETCH_TIMEOUT_MS); });
    await act(async () => { await sync; });
    expect(st().unsavedRules).toEqual({ r1: OFFLINE_SAVE_REASON });
    expect(h.posts[0]!.init.signal).toBeUndefined();
  });

  it('a run whose final write throws does not block the next call', async () => {
    const h = harness();
    h.setServer([rule('s1')]);
    let thrown = false;
    const real = Storage.prototype.setItem;
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, k: string, v: string) {
      if (k === 'bamendjou:alerts' && !thrown) { thrown = true; throw new Error('QuotaExceededError'); }
      return real.call(this, k, v);
    });
    await act(async () => { await st().syncRules(); });
    expect(thrown).toBe(true);
    h.setServer([rule('s1'), rule('s2')]);
    await act(async () => { await st().syncRules(); });
    expect(h.getCount()).toBe(2);
    expect(ids()).toEqual(['s1', 's2']);
  });
});

describe('T8 (G6) -- a local edit made mid-sync survives the final write', () => {
  it('updateRule and setRuleEnabled on a local-only rule', async () => {
    const h = harness();
    setRules([rule('r1')]);
    const sync = st().syncRules();
    await flush();
    act(() => { st().updateRule('r1', { name: 'edited' }); });
    act(() => { st().setRuleEnabled('r1', false); });
    await h.answer('r1', res(201));
    await act(async () => { await sync; });
    expect(st().rules[0]).toMatchObject({ id: 'r1', name: 'edited', enabled: false });
  });
});
