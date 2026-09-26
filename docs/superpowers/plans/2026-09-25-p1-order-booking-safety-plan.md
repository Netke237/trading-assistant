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

---

## Revisions after plan round 1 (these SUPERSEDE the sections they name)

Round 1 (fresh subagent, bmad-review-adversarial-general) found 1 HIGH, 7 MEDIUM and 6 LOW. Each one is answered below. R-n answers finding n.

**R1 (HIGH) — §4a.4 deletes only when nothing can have been placed.** A thrown `postOptionOrder` is classified from the `api.ts` error text `API /broker/option-order → NNN: detail`:
- **DEFINITELY NOT PLACED → delete the saved row:**
  - HTTP 400 (the adapter's ValueError), 422 (request validation), 503 (credentials);
  - a 502 whose detail contains "did not place the order" (the IBKR confirmation reply, `routers/broker.py:166-171`);
  - a 200 whose `status` is a stated rejection (see R10).
- **EVERYTHING ELSE → KEEP the row:** any other 502 (the adapters fold connection errors and read timeouts into RuntimeError → 502), a fetch `TypeError` or other network failure, an unparseable error. The banner reads: `Order status UNKNOWN (${why}). The tracked position ${recId} was KEPT — verify at the broker; if no order exists there, delete the position in Portfolio.` No automatic retry. The dedup never caches a failed request, so a blind retry could double the order, and the kept row's 409 now blocks one (R2).

Keeping a row with no order is the safer failure. It raises alerts about a position that does not exist. The opposite failure is a real order with no stop alert. The new test "`TypeError` → delete NOT called, UNKNOWN banner" pins this, and so does "502 connection error → kept".

**R2 — offline persist and a 409 on persist.**
- `saved.offline`: the response may have been lost after the commit. Make a best-effort `api.deletePortfolioPosition(pos.recId)` (a 404 counts as fine). The banner: `Portfolio tracking could not be confirmed, so NO order was sent.` If that delete also throws, add: `If ${recId} appears in Portfolio, delete it.`
- A persist rejection whose detail contains "already exists" (the duplicate-contract 409) shows its own message: `No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.`

**R3 — the `judged_size` clause gets a test that can fail.** New writer test 6b: direct call, gates off, `|STOCK` contract, qty 20 at a price where 20 shares fit every cap, and the REAL `check_position_risk`. The check is approved with no resize, and `over_exposure is True` only through `judged_size (5) != 20`. The log names "judged 5". M3 now turns 6b red.

**R4 — existing tests this change breaks, each updated (never deleted):**
- `test_position_writer_gates.py:145-159`: the `max_contracts_per_trade {cap}` log assertion becomes the new breach text. Gates off at qty > cap now logs the `exceeds_max_contracts_per_trade` reason.
- `test_o4_step4_booking.py:350`: `"already exists" in second.error` becomes "already open" / "raise that position's Contracts" (per R5).
- `edited-fields-sync.test.tsx:1030-1062` ("broker down") and `:1069-1096` (IBKR confirm 502): the harness gains a persist fetch mock that returns 201. The confirm-502 test asserts exactly one POST `/api/portfolio` and one DELETE `/api/portfolio/<recId>`, still no "Order placed" line, and the banner shows IBKR's text. "broker down" (a plain `Error('broker down')`, no status) now expects the UNKNOWN / kept banner.
- Any other Step-7 test that asserts the broker is called before the persist: found during the build and listed in the build commit.

**R5 — the 409 page text.** `a position for {contract} is already open, so this order was NOT booked as a second row. Either close the extra {qty} at the broker, or raise that position's Contracts by {qty} in Portfolio (the raise is refused if the total passes the {cap}-contract per-trade limit or an exposure cap; then close it at the broker).`

**R6 — §3b's recovery path always pages.** It is booked, but the outcome flags are lost, so it pages `AUTO_TRADE_BOOKED_UNVERIFIED` (rec_id key `auto-trade-booked-unverified:<SYM>`): `{Order} for {contract} was booked as {rec_id}, but the write failed after its commit, so its stop side and exposure were NOT checked — verify both in Portfolio.` New test 15b pins the page.

**R7 — the lock's scope is stated honestly.** `_BOOKING_LOCK` serialises `create_position` against `create_position` only (card POST, basket POST, auto-trade booking). The docstring says so. The locks live in a `weakref.WeakKeyDictionary` keyed by loop. The entry "…CONCURRENCY…" closes for the create↔create race it names (s6.5's gates-off bookings, plus the card path). Two new open lines are re-logged: the drawer PATCH qty-increase race (`routers/portfolio.py`, P6) and the `/fire` pre-broker snapshot race (`routers/auto_trade.py` / `auto_trader.py`, P3b/P6).

