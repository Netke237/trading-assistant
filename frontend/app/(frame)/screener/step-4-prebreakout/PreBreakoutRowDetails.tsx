'use client';

/**
 * STOCK-PRES-P5-PREBREAKOUT T3 — the expanded details of a Pre-Breakout or Fib
 * row: "Why it's a setup" (the row's values against the thresholds the scan
 * applied), the confidence breakdown (P1 field, display only), the Fib swing
 * low / high with the level price, and a mini chart with price lines.
 *
 * Display only: nothing here re-derives `confidence` or a pass/fail verdict,
 * and nothing says or implies anything about entries, stops, targets or exits
 * (decision D14 — Pre-Breakout exit semantics are not designed yet).
 */
import { useEffect, useRef, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import type { PreBreakoutParams } from '@/components/organisms/PreBreakoutParamsPanel';
import { api } from '@/lib/api';
import type { Candle } from '@/types/chart';
import type { FibSwing, PreBreakoutConfidenceBreakdown } from '@/types/stockDomain';
import { fmtThreshold } from './scanThresholds';
import styles from './page.module.css';

type PriceLine = { price: number; title: string };

const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);

// ── Mini chart ────────────────────────────────────────────────────────────────

type ChartState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; candles: Candle[] };

/**
 * Daily candles from `api.getCandles` (the call InlineChartPanel uses), fetched
 * when the row is expanded. A request token drops any answer that is not for
 * the latest request of this panel, so a slow response can never draw under
 * another symbol.
 */
function MiniChart({ symbol, priceLines }: { symbol: string; priceLines: PriceLine[] }) {
  const [state, setState] = useState<ChartState>({ status: 'loading' });
  const requestRef = useRef(0);

  useEffect(() => {
    const token = ++requestRef.current;
    setState({ status: 'loading' });
    api.getCandles(symbol)
      .then((candles) => { if (requestRef.current === token) setState({ status: 'ready', candles }); })
      .catch(() => { if (requestRef.current === token) setState({ status: 'error' }); });
    return () => { requestRef.current++; };
  }, [symbol]);

  return (
    <div className={styles.detailsSection}>
      <h3 className={styles.detailsTitle}><Text size={12} weight={500}>Chart</Text></h3>
      {state.status === 'loading' ? (
        <Text size={12} tone="dim">Loading chart…</Text>
      ) : state.status === 'error' ? (
        <Text size={12} tone="dim">Chart unavailable</Text>
      ) : (
        <CandlestickChart
          data={state.candles}
          height={180}
          showToggles={false}
          defaultIndicators={[]}
          priceLines={priceLines}
        />
      )}
      <Text size={11} tone="dim">📈 Open in Chart and Set Alert stay on the row.</Text>
    </div>
  );
}

// ── Pre-Breakout ──────────────────────────────────────────────────────────────

type MetricKey = 'atr_ratio' | 'range_ratio' | 'vol_ratio' | 'proximity_pct' | 'swing_level';

export interface PreBreakoutDetailsRow {
  symbol: string;
  direction: string;
  confidence: number;
  metrics: Partial<Record<MetricKey, number | null>>;
  confidence_breakdown?: PreBreakoutConfidenceBreakdown | null;
}

/** Display order and labels of the confidence components; only those present are shown. */
const COMPONENTS: { key: string; label: string }[] = [
  { key: 'proximity', label: 'Proximity' },
  { key: 'atr',       label: 'ATR compression' },
  { key: 'vol',       label: 'Volume quiet' },
  { key: 'fib',       label: 'Fib level' },
];

const fixed = (x: number | null | undefined, digits: number) => (isNum(x) ? x.toFixed(digits) : '—');

