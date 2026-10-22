import {
  buildGrading, compareWatchedRows, gradingKey, gradingToCtx, isValidGrading, isYamlGraded,
  localTodayIso, parseContractId, planContractGroups, resolveWatchedRows,
  type KeptGroupResult, type WatchedContractRow,
} from '@/lib/contractGrading';
import type { ContractGrading, OptionContract } from '@/types/domain';

// Dates relative to now: no test may start failing when a literal date passes.
const isoIn = (days: number) => localTodayIso(new Date(Date.now() + days * 86_400_000));
const E = isoIn(40);
const PAST = isoIn(-3);
const TODAY = localTodayIso();

const G: ContractGrading = { contract_rules: { min_volume: 20 }, hold_min_days: 20, hold_max_days: 25, stock_score: 72 };

function contract(id: string, over: Partial<OptionContract> = {}): OptionContract {
  const [symbol, strike, expiry, right] = id.split('|');
  return {
    id, symbol: symbol!, strike: Number(strike), expiry: expiry!, right: right as 'C' | 'P',
    dte: 40, dteTotal: 40, price: 2.5, delta: 0.45, theta: -0.05, ivRank: 40, spread: 0.1,
    volume: 100, score: 70, contractConfidence: 'PASS', ...over,
  } as OptionContract;
}

describe('parseContractId', () => {
  it('parses a valid id', () => {
    expect(parseContractId(`AAPL|187|${E}|C`)).toEqual({
      id: `AAPL|187|${E}|C`, symbol: 'AAPL', strike: 187, expiry: E, right: 'C',
    });
  });
  // EXACT-STRIKE ES-3: the strike is matched exactly (the backend sends exact
  // fractional strikes); 187.0 is the number 187.
  it('keeps a fractional strike exactly; 187.0 parses to 187', () => {
    expect(parseContractId(`AAPL|187.5|${E}|P`)).toMatchObject({ strike: 187.5 });
    expect(parseContractId(`AAPL|187.5|${E}|P`)).not.toHaveProperty('truncStrike');
    expect(parseContractId(`AAPL|187.0|${E}|C`)).toMatchObject({ strike: 187 });
  });
  it.each([
    ['3 parts', `AAPL|187|${E}`],
    ['5 parts', `AAPL|187|${E}|C|x`],
    ['bad strike', `AAPL|abc|${E}|C`],
    ['187abc', `AAPL|187abc|${E}|C`],
    ['negative strike', `AAPL|-5|${E}|C`],
    ['bad expiry', 'AAPL|187|2026-1-5|C'],
    ['lowercase symbol', `aapl|187|${E}|C`],
    ['empty symbol', `|187|${E}|C`],
    ['bad right', `AAPL|187|${E}|X`],
  ])('rejects %s', (_label, id) => {
    expect(parseContractId(id)).toBeNull();
  });
  it('accepts an impossible date by shape (lands as not_listed)', () => {
    expect(parseContractId('AAPL|187|2026-02-30|C')).not.toBeNull();
  });
});

describe('gradingToCtx', () => {
  it('maps every field', () => {
    expect(gradingToCtx(G)).toEqual({ stock_score: 72, hold_min_days: 20, hold_max_days: 25, contract_rules: { min_volume: 20 } });
  });
  it('omits null fields (what Step 6 sent before gradings existed)', () => {
    const ctx = gradingToCtx({ contract_rules: null, hold_min_days: null, hold_max_days: null, stock_score: null });
    expect(ctx).toEqual({});
    expect(ctx.contract_rules).toBeUndefined();
    expect(ctx.hold_min_days).toBeUndefined();
  });
  it('passes empty rules through as {}', () => {
    expect(gradingToCtx({ ...G, contract_rules: {} }).contract_rules).toEqual({});
  });
  it('is empty for no grading', () => {
    expect(gradingToCtx(null)).toEqual({});
    expect(gradingToCtx(undefined)).toEqual({});
  });
});

describe('buildGrading', () => {
  it('records unknown rules as null and no hold as nulls', () => {
    expect(buildGrading(undefined, undefined, 70)).toEqual({
      contract_rules: null, hold_min_days: null, hold_max_days: null, stock_score: 70,
    });
  });
  it('records the rules and hold as given', () => {
    expect(buildGrading({}, { hold_min_days: 3, hold_max_days: 5 }, 61)).toEqual({
      contract_rules: {}, hold_min_days: 3, hold_max_days: 5, stock_score: 61,
    });
  });
});

