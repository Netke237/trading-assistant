'use client';

import { Text } from '@/components/primitives';
import styles from './FibPullbackParamsPanel.module.css';

export interface FibPullbackParams {
  fibSwingLookback: number;   // 20–200, default 100
  fibLevels: number[];        // subset of [23.6, 38.2, 50.0, 61.8, 78.6], default [38.2, 61.8]
  fibTolerancePct: number;    // stored as fraction 0.005–0.05, default 0.015
  emaFilterPeriod: number;    // 0 = disabled, default 20
}

export const FIB_PULLBACK_DEFAULTS: FibPullbackParams = {
  fibSwingLookback: 100,
  fibLevels: [38.2, 61.8],
  fibTolerancePct: 0.015,
  emaFilterPeriod: 20,
};

const ALL_FIB_LEVELS = [23.6, 38.2, 50.0, 61.8, 78.6];

interface Props {
  params: FibPullbackParams;
  setParams: React.Dispatch<React.SetStateAction<FibPullbackParams>>;
  onReset: () => void;
}

export function FibPullbackParamsPanel({ params, setParams, onReset }: Props) {
  return (
    <details className={styles.paramsPanel}>
      <summary className={styles.paramsSummary}>
        <Text size={12} tone="secondary">Scan parameters</Text>
      </summary>

      <div className={styles.paramsGrid}>

        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Fibonacci levels</Text>
          <Text size={10} tone="dim">
            Which retracement levels to treat as support. 38.2% and 61.8% are the most
            reliable. More levels = more results but more false positives.
          </Text>
          <div className={styles.fibLevels}>
            {ALL_FIB_LEVELS.map((lvl) => {
              const isChecked = params.fibLevels.includes(lvl);
              const isLastRemaining = isChecked && params.fibLevels.length === 1;
              return (
                <label key={lvl} className={styles.fibLevelCheck}>
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={isLastRemaining}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...params.fibLevels, lvl].sort((a, b) => a - b)
                        : params.fibLevels.filter((l) => l !== lvl);
                      setParams((p) => ({ ...p, fibLevels: next }));
                    }}
                  />
                  <Text size={11} tone={isChecked ? 'primary' : 'dim'}>{lvl}%</Text>
                </label>
              );
            })}
          </div>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Swing lookback</Text>
          <Text size={10} tone="dim">
            Bars back to search for the dominant swing high/low that anchors the fib move.
            Higher = captures bigger structural moves.
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.fibSwingLookback}
              min={20} max={200} step={5}
              onChange={(e) => setParams((p) => ({ ...p, fibSwingLookback: Number(e.target.value) }))}
            />
            <Text size={11} tone="dim">bars</Text>
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Tolerance</Text>
          <Text size={10} tone="dim">
            How close (%) price must be to a fib level to count as &quot;at level&quot;.
            Higher = wider net (more results); lower = only precise hits qualify.
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={Number((params.fibTolerancePct * 100).toFixed(6))}
              min={0.5} max={5.0} step={0.1}
              onChange={(e) =>
                setParams((p) => ({ ...p, fibTolerancePct: Number(e.target.value) / 100 }))
              }
            />
            <Text size={11} tone="dim">%</Text>
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">EMA trend filter</Text>
          <Text size={10} tone="dim">
            Only show stocks on the correct side of this EMA (Bullish: price &gt; EMA; Bearish: price &lt; EMA).
            Filters out counter-trend fib hits. Set to 0 to disable.
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.emaFilterPeriod}
              min={0} max={200} step={1}
              onChange={(e) => setParams((p) => ({ ...p, emaFilterPeriod: Number(e.target.value) }))}
            />
            <Text size={11} tone="dim">EMA {params.emaFilterPeriod > 0 ? params.emaFilterPeriod : '(off)'}</Text>
          </div>
        </label>

        <button type="button" className={styles.resetBtn} onClick={onReset}>
          Reset to defaults
        </button>

      </div>
    </details>
  );
}
