'use client';

import { Text } from '@/components/primitives';
import styles from './MethodCompareSelector.module.css';

// TC-REVIEW-05 (#580) — which profit-target method cards are open side by
// side. DISPLAY ONLY and controlled: it holds no state, starts no effects and
// knows nothing about `methodPick`. Opening or comparing a method is not
// choosing it for the Final Recommendation, and it never runs a calculation
// or writes an order/exit field. The caller owns the selection.

export type ComparedMethod = 'arithmetic' | 'monte_carlo' | 'ladder';

export const COMPARED_METHODS: readonly { method: ComparedMethod; label: string }[] = [
  { method: 'arithmetic', label: 'Arithmetic' },
  { method: 'monte_carlo', label: 'Monte Carlo' },
  { method: 'ladder', label: 'Fixed % Ladder' },
];

interface MethodCompareSelectorProps {
  value: readonly ComparedMethod[];
  onChange: (next: ComparedMethod[]) => void;
}

export function MethodCompareSelector({ value, onChange }: MethodCompareSelectorProps) {
  const toggle = (method: ComparedMethod) => {
    const shown = value.includes(method);
    // At least one card stays open; the last checked box is disabled below.
    if (shown && value.length === 1) return;
    // Canonical order, so the cards never reorder on a toggle.
    onChange(COMPARED_METHODS
      .map((m) => m.method)
      .filter((m) => (m === method ? !shown : value.includes(m))));
  };

  return (
    <fieldset className={styles.wrap}>
      <legend className={styles.legend}>
        <Text size={11} tone="secondary">Show side by side</Text>
      </legend>
      <div className={styles.row}>
        {COMPARED_METHODS.map(({ method, label }) => {
          const checked = value.includes(method);
          return (
            <label key={method} className={styles.option}>
              <input
                type="checkbox"
                checked={checked}
                disabled={checked && value.length === 1}
                onChange={() => toggle(method)}
              />
              <Text size={12} weight={400}>{label}</Text>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
