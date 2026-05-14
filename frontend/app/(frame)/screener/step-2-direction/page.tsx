'use client';

/*
 * Screener Step 2 — Direction + Horizon. Phase 5 / Round 1.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 * Round 4: collapsible Execution Parameters panel with per-horizon overrides.
 */

import { useEffect, useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import type { Direction } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { RunScanButton } from '@/components/organisms/RunScanButton';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

const DIRECTIONS: Direction[] = ['Bullish', 'Bearish'];

type HorizonKey = 'Intraday' | 'Swing' | 'Position' | 'Custom';

const HORIZON_PRESETS: { key: HorizonKey; label: string; hint: string }[] = [
  { key: 'Intraday', label: 'Intraday', hint: '0–2 days' },
  { key: 'Swing',    label: 'Swing',    hint: '5–15 days' },
  { key: 'Position', label: 'Position', hint: '15–45 days' },
  { key: 'Custom',   label: 'Custom',   hint: 'Set range' },
];

interface ParamDef {
  key: string;
  label: string;
  type: 'number' | 'boolean';
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}

const PARAM_DEFS: ParamDef[] = [
  { key: 'iv_rank_pass_max',        label: 'IV Rank pass threshold', type: 'number',  min: 0,   max: 100,  step: 1   },
  { key: 'rsi_floor',               label: 'RSI floor',              type: 'number',  min: 0,   max: 100,  step: 1   },
  { key: 'macd_fast',               label: 'MACD fast',              type: 'number',  min: 2,   max: 50,   step: 1   },
  { key: 'macd_slow',               label: 'MACD slow',              type: 'number',  min: 2,   max: 100,  step: 1   },
  { key: 'macd_signal',             label: 'MACD signal',            type: 'number',  min: 2,   max: 50,   step: 1   },
  { key: 'ema_required',            label: 'EMA condition active',   type: 'boolean'                                   },
  { key: 'max_delta',               label: 'Max delta',              type: 'number',  min: 0,   max: 1,    step: 0.01 },
  { key: 'atr_caution_max',         label: 'ATR caution max',        type: 'number',  min: 0,   max: 10,   step: 0.1  },
  { key: 'swing_high_lookback_bars',label: 'Swing high lookback',    type: 'number',  min: 2,   max: 200,  step: 1   },
  { key: 'max_bid_ask_spread_pct',  label: 'Bid-ask spread ceiling', type: 'number',  min: 0,   max: 1,    step: 0.01 },
  { key: 'event_reject_days',       label: 'Event reject days',      type: 'number',  min: 0,   max: 90,   step: 1   },
  { key: 'event_caution_days',      label: 'Event caution days',     type: 'number',  min: 0,   max: 120,  step: 1   },
];

type ParamDefaults = Record<string, number | boolean | null>;

const PARAM_DEFAULTS_PER_HORIZON: Record<HorizonKey, ParamDefaults> = {
  Intraday: { iv_rank_pass_max: null, rsi_floor: 44, macd_fast: 5, macd_slow: 13, macd_signal: 3, ema_required: false, max_delta: 0.85, atr_caution_max: 2.5, swing_high_lookback_bars: 20, max_bid_ask_spread_pct: 0.20, event_reject_days: 1, event_caution_days: 3 },
  Swing:    { iv_rank_pass_max: 34,  rsi_floor: 44, macd_fast: 8, macd_slow: 21, macd_signal: 5, ema_required: true,  max_delta: 0.85, atr_caution_max: 2.5, swing_high_lookback_bars: 40, max_bid_ask_spread_pct: 0.20, event_reject_days: 7, event_caution_days: 21 },
  Position: { iv_rank_pass_max: 44,  rsi_floor: 48, macd_fast: 12, macd_slow: 26, macd_signal: 9, ema_required: true,  max_delta: 0.85, atr_caution_max: 2.5, swing_high_lookback_bars: 15, max_bid_ask_spread_pct: 0.20, event_reject_days: 30, event_caution_days: 60 },
  Custom:   { iv_rank_pass_max: 34,  rsi_floor: 44, macd_fast: 8, macd_slow: 21, macd_signal: 5, ema_required: true,  max_delta: 0.85, atr_caution_max: 2.5, swing_high_lookback_bars: 40, max_bid_ask_spread_pct: 0.20, event_reject_days: 7, event_caution_days: 21 },
};

function formatDefault(def: number | boolean | null): string {
  if (def === null) return 'N/A (not scored for Intraday)';
  if (typeof def === 'boolean') return def ? 'On' : 'Off';
  return String(def);
}

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

function inferStage(reason: string): 'stock' | 'contract' | 'filter' {
  if (reason.includes('contract') || reason.includes('delta') || reason.includes('DTE') || reason.includes('spread')) return 'contract';
  if (reason.includes('price') || reason.includes('cap')) return 'filter';
  return 'stock';
}

function dteRecommendation(horizon: string | undefined): string {
  if (!horizon) return '';
  if (horizon.startsWith('Intraday')) return 'For Intraday 0–2d: target DTE 7–14d';
  if (horizon.startsWith('Swing'))    return 'For Swing 5–15d: target DTE 21–45d (2–3× hold period to reduce theta drag)';
  if (horizon.startsWith('Position')) return 'For Position 15–45d: target DTE 45–90d';
  const m = horizon.match(/(\d+)–(\d+)/);
  if (m) {
    const max = Number(m[2]);
    return `For this horizon: target DTE ${max * 2}–${max * 3}d`;
  }
  return '';
}

export default function Step2Page() {
  const context       = useScanStore((s) => s.context);
  const setContext    = useScanStore((s) => s.setContext);
  const rejectedLog   = useScanStore((s) => s.rejectedLog);
  const scanResult    = useScanStore((s) => s.scanResult);
  const regime        = useScanStore((s) => s.regime);
  const scanOverrides = useScanStore((s) => s.scanOverrides);

  const [dir,     setDir]     = useState<Direction>(() => context?.direction ?? 'Bullish');
  const [hz,      setHz]      = useState<HorizonKey>(() => parseHorizonKey(context?.horizon));
  const [minDays, setMinDays] = useState<number>(() => parseCustomDays(context?.horizon)[0]);
  const [maxDays, setMaxDays] = useState<number>(() => parseCustomDays(context?.horizon)[1]);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    api.getRegime().then((r) => {
      useScanStore.getState().setRegime(r.overall);
    }).catch(() => {});
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
    useScanStore.getState().setScanOverrides({});
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

  const byReason = rejectedLog.reduce<Record<string, number>>((acc, e) => {
    acc[e.reason] = (acc[e.reason] ?? 0) + 1;
    return acc;
  }, {});

  const stageCounts = rejectedLog.reduce<{ stock: number; contract: number; filter: number }>(
    (acc, e) => {
      const stage = inferStage(e.reason);
      acc[stage]++;
      return acc;
    },
    { stock: 0, contract: 0, filter: 0 },
  );

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 2 OF 7</Text>
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

      <div className={formStyles.paramsPanel}>
        <button
          type="button"
          className={formStyles.paramsHeader}
          onClick={() => setIsExpanded((v) => !v)}
          aria-expanded={isExpanded}
        >
          <Text size={12} weight={500}>Execution Parameters</Text>
          <span className={formStyles.paramsChevron} aria-hidden>
            {isExpanded ? '\u25BE Collapse' : '\u25B8 Expand'}
          </span>
        </button>

        {isExpanded && (
          <div className={formStyles.paramsBody}>
            {PARAM_DEFS.map((def) => {
              const defaults = PARAM_DEFAULTS_PER_HORIZON[hz];
              const defaultVal = defaults[def.key];
              const isNa = defaultVal === null;
              const currentOverride = scanOverrides[def.key] as number | boolean | undefined;

              if (isNa) {
                return (
                  <div key={def.key} className={formStyles.paramsRow} data-param-key={def.key}>
                    <Text size={12} tone="dim">{def.label}</Text>
                    <div className={formStyles.paramsValue}>
                      <Data size={11} tone="dim">{formatDefault(defaultVal)}</Data>
                    </div>
                    <div className={formStyles.paramsInput}>
                      <Text size={11} tone="dim">&mdash;</Text>
                    </div>
                  </div>
                );
              }

              if (def.type === 'boolean') {
                const isOn = currentOverride !== undefined
                  ? currentOverride as boolean
                  : defaultVal as boolean;
                return (
                  <div key={def.key} className={formStyles.paramsRow} data-param-key={def.key}>
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

              const inputValue = currentOverride !== undefined
                ? String(currentOverride)
                : String(defaultVal);

              return (
                <div key={def.key} className={formStyles.paramsRow} data-param-key={def.key}>
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
            })}

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
          {scanResult !== null && rejectedLog.length > 0 && (
            <span className={formStyles.badge}>{rejectedLog.length}</span>
          )}
        </div>

        {scanResult === null && (
          <Text size={13} tone="secondary">No scan run yet.</Text>
        )}

        {scanResult !== null && rejectedLog.length === 0 && (
          <Text size={13} tone="secondary">All symbols passed all filters.</Text>
        )}

        {scanResult !== null && rejectedLog.length > 0 && (
          <>
            <div className={formStyles.logBlock}>
              <Text size={11} tone="dim" weight={500}>REJECTION BREAKDOWN</Text>
              <div className={formStyles.breakdownTable}>
                {Object.entries(byReason).map(([reason, count]) => (
                  <div key={reason} className={formStyles.breakdownRow}>
                    <Text size={12} tone="secondary">{reason}</Text>
                    <Data size={12} weight={500}>{count}</Data>
                  </div>
                ))}
              </div>
            </div>

            <div className={formStyles.logBlock}>
              <Text size={11} tone="dim" weight={500}>STAGE SUMMARY</Text>
              <div className={formStyles.summaryRow}>
                <Text size={12} tone="secondary">Stock scoring: <Data size={12} weight={500}>{stageCounts.stock}</Data> rejected</Text>
                <Text size={12} tone="secondary">Contract scoring: <Data size={12} weight={500}>{stageCounts.contract}</Data> rejected</Text>
                <Text size={12} tone="secondary">Pre-filter: <Data size={12} weight={500}>{stageCounts.filter}</Data> rejected</Text>
              </div>
            </div>

            <div className={formStyles.logBlock}>
              <Text size={11} tone="dim" weight={500}>DTE RECOMMENDATION</Text>
              <Text size={12} tone="secondary">{dteRecommendation(context?.horizon)}</Text>
            </div>
          </>
        )}
      </div>

      <RunScanButton />
    </div>
  );
}
