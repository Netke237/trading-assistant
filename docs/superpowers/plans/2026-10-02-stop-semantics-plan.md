# STOP-SEMANTICS — build plan (v1)

Decision: `STOP-SEMANTICS-2026-10-02` (PROJECT_STATE.json). Task: `task_backlog` STOP-SEMANTICS.
Two behaviour changes, one branch, one plan:

- **(a)** A SHORT stock position's percent stop fires when the price RISES X% above entry.
- **(b)** A premium stop whose threshold is below $0.01 is REFUSED when saved.

Part (c) of the decision (COMPOSITE-WATCH-KEYERROR) is closed, so no code.

---

## 0. Ground truth (read before the plan; every claim below was read on main fa354b5)

### The percent stop is one mechanism for options and stocks

`PREMIUM_STOP` fires on `currentPrice <= entry * (1 - pct)` in BOTH engines:

- frontend `lib/alertEngine.ts` `scanPortfolio`, the `PREMIUM_STOP` block (~L250-315). No `isStock` and no
  `isBearish` term.
- backend `services/alert_generator.py` `generate_alerts`, the `PREMIUM_STOP` block (~L306-357). Same
  comparison via `premium_stop.premium_stop_threshold_price`. For a `|STOCK` contract, `opt_price` is the
  stock quote (market.py stock-format branch).

`pct` is resolved by `resolve_premium_stop_pct(position_pct, global)` (Python) and `resolvePremiumStopPct`
(TS), which are kept as twins. The threshold helper `premiumStopThresholdPrice(entry, pct) = entry * (1 - pct)`
also has twins.

Preview and label sites that state the threshold:
- `EditDrawer.tsx` `alertFiresAgainst` 'PREMIUM_STOP' → `premiumStopFiringPrice(entry, pct)` (the largest 2dp price
  `<=` threshold).
- `EditDrawer.tsx` premium-stop field label: `Stock stop — fires X below entry` for stocks (P2-13), and a comment
  pointing at this open question.
- `EditDrawer.tsx` `subCent` = `premiumStopFiringPrice(...) <= 0` → caution "At this entry the stop threshold is
  below $0.01, so it can never fire." (decision Q-P2-3 warn-only, now superseded).
- `alerts/page.tsx` `alertTypeLabel`: `Premium stop (–X%)`.
- backend reason `Premium stop — SYM stock|option at $P`; frontend reason `Premium stop — SYM down N%`.

**A Bearish OPTION position is a long put. Its premium falls on a loss exactly like a call's, so (a) must not
touch options.** (a) is `|STOCK` AND `direction == 'Bearish'` only.

### Where a per-position premium stop is SAVED (scope of (b))

| # | Path | Value written | Entry known at save? |
|---|---|---|---|
| S1 | `PATCH /api/portfolio/{rec_id}` `premiumStopPct` (routers/portfolio.py `update_position`) | fraction | yes, `position.entry_price` |
| S2 | `POST /api/portfolio` → `position_writer.create_position` from `premiumStopDollar` (ratio = dollar / persisted entry) | fraction | yes, the persisted (possibly live-quote-replaced) entry |
| S3 | same, from a client `premiumStopPct` (auto-trade booking `auto_trade_booking.py:199`, AutoTradeArm `premium_stop_pct`) | fraction | yes |
| F1 | Portfolio `EditDrawer` premium-stop field `commit` (frontend refusal before S1) | fraction | yes |
| F2 | TradeCard premium-stop dollar field, bounded by `premiumStopDollarBounds(mid)` (10–99% of mid) | dollar, sent to S2 | the mid only; the fill can differ |
| F3 | AutoTradeArm arm (sends `premium_stop_pct` from `premiumStopPctFromDollars(dollar, entryPremium)`; booking later goes through S2/S3) | fraction + dollar | the entry premium estimate only |
| G | Settings global `premiumStopPct` (`routers/risk_settings.py`, `ge=0.10 le=0.99`) | fraction | **no — the global has no entry** |

The create path already handles a stop it cannot store. A ratio `>= 1` logs a WARNING, falls back to
`body.premiumStopPct` (usually None → inherit global), and the frontend detects
`premiumStopDollar != null && response.premiumStopPct == null`. It then raises the existing Portfolio banner
"premium stop of $X/share could not be applied at the saved premium — this position inherits the global
stop" (`portfolioStore` `premiumStopDropQueue`, P2-08 / round 9). (b) at S2 reuses that exact signal.

