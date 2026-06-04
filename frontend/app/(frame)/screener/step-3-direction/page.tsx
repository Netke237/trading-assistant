'use client';

/*
 * Screener Step 3 — Direction + Horizon.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 * Round 5: full 34-param Execution Parameters panel — Stocks / Options sections,
 * per-subgroup collapse, Score Weights from Settings migrated here.
 */

import { useEffect, useState, useCallback } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import type { Direction } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import type { RejectedEntry } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

// ── Scan-log constants ────────────────────────────────────────────────────────

const HORIZON_WEIGHTS: Record<string, Record<string, number>> = {
  Intraday: { trend: 35, pullback: 20, trigger: 30, event: 5,  vol: 10 },
  Swing:    { trend: 30, pullback: 20, trigger: 25, event: 15, vol: 10 },
  Position: { trend: 30, pullback: 20, trigger: 20, event: 20, vol: 10 },
};

const COMPONENT_LABELS: Record<string, string> = {
  trend:    'Trend',
  pullback: 'Pullback',
  trigger:  'Trigger',
  event:    'Event',
  vol:      'Vol',
};

const COMPONENT_ORDER = ['trend', 'pullback', 'trigger', 'event', 'vol'];

// ── Breakdown row component ───────────────────────────────────────────────────

function BreakdownRow({ compKey, rawScore, weight }: { compKey: string; rawScore: number; weight: number }) {
  const label = COMPONENT_LABELS[compKey] ?? compKey;
  const weightedPts = Math.round((rawScore / 100) * weight);
  const tone: 'pass' | 'caution' | 'reject' =
    weightedPts >= weight * 0.6 ? 'pass' : weightedPts >= weight * 0.3 ? 'caution' : 'reject';
  return (
    <div className={formStyles.breakdownRow}>
      <Text size={11} tone="secondary" weight={400}>{label}</Text>
      <Data size={11} weight={500}>{rawScore}/100</Data>
      <Text size={11} tone="dim">{weight}%</Text>
      <div className={formStyles.miniTrack}>
        <div className={formStyles.miniFill} style={{ width: `${rawScore}%` }} />
      </div>
      <Data size={11} weight={500} tone={tone}>{weightedPts}pt</Data>
    </div>
  );
}

// ── StockRejectGroup ──────────────────────────────────────────────────────────

