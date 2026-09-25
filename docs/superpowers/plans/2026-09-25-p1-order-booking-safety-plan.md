# P1 — Order & booking safety: plan

Package: P1 in `docs/superpowers/plans/2026-09-25-work-packages.md`. Phase
`P1-ORDER-BOOKING-SAFETY` in PROJECT_STATE.json. Branch
`claude/order-booking-safety-7evlql`, off origin/main 91e6725.

Kenneth's decisions this plan implements:

- **Q12** — a wrong-side stop booked with gates off sends an alert, not only a log line.
- **Q18** — with gates on, a quantity above the 5-contract clamp is REFUSED with a clear message, never booked.
- **P1-CLAMP-AT-SOURCE-2026-09-25** — the Q18 refusal lives in `check_position_risk`, so it applies to every caller (card POST, drawer PATCH, auto-trade fire check).
- **P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25** — stocks keep today's share clamp in P1. Judging real share counts is queued as phase `STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES`.
- **P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25** — Step-7 Place Limit / Place Market save the position first, send the broker order at the approved quantity, and delete the saved row if the broker refuses.

## 0. Scope, ownership, and what is skipped

Files touched:

| File | Owner |
|---|---|
| `backend/app/services/portfolio_risk.py` | P1 |
| `backend/app/services/position_writer.py` | P1 |
| `backend/app/services/auto_trade_booking.py` | not listed for any package. The P1 backlog entry "Booking residuals…" is about this file, so P1 takes it with the entry. |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | P1 |
| `frontend/lib/api.ts` | not listed for any package. One added line: `deletePortfolioPosition`. |
| tests: `test_portfolio_risk*.py`, `test_position_writer*.py`, `test_o4_step4_booking.py`, `test_o4_step3_arm_fields.py`, a new step-7 jest file | P1 (tests of owned files) |

NOT touched: TradeCard (P2), portfolioStore.ts (P2), auto_trader.py (P3b),
routers/portfolio.py (P6), schemas (P6), the Stocks-mode send paths (queued phase).

Backlog entries re-checked against 91e6725. Items already fixed or not code are skipped:

- "LOGGED BY O4 STEP 3 ROUND 2…": item (1) is a wording note on a finished step, and (2) was answered by AUDIT-CAP-PER-STAGE-2026-09-25. Item (3) is **already done**: `test_o4_step4_booking.py::test_the_arms_boundary_values_survive_the_create_schema` (test 13) pushes the arm's smallest values through `_build_body` → `PortfolioPositionCreate`. Item (5) is **already done**: `_build_body` deep-copies. Only item (4) is open, and §6 fixes it.
- "LOGGED BY O4 STEPS 4+5 ROUND 2…": item (7) is unreachable (one row per attempt_id) and gets no test. Item (11) is guidance for step 6's client, not code. Item (12), a CancelledError at shutdown, stays open, re-logged in one short entry.
- "The contract cap is still applied to stock share counts…": not fixed here, by Kenneth's deferral. It is re-pointed at the queued phase.

## 1. `portfolio_risk.check_position_risk` — refuse, don't clamp (Q18 at the source)

Today: `proposed_contracts = min(proposed_contracts, max_contracts_per_trade)`
runs before anything is judged. A 10-lot is judged as 5 and then booked as 10
(card POST), set to 10 (drawer PATCH: `position.qty = qty` uses the unclamped
value), or fired as 10 (auto-trader `_check_exposure` approves).

Change:

```python
@dataclass
class RiskCheckResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    adjusted_size: Optional[int] = None
    portfolio_exposure_pct: float = 0.0
    judged_size: Optional[int] = None   # NEW: the quantity the caps were judged at

EXCEEDS_MAX_CONTRACTS = "exceeds_max_contracts_per_trade"

def max_contracts_per_trade() -> int:        # NEW public reader (writer's message)
    return int(_load_config()["sizing"]["max_contracts_per_trade"])
```

In the body, where the clamp line is today:

