'use client';

/*
 * Screener Step 2 — Direction + Horizon. Phase 5 / Round 1.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 */

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import type { Direction } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import styles from '../screener.module.css';
import formStyles from './page.module.css';

const DIRECTIONS: Direction[] = ['Bullish', 'Bearish'];

type HorizonKey = 'Intraday' | 'Swing' | 'Position' | 'Custom';

const HORIZON_PRESETS: { key: HorizonKey; label: string; hint: string }[] = [
  { key: 'Intraday', label: 'Intraday', hint: '0–2 days' },
  { key: 'Swing',    label: 'Swing',    hint: '5–15 days' },
  { key: 'Position', label: 'Position', hint: '15–45 days' },
  { key: 'Custom',   label: 'Custom',   hint: 'Set range' },
];

function horizonLabel(hz: HorizonKey, minDays: number, maxDays: number): string {
  if (hz === 'Intraday') return 'Intraday (0–2d)';
  if (hz === 'Swing')    return 'Swing (5–15d)';
  if (hz === 'Position') return 'Position (15–45d)';
  return `Custom (${minDays}–${maxDays}d)`;
}

function parseHorizonKey(h: string | undefined): HorizonKey {
  if (!h) return 'Swing';
  if (h.startsWith('Intraday')) return 'Intraday';
  if (h.startsWith('Swing'))    return 'Swing';
  if (h.startsWith('Position')) return 'Position';
  if (h.startsWith('Custom'))   return 'Custom';
  return 'Swing';
}

function parseCustomDays(h: string | undefined): [number, number] {
  if (!h?.startsWith('Custom')) return [5, 15];
  const m = h.match(/(\d+)–(\d+)/);
  return m ? [Number(m[1]), Number(m[2])] : [5, 15];
}

export default function Step2Page() {
  const context     = useScanStore((s) => s.context);
  const setContext  = useScanStore((s) => s.setContext);
  const rejectedLog = useScanStore((s) => s.rejectedLog);

  const [dir,     setDir]     = useState<Direction>(() => context?.direction ?? 'Bullish');
  const [hz,      setHz]      = useState<HorizonKey>(() => parseHorizonKey(context?.horizon));
  const [minDays, setMinDays] = useState<number>(() => parseCustomDays(context?.horizon)[0]);
  const [maxDays, setMaxDays] = useState<number>(() => parseCustomDays(context?.horizon)[1]);

  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    setContext({
      universe:  context?.universe ?? 'SP500',
      direction: newDir,
      horizon:   horizonLabel(newHz, newMin, newMax),
    });
  }

  const handleDirChange = (d: Direction) => {
    setDir(d);
    syncToStore(d, hz, minDays, maxDays);
  };
  const handleHzChange = (h: HorizonKey) => {
    setHz(h);
    syncToStore(dir, h, minDays, maxDays);
  };
  const handleMinChange = (v: number) => {
    setMinDays(v);
    syncToStore(dir, hz, v, maxDays);
  };
  const handleMaxChange = (v: number) => {
    const clamped = Math.max(minDays, v);
    setMaxDays(clamped);
    syncToStore(dir, hz, minDays, clamped);
  };

  const custom = hz === 'Custom';

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 2 OF 7</Text>
        <Title as="h1" size={24}>Direction + Horizon</Title>
        <Text size={13} tone="secondary">Choose your directional bias and holding horizon.</Text>
      </div>

      <div className={formStyles.group}>
        <Text size={12} weight={600}>Directional bias</Text>
        <div className={formStyles.segmented}>
          {DIRECTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => handleDirChange(d)}
              className={`${formStyles.seg} ${dir === d ? formStyles.segActive : ''}`}
              aria-pressed={dir === d}
            >
              <Text size={13} weight={500}>{d}</Text>
            </button>
          ))}
        </div>
      </div>

      <div className={formStyles.group}>
        <Text size={12} weight={600}>Holding horizon</Text>
        <div className={formStyles.segmented}>
          {HORIZON_PRESETS.map((h) => (
            <button
              key={h.key}
              type="button"
              onClick={() => handleHzChange(h.key)}
              className={`${formStyles.seg} ${hz === h.key ? formStyles.segActive : ''}`}
              aria-pressed={hz === h.key}
            >
              <Text size={13} weight={500}>{h.label}</Text>
              <Text size={11} tone="secondary">{h.hint}</Text>
            </button>
          ))}
        </div>

        <div className={formStyles.customRow}>
          <Text size={12} tone={custom ? 'secondary' : 'dim'}>Range (days)</Text>
          <div className={formStyles.customInputs}>
            <input
              type="number"
              className={formStyles.numInput}
              value={minDays}
              min={0}
              max={365}
              disabled={!custom}
              onChange={(e) => handleMinChange(Math.max(0, Number(e.target.value)))}
              aria-label="Minimum days"
            />
            <Text size={12} tone="dim">to</Text>
            <input
              type="number"
              className={formStyles.numInput}
              value={maxDays}
              min={0}
              max={365}
              disabled={!custom}
              onChange={(e) => handleMaxChange(Number(e.target.value))}
              aria-label="Maximum days"
            />
          </div>
        </div>
      </div>

      {rejectedLog.length > 0 && (
        <div className={formStyles.logSection}>
          <div className={formStyles.logHeader}>
            <Text size={11} tone="dim" weight={500}>SCAN FILTER LOG</Text>
            <span className={formStyles.badge}>{rejectedLog.length}</span>
          </div>
          {rejectedLog.slice(0, 10).map((entry, i) => (
            <div key={i} className={formStyles.logRow}>
              <Data size={12} weight={500}>{entry.symbol}</Data>
              <Text size={12} tone="secondary">&mdash; {entry.reason}</Text>
            </div>
          ))}
          {rejectedLog.length > 10 && (
            <Text size={12} tone="dim">&hellip; and {rejectedLog.length - 10} more screened out</Text>
          )}
        </div>
      )}

    </div>
  );
}
