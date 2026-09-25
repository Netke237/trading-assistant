# P1a — Backend: refuse more than 5 option contracts at the source, plus booking safety: plan

Split from P1 on 2026-09-25 by Kenneth's decision `P1-SPLIT-P1A-P1B-2026-09-25`.
The P1 plan (`2026-09-25-p1-order-booking-safety-plan.md`) ran three plan rounds
without going clean and hit the cap. Its backend half is P1a, this file. Its
Step-7 page half is P1b (`2026-09-25-p1b-step7-save-first-plan.md`). The round
count restarts at 0 for each.

This file is self-contained. It folds the P1 plan's §1-§3, §5, §7 and the
backend answers from its R, S and T sections into one text. Where this file
and the P1 plan disagree, this file wins for P1a.

Phase `P1A-BACKEND-CONTRACT-CAP`. Branch `claude/order-booking-safety-7evlql`.

Kenneth's decisions this plan implements:

- **Q12**: a wrong-side stop booked with gates off pages an alert. A log line alone is not enough.
- **Q18**: with gates on, a quantity above the 5-contract limit is REFUSED with a clear message and never booked.
- **P1-CLAMP-AT-SOURCE-2026-09-25**: the refusal lives in `check_position_risk`, so it covers every caller.
- **P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25**: stocks keep today's share clamp.

## 0. Merge-order constraint (why P1a cannot reach main alone)

Step-7's Place Limit and Place Market (`step-7-trade-card/page.tsx:1066-1078`
and `:1117-1129`) send the broker order FIRST and then persist it. Take a
6-lot direct send. Today it is judged at 5 and booked at 6: tracked, but the
check was wrong. After P1a alone, the persist returns 422 AFTER the order is
live, so the order is not tracked at all. That is worse.

**Rule: P1a merges into main only together with P1b, or after it.** P1b makes
the page save first, so a 422 then stops the order before it is sent. Both
live on the same branch. The branch is merged `--no-ff` once, when both
phases are clean. The auto-trader fire check and the drawer PATCH both refuse
before any broker call or write, so they carry no such hazard.

## 1. Files

| File | Owner |
|---|---|
| `backend/app/services/portfolio_risk.py` | P1 |
| `backend/app/services/position_writer.py` | P1 |
| `backend/app/services/auto_trade_booking.py` | no package lists it. P1's backlog entry "Booking residuals…" is about this file, so P1 takes it. |
| `backend/tests/test_portfolio_risk_contract_cap.py` (new), `test_position_writer.py`, `test_position_writer_gates.py`, `test_portfolio_concurrent_add.py`, `test_o4_step4_booking.py`, `test_o4_step3_arm_fields.py`, a new `test_p1a_callers_through_source_cap.py` | P1 (tests of owned files) |

NOT touched: `auto_trader.py` (P3b), `routers/portfolio.py`, `routers/auto_trade.py`
and the schemas (P6), and every frontend file (P1b, P2).

## 2. `portfolio_risk.check_position_risk`: refuse, don't clamp

Today the check runs `proposed_contracts = min(proposed_contracts, max_contracts_per_trade)`
before it judges anything. A 10-lot is judged as 5 and then:
- booked as 10 by the card POST;
- set to 10 by the drawer PATCH;
- fired as 10 by the auto-trader.

```python
@dataclass
class RiskCheckResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    adjusted_size: Optional[int] = None
    portfolio_exposure_pct: float = 0.0
    judged_size: Optional[int] = None    # NEW: the quantity the caps were judged at
    max_contracts: Optional[int] = None  # NEW: the per-trade cap the check read

EXCEEDS_MAX_CONTRACTS = "exceeds_max_contracts_per_trade"
```

At the clamp line:

```python
max_per_trade = sizing["max_contracts_per_trade"]
if contract_id.endswith("|STOCK"):
    # DEFERRED by P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25 ...
    proposed_contracts = min(proposed_contracts, max_per_trade)
elif proposed_contracts > max_per_trade:
    reasons.append(EXCEEDS_MAX_CONTRACTS)   # hard reason, judged at the REAL qty
judged_size = proposed_contracts
```

- The new code sits exactly where the clamp line is, so the early returns keep their order.
- `judged_size` is set on every result from that point on, early returns included. It is `None` only on the `portfolio_too_small` return, which comes before it.
- `max_contracts` is set on every result wherever the config has been read, including that early return.
- The exposure maths now run on the real option quantity. A single-cap resize can still set `adjusted_size`, but the result stays unapproved because the new reason is hard.
- No public getter is added. The writer takes the number from `result.max_contracts`, so it makes no config read of its own.