function StockRejectGroup({ reason, entries, horizonKey }: { reason: string; entries: RejectedEntry[]; horizonKey: string }) {
  const [open, setOpen] = useState(false);
  const weights = HORIZON_WEIGHTS[horizonKey] ?? HORIZON_WEIGHTS['Swing'];
  const sampleBreakdown = entries.find((e) => e.breakdown)?.breakdown;

  return (
    <div className={formStyles.rejectGroup}>
      <button type="button" className={formStyles.rejectGroupHeader} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Text size={12} tone="reject" weight={500}>{reason}</Text>
        <Text size={11} tone="dim">{entries.length} symbol{entries.length !== 1 ? 's' : ''}</Text>
        <span className={`${formStyles.chevron} ${open ? formStyles.chevronOpen : ''}`} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={formStyles.rejectGroupBody}>
          <div className={formStyles.symbolList}>
            {entries.map((e) => <Text key={e.symbol} size={11} tone="secondary">{e.symbol}</Text>)}
          </div>
          {sampleBreakdown && (
            <div className={formStyles.breakdownBlock}>
              <div className={formStyles.breakdownHeader}>
                <Text size={10} tone="dim">COMPONENT</Text>
                <Text size={10} tone="dim">RAW</Text>
                <Text size={10} tone="dim">WT%</Text>
                <span />
                <Text size={10} tone="dim">PTS</Text>
              </div>
              {COMPONENT_ORDER.map((k) =>
                sampleBreakdown[k] !== undefined ? (
                  <BreakdownRow key={k} compKey={k} rawScore={sampleBreakdown[k]} weight={weights[k] ?? 0} />
                ) : null
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── ScanLog section ───────────────────────────────────────────────────────────

function ScanLogSection({ entries, horizonKey }: { entries: RejectedEntry[]; horizonKey: string }) {
  if (entries.length === 0) return null;
  const stockRejects = entries.filter((e) => e.reason.startsWith('stock REJECT'));
  const otherRejects = entries.filter((e) => !e.reason.startsWith('stock REJECT'));
  const byReason = new Map<string, RejectedEntry[]>();
  for (const e of stockRejects) {
    const list = byReason.get(e.reason) ?? [];
    list.push(e);
    byReason.set(e.reason, list);
  }
  return (
    <div className={formStyles.rejectList}>
      {Array.from(byReason.entries())
        .sort((a, b) => b[1].length - a[1].length)
        .map(([reason, list]) => (
          <StockRejectGroup key={reason} reason={reason} entries={list} horizonKey={horizonKey} />
        ))}
      {otherRejects.length > 0 && (
        <div className={formStyles.otherRejects}>
          <Text size={11} tone="dim" weight={500}>OTHER</Text>
          {otherRejects.map((e) => (
            <div key={e.symbol} className={formStyles.otherRejectRow}>
              <Text size={11} weight={500}>{e.symbol}</Text>
              <Text size={11} tone="dim">{e.reason}</Text>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const DIRECTIONS: Direction[] = ['Bullish', 'Bearish'];

type HorizonKey = 'Intraday' | 'Swing' | 'Position' | 'Custom';

const HORIZON_PRESETS: { key: HorizonKey; label: string; hint: string }[] = [
  { key: 'Intraday', label: 'Intraday', hint: '0–2 days' },
  { key: 'Swing',    label: 'Swing',    hint: '5–15 days' },
  { key: 'Position', label: 'Position', hint: '15–45 days' },
  { key: 'Custom',   label: 'Custom',   hint: 'Set range' },
];

// ── Execution Parameters types ────────────────────────────────────────────────

interface ParamDef {
  key: string;
  label: string;
  type: 'number' | 'boolean' | 'select' | 'display';
  section: 'stocks' | 'options';
  subGroup: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  redundant?: true;
  deprecated?: true;
  visibleFor?: string[];   // if set, only show when scanOverrides.trend_method (or default) is in this list
}

const PARAM_DEFS: ParamDef[] = [
  // STOCKS — Score Weights
  { key: 'weight_trend',    label: 'Trend weight',    type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%' },
  { key: 'weight_pullback', label: 'Pullback weight', type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%' },
  { key: 'weight_trigger',  label: 'Trigger weight',  type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%' },
  { key: 'weight_event',    label: 'Event weight',    type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%' },
  { key: 'weight_vol',      label: 'Vol weight',      type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%' },
  // STOCKS — Trend
  { key: 'trend_method',            label: 'Trend method',          type: 'select',  section: 'stocks', subGroup: 'Trend', options: ['additive', 'crossover', 'relative_strength'] },
  // crossover
  { key: 'ma_type',                 label: 'MA type',               type: 'select',  section: 'stocks', subGroup: 'Trend', options: ['EMA', 'SMA'],           visibleFor: ['crossover'] },
  { key: 'fast_ema',                label: 'Fast MA period',        type: 'number',  section: 'stocks', subGroup: 'Trend', min: 5,   max: 200, step: 1,       visibleFor: ['crossover'] },
  { key: 'slow_ema',                label: 'Slow MA period',        type: 'number',  section: 'stocks', subGroup: 'Trend', min: 10,  max: 500, step: 1,       visibleFor: ['crossover'] },
  // additive
  { key: 'additive_ma_type',        label: 'MA type',               type: 'select',  section: 'stocks', subGroup: 'Trend', options: ['EMA', 'SMA'],           visibleFor: ['additive'] },
  { key: 'additive_ma_period',      label: 'MA period',             type: 'number',  section: 'stocks', subGroup: 'Trend', min: 5,   max: 200, step: 1,       visibleFor: ['additive'] },
  { key: 'additive_slope_lookback', label: 'Slope lookback',        type: 'number',  section: 'stocks', subGroup: 'Trend', min: 1,   max: 50,  step: 1, unit: 'bars', visibleFor: ['additive'] },
  { key: 'additive_adx_period',     label: 'ADX period',            type: 'number',  section: 'stocks', subGroup: 'Trend', min: 5,   max: 30,  step: 1,       visibleFor: ['additive'] },
  { key: 'additive_adx_pass',       label: 'ADX pass threshold',    type: 'number',  section: 'stocks', subGroup: 'Trend', min: 0,   max: 60,  step: 1,       visibleFor: ['additive'] },
  { key: 'additive_adx_caution',    label: 'ADX caution threshold', type: 'number',  section: 'stocks', subGroup: 'Trend', min: 0,   max: 50,  step: 1,       visibleFor: ['additive'] },
  { key: 'additive_price_max',      label: 'Price factor max pts',  type: 'number',  section: 'stocks', subGroup: 'Trend', min: 0,   max: 100, step: 5,       visibleFor: ['additive'] },
  { key: 'additive_slope_max',      label: 'Slope factor max pts',  type: 'number',  section: 'stocks', subGroup: 'Trend', min: 0,   max: 100, step: 5,       visibleFor: ['additive'] },
  { key: 'additive_adx_max',        label: 'ADX factor max pts',    type: 'number',  section: 'stocks', subGroup: 'Trend', min: 0,   max: 100, step: 5,       visibleFor: ['additive'] },
  // relative_strength
  { key: 'rs_period',               label: 'RS period',             type: 'number',  section: 'stocks', subGroup: 'Trend', min: 1,   max: 252, step: 1, unit: 'days', visibleFor: ['relative_strength'] },
  { key: 'rs_pass_threshold',       label: 'RS pass threshold',     type: 'number',  section: 'stocks', subGroup: 'Trend', min: -10, max: 20,  step: 0.5, unit: '%', visibleFor: ['relative_strength'] },
  { key: 'rs_caution_threshold',    label: 'RS caution threshold',  type: 'number',  section: 'stocks', subGroup: 'Trend', min: -10, max: 10,  step: 0.5, unit: '%', visibleFor: ['relative_strength'] },
  { key: 'rs_benchmark',            label: 'Benchmark index',       type: 'select',  section: 'stocks', subGroup: 'Trend', options: ['NDX', 'SPX'],            visibleFor: ['relative_strength'] },
  // STOCKS — Pullback
  { key: 'rsi_period',               label: 'RSI period',          type: 'display', section: 'stocks', subGroup: 'Pullback' },
  { key: 'swing_high_lookback_bars', label: 'Swing high lookback', type: 'number',  section: 'stocks', subGroup: 'Pullback', min: 2, max: 200, step: 1 },
  { key: 'atr_caution_max',          label: 'ATR caution max',     type: 'number',  section: 'stocks', subGroup: 'Pullback', min: 0, max: 10, step: 0.1 },
  // STOCKS — Trigger
  { key: 'macd_fast',           label: 'MACD fast',        type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 50,  step: 1 },
  { key: 'macd_slow',           label: 'MACD slow',        type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 100, step: 1 },
  { key: 'macd_signal',         label: 'MACD signal',      type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 50,  step: 1 },
  { key: 'rsi_floor',           label: 'RSI floor',        type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 0, max: 100, step: 1 },
  { key: 'volume_lookback_bars', label: 'Volume lookback', type: 'display', section: 'stocks', subGroup: 'Trigger' },
  { key: 'volume_multiplier',    label: 'Volume multiplier', type: 'display', section: 'stocks', subGroup: 'Trigger' },
  // STOCKS — Event
  { key: 'event_reject_days',    label: 'Event reject days',  type: 'number',  section: 'stocks', subGroup: 'Event', min: 0, max: 90,  step: 1, unit: 'days' },
  { key: 'event_caution_days',   label: 'Event caution days', type: 'number',  section: 'stocks', subGroup: 'Event', min: 0, max: 120, step: 1, unit: 'days' },
  { key: 'earnings_buffer_days', label: 'Earnings buffer',    type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  { key: 'fomc_buffer_days',     label: 'FOMC buffer',        type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  { key: 'div_buffer_days',      label: 'Div buffer',         type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  // STOCKS — Volatility
  { key: 'iv_rank_pass_max', label: 'IV rank pass max',  type: 'number',  section: 'stocks', subGroup: 'Volatility', min: 0, max: 100, step: 1 },
  { key: 'iv_rank_lookback', label: 'IV rank lookback',  type: 'display', section: 'stocks', subGroup: 'Volatility' },
  { key: 'hv_lookback',      label: 'HV period',         type: 'display', section: 'stocks', subGroup: 'Volatility' },
  // STOCKS — Confidence (signal backtest gate)
  { key: 'confidence_caution_below', label: 'Confidence caution below', type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%' },
  { key: 'confidence_reject_below',  label: 'Confidence reject below',  type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%' },
  { key: 'confidence_atr_mult',      label: 'Confidence ATR multiple',  type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0.5, max: 5,   step: 0.1 },
  // OPTIONS — Contract
  { key: 'max_delta',              label: 'Max delta',             type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01 },
  { key: 'max_bid_ask_spread_pct', label: 'Bid-ask spread ceiling', type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,    step: 0.01 },
  { key: 'min_volume',             label: 'Min option volume',     type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10 },
  { key: 'min_open_interest',      label: 'Min open interest',     type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10 },
  { key: 'min_delta',              label: 'Min delta (far OTM)',   type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01 },
  { key: 'min_dte',                label: 'Min DTE',               type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 365, step: 1, unit: 'days' },
  { key: 'max_dte',                label: 'Max DTE',               type: 'number', section: 'options', subGroup: 'Contract', min: 1, max: 730, step: 1, unit: 'days' },
];

type ParamDefaults = Record<string, number | boolean | string | null>;

const PARAM_DEFAULTS_PER_HORIZON: Record<HorizonKey, ParamDefaults> = {
  Intraday: {
    confidence_caution_below: 50, confidence_reject_below: 35, confidence_atr_mult: 1.5,
    weight_trend: 35, weight_pullback: 20, weight_trigger: 30, weight_event: 5,  weight_vol: 10,
    ma_type: 'EMA', fast_ema: 20, slow_ema: 50, adx_period: 7, ema_required: false, rsi_period: 14,
    swing_high_lookback_bars: 20, atr_caution_max: 2.5,
    macd_fast: 5, macd_slow: 13, macd_signal: 3, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
    event_reject_days: 1, event_caution_days: 3,
    earnings_buffer_days: 1, fomc_buffer_days: 1, div_buffer_days: 1,
    iv_rank_pass_max: null, iv_rank_lookback: 30, hv_lookback: 10,
    max_delta: 0.85, max_bid_ask_spread_pct: 0.20,
    min_volume: 50, min_open_interest: 200, min_delta: 0.20, min_dte: 1, max_dte: 7,
    trend_method: 'additive',
    additive_ma_period: 9, additive_ma_type: 'EMA', additive_slope_lookback: 3,
    additive_adx_period: 7, additive_adx_pass: 20, additive_adx_caution: 15,
    additive_price_max: 40, additive_slope_max: 30, additive_adx_max: 30,
    rs_period: 2, rs_pass_threshold: 1.0, rs_caution_threshold: -0.5, rs_benchmark: 'NDX',
  },
  Swing: {
    confidence_caution_below: 50, confidence_reject_below: 35, confidence_atr_mult: 1.5,
    weight_trend: 30, weight_pullback: 20, weight_trigger: 25, weight_event: 15, weight_vol: 10,
    ma_type: 'EMA', fast_ema: 50, slow_ema: 200, adx_period: 14, ema_required: true, rsi_period: 14,
    swing_high_lookback_bars: 40, atr_caution_max: 2.5,
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
    event_reject_days: 7, event_caution_days: 21,
    earnings_buffer_days: 7, fomc_buffer_days: 3, div_buffer_days: 3,
    iv_rank_pass_max: 34, iv_rank_lookback: 252, hv_lookback: 20,
    max_delta: 0.85, max_bid_ask_spread_pct: 0.20,
    min_volume: 50, min_open_interest: 200, min_delta: 0.20, min_dte: 14, max_dte: 45,
    trend_method: 'additive',
    additive_ma_period: 20, additive_ma_type: 'SMA', additive_slope_lookback: 10,
    additive_adx_period: 14, additive_adx_pass: 25, additive_adx_caution: 20,
    additive_price_max: 40, additive_slope_max: 30, additive_adx_max: 30,
    rs_period: 20, rs_pass_threshold: 2.0, rs_caution_threshold: -1.0, rs_benchmark: 'NDX',
  },
  Position: {
    confidence_caution_below: 50, confidence_reject_below: 35, confidence_atr_mult: 1.5,
    weight_trend: 30, weight_pullback: 20, weight_trigger: 20, weight_event: 20, weight_vol: 10,
    ma_type: 'EMA', fast_ema: 50, slow_ema: 200, adx_period: 14, ema_required: true, rsi_period: 14,
    swing_high_lookback_bars: 15, atr_caution_max: 2.5,
    macd_fast: 12, macd_slow: 26, macd_signal: 9, rsi_floor: 48,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
    event_reject_days: 30, event_caution_days: 60,
    earnings_buffer_days: 14, fomc_buffer_days: 5, div_buffer_days: 5,
    iv_rank_pass_max: 44, iv_rank_lookback: 252, hv_lookback: 60,
    max_delta: 0.85, max_bid_ask_spread_pct: 0.20,
    min_volume: 50, min_open_interest: 200, min_delta: 0.20, min_dte: 30, max_dte: 90,
    trend_method: 'additive',
    additive_ma_period: 50, additive_ma_type: 'SMA', additive_slope_lookback: 20,
    additive_adx_period: 14, additive_adx_pass: 20, additive_adx_caution: 15,
    additive_price_max: 40, additive_slope_max: 30, additive_adx_max: 30,
    rs_period: 50, rs_pass_threshold: 3.0, rs_caution_threshold: -1.5, rs_benchmark: 'SPX',
  },
  Custom: {
    confidence_caution_below: 50, confidence_reject_below: 35, confidence_atr_mult: 1.5,
    weight_trend: 30, weight_pullback: 20, weight_trigger: 25, weight_event: 15, weight_vol: 10,
    ma_type: 'EMA', fast_ema: 50, slow_ema: 200, adx_period: 14, ema_required: true, rsi_period: 14,
    swing_high_lookback_bars: 40, atr_caution_max: 2.5,
    macd_fast: 8, macd_slow: 21, macd_signal: 5, rsi_floor: 44,
    volume_lookback_bars: 20, volume_multiplier: 1.2,
    event_reject_days: 7, event_caution_days: 21,
    earnings_buffer_days: 7, fomc_buffer_days: 3, div_buffer_days: 3,
    iv_rank_pass_max: 34, iv_rank_lookback: 252, hv_lookback: 20,
    max_delta: 0.85, max_bid_ask_spread_pct: 0.20,
    min_volume: 50, min_open_interest: 200, min_delta: 0.20, min_dte: 14, max_dte: 90,
    trend_method: 'additive',
    additive_ma_period: 20, additive_ma_type: 'SMA', additive_slope_lookback: 10,
    additive_adx_period: 14, additive_adx_pass: 25, additive_adx_caution: 20,
    additive_price_max: 40, additive_slope_max: 30, additive_adx_max: 30,
    rs_period: 20, rs_pass_threshold: 2.0, rs_caution_threshold: -1.0, rs_benchmark: 'NDX',
  },
};

function formatDefault(val: number | boolean | string | null): string {
  if (val === null) return 'N/A';
  if (typeof val === 'boolean') return val ? 'On' : 'Off';
  if (typeof val === 'string') return val;
  return String(val);
}

function countActiveOverrides(defs: ParamDef[], overrides: Record<string, number | boolean | string>, defaults: ParamDefaults): number {
  return defs.filter((d) => {
    if (d.redundant || d.deprecated || d.type === 'display') return false;
    const ov = overrides[d.key];
    if (ov === undefined) return false;
    return ov !== defaults[d.key];
  }).length;
}

// ── Param row component ───────────────────────────────────────────────────────

function ParamRow({
  def,
  defaultVal,
  scanOverrides,
}: {
  def: ParamDef;
  defaultVal: number | boolean | string | null;
  scanOverrides: Record<string, number | boolean | string>;
}) {
  const currentOverride = scanOverrides[def.key];
  const isNa = defaultVal === null;

  // Redundant rows — static value with badge, never editable
  if (def.redundant) {
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12} tone="dim">{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11} tone="dim">{formatDefault(defaultVal)}</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <span className={formStyles.redundantNote}>(redundant)</span>
        </div>
      </div>
    );
  }

  // Display-only rows — static value, no interaction
  if (def.type === 'display') {
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12} tone="dim">{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11}>{isNa ? 'N/A' : formatDefault(defaultVal)}</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <Text size={11} tone="dim">display only</Text>
        </div>
      </div>
    );
  }

  // N/A rows (Intraday iv_rank_pass_max)
  if (isNa) {
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12} tone="dim">{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11} tone="dim">N/A</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <Text size={11} tone="dim">&mdash;</Text>
        </div>
      </div>
    );
  }

  // Deprecated boolean (ema_required)
  if (def.deprecated) {
    const isOn = typeof defaultVal === 'boolean' ? defaultVal : false;
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12} tone="dim">{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11} tone="dim">{isOn ? 'On' : 'Off'}</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <span className={formStyles.redundantNote}>(superseded by MA type)</span>
        </div>
      </div>
    );
  }

  // Select (ma_type — SMA/EMA segmented toggle)
  if (def.type === 'select' && def.options) {
    const current = (currentOverride as string | undefined) ?? (defaultVal as string);
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12}>{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11} tone="dim">{formatDefault(defaultVal)}</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <div className={formStyles.segmentedTiny}>
            {def.options.map((opt) => (
              <button
                key={opt}
                type="button"
                className={`${formStyles.segTiny} ${current === opt ? formStyles.segTinyActive : ''}`}
                onClick={() => {
                  if (opt === defaultVal) {
                    const next = { ...scanOverrides };
                    delete next[def.key];
                    useScanStore.getState().setScanOverrides(next);
                  } else {
                    useScanStore.getState().setScanOverrides({ ...scanOverrides, [def.key]: opt });
                  }
                }}
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Boolean toggle
  if (def.type === 'boolean') {
    const isOn = currentOverride !== undefined
      ? (currentOverride as boolean)
      : (defaultVal as boolean);
    return (
      <div className={formStyles.paramsRow} data-param-key={def.key}>
        <Text size={12}>{def.label}</Text>
        <div className={formStyles.paramsValue}>
          <Data size={11} tone="dim">{formatDefault(defaultVal)}</Data>
        </div>
        <div className={formStyles.paramsInput}>
          <button
            type="button"
            className={`${formStyles.toggleBtn} ${isOn ? formStyles.toggleOn : ''}`}
            onClick={() => {
              const next = { ...scanOverrides, [def.key]: !isOn };
              useScanStore.getState().setScanOverrides(next);
            }}
            aria-label={def.label}
          >
            {isOn ? 'On' : 'Off'}
          </button>
        </div>
      </div>
    );
  }

  // Number input
  const inputValue = currentOverride !== undefined
    ? String(currentOverride)
    : String(defaultVal);

  return (
    <div className={formStyles.paramsRow} data-param-key={def.key}>
      <Text size={12}>{def.label}</Text>
      <div className={formStyles.paramsValue}>
        <Data size={11} tone="dim">{formatDefault(defaultVal)}</Data>
      </div>
      <div className={formStyles.paramsInput}>
        <input
          type="number"
          className={formStyles.numInput}
          value={inputValue}
          min={def.min}
          max={def.max}
          step={def.step}
          aria-label={def.label}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === '' || raw === String(defaultVal)) {
              const next = { ...scanOverrides };
              delete next[def.key];
              useScanStore.getState().setScanOverrides(next);
            } else {
              const num = Number(raw);
              if (!Number.isNaN(num)) {
                useScanStore.getState().setScanOverrides({ ...scanOverrides, [def.key]: num });
              }
            }
          }}
        />
        {def.unit && <Text size={11} tone="dim">{def.unit}</Text>}
      </div>
    </div>
  );
}

// ── Collapsible sub-group block ───────────────────────────────────────────────

function SubGroupBlock({
  label,
  open,
  onToggle,
  overrideCount,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  overrideCount: number;
  children: React.ReactNode;
}) {
  return (
    <div className={formStyles.subGroup}>
      <button type="button" className={formStyles.subGroupHeader} onClick={onToggle} aria-expanded={open}>
        <Text size={11} weight={500} tone="secondary">{label}</Text>
        {overrideCount > 0 && !open && (
          <span className={formStyles.overrideBadge}>{overrideCount} override{overrideCount !== 1 ? 's' : ''}</span>
        )}
        <span className={`${formStyles.chevron} ${open ? formStyles.chevronOpen : ''}`} style={{ marginLeft: 'auto' }} aria-hidden>▾</span>
      </button>
      {open && <div className={formStyles.subGroupBody}>{children}</div>}
    </div>
  );
}

// ── Collapsible section block (STOCKS / OPTIONS) ──────────────────────────────

function SectionBlock({
  label,
  open,
  onToggle,
  overrideCount,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  overrideCount: number;
  children: React.ReactNode;
}) {
  return (
    <div className={formStyles.sectionBlock}>
      <button type="button" className={formStyles.sectionHeader} onClick={onToggle} aria-expanded={open}>
        <Text size={12} weight={500}>{label}</Text>
        {overrideCount > 0 && !open && (
          <span className={formStyles.overrideBadge}>{overrideCount} override{overrideCount !== 1 ? 's' : ''}</span>
        )}
        <span className={`${formStyles.chevron} ${open ? formStyles.chevronOpen : ''}`} style={{ marginLeft: 'auto' }} aria-hidden>▾</span>
      </button>
      {open && <div className={formStyles.sectionBody}>{children}</div>}
    </div>
  );
}

// ── Horizon helpers ───────────────────────────────────────────────────────────

function horizonLabel(hz: HorizonKey, minDays: number, maxDays: number): string {
  if (hz === 'Intraday') return 'Intraday (0–2d)';
  if (hz === 'Swing')    return 'Swing (5–15d)';
  if (hz === 'Position') return 'Position (15–45d)';
  return `Custom (${minDays}–${maxDays}d)`;
}

function parseHorizonKey(h: string | undefined): HorizonKey {
  if (!h) return 'Swing';
  if (h.startsWith('Intraday')) return 'Intraday';
  if (h.startsWith('Swing'))    return 'Swing';
  if (h.startsWith('Position')) return 'Position';
  if (h.startsWith('Custom'))   return 'Custom';
  return 'Swing';
}

function parseCustomDays(h: string | undefined): [number, number] {
  if (!h?.startsWith('Custom')) return [5, 15];
  const m = h.match(/(\d+)–(\d+)/);
  return m ? [Number(m[1]), Number(m[2])] : [5, 15];
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Step2Page() {
  const context       = useScanStore((s) => s.context);
  const setContext    = useScanStore((s) => s.setContext);
  const rejectedLog   = useScanStore((s) => s.rejectedLog);
  const regime        = useScanStore((s) => s.regime);
  const scanOverrides = useScanStore((s) => s.scanOverrides);
  const scanResult    = useScanStore((s) => s.scanResult);

  const [dir,     setDir]     = useState<Direction>(() => context?.direction ?? 'Bullish');
  const [hz,      setHz]      = useState<HorizonKey>(() => parseHorizonKey(context?.horizon));
  const [minDays, setMinDays] = useState<number>(() => parseCustomDays(context?.horizon)[0]);
  const [maxDays, setMaxDays] = useState<number>(() => parseCustomDays(context?.horizon)[1]);
  const [isExpanded,  setIsExpanded]  = useState(false);
  const [stocksOpen,  setStocksOpen]  = useState(true);
  const [optionsOpen, setOptionsOpen] = useState(true);
  const [subGroupOpen, setSubGroupOpen] = useState<Record<string, boolean>>({
    'Score Weights': true, Trend: true, Pullback: true, Trigger: true, Event: true, Volatility: true, Contract: true,
  });

  useEffect(() => {
    api.getRegime().then((r) => {
      useScanStore.getState().setRegime(r.overall);
    }).catch(() => {});
  }, []);

  const toggleSubGroup = useCallback((name: string) => {
    setSubGroupOpen((prev) => ({ ...prev, [name]: !(prev[name] ?? true) }));
  }, []);

  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    setContext({
      universe:  context?.universe ?? 'SP500',
      direction: newDir,
      horizon:   horizonLabel(newHz, newMin, newMax),
    });
  }

  const handleDirChange = (d: Direction) => {
    setDir(d);
    syncToStore(d, hz, minDays, maxDays);
  };
  const handleHzChange = (h: HorizonKey) => {
    setHz(h);
    syncToStore(dir, h, minDays, maxDays);
    const hd = PARAM_DEFAULTS_PER_HORIZON[h];
    useScanStore.getState().setScanOverrides({
      ma_type:                hd.ma_type                as string,
      fast_ema:               hd.fast_ema               as number,
      slow_ema:               hd.slow_ema               as number,
      trend_method:           hd.trend_method           as string,
      additive_ma_period:     hd.additive_ma_period     as number,
      additive_ma_type:       hd.additive_ma_type       as string,
      additive_slope_lookback: hd.additive_slope_lookback as number,
      additive_adx_period:    hd.additive_adx_period    as number,
      additive_adx_pass:      hd.additive_adx_pass      as number,
      additive_adx_caution:   hd.additive_adx_caution   as number,
      additive_price_max:     hd.additive_price_max     as number,
      additive_slope_max:     hd.additive_slope_max     as number,
      additive_adx_max:       hd.additive_adx_max       as number,
      rs_period:              hd.rs_period              as number,
      rs_pass_threshold:      hd.rs_pass_threshold      as number,
      rs_caution_threshold:   hd.rs_caution_threshold   as number,
      rs_benchmark:           hd.rs_benchmark           as string,
    });
  };
  const handleMinChange = (v: number) => {
    setMinDays(v);
    syncToStore(dir, hz, v, maxDays);
  };
  const handleMaxChange = (v: number) => {
    const clamped = Math.max(minDays, v);
    setMaxDays(clamped);
    syncToStore(dir, hz, minDays, clamped);
  };

  const custom = hz === 'Custom';
  const defaults = PARAM_DEFAULTS_PER_HORIZON[hz];

  const totalPassed   = scanResult?.candidates?.length ?? 0;
  const totalRejected = rejectedLog.length;
  const totalScanned  = totalPassed + totalRejected;

  const effectiveMinDte = (scanOverrides.min_dte as number | undefined) ?? (defaults.min_dte as number);
  const effectiveMaxDte = (scanOverrides.max_dte as number | undefined) ?? (defaults.max_dte as number);

  const horizonKey = context?.horizon?.startsWith('Intraday') ? 'Intraday'
    : context?.horizon?.startsWith('Position') ? 'Position'
    : 'Swing';

  const stocksDefs  = PARAM_DEFS.filter((d) => d.section === 'stocks');
  const optionsDefs = PARAM_DEFS.filter((d) => d.section === 'options');
  const stockSubGroups  = [...new Set(stocksDefs.map((d) => d.subGroup))];
  const optionSubGroups = [...new Set(optionsDefs.map((d) => d.subGroup))];

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 3 OF 7</Text>
        <Title as="h1" size={24}>Direction + Horizon</Title>
        <Text size={13} tone="secondary">Choose your directional bias and holding horizon.</Text>
        {regime === 'REJECT' && (
          <div className={formStyles.regimeBadge}>
            <Text size={11} tone="reject" weight={500}>REGIME REJECT — confirm before scanning</Text>
          </div>
        )}
      </div>

      <div className={formStyles.group}>
        <Text size={12} weight={600}>Directional bias</Text>
        <div className={formStyles.segmented}>
          {DIRECTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => handleDirChange(d)}
              className={`${formStyles.seg} ${dir === d ? formStyles.segActive : ''}`}
              aria-pressed={dir === d}
            >
              <Text size={13} weight={500}>{d}</Text>
            </button>
          ))}
        </div>
      </div>

      <div className={formStyles.group}>
        <Text size={12} weight={600}>Holding horizon</Text>
        <div className={formStyles.segmented}>
          {HORIZON_PRESETS.map((h) => (
            <button
              key={h.key}
              type="button"
              onClick={() => handleHzChange(h.key)}
              className={`${formStyles.seg} ${hz === h.key ? formStyles.segActive : ''}`}
              aria-pressed={hz === h.key}
            >
              <Text size={13} weight={500}>{h.label}</Text>
              <Text size={11} tone="secondary">{h.hint}</Text>
            </button>
          ))}
        </div>

        <div className={formStyles.customRow}>
          <Text size={12} tone={custom ? 'secondary' : 'dim'}>Range (days)</Text>
          <div className={formStyles.customInputs}>
            <input
              type="number"
              className={formStyles.numInput}
              value={minDays}
              min={0}
              max={365}
              disabled={!custom}
              onChange={(e) => handleMinChange(Math.max(0, Number(e.target.value)))}
              aria-label="Minimum days"
            />
            <Text size={12} tone="dim">to</Text>
            <input
              type="number"
              className={formStyles.numInput}
              value={maxDays}
              min={0}
              max={365}
              disabled={!custom}
              onChange={(e) => handleMaxChange(Number(e.target.value))}
              aria-label="Maximum days"
            />
          </div>
        </div>
      </div>

      {/* ── Execution Parameters panel ── */}
      <div className={formStyles.paramsPanel}>
        <button
          type="button"
          className={formStyles.paramsHeader}
          onClick={() => setIsExpanded((v) => !v)}
          aria-expanded={isExpanded}
        >
          <Text size={12} weight={500}>Execution Parameters</Text>
          <span className={formStyles.paramsChevron} aria-hidden>
            {isExpanded ? '▾ Collapse' : '▸ Expand'}
          </span>
        </button>

        {isExpanded && (
          <div className={formStyles.paramsBody}>

            {/* STOCKS section */}
            <SectionBlock
              label="STOCKS"
              open={stocksOpen}
              onToggle={() => setStocksOpen((v) => !v)}
              overrideCount={countActiveOverrides(stocksDefs, scanOverrides, defaults)}
            >
              {stockSubGroups.map((sg) => {
                const sgDefs = stocksDefs.filter((d) => d.subGroup === sg);
                const sgOpen = subGroupOpen[sg] ?? true;
                const currentTrendMethod = (scanOverrides.trend_method as string | undefined) ?? (defaults.trend_method as string ?? 'additive');
                const visibleDefs = sgDefs.filter((d) => !d.visibleFor || d.visibleFor.includes(currentTrendMethod));
                return (
                  <SubGroupBlock
                    key={sg}
                    label={sg}
                    open={sgOpen}
                    onToggle={() => toggleSubGroup(sg)}
                    overrideCount={countActiveOverrides(visibleDefs, scanOverrides, defaults)}
                  >
                    {visibleDefs.map((def) => (
                      <ParamRow
                        key={def.key}
                        def={def}
                        defaultVal={defaults[def.key] ?? null}
                        scanOverrides={scanOverrides}
                      />
                    ))}
                  </SubGroupBlock>
                );
              })}
            </SectionBlock>

            {/* OPTIONS section */}
            <SectionBlock
              label="OPTIONS"
              open={optionsOpen}
              onToggle={() => setOptionsOpen((v) => !v)}
              overrideCount={countActiveOverrides(optionsDefs, scanOverrides, defaults)}
            >
              {optionSubGroups.map((sg) => {
                const sgDefs = optionsDefs.filter((d) => d.subGroup === sg);
                const sgOpen = subGroupOpen[sg] ?? true;
                return (
                  <SubGroupBlock
                    key={sg}
                    label={sg}
                    open={sgOpen}
                    onToggle={() => toggleSubGroup(sg)}
                    overrideCount={countActiveOverrides(sgDefs, scanOverrides, defaults)}
                  >
                    {sgDefs.map((def) => (
                      <ParamRow
                        key={def.key}
                        def={def}
                        defaultVal={defaults[def.key] ?? null}
                        scanOverrides={scanOverrides}
                      />
                    ))}
                  </SubGroupBlock>
                );
              })}
            </SectionBlock>

            <div className={formStyles.paramsFooter}>
              <button
                type="button"
                className={formStyles.paramsReset}
                onClick={() => useScanStore.getState().setScanOverrides({})}
              >
                Reset to defaults
              </button>
            </div>
          </div>
        )}
      </div>

      <div className={formStyles.logSection}>
        <div className={formStyles.logHeader}>
          <Text size={11} tone="dim" weight={500}>SCAN LOG</Text>
          <div className={formStyles.logStats}>
            {totalScanned > 0 && (
              <>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="dim">Scanned</Text>
                  <span className={formStyles.badge}>{totalScanned}</span>
                </span>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="pass">Passed</Text>
                  <span className={`${formStyles.badge} ${formStyles.badgePass}`}>{totalPassed}</span>
                </span>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="reject">Rejected</Text>
                  <span className={`${formStyles.badge} ${formStyles.badgeReject}`}>{totalRejected}</span>
                </span>
                <span className={formStyles.logStat}>
                  <Text size={11} tone="dim">DTE</Text>
                  <Text size={11} tone="secondary">{effectiveMinDte}–{effectiveMaxDte}d</Text>
                </span>
              </>
            )}
            {totalScanned === 0 && rejectedLog.length > 0 && (
              <span className={formStyles.badge}>{rejectedLog.length}</span>
            )}
          </div>
        </div>
        <ScanLogSection entries={rejectedLog} horizonKey={horizonKey} />
      </div>

      <RunScanButton />
    </div>
  );
}
