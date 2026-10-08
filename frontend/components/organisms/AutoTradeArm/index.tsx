'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Text } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfirmDialog } from '@/components/molecules/ConfirmDialog';
import { useAutoTradeStore, type AutoTradeMode } from '@/lib/autoTradeStore';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { sanitizeHoldDays, scoringHorizonFromLabel } from '@/lib/horizonPresets';
import { regimeGateFromCard, MISSING_REGIME_GATE_SNAPSHOT_TITLE } from '@/lib/regimeGateOverrides';
import { api } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { armBookingFieldsFrom, classifyFireFailure } from '@/lib/armBookingFields';
import { tradeCardSnapshotOf } from '@/lib/tradeCardSnapshot';
import { premiumStopPctFromDollars } from '@/lib/barrierRace';
import { premiumStopIsSubCent } from '@/lib/premiumStop';
import { armPickedFieldsFrom } from '@/lib/cardEdits';
import { checkInvalidation, MISSING_INVALIDATION_TITLE, checkMethodPick, MISSING_METHOD_PICK_TITLE } from '@/lib/risk';
import type { TradeCardData, MethodPick, ExitPlan, MaxLossOverride } from '@/types/domain';
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
   *  The invalidation stop travels separately, as `stop` (O4 step 6): see
   *  `resolvedInvalidation` below, which is both the gate and that payload. The
   *  auto-trader still places no protective order AT THE BROKER; the stop is
   *  booked on the position, where the alert engines read it. */
  entryLimit?: number | null;
  /** DIRECT-SEND-STOP-GATE-2026-09-09 -- the stop the card is SHOWING, resolved
   *  by the caller exactly as every send path resolves it (step 7's
   *  `invalidationFor`: the user's typed value when the Invalidation field is
   *  touched, else the card's own). Null means the card has no stop, and arming
   *  is refused.
   *
   *  SINCE O4 STEP 6 IT IS ALSO THE PAYLOAD: `handleArm` posts this same value
   *  (one local, `armedStop`) as `stop`, and a fired trade is booked with it.
   *  The gate is still needed, now for a sharper reason: the booking REFUSES a
   *  strategy with no stop (backend `book_fired_order`), and it refuses AFTER
   *  the broker order is live -- so a stopless card armed here would place a
   *  real order that no position records, and page "not booked". Refusing at
   *  arm costs no order. It also keeps Arm from being the way around the same
   *  refusal on Place Limit, Right Now — Market and the basket.
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
   *  `_check_daily_loss` sizes the full premium `entry_premium * quantity *
   *  100` off it (since A6; the declared stop no longer enters that gate).
   *  Scanned at $2.50 and reopened at $6.00, the daily-loss gate booked 2.4x
   *  less risk than the trade carries and a $1.00 stop armed at 40% instead of
   *  17%, with "Live mid: $6.00" on screen a few rows below.
   *
   *  Null/undefined falls back to the scan-time mid, which is all that was
   *  ever available before. */
  liveMid?: number | null;
  /** O4 step 6 — the pipe-form option id (`SYM|STRIKE|YYYY-MM-DD|R`), resolved
   *  at the call site by the SAME `toOptionSymbol(card)` the card path books
   *  under. It is posted as `option_symbol`, which is both what the broker
   *  adapter receives and the `contract` the fired trade is booked as -- a
   *  unique column, and the key the premium-stop and time-stop alerts parse.
   *  REQUIRED: `card.contract` is a different expression, and two spellings of
   *  one option would be two rows.
   *
   *  (It is Bamendjou's id, not OCC; the adapters convert. OCC at the wire is a
   *  tracked follow-up, spec §9.5.) */
  optionSymbol: string;
  /** O4 step 6 — whether the stop was TYPED on the card (step 7's
   *  `invalidationIsUserSetFor`). The booking re-anchors a plan-derived stop by
   *  (live price - scan price) and must not move a typed one; "absent" reads as
   *  not typed, so this is REQUIRED rather than defaulted. */
  stopIsUserSet: boolean;
  /** O4 step 6 — booked as the position's `structural_stop`. Step 7's
   *  `structuralBySymbol[symbol]?.stop?.price`, as `buildPaperPosition`. */
  structuralStop?: number | null;
  /** O4 step 6 — booked as the position's `exit_plan`. Step 7's
   *  `exitPlanFor(card)`, the same helper `buildPaperPosition` calls. */
  exitPlan?: ExitPlan | null;
  /** O4 step 6 — booked as the position's `max_loss_override`. Step 7's
   *  `maxLossOverrideBySymbol[symbol]`, as `buildPaperPosition`. */
  maxLossOverride?: MaxLossOverride | null;
  /** Task 10c (Kenneth, 2026-10-03) — non-null refuses Arm and Fire now on
   *  this card, with this sentence as the buttons' `title`. Step 7 passes the
   *  earnings-veto message for a vetoed card. It used to HIDE the whole
   *  component instead, which also hid Disarm for a strategy already armed;
   *  Disarm is never refused on it.
   *
   *  Fire now is refused only when the armed trade is THIS card's symbol (or
   *  the server did not say which symbol is armed): it fires the armed
   *  strategy, not the card on screen, so another symbol's arm is not this
   *  card's veto to block. The backend fire refuses a vetoed trade anyway.
   *
   *  Audit round 1, F8: step 7 also passes a reason for a SINGLE STOCK whose
   *  earnings date is unknown (`lib/earningsGate.ts`) -- the backend's fire
   *  would refuse every fire of it, so the Arm is refused up front. Same
   *  rules: Disarm stays reachable, Fire now follows the symbol rule above.
   *
   *  Like the regime-gate refusal, the sentence itself is printed by the
   *  CALLER (step 7 shows it beside the direct buttons in the same panel), so
   *  it is not repeated here. */
  armBlockedReason?: string | null;
}

