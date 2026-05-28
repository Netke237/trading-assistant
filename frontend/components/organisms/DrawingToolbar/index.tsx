'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool = 'cursor' | 'trendline' | 'fib' | 'rect' | 'text' | 'measure' | 'zoom';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',    label: 'Cursor',    icon: '✛' },
  { id: 'trendline', label: 'Trendline', icon: '╱' },
  { id: 'fib',       label: 'Fibonacci', icon: 'Φ' },
  { id: 'rect',      label: 'Rectangle', icon: '□' },
  { id: 'text',      label: 'Text',      icon: 'T' },
  { id: 'measure',   label: 'Measure',   icon: '↔' },
  { id: 'zoom',      label: 'Zoom',      icon: '⊕' },
];

export default function DrawingToolbar({ active, onChange }: Props) {
  return (
    <div className={styles.toolbar}>
      {TOOLS.map(t => (
        <button
          key={t.id}
          className={`${styles.tool} ${active === t.id ? styles.active : ''}`}
          title={t.label}
          onClick={() => onChange(t.id)}
        >
          {t.icon}
        </button>
      ))}
    </div>
  );
}
