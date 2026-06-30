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

const CONFIRMATION_OPTIONS = [
  { type: 'structure', signal_kind: 'BOS',            label: 'Break of Structure' },
  { type: 'structure', signal_kind: 'CHoCH',          label: 'Change of Character' },
  { type: 'structure', signal_kind: 'FVG',            label: 'Fair Value Gap' },
  { type: 'structure', signal_kind: 'OrderBlock',     label: 'Order Block' },
  { type: 'structure', signal_kind: 'RSIDivergence',  label: 'RSI Divergence' },
  { type: 'structure', signal_kind: 'MACDDivergence', label: 'MACD Divergence' },
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

  useEffect(() => {
    api.getCompositeWatchDefaults().then((d) => {
      setConvictionMin(d.conviction_min);
      setPStayMin(d.p_stay_min);
      setMinConf(d.min_confirmations);
    }).catch(() => {});
  }, []);

  const stateOptions = model === 'OMM' ? OMM_STATES : HMM_STATES;

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
    const confirmations = Array.from(selected).map((i) => ({
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
      min_confirmations: Math.min(minConf, confirmations.length),
      strategy_confirmations: strategyConfirmations,
      min_strategy_confirmations: strategyConfirmations.length > 0 ? Math.min(minMrConf, strategyConfirmations.length) : 0,
      horizon: 'swing',
    };
    try {
      await api.addCompositeWatch(symbol, triggerDef, direction, interval);
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
          <Text size={14} weight={500}>Set Regime Alert — {symbol}</Text>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close">✕</button>
        </div>

        {done ? (
          <div className={styles.doneMsg}>
            <Text size={13} tone="pass">Alert created for {symbol}.</Text>
          </div>
        ) : (
          <>
            <div className={styles.row}>
              <Text size={12} tone="secondary">Model</Text>
              <select
                className={styles.select}
                value={model}
                onChange={(e) => { setModel(e.target.value as MarkovModel); setToState('any'); }}
              >
                <option value="OMM">OMM (daily)</option>
                <option value="HMM_daily">HMM daily</option>
                <option value="HMM_intraday">HMM intraday</option>
                <option value="any">Any model</option>
              </select>
            </div>

            {model === 'HMM_intraday' && (
              <div className={styles.row}>
                <Text size={12} tone="secondary">Interval</Text>
                <select className={styles.select} value={interval} onChange={(e) => setIntervalVal(e.target.value)}>
                  {['5m', '15m', '30m', '1h', '4h'].map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            )}

            {model !== 'any' && (
              <div className={styles.row}>
                <Text size={12} tone="secondary">Target state</Text>
                <select className={styles.select} value={toState} onChange={(e) => setToState(e.target.value)}>
                  {stateOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            )}

            <div className={styles.row}>
              <Text size={12} tone="secondary">Conviction ≥ {convictionMin}%</Text>
              <input
                type="range" min={0} max={100} step={5}
                value={convictionMin}
                onChange={(e) => setConvictionMin(Number(e.target.value))}
                className={styles.range}
              />
            </div>

            <div className={styles.row}>
              <Text size={12} tone="secondary">P(stay) ≥ {pStayMin.toFixed(2)}</Text>
              <input
                type="range" min={0} max={1} step={0.05}
                value={pStayMin}
                onChange={(e) => setPStayMin(Number(e.target.value))}
                className={styles.range}
              />
            </div>

            <div className={styles.section}>
              <Text size={12} tone="secondary" weight={500}>Structure confirmations</Text>
              <div className={styles.confirmList}>
                {CONFIRMATION_OPTIONS.map((opt, i) => (
                  <label
                    key={opt.signal_kind}
                    className={`${styles.confirmItem} ${selected.has(i) ? styles.confirmItemSelected : ''}`}
                  >
                    <input type="checkbox" checked={selected.has(i)} onChange={() => toggleConfirm(i)} />
                    <Text size={12}>{opt.label}</Text>
                  </label>
                ))}
              </div>
              {selected.size > 0 && (
                <div className={styles.row}>
                  <Text size={12} tone="secondary">Require {Math.min(minConf, selected.size)} of {selected.size}</Text>
                  <input
                    type="range" min={1} max={selected.size} step={1}
                    value={Math.min(minConf, selected.size)}
                    onChange={(e) => setMinConf(Number(e.target.value))}
                    className={styles.range}
                  />
                </div>
              )}
            </div>

            <div className={styles.section}>
              <Text size={12} tone="secondary" weight={500}>Mean Reversion strategies</Text>
              <div className={styles.confirmList}>
                {MR_STRATEGY_OPTIONS.map((opt, i) => (
                  <label
                    key={opt.key}
                    className={`${styles.confirmItem} ${mrSelected.has(i) ? styles.confirmItemSelected : ''}`}
                  >
                    <input type="checkbox" checked={mrSelected.has(i)} onChange={() => toggleMr(i)} />
                    <span>
                      <Text size={12}>{opt.label}</Text>
                      <Text size={11} tone="dim"> — {opt.note}</Text>
                    </span>
                  </label>
                ))}
              </div>
              {mrSelected.size > 0 && (
                <div className={styles.row}>
                  <Text size={12} tone="secondary">At least {Math.min(minMrConf, mrSelected.size)} of {mrSelected.size} must fire</Text>
                  <input
                    type="range" min={1} max={mrSelected.size} step={1}
                    value={Math.min(minMrConf, mrSelected.size)}
                    onChange={(e) => setMinMrConf(Number(e.target.value))}
                    className={styles.range}
                  />
                </div>
              )}
            </div>

            {error && <Text size={12} tone="reject">{error}</Text>}

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
