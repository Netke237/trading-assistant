import {
  parseConfigHealth, tierOf, fingerprintOf, MAX_REPORT_AGE_MS,
  type HealthView, type HealthStatus,
} from '@/lib/configHealth';
import {
  CLEAN_REPORT, ERROR_REPORT, STALE_REPORT, WARNING_REPORT, CRASH_REPORT,
} from '@/lib/testFixtures/configHealth';

const NOW = 1_000_000_000;
const view = (over: Partial<HealthView> = {}): HealthView => ({
  status: 'ready', report: CLEAN_REPORT, error: null, fetchedAt: NOW, multiWorker: false, now: NOW,
  ...over,
});
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

describe('parseConfigHealth', () => {
  it('P1: every fixture parses to itself', () => {
    for (const r of [CLEAN_REPORT, ERROR_REPORT, STALE_REPORT, WARNING_REPORT, CRASH_REPORT]) {
      expect(parseConfigHealth(clone(r))).toEqual(r);
    }
  });

  it('P1b: extra keys are ignored', () => {
    expect(parseConfigHealth({ ...clone(CLEAN_REPORT), extra: 1 })).toEqual(CLEAN_REPORT);
  });

  it('P2: refuses, naming the path', () => {
    expect(() => parseConfigHealth(null)).toThrow('expected an object');
    expect(() => parseConfigHealth([])).toThrow('expected an object');
    for (const k of ['ok', 'checked', 'not_checked', 'pid', 'errors', 'warnings', 'stale']) {
      const r = clone(CLEAN_REPORT) as unknown as Record<string, unknown>;
      delete r[k];
      expect(() => parseConfigHealth(r)).toThrow(`${k}: missing`);
    }
    for (const pid of [0, 1.5, '1', -3]) {
      expect(() => parseConfigHealth({ ...clone(CLEAN_REPORT), pid })).toThrow('pid:');
    }
    expect(() => parseConfigHealth({ ...clone(CLEAN_REPORT), checked: 'x' })).toThrow('checked:');
    expect(() => parseConfigHealth({ ...clone(CLEAN_REPORT), checked: ['a', 2] })).toThrow('checked[1]');
    expect(() => parseConfigHealth({ ...clone(CLEAN_REPORT), ok: 'true' })).toThrow('ok: expected a boolean');

    const noBlocks = clone(ERROR_REPORT) as any;
    delete noBlocks.errors[0].blocks;
    expect(() => parseConfigHealth(noBlocks)).toThrow('errors[0].blocks: missing');

    const badMsg = clone(STALE_REPORT) as any;
    badMsg.stale[0].message = 3;
    expect(() => parseConfigHealth(badMsg)).toThrow('stale[0].message: expected a string');
  });

  it('P3: ok contradicting the findings is refused', () => {
    expect(() => parseConfigHealth({ ...clone(ERROR_REPORT), ok: true })).toThrow('contradicts');
    expect(() => parseConfigHealth({ ...clone(CLEAN_REPORT), ok: false })).toThrow('contradicts');
  });
});

describe('tierOf', () => {
  it('T1: rules 1-8 in order', () => {
    expect(tierOf(view({ status: 'idle', report: null, fetchedAt: null }))).toBe('checking');
    expect(tierOf(view({ status: 'loading', report: null, fetchedAt: null }))).toBe('checking');
    expect(tierOf(view({ status: 'failed', report: null, error: 'boom', fetchedAt: null }))).toBe('unknown');
    expect(tierOf(view({ fetchedAt: NOW - MAX_REPORT_AGE_MS - 1 }))).toBe('unknown');
    expect(tierOf(view({ fetchedAt: NOW - MAX_REPORT_AGE_MS }))).toBe('clean');
    expect(tierOf(view({ report: ERROR_REPORT }))).toBe('error');
    expect(tierOf(view({ report: STALE_REPORT }))).toBe('stale');
    expect(tierOf(view({ multiWorker: true }))).toBe('multiworker');
    expect(tierOf(view({ report: WARNING_REPORT }))).toBe('warning');
    expect(tierOf(view())).toBe('clean');
  });

  it('T1b: an old ERROR report is unknown too (rule 3 before rule 4)', () => {
    expect(tierOf(view({ report: ERROR_REPORT, fetchedAt: NOW - MAX_REPORT_AGE_MS - 1 }))).toBe('unknown');
  });

  it('T2: the worst tier wins', () => {
    const all = { ...ERROR_REPORT, stale: STALE_REPORT.stale, warnings: WARNING_REPORT.warnings };
    expect(tierOf(view({ report: all, multiWorker: true }))).toBe('error');
    const sw = { ...STALE_REPORT, warnings: WARNING_REPORT.warnings };
    expect(tierOf(view({ report: sw, multiWorker: true }))).toBe('stale');
    expect(tierOf(view({ report: WARNING_REPORT, multiWorker: true }))).toBe('multiworker');
  });

  it('T3: the crash shape is the error tier', () => {
    expect(tierOf(view({ report: CRASH_REPORT }))).toBe('error');
  });

  it('T5: a retry in flight after a failure stays unknown (round-1 G1)', () => {
    expect(tierOf(view({ status: 'loading', report: null, error: 'x', fetchedAt: null }))).toBe('unknown');
  });

  it('T4: never clean without a report', () => {
    for (const status of ['idle', 'loading', 'ready', 'failed'] as HealthStatus[]) {
      for (const error of [null, 'e']) {
        expect(tierOf(view({ status, report: null, error, fetchedAt: NOW }))).not.toBe('clean');
      }
    }
  });
});

describe('fingerprintOf', () => {
  it('F1: stable under reordering, changes with a message, constant for unknown', () => {
    const two = { ...WARNING_REPORT, warnings: [
      { file: 'a', path: 'x', message: 'm1' }, { file: 'b', path: 'y', message: 'm2' }] };
    const rev = { ...two, warnings: [...two.warnings].reverse() };
    expect(fingerprintOf(view({ report: two }))).toBe(fingerprintOf(view({ report: rev })));
    const changed = { ...two, warnings: [two.warnings[0], { ...two.warnings[1], message: 'm3' }] };
    expect(fingerprintOf(view({ report: changed }))).not.toBe(fingerprintOf(view({ report: two })));
    const errMsg = { ...ERROR_REPORT, errors: [{ ...ERROR_REPORT.errors[0], message: 'other' }] };
    expect(fingerprintOf(view({ report: errMsg }))).not.toBe(fingerprintOf(view({ report: ERROR_REPORT })));
    const staleMsg = { ...STALE_REPORT, stale: [{ ...STALE_REPORT.stale[0], message: 'other' }] };
    expect(fingerprintOf(view({ report: staleMsg }))).not.toBe(fingerprintOf(view({ report: STALE_REPORT })));
    expect(fingerprintOf(view({ report: null, status: 'failed', error: 'a' })))
      .toBe(fingerprintOf(view({ report: null, status: 'failed', error: 'b' })));
    expect(fingerprintOf(view({ report: null, status: 'failed', error: 'a' }))).toBe('unknown');
    expect(fingerprintOf(view())).toBe('');
    expect(fingerprintOf(view({ report: WARNING_REPORT, multiWorker: true })))
      .not.toBe(fingerprintOf(view({ report: WARNING_REPORT, multiWorker: false })));
  });
});
