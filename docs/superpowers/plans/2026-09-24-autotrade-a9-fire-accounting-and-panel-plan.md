# AUTOTRADE-A9: fire accounting for failed/rejected orders, RegimeGateConfigError 500, panel refresh on refusal

Date: 2026-09-24. Branch: `claude/jolly-thompson-0q7paq`, restarted from main `5726e12`
(its previous A6/A7 history is fully merged).

Decisions (Kenneth, 2026-09-24, this session):

- **A9-ORDER-FAILED-BOOKS-FULL-PREMIUM-2026-09-24** — an `order_failed` row books the
  FULL premium (the `this_risk` `_check_daily_loss` already returned) as
  `premium_at_risk`, not 0. Closes open_questions[100].
- **A9-REJECTED-BOOKS-ZERO-2026-09-24** — a success-shaped row whose broker status
  is a stated rejection books `premium_at_risk` 0. The rejection words are ONE
  set shared with the booking step. Closes open_questions[96] (the at-risk half;
  see §6 for the half not in scope).
- **A9-REGIME-GATE-CONFIG-500-2026-09-24** — POST /auto-trade/fire answers
  `RegimeGateConfigError` with a prefixed 500, like A7b's `SizingConfigError`.
  Closes open_questions[99].

Also in scope (logged, below the gate, Kenneth's "proposed next step"):
open_questions[98] (panel refresh on refusal), [97] (four stale frontend
comments), [102] (the "only RuntimeError" docstring), [70] (test gap: `sizing`
on the order_failed row — the touched row, one assertion). [101] (deploy-day
rows) is CLOSED with no code: history is in-memory and a deploy restarts the
process, so no pre-deploy stop-scaled row survives it.

## 1. Backend — `services/auto_trader.py`

### 1.1 One rejection set

Move `_REJECTED_STATUSES` from `services/auto_trade_booking.py` into
`services/auto_trader.py` (booking already imports from auto_trader; the reverse
import would be circular). Add a helper next to it:

```python
def _is_rejected_status(status) -> bool:
    return str(status).strip().lower() in _REJECTED_STATUSES
```

`auto_trade_booking.py` imports `_REJECTED_STATUSES` and `_is_rejected_status`
from `auto_trader` and `_check_refusals` calls `_is_rejected_status(result.status)`.
The set's comment moves with it and gains one line: the fire path reads it too.
Identity is pinned by a test (`auto_trade_booking._REJECTED_STATUSES is
auto_trader._REJECTED_STATUSES`).

### 1.2 `order_failed` row books `this_risk`

In `fire()`'s bare `except Exception` after `execute_option_order`,
`"premium_at_risk": 0.0` → `"premium_at_risk": this_risk`, with a comment citing
the decision: the broker call was made and errored, the order may be live, no
position is booked (fire raises before the caller books), so fail closed — the
worst case is one extra refused trade that day. `this_risk` is always bound here
(the daily-loss try either assigned it or raised).

`not_submitted` stays 0.0 (nothing reached the broker — `OrderNotSubmittedError`'s
contract). Every pre-order refusal row stays 0.0.

### 1.3 Rejected success-shaped row books 0

In the success row: `"premium_at_risk": 0.0 if _is_rejected_status(result.status) else this_risk`,
comment citing the decision: the broker SAID it did not happen; the booking step
refuses the same status with the same set. Unknown/other statuses keep booking
the full premium (a rejection list, not an allowlist — same reasoning as the
booking step). The "no order id" case (`_NO_ORDER_IDS`) is NOT treated as
rejected here: not part of the decision, and booking it fails closed.

The `_check_daily_loss` docstring gains one sentence: the rows it sums book the
full premium on success and on `order_failed`, 0 on a stated rejection and on
every refusal.

### 1.4 Docstring fix (oq 102)

`_alert_unclassified_refusal`: replace "`fire()`'s guard there catches only
RuntimeError, and by then the disarm has already happened" with the true
statement: that path now leaves a `risk_check_failed` row (fire()'s
`except Exception` after the sizing call, the exposure check and the daily-loss
check) and this alert is what the scan trigger routes that status to. Wording
only; verify it against `maybe_fire_on_scan`'s routing before writing.

## 2. Backend — `routers/auto_trade.py`

Add `REGIME_GATE_CONFIG_REFUSED_PREFIX = "Refused, nothing sent: regime_gate is unusable: "`
next to the sizing prefix, and an `except RegimeGateConfigError` clause alongside
the `SizingConfigError` one (both before `(ValueError, RuntimeError)`, since both
subclass RuntimeError) raising `HTTPException(500, detail=PREFIX + str(exc))`.
Comment: decision A9, same reasoning as A7b; `fire()` raises it only from
`_apply_vol_sizing`, after the disarm and before any broker call, and has
already written its `regime_gate_config_blocked` row. Import it from
`app.services.auto_trader`.

## 3. Frontend — `lib/armBookingFields.ts`

Export `REGIME_GATE_CONFIG_REFUSED_PREFIX` (same string). In
`classifyFireFailure`, the 500 branch returns `'refused'` when the detail starts
with EITHER prefix; every other 500 stays `'unknown'`. Doc comment updated
(two 500s are refusals; coupled to four strings now).

## 4. Frontend — `components/organisms/AutoTradeArm/index.tsx`

### 4.1 Refresh on refusal (oq 98)

In `handleFireNow`'s catch, the `'refused'` branch keeps `setError(String(e))`
and adds `void refreshStatus();`. NOT `applyArmedStatus(false, …)`: some refusals
PRESERVE the arm (`ArmPreservedError` — market closed/halted, re-armed since the
read; the router maps them to 400), so the backend's answer is the truth, not an
assumption. No portfolio sync on this branch (nothing was placed).

`statusSeq` is not bumped: `refreshStatus` captures the seq at issue, and a
refusal changes nothing locally, so there is no newer local state to protect.

### 4.2 Stale comment (oq 97, 1 of 4)

The `liveMid` doc (~:120-126): drop the claim that `_check_daily_loss` sizes
`entry_premium * quantity * 100 * stop_pct`; since A6 it sizes the full premium
`entry_premium * quantity * 100`, so a stale `entry_premium` still under-counts
the daily-loss risk (2.4x in the example), and the stop-fraction half of the
example stays true of `premiumStopPctFromDollars`. Keep the example numbers
consistent.

## 5. Frontend — the other three stale comments (oq 97)

`components/organisms/TradeCard/index.tsx` ~:1697, `app/(frame)/portfolio/EditDrawer.tsx`
~:1209, `lib/premiumStop.ts` ~:28: remove the "shrinks the auto-trader's
daily-loss denominator ~3000x" clause (the declared stop no longer enters that
gate since A6), keeping the PREMIUM_STOP-alert half, which is still true. Comment
text only.

