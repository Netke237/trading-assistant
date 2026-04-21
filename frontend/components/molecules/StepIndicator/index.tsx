/*
 * StepIndicator — single step row (circle + label).
 * Completed: checkmark on --pass circle.
 * Current:   filled --accent circle with index.
 * Future:    outline circle with index.
 */

import { Text } from '@/components/primitives';
import styles from './StepIndicator.module.css';

export type StepState = 'completed' | 'current' | 'future';

interface StepIndicatorProps {
  index: number;
  label: string;
  state: StepState;
  onClick?: () => void;
  className?: string;
}

const STATE_CLASS: Record<StepState, string> = {
  completed: styles.completed,
  current:   styles.current,
  future:    styles.future,
};

export function StepIndicator({ index, label, state, onClick, className }: StepIndicatorProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[styles.item, className].filter(Boolean).join(' ')}
    >
      <span className={[styles.circle, STATE_CLASS[state]].join(' ')}>
        {state === 'completed' ? <CheckIcon /> : <span>{index}</span>}
      </span>
      <Text size={12} tone={state === 'future' ? 'secondary' : 'primary'}>
        {label}
      </Text>
    </button>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={styles.check}
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
