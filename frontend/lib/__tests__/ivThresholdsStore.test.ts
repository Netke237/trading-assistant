/*
 * ivThresholdsStore holds ONLY validated backend values (decision
 * DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29), plus Settings' session override
 * layer, which a re-fetch never touches.
 */
import {
  useIvThresholdsStore, parseIvThresholds, effectiveIvThresholds, ivOverrideFor,
  getIvPassMax, getIvCautionMax,
} from '@/lib/ivThresholdsStore';
import { api } from '@/lib/api';
import { IV_SHIPPED } from '@/lib/testFixtures/thresholds';

jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn() } }));
const get = api.getIvThresholds as jest.Mock;
const state = () => useIvThresholdsStore.getState();

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const OTHER = {
  ...IV_SHIPPED,
  Swing: { abs_pass_max: 20, abs_caution_max: 30, rank_pass_max: 25, rank_caution_max: 35 },
};
const effective = () => effectiveIvThresholds(state().thresholds, state().overrides);

beforeEach(() => {
  get.mockReset();
  useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
});

describe('ivThresholdsStore', () => {
  it('I1: a good payload gives ready, the parsed record and no error', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', IV_SHIPPED, null]);
  });

  it('I2: a rejection clears a record that was ready, and keeps the message', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    get.mockRejectedValue(new Error('GET /api/config/iv-thresholds → 500 Internal Server Error'));
    await state().fetch();
    expect(state().thresholds).toBeNull();
    expect(state().status).toBe('failed');
    expect(state().error).toContain('GET /api/config/iv-thresholds → 500');
  });

  const swingNoAbsPass: Partial<typeof IV_SHIPPED.Swing> = { ...IV_SHIPPED.Swing };
  delete swingNoAbsPass.abs_pass_max;
  it.each([
    ['Position missing',        { Intraday: IV_SHIPPED.Intraday, Swing: IV_SHIPPED.Swing }, /^Position: /],
    ['an ABSENT key (not null)', { ...IV_SHIPPED, Swing: swingNoAbsPass }, /^Swing\.abs_pass_max: missing/],
    ['pass null, caution 40',   { ...IV_SHIPPED, Swing: { ...IV_SHIPPED.Swing, rank_pass_max: null, rank_caution_max: 40 } }, /^Swing\.rank_pass_max: null/],
    ['pass above caution',      { ...IV_SHIPPED, Swing: { ...IV_SHIPPED.Swing, abs_pass_max: 60, abs_caution_max: 55 } }, /^Swing\.abs_pass_max \(60\) exceeds/],
    ['101',                     { ...IV_SHIPPED, Position: { ...IV_SHIPPED.Position, abs_caution_max: 101 } }, /^Position\.abs_caution_max: 101 is outside/],
    ['a string',                { ...IV_SHIPPED, Swing: { ...IV_SHIPPED.Swing, abs_pass_max: '34' } }, /^Swing\.abs_pass_max: expected a number or null/],
    ['NaN',                     { ...IV_SHIPPED, Swing: { ...IV_SHIPPED.Swing, abs_pass_max: NaN } }, /^Swing\.abs_pass_max: /],
    ['a non-object',            42, /expected an object/],
  ])('I3: refuses a malformed payload (%s), naming the path', async (_n, payload, msg) => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    get.mockResolvedValue(payload);
    await state().fetch();
    expect(state().thresholds).toBeNull();
    expect(state().status).toBe('failed');
    expect(state().error).toMatch(msg);
  });

  it('I4: a failure followed by a success recovers to ready', async () => {
    get.mockRejectedValueOnce(new Error('network down')).mockResolvedValueOnce(OTHER);
    await state().fetch();
    expect(state().status).toBe('failed');
    await state().fetch();
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', OTHER, null]);
  });

  it.each([
    ['succeeded', (d: ReturnType<typeof deferred<unknown>>) => d.resolve(OTHER)],
    ['failed',    (d: ReturnType<typeof deferred<unknown>>) => d.reject(new Error('stale failure'))],
  ])('I5: a stale response that %s never overwrites a newer one', async (_n, settleA) => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    get.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const pa = state().fetch();
    const pb = state().fetch();
    b.resolve(IV_SHIPPED);
    await pb;
    settleA(a);
    await pa;
    expect([state().status, state().thresholds, state().error]).toEqual(['ready', IV_SHIPPED, null]);
  });

  it('I6: a re-fetch in flight keeps the last good record on screen', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    const d = deferred<unknown>();
    get.mockReturnValueOnce(d.promise);
    const p = state().fetch();
    expect([state().status, state().thresholds]).toEqual(['loading', IV_SHIPPED]);
    d.resolve(OTHER);
    await p;
    expect(state().thresholds).toEqual(OTHER);
  });

  it('I7: an override survives a successful re-fetch and is applied', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    state().setAbsPassOverride('Swing', 50);
    await state().fetch();
    expect(state().overrides).toEqual({ Swing: { abs_pass_max: 50 } });
    expect(effective()?.Swing.abs_pass_max).toBe(50);
    // Only the absolute pass ceiling moves; everything else is the fetched record.
    expect(effective()?.Swing).toEqual({ ...IV_SHIPPED.Swing, abs_pass_max: 50 });
    expect(effective()?.Position).toEqual(IV_SHIPPED.Position);
    expect(state().thresholds).toEqual(IV_SHIPPED);
  });

  it('I8: a failed re-fetch keeps the override, but there is no effective record', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    state().setAbsPassOverride('Position', 60);
    get.mockRejectedValue(new Error('down'));
    await state().fetch();
    expect(state().overrides).toEqual({ Position: { abs_pass_max: 60 } });
    expect(effective()).toBeNull();
    expect(ivOverrideFor('Position', state().thresholds, state().overrides)).toBeNull();
  });

  it('I9: an override on a horizon whose YAML has no gate is not applied', async () => {
    const noSwingGate = {
      ...IV_SHIPPED,
      Swing: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: 34, rank_caution_max: 55 },
    };
    get.mockResolvedValue(noSwingGate);
    await state().fetch();
    state().setAbsPassOverride('Swing', 50);
    expect(effective()?.Swing.abs_pass_max).toBeNull();
    expect(ivOverrideFor('Swing', state().thresholds, state().overrides)).toBeNull();
  });

  it('I10: clearOverrides restores the fetched value', async () => {
    get.mockResolvedValue(IV_SHIPPED);
    await state().fetch();
    state().setAbsPassOverride('Swing', 50);
    expect(ivOverrideFor('Swing', state().thresholds, state().overrides)).toEqual({ value: 50, yaml: 34 });
    state().clearOverrides();
    expect(effective()?.Swing.abs_pass_max).toBe(34);
    expect(ivOverrideFor('Swing', state().thresholds, state().overrides)).toBeNull();
  });

  it('I11: getIvPassMax / getIvCautionMax read only the record; null means no gate', () => {
    const t = parseIvThresholds(OTHER);
    expect(getIvPassMax('Swing', t, 'absolute')).toBe(20);
    expect(getIvCautionMax('Swing', t, 'absolute')).toBe(30);
    expect(getIvPassMax('Swing', t, 'rank')).toBe(25);
    expect(getIvCautionMax('Swing', t, 'rank')).toBe(35);
    expect(getIvPassMax('Intraday', t, 'absolute')).toBeNull();
    expect(getIvCautionMax('Intraday', t, 'rank')).toBeNull();
    expect(getIvPassMax('Swing', t, 'none')).toBeNull();
  });

  it('the shipped YAML values pass, and extra keys are ignored', () => {
    expect(parseIvThresholds({ ...IV_SHIPPED, Weekly: {} })).toEqual(IV_SHIPPED);
  });
});
