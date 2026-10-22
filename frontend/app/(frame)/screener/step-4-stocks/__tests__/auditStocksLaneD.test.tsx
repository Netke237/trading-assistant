import '@testing-library/jest-dom';
import {
  buildStockScanRequestBody,
  normalizeWeightOverride,
  SCORE_WEIGHT_KEYS,
  type ResolvedStockScanContext,
} from '@/lib/resolveStockScanRequest';
import { assertStrategyScanOverrides } from '@/lib/strategyScanValidation';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import type { StockScanResult } from '@/types/stockDomain';

describe('Lane D Audit: Stocks Scan Request Resolution & Hydration Lifecycle (#352)', () => {
  const baseContext: ResolvedStockScanContext = {
    universe: ['AAPL', 'MSFT', 'GOOGL'],
    direction: 'Bullish',
    horizon: 'Swing',
    strategy: 'pullback_ema',
    params: {
      eventFilter: 'include',
      stockShortlistMax: 20,
      btMinTrades: 5,
      btMinWinRate: 0.5,
      pullbackTolerancePct: 0.03,
      pullbackEmaPeriod: 20,
      pullbackTrendEma: 50,
      pullbackMaType: 'EMA',
      maCrossoverFast: 9,
      maCrossoverSlow: 21,
      maCrossoverLookback: 5,
      breakoutVolumeMult: 1.5,
      rsiPeriod: 14,
      rsiOversold: 30,
      rsiOverbought: 70,
      rsiTrendSma: 200,
      requireChoppyRegime: false,
      meanReversionVariants: ['rsi', 'bb'],
      meanReversionMinConfirm: 2,
      vwapLookback: 20,
      vwapDeviationPct: 0.02,
    },
    paramsHorizon: 'Swing',
    requireReversal: true,
    scanOverrides: {
      weight_trend: 30,
      weight_pullback: 25,
      weight_trigger: 25,
      weight_vol: 20,
      weight_event: 0,
      max_delta: 0.7, // Options-only key: must be stripped
      min_dte: 30, // Options-only key: must be stripped
      iv_rank_pass_max: 50, // Options-only key: must be stripped
      confidence_caution_below: 48,
      confidence_reject_below: 32,
    },
    confidenceGate: {
      enabled: true,
      cautionBelow: 50,
      rejectBelow: 35,
      atrMult: {
        intraday: { target: 2.0, stop: 1.0 },
        swing: { target: 3.0, stop: 1.5 },
        position: { target: 4.0, stop: 2.0 },
      },
    },
    accountSize: 50000,
    riskPct: 0.01,
    holdMinDays: 5,
    holdMaxDays: 15,
    minPriceRaw: '10',
    maxPriceRaw: '500',
    minCapRaw: '1',
    maxCapRaw: '50',
    capUnit: 'B',
  };

  describe('1. Request Resolution & Whitelist Isolation', () => {
    it('builds valid StockScanRequestBody with numeric conversions and whitelist filtering', () => {
      const body = buildStockScanRequestBody(baseContext);

      expect(body.universe).toEqual(['AAPL', 'MSFT', 'GOOGL']);
      expect(body.direction).toBe('Bullish');
      expect(body.horizon).toBe('Swing');
      expect(body.strategy).toBe('pullback_ema');
      expect(body.account_size).toBe(50000);
      expect(body.risk_pct).toBe(0.01);
      expect(body.min_price).toBe(10);
      expect(body.max_price).toBe(500);
      expect(body.min_cap_usd).toBe(1e9); // 1B = 1e9
      expect(body.max_cap_usd).toBe(50e9); // 50B = 5e10
      expect(body.hold_max_days).toBe(15);
      expect(body.params_horizon).toBe('Swing');
      expect(body.pullback_require_reversal).toBe(true);
      expect(body.confidence_caution_below).toBe(48);
      expect(body.confidence_reject_below).toBe(32);

      // Verify options-only keys were stripped from overrides
      expect(body.overrides).toBeDefined();
      expect(body.overrides!['max_delta']).toBeUndefined();
      expect(body.overrides!['min_dte']).toBeUndefined();
      expect(body.overrides!['iv_rank_pass_max']).toBeUndefined();

      // Verify weight conversion from 0-100 to 0.0-1.0
      expect(body.overrides!['weight_trend']).toBe(0.3);
      expect(body.overrides!['weight_pullback']).toBe(0.25);
      expect(body.overrides!['weight_trigger']).toBe(0.25);
      expect(body.overrides!['weight_vol']).toBe(0.2);
    });

    it('preserves explicit zero in price and cap filters (0 vs undefined)', () => {
      const zeroCtx: ResolvedStockScanContext = {
        ...baseContext,
        minPriceRaw: '0',
        minCapRaw: '0',
        capUnit: 'M',
      };
      const body = buildStockScanRequestBody(zeroCtx);
      expect(body.min_price).toBe(0);
      expect(body.min_cap_usd).toBe(0);
    });

    it('omits price and cap filters when raw strings are empty or whitespace', () => {
      const emptyCtx: ResolvedStockScanContext = {
        ...baseContext,
        minPriceRaw: '  ',
        maxPriceRaw: '',
        minCapRaw: undefined,
        maxCapRaw: '   ',
      };
      const body = buildStockScanRequestBody(emptyCtx);
      expect(body.min_price).toBeUndefined();
      expect(body.max_price).toBeUndefined();
      expect(body.min_cap_usd).toBeUndefined();
      expect(body.max_cap_usd).toBeUndefined();
    });

    it('enforces strategy scan overrides assertions', () => {
      // Invalid breakoutVolumeMult <= 1.0 must throw
      expect(() => {
        assertStrategyScanOverrides({
          breakoutVolumeMult: 0.9,
        });
      }).toThrow();

      // Invalid pullbackTolerancePct <= 0 must throw
      expect(() => {
        assertStrategyScanOverrides({
          pullbackTolerancePct: -0.01,
        });
      }).toThrow();

      // Valid parameters must pass
      expect(() => {
        assertStrategyScanOverrides({
          breakoutVolumeMult: 1.5,
          pullbackTolerancePct: 0.05,
          maCrossoverLookback: 10,
        });
      }).not.toThrow();
    });

    it('normalizes weight overrides correctly', () => {
      expect(normalizeWeightOverride(50)).toBe(0.5);
      expect(normalizeWeightOverride(100)).toBe(1.0);
      expect(normalizeWeightOverride(0)).toBe(0);
      expect(normalizeWeightOverride('50')).toBe('50'); // Non-numbers pass through unchanged
    });
  });

  describe('2. Scan Store State & Clean Invalidation', () => {
    beforeEach(() => {
      useScanStore.setState({
        stockScanResult: null,
        stockScanError: null,
        stockScanAt: null,
        scanState: 'IDLE',
      });
    });

    it('clears scan results on clearScanResults()', () => {
      const mockResult: StockScanResult = {
        scan_id: 'test-scan-id',
        timestamp: new Date().toISOString(),
        candidates: [],
        rejected: [],
        pipeline: {
          scanned: 10,
          failed_history: 0,
          failed_score: 2,
          failed_signal: 3,
          failed_backtest: 1,
          candidates: 4,
        },
        report_run_id: 'report-run-123',
      };

      useScanStore.getState().setStockScanResult(mockResult);
      useScanStore.setState({ stockScanRequest: { universe: ['AAPL'] } as any, stockScanAt: '12:00:00' });

      expect(useScanStore.getState().stockScanResult).toBe(mockResult);
      expect(useScanStore.getState().stockScanRequest).toBeDefined();
      expect(useScanStore.getState().stockScanAt).toBe('12:00:00');

      useScanStore.getState().clearScanResults();

      expect(useScanStore.getState().stockScanResult).toBeNull();
      expect(useScanStore.getState().stockScanRequest).toBeNull();
      expect(useScanStore.getState().stockScanAt).toBeNull();
    });
  });
});