describe('isValidGrading', () => {
  it('accepts a server-shaped grading, including all-null', () => {
    expect(isValidGrading(G)).toBe(true);
    expect(isValidGrading({ contract_rules: null, hold_min_days: null, hold_max_days: null, stock_score: null })).toBe(true);
  });
  it.each([
    ['NaN rule', { ...G, contract_rules: { min_volume: NaN } }],
    ['string rule', { ...G, contract_rules: { min_volume: '5' } }],
    ['one hold bound', { ...G, hold_max_days: null }],
    ['max < min', { ...G, hold_min_days: 30, hold_max_days: 20 }],
    ['fractional hold', { ...G, hold_min_days: 20.5 }],
    ['negative hold', { ...G, hold_min_days: -1 }],
    ['score 101', { ...G, stock_score: 101 }],
    ['fractional score', { ...G, stock_score: 70.5 }],
    ['missing fields', { contract_rules: null }],
    ['not an object', 'x'],
  ])('rejects %s', (_l, g) => {
    expect(isValidGrading(g)).toBe(false);
  });
  it('an invalid entry is YAML-graded', () => {
    expect(isYamlGraded({ ...G, stock_score: 101 })).toBe(true);
    expect(isYamlGraded(undefined)).toBe(true);
    expect(isYamlGraded({ ...G, contract_rules: null })).toBe(true);
    expect(isYamlGraded(G)).toBe(false);
  });
});

describe('gradingKey', () => {
  const none: ContractGrading = { contract_rules: null, hold_min_days: null, hold_max_days: null, stock_score: null };
  it('is "" for anything that sends the same request as no grading', () => {
    expect(gradingKey(undefined)).toBe('');
    expect(gradingKey(none)).toBe('');
    expect(gradingKey({ ...none, stock_score: 70 })).toBe('');
    expect(gradingKey({ ...none, contract_rules: {} })).toBe('');
    expect(gradingKey({ ...G, stock_score: 101 })).toBe('');  // invalid -> none
  });
  it('treats {} / null rules and null / 70 score alike', () => {
    expect(gradingKey({ ...G, contract_rules: {}, stock_score: null }))
      .toBe(gradingKey({ ...G, contract_rules: null, stock_score: 70 }));
  });
  it('is key-order independent and tells different gradings apart', () => {
    const a = { ...G, contract_rules: { min_volume: 20, min_open_interest: 75 } };
    const b = { ...G, contract_rules: { min_open_interest: 75, min_volume: 20 } };
    expect(gradingKey(a)).toBe(gradingKey(b));
    expect(gradingKey(G)).not.toBe(gradingKey({ ...G, stock_score: 55 }));
  });
});

describe('planContractGroups', () => {
  it('groups by (symbol, right, expiry, grading), dedupes ids and strikes, skips expired and invalid', () => {
    const ids = [
      `AAPL|187|${E}|C`, `AAPL|190|${E}|C`, `AAPL|187.0|${E}|C`, `AAPL|187|${E}|C`,
      `AAPL|195|${E}|C`, `AAPL|200|${PAST}|C`, 'junk', `AAPL|185|${isoIn(47)}|C`,
    ];
    const grading = { [`AAPL|195|${E}|C`]: G };
    const plan = planContractGroups(ids, grading, TODAY);
    expect(plan.ids).toHaveLength(7);
    expect(plan.expired).toEqual(new Set([`AAPL|200|${PAST}|C`]));
    expect(plan.parsed.get('junk')).toBeNull();
    expect(plan.groups.map((g) => [g.expiry, g.strikes, g.ctx])).toEqual([
      [E, [187, 190], {}],
      [E, [195], gradingToCtx(G)],
      [isoIn(47), [185], {}],
    ]);
  });
  it('expiring today is not expired', () => {
    const plan = planContractGroups([`AAPL|187|${TODAY}|C`], {}, TODAY);
    expect(plan.expired.size).toBe(0);
    expect(plan.groups).toHaveLength(1);
  });
});