```python
max_per_trade = sizing["max_contracts_per_trade"]
if contract_id.endswith("|STOCK"):
    # DEFERRED by P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25 ...
    proposed_contracts = min(proposed_contracts, max_per_trade)
elif proposed_contracts > max_per_trade:
    reasons.append(EXCEEDS_MAX_CONTRACTS)       # hard reason; judged at the REAL qty
judged_size = proposed_contracts
```

- It is placed exactly where the clamp is. So the early returns (portfolio too small, before it; daily, concurrent and duplicate, after it) keep their order. An early return after this point drops the new reason, but that result is refused anyway.
- The later exposure maths run on the real option quantity. The single-cap resize can still set `adjusted_size`, and the result is not approved because the new reason is hard.
- `judged_size` is set on every result from this point on, early returns included, and is `None` only on the `portfolio_too_small` return.
- `is_stock` / `multiplier` stay where they are. The stock test uses the same `endswith("|STOCK")`.

Effect per caller, with no edits to their files:

- card POST → `create_position` gates on → 422 (§2c);
- drawer PATCH (`routers/portfolio.py`) → `qty_error = "exceeds_max_contracts_per_trade"`, the qty is not written, the other fields still commit (existing shape);
- auto-trader `_check_exposure` → `RuntimeError("Exposure cap breach: [...]")`, the fire is refused (today it fires the full qty). The gates-off booking marks it over_exposure (§2d).

## 2. `position_writer.create_position`

a. **Call-time defaults (entry "Direct-call writer tests…").** `quote_fetcher`,
   `price_fetcher` and `exit_plan_cfg_loader` default to `None` and resolve to the
   module globals at call time. A patch on `app.services.position_writer.*` then lands.
   The docstring's "THE THREE INJECTED CALLABLES" paragraph is updated. The router
   and the booking still pass theirs explicitly. The direct-call test's docstring
   becomes true, and its AssertionError sentinel can now fire.

b. **Serialise the risk snapshot (entry "…CONCURRENCY…").** A module-level
   `_BOOKING_LOCK = asyncio.Lock()` is held from the portfolio SELECT through
   `commit` / the IntegrityError handling / `refresh`. The live fetches (up to 8s)
   stay OUTSIDE the lock. Two concurrent creates then judge in turn, and the second
   sees the first's committed row. Scope, stated in the docstring: one process. The
   backend runs one uvicorn process (no `--workers` anywhere in the repo, and the
   auto-trader singleton already assumes one). The lock is created lazily per event
   loop, because tests run many loops, and a lock bound to a dead loop raises. Use
   `_booking_lock()`, which returns a lock keyed by `asyncio.get_running_loop()`.

c. **Q18 gates on.** When `EXCEEDS_MAX_CONTRACTS in risk.reasons` and gates are
   enforced, raise 422 with this detail:
   `"{qty} contracts is above the {cap}-contract limit per trade (max_contracts_per_trade). Lower Contracts to {cap} or fewer and send again."`
   `cap` comes from `portfolio_risk.max_contracts_per_trade()`. It is the only
   config read in the writer, used for text only. Any other refusal keeps today's
   `" ".join(reasons)` detail, which the Portfolio page and SendToBrokerDialog map.

d. **Gates-off over_exposure from `judged_size` (entries "…RECONSTRUCTS the check's clamp…" and "…resize listed twice").**
   ```python
   breaches = [r for r in risk.reasons if r != "size_reduced_to_fit_exposure_limit"]
   if risk.adjusted_size is not None:
       breaches.append(f"the check would have resized to {risk.adjusted_size}")
   if risk.judged_size is not None and risk.judged_size != body.qty:
       breaches.append(f"the check judged {risk.judged_size}, not the ordered {body.qty}")
   over_exposure = (not risk.approved) or bool(breaches)
   ```
   The `portfolio_risk._load_config()` read is removed from the writer. A refusal
   now lists the resize once. Unchanged: the unreachable stock case (booking
   fires options only) still reads as over_exposure through `judged_size != qty`.

e. **Q12.** `WriteOutcome` gains `wrong_side_stop: Optional[str] = None`. It is set
   to `wrong_side_detail` in the gates-off branch. The field has a default, so every
   existing constructor still works. The caller must page it (§3a).