const MODE_LABELS: Record<AutoTradeMode, string> = {
  manual:    'Manual — I press the button',
  post_scan: 'After scan — fire when next scan finds a PASS',
  armed:     'Armed — fire on next qualifying condition',
};

export function AutoTradeArm({ card, broker, contracts = 1, premiumStopDollar = null, entryLimit = null, liveMid = null, resolvedInvalidation, methodPick = null,
                               optionSymbol, stopIsUserSet, structuralStop = null, exitPlan = null, maxLossOverride = null,
                               armBlockedReason = null }: AutoTradeArmProps) {
  const { autoMode, setAutoMode, armed, armedDirection, armedSymbol, applyArmedStatus,
          lastOrderId, setLastOrderId } = useAutoTradeStore();
  const [working, setWorking] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  /** What the last "Fire now" says about its BOOKING (O4 step 6) -- a caution,
   *  not an error: either the request succeeded and the record did not, or the
   *  outcome is unknown. Local, not persisted; the backend's Gmail/Telegram
   *  page is the durable channel. */
  const [fireNote, setFireNote] = useState<string | null>(null);
  /** P2-18(b) -- whether the last Fire now was booked. `false` recolours the
   *  order-id line as a caution; null/true keep the old line. Local, like
   *  `fireNote`. */
  const [lastFireBooked, setLastFireBooked] = useState<boolean | null>(null);
  // R3-7 -- the browser's copy of the GLOBAL premium stop.
  const globalPremiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  /** The held position a pending Arm would duplicate (yaml plan §9.10: warn,
   *  do not block). Non-null renders the confirmation dialog. */
  const [dupWarning, setDupWarning] = useState<{ contracts: number; entryPrice: number } | null>(null);

  // Monotonic counter guarding against a STALE status response. ROUND 2
  // finding 3 demonstrated the hazard: a read issued on mount that resolves
  // AFTER the user has armed used to apply its `armed: false` over the fresh
  // `armed: true`, showing an "Arm" button while the backend was armed and
  // would fire on the next trigger. The old `active` flag guarded UNMOUNT,
  // which is a different race and does not cover this one. Every local
  // armed-state change bumps this, so a read issued before it is discarded on
  // arrival instead of overwriting newer truth with older.
  const statusSeq = useRef(0);

  const refreshStatus = useCallback(async () => {
    const seq = statusSeq.current;
    try {
      const status = await api.getAutoTradeStatus();
      if (seq !== statusSeq.current) return;   // superseded while in flight
      // ONE call: `armed`, its direction and its symbol are a single fact from
      // a single response and must never be observable half-applied. The store
      // exposes no way to set any of them alone.
      //
      // These are the BACKEND's values, deliberately NOT the card's. ROUND 1
      // finding 6: direction now decides position size and the armed window was
      // the one place that fact was invisible. Echoing the card would only
      // redisplay what this component sent, which cannot disagree with itself
      // and so could never catch a mis-arm; the server's value can.
      applyArmedStatus(status.armed, status.direction, status.symbol);
      if (status.armed) setAutoMode('armed');
    } catch {
      // Keep the safe local defaults when the backend is unavailable.
    }
  }, [applyArmedStatus, setAutoMode]);

  useEffect(() => { void refreshStatus(); }, [refreshStatus]);

  // Step 7 swaps `card` without remounting this component. A duplicate
  // warning raised for one contract must not survive onto another, or "Arm
  // anyway" would arm a card nobody was warned about -- and skip that card's
  // own duplicate check.
  useEffect(() => { setDupWarning(null); }, [optionSymbol]);

  // ONE premium, read once: it is both what the arm request books as the
  // entry and the denominator the premium-stop fraction is derived against.
  // LIVE FIRST -- see the `liveMid` prop doc. The scan-time mid stays as the
  // fallback for when no quote has been fetched.
  const entryPremium =
    (liveMid != null && liveMid > 0 ? liveMid : null)
    ?? card.contractDetails?.mid ?? entryLimit ?? card.entry.limit;

  /* P2-18(a) (R1-18, R2-4) -- a typed dollar stop at or above today's premium
   * is not sent as a fraction (premiumStopPctFromDollars refuses >= 1), so the
   * arm carries only the dollar, and the booking derives it against the FILL.
   * Say what that means before arming. */
  const premiumStopAtOrAbovePremium = premiumStopDollar != null
    && entryPremium > 0 && premiumStopDollar >= entryPremium;

  /* STOP-SEMANTICS-2026-10-02 (F3, decision Q3) -- a typed stop whose
   * threshold is below $0.01 at today's premium can never fire. A WARNING, not
   * a disable, for the same reason as its total-loss sibling above: the fill
   * decides, and the booking (create_position) refuses to store a sub-cent
   * stop at the filled entry and inherits the global instead. Options only,
   * so the short flag is false. */
  const premiumStopSubCent = premiumStopDollar != null
    && entryPremium > 0 && premiumStopDollar > 0 && premiumStopDollar < entryPremium
    && premiumStopIsSubCent(entryPremium, premiumStopDollar / entryPremium, false);

  /* DIRECT-SEND-STOP-GATE-2026-09-09 -- see the `resolvedInvalidation` prop
   * doc. `??` and not `!== undefined`, so this reads the card by the same rule
   * `checkTradeRisk` does; both collapse to the same answer here (the caller's
   * resolution already falls back to the card, so a null out of it means the
   * card is null too) and matching the established idiom is worth more than a
   * second, subtly different one. */
  const armedStop = resolvedInvalidation ?? card.exit.invalidation;
  // O4 step 6: `armedStop` is ALSO what `handleArm` posts as `stop`. One
  // reading for the gate and the wire, so the button cannot be enabled on one
  // number while the booking is armed with another.
  const stopMissing = !checkInvalidation(armedStop);
  /* Phase G piece 5, build step 4 (§7.1) — same treatment `stopMissing` gets,
   * one prop along. No card-level fallback exists to `??` against (see the
   * `methodPick` prop doc), so this reads the prop alone. */
  const pickMissing = !checkMethodPick(methodPick);
  /* The regime-gate rule this card's scan resolved, or null when the card
   * predates the snapshot. Null REFUSES the arm: falling back to the live
   * Step-3 store would re-open arm-door round 1's F1, since that store need
   * not hold what this card's scan was run with. Unlike the two checks above,
   * no caller prints a sentence for this one, so this component does. */
  const regimeGate = regimeGateFromCard(card);
  const gateSnapshotMissing = regimeGate === null;
  /* Task 10c -- see the `armBlockedReason` prop doc. Fire now is blocked only
   * when the armed trade is this card's (or the server named no symbol). */
  const armBlocked = armBlockedReason != null;
  const fireBlocked = armBlocked && (armedSymbol == null || armedSymbol === card.symbol);
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

  /** `confirmedDuplicate` is an ARGUMENT, not state: "Arm anyway" calls this in
   *  the same tick as it closes the dialog, and a state flag read here would
   *  still be the stale `false`, re-opening the dialog forever. */
  async function handleArm(confirmedDuplicate = false) {
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
    // Same belt-and-braces shape, on the same reading `gateSnapshotMissing`
    // was derived from. Also narrows `regimeGate` for the spread below.
    if (regimeGate === null) return;
    // Task 10c: same belt-and-braces shape, on the same reading `armBlocked`
    // was derived from.
    if (armBlocked) return;
    // Yaml plan §9.10 (Kenneth, 2026-09-17): arming into a contract already
    // held WARNS, it does not block. Checked here, at arm, because this is the
    // one moment a human consents for BOTH triggers -- the scan trigger fires
    // unattended. Matched on the exact string the booking uses as its unique
    // key, so "the dialog said held" and "the booking will refuse it as a
    // duplicate" are the same test. `positions` is this tab's store (persisted,
    // plus the sync at mount), so a position opened elsewhere since may be
    // missed; the booking's refusal and its alert still catch that.
    if (!confirmedDuplicate) {
      const held = usePortfolioStore.getState().positions.find((p) => p.contract === optionSymbol);
      if (held) {
        setDupWarning({ contracts: held.contracts ?? 1, entryPrice: held.entryPrice });
        return;
      }
    }
    setDupWarning(null);
    setWorking(true); setError(null); setFireNote(null);
    try {
      const context = useScanStore.getState().context;
      const { hold_max_days } = sanitizeHoldDays(context?.holdMin ?? 0, context?.holdMax ?? 0);
      await api.armAutoTrade({
        broker,
        symbol:          card.symbol,
        option_symbol:   optionSymbol,
        // Still BUY, and still correct -- but it no longer implies BULLISH. A
        // long single-leg option is always buy-to-open whether it is a call or
        // a put, so `action` carries no directional meaning at all.
        action:          'BUY',
        // The card's own direction, carried so the backend sizes the trade off
        // the matching conviction frame. NOT `card.direction ?? 'Bullish'`:
        // `TradeCardData.direction` is required, and a fallback here would
        // typecheck while silently reinstating the defect this closes.
        direction:       card.direction,
        // ── The regime gate's inputs, frozen at arm ─────────────────────────
        // AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19. The backend
        // measures THIS SYMBOL's own regime at fire time instead of reading a
        // cached market-wide SPX number, and these two fields tell it WHICH
        // measurement and BY WHAT RULE — so a refusal is the scan's own verdict
        // on this setup rather than a different question with the same name.
        //
        // Read from the store at SUBMIT time, not from a render-time snapshot:
        // this is the same `getState()` shape `portfolio_value` below already
        // uses, and for the same reason — the value that matters is the one in
        // force when the trade is armed.
        //
        // `scoringHorizonFromLabel` and not `context.horizon.split(' ')[0]`:
        // the context string is a display form ("Position (90–105d)"), and the
        // label helper is the one place that mapping is defined. A null context
        // (nothing scanned this session) falls back to the helper's own default
        // rather than to a literal written here.
        horizon:         scoringHorizonFromLabel(context?.horizon),
        hold_max_days,
        // The thresholds THIS CARD'S SCAN RESOLVED, off the card itself --
        // NOT the live Step-3 store. Arm-door round 1, F1: `scanOverrides` is
        // not persisted and survives a threshold edit or "Reset to defaults"
        // without invalidating the scan, so reading it here armed the trade
        // under whatever Step 3 said at submit time. Decision
        // AUTOTRADE-ARMED-TRADE-JUDGED-BY-ITS-SCANS-RULE-2026-09-21: an armed
        // trade is judged by the rule its own scan ran under. Absent keys stay
        // absent: the resolved block had none, so the scan read the YAML.
        ...regimeGate,
        // Floored defensively: `contracts` comes from the shared per-symbol
        // Contracts map (Feature 7), which a caller could in principle write
        // a sub-1 value into (e.g. Feature 3's Apply button before its own
        // clamp/disable) — 0 would otherwise reach the backend, which
        // rejects quantity:0 with an opaque 422 that gives no clue this is
        // where it came from.
        quantity:        Math.max(1, contracts),
        order_type:      'LMT',
        // Audit round 1, F1: BOTH travel and both matter. `entry_premium` is
        // the mid the position books; the fire-time cap check judges
        // max(entry_premium, limit_price) -- what this LMT order can pay --
        // in `AutoTradeService._check_exposure` (portfolio_risk.premium_cap_basis).
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
        // O4 step 6 — the ten booking fields, so a fired trade books its
        // position (backend `book_fired_order`). Frozen at arm like everything
        // above: "Fire now" posts no body, so a later card edit does not change
        // what the armed trade books. `stop` is `armedStop`, the value the
        // stop gate above read.
        ...armBookingFieldsFrom({
          stop:              armedStop,
          stopIsUserSet,
          scanStockPrice:    card.price,
          structuralStop,
          exitPlan,
          targets:           card.exit.targets,
          dteTotal:          card.contractDetails?.dte,
          premiumStopDollar,
          maxLossOverride,
          tradeCardSnapshot: tradeCardSnapshotOf(card),
        }),
      });
      // Invalidate any status read still in flight (ROUND 2 finding 3) before
      // publishing the new state, so a stale `armed: false` cannot land on top.
      statusSeq.current += 1;
      // Optimistic, and explicitly provisional: the POST above carried exactly
      // these values and the server accepted them, so they are the best guess
      // until the server speaks for itself.
      applyArmedStatus(true, card.direction, card.symbol);
      // ...which it now does. ROUND 2 finding 4: the mount effect's deps are
      // referentially-stable store actions, so it runs ONCE per mount and never
      // re-reads. Without this line the armed label showed `card.direction` on
      // the one path that matters -- the user having just armed -- while both
      // the comments and the tests claimed it showed the backend's. Now it does.
      void refreshStatus();
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleDisarm() {
    setWorking(true); setError(null); setFireNote(null);
    try {
      await api.disarmAutoTrade();
      statusSeq.current += 1;
      // Clears direction and symbol with it -- a stale pair on a disarmed
      // trader is the half-state this action exists to make impossible.
      applyArmedStatus(false, null, null);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function handleFireNow() {
    // Task 10c: belt and braces beside the button's own `disabled`.
    if (fireBlocked) return;
    setWorking(true); setError(null); setFireNote(null);
    try {
      const res = await api.fireAutoTrade();
      setLastOrderId(res.order_id);
      setLastFireBooked(res.booked === false ? false : res.booked === true ? true : null);
      statusSeq.current += 1;
      applyArmedStatus(false, null, null);
      // O4 steps 4+5: the server books the position, so its answer is read
      // here. `=== false`, never `!res.booked`: a backend predating the key
      // omits it, and "not reported" is not "not booked".
      if (res.booked === false) {
        // No "order placed" in the lead: two of the backend's refusals are
        // exactly the cases where the broker's answer reads as NOT live, and
        // `book_error` says which.
        setFireNote(
          `No position was recorded for this fire: ${res.book_error ?? 'no reason given'}. `
          + 'Nothing is watching its stop. Check the broker, then record or adjust the position on the Portfolio page.',
        );
      } else if (res.booked === true) {
        if (res.over_exposure === true) {
          setFireNote(
            `Booked as ${res.rec_id ?? 'a new position'} at the ordered size, which is past your exposure limit. `
            + 'Nothing was resized — the portfolio matches the broker.',
          );
        }
        // Written server-side, so without this pull the position is invisible
        // here and on the Portfolio page until something else syncs.
        void usePortfolioStore.getState().syncFromBackend(true);
      }
    } catch (e) {
      if (classifyFireFailure(e) === 'refused') {
        setError(String(e));
        // Re-read, never assume (open_questions[98]): most refusals land AFTER
        // the backend's disarm, so the panel went on showing "Armed" and a
        // second press got "not armed" -- but a market-closed / re-armed
        // refusal PRESERVES the arm, so clearing it locally would be wrong the
        // other way. The bump makes this read the only one that can apply: an
        // older read still in flight (the mount read) carries the old seq and
        // would otherwise land its pre-fire `armed: true` on top.
        statusSeq.current += 1;
        void refreshStatus();
      } else {
        // UNKNOWN, not failed: the broker call may have been made (see
        // classifyFireFailure). Never a plain error inviting a second press.
        // The status read settles whether THIS request took the armed slot
        // (still armed -> it did not fire); the sync shows a booking if one
        // was made.
        setFireNote(
          'The fire request did not return a result — the order may or may not have been placed. '
          + 'Check the broker and your portfolio before firing again.',
        );
        statusSeq.current += 1;   // same reason as the refused branch above
        void refreshStatus();
        void usePortfolioStore.getState().syncFromBackend(true);
      }
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
              onClick={() => { void handleArm(); }} disabled={!broker || working || armBlocked || stopMissing || pickMissing || gateSnapshotMissing}
              title={
                // The veto wins, as on step 7's direct buttons: filling a
                // field cannot cure it.
                armBlocked ? (armBlockedReason as string)
                : stopMissing ? MISSING_INVALIDATION_TITLE
                : pickMissing ? MISSING_METHOD_PICK_TITLE
                : gateSnapshotMissing ? MISSING_REGIME_GATE_SNAPSHOT_TITLE
                : undefined
              }>
              {working ? 'Arming…' : `Arm — ${card.symbol} ${card.direction}`}
            </button>
          ) : (
            <>
              <StatusBadge status="CAUTION" tooltip="Auto-trade is armed — the next matching signal will submit a live order automatically. Always CAUTION while armed, regardless of scan status, because unattended execution carries elevated risk." />
              <Text size={12} tone="caution">
                {/* BOTH names come from the server, or neither does. ROUND 2
                    finding 2: pairing the server's direction with the local
                    `card.symbol` produced a confidently wrong sentence --
                    step-7 renders this component with no `key`, so stepping
                    through candidates swaps `card` without remounting, and the
                    panel would assert "Armed TSLA Bullish" for a trade armed on
                    AAPL, Disarm button beside it. */}
                {armedSymbol && armedDirection
                  ? `Armed ${armedSymbol} ${armedDirection} — waiting for next trigger`
                  : 'Armed — waiting for next trigger'}
              </Text>
              <button type="button" className={styles.btn} onClick={handleDisarm} disabled={working}>
                Disarm
              </button>
              <button type="button" className={styles.btn} onClick={handleFireNow} disabled={working || fireBlocked}
                title={fireBlocked ? (armBlockedReason as string) : undefined}>
                Fire now
              </button>
            </>
          )}
        </div>
      )}

      {autoMode === 'armed' && !armed && premiumStopAtOrAbovePremium && (
        <Text size={11} tone="caution">
          {`Your $${(premiumStopDollar as number).toFixed(2)} premium stop is at or above today's `
            + `$${entryPremium.toFixed(2)} premium. If the fill is at or below `
            + `$${(premiumStopDollar as number).toFixed(2)}, the booked position inherits the global stop `
            + `(${Number((globalPremiumStopPct * 100).toFixed(2))}%); above it, your `
            + `$${(premiumStopDollar as number).toFixed(2)} stop applies.`}
        </Text>
      )}

      {autoMode === 'armed' && !armed && premiumStopSubCent && (
        <Text size={11} tone="caution">
          {`Your $${(premiumStopDollar as number).toFixed(2)} premium stop leaves a threshold below $0.01 `
            + `at today's $${entryPremium.toFixed(2)} premium, so it could never fire. If it is still below `
            + `$0.01 at the fill, the booked position inherits the global stop `
            + `(${Number((globalPremiumStopPct * 100).toFixed(2))}%).`}
        </Text>
      )}

      {autoMode === 'armed' && !armed && gateSnapshotMissing && (
        <Text size={11} tone="caution">{MISSING_REGIME_GATE_SNAPSHOT_TITLE}</Text>
      )}

      {(autoMode === 'armed' || autoMode === 'post_scan') && (
        // Round 7 finding 16 said here that an auto-trade fill books no
        // position. O4 steps 4-6 changed that: the fire books a
        // PortfolioPosition server-side from the fields `handleArm` captured,
        // so STOP_REACHED, PREMIUM_STOP and TIME_STOP arm on it as they do for
        // Place Limit. What still differs is said on screen: the values are the
        // card's AT ARM (a later edit does not reach an armed trade), and a
        // booking can be refused after the order is live.
        <Text size={11} tone="caution">
          When an auto-trade fires, it is booked as a position with the invalidation you typed, or the
          plan&apos;s invalidation moved with the stock price at booking, and the premium stop and exit plan
          this card had when you armed it — later edits do not change an armed trade. If the booking is
          refused you will see it here (Fire now) and get an alert (Gmail/Telegram, if set up).
        </Text>
      )}

      {autoMode === 'post_scan' && (
        <Text size={11} tone="secondary">
          The system will automatically place this trade when the next scan completes with a PASS candidate.
          Run or schedule a scan to activate.
        </Text>
      )}

      {lastOrderId && (lastFireBooked === false
        // P2-18(b) -- never the green "fired" line for an order no position
        // records; the fireNote below says why.
        ? <Text size={12} tone="caution">Order sent — ID: {lastOrderId} (not booked)</Text>
        : <Text size={12} tone="pass">Auto-trade fired — Order ID: {lastOrderId}</Text>
      )}
      {error && <Text size={12} tone="reject">{error}</Text>}
      {fireNote && <Text size={12} tone="caution">{fireNote}</Text>}

      {dupWarning && (
        <ConfirmDialog
          title={`You already hold ${optionSymbol}`}
          body={
            `Existing position: ${dupWarning.contracts} contract${dupWarning.contracts === 1 ? '' : 's'} `
            + `at $${dupWarning.entryPrice.toFixed(2)}. Arming will place a second buy-to-open on this contract `
            + 'when it fires. That order will NOT be added to your portfolio (a contract is booked once) — '
            + "you will be alerted, and should adjust the existing position's size by hand."
          }
          confirmLabel="Arm anyway"
          onCancel={() => setDupWarning(null)}
          onConfirm={() => { setDupWarning(null); void handleArm(true); }}
        />
      )}
    </div>
  );
}