describe('resolveWatchedRows', () => {
  const A = `AAPL|187|${E}|C`;
  const B = `AAPL|190|${E}|C`;
  const plan = planContractGroups([A, B, `AAPL|1|${PAST}|C`, 'junk'], {}, TODAY);
  const key = plan.groups[0]!.key;

  it('no settled result -> loading; expired and invalid classified without one', () => {
    const rows = resolveWatchedRows(plan, [], {});
    expect(rows.map((r) => (r.kind === 'missing' ? r.reason : r.kind))).toEqual(['loading', 'loading', 'expired', 'invalid']);
  });
  it('a superset request grades the row; one lacking its strike does not', () => {
    const kept: KeptGroupResult[] = [{ groupKey: key, strikes: new Set([187]), outcome: [contract(A)] }];
    const rows = resolveWatchedRows(plan, kept, {});
    expect(rows[0]).toMatchObject({ kind: 'live', yamlGraded: true });
    expect(rows[1]).toMatchObject({ kind: 'missing', reason: 'loading' });
  });
  it('rejected -> fetch_failed; fulfilled without the id -> not_listed', () => {
    expect(resolveWatchedRows(plan, [{ groupKey: key, strikes: new Set([187, 190]), outcome: 'rejected' }], {})[0])
      .toMatchObject({ reason: 'fetch_failed' });
    expect(resolveWatchedRows(plan, [{ groupKey: key, strikes: new Set([187, 190]), outcome: [contract(A)] }], {})[1])
      .toMatchObject({ reason: 'not_listed' });
  });
  it('a legacy 187.0 id is matched exactly to the 187 row and carries the stored id', () => {
    const legacy = `AAPL|187.0|${E}|C`;
    const p = planContractGroups([legacy], {}, TODAY);
    const rows = resolveWatchedRows(p, [{ groupKey: p.groups[0]!.key, strikes: new Set([187]), outcome: [contract(A)] }], {});
    expect(rows[0]).toMatchObject({ kind: 'live' });
    expect(rows[0]!.kind === 'live' && rows[0]!.contract.id).toBe(legacy);
  });
  it('a 187.5 star requests 187.5 and is graded only by the 187.5 row, never the 187 row', () => {
    const half = `AAPL|187.5|${E}|C`;
    const p = planContractGroups([half, A], {}, TODAY);
    expect(p.groups).toHaveLength(1);
    expect(p.groups[0]!.strikes).toEqual([187.5, 187]);
    const k = p.groups[0]!.key;
    // Only the 187 row came back: the 187.5 star is not listed, not graded with 187's numbers.
    const only187 = resolveWatchedRows(p, [{ groupKey: k, strikes: new Set([187.5, 187]), outcome: [contract(A)] }], {});
    expect(only187[0]).toMatchObject({ kind: 'missing', reason: 'not_listed', strike: 187.5 });
    expect(only187[1]).toMatchObject({ kind: 'live' });
    // Both rows: each star gets its own row.
    const both = resolveWatchedRows(p, [{ groupKey: k, strikes: new Set([187.5, 187]), outcome: [contract(A), contract(half, { price: 9 })] }], {});
    expect(both[0]!.kind === 'live' && both[0]!.contract).toMatchObject({ id: half, strike: 187.5, price: 9 });
    expect(both[1]!.kind === 'live' && both[1]!.contract).toMatchObject({ id: A, strike: 187, price: 2.5 });
    // A request holding only 187 does not grade the 187.5 star.
    const req187 = resolveWatchedRows(p, [{ groupKey: k, strikes: new Set([187]), outcome: [contract(A)] }], {});
    expect(req187[0]).toMatchObject({ kind: 'missing', reason: 'loading' });
  });
});

describe('compareWatchedRows', () => {
  const live = (id: string, score: number, price: number, dte: number): WatchedContractRow =>
    ({ kind: 'live', contract: contract(id, { score, price, dte }), yamlGraded: false });
  const missing = (id: string): WatchedContractRow =>
    ({ kind: 'missing', id, symbol: 'AAPL', strike: 1, expiry: E, right: 'C', reason: 'not_listed' });
  const rows = [missing('B'), live('L1', 50, 3, 30), missing('A'), live('L2', 80, 1, 60), { kind: 'invalid', id: 'Z' } as WatchedContractRow];
  const order = new Map([['B', 0], ['L1', 1], ['A', 2], ['L2', 3], ['Z', 4]]);
  const ids = (rs: WatchedContractRow[]) => rs.map((r) => (r.kind === 'live' ? r.contract.id : r.id));

  it.each(['score', 'price', 'dte'] as const)('missing rows last in watchedIds order under %s, both directions', (key) => {
    for (const dir of ['asc', 'desc'] as const) {
      const sorted = [...rows].sort((a, b) => compareWatchedRows(a, b, key, dir, order));
      expect(ids(sorted).slice(2)).toEqual(['B', 'A', 'Z']);
    }
  });
  it('live rows sort as before', () => {
    const sorted = [...rows].sort((a, b) => compareWatchedRows(a, b, 'score', 'desc', order));
    expect(ids(sorted).slice(0, 2)).toEqual(['L2', 'L1']);
    const byPrice = [...rows].sort((a, b) => compareWatchedRows(a, b, 'price', 'asc', order));
    expect(ids(byPrice).slice(0, 2)).toEqual(['L2', 'L1']);
  });
});
