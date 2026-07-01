'use client';
import styles from './DrawingToolbar.module.css';

export type DrawingTool =
  | 'cursor' | 'trendline' | 'hline' | 'rect'
  | 'arrow' | 'arrow_up' | 'arrow_down'
  | 'circle' | 'path'
  | 'alert' | 'buy'
  | 'fib' | 'text' | 'measure' | 'zoom'
  | 'eraser';

interface Props {
  active: DrawingTool;
  onChange: (t: DrawingTool) => void;
  onClear: () => void;
  color: string;
  onColorChange: (c: string) => void;
}

const TOOLS: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor',     label: 'Cursor',           icon: '✛' },
  { id: 'trendline',  label: 'Trendline',        icon: '╱' },
  { id: 'hline',      label: 'Horizontal line',  icon: '─' },
  { id: 'rect',       label: 'Rectangle',        icon: '□' },
  { id: 'arrow',      label: 'Arrow',            icon: '→' },
  { id: 'arrow_up',   label: 'Arrow mark up',    icon: '▲' },
  { id: 'arrow_down', label: 'Arrow mark down',  icon: '▼' },
  { id: 'circle',     label: 'Circle',           icon: '○' },
  { id: 'path',       label: 'Path',             icon: '∿' },
  { id: 'text',       label: 'Text',             icon: 'T' },
  { id: 'alert',      label: 'Set alert',        icon: '🔔' },
  { id: 'buy',        label: 'Paper buy',        icon: '＄' },
  { id: 'eraser',     label: 'Eraser',           icon: '⌫' },
];

export default function DrawingToolbar({ active, onChange, onClear, color, onColorChange }: Props) {
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
      <div className={styles.divider} />
      <label className={styles.colorSwatch} title="Stroke colour" style={{ backgroundColor: color }}>
        <input
          type="color"
          value={color}
          onChange={(e) => onColorChange(e.target.value)}
          className={styles.colorInput}
        />
      </label>
      <button className={styles.tool} title="Clear all drawings" onClick={onClear}>
        ✕
      </button>
    </div>
  );
}
