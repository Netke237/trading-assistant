# AUTOTRADE-A6-A7-GATES-AND-RECORDS — plan

Date: 2026-09-24. Planned against main at `22c49425` (A4b merge). Lane P3 of
`docs/superpowers/parallel-sessions/2026-09-24/` (brief on
`claude/q2-hardening-merged-a2wx5g`, `28102fa9`). This lane is the only one
allowed to edit `backend/app/services/auto_trader.py`.

Kenneth's decisions (2026-09-24, this session):

- **A6 (oq "Should the auto-trader's daily-loss gate size on the full premium…")**:
  **FULL PREMIUM.**
- **A7a (oq "FOR KENNETH, raised by 2A-GATE round 5 finding (4)")**: **YES** — the
  `not_submitted` row carries `regime_gate` and `sizing`.
- **A7b (oq "LOGGED BY SIZING-FAIL-CLOSED ROUND 1 … DIFFERENT HTTP statuses")**:
  **500 on /auto-trade/fire too.**
- **A7c (oq "CLOSED BY BUILDING IT … min_mult above 1")**: **refusal confirmed; close.**

Plus two small fixes that need no decision: oq 2 (`_apply_vol_sizing` has no
catch-all) and oq 5 (`cap_blocked` / `daily_loss_blocked` rows omit `error`), and
a check of oq 4 (a broker REJECTED status takes fire()'s success path).

Line numbers are at `22c49425`.

---

## Batch A — the history record and the arm (no decision)

### A.1 oq 2 — `_apply_vol_sizing` catch-all (`auto_trader.py` fire(), after the `(SizingConfigError, ValueError)` handler ~:2306)

Live today: any exception class other than `RegimeHeadwindError`,
`RegimeGateConfigError`, `SizingConfigError`, `ValueError` escapes `fire()` after
the disarm with **no history row** — `/auto-trade/status` keeps showing the
previous order as `last_order`; `/fire` returns an unhandled 500.

Change: add a final `except Exception as exc:` to that try that appends a row
with status `_STATUS_RISK_CHECK_FAILED` (`"risk_check_failed"`, the existing
last-resort status — it is already NOT in `_RISK_BLOCKED_STATUSES` or
`_SIZING_STATUSES`, so `_alert_for_consumed_attempt` routes it to the
unclassified alert, which is what it is), `premium_at_risk: 0.0`,
`error: f"sizing/regime check failed: {exc}"`, then `raise` unchanged. Same
shape as the two existing `_STATUS_RISK_CHECK_FAILED` rows. No new status.

The HTTP answer is unchanged (still an unhandled 500 on /fire, which the
frontend reads as 'unknown' — conservative; nothing was sent but the UI does
not claim so). Not widened: mapping arbitrary exceptions is out of scope.

### A.2 oq 5 — `error` on `cap_blocked` and `daily_loss_blocked` rows (~:2345, ~:2389)

`except RuntimeError:` → `except RuntimeError as exc:` and add
`"error": str(exc)` to both rows. The message is the check's own
("Exposure cap breach: …", "Daily loss limit reached: …").

### A.3 oq 4 — REJECTED broker status: CLOSE with evidence, no code

Both callers of `fire()` book the result: `routers/auto_trade.py` `fire_now` →
`book_fired_order`; `routers/scan.py` ~:1837 → `book_fired_order`.
`auto_trade_booking._check_refusals` refuses `_REJECTED_STATUSES`
(rejected/inactive/error/canceled/cancelled/expired) and a missing order id,
and `_refuse` pages `AUTO_TRADE_NOT_BOOKED` with `broker_live=False`. So
"nobody is told" no longer holds. The history row carries the broker's own
status word (e.g. `"rejected"`), not `"filled"`.

Residue, logged not fixed (below the gate — fails closed): a rejected order's
success-shaped row still books `premium_at_risk`, so it spends daily-loss
budget on a trade that did not happen (over-blocks later trades, never
under-blocks); `_clear_config_refusal_holds` and the "fired" log line still run.

---

## Batch B — Kenneth's answers

### B.1 A6 — the daily-loss gate sizes on the FULL premium

`AutoTradeService._check_daily_loss` (~:2854):
- `this_risk = strategy.entry_premium * strategy.quantity * 100` — no stop
  fraction. The auto-trader places no protective order, so the whole premium
  is what is at risk.
- It no longer reads `auto_trade.premium_stop_pct` nor calls
  `resolve_premium_stop_pct`. Returns `this_risk` (dollars) instead of the stop
  fraction.
- `fire()` books the success row's `premium_at_risk` as that returned value
  (keeps Q2's "one computation, before the order" property: nothing is
  computed after the broker call).
- The long NOTE comment is replaced by the decision (A6-FULL-PREMIUM-2026-09-24).

What does NOT change:
- `ArmedStrategy.premium_stop_pct` / `ArmRequest.premium_stop_pct` stay: the
  booking (`auto_trade_booking.py:175`) stores it on the position, where the
  premium-stop alert reads it. Only the daily-loss accounting stops using it.
- `max_daily_loss_pct` still read; a malformed one still raises inside the check
  → `risk_check_failed` row (existing test ~:2366 keeps passing).
- Rows written BEFORE the deploy keep their stop-based `premium_at_risk`
  (in-memory history, cleared on restart; no migration).

Consequence, stated for Kenneth: with the 0.60 default the gate now counts
1/0.60 ≈ 1.67x more risk per trade, so fewer trades per day fit the 2% limit.
A trade whose full premium alone exceeds the limit is refused outright.

`backend/config/risk_rules.yaml` `auto_trade.premium_stop_pct` has NO reader
after this. Kept (removing a key is not what was asked), comment changed to say
it is not read, mirroring the file's existing `gap_threshold_pct` note. The
`premium_stop.py` module docstring line naming it as "(auto-trader sizing)" is
corrected. `ArmedStrategy.premium_stop_pct`'s comment "None inherits
auto_trade.premium_stop_pct" (~:216) is corrected: None means the booked
position inherits the global premium stop.

Tests that pin the OLD arithmetic are changed deliberately, named here:
- `test_premium_stop_per_position.py::test_auto_trader_daily_loss_gate_sizes_off_the_resolved_pct`
  → rewritten: a tighter declared stop no longer lets a trade through; the
  gate counts full premium regardless of the declared stop.
- `…::test_auto_trader_books_premium_at_risk_at_the_resolved_pct` → the row
  books full premium (500.0 for 5.00 x 1 x 100, not 150).
- `test_auto_trader.py` Q2 block (~:4429-4512): `…books_the_stop_the_breaker_gated_on`
  → the row books the dollars the breaker gated on (full premium), config read
  once; `…stop_is_resolved_exactly_once_per_fire` → `resolve_premium_stop_pct`
  is called ZERO times on the fire path; `…malformed_stop_is_refused_before_the_order`
  → a malformed `premium_stop_pct` no longer affects the fire (the key is not
  read) — the order goes out and the row books full premium.
- Any other test asserting a stop-scaled `premium_at_risk` found by the suite.

### B.2 A7a — `not_submitted` carries `regime_gate` and `sizing` (~:2428)

Add `"regime_gate": strategy.regime_gate_outcome` and
`"sizing": strategy.sizing_basis` to the `not_submitted` row; replace its
"NO `regime_gate` HERE" comment with the decision. Update the `order_failed`
row's comment ("carried here and not on the other blocked rows") so it no
longer claims exclusivity. `cap_blocked` / `daily_loss_blocked` / `stale_blocked`
unchanged (not asked).

Flip `test_which_rows_carry_the_regime_gate_outcome` deliberately: assert
`regime_gate` AND `sizing` are in the `not_submitted` row.

### B.3 A7b — `SizingConfigError` → 500 on POST /auto-trade/fire

`routers/auto_trade.py` `fire_now` (~:226): before
`except (ValueError, RuntimeError)`, add
`except SizingConfigError as exc: raise HTTPException(500, detail=f"{SIZING_CONFIG_REFUSED_PREFIX}{exc}")`
with the prefix `"Refused, nothing sent: regime_sizing is unusable: "`. The
refusal happens after the disarm and before any broker call
(`_apply_vol_sizing` precedes the risk checks and `execute_option_order`), so
"nothing sent" is true. `fire()` already `logger.error`s it, so the server
trace exists. `sizing_data_blocked` (a ValueError: bad measured conviction, a
data fault not a config fault) stays 400. `RegimeGateConfigError` is not part
of the decision: stays 400, logged as an open question.

The comment in `fire()` ~:2233 ("SizingConfigError is a RuntimeError, so
/auto-trade/fire still maps it to a 400") is corrected.

FRONTEND, required, otherwise the UI misreports: `classifyFireFailure`
(`frontend/lib/armBookingFields.ts:74`) returns `'unknown'` for every non-400,
and `AutoTradeArm` then shows "the order may or may not have been placed". Add:
a 500 whose detail starts with the same prefix → `'refused'` (the error text
is shown, the "check the broker" note is not). Every other 500 stays
`'unknown'`. The prefix is a string coupling across the wire, pinned by a
backend test (the detail text) and a frontend test (the classifier), exactly
as the existing `"Order failed:"` coupling is.

### B.4 A7c — close, bookkeeping only

Move the oq "CLOSED BY BUILDING IT … min_mult above 1" into `closed_questions`
with Kenneth's confirmation. No code.

---

## State file

One phase `AUTOTRADE-A6-A7-GATES-AND-RECORDS`, `active_phase` pointed at it;
decisions `A6-FULL-PREMIUM-DAILY-LOSS-2026-09-24`,
`A7A-NOT-SUBMITTED-CARRIES-GATE-2026-09-24`, `A7B-FIRE-SIZING-CONFIG-500-2026-09-24`,
`A7C-MIN-MULT-REFUSAL-CONFIRMED-2026-09-24`. The answered open questions (55, 78, 25,
26, 2, 5, 4) are moved to `closed_questions` with a pointer; residue logged.

## Verification

- New/changed tests in `tests/test_autotrade_a6_a7.py` plus the deliberate flips
  above. Mutation checks: revert each change (full premium → stop; drop the
  catch-all; drop `error`; drop `regime_gate`/`sizing` on not_submitted; map
  back to 400; classifier without the 500 branch) and confirm a test fails.
- Full backend suite (baseline 2959 passed / 1 skipped), frontend jest +
  typecheck (baseline 1811 / 136 suites), `state.py` exit 0.
