'use client';

import { useState, useEffect } from 'react';
import { Text } from '@/components/primitives';
import { api } from '@/lib/api';
import styles from './CompositeAlertDialog.module.css';

interface Props {
  symbol:    string;
  direction: string;
  onClose:   () => void;
}

type MarkovModel = 'OMM' | 'HMM_daily' | 'HMM_intraday' | 'any';

const OMM_STATES  = ['Bull', 'Bear', 'Choppy', 'any'];
const HMM_STATES  = ['Trending', 'Choppy', 'Mean-reverting', 'any'];

type Side = 'bullish' | 'bearish' | null;

// COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD (Q0 = a): structure and momentum rows
// share one list, one selection and one N-of-M count, as the backend does.
// Momentum labels follow the alert direction and must read exactly as the
// backend's chart_alerts._momentum_label (the alert checklist names the row).
const RSI_LEVEL = 60;
const SESSION_NOTE = 'Intraday alerts read regular-session (09:30-16:00 ET) candles only.';
const CONFIRMATION_OPTIONS: {
  type: 'structure' | 'momentum';
  signal_kind: string;
  label: (side: Side) => string;
  tip?: string;
}[] = [
  { type: 'structure', signal_kind: 'BOS',            label: () => 'Break of Structure' },
  { type: 'structure', signal_kind: 'CHoCH',          label: () => 'Change of Character' },
  { type: 'structure', signal_kind: 'FVG',            label: () => 'Fair Value Gap' },
  { type: 'structure', signal_kind: 'OrderBlock',     label: () => 'Order Block' },
  { type: 'structure', signal_kind: 'RSIDivergence',  label: () => 'RSI Divergence' },
  { type: 'structure', signal_kind: 'MACDDivergence', label: () => 'MACD Divergence' },
  {
    type: 'momentum', signal_kind: 'rsi_cross',
    label: (side) => side === 'bullish' ? `RSI crosses up through ${RSI_LEVEL}`
      : side === 'bearish' ? `RSI crosses down through ${100 - RSI_LEVEL}`
      : `RSI crosses up through ${RSI_LEVEL} or down through ${100 - RSI_LEVEL}`,
    tip: 'RSI(14) crosses the level on the last closed candle of the alert\'s interval '
      + '(it was on the other side on the candle before). Needs 201 candles of history. '
      + SESSION_NOTE,
  },
  {
    type: 'momentum', signal_kind: 'macd_cross',
    label: (side) => `MACD crosses ${side === 'bullish' ? 'above' : side === 'bearish' ? 'below' : 'above or below'} its signal line`,
    tip: 'MACD(12, 26, 9) line crosses its signal line on the last closed candle of the '
      + 'alert\'s interval. Needs 201 candles of history. ' + SESSION_NOTE,
  },
  {
    type: 'momentum', signal_kind: 'volume_spike',
    label: (side) => `Volume spike (at least 2x usual, ${side === 'bullish' ? 'up candle' : side === 'bearish' ? 'down candle' : 'any candle colour'})`,
    tip: 'Volume of the last closed candle is at least 2x usual. Daily/weekly: the mean of the '
      + '20 candles before it. Intraday: the mean of the same time of day over the previous 10 '
      + 'sessions (at least 5 needed, so 1min charts without a Tradier token rarely have enough). '
      + 'Early-close days are not recognised. ' + SESSION_NOTE,
  },
];

const MR_STRATEGY_OPTIONS = [
  { key: 'mean_reversion_rsi',  label: 'Mean Reversion RSI',  note: 'RSI extremes + trend filter (daily)' },
  { key: 'mean_reversion_bb',   label: 'Mean Reversion BB',   note: 'Bollinger Band touch + close back inside (daily)' },
  { key: 'mean_reversion_vwap', label: 'Mean Reversion VWAP', note: 'VWAP deviation snap-back (intraday 15m)' },
];

