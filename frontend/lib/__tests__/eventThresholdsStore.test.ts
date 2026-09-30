/*
 * eventThresholdsStore holds ONLY validated backend values (decision
 * DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29): a failed or malformed fetch
 * clears the record, and only the latest request may write.
 */
import {
  useEventThresholdsStore, parseEventThresholds, getEventWindow,
} from '@/lib/eventThresholdsStore';
import { api } from '@/lib/api';
import { EVENT_SHIPPED } from '@/lib/testFixtures/thresholds';

jest.mock('@/lib/api', () => ({ api: { getEventThresholds: jest.fn() } }));
const get = api.getEventThresholds as jest.Mock;
const state = () => useEventThresholdsStore.getState();

/** A promise the test resolves or rejects by hand. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const OTHER = {
  Intraday: { reject_days: 2, caution_days: 4 },
  Swing:    { reject_days: 5, caution_days: 10 },
  Position: { reject_days: 7, caution_days: 30 },
};

beforeEach(() => {
  get.mockReset();
  useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
});

describe('eventThresholdsStore', () => {
  it('E1: a good payload gives ready, the parsed record and no error', async () => {
    get.mockResolvedValue(EVENT_SHIPPED);
    await state().fetch();
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', EVENT_SHIPPED, null]);
  });

  it('E2: a rejection clears a record that was ready, and keeps the message', async () => {
    get.mockResolvedValue(EVENT_SHIPPED);
    await state().fetch();
    get.mockRejectedValue(new Error('GET /api/config/event-thresholds → 500 Internal Server Error'));
    await state().fetch();
    expect(state().thresholds).toBeNull();
    expect(state().status).toBe('failed');
    expect(state().error).toContain('GET /api/config/event-thresholds → 500');
  });

  it.each([
    ['Swing missing',          { Intraday: EVENT_SHIPPED.Intraday, Position: EVENT_SHIPPED.Position }, /^Swing: /],
    ['a string day count',     { ...EVENT_SHIPPED, Swing: { reject_days: 21, caution_days: '45' } }, /^Swing\.caution_days: /],
    ['reject above caution',   { ...EVENT_SHIPPED, Swing: { reject_days: 50, caution_days: 45 } }, /^Swing: reject_days \(50\) exceeds caution_days \(45\)/],
    ['NaN',                    { ...EVENT_SHIPPED, Position: { reject_days: NaN, caution_days: 60 } }, /^Position\.reject_days: /],
    ['a negative day count',   { ...EVENT_SHIPPED, Intraday: { reject_days: -1, caution_days: 3 } }, /^Intraday\.reject_days: /],
    ['a non-object',           'nope', /expected an object/],
    ['null',                   null, /expected an object/],
  ])('E3: refuses a malformed payload (%s), naming the path', async (_n, payload, msg) => {
    get.mockResolvedValue(EVENT_SHIPPED);
    await state().fetch();
    get.mockResolvedValue(payload);
    await state().fetch();
    expect(state().thresholds).toBeNull();
    expect(state().status).toBe('failed');
    expect(state().error).toMatch(msg);
  });

  it('E4: a failure followed by a success recovers to ready', async () => {
    get.mockRejectedValueOnce(new Error('network down')).mockResolvedValueOnce(OTHER);
    await state().fetch();
    expect(state().status).toBe('failed');
    await state().fetch();
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', OTHER, null]);
  });

  it.each([
    ['succeeded', (d: ReturnType<typeof deferred<unknown>>) => d.resolve(OTHER)],
    ['failed',    (d: ReturnType<typeof deferred<unknown>>) => d.reject(new Error('stale failure'))],
  ])('E5: a stale response that %s never overwrites a newer one', async (_n, settleA) => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    get.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const pa = state().fetch();
    const pb = state().fetch();
    b.resolve(EVENT_SHIPPED);
    await pb;
    settleA(a);
    await pa;
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', EVENT_SHIPPED, null]);
  });

  it('E6: a re-fetch in flight keeps the last good record on screen', async () => {
    get.mockResolvedValue(EVENT_SHIPPED);
    await state().fetch();
    const d = deferred<unknown>();
    get.mockReturnValueOnce(d.promise);
    const p = state().fetch();
    expect([state().status, state().thresholds]).toEqual(['loading', EVENT_SHIPPED]);
    d.resolve(OTHER);
    await p;
    expect(state().thresholds).toEqual(OTHER);
  });

  it('E7: getEventWindow returns exactly the record\'s window', () => {
    const t = parseEventThresholds(OTHER);
    expect(getEventWindow('Intraday', t)).toBe(t.Intraday);
    expect(getEventWindow('Swing', t)).toBe(t.Swing);
    expect(getEventWindow('Position', t)).toBe(t.Position);
  });

  it('ignores extra keys, and the shipped YAML values pass', () => {
    expect(parseEventThresholds({ ...EVENT_SHIPPED, Weekly: { x: 1 } })).toEqual(EVENT_SHIPPED);
  });
});
