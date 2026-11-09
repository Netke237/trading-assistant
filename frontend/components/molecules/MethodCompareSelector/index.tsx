'use client';

import styles from './MethodCompareSelector.module.css';

// TC-REVIEW-05 (#580) — which profit-target method cards are open side by
// side. DISPLAY ONLY and controlled: it holds no state, starts no effects and
// knows nothing about `methodPick`. Opening or comparing a method is not
// choosing it for the Final Recommendation, and it never runs a calculation
// or writes an order/exit field. The caller owns the selection.
//
// #610 G6 — drawn as the reference's segmented buttons (Monte Carlo ·
// Arithmetic · Ladder · Compare) instead of a checkbox fieldset. The rules are
// unchanged: each method button shows or hides its own card (a toggle with
// checkbox semantics, so its state is announced), at least one card stays
// open (the last one is disabled), and cards keep the canonical order.
// Compare is a shortcut over the same selection: it opens all three, and
// while two or more are open it returns to the first open card alone.

export type ComparedMethod = 'arithmetic' | 'monte_carlo' | 'ladder';

export const COMPARED_METHODS: readonly { method: ComparedMethod; label: string }[] = [
  { method: 'monte_carlo', label: 'Monte Carlo' },
  { method: 'arithmetic', label: 'Arithmetic' },
  { method: 'ladder', label: 'Ladder' },
];

const ORDER = COMPARED_METHODS.map((m) => m.method);

interface MethodCompareSelectorProps {
  value: readonly ComparedMethod[];
  onChange: (next: ComparedMethod[]) => void;
}

export function MethodCompareSelector({ value, onChange }: MethodCompareSelectorProps) {
  const toggle = (method: ComparedMethod) => {
    const shown = value.includes(method);
    // At least one card stays open; the last open button is disabled below.
    if (shown && value.length === 1) return;
    // Canonical order, so the cards never reorder on a toggle.
    onChange(ORDER.filter((m) => (m === method ? !shown : value.includes(m))));
  };
  const comparing = value.length > 1;
  const compare = () => {
    onChange(comparing ? ORDER.filter((m) => value.includes(m)).slice(0, 1) : [...ORDER]);
  };

  return (
    <div className={styles.wrap} role="group" aria-label="Show methods">
      {COMPARED_METHODS.map(({ method, label }) => {
        const checked = value.includes(method);
        return (
          <button
            key={method}
            type="button"
            role="checkbox"
            aria-checked={checked}
            className={styles.segment}
            disabled={checked && value.length === 1}
            onClick={() => toggle(method)}
          >
            {label}
          </button>
        );
      })}
      <button
        type="button"
        aria-pressed={comparing}
        className={styles.segment}
        onClick={compare}
      >
        Compare
      </button>
    </div>
  );
}
