/**
 * Independent verification test suite for Lane E: Pre-Breakout, Fibonacci, and Pullback (APP-AUDIT-PREBREAKOUT, #353).
 * Pins Candidate Chart query contracts, context parsing, integer truncation, and scan chart lines.
 */

import { buildCandidateChartHref, parseCandidateChartContext } from '@/lib/candidateChart';
import { truncPreBreakoutInts, truncFibInts } from '../scanThresholds';
import { scanChartLines } from '../scanChartLines';
import type { PreBreakoutResultRow } from '@/types/stockDomain';

describe('Lane E Pre-Breakout Audit Verification', () => {
  describe('Candidate Chart Navigation Contract', () => {
    it('sets status to unsupported and omits artifact ID for prebreakout candidates', () => {
      const row = {
        symbol: 'AAPL',
        confidence: 85,
        direction: 'Bullish' as const,
        metrics: { swing_level: 150.0 },
      };
      const href = buildCandidateChartHref(row, 'prebreakout');
      const url = new URL(href, 'http://localhost');
      expect(url.pathname).toBe('/chart');
      expect(url.searchParams.get('symbol')).toBe('AAPL');
      expect(url.searchParams.get('source')).toBe('prebreakout');
      expect(url.searchParams.get('backtest_artifact_status')).toBe('unsupported');
      expect(url.searchParams.has('backtest_artifact_id')).toBe(false);
    });

    it('sets status to unsupported and omits artifact ID for fib candidates', () => {
      const row = {
        symbol: 'NVDA',
        confidence: 90,
        direction: 'Bullish' as const,
      };
      const href = buildCandidateChartHref(row, 'fib');
      const url = new URL(href, 'http://localhost');
      expect(url.pathname).toBe('/chart');
      expect(url.searchParams.get('symbol')).toBe('NVDA');
      expect(url.searchParams.get('source')).toBe('fib');
      expect(url.searchParams.get('backtest_artifact_status')).toBe('unsupported');
      expect(url.searchParams.has('backtest_artifact_id')).toBe(false);
    });

    it('preserves valid artifact ID and status for pullback candidates', () => {
      const artifactId = '12345678-1234-1234-1234-1234567890ab';
      const row = {
        symbol: 'MSFT',
        backtest_artifact_id: artifactId,
        backtest_artifact_status: 'available' as const,
      };
      const href = buildCandidateChartHref(row, 'pullback');
      const url = new URL(href, 'http://localhost');
      expect(url.pathname).toBe('/chart');
      expect(url.searchParams.get('symbol')).toBe('MSFT');
      expect(url.searchParams.get('source')).toBe('pullback');
      expect(url.searchParams.get('backtest_artifact_status')).toBe('available');
      expect(url.searchParams.get('backtest_artifact_id')).toBe(artifactId);
    });

    it('parses prebreakout and fib context strictly to unsupported status', () => {
      const query = new URLSearchParams({
        symbol: 'TSLA',
        source: 'prebreakout',
        backtest_artifact_status: 'available', // attempted spoof
        backtest_artifact_id: '12345678-1234-1234-1234-1234567890ab',
      });
      const parsed = parseCandidateChartContext(query);
      expect(parsed).toEqual({
        source: 'prebreakout',
        symbol: 'TSLA',
        artifactId: null,
        status: 'unsupported',
      });
    });
  });

  describe('Integer Truncation Semantics', () => {
    it('truncates fractional parameters in prebreakout and fib snapshots to match backend integer coercion', () => {
      const preTruncated = truncPreBreakoutInts({
        atrCompressionRatio: 0.85,
        atrAvgLookback: 20.8,
        rangeAtrMult: 3.0,
        rangeLookbackBars: 10.4,
        volCompressionRatio: 0.90,
        resistanceProximityPct: 0.08,
        swingLookback: 50.9,
      });
      expect(preTruncated.atrAvgLookback).toBe(20);
      expect(preTruncated.rangeLookbackBars).toBe(10);
      expect(preTruncated.swingLookback).toBe(50);

      const fibTruncated = truncFibInts({
        fibSwingLookback: 100.7,
        fibLevels: [38.2, 61.8],
        fibTolerancePct: 0.015,
        emaFilterPeriod: 20.3,
      });
      expect(fibTruncated.fibSwingLookback).toBe(100);
      expect(fibTruncated.emaFilterPeriod).toBe(20);
    });
  });

  describe('Setup Evidence Price Lines', () => {
    it('generates scan evidence lines for prebreakout with swing levels', () => {
      const row: PreBreakoutResultRow = {
        symbol: 'AAPL',
        confidence: 80,
        direction: 'Bullish',
        metrics: { swing_level: 155.50 },
        fib_swing: { low: 140.0, high: 160.0 },
      };
      const lines = scanChartLines(row, 'prebreakout');
      expect(lines).toContainEqual({
        price: 155.50,
        title: 'Scan swing high',
      });
      expect(lines).toContainEqual({
        price: 140.0,
        title: 'Scan Fib swing low',
      });
    });

    it('returns empty array for pullback rows preserving execution isolation', () => {
      const lines = scanChartLines({ symbol: 'GOOGL', direction: 'Bullish', metrics: { swing_level: 200 } } as any, 'pullback');
      expect(lines).toEqual([]);
    });
  });
});
