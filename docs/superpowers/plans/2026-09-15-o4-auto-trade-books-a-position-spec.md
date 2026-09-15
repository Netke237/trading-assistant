# O4 — The auto-trade fire path books a position

**Status: SPEC, not built. Written 2026-09-15 on `claude/dev-state-reconstruction-hzmzbi`.**

The investigation this spec is built on is `o4_auto_trade_books_a_position` in
`docs/superpowers/PROJECT_STATE.json`, specifically its
`verified_2026_09_15_do_not_re_derive` list. Everything in that list is treated here as measured and
is not re-derived; §2 restates only the parts a reader needs in front of them, and adds the four
things this spec measured on top of it (§2.6–§2.9).

The three open questions in that record are answered in §3, each with the option list it was chosen
from — the rule §3.7 of the Phase G spec established.

---

## 1. What O4 is, in one paragraph

You arm an auto-trade, it fires, the broker takes the order, and Bamendjou **writes nothing down**.
No `PortfolioPosition` is created, so there is no stop alert, no TP alert, no P&L, and no record that
the trade happened at all. Arm AAPL with an invalidation at $140, let it fill, let the stock fall to
$138 — no `STOP_REACHED` fires, because there is no position for `alert_generator` to check. Every
other send path in the product books a position; this is the only door that leaves no trace. O4
closes it: the fire path books a position carrying the stop, the pick and the exit plan that were on
the card when the trade was armed.

O4 is **a record of a trade that already happened**. It is not a new gate, not a change to what the
auto-trader submits, and not a reconciliation against broker fills. Everything O4 declines to do is
in §9, with the reason for each.

---

## 2. What exists today — measured, not remembered

### 2.1 `fire()` destroys the thing that knows what was armed

`AutoTradeService.fire()` (`services/auto_trader.py:198`) clears `_state.strategy` **before** it
executes the order (`:224-225`), and returns an `OrderResult` alone (`:298`). After it returns, the
`ArmedStrategy` is unreachable. Booking a position requires `fire()` to hand that strategy back.
**This is the first design change and it is not optional.**

It is also not merely "return the field you already had": `_apply_vol_sizing` (`:228`) returns a
**new** `ArmedStrategy` via `_dc_replace(strategy, quantity=...)`, so the quantity that reaches the
broker is not the quantity that was armed. The strategy handed back must be the **post-sizing** one,
or the books record a quantity the broker never traded. (`test_phase_g_arm_pick.py:281` already pins
that `_dc_replace` carries the pick across; nothing pins the quantity for a booker, because there
was no booker.)

### 2.2 `OrderResult` carries no fill price

`order_id`, `status`, `broker`, `message` — that is the whole dataclass
(`data/ibkr_paper.py:85-89`, mirrored in `data/tradier_paper.py:54`). No fill price, no filled
quantity. `entry_price` therefore cannot come from the broker response. That is Q1 (§3.1).

### 2.3 Both callers of `fire()` can reach a DB session

The sync/async split is the thing that looks like the blocker and is not.

1. **`POST /auto-trade/fire`** (`routers/auto_trade.py:94`) already takes
   `db: AsyncSession = Depends(get_db)` and already queries `PortfolioPositionModel` at `:99-101` to
   build the exposure snapshot.
2. **`maybe_fire_on_scan`** (`auto_trader.py:325`) is called from `routers/scan.py:1697` inside
   `await asyncio.to_thread(...)`, and `scan.py` holds `db` on **both sides** of that await — it
   queries `PortfolioPositionModel` at `:1693` for the same snapshot.

So in both cases the DB session lives on the event loop, and the booking happens **after** the
thread returns. No DB access ever crosses into the worker thread. §5.3 makes that explicit.

### 2.4 `maybe_fire_on_scan` cannot currently tell its caller anything

It returns `None` unconditionally and wraps the `fire()` call in
`except Exception as exc: logger.error(...)` (`:352-353`). For the scan path to book anything, it
has to return what it fired.

### 2.5 `ArmRequest` carries no stop, and no direction, and no plan

`ArmRequest` (`routers/auto_trade.py:16-78`) has broker, symbol, option_symbol, action, quantity,
order_type, limit_price, conid, entry_premium, portfolio_value, premium_stop_pct and the five
Phase G `picked_*` fields. It has **no invalidation, no direction, no exit plan, no targets, no
structural stop, no rec_id and no entry date**.

`PortfolioPositionCreate` (`schemas/__init__.py:855`) **requires** `recId`, `symbol`, `contract`,
`direction`, `entryPrice` (`gt=0`) and `entryDate`. So O4 is not "book a position on fire" — the arm
request has to grow the fields a position needs first (§4).

