'use client';
import { useState } from 'react';
import { useChartStore, type IndicatorConfig } from '@/lib/chartStore';
import { Text } from '@/components/primitives';
import styles from './IndicatorPanel.module.css';

const AVAILABLE: Array<{
  type: string; label: string; pane: 'main' | 'sub';
  defaultParams: Record<string, number>; color: string;
}> = [
  { type: 'SMA',  label: 'SMA',             pane: 'main', defaultParams: { period: 20 },                    color: '#a0a0ff' },
  { type: 'EMA',  label: 'EMA',             pane: 'main', defaultParams: { period: 20 },                    color: '#4f8ef7' },
  { type: 'BB',   label: 'Bollinger Bands', pane: 'main', defaultParams: { period: 20, stdDev: 2 },         color: '#c07070' },
  { type: 'VWAP', label: 'VWAP',            pane: 'main', defaultParams: {},                                color: '#70c0c0' },
  { type: 'RSI',  label: 'RSI',             pane: 'sub',  defaultParams: { period: 14 },                    color: '#70b070' },
  { type: 'MACD', label: 'MACD',            pane: 'sub',  defaultParams: { fast: 12, slow: 26, signal: 9 }, color: '#c080c0' },
  { type: 'ATR',  label: 'ATR',             pane: 'sub',  defaultParams: { period: 14 },                    color: '#c0a040' },
  { type: 'VOL',  label: 'Volume',          pane: 'sub',  defaultParams: {},                                color: '#4a4a6a' },
  // ── New chart overlays (params editable in-panel) ──
  { type: 'MASUITE',   label: 'MA Suite (4)',     pane: 'main', defaultParams: { ma1: 9, ma2: 21, ma3: 50, ma4: 200 }, color: '#4f8ef7' },
  { type: 'XSIGNAL',   label: 'EMA/SMA Cross',    pane: 'main', defaultParams: { emaLen: 9, smaLen: 20 },              color: '#e0a030' },
  { type: 'AVWAP',     label: 'Anchored VWAP',    pane: 'main', defaultParams: { anchorMs: 1735689600000 },           color: '#b070e0' },
  { type: 'KEYLEVELS', label: 'Key Levels',       pane: 'main', defaultParams: { day: 1, week: 1 },                   color: '#808080' },
  { type: 'HTFLEVELS', label: 'Higher-TF Levels', pane: 'main', defaultParams: { tfMin: 240 },                        color: '#30a060' },
  { type: 'SIGNALS',   label: 'Signal Markers',   pane: 'main', defaultParams: { fast: 9, slow: 21, rsi: 14 },        color: '#26a69a' },
  { type: 'MTF',       label: 'MTF Dashboard',    pane: 'main', defaultParams: { rsi: 14 },                           color: '#888888' },
  { type: 'VPROFILE',  label: 'Volume Profile',   pane: 'main', defaultParams: { lookback: 200, rows: 24 },           color: '#5a6acf' },
];

const PARAM_LABELS: Record<string, string> = {
  period: 'Period', fast: 'Fast', slow: 'Slow', signal: 'Signal', stdDev: 'StdDev',
  ma1: 'MA1', ma2: 'MA2', ma3: 'MA3', ma4: 'MA4',
  emaLen: 'EMA len', smaLen: 'SMA len', anchorMs: 'Anchor (ms)',
  day: 'Prev day', week: 'Prev week', tfMin: 'HTF (min)',
  lookback: 'Lookback', rows: 'Rows',
};

interface Props { onClose: () => void; }

export default function IndicatorPanel({ onClose }: Props) {
  const { activeIndicators, addIndicator, removeIndicator, updateIndicator } = useChartStore();
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filtered = AVAILABLE.filter(a => a.label.toLowerCase().includes(search.toLowerCase()));
  const isActive = (type: string) => activeIndicators.some(i => i.type === type);

  const toggle = (def: typeof AVAILABLE[0]) => {
    if (isActive(def.type)) {
      const existing = activeIndicators.find(i => i.type === def.type);
      if (existing) removeIndicator(existing.id);
    } else {
      const cfg: IndicatorConfig = {
        id: `${def.type.toLowerCase()}-${Date.now()}`,
        type: def.type, params: def.defaultParams, pane: def.pane, color: def.color,
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

      {activeIndicators.length > 0 && (
        <div className={styles.activeSection}>
          <Text size={10} tone="dim" weight={500}>ACTIVE</Text>
          {activeIndicators.map(ind => {
            const paramKeys = Object.keys(ind.params);
            const isExpanded = expandedId === ind.id;
            return (
              <div key={ind.id} className={styles.activeRow}>
                <span className={styles.dot} style={{ background: ind.color }} />
                <Text size={12} tone="primary">{ind.type}</Text>
                {paramKeys.length > 0 && (
                  <button
                    className={styles.editBtn}
                    onClick={() => setExpandedId(isExpanded ? null : ind.id)}
                  >
                    {isExpanded ? '▲' : '▼'}
                  </button>
                )}
                <button
                  className={styles.removeBtn}
                  onClick={() => removeIndicator(ind.id)}
                >✕</button>
                {isExpanded && paramKeys.length > 0 && (
                  <div className={styles.paramRow}>
                    {paramKeys.map(key => (
                      <label key={key} className={styles.paramLabel}>
                        <Text size={10} tone="dim">{PARAM_LABELS[key] ?? key}</Text>
                        <input
                          key={`${ind.id}-${key}`}
                          type="number"
                          className={styles.paramInput}
                          defaultValue={ind.params[key]}
                          min={1}
                          step={1}
                          onBlur={e => {
                            const val = Number(e.target.value);
                            if (val > 0) {
                              updateIndicator(ind.id, { params: { ...ind.params, [key]: val } });
                            } else {
                              e.target.value = String(ind.params[key]);
                            }
                          }}
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

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