f. **Docstrings (entry "…FALSE CLAIM…").** WriteOutcome and the `over_exposure`
   comment now say: "computed only with gates off; with gates on it is False by
   construction — an unapproved result (which now includes a qty above the
   per-trade cap) raises 422, and an approved soft resize is applied to qty".

g. **Log prefixes (entry "…test gaps…", last clause).** Every `add_position:`
   prefix in the writer becomes `create_position:`. No test asserts on these strings.
   The router's own log lines, if any, are not touched.

## 3. `auto_trade_booking.book_fired_order`

a. **Q12 page.** `_ALERT_TYPE_WRONG_SIDE_STOP = "AUTO_TRADE_BOOKED_WRONG_SIDE_STOP"`,
   with rec_id key `auto-trade-wrong-side-stop:<SYM>`. After the commit, if
   `outcome.wrong_side_stop`, it pages this text: "{Order label} for {contract} was
   booked as {rec_id} with a stop on the wrong side: {detail} It will fire
   STOP_REACHED on the first scan — correct the stop in Portfolio." The page failing
   never unbooks. `BookingOutcome` gains `wrong_side_stop: bool = False`. The /fire
   response (`routers/auto_trade.py`:271-274, P6's file) builds its body field by
   field, so the field is not exposed there and that file is not edited: the page
   is the record.

b. **A fault after create_position's own commit (item 8).** In the `except` around
   `create_position`: after `_rollback`, SELECT `PortfolioPositionModel.id WHERE rec_id == rec_id`.
   If a row exists, treat it as booked: log it, run the post-commit steps
   (`record_booking`, no audit retry), and return `booked=True`. `over_exposure` and
   `wrong_side_stop` are unknown there, so over_exposure is reported False and the
   log says the outcome flags were lost. If that SELECT itself fails, fall through
   to today's refusal.

c. **409 wording (item 9).** When the write fails with `HTTPException` 409, the
   reason text says: "a position for {contract} is already open, so this order was
   not booked as a second row: raise that position's Contracts by {qty} in
   Portfolio, or close the extra {qty} at the broker". `_alert_not_booked` stops
   appending "Add it by hand or close it at the broker." when the reason already
   carries its own remedy (a `remedy_included` flag).

d. **Undashed expiry (item 10).** Refusal 4 requires
   `re.fullmatch(r"\d{4}-\d{2}-\d{2}", expiry)` before `date.fromisoformat`.
   `option_symbol._PIPE_RE` is NOT reused: its symbol group `[A-Z]{1,6}` would
   refuse `BRK.B`, which the tokenised check accepts today.

e. **Whitespace order id (item 13).** `_order_label` uses `str(oid).strip()`.
   Whitespace-only counts as no id, the same as refusal 1.

## 4. Step-7 page (`step-7-trade-card/page.tsx`)

a. **Save first, send the approved qty (P1-CARD-SAVE-FIRST-SEND-TRIMMED; entries
   "placeLimitPaper posts…", "Contracts is still min=1…").** One shared helper,
   `placeDirectOrder(orderType)`, replaces the two duplicated bodies. The guards
   (`checkInvalidation`, `checkMethodPick`) and the per-type spinner flags stay:

   1. `contracts = Math.max(1, orderContractsBySymbol[sym] ?? 1)`;
      `pos = buildPaperPosition(card, type, broker, 'pending', livePrice, contracts)`,
      with sourceLabel "… (ID: pending)".
   2. `saved = await persistPosition(pos)`.
      - `saved.offline` → `setOrderError('Portfolio tracking is unreachable, so NO order was sent. Try again when the backend is back.')`, return. The broker call goes through the same backend, so nothing is lost by refusing.
      - `!saved.ok` → `setOrderError(\`No order was sent — portfolio tracking refused it: ${saved.detail}\`)`, return.
   3. `orderQty = saved.adjustedQty ?? contracts`. Post the broker order at `orderQty`.
   4. Broker throws, OR `res.status` is a stated rejection (the same set as the backend's `_REJECTED_STATUSES`: rejected, inactive, error, canceled, cancelled, expired — case-insensitive, trimmed) → `await api.deletePortfolioPosition(pos.recId)`:
      - delete ok → `setOrderError(\`Order NOT placed: ${why}. The tracked position was removed.\`)`;
      - delete fails → `setOrderError(\`Order NOT placed: ${why}. Its tracked position ${recId} could not be removed — delete it in Portfolio.\`)`.
      Return. Local state was never touched, because `applyPersistedPosition` has not run yet.
   5. Success → `applyPersistedPosition(saved, {...pos, contracts: orderQty, sourceLabel: …ID: res.order_id}, addPosition, onAdjusted→addSaveNote(sizeNote(q)), onDropped)`, then `setPaperOrderId(res.order_id)`.

   `sizeNote` today reads "Size reduced to N contracts to fit exposure limits."
   The broker now receives N, so it gains " The order was sent for N." — the note
   is about the order as well as the row.

b. **paperOrderId (entry "R2-11…").** Each direct send calls `setPaperOrderId(null)`
   at its start, beside `setOrderError(null)`. `handleSubmit` (basket) no longer
   clears it: a direct order's confirmation is still true after a basket records
   rows. The misleading comment in handleSubmit is corrected.

c. **Positive mid (entry "entryPrice gt=0…").** A module-level
   `positiveOrNull(x) => (typeof x === 'number' && Number.isFinite(x) && x > 0 ? x : null)`.
   `positionFromOrder`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? positiveOrNull(entryLimit) ?? c.entry.limit`.
   `buildPaperPosition`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? entryLimitFor(card)`.

d. `api.ts`: `deletePortfolioPosition: (recId: string) => del(\`/api/portfolio/${encodeURIComponent(recId)}\`)`.
   `del` throws on non-2xx, which is what 4a.4 relies on.

## 5. Backend tests (new or extended)

`tests/test_portfolio_risk_contract_cap.py` (new):
1. Options: qty 6 with cap 5 → not approved, `exceeds_max_contracts_per_trade` in reasons, `judged_size == 6`. Qty 5 → approved, judged 5.
2. The exposure is judged at the real qty: an option 6-lot whose real capital breaches the single cap carries `size_reduced…`, and `adjusted_size` is computed from the real premium.
3. Stock: 100 shares → no cap reason, `judged_size == 5` (deferred behaviour pinned; the queued phase flips this test).
4. `max_contracts_per_trade()` reads the config value.

`test_position_writer_gates.py` (extend):
5. Gates on, qty 6 → 422 whose detail contains "6 contracts is above the 5-contract limit", and no row. Qty 5 → 201.
6. Gates off, qty 6 → booked at 6, `over_exposure` True, the warning names "judged" or the cap reason.
7. Gates off, both gates in one call (wrong-side user stop AND unapproved) → booked, `over_exposure` True, `wrong_side_stop` set.
8. Gates on, approved resize → no `create_position: booking … OVER` log (the no-new-log assertion on the resize arm).
9. Bearish `|STOCK` wrong-side row: gates on → 422; gates off → booked with `wrong_side_stop`.
10. Refused-with-resize: the warning mentions the resize exactly once.
11. The writer no longer reads `portfolio_risk._load_config` (patch it to raise; gates-off booking still works because the check itself is patched).

`test_position_writer.py` (fix):
12. The direct-call test now proves offline-ness: patch the module global with an AsyncMock and assert it was awaited. Mutation: restoring the bound default makes it fail.
13. Concurrency: two `create_position` calls under `asyncio.gather` on one file-backed sqlite DB (two sessions), each alone within the total cap but together over it, gates on → exactly one 201-equivalent and one 422 `total_exposure_limit_reached`. Mutation: removing the lock makes both pass. The quote fetcher is an AsyncMock that `await asyncio.sleep(0)`, so both reach the SELECT before either commits.

`test_o4_step4_booking.py` (extend):
14. Q12: a gates-off booking with a wrong-side user stop pages `AUTO_TRADE_BOOKED_WRONG_SIDE_STOP` with rec_id `auto-trade-wrong-side-stop:AAPL` and stays booked.
15. Item 8: `create_position` patched to commit the row and then raise → `booked=True`, no NOT_BOOKED page.
16. Item 9: the duplicate-contract page text says "raise that position's Contracts" and not "Add it by hand".
17. Item 10: `AAPL|185|20261218|C` → refused, "no usable expiry". Item 5: a strike of `0`, `abc` or `inf`, an expiry of `2026-13-40`, and refusal 5 (`entry_premium=0` via `dataclasses.replace`), each through `_check_refusals`.
18. Item 13: order id `"  "` → the label says "no order id".
19. Items 1-2: rollback pins. A session whose `commit` raises after flush → `_rollback` awaited, and the session is usable afterwards (a SELECT works). The same for `log_approval` raising after a flush. Mutation M5/M6: deleting the `_rollback` call makes the follow-up SELECT fail.
20. Item 3: freeze `datetime.now` in `atb` to 2026-09-15 21:30 ET (01:30 UTC next day) → `entryDate == "2026-09-15"`.
21. Item 4: test 14 also pins `tradeCardSnapshot` (nested dict not shared) and `targets` list identity.
22. Item 6: `discrete=True` is pinned: `_alert_refusal` spy called with `discrete=True`.

`test_o4_step3_arm_fields.py`:
23. Item (4): assert on `detail[*].loc[-1] == name` instead of `name in resp.text`.

Auto-trader behaviour through the source change, in a P1-owned test file (NOT test_auto_trader.py, which is P3b's):
24. `AutoTradeService._check_exposure` with quantity 6 raises "Exposure cap breach", with `exceeds_max_contracts_per_trade` in the message.

Drawer PATCH through the source change, in a P1 test file:
25. PATCH qty 3 → 6 on an option row → 422 detail `exceeds_max_contracts_per_trade`, qty stays 3, a stop sent alongside is still saved.

## 6. Frontend tests (new `step-7-trade-card/__tests__/direct-send-save-first.test.tsx`)

Reuse `direct-send-stop-gate.test.tsx`'s render harness and mocks.

1. Order of calls: persist POST happens before `postOptionOrder` (a shared call-order log).
2. Persist rejected (422 detail) → `postOptionOrder` never called, and the red banner says "No order was sent".
3. Persist offline → never called, and the "unreachable" banner shows.
4. `adjustedQty: 2` on a 4-lot → `postOptionOrder` quantity 2, and the local row has contracts 2.
5. Broker throws → `deletePortfolioPosition(recId)` called; banner "Order NOT placed … removed"; no local row added.
6. Broker returns status "Rejected" → the same as 5.
7. The delete fails → the banner names the recId and "delete it in Portfolio".
8. paperOrderId: a successful Limit then a failed Market → no green "Order placed" above the red banner. A basket submit after a direct success keeps the green line.
9. `contractDetails.mid: 0` with no live quote → the persisted `entryPrice` is the entry limit, not 0 (both builders: direct path and basket `positionFromOrder`).

Existing Step-7 tests that assert the old order (broker first) are updated, never deleted. Each update is listed in the build commit message.

## 7. Mutation checks (each must turn a test red)

M1 restore the clamp for options → 1, 5. M2 drop the stock branch → 3. M3 over_exposure ignores judged_size → 6. M4 drop the `wrong_side_stop` assignment → 7, 14. M5 remove the lock → 13. M6 bound defaults → 12. M7 skip the post-failure rec_id SELECT → 15. M8 accept an undashed expiry → 17. M9 post the order before persist → FE 1. M10 send `contracts` instead of `orderQty` → FE 4. M11 skip the delete → FE 5. M12 revert to `??` → FE 9. M13 restore `setPaperOrderId(null)` in handleSubmit → FE 8.

## 8. PROJECT_STATE

The phase `P1-ORDER-BOOKING-SAFETY` becomes shipped when clean. Its probe changes
to `present: exceeds_max_contracts_per_trade` in portfolio_risk.py. Close into
`closed_questions.items` with evidence: open_questions entries 58, 60, 62, 63, 65,
66 (items 3-5 noted done), 67 (with the residuals 7/11/12 re-logged);
round_11_followups items 5 and 7; round_13_followups item 7 (the money half:
server refusal + save-first; the TradeCard input `max` is P2's file, re-logged as
one line for P2); round_2_batch_followups item 3. Entry 61 (stock clamp) stays open
and is re-pointed at the queued phase.