**R8 — follow-ups re-logged in open_questions, one line each, for their owners:**
- `lib/risk.ts` `checkTradeRisk` has no contract cap, so SendToBrokerDialog shows "Within risk limits" for a 6-lot the backend refuses (P2);
- `portfolio/page.tsx` `REJECTION_LABELS` has no `exceeds_max_contracts_per_trade` label (Portfolio page; unowned, so Kenneth assigns it);
- `/auto-trade/arm` accepts quantity > 5, and the fire then refuses it after consuming the arm (P3b/P6);
- the TradeCard Contracts input has no `max` (P2).

**R9 — local state on a delete.** After a successful delete, or a 404 (already gone), the page also drops any store row with that recId: `usePortfolioStore.setState(s => ({ positions: s.positions.filter(r => r.recId !== recId) }))`. A 30s `syncFromBackend` during the broker wait can have pulled the row in. This is a store call, not an edit to portfolioStore.ts, and it sends no second DELETE.

**R10 — status check and scope.**
- The rejection test is `String(res?.status ?? '').trim().toLowerCase()` in the set {rejected, inactive, error, canceled, cancelled, expired}. A missing status counts as placed. This matches the backend's `_is_rejected_status` and the existing mocks.
- The delete/keep logic wraps ONLY the `postOptionOrder` call and the status check. `applyPersistedPosition` and later steps run outside that try, and their failure shows `Order placed (ID …) but the local view failed to update: …` without touching the row.
- `deletePortfolioPosition` treats a 404 as success. The page checks for `→ 404` in the thrown error.

**R11 — §2c.** `RiskCheckResult` gains `max_contracts: Optional[int]`, set from the config the check already read. The writer builds the sentence from it and makes no config read of its own. The public `max_contracts_per_trade()` getter is dropped. The 422 detail is the sentence followed by `" Also: " + " ".join(other hard reasons)` when there are any. Test 5 adds a case where the cap and `total_exposure_limit_reached` occur together, and both appear.

**R12 — §3b.** The recovery SELECT matches `rec_id == rec_id AND contract == body.contract`. It is skipped when the write failed with an `HTTPException` whose status is 409 or 500, because those are the writer's own decided outcomes. Only a non-HTTP exception, or an exception after the commit, reaches it.

**R13 — the tests, made to discriminate.**
- Test 2: portfolio 100k, premium 1.70. A 5-lot costs 850 (0.85%) and fits. Use a premium of 9.00 instead: a 5-lot is 4,500 (4.5%) and fits the 5% cap; a 6-lot is 5,400 (5.4%) and breaches it. With the clamp restored, the 6-lot is judged at 5 → no `size_reduced` (M1 red). Without it → `size_reduced` plus the cap reason.
- Test 12: two variants. One is the plain body (the quote fetcher is patched and awaited). The other has `stopIsUserSet=True` (the price fetcher is patched and awaited). Restoring either bound default turns one red.
- Test 13: two different symbols, each at 4% single. The seeded exposure is 18%, so each alone totals 22% (fits 25%) and both together total 26%. Expect one 201 and one `total_exposure_limit_reached`.

**R14 — Q12's scope is stated in the §3a docstring.** Only USER-SET stops are direction-checked (`position_writer.py:277`). A plan-derived armed stop is re-anchored, not checked. `stop_required` still refuses a missing or non-positive one. Re-logged as one open line for the owner (P3b), if it wants the check on plan-derived stops too.

---

## Revisions after plan round 2 (these SUPERSEDE R1-R14 where they conflict)

Round 2 (fresh subagent) found 1 HIGH, 5 MEDIUM and 5 LOW. S-n answers finding n.