---

## 1. Definitions (one rule, both languages)

```
stopFiresBelow(entry, pct)   = entry * (1 - pct)            # long stock, every option (unchanged)
stopFiresAbove(entry, pct)   = entry * (1 + pct)            # SHORT stock only (new)
isShortStock(contract, dir)  = contract.endsWith('|STOCK') and dir == 'Bearish'
```

New twin helpers, beside the existing ones:

- TS `lib/premiumStop.ts`: `isShortStockPosition(contract, direction)`,
  `percentStopThresholdPrice(entry, pct, shortStock)`, `percentStopFiringPrice(entry, pct, shortStock)`
  (short: the SMALLEST 2dp price `>=` threshold, with the same round-then-step guard as
  `premiumStopFiringPrice` but stepping UP), and `premiumStopIsSubCent(entry, pct)`.
- Python `services/premium_stop.py`: `is_short_stock_position(contract, direction)`,
  `percent_stop_threshold_price(entry, pct, short_stock)`, `premium_stop_is_sub_cent(entry, pct)`.

`premium_stop_threshold_price` / `premiumStopThresholdPrice` stay as they are (long formula). The new
`percent_stop_threshold_price` delegates to them for the long side, so there is one long formula.

**Sub-cent rule (b):** `premium_stop_is_sub_cent(entry, pct) := entry > 0 and entry * (1 - pct) < 0.01`.
This is the backend comparison `opt_price <= threshold` with quotes in whole cents: a threshold under one cent
can only be met by a quote of 0, which both engines treat as "no quote" (`> 0` guard). It fires never.
- TS twin: `premiumStopIsSubCent(entry, pct) := entry > 0 && premiumStopFiringPrice(entry, pct) <= 0`. That is the
  predicate the drawer already uses, so the editor and the warning cannot disagree. A test pins that both
  languages agree on a sweep (entries $0.01–$2.00 by cent × pct 10%–99% by 0.5%) near the boundary
  (`entry*(1-pct)` within 1e-9 of 0.01). Any float disagreement at exactly $0.01 is resolved toward
  "fires" (not sub-cent) in both: Python uses `entry * (1 - pct) < 0.01 - 1e-12`, and the TS step-down already
  treats an exact cent as firing.
- **A short stock is never sub-cent**: its threshold is above entry. Both helpers return False when `short_stock`
  is true. The predicate takes the short flag, so callers cannot apply the long rule to a short.

---

## 2. (a) Direction-aware percent stop for a short stock

### 2.1 Engines (the behaviour change)

- `alertEngine.ts` PREMIUM_STOP block: compute `shortStock = isStock && isBearish`;
  `threshold = percentStopThresholdPrice(entry, pct, shortStock)`;
  `hit = entry > 0 && currentPrice > 0 && (shortStock ? currentPrice >= threshold : currentPrice <= threshold)`.
  Reason text for a short: `Stock stop — SYM up N%` (N = −pnlPct... **no**: `pnlPct` on a short. See 2.4).
  `referenceValue: pythonRound4(threshold)` unchanged in shape.
- `alert_generator.py` PREMIUM_STOP block: same, via `percent_stop_threshold_price(..., short_stock)` and
  `opt_price >= threshold` for a short. `threshold_price` / `reference_value` / event-log payload use the
  direction-aware threshold. Reason: `Premium stop — SYM stock at $P` stays (price-only, true for both sides).
- `_sustained("PREMIUM_STOP", ...)` and `_muted` are unchanged. The sustain counter is keyed per alert type, not
  per side.

### 2.2 Labels and previews

- `EditDrawer` field label: long stock `Stock stop — fires X below entry`, short stock
  `Stock stop — fires X above entry`, option unchanged. Remove the Q-P2-1 "open question" comment.
- `EditDrawer.alertFiresAgainst('PREMIUM_STOP')`: `stock $` + `percentStopFiringPrice(entry, pct, shortStock)`.
- `alerts/page.tsx` `alertTypeLabel`: PREMIUM_STOP on a short stock reads `Stock stop (+X%)`. The toast/row carries
  `direction` and `contract` already. For a long stock it reads `Stock stop (–X%)`, and options keep
  `Premium stop (–X%)`. (Today stocks print "Premium stop", which is a pre-existing mislabel P2-13 fixed only in
  the drawer. Fixing it here is in scope because the sign is now direction-dependent and must be right.)

