# O4 steps 4 + 5 — the fired order books a position, on both triggers (re-plan)

Date: 2026-09-24. Re-planned against the tree at `52a19b80` (main), per decision
`O4-ROUTE-AND-ALERT-2026-09-24`. It replaces "Step 4" and "Step 5" in
`2026-09-17-o4-implementation-plan.md` §2, which were written against a ~350-line `auto_trader.py`
(2822 lines today). The two steps are planned, built, audited and merged **together**: between them,
"Fire now" would book a position and a scan-triggered fire of the same arm would not (spec §11.5).

Inputs: spec `2026-09-15-o4-auto-trade-books-a-position-spec.md` §3.1, §3.2, §4.3, §4.4, §5.3, §5.4,
§6; step 2's phase note (`over_exposure` is widened); step 3 re-plan §6 (obligations); the O4
`open_questions` entries logged by steps 1–3.
Targets: `backend/app/services/auto_trader.py`, new `backend/app/services/auto_trade_booking.py`,
`backend/app/services/position_writer.py`, `backend/app/routers/auto_trade.py`,
`backend/app/routers/scan.py`. One layer (backend).

---

## 1. What the old steps 4–5 got wrong against today's tree

| Old plan / spec said | Today | Consequence |
|---|---|---|
| A refusal calls `await notify_alert(...)` (spec §6.5) | Decision `O4-ROUTE-AND-ALERT-2026-09-24`: **reuse `_alert_refusal`** (`auto_trader.py:1485`). It is **sync**, runs `asyncio.run(notify_alert(...))`, and **refuses to run when a loop is already running in its thread** (it logs "NOT alerted" and returns). The booking runs **on the event loop** on both triggers. | Called as `await asyncio.to_thread(_alert_refusal, ...)`: a worker thread has no loop, which is exactly the thread shape `_alert_refusal` already runs in today (the scan trigger's `to_thread`). Called directly, every booking alert would be a silent no-op. **Test 11 pins that the alert reaches `notify_alert`**, not merely that a helper was called. |
| `fire()` stamps each history row with a new `fire_id` (spec §5.4) | Every row `fire()` writes already carries **`attempt_id`** (2a-alert F1; ten append sites in `fire()`, `auto_trader.py:2198`–`2426`). One attempt writes exactly one row. | `FiredOrder` carries `attempt_id`; no new id. |
| `fire()` appends at four sites; only one is the success row | Ten append sites; the success row is the last (`:2425`–`:2447`), `return result` at `:2449`. | Only the success row can get a `rec_id`. |
| `maybe_fire_on_scan` has one `except Exception` | It has six handlers (`:2592`–`:2675`) routing refusals to alerts. `self.fire(...)` is at `:2579`, the success tail at `:2587`–`:2591`. | It returns the `FiredOrder` from the success path only; **every handler returns `None` unchanged** (spec §9.4 — the fire-refusal routing is not touched). |
| `direction` is derived from `action` × right when absent (spec §4.2) | `direction` is **required** on `ArmRequest` and validated by `ArmedStrategy.__post_init__`; `action` is `Literal["BUY"]`. | Nothing is derived. **New** (§2.4 refusal 4): the contract's right must **agree** with `strategy.direction` (C ↔ Bullish, P ↔ Bearish). With `action` fixed at BUY, a Bullish long put is a malformed arm, and booking it stores a stop compared on the wrong side (`alert_generator` reads `direction`), i.e. a stop that silently never fires. |
| `create_position` takes `stop_required` (spec §6.2, old plan step 4) | Step 2 did **not** add it (`position_writer.py:115-123`). | Step 4 adds it (§2.5). |
| tastytrade's status string is unverified (spec §3.2) | `tastytrade` 13.2.3 is installed; `OrderStatus` is a **`StrEnum`**, so `str(OrderStatus.REJECTED) == "Rejected"`. Values: Received, Cancelled, Filled, Expired, Live, Rejected, Contingent, Routed, In Flight, Cancel Requested, Replace Requested, Removed, Partially Removed. | Plain case-insensitive equality works for all four brokers (§2.4 refusal 2). |
| An empty `order_id` means "not transmitted" (spec §6.3.4) | Alpaca's adapter defaults a missing id to the literal `"unknown"` (`alpaca_paper_execution.py:71`) and does not `str()` it, so it can also be `None`. | "No order id" is `None`, `""` or `"unknown"` (case-insensitive, stripped). |
| `entry_date` is the UTC date (spec §4.3) | `auto_trader.py` already imports `MARKET_TZ` (`:17`). | **Changed:** `datetime.now(MARKET_TZ).date()`. A fire is a US-market event; UTC reads a day late after 20:00 ET, which spec §4.3 accepted only because the server "has no business guessing a browser's timezone". It does not have to guess the market's. Display and holding-period only (spec §4.3). |
| `rec_id` is `REC-AT-{ms}-{4 hex}` | Nothing parses `rec_id`'s shape (grepped backend and frontend). `rec_id` is `unique`; a collision is a 500 from `create_position`, i.e. a refused booking. | `REC-AT-{ms}-{8 hex}`: four hex digits is 1-in-65 536 per millisecond for no saving. |
| The scan call site is `scan.py:1762-1766` | It is `scan.py:1806-1810`; `_upsert_session` follows at `:1824`. `tests/test_scan_session.py:285-296` still swaps in a `SimpleNamespace` auto-trader and a `_FakeDb` with only `execute`. | Guard `if fired is not None` (§2.7). |
| Test sweep: `result.order_id` in a handful of tests | Four sites: `test_auto_trader.py:66-67, 137-138, 168-169, 4463-4465`. **Plus one the old plan did not list**: `test_auto_trader.py:3446` (`test_the_manual_fire_endpoint_fires_the_order_it_checked`) patches `fire` to return a bare `OrderResult` and calls `fire_now` with a `_FakeDb`. | §5. |

---

## 2. The change

### 2.1 `FiredOrder` — `auto_trader.py`

```python
@dataclass(frozen=True)
class FiredOrder:
    result:     OrderResult     # what the broker adapter returned
    strategy:   ArmedStrategy   # POST-_apply_vol_sizing: the quantity the broker got (spec §2.1)
    attempt_id: str             # the key of the success history row
```

- `fire()`'s last line (`:2449`) returns `FiredOrder(result, strategy, attempt_id)`. `strategy` is the
  local that `_apply_vol_sizing` reassigned at `:2188`, i.e. post-sizing. **No raise path changes.**
- `maybe_fire_on_scan` becomes `-> Optional[FiredOrder]`: `fired = self.fire(...)` inside the existing
  `try`, and `return fired` as the last statement of that `try` (after `_clear_config_refusal_holds()`,
  which cannot raise — its body is one guarded `try`). The early returns and all six handlers stay
  byte-identical and return `None` implicitly.
- `OrderResult` is imported for the annotation only (`TYPE_CHECKING`), because `fire()` imports the
  adapter module lazily today and that stays true.

### 2.2 `record_booking` — `auto_trader.py`

```python
def record_booking(self, attempt_id: str, rec_id: str) -> bool:
```

Under `self._lock`, find the row whose `attempt_id` matches (searched from the end, as
`_fire_attempt_record` does) and **replace it in the list** with `{**row, "rec_id": rec_id}` — a new
dict, never an in-place mutation, so a reader holding the old dict (`get_state()` copies the list, not
the rows) never sees it change size. A miss logs at WARNING and returns `False`; it never raises.
Spec §5.4's link between "the auto-trader fired this" and "this position exists". Unbooked rows carry
no `rec_id` key; `row.get("rec_id") is None` reads as *fired, not booked*. In-memory only, like the
rest of `history` (pre-existing; spec §5.4).

### 2.3 `book_fired_order` — new `services/auto_trade_booking.py`

```python
@dataclass(frozen=True)
class BookingOutcome:
    booked:        bool
    rec_id:        Optional[str]
    error:         Optional[str]   # human-readable, always names the order id
    over_exposure: bool

async def book_fired_order(fired: FiredOrder, db: AsyncSession) -> BookingOutcome:
```

**It never raises** (spec §6.1). Its whole body is inside one `try/except Exception` that returns
`booked=False`; `asyncio.CancelledError` (a `BaseException`) is left to propagate. Order of work:

1. The refusals in §2.4, in order, **before anything touches `db`**.
2. Build `PortfolioPositionCreate` from `fired.strategy` (§2.6). A `ValidationError` is a refusal.
3. `await create_position(body, db, quote_fetcher=..., price_fetcher=..., exit_plan_cfg_loader=...,
   enforce_pre_trade_gates=False, stop_required=True)`. The three callables are **this module's
   module-level names, looked up at call time and passed explicitly** — the router's pattern, and the
   remedy the step-1 open question names for the default-bound-at-definition trap. Tests patch
   `app.services.auto_trade_booking.fetch_contract_quote_async` etc.
   Any exception (the 409 duplicate, the 500 `rec_id` collision, the `stop_required` 422 (§2.5),
   anything else) → **`await db.rollback()` in its own guarded `try`**, then a refusal. The rollback is
   what keeps the scan's session usable for `_upsert_session` (`scan.py:1824`) if the failure left it
   pending-rollback (spec §5.3, round 2).
4. `log_approval(rec_id, snapshot, db)` when `trade_card_snapshot` is truthy — the same condition the
   router uses (`portfolio.py:163`). Guarded; on failure **`await db.rollback()`** (guarded) and log at
   ERROR. The position is already committed; the booking stays `booked=True`. The rollback expires ORM
   objects, so nothing after this reads `outcome.position` — `rec_id` is the string built in step 2.
5. `auto_trader.record_booking(fired.attempt_id, rec_id)`.
6. If `outcome.over_exposure`: the over-exposure alert (§2.8). The booking stands.
7. Return `BookingOutcome(True, rec_id, None, outcome.over_exposure)`.

Every refusal (steps 1–3, and the outer catch-all) logs at ERROR and raises the not-booked alert
(§2.8) before returning.

### 2.4 The refusals, and why each is a refusal

All run on `fired.strategy` and `fired.result`, before `db` is touched. Each yields
`booked=False` and an `error` that names the order id (or says there is none).

1. **No order id** — `result.order_id` is `None`, or stripped and lower-cased is `""` or `"unknown"`.
   IBKR's confirmation-question response (`ibkr_paper.py:140-141`) yields `order_id=""` for an order
   never transmitted; Alpaca's missing id is `"unknown"` (spec §6.3.4).
2. **A stated rejection** — `str(result.status).strip().lower()` in
   `{"rejected", "inactive", "error", "canceled", "cancelled", "expired"}`. One set for all brokers:
   none of those words means *live* at any of the four, so the union is strictly the safer match.
   IBKR says `Inactive`; Tradier adds `error`; Alpaca `canceled`/`expired`; tastytrade
   `Rejected`/`Cancelled`/`Expired` (confirmed, §1). **Anything else books**, including values no
   adapter emits today — this is a rejection list, not an allowlist (spec §3.2).
3. **No stop** — `strategy.stop is None or strategy.stop <= 0` (spec §6.2). The door half; the write
   half is §2.5.
4. **The contract does not parse, or disagrees with the arm** — `option_symbol.split("|")` must be
   exactly four parts `SYM|STRIKE|EXPIRY|RIGHT` with `SYM == strategy.symbol`, `float(STRIKE) > 0`,
   `date.fromisoformat(EXPIRY)` succeeding, `RIGHT in {"C","P"}`, and RIGHT agreeing with
   `strategy.direction` (C ↔ Bullish, P ↔ Bearish). Unconditional (spec §6.3.1): a bad shape kills
   the live quote, `PREMIUM_STOP` and `TIME_STOP` and dodges the `unique` duplicate check; a symbol
   mismatch watches the wrong underlying; a right/direction mismatch compares the stop on the wrong
   side. (The OCC-form fixtures in the tests fail this, on purpose — §5.)
5. **No entry** — `strategy.entry_premium <= 0`. **Defence in depth, not a live path**: `arm()`
   refuses it (`auto_trader.py:2074`), so no armed strategy has one (spec §3.1).
6. **The body does not build** — `PortfolioPositionCreate(...)` raises.
7. **The write fails** — §2.3 step 3.

### 2.5 `stop_required` — `position_writer.py`

`create_position(..., stop_required: bool = False)`, keyword-only, default False (the card path is
unchanged: the POST /api/portfolio suite passes unedited). When True, **immediately after the
re-anchor block and before the wrong-side check** (i.e. after `:237`, before `:239`), if
`_floor_stop(adjusted_stop) is None` it raises `HTTPException(422, "... no usable stop after the
re-anchor ...")`. That point is before the risk-check SELECT and long before `db.add` (`:506`), so no
row and no pending write can exist when it raises. It closes spec §6.2's write half: a stop armed
above zero that the `(live − scan)` re-anchor drives to ≤ 0 is stored as NULL by `_floor_stop` today
(the comment at `:212` says so); with the flag it is refused instead. The module docstring gains one
paragraph for the flag.

### 2.6 The mapping — `fired.strategy` → `PortfolioPositionCreate`

Built with the create schema's **field names** (camelCase; `populate_by_name=True` accepts them).

| `PortfolioPositionCreate` | From |
|---|---|
| `recId` | `f"REC-AT-{int(time.time()*1000)}-{uuid4().hex[:8].upper()}"`, generated here, at booking (spec §4.3) |
| `symbol`, `contract`, `direction` | `strategy.symbol`, `strategy.option_symbol` (verbatim — spec §2.6), `strategy.direction` (never derived) |
| `entryPrice` | `strategy.entry_premium` — `create_position` replaces it with the live quote when there is one (spec §3.1) |
| `qty` | `strategy.quantity` — post-sizing (§2.1); with gates off `create_position` books it unresized |
| `entryDate` | `datetime.now(MARKET_TZ).date().isoformat()` (§1) |
| `portfolioValue` | `strategy.portfolio_value` — what `fire()` sized against (`pv` at `:2290`; both callers pass `None`) |
| `premiumStopPct` | `strategy.premium_stop_pct` — the fallback when there is no dollar stop (spec §4.4) |
| `stop`, `stopIsUserSet`, `scanStockPrice`, `structuralStop`, `dteTotal`, `premiumStopDollar` | the step-3 fields of the same (snake_case) name |
| `exitPlan`, `targets`, `maxLossOverride`, `tradeCardSnapshot` | **`copy.deepcopy`** of the step-3 field. Frozen is shallow and `_dc_replace` shares these containers with the pre-sizing object (step 3 §4), and the JSON columns would otherwise hold the strategy's own objects. Copying costs nothing and removes the question. |
| `pickedMethod` … `pickedAt` | the five `picked_*` fields (Phase G) |

`PortfolioPositionCreate` is never looser than `ArmRequest` on any of the ten (step 3 §2.1), so a value
the arm accepted cannot fail the create schema on a bound; test 13 pushes the arm's boundary values
through it (step 3 round 2's below-gate item 3).

### 2.7 The two call sites

**`routers/auto_trade.py:fire_now`.** `fired = auto_trader.fire(...)` inside the existing
`try/except (ValueError, RuntimeError)` (`:199-226`), unchanged. **After and outside it**:
`booking = await book_fired_order(fired, db)`. The response is
`{order_id, status, broker, booked, rec_id, book_error, over_exposure}` — **always 200 once the order
went through**, whatever the booking did (spec §6.1). A pre-O4 client ignores the four new keys; the
alert (§2.8) is what reaches a human regardless of the bundle (spec §6.5(b)).

**`routers/scan.py:run_scan`.** `fired = await asyncio.to_thread(...)` at `:1806`, then
`if fired is not None: booking = await book_fired_order(fired, db)` and one log line (INFO booked /
ERROR not booked). Still on the event loop, `db` in scope; the session never enters the worker thread.
The guard is what threads past `test_scan_session.py`'s `SimpleNamespace` double, which returns `None`
implicitly and whose `_FakeDb` has no `commit`. Nothing is pending on `db` at this point:
`_execute_scan_core` does not write and `_upsert_session` commits its own work (`scan.py:1285`) after.
The booking adds its network round-trip (the writer's 8s-bounded quote fetch) to the scan response;
accepted.

### 2.8 The two alerts — through `_alert_refusal`, from a worker thread

Two wording helpers in `auto_trade_booking.py`, each calling
`await asyncio.to_thread(auto_trader_module._alert_refusal, symbol, what, reason, rec_id_key, alert_type, discrete=True)`
inside its own `try/except Exception` (log and continue — `_alert_refusal` never raises, the guard is
for the thread hop). `auto_trader_module` is looked up at call time so a test patch lands.

| | Not booked | Booked over the exposure cap |
|---|---|---|
| alert type | `AUTO_TRADE_NOT_BOOKED` | `AUTO_TRADE_BOOKED_OVER_EXPOSURE` |
| dedup key | `_per_symbol_rec_id("auto-trade-not-booked", symbol)` | `_per_symbol_rec_id("auto-trade-over-exposure", symbol)` |
| wording | Refusals 1–2: *the broker's answer reads as NOT live (status / no id); nothing was booked; verify at the broker.* Refusals 3–7: *the broker ACCEPTED order {id} ({status}); NO position was booked, so there is no stop alert and no P&L for it: {reason}. Add it by hand or close it at the broker.* | *order {id} was booked as {rec_id} at the ordered qty {q}, which is past the exposure cap. Nothing was resized — the books match the broker.* |

Per-symbol keys with `discrete=True`: the house rule (`_per_symbol_rec_id`'s docstring) so a second
symbol inside the dedup window is not dropped, and a delivered alert clears its own hold so the next
event pages fresh. `_alert_refusal`'s docstring paragraph "THE RUNNING-LOOP GUARD IS UNREACHABLE TODAY
… the only callers are in maybe_fire_on_scan" becomes false and is corrected in the same commit
(comment only; the guard stays unreachable, because the new callers reach it from a worker thread).

---

## 3. Decisions taken here, and what step 4+5 does not do

- **The wrong-side stop booked with gates off gets no alert of its own** (step 2 open question). It
  already reaches a human: a wrong-side stop fires `STOP_REACHED` Critical — Gmail and Telegram — on
  the first portfolio scan (spec §5.2). A second alert for the same fact adds nothing.
- **No serialization of bookings** (step 2's concurrency open question). Two gates-off bookings racing
  on the exposure snapshot needs two *auto-trade* fires in flight at once, and there is one armed slot,
  consumed atomically: it takes a scan-triggered booking still awaiting its quote while a human re-arms
  and presses Fire now. And a lock inside `book_fired_order` would not cover the race it is part of,
  which is any booking against a concurrent card send (the card path has the same race, logged in
  step 2). Recorded, not closed. (A module-level `asyncio.Lock` would also bind to the first event
  loop that contends it — the `_HESTON_SEMAPHORE` trap already logged.)
- **No fire refusal changes.** `fire()`'s raises, rows and statuses, and `maybe_fire_on_scan`'s six
  handlers, are untouched (spec §9.4).
- **No `direction` on the history row.** `routers/auto_trade.py:242-246` names this as O4's; the
  booked position now carries it (`rec_id` on the row links to it). The row stays as it is.
- **No duplicate-contract pre-check before firing** (spec §10.3 = yaml plan §9.10, Kenneth: warn, do
  not block, popup in the UI). That warning is frontend work (step 6). Here a duplicate is a refused
  booking with the not-booked alert (spec §6.4).
- No frontend change (step 6), no `extra='forbid'` (G5-1), no fill reconciliation (spec §9.2), no
  broker-side stop (spec §9.1).

### 3.1 The state this ships into — read before merging

**Today's frontend sends none of the ten fields**, so every fire from today's `AutoTradeArm` arrives
with `stop=None`, is refused at §2.4.3, and pages *"not booked — no invalidation was armed"*. Nothing is
booked today either; after this step that is **loud** on every fire instead of silent. That is the
honest state of the product until step 6 sends the stop, not a regression — but it means the first
auto-trade Kenneth fires after this merge will page. Step 6 is what makes a live fire book.

---

## 4. Tests — new file `backend/tests/test_o4_step4_booking.py`

The harness is `test_phase_g_arm_pick.py`'s: the auto-trade router on its own app over an in-memory
aiosqlite db, `_market_is_open` and `execute_option_order` patched, the singleton disarmed in
`finally`. Additionally: `_apply_vol_sizing` patched to identity (except test 2), and the three
fetchers patched **on `app.services.auto_trade_booking`** (the live-quote cases return a quote; the rest
return `None`), so nothing reaches the network. Contracts are pipe form (`AAPL|185|2026-06-20|C`).
The alert is observed by patching `app.services.notifications.alert_notifier.notify_alert` with an
`AsyncMock` — the far end of `_alert_refusal`, reached through the real `asyncio.to_thread` +
`asyncio.run`.

1. **Fire now books one position from the armed values** — pick, stop, structural stop, targets,
   exit plan, dte, direction, `contract == option_symbol`, `qty`, `entry_price == entry_premium` (no
   live quote), `entry_date` = today in `MARKET_TZ`, `rec_id` starting `REC-AT-`;
   `(active_tp_method, resolved_tp_price)` is what `seed_tp_from_pick` gives, not `('ladder', None)`.
   Response 200 with `booked: true`, that `rec_id`, `book_error: null`, `over_exposure: false`.
   **Replaces** the tripwire `test_phase_g_arm_pick.py::test_firing_still_creates_no_position_…`.
2. **The booked qty is the post-sizing qty** — `_apply_vol_sizing` patched to `_dc_replace(q=2)` on an
   arm of 4 → row `qty == 2`.
3. **Live quote replaces `entry_premium`** — quote fetcher returns 3.10 → `entry_price == 3.10`.
4. **Re-anchor per `stop_is_user_set`** — price fetcher returns live ≠ scan: a plan stop moves by
   `live − scan`; a user-set stop is stored as sent.
5. **`premium_stop_dollar` is re-derived against the persisted entry** — dollar 1.00, entry 2.50, live
   quote 2.00 → stored fraction 0.50, not 0.40; without a dollar stop, `premium_stop_pct` is stored.
6. **Each refusal books nothing, still returns 200 with the order id, and pages** — parametrised:
   no stop; stop re-anchored to ≤ 0 (the §2.5 write half, `stop_is_user_set` false, scan far above
   live); OCC-form contract; symbol mismatch; right/direction mismatch; order id `""`, `None`,
   `"unknown"`; status `Inactive`, `rejected`, `error`, `canceled`, `Cancelled`, `Expired`, `Rejected`;
   `create_position` patched to raise; `PortfolioPositionCreate` patched to raise. Each: zero rows,
   `booked: false`, `book_error` contains the order id (or says there is none), `notify_alert`
   awaited once with `alert_type="AUTO_TRADE_NOT_BOOKED"`.
7. **An unknown status books** — `"some_new_broker_value"` and `"PreSubmitted"` → one row. Pins that
   refusal 2 is a rejection list.
8. **A duplicate contract** — a row for the contract already exists → `booked: false`, the error names
   the duplicate, still exactly one row, alert paged. Then a `GET`-shaped `select` on the same session
   works (the rollback left it usable).
9. **Over the cap books at the ordered qty and says so** — `app.services.position_writer.check_position_risk`
   patched to `approved=False, adjusted_size=None` (the max-concurrent shape), while `fire()`'s lazily
   imported `portfolio_risk.check_position_risk` is untouched and approves → row `qty` is the ordered
   qty, `over_exposure: true`, `notify_alert` awaited with `AUTO_TRADE_BOOKED_OVER_EXPOSURE`.
10. **The audit record** — a `trade_card_snapshot` → one `AuditEventModel` row for the `rec_id`. Then
    `log_approval` patched to raise → still booked, 200, and the session still answers a `select`.
11. **The alert reaches `notify_alert` from the event loop** — covered by 6 and 9 asserting on
    `notify_alert` itself. A test that only asserted `_alert_refusal` was called would pass against a
    direct call that the running-loop guard silently drops (§1 row 1).
12. **The history row carries the `rec_id`, found by `attempt_id`** — unit test of `record_booking`:
    two rows, the target not last → only the target gains `rec_id`, and it is a new dict object; a
    missing `attempt_id` → `False`, no raise.
13. **The arm's boundary values survive the create schema** — the smallest values `ArmRequest`
    accepts for the ten (and the five `picked_*`) build a `PortfolioPositionCreate` without error.
14. **Containers are copied** — the booked row's `exit_plan`/`targets`/`max_loss_override` are equal
    to, and not the same objects as, the strategy's.
15. **`book_fired_order` never raises** — `auto_trader.record_booking` and the alert helper patched to
    raise → returns an outcome, does not propagate.
16. **`fire()` returns a `FiredOrder`** whose `strategy` is the post-sizing object and whose
    `attempt_id` is the success row's. **`maybe_fire_on_scan` returns it** on a fire, and `None` when
    not armed, stale, and on a refusal (one refusal class is enough — the handlers are unchanged).
17. **The scan path books** — `run_scan` with `_execute_scan_core` patched to one PASS candidate and
    `_upsert_session` patched to a recorder, the real singleton armed, a real session → one row with
    test 1's shape, and `_upsert_session` was reached. Then `create_position` patched to raise → the
    scan still returns its result, `_upsert_session` still reached, the alert paged.
18. **`stop_required`, directly** — `create_position(stop_required=True)` with no stop → 422 and no
    row; with `stop_required` omitted, the same body books with `stop` NULL (the card path unchanged).
    Fetchers passed explicitly (step 1's open question).

## 5. Existing tests swept (the same commit)

- `test_auto_trader.py:66-67, 137-138, 168-169, 4463-4465`: `result.order_id` → `result.result.order_id`
  (variable renamed `fired`).
- `test_auto_trader.py:3446` `test_the_manual_fire_endpoint_fires_the_order_it_checked`: the patched
  `fire` returns a `FiredOrder`, and `rt.book_fired_order` is patched with an `AsyncMock` (its
  `_FakeDb` has no `commit`; the test is about `expect`, not booking).
- `test_phase_g_arm_pick.py`'s tripwire: deleted, replaced by test 1 (spec §2.9 says this is the work,
  not an incidental fix).
- Nothing else reads `fire()`'s or `maybe_fire_on_scan`'s return value (grepped: 36 `svc.fire(` calls
  in `test_auto_trader.py`, one each in `test_phase_g_arm_pick.py` and
  `test_premium_stop_per_position.py`; `test_scan_core.py` only asserts `maybe_fire_on_scan` is not
  called). Any further edit found during the build is listed in the commit message.

Budget: ~250 lines of code (booking module ~170, the rest ~80) and ~450 of tests. One layer.

---

## 6. Obligations handed forward

- **Step 6 (frontend):** send the ten (step 3 §6); read `booked === false` (not `!booked`) and
  `over_exposure` into a caution; `syncFromBackend` on `booked: true`; the duplicate-contract warning
  popup (spec §10.3 / yaml §9.10). Until then, §3.1.

## 7. Done means

- Backend suite: 2891 + the new file's count − 1 (the tripwire) passed, 1 skipped; the only edited
  existing tests are those in §5.
- The POST /api/portfolio suite passes unedited (`stop_required` defaults off).
- `python3 scripts/state.py` exit 0, with a phase entry for O4 steps 4+5 whose probe pins
  `book_fired_order`.
- An adversarial round on the **code** comes back clean at `audit_rule`'s gate before merge.
