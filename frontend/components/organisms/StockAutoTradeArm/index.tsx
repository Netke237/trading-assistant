'use client';

import { useState } from 'react';
import { Text } from '@/components/primitives';
import { api } from '@/lib/api';
import styles from './StockAutoTradeArm.module.css';

type StockArmMode = 'manual' | 'after_scan' | 'armed';

const MODE_LABELS: Record<StockArmMode, string> = {
  manual:     'Manual — I press the button',
  after_scan: 'After scan — fire when next scan PASS',
  armed:      'Armed — add to Strategy Watches now',
};

interface StockAutoTradeArmProps {
  symbol: string;
  strategyKey: string;
  afterScanArmed: boolean;
  onAfterScanToggle: (symbol: string, armed: boolean) => void;
}

export function StockAutoTradeArm({
  symbol,
  strategyKey,
  afterScanArmed,
  onAfterScanToggle,
}: StockAutoTradeArmProps) {
  const [mode, setMode]       = useState<StockArmMode>('manual');
  const [watchId, setWatchId] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function handleArm() {
    setWorking(true);
    setError(null);
    try {
      const res = await api.addStrategyWatch(symbol, strategyKey);
      setWatchId(res.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <Text size={13} weight={500}>Auto-trade mode</Text>

      <div className={styles.modeRow}>
        {(Object.keys(MODE_LABELS) as StockArmMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`${styles.modeBtn} ${mode === m ? styles.modeBtnActive : ''}`}
            onClick={() => {
              const prev = mode;
              setMode(m);
              if (m === 'after_scan') onAfterScanToggle(symbol, true);
              else if (prev === 'after_scan') onAfterScanToggle(symbol, false);
            }}
          >
            <Text size={12}>{MODE_LABELS[m]}</Text>
          </button>
        ))}
      </div>

      {mode === 'armed' && (
        <div className={styles.armRow}>
          {watchId === null ? (
            <button
              type="button"
              className={`${styles.btn} ${styles.btnArm}`}
              onClick={handleArm}
              disabled={working || !strategyKey}
              title={!strategyKey ? 'Select a strategy first' : undefined}
            >
              <Text size={12}>{working ? 'Adding watch…' : `Watch ${symbol} — ${strategyKey}`}</Text>
            </button>
          ) : (
            <>
              <Text size={12} tone="pass">Watching {symbol} (ID: {watchId})</Text>
              <button
                type="button"
                className={styles.btn}
                onClick={() => setWatchId(null)}
              >
                <Text size={12}>Remove watch</Text>
              </button>
            </>
          )}
        </div>
      )}

      {mode === 'after_scan' && (
        <Text size={11} tone="secondary">
          {afterScanArmed
            ? `Armed — will execute when next scan finds a PASS for ${symbol}.`
            : `Will execute when next scan finds a PASS for ${symbol}.`}
        </Text>
      )}

      {error && <Text size={12} tone="reject">{error}</Text>}
    </div>
  );
}
