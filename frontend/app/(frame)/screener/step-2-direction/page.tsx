'use client';

/*
 * Screener Step 2 — Direction + Horizon. Phase 5 / Round 1.
 * Directional bias + holding-horizon preset picker, plus a Custom option
 * for explicit (min..max) day ranges.
 */

import { useState } from 'react';
import { Title, Text } from '@/components/primitives';
import type { Direction } from '@/types/domain';
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

export default function Step2Page() {
  const [dir, setDir] = useState<Direction>('Bullish');
  const [hz,  setHz]  = useState<HorizonKey>('Swing');
  const [minDays, setMinDays] = useState(5);
  const [maxDays, setMaxDays] = useState(15);

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
              onClick={() => setDir(d)}
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
              onClick={() => setHz(h.key)}
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
              onChange={(e) => setMinDays(Math.max(0, Number(e.target.value)))}
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
              onChange={(e) => setMaxDays(Math.max(minDays, Number(e.target.value)))}
              aria-label="Maximum days"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