**S1 (HIGH) + S6 — the delete rule is narrowed to PROVABLY-PRE-SUBMIT failures. Everything else keeps the row and gives the user a button.** R1's status-code classes are dropped. A 400 can be a `JSONDecodeError` (a `ValueError`) raised while parsing a 2xx broker reply, so the order may be live. The page auto-deletes the saved row ONLY when one of these holds:
- HTTP **422**: FastAPI request validation, raised before the handler runs;
- HTTP **503** with detail starting `Broker credentials unavailable`: raised before `execute` (`routers/broker.py:307-314`);
- HTTP **400** with detail starting `live trading via` or `Unknown broker`: `broker_router.resolve`, before any adapter call (`broker_router.py:37-47`). Alpaca's STK-only `ValueError` is not listed, because this page sends options only and the broker picker never offers Alpaca for options;
- HTTP **502** with detail containing `did not place the order` (the IBKR confirmation reply, `routers/broker.py:166-171`);
- a 2xx whose `status` is a stated rejection (R10's set).

Everything else is an unknown order state: other 400s, other 502s (connection error, read timeout, broker HTTP 4xx/5xx such as an expired Tradier token, an unauthenticated IBKR gateway), a fetch TypeError, a 2xx with `order_id` `""` or `"unknown"` (the backend's no-order-id rule, `auto_trade_booking.py:67-69`). For all of these the row is KEPT. The banner reads: `Order status UNKNOWN (${why}). The tracked position ${recId} was kept — check the broker. If no order exists there, remove it:` followed by a **Remove tracked position** button. The button calls `api.deletePortfolioPosition(recId)`, then does R9's store drop, and the banner becomes `Tracked position removed.`

This answers S6's phantom-row cost without string-matching four adapters' error texts, which the page does not own and which can change. The phantom row is visible and removable in one click. A missing position is not. Re-logged for the broker/adapters owner (unowned; Kenneth to assign): post-submit parse errors should raise `RuntimeError`, not `ValueError`, and a broker 4xx should be distinguishable from a transport failure in the 502 detail. Then the page could auto-delete more cases.

Tests (FE): a 400 "Expecting value: line 1 column 1" keeps the row, shows the button, and does not delete. A 502 "Tradier paper order failed: HTTP 401…" does the same. A 422, the 503 credentials error, "Unknown broker", the IBKR confirm 502 and status "Rejected" each auto-delete. An `order_id: ""` 200 keeps the row. Clicking the button deletes and drops the row.

**S2 — same-contract race under the lock.** Right after the lock is acquired, `create_position` re-runs `SELECT … WHERE contract == body.contract` and raises the same 409 before the risk SELECT. New test 13b: two same-contract creates under `gather` give one 201 and one 409, never a 422. Mutation M16: drop the re-check → a 422 appears.

**S3 — api mocks.** `deletePortfolioPosition: jest.fn().mockResolvedValue(undefined)` is added to the `@/lib/api` mock factory in all four Step-7 test files: `edited-fields-sync`, `contracts-sync`, `direct-send-stop-gate` and `a8-rail-and-structural-cache`. The DELETE is asserted on that mock, not on `global.fetch`. The confirm-502 test's `expect(global.fetch).not.toHaveBeenCalled()` is replaced by exactly one persist POST plus `deletePortfolioPosition` called with the recId. These four files are added to §0's table as edited tests of the P1-owned page.

**S4 — the 409 page text carries no number:** `…or raise that position's Contracts by {qty} in Portfolio (refused if the total passes the per-trade contract limit or an exposure cap; then close it at the broker).` `auto_trade_booking` reads no config.

**S5 — rollback tests use a real DB failure.**
- Test 19a: `create_position` is patched to `db.add` a row that collides with an existing primary key and to `await db.flush()`, which raises a genuine IntegrityError. After the call, the session answers a SELECT, and that SELECT would raise `PendingRollbackError` without the rollback.
- Test 19b: `log_approval` is patched to add a duplicate-PK `AuditEventModel` and flush. The rollback leaves the session usable, and the booked row is still there (it was committed earlier).
- These are mutations M14 (drop the rollback in the write `except`) and M15 (drop the rollback after `log_approval`), renamed so they do not clash with §7.

**S7** — added to R8's Portfolio-page re-log line: `rejectionMessage` drops the unmapped sentence when a code in the same detail maps. The writer's "Also:" suffix keeps the raw codes, so the basket's own red banner (which prints the detail verbatim) shows everything.

**S8 — persist !ok after a commit.**
- A persist result that is `!ok`, not offline, and whose detail is none of the following gets a best-effort `deletePortfolioPosition(pos.recId)`: a 409, a 422, or one containing `duplicate rec_id` (that rec_id belongs to another row, so it must never be deleted).
- The banner is always `No order was sent — ${detail}.` When the delete was attempted and did not succeed, it adds `If ${recId} appears in Portfolio, delete it.`
- The offline branch always adds that line.
- `deletePortfolioPosition` stays a plain `del`, which throws on non-2xx. The page treats a thrown `→ 404` as already removed. That is the one place 404 is interpreted, which answers S11's contradiction.

**S9 — Q12 without a live price.** With gates off only, when the underlying fetch returns nothing, the wrong-side direction check falls back to `body.scanStockPrice` (the arm-time price) when it is > 0. The warning and `wrong_side_stop` then say `(against the scan price {p}; the live fetch failed)`. With gates on, nothing changes: the card path refuses only against a live price, as today. Test 7b covers this. The docstring states the remaining gap: no live price and no scanStockPrice means no check.

**S10** — test 12 gets a third variant that patches `app.services.position_writer.load_exit_plan_cfg` with a Mock and asserts it was called.

**S11 bookkeeping.**
- §0's "fixed by §6" means §5 test 23.
- §5 test 21 refers to the EXISTING `test_the_containers_are_copied_not_shared`.
- The 404 rule is settled in S8.
- The no-order-id 2xx is settled in S1.

---

## Revisions after plan round 3 (these SUPERSEDE R1-R14 and S1-S11 where they conflict)

Round 3 (fresh subagent) found 0 HIGH, 2 MEDIUM and 7 LOW. It verified S1's five auto-delete classes against the code: each is raised before any broker submission, and no path leaves a live order untracked or deletes a row whose order may be live. T-n answers round 3's findings in order: T1-T2 are M-1 and M-2, T3-T9 are L-1 to L-7. A 4th plan round is NOT yet run: the 3-round cap applies (see PROJECT_STATE audit_rule), pending Kenneth's call.

**T1 (M-1) — S8's persist-failure rule depends on the detail TEXT only.** The page never sees the HTTP status: `persistPosition` returns `{ok, offline?, detail?, …}` (`frontend/lib/portfolioStore.ts:389-429`), and `errorDetail` returns the backend's text, falling back to `HTTP ${status}` only when there is none (`:311-323`). `portfolioStore.ts` is P2's file and is not edited. The rule that replaces S8's first bullet:
- After ANY `!saved.ok && !saved.offline`, make a best-effort `api.deletePortfolioPosition(pos.recId)`, UNLESS the detail contains `duplicate rec_id` (`position_writer.py:558`: that rec_id belongs to another row, so it must never be deleted).
- Why the text alone is enough: `pos.recId` is generated fresh for this send. On a 409 (the existing row has a DIFFERENT rec_id) or a 422 (nothing written), the DELETE returns 404, which the page treats as already removed. On a 500 after the commit (detail `HTTP 500` or any other text), it removes the committed row. So the delete is harmless where nothing was written and needed where something was.
- S8's 409/422 exclusions are dropped. S8's other bullets stand.
- FE tests: a `duplicate rec_id` detail → `deletePortfolioPosition` NOT called. A detail `HTTP 500` → called with the recId. A 422 risk detail → called, and a mocked 404 rejection shows no "delete it" line.

**T2 (M-2) — S2's second duplicate check vs `test_portfolio_concurrent_add.py`.** That test (`:78-113`) fakes the race by emptying only the FIRST `AsyncSession.execute`. With S2's re-check under the lock, the SECOND contract SELECT finds the pre-inserted row and raises the 409 itself, so the test still passes but no longer reaches `commit` or the `IntegrityError` contract-collision branch (`position_writer.py:532-552`), which is its only pin. The fix:
- The patched `execute` empties EVERY contract-existence SELECT: it matches statements that select `PortfolioPositionModel.id` filtered on `contract`, not the call count. The `IntegrityError` branch's own re-check (also a contract SELECT) is made distinguishable by running AFTER a `rollback`: a `db.rollback` spy flips a flag, and from then on the patched `execute` passes through.
- New assertion: the `db.rollback` spy was awaited, so the 409 came from the `IntegrityError` path.
- The sibling `test_rec_id_collision_race_returns_500_not_409` gets the same treatment if its bypass relies on the call count. The build checks this and lists it in the commit.
- `backend/tests/test_portfolio_concurrent_add.py` is added to §0's table and to R4's list of existing tests updated.
- Mutation M17: S2's re-check made to run BEFORE the lock instead of inside it → test 13b red (one 422 appears). The concurrent-add test is not a mutation target for S2; it pins the `IntegrityError` branch, and M18 (the branch answering 500 for a contract collision) turns it red.

**T3 (L-1) — §5 test 4 is replaced.** R11 drops the `max_contracts_per_trade()` getter. Test 4 now asserts `result.max_contracts == cfg["sizing"]["max_contracts_per_trade"]` on three results: an approved one, the cap refusal, and an early return (for example a zero portfolio value), wherever the check returns.

**T4 (L-2) — the one persist-failure banner, final.**
- Detail contains `already exists` → R2's dedicated text survives: `No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.`
- Any other `!ok` (not offline) → `No order was sent — ${detail}.`
- Either one gets ` If ${recId} appears in Portfolio, delete it.` appended when T1's delete was attempted and threw anything other than `→ 404`.
- Offline → R2's text, `Portfolio tracking could not be confirmed, so NO order was sent.`, and the same "If … delete it." line when its delete threw anything other than `→ 404`.
§4a.2's "portfolio tracking refused it:" wording is dropped.

**T5 (L-3) — the full 409 page text (auto_trade_booking, duplicate contract), written once. It supersedes §3c, R5 and S4:**
`{Order} for {contract}: a position for this contract is already open, so this order was NOT booked as a second row. Either close the extra {qty} at the broker, or raise that position's Contracts by {qty} in Portfolio (refused if the total passes the per-trade contract limit or an exposure cap; then close it at the broker).`
`{Order}` is the same order label the other booking pages use (order id, or "no order id" per item 13). Test 16 asserts the substrings `NOT booked as a second row`, `raise that position's Contracts by`, and the absence of `Add it by hand` and of any digit that is not `{qty}`.

**T6 (L-4) — the IBKR 502 match uses the exact prefix.** It auto-deletes only when the detail STARTS WITH `IBKR did not place the order:` (`routers/broker.py:166-171`), checked on the text after `api.ts`'s `→ 502: `. Other adapters echo the broker's own text into their 502 detail (`ibkr_paper.py:147-149`, `tradier_paper.py:121`, `alpaca_paper_execution.py:66-68`), so a substring match could delete a row whose order is live. New FE test: a 502 `Tradier paper order failed: … did not place the order …` (substring present, prefix absent) keeps the row.

**T7 (L-5) — no Market orders to Tastytrade.** `TastytradePaperAdapter` refuses non-limit orders (`tastytrade_paper.py:106-111`), and the refusal is re-wrapped as a RuntimeError → 502 (`:126-127`, `routers/broker.py:335-340`). So every Place Market with Tastytrade would save a row, send nothing, and land on the UNKNOWN banner. In page.tsx (P1-owned), the "Right Now — Market" button is `disabled` when `selectedBroker === 'tastytrade_paper'`, with the title `Tastytrade paper accepts limit orders only — use Place Limit.` `placeDirectOrder('MKT')` also returns early with that text in `orderError` for the same broker, before any save, as a guard for keyboard or programmatic triggers. The adapter's error text is NOT added to the auto-delete list, because S1 forbids matching adapter texts the page does not own. FE test: broker `tastytrade_paper` → the Market button is disabled, and calling the handler anyway sends neither a persist POST nor `postOptionOrder`. Mutation M19: drop the guard → red.

**T8 (L-6) — the Remove button has its own state.** The kept rec_id lives in `const [unknownRecId, setUnknownRecId] = useState<string | null>(null)`, apart from `orderError`. The button renders whenever `unknownRecId` is set, under whatever banner shows. Its lifetime:
- It is set on the S1 UNKNOWN branch.
- It is cleared ONLY by a successful click (the DELETE succeeded or threw `→ 404`), or by unmount.
- It is NOT cleared by Prev/Next (`page.tsx:607`), a basket submit (`:1179`), or a new direct send. A later UNKNOWN send overwrites it, and the earlier rec_id stays named in the Portfolio instruction of its own banner. So that it is not lost silently, a second UNKNOWN while one is pending turns the value into a list: `unknownRecIds: string[]`, one Remove button per rec_id, each labelled with its rec_id.
- The label reads `Remove tracked position ${recId}`. Because the card can change under it, the click removes by rec_id and never reads the active card.
FE test: an UNKNOWN send, then Next, then Prev → the button is still there, and clicking it deletes that rec_id. Mutation M20: clear it in the `[active]` effect → red.

**T9 (L-7) — the two tests, specified exactly.**
- Test 13 (and 13b): the interleaving is forced, not hoped for. `AsyncSession.commit` is wrapped: `await asyncio.wait_for(barrier.wait(), timeout=0.5)` on a two-party `asyncio.Barrier` (Python 3.11), catching `TimeoutError` and `asyncio.BrokenBarrierError`, then the real commit. With the lock (correct code), the second create is blocked on the lock, so the first times out at the barrier and commits: the result is one 201 and one 422 (13b: one 409). With M5 (no lock), both SELECTs run and both reach the barrier before either commits, so both pass and the test is red every time. The `asyncio.sleep(0)` quote fetcher is dropped.
- Test 15 (M7): the patched `create_position` commits the row and then raises `RuntimeError("post-commit failure")`, a NON-HTTP exception, because R12 skips the recovery SELECT for an `HTTPException` 409/500. Test 15b (R6's page) uses the same patch. M7 (skip the recovery SELECT) then turns 15 red.

**§7 mutation list, additions:** M17 (T2), M18 (T2), M19 (T7), M20 (T8), plus FE mutations: M21, T1's delete skipped on an `HTTP 500` detail → red; M22, T6 back to a substring match → red.
