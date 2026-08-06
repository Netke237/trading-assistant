'use client';

/*
 * Screener Step 3 — Direction + Horizon.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 * Round 5: full 34-param Execution Parameters panel — Stocks / Options sections,
 * per-subgroup collapse, Score Weights from Settings migrated here.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import type { Direction } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import type { RejectedEntry } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { alignmentVerdict, descriptorFromState, type RegimeDescriptor } from '@/lib/regimeAlignment';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { SearchProfileBar } from '@/components/organisms/SearchProfileBar';
import styles from '../screener.module.css';
import formStyles from './page.module.css';
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, horizonDisplayString,
  resolveParamsHorizon, type HorizonKey, type ScoringHorizon,
} from '@/lib/horizonPresets';
import { PARAM_DEFAULTS_PER_HORIZON, type ParamDefaults } from '@/lib/executionParamDefaults';

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

const GROUPED_PREFIXES = ['Pre-screen:', 'Score gate:'];

function ScanLogSection({ entries, horizonKey }: { entries: RejectedEntry[]; horizonKey: string }) {
  if (entries.length === 0) return null;
  const stockRejects = entries.filter((e) => GROUPED_PREFIXES.some((p) => e.reason.startsWith(p)));
  const otherRejects = entries.filter((e) => !GROUPED_PREFIXES.some((p) => e.reason.startsWith(p)));
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

// ── Execution Parameters types ────────────────────────────────────────────────

interface ParamDef {
  key: string;
  label: string;
  type: 'number' | 'boolean' | 'select' | 'display';
  section: 'stocks' | 'options' | 'all';
  subGroup: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  hint?: string;
  redundant?: true;
  deprecated?: true;
  visibleFor?: string[];   // if set, only show when scanOverrides.trend_method (or default) is in this list
}

const PARAM_DEFS: ParamDef[] = [
  // STOCKS — Score Weights
  { key: 'weight_trend',    label: 'Trend weight',    type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Share of composite score from trend analysis. ↑ Higher → only clear trends pass (fewer results) · ↓ Lower → sideways stocks qualify (more results)' },
  { key: 'weight_pullback', label: 'Pullback weight', type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Share of score from pullback quality. ↑ Higher → only clean, shallow pullbacks pass (fewer) · ↓ Lower → any pullback depth qualifies (more)' },
  { key: 'weight_trigger',  label: 'Trigger weight',  type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Share of score from momentum timing signals. ↑ Higher → only active buying pressure qualifies (fewer) · ↓ Lower → weaker signals still pass (more)' },
  { key: 'weight_event',    label: 'Event weight',    type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Share of score from catalyst proximity. ↑ Higher → upcoming events penalise more stocks (fewer) · ↓ Lower → events count for less (more)' },
  { key: 'weight_vol',      label: 'Vol weight',      type: 'number', section: 'stocks', subGroup: 'Score Weights', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Share of score from IV conditions. ↑ Higher → only calm-IV stocks qualify (fewer) · ↓ Lower → high-IV stocks still pass (more)' },
  // STOCKS — Trend
  { key: 'trend_method', label: 'Trend method', type: 'select', section: 'stocks', subGroup: 'Trend', options: ['additive', 'crossover', 'relative_strength'],
    hint: 'Algorithm for scoring trend strength. Additive = price + slope + ADX combined; Crossover = MA crossover signal; Relative Strength = return vs. benchmark index' },
  // crossover
  { key: 'ma_type',  label: 'MA type',        type: 'select', section: 'stocks', subGroup: 'Trend', options: ['EMA', 'SMA'], visibleFor: ['crossover'],
    hint: 'Moving average type. EMA reacts faster to recent price (more signals, more results); SMA is smoother (fewer, calmer signals)' },
  { key: 'fast_ema', label: 'Fast MA period', type: 'number', section: 'stocks', subGroup: 'Trend', min: 5,  max: 200, step: 1, visibleFor: ['crossover'],
    hint: 'Short-period MA that detects momentum change. ↑ Higher → fewer, slower crossover signals · ↓ Lower → more frequent but noisier signals' },
  { key: 'slow_ema', label: 'Slow MA period', type: 'number', section: 'stocks', subGroup: 'Trend', min: 10, max: 500, step: 1, visibleFor: ['crossover'],
    hint: 'Long-period MA representing the primary trend. ↑ Higher → stronger trend required (fewer results) · ↓ Lower → shallower trends qualify (more)' },
  // additive
  { key: 'additive_ma_type',        label: 'MA type',              type: 'select', section: 'stocks', subGroup: 'Trend', options: ['EMA', 'SMA'], visibleFor: ['additive'],
    hint: 'Moving average type for the additive model. EMA → faster reaction (more results); SMA → smoother baseline (fewer results)' },
  { key: 'additive_ma_period',      label: 'MA period',            type: 'number', section: 'stocks', subGroup: 'Trend', min: 5,  max: 200, step: 1, visibleFor: ['additive'],
    hint: 'Period of the trend-defining MA. ↑ Higher → longer trend baseline required (fewer) · ↓ Lower → more stocks qualify (more)' },
  { key: 'additive_slope_lookback', label: 'Slope lookback',       type: 'number', section: 'stocks', subGroup: 'Trend', min: 1,  max: 50,  step: 1, unit: 'bars', visibleFor: ['additive'],
    hint: 'Bars used to measure MA angle (steepness). ↑ Higher → smoother reading, misses early moves · ↓ Lower → reacts faster but noisier' },
  { key: 'additive_adx_period',     label: 'ADX period',           type: 'number', section: 'stocks', subGroup: 'Trend', min: 5,  max: 30,  step: 1, visibleFor: ['additive'],
    hint: 'Bars for the Average Directional Index. ↑ Higher → smoother but slower ADX · ↓ Lower → quicker but noisier' },
  { key: 'additive_adx_pass',       label: 'ADX pass threshold',   type: 'number', section: 'stocks', subGroup: 'Trend', min: 0,  max: 60,  step: 1, visibleFor: ['additive'],
    hint: 'Minimum ADX value for a PASS score. ↑ Higher → only strong trends qualify (fewer) · ↓ Lower → weak trends also pass (more)' },
  { key: 'additive_adx_caution',    label: 'ADX caution threshold',type: 'number', section: 'stocks', subGroup: 'Trend', min: 0,  max: 50,  step: 1, visibleFor: ['additive'],
    hint: 'ADX below this triggers CAUTION. ↑ Higher → broader caution zone, fewer clean passes · ↓ Lower → narrower caution zone, more passes' },
  { key: 'additive_price_max',      label: 'Price factor max pts', type: 'number', section: 'stocks', subGroup: 'Trend', min: 0,  max: 100, step: 5, visibleFor: ['additive'],
    hint: 'Max points the price-above-MA check can contribute. ↑ Higher → price position dominates the trend score · ↓ Lower → price position matters less' },
  { key: 'additive_slope_max',      label: 'Slope factor max pts', type: 'number', section: 'stocks', subGroup: 'Trend', min: 0,  max: 100, step: 5, visibleFor: ['additive'],
    hint: 'Max points MA steepness can contribute. ↑ Higher → trend angle matters more · ↓ Lower → slope carries less weight' },
  { key: 'additive_adx_max',        label: 'ADX factor max pts',   type: 'number', section: 'stocks', subGroup: 'Trend', min: 0,  max: 100, step: 5, visibleFor: ['additive'],
    hint: 'Max points ADX strength can contribute. ↑ Higher → directional strength required · ↓ Lower → ADX matters less' },
  // relative_strength
  { key: 'rs_period',            label: 'RS period',           type: 'number', section: 'stocks', subGroup: 'Trend', min: 1,   max: 252, step: 1,   unit: 'days', visibleFor: ['relative_strength'],
    hint: 'Days of return used for benchmark comparison. ↑ Higher → structural outperformance required · ↓ Lower → recent momentum only' },
  { key: 'rs_pass_threshold',    label: 'RS pass threshold',   type: 'number', section: 'stocks', subGroup: 'Trend', min: -10, max: 20,  step: 0.5, unit: '%',   visibleFor: ['relative_strength'],
    hint: 'Minimum return vs. benchmark for PASS. ↑ Higher → only clear outperformers qualify (fewer) · ↓ Lower → slight outperformers qualify (more)' },
  { key: 'rs_caution_threshold', label: 'RS caution threshold',type: 'number', section: 'stocks', subGroup: 'Trend', min: -10, max: 10,  step: 0.5, unit: '%',   visibleFor: ['relative_strength'],
    hint: 'Return below this triggers CAUTION. ↑ Higher → stricter caution zone · ↓ Lower → slight underperformers still score cleanly' },
  { key: 'rs_benchmark',         label: 'Benchmark index',     type: 'select', section: 'stocks', subGroup: 'Trend', options: ['NDX', 'SPX'],                    visibleFor: ['relative_strength'],
    hint: 'Index used as the return baseline. NDX = tech-heavy comparison; SPX = broad market comparison' },
  // STOCKS — Pullback
  { key: 'rsi_period',               label: 'RSI period',             type: 'display', section: 'stocks', subGroup: 'Pullback',
    hint: 'Bars used to compute RSI. Set in the Trigger group (display only here).' },
  { key: 'swing_high_lookback_bars', label: 'Swing high lookback',    type: 'number',  section: 'stocks', subGroup: 'Pullback', min: 2, max: 200, step: 1,
    hint: 'How many bars back to find the most recent swing high. ↑ Higher → broader context, fewer stocks qualify as pulling back · ↓ Lower → recent highs only (more)' },
  { key: 'atr_caution_max',          label: 'ATR caution max',        type: 'number',  section: 'stocks', subGroup: 'Pullback', min: 0, max: 10, step: 0.1,
    hint: 'Max ATR multiples a move can extend before CAUTION. ↑ Higher → extended moves allowed (more results) · ↓ Lower → only tight pullbacks pass (fewer)' },
  { key: 'pullback_require_reversal',label: 'Require reversal candle',type: 'boolean', section: 'stocks', subGroup: 'Pullback',
    hint: 'Requires a bullish reversal bar at the pullback low (e.g. hammer). On → fewer, higher-conviction entries · Off → all pullbacks qualify' },
  // STOCKS — Trigger
  { key: 'macd_fast',            label: 'MACD fast',          type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 50,  step: 1,
    hint: 'Fast EMA period in MACD. ↑ Higher → fewer, stronger signals · ↓ Lower → more frequent but noisier signals' },
  { key: 'macd_slow',            label: 'MACD slow',          type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 100, step: 1,
    hint: 'Slow EMA period in MACD. ↑ Higher → more pronounced divergence required (fewer) · ↓ Lower → smaller divergences trigger (more)' },
  { key: 'macd_signal',         label: 'MACD signal',         type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 2, max: 50,  step: 1,
    hint: 'Smoothing on the MACD histogram. ↑ Higher → slower, steadier confirmation · ↓ Lower → noisier, faster trigger' },
  { key: 'rsi_floor',           label: 'RSI floor',           type: 'number',  section: 'stocks', subGroup: 'Trigger', min: 0, max: 100, step: 1,
    hint: 'Minimum RSI to confirm momentum is recovering at entry. ↑ Higher → only stocks with active buying qualify (fewer) · ↓ Lower → oversold stocks also pass (more)' },
  { key: 'volume_lookback_bars', label: 'Volume lookback',    type: 'display', section: 'stocks', subGroup: 'Trigger',
    hint: 'Days used to compute the average volume baseline (display only).' },
  { key: 'volume_multiplier',    label: 'Volume multiplier',  type: 'display', section: 'stocks', subGroup: 'Trigger',
    hint: 'Required volume as a multiple of average on the signal day (display only).' },
  // STOCKS — Event
  { key: 'event_reject_days',  label: 'Event reject days',  type: 'number', section: 'stocks', subGroup: 'Event', min: 0, max: 90,  step: 1, unit: 'days',
    hint: 'Stocks with a catalyst within this window are hard-rejected. ↑ Higher → wider safety zone (fewer) · ↓ Lower → closer-to-event entries allowed (more)' },
  { key: 'event_caution_days', label: 'Event caution days', type: 'number', section: 'stocks', subGroup: 'Event', min: 0, max: 120, step: 1, unit: 'days',
    hint: 'Stocks within this wider window get a CAUTION flag instead of reject. ↑ Higher → larger amber zone · ↓ Lower → smaller amber zone' },
  { key: 'earnings_buffer_days', label: 'Earnings buffer', type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  { key: 'fomc_buffer_days',     label: 'FOMC buffer',     type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  { key: 'div_buffer_days',      label: 'Div buffer',      type: 'display', section: 'stocks', subGroup: 'Event', redundant: true },
  // STOCKS — Volatility
  { key: 'iv_rank_pass_max', label: 'IV rank pass max', type: 'number', section: 'options', subGroup: 'Volatility', min: 0, max: 100, step: 1,
    hint: 'Max IV rank (0–100) for a PASS on options contracts. N/A on Intraday. ↑ Higher → elevated-IV stocks still qualify (more) · ↓ Lower → only calm-IV stocks pass (fewer). Per-horizon defaults are set in Settings → Scan.' },
  { key: 'iv_rank_lookback', label: 'IV rank lookback', type: 'display', section: 'stocks', subGroup: 'Volatility',
    hint: 'Lookback window used to normalise current IV into a percentile rank (display only).' },
  { key: 'hv_lookback',      label: 'HV period',        type: 'display', section: 'stocks', subGroup: 'Volatility',
    hint: 'Days used to calculate historical (realised) volatility (display only).' },
  // STOCKS — Confidence (signal backtest gate)
  { key: 'confidence_caution_below', label: 'Confidence caution below', type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%',
    hint: 'Signal backtest win rate below this % triggers CAUTION. ↑ Higher → broader caution zone · ↓ Lower → narrower caution zone' },
  { key: 'confidence_reject_below',  label: 'Confidence reject below',  type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%',
    hint: 'Signal backtest win rate below this % triggers REJECT. ↑ Higher → stricter gate, better-tested results (fewer) · ↓ Lower → looser gate (more)' },
  { key: 'confidence_atr_mult',      label: 'Confidence ATR multiple',  type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0.5, max: 5,   step: 0.1,
    hint: 'R/R ratio used in the mini backtest (target ÷ stop size). ↑ Higher → demands bigger winners (stricter, fewer) · ↓ Lower → accepts smaller winners (more)' },
  // OPTIONS — Contract
  { key: 'max_delta',              label: 'Max delta',              type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Highest delta (0–1) allowed — controls how far in-the-money contracts can be. ↑ Higher → near-the-money contracts allowed (more) · ↓ Lower → OTM-only (fewer)' },
  { key: 'max_bid_ask_spread_pct', label: 'Bid-ask spread ceiling', type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Max spread as a fraction of mid price. ↑ Higher → illiquid contracts included (more, but costly) · ↓ Lower → tight spread required (fewer, cheaper to trade)' },
  { key: 'min_volume',             label: 'Min option volume',      type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10,
    hint: 'Minimum daily contracts traded. ↑ Higher → better liquidity required (fewer) · ↓ Lower → thin markets allowed (more)' },
  { key: 'min_open_interest',      label: 'Min open interest',      type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10,
    hint: 'Minimum outstanding contracts. ↑ Higher → requires an established market (fewer) · ↓ Lower → new or low-traffic strikes included (more)' },
  { key: 'min_delta',              label: 'Min delta (far OTM)',    type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Rejects contracts too far out of the money. ↑ Higher → keeps contracts closer to the money · ↓ Lower → very cheap deep-OTM contracts included' },
  { key: 'min_dte', label: 'Min DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  { key: 'max_dte', label: 'Max DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  // ALL — Regime Gate
  { key: 'regime_headwind_caution_pct', label: 'Headwind caution %', type: 'number', section: 'all', subGroup: 'Regime Gate', min: -100, max: 0, step: 5, unit: '%',
    hint: 'Sector underperformance vs benchmark below this % → CAUTION on candidate. ↑ Higher (closer to 0) → stricter, more candidates caught (fewer pass) · ↓ Lower → only severe laggards affected (more pass). Default: -15%' },
  { key: 'regime_headwind_reject_pct',  label: 'Headwind reject %',  type: 'number', section: 'all', subGroup: 'Regime Gate', min: -100, max: 0, step: 5, unit: '%',
    hint: 'Sector underperformance below this % → hard REJECT regardless of score. ↑ Higher (less negative) → stricter, more rejections · ↓ Lower → only catastrophic laggards rejected (more pass). Default: -40%' },
  // ALL — Fundamentals Bearish
  { key: 'fundamentals_caution_above', label: 'Fundamentals caution above', type: 'number', section: 'all', subGroup: 'Fundamentals Bearish', min: 0, max: 100, step: 5,
    hint: 'BEARISH SCANS ONLY. Fundamental health score above this → CAUTION. Flags risk of shorting a financially strong company. ↑ Higher → only very strong companies flagged (fewer cautions) · ↓ Lower → wider caution zone (more cautions). Default: 70' },
  { key: 'fundamentals_reject_above',  label: 'Fundamentals reject above',  type: 'number', section: 'all', subGroup: 'Fundamentals Bearish', min: 0, max: 100, step: 5,
    hint: 'BEARISH SCANS ONLY. Fundamental health score above this → hard REJECT. Company is too financially strong to short safely. ↑ Higher → only fortress-balance-sheet companies rejected (fewer) · ↓ Lower → stricter, more rejections. Default: 80' },
  // OPTIONS — Entry Quality
  { key: 'entry_spread_tolerance_pct', label: 'Spread tolerance', type: 'number', section: 'options', subGroup: 'Entry Quality', min: 0, max: 0.5, step: 0.01,
    hint: 'Max bid-ask spread as a fraction of mid price at entry. ↑ Higher → wider spreads allowed (more contracts, worse fills) · ↓ Lower → tight spread required (fewer contracts, better fills). Default: 0.10' },
  { key: 'entry_max_slippage_pct',     label: 'Max slippage',     type: 'number', section: 'options', subGroup: 'Entry Quality', min: 0, max: 0.1, step: 0.005,
    hint: 'Expected slippage as a fraction of price. ↑ Higher → accepts poor fills (more, but costlier) · ↓ Lower → only clean-fill entries pass (fewer). Default: 0.03' },
  { key: 'entry_min_premium',          label: 'Min premium',      type: 'number', section: 'options', subGroup: 'Entry Quality', min: 0, max: 5,   step: 0.05, unit: '$',
    hint: 'Minimum option premium per contract in $. ↑ Higher → rejects cheap, illiquid options (fewer) · ↓ Lower → penny options included (more, but harder to exit). Default: $0.10' },
  // ALL — Reward/Risk
  { key: 'rr_bullish_target_pct',       label: 'Bullish target %',       type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.01, max: 2.0, step: 0.01, unit: '%',
    hint: 'Profit target as a fraction of entry for bullish trades. ↑ Higher → demands bigger moves (fewer qualify, R/R better) · ↓ Lower → takes smaller wins (more qualify). Default: 8%' },
  { key: 'rr_bearish_target_pct',       label: 'Bearish target %',       type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.01, max: 2.0, step: 0.01, unit: '%',
    hint: 'Profit target as a fraction of entry for bearish trades. ↑ Higher → demands bigger downside moves · ↓ Lower → takes smaller drops. Default: 8%' },
  { key: 'rr_bullish_invalidation_pct', label: 'Bullish stop %',         type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.005, max: 1.0, step: 0.005, unit: '%',
    hint: 'Stop-loss distance for bullish trades. ↑ Higher → wider stop (more room, worse R/R) · ↓ Lower → tighter stop (better R/R but more stop-outs). Default: 3%' },
  { key: 'rr_bearish_invalidation_pct', label: 'Bearish stop %',         type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.005, max: 1.0, step: 0.005, unit: '%',
    hint: 'Stop-loss distance for bearish trades. ↑ Higher → wider stop · ↓ Lower → tighter stop. Default: 3%' },
];

const SUBGROUP_DESCRIPTIONS: Record<string, string> = {
  'Score Weights': 'Proportional contribution of each signal family to the composite stock score (weights sum to 100). Rebalance to emphasise what matters most for your approach.',
  'Trend': 'Measures whether the stock is in a sustained trend. Three algorithms: Additive (price position + slope + ADX combined), Crossover (MA cross signal), Relative Strength (return vs. benchmark index).',
  'Pullback': 'Checks that the stock has pulled back from its recent swing high in a healthy way — momentum cooling off without breaking the trend structure.',
  'Trigger': 'Short-term momentum signals confirming that buying pressure is returning now, not just that the stock trended up in the past.',
  'Event': 'Filters out stocks approaching scheduled catalysts (earnings, FOMC, dividends) that could cause unpredictable gap risk during your hold.',
  'Volatility': 'Checks implied volatility conditions. High IV rank means options premiums are expensive and large moves are already priced in.',
  'Confidence': 'A mini backtest gate — runs a quick simulation over recent history and rejects setups where the signal would have failed too often.',
  'Contract': 'Filters which options contracts are surfaced per qualifying stock, by liquidity, moneyness, and time to expiry.',
  'Regime Gate': "Sector vs. benchmark headwind thresholds. When a stock's sector is lagging the benchmark by more than these percentages, the candidate is cautioned or rejected regardless of its score.",
  'Fundamentals Bearish': 'Applied only when Direction = Bearish. Protects against shorting companies with strong balance sheets — high fundamental health scores are a caution or reject signal for short trades.',
  'Entry Quality': 'Options fill-quality filters applied at contract selection. Controls minimum premium, maximum spread, and expected slippage.',
  'Reward/Risk': 'Target and invalidation (stop) distances used to compute R/R ratios. These drive the reward_risk scorer and position card stop/target prices.',
};

const SECTION_DESCRIPTIONS: Record<string, string> = {
  'stocks': 'Stock-level scoring and filtering. Each stock is evaluated against five signal families and eliminated if its composite score falls below the threshold.',
  'options': 'Options contract filtering. Applied after a stock qualifies — determines which expiries and strikes are shown for that stock.',
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
        <div className={formStyles.paramLabelCell}>
          <Text size={12} tone="dim">{def.label}</Text>
        </div>
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
        <div className={formStyles.paramLabelCell} title={def.hint}>
          <Text size={12} tone="dim">{def.label}</Text>
        </div>
        <div className={formStyles.paramsValue}>
          <Data size={11}>{isNa ? 'N/A' : formatDefault(defaultVal)}</Data>
          {!isNa && def.unit && <Text size={11} tone="dim">{def.unit}</Text>}
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
        <div className={formStyles.paramLabelCell} title={def.hint}>
          <Text size={12} tone="dim">{def.label}</Text>
        </div>
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
        <div className={formStyles.paramLabelCell}>
          <Text size={12} tone="dim">{def.label}</Text>
        </div>
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
        <div className={formStyles.paramLabelCell} title={def.hint}>
          <Text size={12}>{def.label}</Text>
        </div>
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
        <div className={formStyles.paramLabelCell} title={def.hint}>
          <Text size={12}>{def.label}</Text>
        </div>
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
      <div className={formStyles.paramLabelCell} title={def.hint}>
        <Text size={12}>{def.label}</Text>
      </div>
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
          onBlur={() => {
            const current = useScanStore.getState().scanOverrides[def.key];
            if (typeof current !== 'number') return;
            let clamped = current;
            if (def.min !== undefined) clamped = Math.max(clamped, def.min);
            if (def.max !== undefined) clamped = Math.min(clamped, def.max);
            if (clamped !== current) {
              useScanStore.getState().setScanOverrides({ ...useScanStore.getState().scanOverrides, [def.key]: clamped });
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
  description,
  paramHints,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  overrideCount: number;
  description?: string;
  paramHints?: Array<{ label: string; hint?: string }>;
  children: React.ReactNode;
}) {
  const hasPanel = !!(description || paramHints?.some((p) => p.hint));
  return (
    <div className={formStyles.subGroup}>
      <button type="button" className={formStyles.subGroupHeader} onClick={onToggle} aria-expanded={open}>
        <Text size={11} weight={500} tone="secondary">{label}</Text>
        {overrideCount > 0 && !open && (
          <span className={formStyles.overrideBadge}>{overrideCount} override{overrideCount !== 1 ? 's' : ''}</span>
        )}
        <span className={`${formStyles.chevron} ${open ? formStyles.chevronOpen : ''}`} style={{ marginLeft: 'auto' }} aria-hidden>▾</span>
      </button>
      {open && (
        <div className={formStyles.subGroupBody}>
          <div className={formStyles.subGroupParamCol}>
            {children}
          </div>
          {hasPanel && (
            <div className={formStyles.subGroupDescBox}>
              {description && <Text size={11} tone="dim">{description}</Text>}
              {paramHints && paramHints.some((p) => p.hint) && (
                <div className={formStyles.subGroupHintList}>
                  {paramHints.filter((p) => p.hint).map((p) => (
                    <div key={p.label} className={formStyles.subGroupHintRow}>
                      <Text size={10} weight={500} tone="secondary">{p.label}</Text>
                      <Text size={10} tone="dim">{p.hint}</Text>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Collapsible section block (STOCKS / OPTIONS) ──────────────────────────────

function SectionBlock({
  label,
  open,
  onToggle,
  overrideCount,
  description,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  overrideCount: number;
  description?: string;
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
      {open && (
        <div className={formStyles.sectionBody}>
          {description && (
            <div className={formStyles.sectionDesc}>
              <Text size={10} tone="dim">{description}</Text>
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Step3Page() {
  const context        = useScanStore((s) => s.context);
  const setContext     = useScanStore((s) => s.setContext);
  const rejectedLog    = useScanStore((s) => s.rejectedLog);
  const regime         = useScanStore((s) => s.regime);
  const scanOverrides  = useScanStore((s) => s.scanOverrides);
  const scanResult     = useScanStore((s) => s.scanResult);
  const screenerMode   = useScanStore((s) => s.screenerMode);
  const regimeDirection = useScanStore((s) => s.regimeDirection);

  const [dir,     setDir]     = useState<Direction>(() => context?.direction ?? 'Bullish');
  const [hz,      setHz]      = useState<HorizonKey>(() => context?.horizonPreset ?? 'Swing');
  const [holdMin, setHoldMin] = useState<number>(() => Math.round(context?.holdMin ?? presetByKey('Swing').holdMin));
  const [holdMax, setHoldMax] = useState<number>(() => Math.round(context?.holdMax ?? presetByKey('Swing').holdMax));
  const [isExpanded,  setIsExpanded]  = useState(false);
  const [stocksOpen,  setStocksOpen]  = useState(true);
  const [optionsOpen, setOptionsOpen] = useState(true);
  const [subGroupOpen, setSubGroupOpen] = useState<Record<string, boolean>>({
    'Score Weights': true, Trend: true, Pullback: true, Trigger: true, Event: true, Volatility: true, Contract: true,
  });

  // If this page mounts before useScanStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializers above capture the hardcoded fallback defaults instead of the
  // persisted context. Sync local state once hydration actually finishes, so
  // the first click on this page doesn't write those fallback defaults back
  // into the store and silently overwrite a saved horizon/hold-days.
  useEffect(() => {
    const syncFromHydratedContext = () => {
      const c = useScanStore.getState().context;
      if (!c) return;
      setDir(c.direction ?? 'Bullish');
      setHz(c.horizonPreset ?? 'Swing');
      setHoldMin(Math.round(c.holdMin ?? presetByKey('Swing').holdMin));
      setHoldMax(Math.round(c.holdMax ?? presetByKey('Swing').holdMax));
    };
    // Covers the common case: hydration already finished before this effect
    // runs (e.g. navigating from Step 2, rather than a fresh Step-3 landing).
    if (useScanStore.persist.hasHydrated()) syncFromHydratedContext();
    // Covers the race: hydration finishes after this component has already
    // mounted with fallback-default local state.
    const unsub = useScanStore.persist.onFinishHydration(syncFromHydratedContext);
    return unsub;
  }, []);

  // Keep local dir/hz/holdMin/holdMax mirrored to context after every change,
  // not just at hydration — e.g. a Search Profile applied from the sibling
  // SearchProfileBar updates context directly on an already-mounted page, and
  // without this, the Directional-bias/Horizon buttons would keep showing
  // stale values until the user clicked one (silently re-overwriting the
  // just-applied profile). Safe to run unconditionally: when the change
  // originated from this page's own handlers (handleDirChange/handleHzChange/
  // handleMinChange/handleMaxChange), context already matches local state, so
  // this is a no-op re-affirmation.
  useEffect(() => {
    if (!context) return;
    setDir(context.direction ?? 'Bullish');
    setHz(context.horizonPreset ?? 'Swing');
    setHoldMin(Math.round(context.holdMin ?? presetByKey('Swing').holdMin));
    setHoldMax(Math.round(context.holdMax ?? presetByKey('Swing').holdMax));
  }, [context]);

  const descriptorRef = useRef<RegimeDescriptor>('Choppy');

  useEffect(() => {
    api.getRegime().then((r) => {
      useScanStore.getState().setRegime(r.overall);
      descriptorRef.current = descriptorFromState(r.omm?.state ?? '');
      const dir = useScanStore.getState().context?.direction ?? 'Bullish';
      useScanStore.getState().setCombinedRegime(alignmentVerdict(dir, descriptorRef.current));
    }).catch(() => {});
  }, []);

  const toggleSubGroup = useCallback((name: string) => {
    setSubGroupOpen((prev) => ({ ...prev, [name]: !(prev[name] ?? true) }));
  }, []);

  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    // Equivalent to the old ternary for every newHz value: resolveParamsHorizon
    // resolves Custom dynamically and passes every other key through unchanged.
    const scoringHz = presetByKey(resolveParamsHorizon(newHz, newMax)).scoringHorizon;
    setContext({
      universe:      context?.universe ?? 'SP500',
      direction:     newDir,
      horizon:       horizonDisplayString(scoringHz, newMin, newMax),
      horizonPreset: newHz,
      holdMin:       newMin,
      holdMax:       newMax,
    });
  }

  const handleDirChange = (d: Direction) => {
    setDir(d);
    useScanStore.getState().setCombinedRegime(alignmentVerdict(d, descriptorRef.current));
    syncToStore(d, hz, holdMin, holdMax);
  };
  const handleHzChange = (h: HorizonKey) => {
    const p = presetByKey(h);
    const nextMin = h === 'Custom' ? holdMin : p.holdMin;
    const nextMax = h === 'Custom' ? holdMax : p.holdMax;
    setHz(h);
    setHoldMin(nextMin);
    setHoldMax(nextMax);
    syncToStore(dir, h, nextMin, nextMax);
    // Same resolution as `defaults` above — both call sites now share one
    // implementation, so they cannot drift apart from each other again.
    const hd = PARAM_DEFAULTS_PER_HORIZON[resolveParamsHorizon(h, nextMax)];
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
    // Whole days only — the backend's hold_min_days/hold_max_days are strict
    // ints (Pydantic/FastAPI Query), and a free-typed decimal like "3.5" would
    // otherwise reach postScan/getContracts and 422.
    const clamped = Math.min(Math.round(v), holdMax);
    setHoldMin(clamped);
    syncToStore(dir, hz, clamped, holdMax);
  };
  const handleMaxChange = (v: number) => {
    const clamped = Math.max(holdMin, Math.round(v));
    setHoldMax(clamped);
    syncToStore(dir, hz, holdMin, clamped);
  };

  const custom = hz === 'Custom';
  const defaults = PARAM_DEFAULTS_PER_HORIZON[resolveParamsHorizon(hz, holdMax)];
  const [previewMinDte, previewMaxDte] = previewDteWindow(holdMin, holdMax);
  const displayDefaults: ParamDefaults = { ...defaults, min_dte: previewMinDte, max_dte: previewMaxDte };

  const totalPassed   = scanResult?.candidates?.length ?? 0;
  const totalRejected = rejectedLog.length;
  const totalScanned  = totalPassed + totalRejected;

  const enforcedDte = scanResult?.dte_window;   // set by the backend on every scan

  // Equivalent to the old ternary for every hz value — consolidated onto the
  // same helper `defaults` above uses, closing this independent copy of the
  // decision instead of leaving it to drift on its own.
  const weightsKey: ScoringHorizon = presetByKey(resolveParamsHorizon(hz, holdMax)).scoringHorizon;

  const stocksDefs  = PARAM_DEFS.filter((d) => d.section === 'stocks' || d.section === 'all');
  const optionsDefs = PARAM_DEFS.filter((d) => d.section === 'options' || d.section === 'all');
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

      <SearchProfileBar />

      {regimeDirection === 'BULL' && dir === 'Bearish' && (
        <div className={formStyles.mismatchWarn} role="status">
          <Text size={12} tone="caution">
            The macro regime currently favours Bullish trades — your Bearish direction runs against the tide.
          </Text>
        </div>
      )}
      {regimeDirection === 'BEAR' && dir === 'Bullish' && (
        <div className={formStyles.mismatchWarn} role="status">
          <Text size={12} tone="caution">
            The macro regime currently favours Bearish trades — your Bullish direction runs against the tide.
          </Text>
        </div>
      )}

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
          <Text size={12} tone={custom ? 'secondary' : 'dim'}>Holding period (days)</Text>
          <div className={formStyles.customInputs}>
            <input
              type="number"
              className={formStyles.numInput}
              value={holdMin}
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
              value={holdMax}
              min={0}
              max={365}
              disabled={!custom}
              onChange={(e) => handleMaxChange(Number(e.target.value))}
              aria-label="Maximum days"
            />
          </div>
          <Text size={11} tone="dim">
            Contracts will expire in {previewMinDte}–{previewMaxDte} days (hold × 2).
          </Text>
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
              description={SECTION_DESCRIPTIONS['stocks']}
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
                    description={SUBGROUP_DESCRIPTIONS[sg]}
                    paramHints={visibleDefs.filter((d) => !d.redundant && !d.deprecated).map((d) => ({ label: d.label, hint: d.hint }))}
                  >
                    {visibleDefs.map((def) => (
                      <ParamRow
                        key={def.key}
                        def={def}
                        defaultVal={displayDefaults[def.key] ?? null}
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
              description={SECTION_DESCRIPTIONS['options']}
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
                    description={SUBGROUP_DESCRIPTIONS[sg]}
                    paramHints={sgDefs.filter((d) => !d.redundant && !d.deprecated).map((d) => ({ label: d.label, hint: d.hint }))}
                  >
                    {sgDefs.map((def) => (
                      <ParamRow
                        key={def.key}
                        def={def}
                        defaultVal={displayDefaults[def.key] ?? null}
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

      {screenerMode !== 'stocks' && (
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
                  <Text size={11} tone="secondary">
                    {enforcedDte ? `${enforcedDte.min_dte}–${enforcedDte.max_dte}d` : '—'}
                  </Text>
                </span>
              </>
            )}
            {totalScanned === 0 && rejectedLog.length > 0 && (
              <span className={formStyles.badge}>{rejectedLog.length}</span>
            )}
          </div>
        </div>
          {scanResult?.pipeline && (
            <ScanFunnel mode="options" pipeline={scanResult.pipeline} />
          )}
          <ScanLogSection entries={rejectedLog} horizonKey={weightsKey} />
      </div>
      )}

      <RunScanButton />
    </div>
  );
}
