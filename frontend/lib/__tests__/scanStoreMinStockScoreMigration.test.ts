/**
 * scanStore v18 — open question #57.
 *
 * Before the options resolver stripped Step 3's stocks-only "Min stock score",
 * an options scan posted it, the backend graded contracts with it in place of
 * contract_rules.yaml's floor (55), and recorded it in `contract_rules`. Step 6
 * sends that record back to /api/contracts. A restored blob carrying it must be
 * dropped whole -- editing out only the key would leave Step 6 grading at 55
 * while the Step 4/7 cards of the same result were graded at the Step-3 value.
 */
import { useScanStore } from '../scanStore';

// Same approach as scanStoreStopMigration.test.ts: the real migrate() callback.
const opts = (useScanStore as unknown as {
  persist: { getOptions: () => {
    migrate: (state: unknown, version: number) => unknown;
    version: number;
  } };
}).persist.getOptions();

type Blob = Record<string, unknown>;
const result = (contract_rules: unknown) => ({
  scan_id: 'S1', timestamp: '2026-09-30T10:00:00', rejected: [], candidates: [{ symbol: 'AAPL' }],
  contract_rules,
});

it('sits below the configured version, so a v17 blob reaches the branch', () => {
  expect(opts.version).toBeGreaterThanOrEqual(18);
});

it('drops a result graded with the Step-3 min_stock_score, and its timestamp', () => {
  const out = opts.migrate({
    scanResult: result({ min_stock_score: 40, min_volume: 5 }),
    optionsScanAt: '2026-09-30T10:00:00Z',
    previousRun: null,
  }, 17) as Blob;
  expect(out.scanResult).toBeNull();
  expect(out.optionsScanAt).toBeNull();
});

it.each([
  ['other contract rules', { min_volume: 5 }],
  ['an empty record', {}],
  ['no record (pre-2026-09-29 result)', undefined],
  ['a null record', null],
])('keeps a result with %s', (_label, rules) => {
  const scanResult = result(rules);
  const out = opts.migrate({ scanResult, optionsScanAt: '2026-09-30T10:00:00Z' }, 17) as Blob;
  expect(out.scanResult).toEqual(scanResult);
  expect(out.optionsScanAt).toBe('2026-09-30T10:00:00Z');
});

it('leaves a null result alone', () => {
  const out = opts.migrate({ scanResult: null, optionsScanAt: null }, 17) as Blob;
  expect(out.scanResult).toBeNull();
});