The effect on each caller needs no edit to their files:
- card POST: gates on → 422 (§3c);
- drawer PATCH: the existing `qty_error` shape. The qty is not written; the other fields still commit;
- auto-trader `_check_exposure`: `RuntimeError("Exposure cap breach: [...]")` before the broker call. Today it fires the full qty.

## 3. `position_writer.create_position`

a. **Call-time defaults.** `quote_fetcher`, `price_fetcher` and
   `exit_plan_cfg_loader` default to `None` and resolve to the module globals
   at call time. A patch on `app.services.position_writer.*` then lands. The
   router and the booking still pass theirs explicitly. The docstring
   paragraph "THE THREE INJECTED CALLABLES" is updated.

b. **Serialise create against create.**
   - `_booking_lock()` returns an `asyncio.Lock` per running event loop, held in a `weakref.WeakKeyDictionary`. Tests run many loops, and a lock bound to a dead loop raises.
   - The lock is held from just before the duplicate-contract SELECT through the portfolio SELECT, the risk check, `commit`, the IntegrityError handling and `refresh`.
   - The live fetches (up to 8s) stay OUTSIDE the lock.
   - Right after the lock is taken, the duplicate-contract SELECT runs again: `WHERE contract == body.contract`, raising the same 409. So a same-contract race answers 409, never 422.
   - The docstring states the scope. The lock covers one process: the backend runs one uvicorn process (no `--workers` in the repo, and the auto-trader singleton already assumes one). It serialises `create_position` against `create_position` only (card POST, basket POST, auto-trade booking). The drawer PATCH qty race and the `/fire` pre-broker snapshot race stay open (§8).

c. **Q18, gates on.** When `EXCEEDS_MAX_CONTRACTS in risk.reasons` and gates
   are enforced, raise 422 with this detail:
   `"{qty} contracts is above the {cap}-contract limit per trade (max_contracts_per_trade). Lower Contracts to {cap} or fewer and send again."`
   - `cap` is `risk.max_contracts`.
   - When other hard reasons are present, append `" Also: " + " ".join(other_reasons)`.
   - Any refusal without the cap reason keeps today's `" ".join(reasons)` detail.

d. **Gates-off over_exposure from `judged_size`.**
   ```python
   breaches = [r for r in risk.reasons if r != "size_reduced_to_fit_exposure_limit"]
   if risk.adjusted_size is not None:
       breaches.append(f"the check would have resized to {risk.adjusted_size}")
   if risk.judged_size is not None and risk.judged_size != body.qty:
       breaches.append(f"the check judged {risk.judged_size}, not the ordered {body.qty}")
   over_exposure = (not risk.approved) or bool(breaches)
   ```
   The writer's `portfolio_risk._load_config()` read is removed. A refusal lists the resize once.

e. **Q12.** `WriteOutcome` gains `wrong_side_stop: Optional[str] = None`. It
   is set to the wrong-side detail in the gates-off branch. With gates off only,
   when the underlying fetch returns nothing, the direction check falls back to
   `body.scanStockPrice` when it is > 0, and the detail says
   `(against the scan price {p}; the live fetch failed)`. Gates on is
   unchanged: it refuses only against a live price. The docstring states the
   gaps: with no live price and no scanStockPrice there is no check, and only
   USER-SET stops are direction-checked (`position_writer.py:277`).

f. **Docstrings.** The WriteOutcome and `over_exposure` comments say it is
   "computed only with gates off; with gates on it is False by construction —
   an unapproved result (which now includes a qty above the per-trade cap)
   raises 422, and an approved soft resize is applied to qty".

g. **Log prefixes.** Every `add_position:` prefix in the writer becomes `create_position:`.

## 4. `auto_trade_booking.book_fired_order`

