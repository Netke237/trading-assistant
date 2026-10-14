/**
 * scanStore v18 — TRADING-REVIEW-PHASE-C-RR (review M7, D5).
 *
 * Options R/R now risks the FULL premium (no protective stop order is ever
 * placed). Every `rrRatio` / `rrContribution` persisted before that was divided
 * by the premium stop or the captured stock-stop loss, so under the new reading
 * it overstates reward per unit of risk by at least 1/0.6. The header, the rail
 * and AlternativeContractRow would print it as if it were current. The whole
 * options result is discarded rather than relabelled; the user re-runs the scan.
 */
import { useScanStore } from '../scanStore';

const migrate = (useScanStore as unknown as {
  persist: { getOptions: () => {
    migrate: (state: unknown, version: number) => unknown;
    version: number;
  } };
}).persist.getOptions();

type Blob = Record<string, any>;   // eslint-disable-line @typescript-eslint/no-explicit-any

function run(scanId: string, bases: Array<string | undefined>): Blob {
  return {
    scan_id: scanId, timestamp: '2026-10-01T10:00:00', rejected: [],
    candidates: bases.map((basis, i) => ({
      symbol: `S${i}`, rrRatio: 2.1,
      exit: {
        invalidation: 180, premiumStop: 1.2, timeStopDays: 10, target: 200, targets: [],
        finalStop: { price: 180 },
        ...(basis === undefined ? {} : { rrRiskBasis: basis }),
      },
    })),
  };
}

function v17(scan: Blob | null, previous: Blob | null): Blob {
  return {
    scanResult: scan,
    previousRun: previous,
    stockScanResult: { scan_id: 'STK', candidates: [{ symbol: 'X', exit: { rrRiskBasis: 'premium_stop' } }] },
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (7–21d)' },
    pickedContracts: { S0: 'S0|100|2026-12-01|C' },
    screenerMode: 'options',
    stockScanRequest: null,
  };
}

describe('scanStore migrate(): v18, options R/R on the full-premium basis', () => {
  it('sits at or above 18, so a v17 blob actually reaches the branch', () => {
    expect(migrate.version).toBeGreaterThanOrEqual(18);
  });

  it.each([
    ['absent', undefined],
    ['premium_stop', 'premium_stop'],
    ['stock_stop', 'stock_stop'],
  ])('discards scanResult when any candidate has rrRiskBasis %s', (_label, basis) => {
    const out = migrate.migrate(v17(run('A', ['full_premium', basis]), null), 17) as Blob;
    expect(out.scanResult).toBeNull();
  });

  it('applies the same rule to previousRun', () => {
    const out = migrate.migrate(v17(run('A', ['full_premium']), run('P', ['premium_stop'])), 17) as Blob;
    expect(out.previousRun).toBeNull();
    expect(out.scanResult).toEqual({...run('A', ['full_premium']),report_run_id:null,report_generation:null,report_persistence:null});
  });

  it('keeps a result whose candidates are all full_premium unchanged', () => {
    const before = v17(run('A', ['full_premium', 'full_premium']), run('P', ['full_premium']));
    const out = migrate.migrate(JSON.parse(JSON.stringify(before)), 17) as Blob;
    expect(out.scanResult).toEqual({...before.scanResult,report_run_id:null,report_generation:null,report_persistence:null});
    expect(out.previousRun).toEqual({...before.previousRun,report_run_id:null,report_generation:null,report_persistence:null});
  });

  it('leaves stockScanResult and every other field untouched', () => {
    const before = v17(run('A', ['premium_stop']), run('P', [undefined]));
    const out = migrate.migrate(JSON.parse(JSON.stringify(before)), 17) as Blob;
    expect(out.scanResult).toBeNull();
    expect(out.previousRun).toBeNull();
    for (const key of ['stockScanResult', 'context', 'pickedContracts', 'screenerMode', 'stockScanRequest']) {
      expect(out[key]).toEqual(key==='stockScanResult'?{...before[key],report_run_id:null,report_generation:null,report_persistence:null}:before[key]);
    }
  });

  it('survives an absent or malformed result', () => {
    expect(() => migrate.migrate({ scanResult: null, previousRun: undefined }, 17)).not.toThrow();
    expect(() => migrate.migrate({ scanResult: { candidates: 'nope' } }, 17)).not.toThrow();
    expect(() => migrate.migrate({ scanResult: { candidates: [null, 7, { symbol: 'X' }] } }, 17)).not.toThrow();
  });
});
