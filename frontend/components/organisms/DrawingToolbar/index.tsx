'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool =
  | 'cursor' | 'trendline' | 'hline' | 'rect'
  | 'alert'  | 'buy'
  | 'fib' | 'text' | 'measure' | 'zoom'
  | 'eraser';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
  onClear: () => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',    label: 'Cursor',          icon: '✛' },
  { id: 'trendline', label: 'Trendline',       icon: '╱' },
  { id: 'hline',     label: 'Horizontal line', icon: '─' },
  { id: 'rect',      label: 'Rectangle',       icon: '□' },
  { id: 'text',      label: 'Text',            icon: 'T' },
  { id: 'alert',     label: 'Set alert',       icon: '🔔' },
  { id: 'buy',       label: 'Paper buy',       icon: '＄' },
  { id: 'eraser',    label: 'Eraser',          icon: '⌫' },
];

export default function DrawingToolbar({ active, onChange, onClear }: Props) {
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
      <button
        className={styles.tool}
        title="Clear all drawings"
        onClick={onClear}
      >
        ✕
      </button>
    </div>
  );
}