**The stop is the one that matters.** Booking with `stop = NULL` reproduces exactly the defect
`DIRECT-SEND-STOP-GATE-2026-09-09` closed: a real filled position that arms no stop alert while
looking completely normal in the portfolio list. §3.3 and §6.2 are where that is handled, and §6.2
is the rule that must not be softened.

The frontend **already holds the stop at arm time and simply does not send it**: `AutoTradeArm`
gained a `resolvedInvalidation` prop when the direct-send stop gate shipped, and both its `disabled`
and its `handleArm` early-return refuse without one (`AutoTradeArm/index.tsx:169`, `:196`). The
value exists at the call site. Only the wire is missing.

### 2.6 `option_symbol` is already in the shape `contract` wants — verified on all four producers

`AutoTradeArm` posts `card.contract` as `option_symbol` (`:185`, `:206`). The card path posts
`toOptionSymbol(card)` (`step-7-trade-card/page.tsx:921-927`). Those are two different expressions
and it matters, because `contract` is a **unique** column (`models/portfolio.py:15`) — two spellings
of one option would be two rows.

They agree, and they agree because every producer of a strike formats it the same way:

| Producer | Expression | Shape |
|---|---|---|
| Live scan card | `f"{symbol}\|{int(strike)}\|{expiry}\|{right}"` | `routers/scan.py:1006` |
| Live scan `contractDetails.strike` | `int(strike)` | `routers/scan.py:1023` |
| Option chain rows (`picked.id`) | `f"{symbol}\|{int(strike)}\|{target_exp}\|{option_type}"` | `data/market.py:605`, `:1281` |
| Step-6 override | `contract: picked.id`, `contractDetails.strike: picked.strike` | `lib/tradeCardOverride.ts:30`, `:47` |
| `toOptionSymbol` | `contractId(symbol, cd.strike, cd.expiry, cd.right)` | `types/domain.ts:764` |

`int(strike)` at every source means `cd.strike` is always an integer, so `contractId()`'s raw-number
interpolation produces the same string `card.contract` already holds. **O4 keeps posting
`option_symbol` and uses it verbatim as `contract`** — it does not introduce a second spelling.

