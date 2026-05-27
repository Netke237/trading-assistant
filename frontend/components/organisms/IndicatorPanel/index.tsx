'use client';
import { useState } from 'react';
import { useChartStore, type IndicatorConfig } from '@/lib/chartStore';
import { Text } from '@/components/primitives';
import styles from './IndicatorPanel.module.css';

const AVAILABLE: Array<{
  type: string;
  label: string;
  pane: 'main' | 'sub';
  defaultParams: Record<string, number>;
  color: string;
}> = [
  { type: 'SMA',  label: 'SMA',             pane: 'main', defaultParams: { period: 20 },                      color: '#a0a0ff' },
  { type: 'EMA',  label: 'EMA',             pane: 'main', defaultParams: { period: 20 },                      color: '#4f8ef7' },
  { type: 'BB',   label: 'Bollinger Bands', pane: 'main', defaultParams: { period: 20, stdDev: 2 },           color: '#c07070' },
  { type: 'VWAP', label: 'VWAP',            pane: 'main', defaultParams: {},                                  color: '#70c0c0' },
  { type: 'RSI',  label: 'RSI',             pane: 'sub',  defaultParams: { period: 14 },                      color: '#70b070' },
  { type: 'MACD', label: 'MACD',            pane: 'sub',  defaultParams: { fast: 12, slow: 26, signal: 9 },   color: '#c080c0' },
  { type: 'ATR',  label: 'ATR',             pane: 'sub',  defaultParams: { period: 14 },                      color: '#c0a040' },
  { type: 'VOL',  label: 'Volume',          pane: 'sub',  defaultParams: {},                                  color: '#4a4a6a' },
];

interface Props { onClose: () => void; }

export default function IndicatorPanel({ onClose }: Props) {
  const { activeIndicators, addIndicator, removeIndicator } = useChartStore();
  const [search, setSearch] = useState('');

  const filtered = AVAILABLE.filter(a => a.label.toLowerCase().includes(search.toLowerCase()));
  const isActive = (type: string) => activeIndicators.some(i => i.type === type);

  const toggle = (def: typeof AVAILABLE[0]) => {
    if (isActive(def.type)) {
      const existing = activeIndicators.find(i => i.type === def.type);
      if (existing) removeIndicator(existing.id);
    } else {
      const cfg: IndicatorConfig = {
        id: `${def.type.toLowerCase()}-${Date.now()}`,
        type: def.type,
        params: def.defaultParams,
        pane: def.pane,
        color: def.color,
      };
      addIndicator(cfg);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Text size={13} tone="primary" weight={500}>Indicators</Text>
        <button className={styles.close} onClick={onClose}>✕</button>
      </div>
      <input
        className={styles.search}
        placeholder="Search…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className={styles.list}>
        {filtered.map(def => (
          <button
            key={def.type}
            className={`${styles.item} ${isActive(def.type) ? styles.itemActive : ''}`}
            onClick={() => toggle(def)}
          >
            <span className={styles.dot} style={{ background: def.color }} />
            <Text size={12} tone={isActive(def.type) ? 'primary' : 'secondary'}>{def.label}</Text>
            <span className={styles.check}>{isActive(def.type) ? '✓' : '+'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
