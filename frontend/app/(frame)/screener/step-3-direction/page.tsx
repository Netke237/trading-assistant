'use client';

/*
 * Screener Step 3 — Direction + Horizon.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 * Round 5: full 62-definition Execution Parameters panel — Stocks / Options sections,
 * per-subgroup collapse, Score Weights from Settings migrated here (some rows are
 * display-only or conditionally visible per trend method).
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import type { Direction } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { alignmentVerdict, descriptorFromState, type RegimeDescriptor } from '@/lib/regimeAlignment';
import { applyRegimeResponse, beginRegimeFetch, fetchGateRegime } from '@/lib/regimeFetchOrder';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import { SavedScanReportInspector } from '@/components/organisms/SavedScanReportInspector';
import { scanLogTotals } from './scanLogTotals';
import { SearchProfileBar } from '@/components/organisms/SearchProfileBar';
import styles from '../screener.module.css';
import formStyles from './page.module.css';
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, horizonDisplayString,
  resolveParamsHorizon, type HorizonKey,
} from '@/lib/horizonPresets';
import { PARAM_DEFAULTS_PER_HORIZON, type ParamDefaults } from '@/lib/executionParamDefaults';

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
  scale?: number;          // scale factor between stored representation and UI representation (e.g. 100 for percentage fraction)
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
  // STOCKS — Score Gate (P3a, decision Q5)
  { key: 'min_stock_score', label: 'Min stock score', type: 'number', section: 'stocks', subGroup: 'Score Gate', min: 35, max: 100, step: 1,
    hint: 'Stocks-mode scans only (the Options scan does not read it). Drops any name whose stock score is below this. At or below 35 it adds nothing: a score under 35 is already REJECT and dropped.' },
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
  // Two ceilings, because `ivRank` and `iv` are two different quantities and
  // the scorer picks between them by basis (PHASE-A-NULL-IVRANK-2026-09-06).
  // Only ONE of the two applies to any given contract, so both are exposed:
  // with the percentile knob alone, a user's ceiling was silently inert on
  // every chain where no rank source answered — which is nearly all of them.
  { key: 'iv_abs_pass_max', label: 'IV pass max (absolute)', type: 'number', section: 'options', subGroup: 'Volatility', min: 0, max: 100, step: 1, unit: '%',
    hint: 'Max ABSOLUTE implied volatility (0–100%) for a PASS. This is the one that applies on most chains — a true IV rank needs IBKR or tastytrade to answer, and otherwise the contract carries a raw IV instead. N/A on Intraday. ↑ Higher → elevated-IV contracts still qualify (more) · ↓ Lower → only calm-IV contracts pass (fewer).' },
  { key: 'iv_rank_pass_max', label: 'IV rank pass max (percentile)', type: 'number', section: 'options', subGroup: 'Volatility', min: 0, max: 100, step: 1,
    hint: 'Max IV RANK — where today\u2019s IV sits in the name\u2019s own 52-week range (0–100) — for a PASS. Applies ONLY when IBKR or tastytrade supplied a real rank; otherwise the absolute ceiling above is what judges the contract. N/A on Intraday. ↑ Higher → elevated-IV stocks still qualify (more) · ↓ Lower → only calm-IV stocks pass (fewer).' },
  { key: 'iv_rank_lookback', label: 'IV rank lookback', type: 'display', section: 'stocks', subGroup: 'Volatility',
    hint: 'Lookback window used to normalise current IV into a percentile rank (display only).' },
  { key: 'hv_lookback',      label: 'HV period',        type: 'display', section: 'stocks', subGroup: 'Volatility',
    hint: 'Days used to calculate historical (realised) volatility (display only).' },
  // STOCKS — Confidence (signal backtest gate)
  { key: 'confidence_caution_below', label: 'Confidence caution below', type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%',
    hint: 'Signal backtest win rate below this % triggers CAUTION. ↑ Higher → broader caution zone · ↓ Lower → narrower caution zone' },
  { key: 'confidence_reject_below',  label: 'Confidence reject below',  type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0,   max: 100, step: 1,   unit: '%',
    hint: 'Signal backtest win rate below this % triggers REJECT. ↑ Higher → stricter gate, better-tested results (fewer) · ↓ Lower → looser gate (more)' },
  { key: 'confidence_atr_mult_target', label: 'Confidence ATR target', type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0.5, max: 5, step: 0.1,
    hint: 'Win barrier for the mini backtest = this × ATR, for the active horizon. Overrides the Settings default for this scan only. ↑ Higher → demands a bigger winner (stricter, fewer)' },
  { key: 'confidence_atr_mult_stop',   label: 'Confidence ATR stop',   type: 'number', section: 'stocks', subGroup: 'Confidence', min: 0.5, max: 5, step: 0.1,
    hint: 'Loss barrier for the mini backtest = this × ATR, for the active horizon. Overrides the Settings default for this scan only. A lone target or stop override (without the other) is ignored.' },
  // OPTIONS — Contract
  { key: 'max_delta',              label: 'Max delta',              type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Highest delta (0–1) allowed — controls how far in-the-money contracts can be. ↑ Higher → near-the-money contracts allowed (more) · ↓ Lower → OTM-only (fewer)' },
  { key: 'max_bid_ask_spread_pct', label: 'Bid-ask spread ceiling', type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Max spread as a fraction of mid price. ↑ Higher → illiquid contracts included (more, but costly) · ↓ Lower → tight spread required (fewer, cheaper to trade)' },
  { key: 'min_volume',             label: 'Min option volume (0 = off)', type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10,
    hint: 'Optional hard floor on contracts traded, off (0) by default because volume is scored softly under Preferred Liquidity below. The figure is session-to-date volume, so with a floor set, results change with the time of day. ↑ Higher → better liquidity required (fewer) · ↓ Lower → thin markets allowed (more). Hard floor only: a thinner contract still misses Preferred min volume / open interest below, and can still be rejected for a contract score below the caution band or for too many soft misses (the two Preferred liquidity floors together count as at most one), so lower those too.' },
  { key: 'min_open_interest',      label: 'Min open interest',      type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 10000, step: 10,
    hint: 'Minimum outstanding contracts. ↑ Higher → requires an established market (fewer) · ↓ Lower → new or low-traffic strikes included (more). Hard floor only: a thinner contract still misses Preferred min volume / open interest below, and can still be rejected for a contract score below the caution band or for too many soft misses (the two Preferred liquidity floors together count as at most one), so lower those too.' },
  { key: 'min_delta',              label: 'Min delta (far OTM)',    type: 'number', section: 'options', subGroup: 'Contract', min: 0, max: 1,     step: 0.01,
    hint: 'Rejects contracts too far out of the money. ↑ Higher → keeps contracts closer to the money · ↓ Lower → very cheap deep-OTM contracts included' },
  { key: 'min_dte', label: 'Min DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  { key: 'max_dte', label: 'Max DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  // OPTIONS — Preferred Liquidity. SOFT-RANK counterparts of the three
  // Contract fields above (max_bid_ask_spread_pct / min_volume /
  // min_open_interest): those REJECT a contract outright; these three only
  // dock its score, but three or more soft misses on ANY axis reject it too,
  // via the fixed max_soft_fail_count. Volume and open interest together count
  // as at most one soft miss (the single thin_liquidity flag); the spread is
  // its own; delta/DTE/IV add the rest. A
  // contract that only clears the hard Contract floor above but stays under
  // these can still be rejected on liquidity/spread grounds it looks like it
  // passed — move both together for a change to actually admit or exclude
  // more contracts, not just relabel the ones that already would have.
  { key: 'preferred_volume_min', label: 'Preferred min volume', type: 'number', section: 'options', subGroup: 'Preferred Liquidity', min: 0, max: 10000, step: 10,
    hint: 'Daily contract volume below this docks the liquidity score and together with Preferred min open interest counts as at most one soft miss. ↑ Higher → more contracts soft-flagged (fewer survive 3 misses) · ↓ Lower → fewer soft-flagged. Default: 200. Independent of the hard "Min option volume" floor above, an optional floor (off, 0, by default) which rejects outright rather than scoring.' },
  { key: 'preferred_oi_min', label: 'Preferred min open interest', type: 'number', section: 'options', subGroup: 'Preferred Liquidity', min: 0, max: 10000, step: 10,
    hint: 'Open interest below this docks the liquidity score and together with Preferred min volume counts as at most one soft miss. ↑ Higher → more contracts soft-flagged · ↓ Lower → fewer soft-flagged. Default: 1000. Independent of the hard "Min open interest" floor above.' },
  { key: 'preferred_spread_pct_max', label: 'Preferred spread ceiling', type: 'number', section: 'options', subGroup: 'Preferred Liquidity', min: 0, max: 1, step: 0.01,
    hint: 'Spread (as a fraction of mid) above this docks the spread score and counts as one soft miss. ↑ Higher → wider spreads tolerated before scoring/rejecting on this axis · ↓ Lower → stricter. Default: 0.08. Independent of the hard "Bid-ask spread ceiling" above, which is far looser (0.20) by default — this preferred ceiling is usually the tighter, binding constraint in practice.' },
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
  { key: 'rr_target_r_multiple', label: 'Target (R-multiple)', type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.5, max: 10, step: 0.25, unit: 'R',
    hint: 'First target distance in multiples of the stock-stop distance, with nearby structure preferred. Default: 2R' },
  { key: 'rr_bullish_invalidation_pct', label: 'Bullish stop %',         type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.5, max: 100, step: 0.5, unit: '%', scale: 100,
    hint: 'Stop-loss distance for bullish trades. ↑ Higher → wider stop (more room, worse R/R) · ↓ Lower → tighter stop (better R/R but more stop-outs). Default: 3%' },
  { key: 'rr_bearish_invalidation_pct', label: 'Bearish stop %',         type: 'number', section: 'all', subGroup: 'Reward/Risk', min: 0.5, max: 100, step: 0.5, unit: '%', scale: 100,
    hint: 'Stop-loss distance for bearish trades. ↑ Higher → wider stop · ↓ Lower → tighter stop. Default: 3%' },
];

const SUBGROUP_DESCRIPTIONS: Record<string, string> = {
  'Score Gate': 'A minimum composite stock score for Stocks-mode scans. Names below it are dropped and counted in the funnel\'s Score gate stage. The default (35) is the REJECT line the scan already applies, so it changes nothing until raised.',
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

function formatDefault(val: number | boolean | string | null, def?: ParamDef): string {
  if (val === null) return 'N/A';
  if (typeof val === 'boolean') return val ? 'On' : 'Off';
  if (typeof val === 'string') return val;
  if (typeof val === 'number') {
    const scaled = def?.scale ? val * def.scale : val;
    return String(Number(scaled.toFixed(4)));
  }
  return String(val);
}

function countActiveOverrides(defs: ParamDef[], overrides: Record<string, number | boolean | string>, defaults: ParamDefaults): number {
  return defs.filter((d) => {
    if (d.redundant || d.deprecated || d.type === 'display') return false;
    const ov = overrides[d.key];
    if (ov === undefined) return false;
    if (d.scale && typeof ov === 'number' && typeof defaults[d.key] === 'number') {
      return Math.abs(ov - (defaults[d.key] as number)) >= 1e-6;
    }
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
          <Data size={11} tone="dim">{formatDefault(defaultVal, def)}</Data>
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
          <Data size={11}>{isNa ? 'N/A' : formatDefault(defaultVal, def)}</Data>
          {!isNa && def.unit && <Text size={11} tone="dim">{def.unit}</Text>}
        </div>
        <div className={formStyles.paramsInput}>
          <Text size={11} tone="dim">display only</Text>
        </div>
      </div>
    );
  }

  // N/A rows (Intraday iv_abs_pass_max / iv_rank_pass_max)
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
          <Data size={11} tone="dim">{formatDefault(defaultVal, def)}</Data>
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
          <Data size={11} tone="dim">{formatDefault(defaultVal, def)}</Data>
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
  const formatNumberValue = (val: number | undefined): string => {
    if (val === undefined) return '';
    const scaled = def.scale ? val * def.scale : val;
    return String(Number(scaled.toFixed(4)));
  };

  const inputValue = currentOverride !== undefined
    ? (typeof currentOverride === 'number' ? formatNumberValue(currentOverride) : String(currentOverride))
    : (typeof defaultVal === 'number' ? formatNumberValue(defaultVal) : String(defaultVal));

  return (
    <div className={formStyles.paramsRow} data-param-key={def.key}>
      <div className={formStyles.paramLabelCell} title={def.hint}>
        <Text size={12}>{def.label}</Text>
      </div>
      <div className={formStyles.paramsValue}>
        <Data size={11} tone="dim">{formatDefault(defaultVal, def)}</Data>
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
            if (raw === '') {
              const next = { ...scanOverrides };
              delete next[def.key];
              useScanStore.getState().setScanOverrides(next);
            } else {
              const num = Number(raw);
              if (!Number.isNaN(num)) {
                if (def.scale) {
                  const storedVal = Number((num / def.scale).toFixed(6));
                  const isDefault = typeof defaultVal === 'number' && Math.abs(storedVal - defaultVal) < 1e-6;
                  if (isDefault) {
                    const next = { ...scanOverrides };
                    delete next[def.key];
                    useScanStore.getState().setScanOverrides(next);
                  } else {
                    useScanStore.getState().setScanOverrides({ ...scanOverrides, [def.key]: storedVal });
                  }
                } else {
                  if (raw === String(defaultVal)) {
                    const next = { ...scanOverrides };
                    delete next[def.key];
                    useScanStore.getState().setScanOverrides(next);
                  } else {
                    useScanStore.getState().setScanOverrides({ ...scanOverrides, [def.key]: num });
                  }
                }
              }
            }
          }}
          onBlur={() => {
            const current = useScanStore.getState().scanOverrides[def.key];
            if (typeof current !== 'number') return;
            if (def.scale) {
              const minStored = def.min !== undefined ? def.min / def.scale : undefined;
              const maxStored = def.max !== undefined ? def.max / def.scale : undefined;
              let clamped = current;
              if (minStored !== undefined) clamped = Math.max(clamped, minStored);
              if (maxStored !== undefined) clamped = Math.min(clamped, maxStored);
              clamped = Number(clamped.toFixed(6));
              if (clamped !== current) {
                const isDefault = typeof defaultVal === 'number' && Math.abs(clamped - defaultVal) < 1e-6;
                const next = { ...useScanStore.getState().scanOverrides };
                if (isDefault) {
                  delete next[def.key];
                } else {
                  next[def.key] = clamped;
                }
                useScanStore.getState().setScanOverrides(next);
              }
            } else {
              let clamped = current;
              if (def.min !== undefined) clamped = Math.max(clamped, def.min);
              if (def.max !== undefined) clamped = Math.min(clamped, def.max);
              if (clamped !== current) {
                useScanStore.getState().setScanOverrides({ ...useScanStore.getState().scanOverrides, [def.key]: clamped });
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
  const liveRejectedLog = useScanStore((s) => s.rejectedLog);
  const scanState       = useScanStore((s) => s.scanState);
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
    // The verdict follows the direction too, once the regime has answered:
    // StoreHydration can restore a scan's context (STEP3-PARAM-REACH) after
    // the fetch below resolved, and only handleDirChange recomputed it.
    if (regimeLoadedRef.current && context.direction) {
      useScanStore.getState().setCombinedRegime(alignmentVerdict(context.direction, descriptorRef.current));
    }
  }, [context]);

  const descriptorRef = useRef<RegimeDescriptor>('Choppy');
  const regimeLoadedRef = useRef(false);

  // Same request and the same ordering as Steps 1 and 2: an older answer
  // never replaces a newer one that already landed on the shared gate, and
  // this page keeps the descriptor only of a response that was applied.
  useEffect(() => {
    const ticket = beginRegimeFetch();
    fetchGateRegime().then((r) => {
      if (!applyRegimeResponse(ticket, r)) return;
      descriptorRef.current = descriptorFromState(r.omm?.state ?? '');
      regimeLoadedRef.current = true;
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
      universe:      context?.universe ?? useUniverseStore.getState().pick ?? 'SP500',
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

  // `rejectedLog` is written only by RunScanButton and is NOT persisted, while
  // the identical entries on `scanResult.rejected` ARE. After a reload the
  // first is empty and the second is not, so reading the store field alone
  // reported "Rejected 0" beside a restored scan's real "Scanned 518" — and
  // emptied the reason breakdown below. Fall back to the persisted copy.
  //
  // ONLY in a settled state. RunScanButton deliberately empties `rejectedLog`
  // when a scan STARTS and when one FAILS, without clearing `scanResult` — so
  // an ungated fallback would undo both clears and show the previous run's log
  // as though it were this one's.
  // Derived together, in one place — see scanLogTotals.ts for why.
  const { shownResult, rejectedLog, totalPassed, totalRejected, totalScanned, totalTrimmed } =
    scanLogTotals(scanState, liveRejectedLog, scanResult);

  // Gated like every other number in the log header: a scan in flight or
  // failed shows no DTE rather than the previous run's.
  const enforcedDte = shownResult?.dte_window;

  const stocksDefs  = PARAM_DEFS.filter((d) => d.section === 'stocks' || d.section === 'all');
  const optionsDefs = PARAM_DEFS.filter((d) => d.section === 'options' || d.section === 'all');
  const stockSubGroups  = [...new Set(stocksDefs.map((d) => d.subGroup))];
  const optionSubGroups = [...new Set(optionsDefs.map((d) => d.subGroup))];

  const legacyTargetPctDropped = useSearchProfilesStore((s) => s.legacyTargetPctDropped);
  const dismissLegacyTargetPctNotice = useSearchProfilesStore((s) => s.dismissLegacyTargetPctNotice);
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
            {legacyTargetPctDropped && <div role="status">
              <Text size={12} tone="caution">Saved target percentages were removed. Reward/Risk now uses Target (R-multiple); review your saved profiles.</Text>
              <button type="button" onClick={dismissLegacyTargetPctNotice}>Dismiss</button>
            </div>}

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

      {(
        <div className={formStyles.logSection}>
          <div className={formStyles.logHeader}>
            <Text size={11} tone="dim" weight={500}>SCAN LOG · CURRENT TABLE COUNTS</Text>
            <div className={formStyles.logStats}>
              {screenerMode === 'options' && totalScanned > 0 && (
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
                  {totalTrimmed > 0 && (
                    <span className={formStyles.logStat}>
                      <Text size={11} tone="caution">Over cap</Text>
                      <span className={formStyles.badge}>{totalTrimmed}</span>
                    </span>
                  )}
                  <span className={formStyles.logStat}>
                    <Text size={11} tone="dim">DTE</Text>
                    <Text size={11} tone="secondary">
                      {enforcedDte ? `${enforcedDte.min_dte}–${enforcedDte.max_dte}d` : '—'}
                    </Text>
                  </span>
                </>
              )}
            </div>
          </div>
          <SavedScanReportInspector category={screenerMode} tableRunId={screenerMode === 'options' ? shownResult?.report_run_id : undefined} />
        </div>
      )}

      <RunScanButton />
    </div>
  );
}
