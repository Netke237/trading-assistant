'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool =
  | 'cursor' | 'trendline' | 'hline' | 'rect'
  | 'alert'  | 'buy'
  | 'fib' | 'text' | 'measure' | 'zoom';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',    label: 'Cursor',          icon: '✛' },
  { id: 'trendline', label: 'Trendline',       icon: '╱' },
  { id: 'hline',     label: 'Horizontal line', icon: '─' },
  { id: 'rect',      label: 'Rectangle',       icon: '□' },
  { id: 'text',      label: 'Text',            icon: 'T' },
  { id: 'alert',     label: 'Set alert',       icon: '🔔' },
  { id: 'buy',       label: 'Paper buy',       icon: '＄' },
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
