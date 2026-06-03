'use client';

import { useState } from 'react';
import { Text } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAutoTradeStore, type AutoTradeMode } from '@/lib/autoTradeStore';
import { api } from '@/lib/api';
import type { TradeCardData } from '@/types/domain';
import styles from './AutoTradeArm.module.css';

interface AutoTradeArmProps {
  card: TradeCardData;
  broker: string | null;
}

const MODE_LABELS: Record<AutoTradeMode, string> = {
  manual:    'Manual — I press the button',
  post_scan: 'After scan — fire when next scan finds a PASS',
  armed:     'Armed — fire on next qualifying condition',
};

export function AutoTradeArm({ card, broker }: AutoTradeArmProps) {
  const { autoMode, setAutoMode, armed, setArmed, lastOrderId, setLastOrderId } = useAutoTradeStore();
  const [working, setWorking] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const contractId = card.contract;
  // NOTE: option_symbol should be OCC format for real broker APIs; card.contract is
  // Bamendjou's display id. OCC conversion is a tracked follow-up — passed as-is for now.

  async function handleArm() {
    if (!broker) return;
    setWorking(true); setError(null);
    try {
      await api.armAutoTrade({
        broker,
        symbol:        card.symbol,
        option_symbol: contractId,
        action:        card.direction === 'Bullish' ? 'BUY' : 'SELL',
        quantity:      1,
        order_type:    'LMT',
        limit_price:   card.entry.limit,
      });
      setArmed(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleDisarm() {
    setWorking(true); setError(null);
    try {
      await api.disarmAutoTrade();
      setArmed(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleFireNow() {
    setWorking(true); setError(null);
    try {
      const res = await api.fireAutoTrade();
      setLastOrderId(res.order_id);
      setArmed(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <Text size={13} weight={600}>Auto-trade mode</Text>

      <div className={styles.modeRow}>
        {(Object.keys(MODE_LABELS) as AutoTradeMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`${styles.modeBtn} ${autoMode === m ? styles.modeBtnActive : ''}`}
            onClick={() => setAutoMode(m)}
            disabled={armed}
          >
            <Text size={12}>{MODE_LABELS[m]}</Text>
          </button>
        ))}
      </div>

      {autoMode === 'armed' && (
        <div className={styles.armRow}>
          {!armed ? (
            <button type="button" className={`${styles.btn} ${styles.btnArm}`}
              onClick={handleArm} disabled={!broker || working}>
              {working ? 'Arming…' : `Arm — ${card.symbol} ${card.direction}`}
            </button>
          ) : (
            <>
              <StatusBadge status="CAUTION" />
              <Text size={12} tone="caution">Armed — waiting for next trigger</Text>
              <button type="button" className={styles.btn} onClick={handleDisarm} disabled={working}>
                Disarm
              </button>
              <button type="button" className={styles.btn} onClick={handleFireNow} disabled={working}>
                Fire now
              </button>
            </>
          )}
        </div>
      )}

      {autoMode === 'post_scan' && (
        <Text size={11} tone="secondary">
          The system will automatically place this trade when the next scan completes with a PASS candidate.
          Run or schedule a scan to activate.
        </Text>
      )}

      {lastOrderId && (
        <Text size={12} tone="pass">Auto-trade fired — Order ID: {lastOrderId}</Text>
      )}
      {error && <Text size={12} tone="reject">{error}</Text>}
    </div>
  );
}
