'use client';

import { useEffect, useState } from 'react';
import { Text } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAutoTradeStore, type AutoTradeMode } from '@/lib/autoTradeStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import { premiumStopPctFromDollars } from '@/lib/barrierRace';
import { armPickedFieldsFrom } from '@/lib/cardEdits';
import { checkInvalidation, MISSING_INVALIDATION_TITLE, checkMethodPick, MISSING_METHOD_PICK_TITLE } from '@/lib/risk';
import type { TradeCardData, MethodPick } from '@/types/domain';
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
   *  this is auto-trade's own existing design, out of scope to change here.
   *
   *  PHASE G PIECE 5, BUILD STEP 5 (§8): the METHOD PICK is captured at arm on
   *  exactly the same terms, and it is the same sentence for the same reason —
   *  `handleArm` posts `methodPick` below, `fire_now()` takes no body, so a
   *  later change on the card does not retroactively change what "Fire now"
   *  records. Q2 ("the pick is frozen at arm time") is this behaviour, not a
   *  new one added for it. */
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
   *  There is no invalidation counterpart in the REQUEST because the arm
   *  request carries no stop level: `/auto-trade/arm` books entry, size and
   *  premium stop only, and the auto-trader places no protective order (see the
   *  daily-loss-gate note in PROJECT_STATE.json's open questions). What the card
   *  does have to say about its stop is `resolvedInvalidation` below, and that
   *  is a GATE, not a payload. */
  entryLimit?: number | null;
  /** DIRECT-SEND-STOP-GATE-2026-09-09 -- the stop the card is SHOWING, resolved
   *  by the caller exactly as every send path resolves it (step 7's
   *  `invalidationFor`: the user's typed value when the Invalidation field is
   *  touched, else the card's own). Null means the card has no stop, and arming
   *  is refused.
   *
   *  Why this control needs the check at all, given it sends no stop and books
   *  no position: because the OTHER four paths now refuse such a card. A gate on
   *  Place Limit, Right Now — Market and the basket, with Arm left open beside
   *  them, does not close the hole -- it relabels it, and puts the way around
   *  the refusal directly under the refusal. It is also the worse door of the
   *  two: an auto-trade fill creates no PortfolioPosition at all, so a card with
   *  no stop armed here yields a filled order carrying no stop, no premium stop
   *  and no time stop, which is the caution already printed below this button.
   *
   *  `undefined` (the default) falls back to `card.exit.invalidation`, matching
   *  `checkTradeRisk`'s `resolvedInvalidation` contract verbatim -- the same
   *  meaning for the same word, so a caller with no overlay to consult can omit
   *  it and still be gated on something real. */
  resolvedInvalidation?: number | null;
  /** Phase G piece 5, build step 4 (§7.1) — the trader's explicit method pick
   *  for this card, resolved by the caller exactly as step 7's `methodPickFor`
   *  does (keyed by contract through `editKeyFor`). Unlike `resolvedInvalidation`
   *  there is no card-level fallback to fall back to: `MethodPick` is not a
   *  field `TradeCardData` carries (§9.4), so `undefined`/`null` both mean "no
   *  pick" rather than "inherit the card's own value".
   *
   *  Why this control needed the check at the time step 4 added it, BEFORE §8
   *  wired the pick onto the arm request: the same reasoning
   *  `resolvedInvalidation`'s doc gives — a gate on the other paths with Arm
   *  left open does not close the hole, it relabels it.
   *
   *  BUILD STEP 5 HAS SINCE WIRED IT. The same value this gates on is now also
   *  POSTED, through `armPickedFieldsFrom` in `handleArm` below, so the prop
   *  has two jobs rather than one and they read the same field. It is still
   *  the gate that makes the payload reliable and not the other way round:
   *  `pickMissing` early-returns above the request, so the all-null shape the
   *  mapping can produce is unreachable from this button. */
  methodPick?: MethodPick | null;
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

export function AutoTradeArm({ card, broker, contracts = 1, premiumStopDollar = null, entryLimit = null, liveMid = null, resolvedInvalidation, methodPick = null }: AutoTradeArmProps) {
  const { autoMode, setAutoMode, armed, armedDirection, applyArmedStatus,
          lastOrderId, setLastOrderId } = useAutoTradeStore();
  const [working, setWorking] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.getAutoTradeStatus()
      .then((status) => {
        if (!active) return;
        // ONE call: `armed` and its direction are a single fact from a single
        // response and must never be observable half-applied. The store no
        // longer exposes a way to set either alone.
        //
        // The direction is the BACKEND's, deliberately NOT `card.direction`.
        // ROUND 1 finding 6: direction now decides position size and the armed
        // window was the one place that fact was invisible. Echoing the card
        // would only ever redisplay what this component sent, which cannot
        // disagree and so cannot catch anything; the server's value can.
        applyArmedStatus(status.armed, status.direction);
        if (status.armed) setAutoMode('armed');
      })
      .catch(() => {
        // Keep the safe local defaults when the backend is unavailable.
      });
    return () => {
      active = false;
    };
  }, [applyArmedStatus, setAutoMode]);

  // ONE premium, read once: it is both what the arm request books as the
  // entry and the denominator the premium-stop fraction is derived against.
  // LIVE FIRST -- see the `liveMid` prop doc. The scan-time mid stays as the
  // fallback for when no quote has been fetched.
  const entryPremium =
    (liveMid != null && liveMid > 0 ? liveMid : null)
    ?? card.contractDetails?.mid ?? entryLimit ?? card.entry.limit;

  /* DIRECT-SEND-STOP-GATE-2026-09-09 -- see the `resolvedInvalidation` prop
   * doc. `??` and not `!== undefined`, so this reads the card by the same rule
   * `checkTradeRisk` does; both collapse to the same answer here (the caller's
   * resolution already falls back to the card, so a null out of it means the
   * card is null too) and matching the established idiom is worth more than a
   * second, subtly different one. */
  const stopMissing = !checkInvalidation(resolvedInvalidation ?? card.exit.invalidation);
  /* Phase G piece 5, build step 4 (§7.1) — same treatment `stopMissing` gets,
   * one prop along. No card-level fallback exists to `??` against (see the
   * `methodPick` prop doc), so this reads the prop alone. */
  const pickMissing = !checkMethodPick(methodPick);
  /* NOTE: the disclosure is the CALLER'S, not this component's, and that is a
   * choice rather than an omission. Rendering the refusal sentence here too put
   * it on screen TWICE in one column -- step 7 already prints it a few rows
   * above, under the two direct buttons it also gates, and this control sits
   * inside that same panel. Two identical sentences stacked in one section make
   * the refusal easier to skim past, not harder. What stays here is the part
   * that cannot be delegated: the check itself, the `disabled`, and the
   * `title`. A second call site that does not print the sentence would leave a
   * greyed Arm button unexplained -- there is exactly one today, and it prints
   * it. */

  const contractId = card.contract;
  // NOTE: option_symbol should be OCC format for real broker APIs; card.contract is
  // Bamendjou's display id. OCC conversion is a tracked follow-up — passed as-is for now.

  async function handleArm() {
    if (!broker) return;
    // Belt and braces beside the button's own `disabled`, on the same reading
    // of the same value -- an invariant on the function that submits the arm
    // request, not a second chance at a race it could not lose. Same shape as
    // step 7's two direct handlers and SendToBrokerDialog.submit(): `disabled`
    // protects the button, this protects the REQUEST.
    if (stopMissing) return;
    // Phase G piece 5, build step 4 (§7.1) — same belt-and-braces shape as
    // the check immediately above, on the same reading `pickMissing` was
    // derived from.
    if (pickMissing) return;
    setWorking(true); setError(null);
    try {
      await api.armAutoTrade({
        broker,
        symbol:          card.symbol,
        option_symbol:   contractId,
        // Still BUY, and still correct -- but it no longer implies BULLISH. A
        // long single-leg option is always buy-to-open whether it is a call or
        // a put, so `action` carries no directional meaning at all.
        action:          'BUY',
        // The card's own direction, carried so the backend sizes the trade off
        // the matching conviction frame. NOT `card.direction ?? 'Bullish'`:
        // `TradeCardData.direction` is required, and a fallback here would
        // typecheck while silently reinstating the defect this closes.
        direction:       card.direction,
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
        // Phase G piece 5, build step 5 (§8) — the pick, frozen at arm. SPREAD,
        // not five hand-written keys, and snake_case rather than the portfolio
        // path's camelCase: see `armPickedFieldsFrom`'s own doc for why the two
        // mappings exist separately.
        //
        // Reached only with a pick in hand: `pickMissing` above early-returns
        // before this line, so in practice the all-null shape is unreachable
        // from this button. It is still spelled explicitly rather than
        // conditionally spread, because "no pick" is a real state on this
        // endpoint (a pre-G client, a direct API call) and the schema must go on
        // accepting it as one.
        ...armPickedFieldsFrom(methodPick ?? null),
      });
      // `card.direction` is the right value HERE and only here: the arm POST
      // above carried exactly it and the server accepted it, so this is the
      // confirmed armed direction rather than an unverified echo. The effect
      // above still overwrites it with the server's own value on next read.
      applyArmedStatus(true, card.direction);
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
      // Clears the direction with it -- a stale direction on a disarmed
      // trader is the half-state this action exists to make impossible.
      applyArmedStatus(false, null);
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
      applyArmedStatus(false, null);
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
              onClick={handleArm} disabled={!broker || working || stopMissing || pickMissing}
              title={
                stopMissing ? MISSING_INVALIDATION_TITLE
                : pickMissing ? MISSING_METHOD_PICK_TITLE
                : undefined
              }>
              {working ? 'Arming…' : `Arm — ${card.symbol} ${card.direction}`}
            </button>
          ) : (
            <>
              <StatusBadge status="CAUTION" tooltip="Auto-trade is armed — the next matching signal will submit a live order automatically. Always CAUTION while armed, regardless of scan status, because unattended execution carries elevated risk." />
              <Text size={12} tone="caution">
                {armedDirection
                  ? `Armed ${card.symbol} ${armedDirection} — waiting for next trigger`
                  : 'Armed — waiting for next trigger'}
              </Text>
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