export function PreBreakoutRowDetails({
  row,
  scanned,
}: {
  row: PreBreakoutDetailsRow;
  /** The params the rows in memory were judged on (scanThresholds.ts). */
  scanned: PreBreakoutParams;
}) {
  const mx = row.metrics ?? {};
  const bullish = row.direction === 'Bullish';
  const side = bullish ? 'swing high' : 'swing low';
  const proximity = isNum(mx.proximity_pct) ? `${mx.proximity_pct.toFixed(1)}%` : '—';
  const swing = isNum(mx.swing_level) ? `$${mx.swing_level.toFixed(2)}` : '—';

  // Row values keep the table's display rounding; thresholds print as applied.
  const lines = [
    `ATR ratio ${fixed(mx.atr_ratio, 2)} · must be below ${fmtThreshold(scanned.atrCompressionRatio, 2)}`,
    `Range ratio ${fixed(mx.range_ratio, 2)} · ${scanned.rangeLookbackBars}-bar range must be below ${fmtThreshold(scanned.rangeAtrMult, 1)} × ATR`,
    `Volume ratio ${fixed(mx.vol_ratio, 2)} · must be below ${fmtThreshold(scanned.volCompressionRatio, 2)}`,
    `${proximity} from ${side} ${swing} · within ${fmtThreshold(scanned.resistanceProximityPct * 100, 1)}%`,
  ];

  const breakdown = row.confidence_breakdown;
  const components = breakdown?.components;
  const priceLines: PriceLine[] = isNum(mx.swing_level)
    ? [{ price: mx.swing_level, title: bullish ? 'Swing high' : 'Swing low' }]
    : [];

  return (
    <div
      id={detailsId('prebreakout', row.symbol)}
      role="region"
      aria-label={`Details for ${row.symbol}`}
      className={styles.details}
    >
      <div className={styles.detailsSection}>
        <h3 className={styles.detailsTitle}><Text size={12} weight={500}>Why it&apos;s a setup</Text></h3>
        {lines.map((line) => (
          <Text key={line} size={12} tone="secondary">{line}</Text>
        ))}
        <Text size={11} tone="dim">Same facts as the hover tooltips.</Text>
      </div>

      <div className={styles.detailsSection}>
        <h3 className={styles.detailsTitle}><Text size={12} weight={500}>{`Confidence ${row.confidence}%`}</Text></h3>
        {components ? (
          COMPONENTS.filter(({ key }) => components[key] != null).map(({ key, label }) => {
            const c = components[key];
            const score = isNum(c.score) ? c.score : null;
            const width = score == null ? 0 : Math.min(100, Math.max(0, score));
            return (
              <div key={key} className={styles.breakdownRow} data-breakdown-row="">
                <div className={styles.breakdownLabel}>
                  <Text size={12}>{label}</Text>
                  <Text size={10} tone="dim">{isNum(c.weight) ? `${Math.round(c.weight * 100)}% of confidence` : '—'}</Text>
                </div>
                <div
                  className={styles.breakdownBar}
                  role="meter"
                  aria-label={`${label} score`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={score ?? undefined}
                >
                  <div className={styles.breakdownFill} style={{ width: `${width}%` }} />
                </div>
                <Data size={12} tone="secondary">{score == null ? '—' : String(Math.round(score))}</Data>
              </div>
            );
          })
        ) : (
          <Text size={12} tone="dim">Confidence breakdown is not in this result — re-run the scan.</Text>
        )}
      </div>

      <MiniChart symbol={row.symbol} priceLines={priceLines} />
    </div>
  );
}

// ── Fib ───────────────────────────────────────────────────────────────────────

/** Local copy of `strategy_engine._FIB_RATIOS` (label → retracement ratio). */
const FIB_RATIOS = new Map<number, number>([
  [23.6, 0.236],
  [38.2, 0.382],
  [50.0, 0.5],
  [61.8, 0.618],
  [78.6, 0.786],
]);

/**
 * The level price exactly as `strategy_engine._fibonacci_pullback_detail`
 * computes it: Bullish `high − r × (high − low)`, Bearish `low + r × (high − low)`.
 * An unknown label → null (never guessed).
 */
export function fibLevelPrice(direction: string, label: string, low: number, high: number): number | null {
  const r = FIB_RATIOS.get(Number(label));
  if (r === undefined) return null;
  const move = high - low;
  return direction === 'Bullish' ? high - r * move : low + r * move;
}

export interface FibDetailsRow {
  symbol: string;
  direction: string;
  fib_level_hit: string;
  fib_swing?: FibSwing | null;
}

export function FibRowDetails({ row }: { row: FibDetailsRow }) {
  const low = row.fib_swing?.low;
  const high = row.fib_swing?.high;
  const hasSwing = isNum(low) && isNum(high);
  const level = hasSwing ? fibLevelPrice(row.direction, row.fib_level_hit, low, high) : null;

  const priceLines: PriceLine[] = [];
  let swingText: string | null = null;
  if (hasSwing) {
    priceLines.push({ price: low, title: 'Swing low' }, { price: high, title: 'Swing high' });
    swingText = `Swing low $${low.toFixed(2)} · Swing high $${high.toFixed(2)}`;
    if (level != null && Number.isFinite(level)) {
      priceLines.push({ price: level, title: `${row.fib_level_hit}% level` });
      swingText += ` · ${row.fib_level_hit}% level $${level.toFixed(2)}`;
    }
  }

  return (
    <div
      id={detailsId('fib', row.symbol)}
      role="region"
      aria-label={`Details for ${row.symbol}`}
      className={styles.details}
    >
      <div className={styles.detailsSection}>
        <h3 className={styles.detailsTitle}><Text size={12} weight={500}>Swing measured from</Text></h3>
        {swingText != null ? (
          <Text size={12} tone="secondary">{swingText}</Text>
        ) : (
          <Text size={12} tone="dim">Swing low/high is not in this result — re-run the scan.</Text>
        )}
      </div>
      <MiniChart symbol={row.symbol} priceLines={priceLines} />
    </div>
  );
}

/** The `id` of a row's details region, for the toggle's `aria-controls`. */
export function detailsId(table: 'prebreakout' | 'fib', symbol: string): string {
  return `${table}-details-${symbol}`;
}