a. **Q12 page.** `_ALERT_TYPE_WRONG_SIDE_STOP = "AUTO_TRADE_BOOKED_WRONG_SIDE_STOP"`,
   with rec_id key `auto-trade-wrong-side-stop:<SYM>`. After the commit, when
   `outcome.wrong_side_stop` is set, it pages:
   `{Order} for {contract} was booked as {rec_id} with a stop on the wrong side: {detail} It will fire STOP_REACHED on the first scan — correct the stop in Portfolio.`
   - A failed page never unbooks the order.
   - `BookingOutcome` gains `wrong_side_stop: bool = False`. It is not exposed in the /fire response (P6's file); the page is the record.

b. **A fault after `create_position`'s own commit.** In the `except` around
   `create_position`, after `_rollback`, it SELECTs `PortfolioPositionModel.id`
   `WHERE rec_id == rec_id AND contract == body.contract`.
   - The SELECT is skipped when the failure is an `HTTPException` with status 409 or 500. Those are the writer's own decided outcomes.
   - If a row exists, the order is booked: run the post-commit steps (`record_booking`, no audit retry), page `AUTO_TRADE_BOOKED_UNVERIFIED` (rec_id key `auto-trade-booked-unverified:<SYM>`) with `{Order} for {contract} was booked as {rec_id}, but the write failed after its commit, so its stop side and exposure were NOT checked — verify both in Portfolio.`, and return `booked=True`.
   - If the SELECT itself fails, fall through to today's refusal.

c. **409 page text (duplicate contract).**
   `{Order} for {contract}: a position for this contract is already open, so this order was NOT booked as a second row. Either close the extra {qty} at the broker, or raise that position's Contracts by {qty} in Portfolio (refused if the total passes the per-trade contract limit or an exposure cap; then close it at the broker).`
   `_alert_not_booked` stops appending "Add it by hand or close it at the broker." when the reason carries its own remedy (a `remedy_included` flag). `auto_trade_booking` reads no config.

d. **Undashed expiry.** Refusal 4 requires `re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry)`
   before `date.fromisoformat`. `option_symbol._PIPE_RE` is not reused, because its
   `[A-Z]{1,6}` symbol group would refuse `BRK.B`.

e. **Whitespace order id.** `_order_label` uses `str(oid).strip()`, so an id of only whitespace counts as no id.

## 5. Tests

`tests/test_portfolio_risk_contract_cap.py` (new):
1. Option qty 6, cap 5 → not approved, `exceeds_max_contracts_per_trade` in reasons, `judged_size == 6`. Qty 5 → approved, judged 5.
2. Portfolio 100k, premium 9.00. A 5-lot (4.5%) fits the 5% single cap; a 6-lot (5.4%) carries `size_reduced…` plus the cap reason, with `adjusted_size` computed from the real premium.
3. Stock, 100 shares → no cap reason, `judged_size == 5` (the deferred behaviour, pinned).
4. `result.max_contracts == cfg["sizing"]["max_contracts_per_trade"]` on an approved result, the cap refusal, and an early return.

`test_position_writer_gates.py` (extend):
5. Gates on, qty 6 → 422 whose detail contains "6 contracts is above the 5-contract limit", and no row. Qty 5 → 201. Cap together with `total_exposure_limit_reached` → both appear (" Also: ").
6. Gates off, qty 6 → booked at 6, `over_exposure` True.
6b. Gates off, direct call, `|STOCK`, qty 20 where 20 shares fit every cap, with the REAL check → `over_exposure is True` only through `judged 5 != 20`, and the log names "judged 5".
7. Gates off, a wrong-side user stop AND an unapproved result → booked, `over_exposure`, `wrong_side_stop` set.
7b. Gates off, the live fetch returns nothing, scanStockPrice > 0 → `wrong_side_stop` says "against the scan price".
8. Gates on, approved resize → no `create_position: booking … OVER` log.
9. Bearish `|STOCK` wrong-side row: gates on → 422; gates off → booked with `wrong_side_stop`.
10. Refused with a resize → the warning names the resize once.
11. The writer no longer reads `portfolio_risk._load_config`: it is patched to raise, and a gates-off booking still works.
- Existing `:145-159`: the `max_contracts_per_trade {cap}` log assertion becomes the new breach text.

`test_position_writer.py`:
12. Three variants, each patching one module global with a mock and asserting it was called: the plain body (quote fetcher), `stopIsUserSet=True` (price fetcher), and `load_exit_plan_cfg`.
13. Concurrency, forced. Two `create_position` calls run under `asyncio.gather` on one file-backed sqlite DB, one session each. `AsyncSession.commit` is wrapped: `await asyncio.wait_for(barrier.wait(), 0.5)` on a two-party `asyncio.Barrier`, catching `TimeoutError`/`BrokenBarrierError`, then the real commit. Two symbols at 4% single each, with 18% seeded, so each alone totals 22% and both together 26% → one 201 and one 422 `total_exposure_limit_reached`.
13b. The same harness with the same contract → one 201 and one 409.

`test_portfolio_concurrent_add.py` (update, never delete):
- The patched `execute` empties EVERY contract-existence SELECT, matched on the statement rather than the call count, until a `db.rollback` spy has been awaited. After that it passes through, so the IntegrityError branch's own re-check sees the row.
- It asserts that the rollback spy was awaited, so the 409 came from the IntegrityError path.
- `test_rec_id_collision_race_returns_500_not_409` gets the same treatment if its bypass relies on the call count. The build commit says which.

`test_o4_step4_booking.py` (extend):
14. Q12: gates off, wrong-side user stop → pages `AUTO_TRADE_BOOKED_WRONG_SIDE_STOP` with rec_id `auto-trade-wrong-side-stop:AAPL`, and the order stays booked.
15. `create_position` patched to commit the row and then raise `RuntimeError("post-commit failure")` → `booked=True`, no NOT_BOOKED page.
15b. The same patch → `AUTO_TRADE_BOOKED_UNVERIFIED` is paged.
16. Duplicate contract → the page text contains `NOT booked as a second row` and `raise that position's Contracts by`, does not contain `Add it by hand`, and has no digit other than `{qty}`. The existing `:350` `"already exists"` assertion is updated to match.
17. `AAPL|185|20261218|C` → refused, "no usable expiry". Through `_check_refusals`: a strike of `0`, `abc` or `inf`; an expiry of `2026-13-40`; `entry_premium=0` via `dataclasses.replace`.
18. Order id `"  "` → the label says "no order id".
19a. `create_position` patched to add a row whose primary key collides with an existing row, then `flush` → a real IntegrityError. Afterwards the session answers a SELECT.
19b. `log_approval` patched the same way → the session is usable and the booked row is still there.
20. `datetime.now` in `atb` frozen at 2026-09-15 21:30 ET → `entryDate == "2026-09-15"`.
21. The existing `test_the_containers_are_copied_not_shared` also pins `tradeCardSnapshot` and `targets`.
22. `_alert_refusal` spy called with `discrete=True`.

`test_o4_step3_arm_fields.py`:
23. Assert `detail[*].loc[-1] == name` instead of `name in resp.text`.

`test_p1a_callers_through_source_cap.py` (new):
24. `AutoTradeService._check_exposure` with quantity 6 raises "Exposure cap breach" naming `exceeds_max_contracts_per_trade`.
25. Drawer PATCH qty 3 → 6 on an option row → 422 detail `exceeds_max_contracts_per_trade`, qty stays 3, and a stop sent in the same PATCH is still saved.

## 6. Mutation checks (each must turn a named test red)

| # | Mutation | Test that turns red |
|---|---|---|
| M1 | Restore the clamp for options | 1, 2, 5 |
| M2 | Drop the stock branch | 3 |
| M3 | over_exposure ignores judged_size | 6b |
| M4 | Drop the `wrong_side_stop` assignment | 7, 14 |
| M5 | Remove the lock | 13 |
| M6 | Bound defaults | 12 |
| M7 | Skip the recovery SELECT | 15 |
| M8 | Accept an undashed expiry | 17 |
| M14 | Drop the rollback in the write `except` | 19a |
| M15 | Drop the rollback after `log_approval` | 19b |
| M16 | Drop the in-lock re-check | 13b |
| M17 | Run the re-check before the lock | 13b |
| M18 | The IntegrityError branch answers 500 for a contract collision | the concurrent-add test |

## 7. Gate reminder for the reviewer

Per `audit_rule`, a finding blocks only if it can put a wrong number in front of
a user or on a broker order, or corrupt persisted data. Frontend behaviour is
P1b's and out of scope here, except the merge-order constraint in §0.

## 8. PROJECT_STATE at close

- Phase `P1A-BACKEND-CONTRACT-CAP` becomes shipped when its code round is clean. Its probe flips to `present`.
- Closes:
  - open_questions 58 (writer call-time defaults);
  - 60, 62, 63 (the writer entries: false docstring, reconstructed clamp, concurrency);
  - 65 (writer test gaps);
  - 66 (O4 step 3: item 4 fixed by test 23; items 1-2 bookkeeping, 3 and 5 already done);
  - 67 (O4 steps 4+5 booking residuals; 7/11/12 re-logged).
- round_11_followups 5 and 7, round_13_followups 7 and round_2_batch_followups 3 are all Step-7 page entries. They stay open for P1b. round_13 item 7's server-refusal half is noted as done here.
- 61 (stock clamp) is re-pointed at `STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES`.
- New open lines, one each:
  - PATCH qty race (P6);
  - `/fire` snapshot race (P3b/P6);
  - `lib/risk.ts` has no contract cap (P2);
  - Portfolio `REJECTION_LABELS` / `rejectionMessage` (unowned);
  - `/auto-trade/arm` accepts qty > 5 (P3b/P6);
  - TradeCard Contracts input has no `max` (P2);
  - Q12 on plan-derived stops (P3b).

---

## Plan round 1 (2026-09-25): CLEAN

A fresh subagent ran bmad-review-adversarial-general and found 0 gate-level findings. It confirmed all three callers of `check_position_risk`, the §0 merge-order hazard, and that M1, M5 and M16/M17 can fail. Two notes below the gate are carried into the build:
- The existing `test_gates_off_a_qty_over_the_per_trade_clamp_is_flagged` asserts that `adjusted_size is None`. That precondition is updated where the real-qty judgement changes it; the test is not deleted.
- Test 16 applies its "no digit other than `{qty}`" check after `{contract}` is removed from the text.
