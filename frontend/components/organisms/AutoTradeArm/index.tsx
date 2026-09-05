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
  /** The card's editable Entry limit, sourced at the call site from the same
   *  `entryLimitFor` every send path uses. Null (the default) means the field
   *  was never edited and `card.entry.limit` stands.
   *
   *  Feeds BOTH the posted `limit_price` and `entryPremium` -- the latter only
   *  as the fallback when `contractDetails.mid` is absent, but that fallback is
   *  the premium-stop denominator, so an edited limit that reached one and not
   *  the other would arm the trade at a fraction derived against a price the
   *  order was never placed at.
   *
   *  There is no invalidation counterpart because the arm request carries no
   *  stop level: `/auto-trade/arm` books entry, size and premium stop only, and
   *  the auto-trader places no protective order (see the daily-loss-gate note
   *  in PROJECT_STATE.json's open questions). */
  entryLimit?: number | null;
  /** The live option mid, fetched by the page (`liveQuote?.price`) -- the same
   *  number it already hands TradeCard as `liveMid` and prints as "Live mid".
   *
   *  ROUND 9. `card.contractDetails.mid` is a SCAN-TIME snapshot off a
   *  `scanResult` that `scanStore` persists to localStorage, so after a reload
   *  it can be days old -- the exact staleness round 8 fixed for the card's
   *  own bounds and did not carry to this path. It matters three times over
   *  here: it is booked as `entry_premium`, it is the denominator
   *  `premiumStopPctFromDollars` divides the dollar stop by, and the backend's
   *  `_check_daily_loss` sizes `entry_premium * quantity * 100 * stop_pct` off
   *  it. Scanned at $2.50 and reopened at $6.00, the daily-loss gate booked
   *  2.4x less risk than the trade carries and a $1.00 stop armed at 40%
   *  instead of 17%, with "Live mid: $6.00" on screen a few rows below.
   *
   *  Null/undefined falls back to the scan-time mid, which is all that was
   *  ever available before. */
  liveMid?: number | null;
}

const MODE_LABELS: Record<AutoTradeMode, string> = {
  manual:    'Manual — I press the button',
  post_scan: 'After scan — fire when next scan finds a PASS',
  armed:     'Armed — fire on next qualifying condition',
};

export function AutoTradeArm({ card, broker, contracts = 1, premiumStopDollar = null, entryLimit = null, liveMid = null }: AutoTradeArmProps) {
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
  // LIVE FIRST -- see the `liveMid` prop doc. The scan-time mid stays as the
  // fallback for when no quote has been fetched.
  const entryPremium =
    (liveMid != null && liveMid > 0 ? liveMid : null)
    ?? card.contractDetails?.mid ?? entryLimit ?? card.entry.limit;

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
        limit_price:     entryLimit ?? card.entry.limit,
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

      {(autoMode === 'armed' || autoMode === 'post_scan') && (
        // Round 7 finding 16. An auto-trade FIRE places the broker order and
        // appends a history row -- it creates no PortfolioPosition
        // (auto_trader.fire), so nothing on that path carries a `stop` or a
        // `premium_stop_pct` into the alert engines: no STOP_REACHED, no
        // PREMIUM_STOP, no TIME_STOP. The armed request does send the premium
        // stop, but only as the `premium_at_risk` history figure and the
        // daily-loss-gate denominator.
        //
        // Said on screen because this control sits directly beside Place
        // Limit, which DOES thread all of it, and nothing distinguished them.
        // Both halves were already recorded (this file's own prop docs, the
        // open questions in PROJECT_STATE) -- recorded is not the same as
        // visible to the person pressing the button.
        <Text size={11} tone="caution">
          An auto-trade fill is not tracked as a position: the invalidation and premium stops on the card
          above arm no alerts on this path. Place Limit does thread both.
        </Text>
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
