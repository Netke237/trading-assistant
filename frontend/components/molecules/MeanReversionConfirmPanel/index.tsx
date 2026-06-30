'use client';

import { Text } from '@/components/primitives';
import styles from './MeanReversionConfirmPanel.module.css';

interface Props {
  variants: string[];
  minConfirmations: number;
  vwapLookback: number;
  vwapDeviationPct: number;
  onChange: (update: Partial<{
    variants: string[];
    minConfirmations: number;
    vwapLookback: number;
    vwapDeviationPct: number;
  }>) => void;
}

const VARIANT_OPTIONS = [
  { key: 'mean_reversion_rsi',  label: 'RSI extremes + trend filter' },
  { key: 'mean_reversion_bb',   label: 'Bollinger Band touch + close' },
  { key: 'mean_reversion_vwap', label: 'Daily VWAP snap-back' },
] as const;

export function MeanReversionConfirmPanel({
  variants,
  minConfirmations,
  vwapLookback,
  vwapDeviationPct,
  onChange,
}: Props) {
  function toggleVariant(key: string) {
    const next = variants.includes(key)
      ? variants.filter((v) => v !== key)
      : [...variants, key];
    onChange({ variants: next });
  }

  const vwapChecked = variants.includes('mean_reversion_vwap');
  const maxSelect = variants.length;
  const showWarning = minConfirmations > maxSelect;

  return (
    <div className={styles.panel}>
      <Text size={12} tone="secondary" weight={500}>Signal confirmation</Text>

      <div className={styles.checkboxGroup}>
        {VARIANT_OPTIONS.map(({ key, label }) => (
          <label key={key} className={styles.checkboxRow}>
            <input
              type="checkbox"
              checked={variants.includes(key)}
              onChange={() => toggleVariant(key)}
              className={styles.checkbox}
            />
            <Text size={11} tone={variants.includes(key) ? 'primary' : 'secondary'}>{label}</Text>
          </label>
        ))}
      </div>

      {vwapChecked && (
        <div className={styles.vwapSubRow}>
          <label className={styles.vwapField}>
            <Text size={11} tone="dim">VWAP lookback</Text>
            <div className={styles.inputRow}>
              <input
                type="number"
                value={vwapLookback}
                min={5}
                max={60}
                step={1}
                className={styles.numInput}
                onChange={(e) => onChange({ vwapLookback: Number(e.target.value) })}
              />
              <Text size={11} tone="dim">bars</Text>
            </div>
          </label>
          <label className={styles.vwapField}>
            <Text size={11} tone="dim">VWAP deviation</Text>
            <div className={styles.inputRow}>
              <input
                type="number"
                value={Math.round(vwapDeviationPct * 100 * 10) / 10}
                min={0.1}
                max={10}
                step={0.1}
                className={styles.numInput}
                onChange={(e) => onChange({ vwapDeviationPct: Number(e.target.value) / 100 })}
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>
        </div>
      )}

      <div className={styles.thresholdRow}>
        <Text size={11} tone="dim">Fire when at least</Text>
        <select
          className={styles.select}
          value={minConfirmations}
          onChange={(e) => onChange({ minConfirmations: Number(e.target.value) })}
        >
          {[1, 2, 3].map((n) => (
            <option key={n} value={n} disabled={n > maxSelect}>
              {n}
            </option>
          ))}
        </select>
        <Text size={11} tone="dim">signal(s) confirm</Text>
      </div>

      {showWarning && (
        <Text size={11} tone="caution">
          Select at least {minConfirmations} variants to match your threshold.
        </Text>
      )}
    </div>
  );
}
