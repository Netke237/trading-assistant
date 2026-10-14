import { useScanStore } from '../scanStore';
import type {
  FibPullbackResultRow,
  PositionCardData,
  PreBreakoutResultRow,
  StockScanResult,
} from '@/types/stockDomain';
import type { StockExplanation } from '@/types/domain';

// STOCK-PRES-P1 Task 3. Types only: the new fields are OPTIONAL, so results
// persisted before P1 must still load unchanged, and the store must keep the
// new fields when a fresh scan carries them. LOG03 later adds nullable report
// identity through the preserving v19 migration; all original evidence stays exact.
//
// Reach the real persist callbacks the same way scanStoreMergeHydration.test.ts
// (merge) and scanStoreHorizonMigration.test.ts (migrate) do.
const options = (useScanStore as unknown as {
  persist: {
    getOptions: () => {
      version: number;
      merge: (persisted: unknown, current: unknown) => Record<string, unknown>;
      migrate: (state: unknown, version: number) => unknown;
    };
  };
}).persist.getOptions();

/** A stock-scan candidate exactly as persisted before P1: no `stock_explanation`. */
function oldCandidate(): Record<string, unknown> {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 190.12, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 190.12, stop_price: 184.5,
      target_price: 201.3, rr_ratio: 1.99, atr: 2.81, detail: { ema: 188.4 },
    },
    backtest: {
      n_trades: 24, win_rate: 0.58, total_return_pct: 12.4, max_drawdown_pct: 6.1,
      expectancy: 0.42, sharpe: 1.1, confidence: 71, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 74, stock_status: 'PASS',
    shares: 35, dollar_risk: 196.7, dollar_size: 6654.2,
    confidence: 71, confidence_text: 'High',
  };
}

function oldBlob(): Record<string, unknown> {
  return {
    screenerMode: 'stocks',
    stockScanResult: {
      scan_id: 'scan-old-1', timestamp: '2026-10-01T14:00:00Z',
      candidates: [oldCandidate()], rejected: [],
    },
    previousStockScanResult: null,
    // Session-only (not in partialize): pins only that merge passes old-shape rows through.
    preBreakoutResults: [
      {
        symbol: 'MSFT', confidence: 59, direction: 'Bullish',
        metrics: { atr_ratio: 0.535, range_ratio: 0.878, vol_ratio: 0.732, proximity_pct: 0.31, swing_level: 104.42, current_atr: 0.4557 },
      },
    ],
    fibPullbackResults: [
      { symbol: 'NVDA', direction: 'Bullish', fib_level_hit: '61.8', fib_dist_pct: 0.07, at_level: true, confidence: 97 },
      { symbol: 'AMD', direction: 'Bullish', fib_level_hit: '', fib_dist_pct: null, at_level: false, confidence: 0 },
    ],
  };
}

const current = { scanState: 'IDLE', screenerMode: 'options', stockExecutionGeneration: 0, stockManualRunToken: 0 };

describe('STOCK-PRES-P1: old persisted results still load through preserving report migration', () => {
  it('the store reaches the preserving v19 report migration', () => {
    expect(options.version).toBeGreaterThanOrEqual(19);
  });

  it('migration preserves original evidence exactly and marks report identity unavailable', () => {
    const blob = oldBlob();
    const migrated = options.migrate(oldBlob(), 18) as Record<string, unknown>;
    expect(migrated).toEqual({...blob,scanResult:undefined,previousRun:undefined,stockScanResult:{...(blob.stockScanResult as Record<string,unknown>),report_run_id:null,report_generation:null,report_persistence:null}});
    expect((migrated.stockScanResult as Record<string,unknown>).category).toBeUndefined();
  });

  it('merge hydrates all original stock, Pre-Breakout and Fib evidence with unavailable report identity', () => {
    const blob = oldBlob();
    const out = options.merge(options.migrate(oldBlob(), 18), current);
    expect(out.stockScanResult).toEqual({...(blob.stockScanResult as Record<string,unknown>),report_run_id:null,report_generation:null,report_persistence:null});
    expect((out.stockScanResult as Record<string,unknown>).category).toBeUndefined();
    expect(out.previousStockScanResult).toBeNull();
    expect(out.preBreakoutResults).toEqual(blob.preBreakoutResults);
    expect(out.fibPullbackResults).toEqual(blob.fibPullbackResults);
    const cand = (out.stockScanResult as StockScanResult).candidates[0];
    expect('stock_explanation' in cand).toBe(false);
    const pre = (out.preBreakoutResults as PreBreakoutResultRow[])[0];
    expect('confidence_breakdown' in pre).toBe(false);
    expect('fib_swing' in pre).toBe(false);
    for (const row of out.fibPullbackResults as FibPullbackResultRow[]) {
      expect('fib_swing' in row).toBe(false);
    }
  });
});