### 2.3 Not changed by (a)
- `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` / `TP_HIT` are already direction-aware. Untouched.
- The global's meaning (a fraction of entry) is unchanged. A short at 10% now fires at entry × 1.10.
- Option positions of either direction: byte-for-byte unchanged (test pins a Bearish option still fires on a fall).

### 2.4 pnlPct on a short (verify, do not assume)
The frontend reason uses `p.pnlPct`. **Step 0 of the build:** read `routers/portfolio.py` GET and
`portfolioStore.fromBackend` to establish whether `pnlPct` is direction-aware for a Bearish stock (a short
that rose 12% must read −12%). If it is, the short reason is `Stock stop — SYM down N%` with the existing
`pnlPct` (a loss reads "down" on either side). If it is NOT direction-aware, the reason must not use it. Use
`Stock stop — SYM at $P` (price-only, matching the backend), and log the pnl defect as a follow-up, outside
this task. Either way, no new P&L arithmetic in this task.

### 2.5 Existing short positions
Any open short stock position with a percent stop changes behaviour on deploy. A stop that today would fire on a
FALL (a gain) now fires on a RISE. No data migration: the stored fraction keeps its meaning (distance from entry).
State this in the merge record.

---

## 3. (b) Refuse a sub-cent premium stop at save

### 3.1 Backend (the authority)

- **S1 PATCH** `update_position`: when `"premiumStopPct" in updates` and the value is not None and
  `premium_stop_is_sub_cent(position.entry_price, value)` (with `short_stock` from the row), refuse with
  **422** `premium_stop_below_one_cent: at entry $E a X% stop fires at $T, below $0.01, so it can never fire.`
  Use the **late-raise pattern** that `qty` uses (apply every other field, do NOT write `premium_stop_pct`,
  commit, raise at the end). The debounced drawer merges several edits into one PATCH, and an early raise
  would drop a valid stop/target edit sent alongside (the exact hazard the qty comment documents). If both qty
  and premium stop fail, both reasons go in one 422 detail (joined with `; `). An explicit null (clear →
  inherit) is never refused.
- **S2/S3 create** `position_writer.create_position`: after the ratio branch resolves
  `resolved_premium_stop_pct`, if it is not None and `premium_stop_is_sub_cent(entry_price, it)` (long side),
  WARN-log and set it to None (inherit the global). Never refuse the create: on the broker paths the order may
  already be at the broker, and a refused row loses the position (the reason the ratio ≥ 1 branch falls back
  rather than raising). The client-sent `premiumStopPct` fallback is checked by the same test (S3), so a
  sub-cent fraction cannot sneak in as the fallback.
  - The frontend signal fires only when `premiumStopDollar != null`. For S3 (fraction only, no dollar) there is
    no banner today. **Decision for this plan:** extend the client check to
    `(premiumStopDollar != null || premiumStopPct != null) && response.premiumStopPct == null`, carrying the
    requested dollar when known, else `entry × pct` rendered as dollars. The banner text is unchanged. The
    auto-trade booking path (`auto_trade_booking.py`) has no UI. Its WARNING log is the record, and the booking
    row's existing outcome log is unchanged.
- **Unit (DB) level**: no CHECK constraint. Entry is a sibling column, and rows created before this rule must
  still load and be editable (same reasoning as the band, `premiumStop.ts` doc).

### 3.2 Frontend (refuse before the server has to)

- **F1 drawer `commit`**: after the band check, if `premiumStopIsSubCent(position.entryPrice, next)` (long side),
  `revert('At this entry a X% stop fires below $0.01 and could never fire — kept the previous value.')` and
  return. Same revert-with-reason pattern as the band.
- **Drawer warning `subCent`**: keep it, now only for (i) an INHERITED global that is sub-cent at this entry, and
  (ii) a STORED own value that predates the rule. Wording for (ii): "… stored before sub-cent stops were refused;
  it can never fire — set a lower percent." Short stocks: never shown.
- **F2 TradeCard dollar field**: tighten `premiumStopDollarBounds(mid)`'s `max` so `mid - max >= 0.01`
  (`max = min(floor(cents*0.99)/100, (cents-1)/100)`), in integer cents like the rest of the helper. The
  degenerate $0.01 mid (already read-only, P2-24) stays read-only. A $0.02 mid then offers exactly $0.01.
  Tests: the bounds sweep in `premiumStop.test.ts` gains `mid - max >= 0.01` for every mid ≥ $0.02.
  The FILL can still differ from the mid. S2 is the backstop and the banner says so.
