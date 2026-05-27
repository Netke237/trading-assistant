'use client';

import { useStructureStore } from '@/lib/structureStore';
import type { SignalKind } from '@/types/structure';
import styles from './StructurePanel.module.css';

const SIGNAL_LABELS: Record<SignalKind, string> = {
  FVG: 'Fair Value Gap',
  BOS: 'Break of Structure',
  CHoCH: 'Change of Character',
  OrderBlock: 'Order Block',
  Divergence: 'Divergence',
  Fibonacci: 'Fibonacci',
  Confluence: 'Confluence',
};

const SIGNAL_ORDER: SignalKind[] = [
  'FVG', 'BOS', 'CHoCH', 'OrderBlock', 'Divergence', 'Fibonacci', 'Confluence',
];

interface Props {
  onClose: () => void;
}

export default function StructurePanel({ onClose }: Props) {
  const visibility = useStructureStore((s) => s.visibility);
  const toggleKind = useStructureStore((s) => s.toggleKind);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.title}>Structure</span>
        <button className={styles.close} onClick={onClose} type="button">
          x
        </button>
      </div>
      <div className={styles.list}>
        {SIGNAL_ORDER.map((kind) => (
          <div key={kind} className={styles.row}>
            <span className={styles.label}>{SIGNAL_LABELS[kind]}</span>
            <button
              className={`${styles.toggle} ${visibility[kind] ? styles.toggleOn : ''}`}
              onClick={() => toggleKind(kind)}
              type="button"
              aria-label={`Toggle ${SIGNAL_LABELS[kind]}`}
            >
              <div className={styles.toggleKnob} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