(The OCC-format note at `AutoTradeArm:186-187` is about what a *real* broker API wants. It is
pre-existing, it is not O4's, and §9.5 says so.)

### 2.7 The create path does far more than write a row, and all of it is wanted

`add_position` (`routers/portfolio.py:145-535`) — in order: duplicate-contract 409; two **concurrent
live fetches** (underlying price, contract quote); re-anchor of `stop`/`structuralStop`/`targets` by
`(live − scan)` unless `stopIsUserSet`; a wrong-side-stop 422; replacement of `entryPrice` with the
live quote; the exposure gate; server-side derivation of `premium_stop_pct` from
`premiumStopDollar` **against the persisted entry**; and `seed_tp_from_pick` for the
`(active_tp_method, resolved_tp_price)` pair.

Every one of those is behaviour an auto-trade position should have, and every one of them is the
subject of a recorded audit finding. **Re-implementing any of it inside the fire path is how the two
drift.** §5.1 extracts it instead.

Two of those steps, however, are **pre-trade gates**, and on the fire path the trade is no longer
pre-anything (§5.2).

### 2.8 The backend position row has no provenance column

`PortfolioPositionModel` has no `source`, `source_label`, `ordered_at` or `expiry` column — those are
frontend-only fields on `PortfolioPosition` (`types/domain.ts:459`). So a row written by O4 is, in
the database, indistinguishable from one sent off the card. §4.3 gives it the one handle it can have.

### 2.9 There is a tripwire test and it is supposed to go red

`test_firing_still_creates_no_position_so_the_armed_pick_is_captured_and_unread`
(`backend/tests/test_phase_g_arm_pick.py:304`) asserts `rows == []` after a fire, with a failure
message addressed to whoever writes O4. **O4 makes it fail, and replacing it is part of the work**,
not an incidental test fix — see §8 test 1, which is the §10-test-6 second half that test was
deferring.

---

## 3. Decisions

### 3.1 Q1 — `entry_price` is `entry_premium`

The options were:

- **(a) `limit_price`** — the worst price agreed to. Conservative, and it is the number the Arm
  button showed. But it is `Optional` on `ArmRequest` and is `None` on every `MKT` order.
- **(b) `entry_premium`** — the mid that sizing and both risk gates were computed against.
- **(c) fetch a live contract quote after the order returns** — closest to the truth, but adds a
  network call and a failure mode to the fire path.

**Chosen: (b).** Three reasons, in order of weight:

1. It is the only candidate **guaranteed present** on this endpoint. `limit_price` is null on MKT.
2. It keeps the position consistent with the gate that approved it: `_check_exposure` and
  `_check_daily_loss` both size off `strategy.entry_premium` (`auto_trader.py:308-309`, `:415`).
3. **(c) is not actually forgone.** `add_position` already fetches the contract quote at save time
   and replaces `entry_price` with it when one comes back (`routers/portfolio.py:300-312`). So the
   live price is used when it exists, and `entry_premium` is the fallback for when it does not. The
   choice between (b) and (c) is therefore only a choice of *fallback*, which makes it a much
   smaller decision than it reads as.

**`entry_premium` cannot be zero on an armed strategy, and that was checked rather than assumed.**
`ArmRequest` defaults it to `0.0` and does not bound it, which reads like a hole — but
`AutoTradeService.arm()` raises `ValueError` on `entry_premium <= 0` before anything is stored
(`auto_trader.py:173-177`). So every strategy that can reach `fire()` has a positive one, and (b) can
always satisfy `entryPrice`'s `gt=0`.

§6.3's refusal on a non-positive entry is therefore **defence in depth, not a live path**, and is
labelled as such there. It stays because it is the last thing between a future non-positive entry and
a stored zero, and a stored zero is the one value `entryPrice`'s bound exists to keep out:
`alert_generator` gates `PREMIUM_STOP` on `entry_price > 0`, so a zero-entry position can never raise
a stop alert at all. Do not read its presence as evidence that a zero-entry path exists.

### 3.2 Q2 — Book on submit, not on fill

The options were: book when the order is submitted, or book only once it is known to be filled.

A resting LMT that never fills becomes a phantom position — that is the real cost, and it is stated
here rather than glossed.

**Chosen: book on submit.** All eight existing send paths already do exactly this:
`step-7-trade-card/page.tsx:1026-1038` and `:1077-1089` call `postOptionOrder` and then
`buildPaperPosition` + `persistPosition` **unconditionally**, without ever reading the order status.
Booking on fill here would make O4 the only path in the product with different semantics, and would
require a fill-polling mechanism that does not exist.

Diverging is a bigger change than it looks, and it belongs to a separate "reconcile positions against
broker fills" piece that would fix all nine paths at once. §9.2.

### 3.3 Q3 — The stop, the exit plan, the structural stop, the pick, and the scan anchor travel

The options were **(a)** stop only, or **(b)** stop + `exitPlan` + `structuralStop`.

**Chosen: (b), plus the three fields (b) turns out to require.** The four listed in the question are
not self-sufficient:

- `exitPlan` alone does not make the TP alert work — `seed_tp_from_pick` needs
  `picked_method` **and** `picked_row_stock_price` to produce a non-ladder seed
  (`services/picked_method.py:98-110`), and seeding `active_tp_method` from the pick is the whole
  reason the five `picked_*` fields were carried onto `ArmedStrategy` in the first place. They are
  **already on the wire**; O4 only has to read them.
- `stop` alone is not enough to store a stop correctly. `add_position` re-anchors it by
  `(live − scanStockPrice)` unless `stopIsUserSet` is true, so **`scan_stock_price` and
  `stop_is_user_set` must travel with it** or a typed $180 stop on a stock scanned at $145 and now
  trading at $200 is stored as $235 — above spot, and `alert_generator`'s bullish `price <= pos.stop`
  raises a Critical `STOP_REACHED` on the first scan. That is a recorded round-9 defect, not a
  hypothetical.
- `direction` is required by the schema and is not derivable safely — see §4.2.

The full field list, and what each is for, is §4.1.

---

## 4. The wire

### 4.1 `ArmRequest` grows eleven fields

All snake_case with **no alias**, matching every existing field on this schema and the
`ArmedStrategy(**req.model_dump())` construction at `routers/auto_trade.py:81` that keys off field
*names*. All Optional, all defaulting to the value that reproduces today's behaviour.

| Field | Type | Why it travels |
|---|---|---|
| `direction` | `Optional[Direction]` | Required by `PortfolioPositionCreate`. §4.2. |
| `stop` | `Optional[float]` | **The non-negotiable.** Drives `STOP_REACHED`. Bounded `gt=0` — a stop is a stock price and zero is never one. |
| `stop_is_user_set` | `Optional[bool]` | Exempts a typed stop from the re-anchor. Without it, §3.3's round-9 defect. |
| `scan_stock_price` | `Optional[float]`, `gt=0` | The anchor the re-anchor measures from, and `entry_stock_price` on the row. |
| `structural_stop` | `Optional[float]`, `gt=0` | Plan-derived; re-anchored by the router like the targets. |
| `exit_plan` | `Optional[dict]` | The rows `seed_tp_from_pick` maps an arithmetic pick against. Persisted verbatim. |
| `targets` | `list[dict] = []` | The ladder. Re-anchored by the router. |
| `dte_total` | `Optional[int]`, `ge=0` | Time-decay display and the time-stop readout. |
| `premium_stop_dollar` | `Optional[float]`, `gt=0` | §4.4. |
| `max_loss_override` | `Optional[dict]` | Parity with the card path (Feature 5, carried at creation). |
| `trade_card_snapshot` | `Optional[dict]` | The "why was this bought" record. Parity with the card path. |

`ArmedStrategy` gains the same eleven, with the same defaults, carried by the existing
`ArmedStrategy(**req.model_dump())` — no new mapping code, and `_dc_replace` carries them across
vol-sizing for free (the mechanism `test_phase_g_arm_pick.py:281` already pins for the pick).

**No field is made required.** Making one required is a behaviour change to a live endpoint of
exactly the class G5-1 was deferred for, and it is not needed: a request missing the stop is refused
at **booking** time (§6.2), which is strictly louder than a 422 at arm time because it names a real
order that has already gone to a broker.

### 4.2 `direction` is optional on the wire and derived when absent — never guessed

`Direction` is `'Bullish' | 'Bearish'`. The frontend always sends it (`card.direction`). When it is
absent — a pre-O4 client, a direct API call — it is **derived from `action` and the contract right**:

| `action` | right | direction |
|---|---|---|
| `BUY` | `C` | Bullish |
| `BUY` | `P` | Bearish |
| `SELL` | `C` | Bearish |
| `SELL` | `P` | Bullish |

The right is the fourth segment of `option_symbol`. **If `option_symbol` does not parse as
`SYM|STRIKE|EXPIRY|C/P`, the booking is refused** (§6.3) — it is not defaulted to Bullish. Direction
decides which side of the underlying `alert_generator` treats as a stop breach
(`price <= stop` vs `price >= stop`), so a wrong direction is not a cosmetic field: it is a stop that
silently never fires. Guessing it is worse than not booking.

The `SELL` rows are written out rather than assumed away because `action` is
`Literal["BUY", "SELL"]` on the schema even though `AutoTradeArm` hardcodes `'BUY'`
(`AutoTradeArm:207`). The table is what the schema permits, not what the one live caller sends.

### 4.3 `rec_id` and `entry_date` are generated server-side, at booking time

- **`rec_id`**: `f"REC-AT-{int(time.time() * 1000)}-{uuid4().hex[:4].upper()}"`. The `AT` segment is
  the only provenance handle an O4 row can have (§2.8), and it costs nothing. It is **not** on the
  arm request and **not** generated at arm time: an arm that is disarmed, or goes stale and is
  dropped by the age guard (`auto_trader.py:339-347`), must not burn an id, and a re-arm must not
  reuse one.
- **`entry_date`**: `datetime.now(timezone.utc).date().isoformat()` at booking time. The card path
  uses `todayISO()` for the same field.

Nothing parses `rec_id`'s shape today; the prefix is for a human reading the table.

### 4.4 `premium_stop_dollar` joins `premium_stop_pct` — both, not either

`ArmRequest` already has `premium_stop_pct`, and `AutoTradeArm` derives it client-side by dividing
the card's dollar stop by `entry_premium` (`AutoTradeArm:224`). The auto-trader needs that fraction:
`_check_daily_loss` and the history's `premium_at_risk` both size off it.

But piece 4's whole lesson is that a **fraction** anchored client-side is wrong on the persisted
position, because `add_position` may replace `entry_price` with a live quote and the fraction is then
measured against a price the order was never placed at. `$3.12` on a `$5.20` mid is 60%; on a `$4.00`
fill it should be 78%, not 60%. That is why `PortfolioPositionCreate` prefers `premiumStopDollar` and
derives the ratio server-side (`routers/portfolio.py:369-371`).

So **both travel, and they are used for different things**:

- `premium_stop_pct` → the auto-trader's sizing and gates. Unchanged, still client-derived.
- `premium_stop_dollar` → passed to `PortfolioPositionCreate.premiumStopDollar`, which re-derives the
  fraction against the persisted entry.

`AutoTradeArm` already has the dollar value in hand: the `premiumStopDollar` prop it currently only
converts. It sends it as well.

When `premium_stop_dollar` is absent, `premium_stop_pct` is passed through as
`premiumStopPct` — which is the existing fallback the create schema already documents, not a new one.

---

## 5. The shape of the change

### 5.1 `add_position`'s body becomes a service function

**New: `backend/app/services/position_writer.py`**

```python
async def create_position(
    body: PortfolioPositionCreate,
    db: AsyncSession,
    *,
    enforce_pre_trade_gates: bool = True,
) -> tuple[PortfolioPositionModel, Optional[int]]:
```

It is `add_position`'s body from the duplicate-contract check through `await db.refresh(position)`,
moved verbatim, returning `(position, risk.adjusted_size)`.

`routers/portfolio.py:add_position` becomes a thin wrapper: call it with the default, then do the two
things that are the router's and not the writer's — `log_approval` for
`tradeCardSnapshot`, and `PortfolioPositionSchema.from_orm_model` + `adjustedQty` on the response.

**Why extract rather than write a second writer.** §2.7: everything `add_position` does is behaviour
an auto-trade position should have, and every line of it is the subject of an audit finding. A second
writer means two of them, and this codebase has a standing rule about that
(`buildPaperPosition` "MUST match what `positionFromOrder` produces", `premiumStop.ts:189`).

**The extraction is behaviour-preserving and the existing suite is the proof.** Every current test of
`POST /api/portfolio` goes through the extracted function unchanged, and none of them may be edited
as part of this step (§8 test 10). If one needs editing, the extraction was not faithful.

### 5.2 `enforce_pre_trade_gates=False` — what it turns off, and why

Two of `add_position`'s steps are **pre-trade** gates. On the fire path the order is already at the
broker, so re-running them can only produce "we refuse to write down a trade that already happened",
which is the defect O4 exists to fix, reintroduced one layer up.

**The exposure gate** (`routers/portfolio.py:329-343`). With gates off:
- `risk.approved == False` does **not** raise 422. It logs a warning and books anyway.
- `risk.adjusted_size` does **not** shrink `qty`. The position records **the quantity that was
  ordered**, which by §2.1 is the post-`_apply_vol_sizing` quantity.

  This one is the sharper of the two: silently booking 3 contracts when the broker traded 5 is worse
  than not booking at all, because the P&L, the premium-at-risk and every exposure check downstream
  are then computed off a number that never happened. **The books match the broker, not the gate.**

  The gate is not skipped for safety reasons either — `fire()` already ran `_check_exposure` against
  the same `check_position_risk` **before** the order was placed (`auto_trader.py:301-321`). The
  pre-trade check happened. This is the post-trade record.

**The wrong-side-stop guard** (`routers/portfolio.py:270-287`). With gates off it **warns instead of
raising**. A wrong-side stop fires `STOP_REACHED` immediately, which is loud and wrong — but the
alternative here is no position at all, which is silent and wrong, and a stop that fires on the first
scan is visible in the drawer and correctable in one edit. This path is also already guarded twice
upstream: the card bounds the invalidation directionally against the live quote at edit time, and
`AutoTradeArm` refuses to arm a card with no stop at all.

**What `enforce_pre_trade_gates=False` does NOT turn off**, and must not:
- the duplicate-contract 409 — a uniqueness constraint, not a gate (§6.4);
- the live refetch, the re-anchor, the `entryPrice` replacement;
- the premium-stop derivation;
- `seed_tp_from_pick`.

### 5.3 `fire()` hands the strategy back; the callers book

**`auto_trader.py`:**

```python
@dataclass
class FiredOrder:
    result:   OrderResult
    strategy: ArmedStrategy   # post-vol-sizing — the one the broker actually got
```

- `fire()` returns `FiredOrder` instead of `OrderResult`. Every raise path is unchanged.
- `maybe_fire_on_scan()` returns `Optional[FiredOrder]`: the `FiredOrder` on success, `None` on
  every existing early return, and `None` on a swallowed exception — its `except Exception` and its
  `logger.error` stay exactly as they are (§9.4).

**New: `backend/app/services/auto_trade_booking.py`**

```python
async def book_fired_order(fired: FiredOrder, db: AsyncSession) -> BookingOutcome:
```

`BookingOutcome` is `(booked: bool, rec_id: Optional[str], error: Optional[str])`. It builds the
`PortfolioPositionCreate` from `fired.strategy` per §4, calls
`create_position(..., enforce_pre_trade_gates=False)`, and **never raises** (§6.1).

**The two call sites:**

1. `routers/auto_trade.py:fire_now` — after the existing `try/except (ValueError, RuntimeError)`
   that maps a fire failure to 400, and **outside** it. The response grows three keys (§7.1).
2. `routers/scan.py:1691-1700` — `await asyncio.to_thread(...)` now returns the `Optional[FiredOrder]`;
   when it is not `None`, `await book_fired_order(fired, db)` **on the event loop**, with `db` — the
   same session already in scope. The booking result is logged and nothing else: a booking failure
   must not fail the scan request (§6.1).

The DB session never enters the worker thread. That is the whole answer to the sync/async split, and
it is why the split was never the blocker it looked like.

### 5.4 The fire history gains `rec_id`

The history entry appended at `auto_trader.py:288-295` gains `"rec_id": None`, filled in by the
caller after a successful booking (a small mutation method on the service, under the lock). It is the
only link between "the auto-trader fired this" and "this position exists", and §2.8 says the position
row cannot carry the reverse link.

A failed booking appends nothing new — the fire entry already exists and its `rec_id` stays `None`,
which is a readable state: *fired, not booked*.

---

## 6. The rules that must not be softened

### 6.1 A booking failure is never reported as an order failure

The order is at the broker. `book_fired_order` **catches every exception**, including the
`HTTPException`s `create_position` still raises, and returns a `BookingOutcome` with `booked=False`
and a human-readable `error`.

This is the same reasoning `add_position` already applies to `log_approval`
(`routers/portfolio.py:522-527`: "a failure here must never turn an already-persisted position into
an apparent 500") and the same reasoning §4.4 of the Phase G spec gives for guarding the config read:
**every send path places the order first and persists second, so an exception in the persist step
does not prevent a trade — it loses the record of a trade that already happened.**

`POST /auto-trade/fire` therefore returns **200** with `booked: false` when the order went through
and the booking did not. It must never return 4xx or 5xx in that case, because the client reads that
as "the order did not happen" and the user's next action is to try again.

### 6.2 No stop, no position — and say so

**If `strategy.stop` is `None` or `<= 0`, `book_fired_order` books nothing**, returns
`booked=False, error="no invalidation was armed — position not booked"`, and logs at `error` level.

This is the one rule §2.5 identifies as non-negotiable, and the direction of the refusal is
deliberate. The counter-argument is real and is recorded rather than dismissed: a position with a
NULL stop would at least give P&L, a TP alert and a visible record, where no position gives nothing.
It is refused anyway, because *a real filled position that arms no stop alert while looking
completely normal in the portfolio list* is precisely the defect `DIRECT-SEND-STOP-GATE` was written
to close, and O4 must not reopen it on a ninth path. A missing record is a known gap; a record that
looks protected and is not is a trap.

A live user cannot reach this: `AutoTradeArm` refuses to arm a card with no stop, on both the button
and the request. Reaching it means a pre-O4 client or a direct API call, and those get the loud
version.

### 6.3 Three more refusals, for the same reason

`book_fired_order` also books nothing, and reports why, when:

1. **`option_symbol` does not parse** as `SYM|STRIKE|EXPIRY|C/P` and `direction` was not sent — §4.2.
   A guessed direction is a stop that never fires.
2. **No usable entry price**: `entry_premium <= 0`. **DEFENCE IN DEPTH, not a live path** —
   `arm()` already rejects a non-positive `entry_premium` (§3.1), so no armed strategy reaching here
   can have one. It stays for the reason `add_position`'s sibling branch states at
   `routers/portfolio.py:352-367`: it is the last thing between a future non-positive entry and a
   stored zero, which can never raise a `PREMIUM_STOP` alert. Checked on the *armed* value rather
   than after the router's live-quote replacement, so the refusal does not depend on network
   weather.
3. **`create_position` raises anything at all** — §6.1.

Every refusal produces a `book_error` string that names the order id, so the log line and the API
response both point at a real order the user can find at the broker.

### 6.4 A duplicate contract is reported, not swallowed and not raised

`contract` is unique. If the user already holds the option — from a card send, or from a previous
auto-trade — `create_position` raises 409 and O4 books nothing. That is caught like any other failure
(§6.1) and reported as `book_error`.

It is **not** merged into the existing position. The backend has never merged (only the frontend's
`portfolioStore.addPosition` does, locally), and making O4 the first path that does would be a
change to portfolio semantics on every path at once. §9.3.

---

## 7. The frontend

### 7.1 The `/fire` response grows three keys

```
{ order_id, status, broker,  booked: bool, rec_id: string | null, book_error: string | null }
```

Additive, so `handleFireNow`'s existing `res.order_id` read is unaffected.
`frontend/lib/api.ts:634` widens `fireAutoTrade`'s return type to match.

### 7.2 `AutoTradeArm` sends eleven more fields and surfaces one result

**Sends** (`handleArm`, `AutoTradeArm/index.tsx:203-241`) — every value is already in the component
or is already resolved by its caller:

| Wire field | Source |
|---|---|
| `direction` | `card.direction` |
| `stop` | `resolvedInvalidation ?? card.exit.invalidation` — **the same expression `stopMissing` is derived from at `:169`** |
| `stop_is_user_set` | a new prop, resolved by the caller exactly as `buildPaperPosition` resolves `invalidationIsUserSetFor(card)` |
| `scan_stock_price` | `card.price` |
| `structural_stop` | a new prop — the caller's `structuralBySymbol[card.symbol]?.stop?.price ?? null` |
| `exit_plan` | a new prop — the caller's `exitPlanByContract[contractKeyFor(card)]?.plan ?? null` |
| `targets` | `card.exit.targets` |
| `dte_total` | `card.contractDetails?.dte` |
| `premium_stop_dollar` | the existing `premiumStopDollar` prop, sent as well as converted (§4.4) |
| `max_loss_override` | a new prop — the caller's `maxLossOverrideBySymbol[card.symbol] ?? null` |
| `trade_card_snapshot` | a new prop — the caller's `tradeCardSnapshotOf(card)` |

**The stop field reads the same expression the gate reads.** That is the invariant: the value that
decides whether the button is enabled and the value that is posted must not be two readings. Anything
else and the gate can pass on one number while the wire carries another — which is the shape of the
defect `c41145ba` had to go back and close on seven paths.

**Surfaces:** `handleFireNow` already stores `res.order_id`. It additionally reads `res.booked`, and
when it is `false` renders a **caution**, not an error, beside the order id — the order *worked*;
the record did not. The copy names the consequence in plain words, e.g.
*"Order 888 placed, but no position was recorded — this trade has no stop alert. Add it manually from
the Portfolio page."* Claiming anything less specific here would be the mistake §9.2 of the Phase G
spec warns about.

The five new props follow `resolvedInvalidation`'s established contract: resolved at the call site
by the same expression `buildPaperPosition` uses, so arming and sending cannot describe the same card
differently. Step 7 is the only call site and it already computes all five.

---

## 8. Tests

1. **`fire_now` books one position carrying the ARMED pick, not a live one.** This is Phase G §10
   test 6's second half as originally written, and it **replaces**
   `test_firing_still_creates_no_position_so_the_armed_pick_is_captured_and_unread`
   (`test_phase_g_arm_pick.py:304`). Arm with the pick, fire, assert exactly one row with
   `picked_method`, `picked_row_stock_price`, `picked_row_option_price`, `picked_stop_basis`,
   `picked_at` equal to the armed values — and assert `active_tp_method` / `resolved_tp_price` are
   the pair `seed_tp_from_pick` produces from them, not `('ladder', None)`.
2. **The booked quantity is the post-vol-sizing quantity.** Arm 4, force `_apply_vol_sizing` to
   resize (the `test_phase_g_arm_pick.py:281` fixture shape), assert the row's `qty` is the resized
   number and not 4. §2.1.
3. **`entry_price` is the live quote when there is one, `entry_premium` when there is not.** Two
   cases, one mock each. §3.1.
4. **The stop is stored, re-anchored or not, per `stop_is_user_set`.** Two cases: a plan stop shifts
   by `(live − scan)`; a user-set stop is stored verbatim. §3.3.
5. **No stop armed → the order fires and nothing is booked.** Assert 200, assert `order_id` present,
   assert zero rows, assert `book_error` names the missing invalidation. §6.2.
6. **A booking failure is not an order failure.** Patch `create_position` to raise, fire, assert
   **200**, `order_id` present, `booked is False`, `book_error` non-null, zero rows. §6.1.
7. **The risk gate does not resize or reject on this path.** A portfolio that makes
   `check_position_risk` return `approved=False` (and one that returns an `adjusted_size`) still
   books the full ordered quantity. §5.2.
8. **A duplicate contract reports and does not raise.** Book once, fire again for the same contract,
   assert 200, `booked is False`, `book_error` mentions the duplicate, and still exactly one row.
   §6.4.
9. **The scan path books too.** Drive `maybe_fire_on_scan` through `scan.py`'s call site with a DB
   session; assert a row appears with the same shape as test 1. Then make the booking raise and
   assert the scan request still succeeds. §5.3.
10. **The extraction is faithful.** The entire existing `POST /api/portfolio` suite passes
    **unedited**. Any test that needs changing means `create_position` is not `add_position`'s body.
11. **`direction` derivation.** Four cases from §4.2's table, plus: an unparseable `option_symbol`
    with no `direction` books nothing and reports why. §6.3.
12. **Frontend — `AutoTradeArm` posts the stop it gated on.** Render with a
    `resolvedInvalidation` that differs from `card.exit.invalidation`, click Arm, assert the request
    body's `stop` is the resolved one. The sibling of
    `direct-send-stop-gate.test.tsx`'s existing assertions.
13. **Frontend — `booked: false` renders the caution.** Fire with a mocked response carrying
    `booked: false`, assert the copy naming the missing stop alert is on screen. §7.2.

---

## 9. What O4 does NOT do, and why each

### 9.1 No stop order at the broker
The stop is an alert, exactly as it is on all eight other paths. The auto-trader places no protective
order today and O4 does not change that. This is worth stating because §6.2's refusal could be
misread as implying the booked stop is *enforced*; it is watched, not enforced.

### 9.2 No reconciliation against fills
Q2 (§3.2). A resting LMT that never fills becomes a phantom position, on this path and on the eight
that already behave this way. Fixing it is one piece covering all nine, not a divergence introduced
here.

### 9.3 No merge into an existing position
§6.4. The backend has never merged duplicate contracts and O4 is not where that changes.

### 9.4 No change to `maybe_fire_on_scan`'s error swallowing
It keeps its `except Exception` and its `logger.error`. That behaviour is a separate question — an
auto-trade that fails to fire is currently silent to the user — and changing it inside O4 would mix a
notification change into a persistence change. O4 only adds a return value.

### 9.5 No OCC symbol conversion
`option_symbol` stays Bamendjou's pipe id. §2.6 shows that is the right shape for `contract`; the
`AutoTradeArm:186-187` note about real broker APIs is pre-existing and separately tracked.

### 9.6 No `extra='forbid'` on `ArmRequest`
That is G5-1, deliberately sequenced **after** O4 because O4 grows this same schema. O4 must not
quietly do half of it: adding eleven fields does not change the fact that an unknown key still
returns 200 today.

### 9.7 No retrofit of auto-trades already fired
There is nothing to retrofit from. The history entries at `auto_trader.py:288-295` carry no stop, no
direction and no pick — only order id, status, broker, symbol, option and premium-at-risk. Past
fires stay unrecorded.

### 9.8 No change to the daily-loss or exposure arithmetic
`_check_exposure` and `_check_daily_loss` are untouched, including the open question about sizing the
daily-loss gate on the full premium rather than the premium stop. O4 reads `entry_premium`; it does
not re-decide what it means.

---

## 10. Open, and Kenneth's

Nothing in §3 is left open — Q1, Q2 and Q3 are answered above with their option lists. Two things
are flagged, neither blocking:

1. **The phantom-position cost of §3.2 is accepted, not solved.** If Kenneth wants fill
   reconciliation, it is its own piece and it covers nine paths, not one.
2. **§6.2's direction of refusal is arguable** and the counter-argument is written into §6.2 rather
   than omitted. It follows the constraint recorded in
   `o4_auto_trade_books_a_position.open_questions_for_kenneth`; if Kenneth reverses it, only §6.2 and
   test 5 change.

---

## 11. Build order

Each step ends green — backend `pytest`, frontend `npx jest`, `npm run typecheck`, `scripts/state.py`.

1. **Extract `create_position`** (§5.1). No behaviour change, no new fields. Green on the existing
   suite **unedited** is the gate for this step, and test 10 is the proof.
2. **Add `enforce_pre_trade_gates`** (§5.2). Still no caller passes `False`; the parameter and its
   two branches land with unit tests for both.
3. **Grow `ArmRequest` / `ArmedStrategy`** (§4.1, §4.2, §4.4). Fields travel and are unread — the
   same shape Phase G build step 5 had, and the same honest description of it.
4. **`FiredOrder` + `book_fired_order`** (§5.3, §6). Wire `POST /auto-trade/fire` first, because it
   is the path with a test harness already built (`test_phase_g_arm_pick.py`'s fixtures). Tests 1–8
   and 11 land here, and the tripwire is replaced here.
5. **Wire the scan path** (§5.3 caller 2). Test 9.
6. **Frontend** (§7). Tests 12–13.

Then one adversarial round on the build, at the `audit_rule` v2 gate, before anything merges.

**Before any of it: one adversarial round on this spec.**