- **F3 AutoTradeArm**: beside `premiumStopAtOrAbovePremium`, add `premiumStopSubCent =
  premiumStopIsSubCent(entryPremium, premiumStopPctFromDollars(...))`. When true, the arm button is
  **disabled** with the reason shown (refuse at save). Arming is a save, and nothing has been sent yet, so
  refusing costs nothing.
- **G Settings global**: NOT refused. The global has no entry, so "sub-cent" is undefined for it. The existing
  Settings hint ("an entry below $X puts the stop below a cent") stays. Positions that inherit a sub-cent
  global are covered by the drawer warning (i). **This is a scope call on Kenneth's decision → §6 Q1.**

---

## 4. Tests (test-first; each named test fails on main before the change)

Frontend (Jest):
- `alertEngine.test.ts`: short stock fires at `>= entry*(1+pct)`, not on a fall; long stock unchanged; Bearish
  OPTION still fires on a fall (regression guard); boundary at exactly the threshold for both sides;
  `referenceValue` is the direction-aware threshold (4dp).
- `premiumStop.test.ts`: `percentStopFiringPrice` short sweep (smallest 2dp `>=` threshold, never below);
  `premiumStopIsSubCent` agrees with the backend predicate on the shared fixture (below); short never sub-cent;
  bounds sweep `mid - max >= 0.01`.
- EditDrawer tests: short label "above entry"; `alertFiresAgainst` short preview; commit of a sub-cent percent
  reverts with the reason and does not call `onChange`; inherited sub-cent global still warns; a pre-rule stored
  sub-cent value shows the (ii) wording.
- alerts page: `Stock stop (+X%)` for a short, `(–X%)` for a long stock, `Premium stop` for options.
- portfolioStore: fraction-only create whose response has `premiumStopPct == null` queues a drop notice.
- AutoTradeArm: sub-cent stop disables Arm with the reason.

Backend (pytest):
- `test_alert_generator`: short stock fires on a rise, not a fall, and `reference_value` is the direction-aware
  threshold; Bearish option unchanged.
- `test_premium_stop`: helpers, plus the **shared boundary fixture**
  `backend/tests/fixtures/premium_stop_subcent_cases.json`, generated once by a script checked in beside it and
  read by BOTH test suites (pattern: `python_round4.json`).
- `test_portfolio` PATCH: sub-cent → 422 `premium_stop_below_one_cent`, `premium_stop_pct` unchanged, and a `stop`
  sent in the same PATCH IS saved; null clear still allowed; qty + premium failures produce one combined 422.
- `test_position_writer` create: sub-cent derived from dollar → stored None + WARNING; sub-cent client fraction
  fallback → None; a valid one is unchanged; the create still returns 201.

Mutation checks to run and record (as prior phases did): swap `>=`/`<=` on the short branch; drop the
`isStock` term (options must break); drop the late-raise (the stop-alongside test must break).

---

## 5. Files

Backend: `app/services/premium_stop.py`, `app/services/alert_generator.py`, `app/routers/portfolio.py`,
`app/services/position_writer.py`, tests + fixture.
Frontend: `lib/premiumStop.ts`, `lib/alertEngine.ts`, `lib/portfolioStore.ts`,
`app/(frame)/portfolio/EditDrawer.tsx`, `app/(frame)/alerts/page.tsx`,
`components/organisms/AutoTradeArm/index.tsx` (+ tests). TradeCard needs no change: it consumes
`premiumStopDollarBounds`.
Ledger: PROJECT_STATE.json phase `STOP-SEMANTICS` (status, verify probe on `isShortStockPosition` /
`premium_stop_is_sub_cent`), and close the two open questions plus the round_13 sub-cent item on merge.

## 6. Questions for Kenneth (recommendation first)

- **Q1 — the global (G).** "Reject at save" cannot apply to the Settings global, because it has no entry.
  Recommend: leave the global warn-only, and refuse only per-position saves (S1, F1–F3). Positions that inherit
  a sub-cent global keep the drawer warning.
- **Q2 — create after a fill (S2/S3).** Recommend: drop the per-position stop to the global with the existing
  banner, never refuse the row (the order may already be at the broker).
- **Q3 — existing shorts (2.5).** Recommend: no migration. Their stops start firing on a rise at deploy, stated in
  the merge record.