describe('STOCK-PRES-P1: new fields survive the store setters', () => {
  afterEach(() => {
    useScanStore.getState().setPreBreakoutResults([]);
    useScanStore.getState().setFibPullbackResults([]);
    useScanStore.getState().setStockScanResult(null);
  });

  it('setPreBreakoutResults keeps confidence_breakdown and fib_swing', () => {
    const row: PreBreakoutResultRow = {
      symbol: 'MSFT', confidence: 67, direction: 'Bullish',
      metrics: { atr_ratio: 0.535, range_ratio: 0.878, vol_ratio: 0.732, proximity_pct: 0.31, swing_level: 104.42, current_atr: 0.4557 },
      confidence_breakdown: {
        fib_used: true,
        weights: { atr: 0.24, vol: 0.2, proximity: 0.36, fib: 0.2 },
        components: {
          atr:       { score: 37.06, weight: 0.24, contribution: 8.89 },
          vol:       { score: 18.67, weight: 0.2,  contribution: 3.73 },
          proximity: { score: 96.13, weight: 0.36, contribution: 34.61 },
          fib:       { score: 100,   weight: 0.2,  contribution: 20 },
        },
        unrounded: 67.23,
        confidence: 67,
      },
      fib_swing: { low: 95.5, high: 104.9 },
    };
    const noFib: PreBreakoutResultRow = {
      symbol: 'AAPL', confidence: 59, direction: 'Bullish', metrics: { atr_ratio: 0.5 },
      confidence_breakdown: {
        fib_used: false,
        weights: { atr: 0.3, vol: 0.25, proximity: 0.45 },
        components: { atr: { score: 37, weight: 0.3, contribution: 11.1 } },
        unrounded: 59.4,
        confidence: 59,
      },
      fib_swing: null,
    };
    useScanStore.getState().setPreBreakoutResults([row, noFib]);
    const stored = useScanStore.getState().preBreakoutResults;
    expect(stored[0]).toBe(row);
    expect(stored[0].confidence_breakdown).toEqual(row.confidence_breakdown);
    expect(stored[0].fib_swing).toEqual({ low: 95.5, high: 104.9 });
    expect(stored[1].fib_swing).toBeNull();
  });

  it('setFibPullbackResults keeps fib_swing', () => {
    const row: FibPullbackResultRow = {
      symbol: 'NVDA', direction: 'Bullish', fib_level_hit: '61.8', fib_dist_pct: 0.07,
      at_level: true, confidence: 97, fib_swing: { low: 100, high: 130 },
    };
    const noSwing: FibPullbackResultRow = {
      symbol: 'AMD', direction: 'Bullish', fib_level_hit: '', fib_dist_pct: null,
      at_level: false, confidence: 0, fib_swing: { low: null, high: null },
    };
    useScanStore.getState().setFibPullbackResults([row, noSwing]);
    const stored = useScanStore.getState().fibPullbackResults;
    expect(stored[0]).toBe(row);
    expect(stored[0].fib_swing).toEqual({ low: 100, high: 130 });
    expect(stored[1].fib_swing).toEqual({ low: null, high: null });
  });

  it('setStockScanResult keeps stock_explanation (reference-equal)', () => {
    const explanation = {
      version: 1, symbol: 'AAPL', direction: 'Bullish', horizon: 'Swing',
      scoring_mode: 'stock', iv_basis: 'none', evaluated_at: '2026-10-10T14:00:00Z',
      score: 74, status: 'PASS', raw_status: 'PASS', unrounded_score: 74.3,
      rounding: 'python_round_ties_to_even', pass_threshold: 70, caution_threshold: 50,
      weights: { trend: 0.3 }, components: {}, caps: [], gate_config: {},
    } as unknown as StockExplanation;
    const candidate = { ...oldCandidate(), stock_explanation: explanation } as unknown as PositionCardData;
    const result: StockScanResult = {
      scan_id: 'scan-new-1', timestamp: '2026-10-10T14:00:00Z', candidates: [candidate], rejected: [],
    };
    useScanStore.getState().setStockScanResult(result);
    const stored = useScanStore.getState().stockScanResult!;
    expect(stored).toBe(result);
    expect(stored.candidates[0].stock_explanation).toBe(explanation);
  });
});