## 6. Out of scope, stated

- oq 96's second half: `maybe_fire_on_scan` still logs "fired on scan completion
  trigger" and runs `_clear_config_refusal_holds` for a rejected status. Not part
  of Kenneth's decision; stays open (re-worded to drop the at-risk half).
- `_NO_ORDER_IDS` on the fire path (see §1.3).
- `maybe_fire_on_scan`'s handling of `RegimeGateConfigError` (it alerts; no HTTP).

## 7. Tests

Backend, new `tests/test_autotrade_a9.py`:

1. `order_failed` row books the full premium: premium 2.50 × qty 2 → 500.0; plus
   `regime_gate`/`sizing` values on that row (oq 70).
2. A later fire the same day is refused by the daily-loss gate because of that
   order_failed row (limit fits one, not two).
3. Rejected status (parametrize a few words incl. mixed case / whitespace, e.g.
   `" Rejected "`, `"Inactive"`, `"cancelled"`) books 0.0; a subsequent fire is
   NOT blocked by it.
4. A non-rejection status (`"filled"`, `"Submitted"`, an unknown word) still books
   the full premium.
5. `auto_trade_booking._REJECTED_STATUSES is auto_trader._REJECTED_STATUSES`.
6. Endpoint: `RegimeGateConfigError` through the REAL `fire()` → 500 with the
   regime prefix, broker not called, booking not called, row
   `regime_gate_config_blocked`.
