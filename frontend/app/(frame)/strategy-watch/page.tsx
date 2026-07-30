'use client';

import { useEffect, useState } from 'react';
import { useStrategyWatchStore } from '@/lib/strategyWatchStore';
import { api } from '@/lib/api';
import type { StrategyWatchSchedule } from '@/lib/api';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
import styles from './page.module.css';

const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback EMA' },
  { key: 'breakout_base',      label: 'Breakout Base' },
  { key: 'ma_crossover',       label: 'MA Crossover' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI' },
  { key: 'mean_reversion_bb',  label: 'Mean Reversion BB' },
] as const;

function phasePill(phase: string) {
  if (phase === 'armed') return <span className={`${styles.pill} ${styles.pillArmed}`}>In trade / setup live</span>;
  return <span className={`${styles.pill} ${styles.pillIdle}`}>Waiting</span>;
}

export default function StrategyWatchPage() {
  const { watches, schedule, error, refresh, add, addBulk, remove, setEnabled, saveSchedule, evaluateNow } =
    useStrategyWatchStore();

  const [symbol, setSymbol] = useState('');
  const [strategyKey, setStrategyKey] = useState(STRATEGIES[0].key);
  const [bulkSymbols, setBulkSymbols] = useState('');
  const [bulkStrategy, setBulkStrategy] = useState(STRATEGIES[0].key);
  const [evalMsg, setEvalMsg] = useState('');
  const [direction, setDirection] = useState<'Bullish' | 'Bearish'>('Bullish');
  const [bulkDirection, setBulkDirection] = useState<'Bullish' | 'Bearish'>('Bullish');
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const missing = Array.from(new Set(watches.map((w) => w.symbol))).filter((s) => !(s in names));
    if (missing.length === 0) return;
    let cancelled = false;
    Promise.all(
      missing.map((s) =>
        api.getSymbolInfo(s).then(
          ({ name }) => [s, name] as const,
          () => [s, s] as const,
        ),
      ),
    ).then((pairs) => {
      if (cancelled) return;
      setNames((cur) => ({ ...cur, ...Object.fromEntries(pairs) }));
    });
    return () => { cancelled = true; };
  }, [watches, names]);

  const onAdd = async () => {
    if (!symbol.trim()) return;
    await add(symbol.trim(), strategyKey, direction);
    setSymbol('');
  };

  const onBulkAdd = async () => {
    const syms = bulkSymbols.split(',').map((s) => s.trim()).filter(Boolean);
    if (syms.length === 0) return;
    await addBulk(syms, bulkStrategy, bulkDirection);
    setBulkSymbols('');
  };

  const onEvaluate = async () => {
    setEvalMsg('Evaluating…');
    const fired = await evaluateNow();
    setEvalMsg(`Done — ${fired} alert(s) fired.`);
  };

  const updateSched = (patch: Partial<StrategyWatchSchedule>) => {
    if (!schedule) return;
    saveSchedule({ ...schedule, ...patch });
  };

  return (
    <div className={styles.page}>
      <h1>Strategy Watch</h1>
      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.section}>
        <strong>Add a watch</strong>
        <div className={styles.row}>
          <input className={styles.input} placeholder="Symbol (e.g. AAPL)"
                 value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <select className={styles.select} value={strategyKey}
                  onChange={(e) => setStrategyKey(e.target.value as typeof strategyKey)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className={styles.select} value={direction}
                  onChange={(e) => setDirection(e.target.value as 'Bullish' | 'Bearish')}>
            <option value="Bullish">Bullish</option>
            <option value="Bearish">Bearish</option>
          </select>
          <button className={styles.btn} onClick={onAdd}>Add</button>
        </div>
        <div className={styles.row}>
          <input className={styles.input} placeholder="Bulk: AAPL, MSFT, GOOG"
                 value={bulkSymbols} onChange={(e) => setBulkSymbols(e.target.value)} />
          <select className={styles.select} value={bulkStrategy}
                  onChange={(e) => setBulkStrategy(e.target.value as typeof bulkStrategy)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className={styles.select} value={bulkDirection}
                  onChange={(e) => setBulkDirection(e.target.value as 'Bullish' | 'Bearish')}>
            <option value="Bullish">Bullish</option>
            <option value="Bearish">Bearish</option>
          </select>
          <button className={styles.btn} onClick={onBulkAdd}>Bulk add</button>
        </div>
      </div>

      <div className={styles.section}>
        <strong>Schedule</strong>
        {schedule && (
          <div className={styles.row}>
            <label><input type="checkbox" checked={schedule.enabled}
                          onChange={(e) => updateSched({ enabled: e.target.checked })} /> Enabled</label>
            <select className={styles.select} value={schedule.mode}
                    onChange={(e) => updateSched({ mode: e.target.value as 'eod' | 'poll' })}>
              <option value="eod">End of day</option>
              <option value="poll">Every N hours</option>
            </select>
            {schedule.mode === 'eod' ? (
              <input className={styles.input} type="time" value={schedule.eod_time}
                     onChange={(e) => updateSched({ eod_time: e.target.value })} />
            ) : (
              <input className={styles.input} type="number" min={1} max={24} value={schedule.poll_hours}
                     onChange={(e) => updateSched({ poll_hours: Number(e.target.value) })} />
            )}
            <label>
              Sustain (min)
              <input className={styles.input} type="number" min={0} max={1440}
                     value={schedule.sustain_minutes}
                     onChange={(e) => updateSched({ sustain_minutes: Number(e.target.value) })}
                     title="Optional: an entry/exit signal must persist across this many minutes of checks before it fires." />
            </label>
            <button className={styles.btn} onClick={onEvaluate}>Evaluate now</button>
            <span>{evalMsg}</span>
          </div>
        )}
      </div>

      <div className={styles.section}>
        <strong>Watched ({watches.length})</strong>
        <table className={styles.table}>
          <thead><tr><th></th><th>Symbol</th><th>Name</th><th>Strategy</th><th>Direction</th><th>State</th><th>Enabled</th><th></th></tr></thead>
          <tbody>
            {watches.map((w) => (
              <tr key={w.id}>
                <td><OpenChartButton symbol={w.symbol} /></td>
                <td>{w.symbol}</td>
                <td>{names[w.symbol] ?? w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
                <td>
                  <span className={`${styles.pill} ${w.direction === 'Bearish' ? styles.pillBearish : styles.pillBullish}`}>
                    {w.direction === 'Bearish' ? 'Bearish' : 'Bullish'}
                  </span>
                </td>
                <td>{phasePill(w.last_state.phase)}</td>
                <td><input type="checkbox" checked={w.enabled}
                           onChange={(e) => setEnabled(w.id, e.target.checked)} /></td>
                <td><button className={styles.btn} onClick={() => remove(w.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
