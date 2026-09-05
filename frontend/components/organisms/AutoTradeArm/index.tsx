'use client';

import { useEffect, useState } from 'react';
import { Text } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAutoTradeStore, type AutoTradeMode } from '@/lib/autoTradeStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import { premiumStopPctFromDollars } from '@/lib/barrierRace';
import type { TradeCardData } from '@/types/domain';
import styles from './AutoTradeArm.module.css';

interface AutoTradeArmProps {
  card: TradeCardData;
  broker: string | null;
  /** Feature 7 — sourced from the page-level shared per-symbol contracts map
   *  at the call site, read only inside handleArm below. Note: handleFireNow
   *  has no quantity to change — it calls api.fireAutoTrade() with an empty
   *  body, and the backend re-fires whatever ArmedStrategy (quantity
   *  included) was captured earlier by /auto-trade/arm. A later Contracts
   *  edit will NOT retroactively change what "Fire now" submits once armed —
   *  this is auto-trade's own existing design, out of scope to change here. */
  contracts?: number;
  /** Piece 4 — the card's premium stop as a DOLLAR loss per share, sourced at
   *  the call site from the same `premiumStopDollarFor` both send paths use, so
   *  arming and sending agree on THE DOLLAR AMOUNT. Null (the default) means
   *  the card's stop was never edited off its seeded value, and the
   *  auto-trader inherits `auto_trade.premium_stop_pct`.
   *
   *  They do NOT necessarily agree on the resulting FRACTION, and this comment
   *  used to claim they did ("cannot arm a position at two different stops").
   *  The two paths anchor the same dollars to different premiums by design:
   *  arming divides by `card.contractDetails.mid` below, while sending posts
   *  dollars and lets `add_position` divide by the persisted entry, which the
   *  router may have replaced with a live quote. $3.12 on a $5.20 mid arms at
   *  0.60 and, on a $4.00 fill, creates the position at 0.78. That
   *  re-anchoring is the point of sending dollars rather than a fraction --
   *  the guarantee is a shared dollar stop, not a shared percentage.
   *
   *  Converted to a fraction HERE rather than at the call site so it is divided
   *  by the very `entry_premium` this component sends. Anchoring it to any
   *  other premium is the bug piece 4's own router fix exists to prevent. */
  premiumStopDollar?: number | null;
}

const MODE_LABELS: Record<AutoTradeMode, string> = {
  manual:    'Manual — I press the button',
  post_scan: 'After scan — fire when next scan finds a PASS',
  armed:     'Armed — fire on next qualifying condition',
};

export function AutoTradeArm({ card, broker, contracts = 1, premiumStopDollar = null }: AutoTradeArmProps) {
  const { autoMode, setAutoMode, armed, setArmed, lastOrderId, setLastOrderId } = useAutoTradeStore();
  const [working, setWorking] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.getAutoTradeStatus()
      .then((status) => {
        if (!active) return;
        setArmed(status.armed);
        if (status.armed) setAutoMode('armed');
      })
      .catch(() => {
        // Keep the safe local defaults when the backend is unavailable.
      });
    return () => {
      active = false;
    };
  }, [setArmed, setAutoMode]);

  // ONE premium, read once: it is both what the arm request books as the
  // entry and the denominator the premium-stop fraction is derived against.
  const entryPremium = card.contractDetails?.mid ?? card.entry.limit;

  const contractId = card.contract;
  // NOTE: option_symbol should be OCC format for real broker APIs; card.contract is
  // Bamendjou's display id. OCC conversion is a tracked follow-up — passed as-is for now.

  async function handleArm() {
    if (!broker) return;
    setWorking(true); setError(null);
    try {
      await api.armAutoTrade({
        broker,
        symbol:          card.symbol,
        option_symbol:   contractId,
        action:          'BUY',   // long single-leg option (call or put) is always buy-to-open
        // Floored defensively: `contracts` comes from the shared per-symbol
        // Contracts map (Feature 7), which a caller could in principle write
        // a sub-1 value into (e.g. Feature 3's Apply button before its own
        // clamp/disable) — 0 would otherwise reach the backend, which
        // rejects quantity:0 with an opaque 422 that gives no clue this is
        // where it came from.
        quantity:        Math.max(1, contracts),
        order_type:      'LMT',
        limit_price:     card.entry.limit,
        entry_premium:   entryPremium,
        // Piece 4 — undefined (omitted) rather than null when the card carries
        // no edited stop: `ArmRequest.premium_stop_pct` is Optional with a None
        // default, and omitting is what "inherit the global" means on that
        // endpoint. premiumStopPctFromDollars already returns undefined for a
        // stop at or above the whole premium, which is a total loss rather
        // than a stop and would fail the schema's `lt=1` bound.
        premium_stop_pct: premiumStopPctFromDollars(premiumStopDollar, entryPremium),
        // Must match the value the frontend's own checkTrade/computeMetrics use, or the
        // frontend and backend exposure/daily-loss gates silently disagree on the same
        // armed trade (see commit 003040c for the same bug in portfolioStore.ts).
        portfolio_value: useRiskStore.getState().limits.portfolioValue,
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
              <StatusBadge status="CAUTION" tooltip="Auto-trade is armed — the next matching signal will submit a live order automatically. Always CAUTION while armed, regardless of scan status, because unattended execution carries elevated risk." />
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