7. Prefix pin against `frontend/lib/armBookingFields.ts` for the new constant.

Changed: `test_autotrade_a6_a7.py::test_other_refusals_stay_400` drops the
`RegimeGateConfigError` param (it moved) and its docstring says so.
Any existing test asserting `order_failed` books 0.0 is flipped (none found by
grep; the full suite is the check).

Frontend:

- `lib/__tests__/armBookingFields.test.ts`: a 500 with the regime prefix is
  `'refused'`; a 500 with a near-miss detail stays `'unknown'`.
- `AutoTradeArm.test.tsx`: 15c extended/15d new — a refused fire re-reads the
  status (`getAutoTradeStatus` called twice) and, when the status says
  `armed: false`, the armed banner is gone; a refused fire whose status says
  still armed keeps the armed banner.

## 8. Verify

`cd backend && pytest` (expect 3000 + new − 0), `cd frontend && npm run typecheck && npm run test`,
`python3 scripts/state.py` exit 0. State file: new phase AUTOTRADE-A9 with a
presence probe (`REGIME_GATE_CONFIG_REFUSED_PREFIX =` in routers/auto_trade.py),
three decisions, oq 70/97/98/99/100/101/102 closed with pointers, oq 96 reworded.

## 9. Round 1 (the plan) — no blocking findings; 4 should-fix + 7 nits, ALL folded in

1. **§4.1 amended — bump `statusSeq` before the refresh.** The post-refusal read IS
   the newer truth; an older in-flight read (the mount read) carries the same seq
   and could land after it with a pre-fire `armed: true`. Both the refused and the
   unknown branch now do `statusSeq.current += 1; void refreshStatus();`. Test:
   mount read held on a deferred promise, refusal, post-refusal read `armed: false`,
   then the mount read resolves `armed: true` → the Arm button is shown.
2. **`RegimeGateConfigError`'s docstring** ("maps it to a 400") reworded to the
   500 + must-be-caught-above-the-400-handler rule; `test_conviction_sizing.py:318`'s
   docstring ("catches (ValueError, RuntimeError) -> 400") corrected for both
   classes.
3. **§7 frontend test spelled out:** `.mockResolvedValueOnce(armedTrue)
   .mockResolvedValueOnce({armed:false})`, wait for 2 calls, assert armed text and
   Fire now gone, Arm button present, red error still shown, no sync. Mutation:
   drop the refresh → fails.
4. **§1.4 widened:** the docstring headline of `_alert_unclassified_refusal` and the
   `else:` comment in `_alert_for_consumed_attempt` stop claiming "no row": a
   `risk_check_failed` row falls through to that `else` (routed by fall-through,
   not by name). The PAGE TEXT ("no outcome was recorded") is left unchanged and
   logged as an open question — wording a human receives is Kenneth's.
5. nit: the §1.2 comment states the true worst case — this premium's share of
   today's budget is spent until the next UTC day.
6. nit: "THE ONE COMPUTATION" comment names both consumers (success row, possibly
   0 on a rejection; `order_failed` row).
7. nit: two stale test comments added to §5 (`AutoTradeArm.test.tsx` ~:133,
   `EditDrawer.test.tsx` ~:1057).
8. nit: expected backend count is 3000 + new − 1 (the dropped 400 param);
   `test_other_refusals_stay_400` docstring + assertion cover both prefixes.
9. nit: frontend constant test pins the literal, prefix-must-lead, 502 → unknown,
   and the two prefixes do not cross.
10. nit: booking imports only `_is_rejected_status`; the identity pin is
    `atb._is_rejected_status is at._is_rejected_status`.
11. nit: endpoint test 6 mirrors the A7b twin exactly (`_apply_vol_sizing`
    patched to raise, real `fire()`, full `detail ==`).