export function CompositeAlertDialog({ symbol, direction, onClose }: Props) {
  const [model, setModel]                   = useState<MarkovModel>('OMM');
  const [toState, setToState]               = useState<string>('Bull');
  const [convictionMin, setConvictionMin]   = useState(60);
  const [pStayMin, setPStayMin]             = useState(0.7);
  const [minConf, setMinConf]               = useState(1);
  const [selected, setSelected]             = useState<Set<number>>(new Set());
  const [mrSelected, setMrSelected]         = useState<Set<number>>(new Set());
  const [minMrConf, setMinMrConf]           = useState(1);
  const [saving, setSaving]                 = useState(false);
  const [done, setDone]                     = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [interval, setIntervalVal]          = useState('1D');
  const [sustainMinutes, setSustainMinutes] = useState(0);
  const [deliveryMode, setDeliveryMode]     = useState<'watch' | 'rule'>('watch');
  const [ruleName, setRuleName]             = useState('');

  useEffect(() => {
    api.getCompositeWatchDefaults().then((d) => {
      setConvictionMin(d.conviction_min);
      setPStayMin(d.p_stay_min);
      setMinConf(d.min_confirmations);
    }).catch(() => {});
  }, []);

  const [snapshot, setSnapshot] = useState<import('@/lib/api').SymbolRegimeSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState(false);

  useEffect(() => {
    if (model === 'any') { setSnapshot(null); return; }
    let cancelled = false;
    setSnapshotError(false);
    setSnapshot(null);
    api.getSymbolRegimeSnapshot(symbol, model, direction, interval).then((s) => {
      if (!cancelled) setSnapshot(s);
    }).catch(() => {
      if (!cancelled) setSnapshotError(true);
    });
    return () => { cancelled = true; };
  }, [symbol, model, direction, interval]);

  const stateOptions = model === 'OMM' ? OMM_STATES : HMM_STATES;
  const side: Side = direction.toLowerCase() === 'bullish' ? 'bullish'
    : direction.toLowerCase() === 'bearish' ? 'bearish' : null;
  const requireN = Math.min(minConf, selected.size);
  // Q7: the backend ignores sustain for a trigger with a momentum confirmation
  // that is actually evaluated (has_momentum: min_confirmations > 0).
  const sustainOff = requireN > 0
    && Array.from(selected).some((i) => CONFIRMATION_OPTIONS[i]!.type === 'momentum');

  const toggleConfirm = (i: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) {
        next.delete(i);
        setMinConf((m) => Math.min(m, next.size || 1));
      } else {
        next.add(i);
      }
      return next;
    });
  };

  const toggleMr = (i: number) => {
    setMrSelected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) {
        next.delete(i);
        setMinMrConf((m) => Math.min(m, next.size || 1));
      } else {
        next.add(i);
      }
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const confirmations = Array.from(selected).sort((a, b) => a - b).map((i) => ({
      type: CONFIRMATION_OPTIONS[i]!.type,
      signal_kind: CONFIRMATION_OPTIONS[i]!.signal_kind,
      direction: direction === 'any' ? null : direction,
      min_confidence: 60,
    }));
    const strategyConfirmations = Array.from(mrSelected).map((i) => MR_STRATEGY_OPTIONS[i]!.key);
    const triggerDef: Record<string, unknown> = {
      primary: {
        model,
        to_state: toState === 'any' ? null : toState,
        conviction_min: convictionMin,
        p_stay_min: pStayMin,
        p_transition_min: 0.3,
      },
      confirmations,
      min_confirmations: requireN,
      strategy_confirmations: strategyConfirmations,
      min_strategy_confirmations: strategyConfirmations.length > 0 ? Math.min(minMrConf, strategyConfirmations.length) : 0,
      horizon: 'swing',
      // Backend's strategy_confirmations gate reads direction from inside
      // trigger_def (td.get("direction") or "Bullish") — without this, every
      // mean-reversion confirmation would silently evaluate as Bullish regardless
      // of the alert's real direction, for both the Watch and live Rule paths.
      direction: direction === 'any' ? null : direction,
      sustain_minutes: sustainOff ? 0 : sustainMinutes,
    };
    try {
      if (deliveryMode === 'rule') {
        const name = ruleName.trim() || `${symbol} composite`;
        await api.addCompositeAlertRule(name, symbol, interval, triggerDef);
      } else {
        await api.addCompositeWatch(symbol, triggerDef, direction, interval);
      }
      setDone(true);
      setTimeout(onClose, 1200);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal
        aria-label={`Set regime alert for ${symbol}`}
      >
        <div className={styles.header}>
          <Text size={16} weight={500}>Set Regime Alert — {symbol}</Text>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close">✕</button>
        </div>

        {done ? (
          <div className={styles.doneMsg}>
            <Text size={16} tone="pass">Alert created for {symbol}.</Text>
          </div>
        ) : (
          <>
            <div className={styles.deliveryToggle}>
              <button
                type="button"
                className={`${styles.deliveryBtn} ${deliveryMode === 'watch' ? styles.deliveryActive : ''}`}
                onClick={() => setDeliveryMode('watch')}
              >
                Watch (background)
              </button>
              <button
                type="button"
                className={`${styles.deliveryBtn} ${deliveryMode === 'rule' ? styles.deliveryActive : ''}`}
                onClick={() => setDeliveryMode('rule')}
              >
                Rule (live)
              </button>
            </div>

            {deliveryMode === 'rule' && (
              <>
                <div className={styles.row}>
                  <Text size={16} tone="secondary">Rule name</Text>
                  <input
                    className={styles.select}
                    value={ruleName}
                    onChange={(e) => setRuleName(e.target.value)}
                    placeholder={`${symbol} composite`}
                  />
                </div>
                <div className={styles.warnBox}>
                  <Text size={16} tone="caution">
                    A Rule is checked by the server on every closed candle of its interval,
                    whether or not the chart is open. A Watch is checked on its own schedule
                    (end of day, or every few hours in market hours).
                  </Text>
                </div>
              </>
            )}

            <div className={styles.row}>
              <Text size={16} tone="secondary">Model</Text>
              <select
                className={styles.select}
                value={model}
                onChange={(e) => {
                  const next = e.target.value as MarkovModel;
                  setModel(next);
                  setToState('any');
                  // A4f: the Interval select (intraday options only) is shown for
                  // HMM_intraday; set a value it offers so what it displays is what
                  // is saved. Every other model keeps today's '1D'. W2-INTERVAL: the
                  // chart's spellings, so a rule shows on (and is checked from) its tab.
                  setIntervalVal(next === 'HMM_intraday' ? '5min' : '1D');
                }}
              >
                <option value="OMM">OMM (daily)</option>
                <option value="HMM_daily">HMM (daily)</option>
                <option value="HMM_intraday">HMM (intraday)</option>
                <option value="any">Any model</option>
              </select>
            </div>

            {model === 'HMM_intraday' && (
              <div className={styles.row}>
                <Text size={16} tone="secondary">Interval</Text>
                <select className={styles.select} value={interval} onChange={(e) => setIntervalVal(e.target.value)}>
                  {['5min', '15min', '30min', '1h', '4h'].map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            )}

            <div className={styles.row}>
              <Text size={16} tone="secondary">Sustain (min)</Text>
              <input
                className={styles.numInput}
                type="number"
                min={0}
                max={1440}
                value={sustainOff ? 0 : sustainMinutes}
                disabled={sustainOff}
                onChange={(e) => setSustainMinutes(Math.max(0, Math.min(1440, Number(e.target.value))))}
                title="Optional: the composite condition must stay true for this many minutes before it fires."
              />
              {sustainOff && (
                <Text size={16} tone="dim">
                  Sustain does not apply with a momentum confirmation: a cross happens on one
                  candle, so the alert fires on the candle that meets it.
                </Text>
              )}
            </div>

            {model !== 'any' && (
              <div className={styles.row}>
                <Text size={16} tone="secondary">Target state</Text>
                <select className={styles.select} value={toState} onChange={(e) => setToState(e.target.value)}>
                  {stateOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            )}

            {model !== 'any' && (
              <div className={styles.snapshotBox}>
                {snapshot ? (
                  <Text size={16} tone="dim">
                    Currently: {snapshot.state}
                    {snapshot.conviction_pct !== undefined
                      ? ` · Conviction ${snapshot.conviction_pct}% (${snapshot.conviction_label})`
                      : ''}
                    {' '}· P(stay) {snapshot.p_stay.toFixed(2)}
                  </Text>
                ) : snapshotError ? (
                  <Text size={16} tone="dim">Live regime unavailable for {symbol}</Text>
                ) : (
                  <Text size={16} tone="dim">Loading current regime…</Text>
                )}
              </div>
            )}

            <div className={styles.row}>
              <Text size={16} tone="secondary">Conviction ≥ {convictionMin}%</Text>
              <input
                type="range" min={0} max={100} step={5}
                value={convictionMin}
                onChange={(e) => setConvictionMin(Number(e.target.value))}
                className={styles.range}
              />
            </div>

            <div className={styles.row}>
              <Text size={16} tone="secondary">P(stay) ≥ {pStayMin.toFixed(2)}</Text>
              <input
                type="range" min={0} max={1} step={0.05}
                value={pStayMin}
                onChange={(e) => setPStayMin(Number(e.target.value))}
                className={styles.range}
              />
            </div>

            <div className={styles.section}>
              {(['structure', 'momentum'] as const).map((group) => (
                <div key={group} className={styles.group}>
                  <Text size={16} tone="secondary" weight={500}>
                    {group === 'structure' ? 'Structure confirmations' : 'Momentum confirmations'}
                  </Text>
                  <div className={styles.confirmList}>
                    {CONFIRMATION_OPTIONS.map((opt, i) => opt.type !== group ? null : (
                      <label
                        key={opt.signal_kind}
                        title={opt.tip}
                        className={`${styles.confirmItem} ${selected.has(i) ? styles.confirmItemSelected : ''}`}
                      >
                        <input type="checkbox" checked={selected.has(i)} onChange={() => toggleConfirm(i)} />
                        <Text size={16}>{opt.label(side)}</Text>
                      </label>
                    ))}
                  </div>
                  {group === 'momentum' && (
                    <Text size={16} tone="dim">
                      {deliveryMode === 'watch'
                        ? 'A Watch judges only the candle that closed last before each run, so it '
                          + 'misses crosses between runs: use a Rule for intraday momentum; a Watch '
                          + 'suits daily charts. The newest candle is treated as still forming, so a '
                          + 'daily cross is seen the next session. After an alert the Watch re-arms on '
                          + 'the first run where the alert is no longer met (for example, no cross), '
                          + 'and the next cross alerts again.'
                        : 'A Rule judges each closed candle once and fires at most once per candle; '
                          + 'the newest candle is treated as still forming, so a daily cross is seen '
                          + 'the next session. Its cooldown (60 min by default) also holds back a '
                          + 'second cross inside that window.'}
                    </Text>
                  )}
                </div>
              ))}
              {selected.size > 0 && (
                <div className={styles.row}>
                  <Text size={16} tone="secondary">Require {requireN} of {selected.size}</Text>
                  <Text size={16} tone="dim">
                    N of the selected confirmations (structure and momentum together)
                  </Text>
                  <input
                    type="range" min={1} max={selected.size} step={1}
                    value={requireN}
                    onChange={(e) => setMinConf(Number(e.target.value))}
                    className={styles.range}
                    aria-label="Confirmations required"
                  />
                </div>
              )}
            </div>

            <div className={styles.section}>
              <Text size={16} tone="secondary" weight={500}>Mean Reversion strategies</Text>
              <div className={styles.confirmList}>
                {MR_STRATEGY_OPTIONS.map((opt, i) => (
                  <label
                    key={opt.key}
                    className={`${styles.confirmItem} ${mrSelected.has(i) ? styles.confirmItemSelected : ''}`}
                  >
                    <input type="checkbox" checked={mrSelected.has(i)} onChange={() => toggleMr(i)} />
                    <span>
                      <Text size={16}>{opt.label}</Text>
                      <Text size={16} tone="dim"> — {opt.note}</Text>
                    </span>
                  </label>
                ))}
              </div>
              {mrSelected.size > 0 && (
                <div className={styles.row}>
                  <Text size={16} tone="secondary">At least {Math.min(minMrConf, mrSelected.size)} of {mrSelected.size} must fire</Text>
                  <input
                    type="range" min={1} max={mrSelected.size} step={1}
                    value={Math.min(minMrConf, mrSelected.size)}
                    onChange={(e) => setMinMrConf(Number(e.target.value))}
                    className={styles.range}
                  />
                </div>
              )}
            </div>

            {error && <Text size={16} tone="reject">{error}</Text>}

            <div className={styles.actions}>
              <button type="button" className={styles.cancelBtn} onClick={onClose}>Cancel</button>
              <button type="button" className={styles.saveBtn} onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Create Alert'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
