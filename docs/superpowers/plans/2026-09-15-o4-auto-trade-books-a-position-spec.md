# O4 — The auto-trade fire path books a position

**Status: SPEC, not built. Written 2026-09-15 on `claude/dev-state-reconstruction-hzmzbi`.**
**Revised 2026-09-17 after adversarial rounds 1 (10 gate-level, 13 below-gate) and 2
(11 gate-level, 7 below-gate) — see §12 and §13.**

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

**Chosen: book on submit — but "submit" means the broker took it, not merely that it answered.**
Round 1 separated two cases this section had conflated. Every adapter raises on HTTP >= 400, but
returns an `OrderResult` unexamined when the broker answers **200 with a rejection in the body**:
`status=str(data.get("status", "unknown"))` (`data/tradier_paper.py:124-130`),
`status=str(data.get("order_status", "Unknown"))` (`data/ibkr_paper.py:142-147`), and the same shape
in `data/tastytrade_paper.py:129-133`. `fire()` returns it without inspecting `status`
(`auto_trader.py:296`).

A rejected order is **not** the §9.2 fill-polling problem: it is knowable now, from a response already
in hand, with no new mechanism. Booking it would create a phantom position carrying a stop, a TP and
a P&L for contracts that do not exist — and on the scan trigger, with no human ever seeing the order
id to reconcile against, every downstream exposure cap and `premium_at_risk` would be computed off
it.

**So `book_fired_order` books nothing when `result.status` is a known-terminal rejection**, and
reports it as `book_error` naming the status.

**The list is per-broker, because round 2 found the generic one missed the actual strings.** All four
adapters in `ArmRequest.broker`'s `Literal` (`routers/auto_trade.py:17`) raise on HTTP >= 400 and pass
the body's status through unexamined:

| Broker | Source | Rejection strings |
|---|---|---|
| IBKR | `data/ibkr_paper.py:142-147`, `order_status` | **`Inactive`** — the Client Portal API reports a rejected or killed order this way, with the reason in `message`; it does **not** say `Rejected` |
| Tradier | `data/tradier_paper.py:124-130`, `status` | `rejected`, **`error`** |
| Alpaca | `data/alpaca_paper_execution.py:65-74`, `status` | `rejected`, `canceled`, `expired` |
| tastytrade | `data/tastytrade_paper.py:129-133`, `str(response.order.status)` | `Rejected`/`Cancelled` — **UNVERIFIED**: this stringifies an SDK enum and the SDK is not installed here, so whether it yields `"Rejected"` or `"OrderStatus.REJECTED"` is unconfirmed. **Build step 4 confirms it against the installed package before writing the match**, and matches on a substring rather than equality if it is the enum form. |

Matching is case-insensitive. Anything else — `filled`, `submitted`, `pending`, `accepted`, `ok`,
`unknown` — books, because the point of §3.2 is not to wait for a fill. An unrecognised status books
rather than refuses: this check catches a *stated* rejection and must not become an allowlist that
silently stops booking when an adapter adds a value. **§8 test 15 pins both directions, per broker.**

Otherwise, book on submit. All eight existing send paths already do exactly this:
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
`ArmedStrategy(**req.model_dump())` construction at `routers/auto_trade.py:83` that keys off field
*names*. All Optional, all defaulting to the value that reproduces today's behaviour.

| Field | Type | Why it travels |
|---|---|---|
| `direction` | `Optional[Direction]` | Required by `PortfolioPositionCreate`. §4.2. |
| `stop` | `Optional[float]` | **The non-negotiable.** Drives `STOP_REACHED`. Bounded `gt=0` — a stop is a stock price and zero is never one. |
| `stop_is_user_set` | `Optional[bool]` | Exempts a typed stop from the re-anchor. Without it, §3.3's round-9 defect. |
| `scan_stock_price` | `Optional[float]`, `gt=0` | The anchor the re-anchor measures from, and `entry_stock_price` on the row. |
| `structural_stop` | `Optional[float]`, `gt=0` | Plan-derived; re-anchored by the router like the targets. |
| `exit_plan` | `Optional[dict]` | The rows `seed_tp_from_pick` maps an arithmetic pick against. Persisted verbatim. |
| `targets` | `list[dict] = []` on the pydantic schema; **`field(default_factory=list)` on the dataclass** | The ladder. Re-anchored by the router. `ArmedStrategy` is a `@dataclass`, so a bare `[]` default raises `ValueError: mutable default` at import — the house form is already there at `auto_trader.py:66` (`history: list[dict] = field(default_factory=list)`). Round 1; "the same eleven, with the same defaults" below does not literally apply to this one row. |
| `dte_total` | `Optional[int]`, `ge=0` | Time-decay display and the time-stop readout. |
| `premium_stop_dollar` | `Optional[float]`, `gt=0` | §4.4. |
| `max_loss_override` | `Optional[dict]` | Parity with the card path (Feature 5, carried at creation). |
| `trade_card_snapshot` | `Optional[dict]` | The "why was this bought" record. Parity with the card path. |

`ArmedStrategy` gains the same eleven, with the same defaults (with the `targets` exception noted in
its row above), carried by the existing
`ArmedStrategy(**req.model_dump())` at `routers/auto_trade.py:83` — no new mapping code, and `_dc_replace` carries them across
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
- **`entry_date`**: `datetime.now(timezone.utc).date().isoformat()` at booking time. **This is NOT
  parity with the card path, and the original claim that it was is withdrawn.** `todayISO`
  (`step-7-trade-card/page.tsx:55-59`) is `getFullYear`/`getMonth`/`getDate` — **browser local**. For
  Kenneth in US/Eastern the two clocks disagree on every booking after 20:00 ET. UTC is kept as the
  server-side choice (a server has no business guessing a browser's timezone), and the divergence is
  recorded rather than papered over: `entry_date` is read only for display and holding-period
  (`portfolio.py:732`), no alert or P&L path touches it, so the cost is one date that can read a day
  early on a late-evening auto-trade. Round 1.

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

**`portfolio_value` travels too.** It is not one of the eleven because `ArmRequest` already carries it
(`routers/auto_trade.py:29`) and `AutoTradeArm` already sends the real value from `useRiskStore`
(`index.tsx:228`) — but nothing said `book_fired_order` passes it into
`PortfolioPositionCreate.portfolioValue`, which defaults to 50 000 (`portfolio.py:335`). Round 1.
It feeds the `risk` result — which §5.2 suppresses for *sizing*, but which §5.2's `over_exposure` flag
now **reads**. Round 2 caught round 1 calling it "inert today": it is not, and was not by the end of
the same revision. A wrong `portfolio_value` now produces a wrong `over_exposure`. Pass it. (The
50 000 default lives on the schema, `schemas/__init__.py:904` — not `portfolio.py:335`, which is the
consumer.)

---

## 5. The shape of the change

### 5.1 `add_position`'s body becomes a service function

**New: `backend/app/services/position_writer.py`**

```python
@dataclass
class WriteOutcome:
    position:       PortfolioPositionModel
    adjusted_size:  Optional[int]   # what the gate WOULD have resized to; None if it would not
    over_exposure:  bool            # risk.approved was False — the booking went past a cap

async def create_position(
    body: PortfolioPositionCreate,
    db: AsyncSession,
    *,
    enforce_pre_trade_gates: bool = True,
    stop_required: bool = False,
) -> WriteOutcome:
```

**Round 2 rewrote this signature, and the reason is load-bearing.** It was
`tuple[PortfolioPositionModel, Optional[int]]` = `(position, risk.adjusted_size)`, from which §5.2's
`over_exposure` flag **cannot be computed**: `approved` and `adjusted_size` are independent in
`check_position_risk`. `services/portfolio_risk.py:69-74` sets `approved=False` with
`adjusted_size=None` (max concurrent positions), while `:90-97` sets an `adjusted_size` and `:114-116`
keeps `approved=True` for that soft reason alone. So `adjusted_size is not None` is neither necessary
nor sufficient for a breach, and the whole §5.2/§7.1/§7.2/§6.5/test-21 chain that hangs off
`over_exposure` was unimplementable through the specified interface.

`stop_required` (§6.2) was also missing from this signature, which is where it has to be declared.

It is `add_position`'s body from the duplicate-contract check through `await db.refresh(position)`,
moved verbatim, returning `(position, risk.adjusted_size)`.

`routers/portfolio.py:add_position` becomes a thin wrapper: call it with the default, then do the two
things that are the router's and not the writer's — `log_approval` for
`tradeCardSnapshot`, and `PortfolioPositionSchema.from_orm_model` + `adjustedQty` on the response.

**`book_fired_order` therefore calls `log_approval` ITSELF, and round 1 is why this sentence exists.**
`trade_card_snapshot` is **not a column** on `PortfolioPositionModel` — the only thing that consumes
it is `log_approval(body.recId, body.tradeCardSnapshot, db)` (`routers/portfolio.py:533`), which
writes an `AuditEventModel`. Because that call stays in the router wrapper and `book_fired_order`
goes straight to `create_position`, §4.1's eleventh field would have travelled the entire wire and
been discarded — leaving **the one send path with no human watching as the only path with no
approval-audit record**, while §4.1, §7.2 and this section all claimed parity.

So `book_fired_order` calls `log_approval` after a successful `create_position`, wrapped in a guard
modelled on the router's (`:529-535`). Keeping it out of `create_position` preserves step 1's verbatim
boundary and its unedited-suite proof; duplicating one guarded call is the cheaper of the two costs.

**The guard must ROLL BACK, and the router's does not — round 2.** `log_approval` commits
(`services/audit.py:154-155`). The router's guard swallows the exception without rolling back, which
is safe there only because the request-scoped session dies immediately after. On the **scan** path the
session is `run_scan`'s and is written again at `scan.py:1780`
(`_upsert_session(..., status="complete")`), so a failed commit inside `log_approval` leaves the
session in a pending-rollback state and `:1780` raises `PendingRollbackError` — which propagates out
of `run_scan` and **500s the user's scan request**, contradicting both §6.1 and §9.4. The guard is
therefore `except Exception: await db.rollback(); log…`, not the router's swallow.

**§8 test 14 pins it, parametrised over BOTH paths** — round 2 noted the original test 14 was
specified against `/fire` only, where there is no subsequent write and the defect is invisible.

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

  **The original justification here was false and round 1 refuted it with the comment sitting above
  the gate.** It read: *"the gate is not skipped for safety reasons either — `fire()` already ran
  `_check_exposure` against the same `check_position_risk` before the order was placed."* They are
  **not the same check**:

  | | `_check_exposure` (`auto_trader.py:302-308`) | `add_position` (`portfolio.py:328-336`) |
  |---|---|---|
  | price basis | `entry_premium`, the armed mid | `entry_price` — **replaced with the live quote** at `:302-304` |
  | quantity | `strategy.quantity` | `body.qty` |
  | portfolio value | `portfolio_value if portfolio_value is not None else strategy.portfolio_value` (`auto_trader.py:229` — the exact form; the two differ at `0.0`) | `body.portfolioValue` |
  | snapshot vintage | read at `scan.py:1759`, **before** a synchronous broker round-trip | read at `portfolio.py:314-315`, after |

  And `portfolio.py:169-174` states, in its own words, why the second check exists: *"This MUST
  happen before the risk check below … otherwise a position could be approved against one price and
  stored at a materially different one, **silently bypassing the exposure gate**."* The original text
  turned off the check that comment was written to guarantee, citing the check that comment was
  written to distrust.

  **The decision does not change — the reasoning does, and so does the consequence.** Refusing to
  book a trade that already happened is still worse than booking it over the cap, so the gate still
  comes off. What was unpriced is that this can book an auto-trade **materially over the exposure
  cap**, on a basis the pre-trade check never saw. That breach must therefore reach a human rather
  than a `logger.warning`: `BookingOutcome` carries **`over_exposure: bool`**, `/fire` returns it
  (§7.1), the frontend surfaces it as a caution (§7.2), and on the scan trigger it goes through the
  §6.5 channel. This is the post-trade record, and a record that hides a breach is not one.

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

The DB session never enters the worker thread. That is the answer to the sync/async split, and it is
why the split was never the blocker it looked like.

**It is not the whole answer, and round 1 found the half that was missing: `create_position` takes
transaction control of a session it does not own.** The verbatim body includes `await db.commit()`
(`portfolio.py:498`), `await db.rollback()` on `IntegrityError` (`:509`) and `await db.refresh(position)`
(`:527`). (**`:498` and `:509`, not `:505`/`:514`** — round 2 caught those, and caught them in the
paragraph whose whole subject is citing this seam to the line.) In a router that is safe — the session is request-scoped and the router is its only writer.
On the scan path `db` belongs to `run_scan`, is shared with `_execute_scan_core` before the fire point
and with `_upsert_session(db, req, result, "complete")` at `:1780` after. A rollback inside the
booking would discard anything else pending on that session, and the commit expires every ORM object
loaded at `:1759`.

**This is latent, not live**: `_upsert_session` is the only other writer and it commits at `:1243`, so
there is nothing pending at the fire point today. It is recorded because it is the first time a
service function that owns a transaction is handed a session it did not open, and the path it sits on
already swallows its own failures (§9.4) — so the day someone adds a write to `_execute_scan_core`,
this becomes silent data loss with no signal.

**Round 2 corrected the mitigation, which had been aimed at the wrong hazard.** It said step 5 should
"re-read the snapshot it needs after the booking rather than reusing objects loaded before it" — but
the ORM objects loaded at `scan.py:1759` are consumed into `_portfolio_snapshot` at `:1761`, *before*
the fire, and `_upsert_session` issues its own query. Nothing after the booking touches an expired
object, so that mitigation guarded nothing. **The real hazard is a session left in a pending-rollback
state reaching `:1780`** — see §5.1, where the `log_approval` guard is required to roll back for
exactly this reason. The constraint is written into `create_position`'s docstring: **it commits, so
its caller must own the transaction or expect it to end.**

### 5.4 The fire history gains `rec_id`

The history entry appended at `auto_trader.py:288-295` gains `"rec_id": None`, filled in by the
caller after a successful booking (a small mutation method on the service, under the lock). It is the
only link between "the auto-trader fired this" and "this position exists", and §2.8 says the position
row cannot carry the reverse link.

A failed booking appends nothing new — the fire entry already exists and its `rec_id` stays `None`,
which is a readable state: *fired, not booked*.

**The entry is addressed by identity, not by position, and round 1 is why this is spelled out.**
"A small mutation method under the lock" did not say *which* entry, and "the last one" is wrong: the
window between `fire()` appending (`auto_trader.py:286-294`) and the booking completing spans a live
quote fetch and a commit, and a re-arm plus a second `maybe_fire_on_scan` can append inside it. So
`fire()` stamps each history entry with a `fire_id` (`uuid4().hex`), `FiredOrder` carries it, and the
mutation method matches on that, and **a miss is a logged no-op, not a raise** — `fire()` appends at
four sites (`auto_trader.py:235`, `:253`, `:268`, `:286`) and only `:286` is the success entry, so the
method must tolerate being handed a `fire_id` it cannot find rather than assuming one. Round 2.
**Known and accepted:** `AutoTradeState.history` is in-memory and
unbounded (`:66`), so this link does not survive a restart. That is pre-existing, is not O4's to fix,
and is the reason the `REC-AT-` prefix in §4.3 exists as an independent handle. **§8 test 16.**

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

**AND THE SAME RULE IS ENFORCED AT THE WRITE, WHICH IS WHERE IT ACTUALLY BITES.** Round 1 found the
door-side check alone is insufficient, and the defeating path is not hypothetical — the code
announces it. `create_position` re-anchors a plan-derived stop by `delta = live − scanStockPrice`
(`routers/portfolio.py:234`) and then writes `stop=_floor_stop(adjusted_stop)` (`:459`), where
`_floor_stop` (`:43-44`) returns `None` for any non-positive value. The comment at `:237-245` says it
outright: *"`_floor_stop` below will silently store this as None."* A stop armed above zero can
therefore reach the row as `NULL` — and on the scan trigger the arm may be up to
`max_arm_age_minutes` (30) old, so `delta` is a real gap, not a rounding error. A gap-down through
`scan_price − stop` nulls the stop at precisely the moment it mattered.

So `create_position` takes a **`stop_required: bool = False`** parameter. When true, a stop that is
`None` or non-positive **after** the re-anchor aborts the insert and raises; `book_fired_order` catches
it like any other failure (§6.1) and reports `book_error`. O4 passes `stop_required=True`. The card
path keeps today's behaviour, because it has a human looking at the result.

This is the difference between checking an input and guaranteeing an invariant. §6.2 is an invariant
about what is in the database, and the only place to enforce that is the statement that writes it.

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

### 6.3 Four more refusals, for the same reason

`book_fired_order` also books nothing, and reports why, when:

1. **`option_symbol` does not parse** as `SYM|STRIKE|EXPIRY|C/P`. **UNCONDITIONALLY — not only when
   `direction` is absent.** Round 1 found the original conditional form let a request that *does* send
   `direction` book a row whose `contract` column is an arbitrary string, and the shape is load-bearing
   well beyond direction derivation:
   - `fetch_contract_quote_async` bails at `data/market.py:1411-1412` (`if len(parts) != 4`), so there
     is no live entry price and no option price;
   - `portfolio_alert_monitor.py:118-120` therefore never populates `option_prices`, and
     `alert_generator.py:304` requires `opt_price is not None` — **`PREMIUM_STOP` can never fire**;
   - `parse_expiry_from_contract` returns `None` (`alert_generator.py:74-82`) — **`TIME_STOP` can
     never fire**;
   - `contract` is `unique` (`models/portfolio.py:15`), so the same option in a second spelling does
     not trip the §6.4 duplicate check.

   The result would be a position that renders normally and raises only the stock-price stop, with two
   option-side stops silently dead. This is not an exotic input: the repo's own fixtures use OCC form
   (`test_phase_g_arm_pick.py:65`, `test_auto_trader.py:57`), and §11 step 4 nominates that harness.
   A guessed direction is a stop that never fires; an unparseable contract is two stops that never
   fire.
2. **No usable entry price**: `entry_premium <= 0`. **DEFENCE IN DEPTH, not a live path** —
   `arm()` already rejects a non-positive `entry_premium` (§3.1), so no armed strategy reaching here
   can have one. It stays for the reason `add_position`'s sibling branch states at
   `routers/portfolio.py:352-367`: it is the last thing between a future non-positive entry and a
   stored zero, which can never raise a `PREMIUM_STOP` alert. Checked on the *armed* value rather
   than after the router's live-quote replacement, so the refusal does not depend on network
   weather.
3. **`create_position` raises anything at all** — §6.1.
4. **`result.order_id` is empty or falsy.** Round 2: `ibkr_paper.place_order` has an
   `if isinstance(data, list): data = data[0]` branch (`data/ibkr_paper.py:140-141`) that exists
   because IBKR's order endpoint can answer a **confirmation question** rather than an order — that
   element carries neither `order_id` nor `order_status`, so the adapter yields `order_id=""`,
   `status="Unknown"`, and §3.2's "unknown books" default would book a full position **for an order
   that was never transmitted**. No order id also makes the refusal string below unprintable.

Every refusal produces a `book_error` string that names the order id, so the log line and the API
response both point at a real order the user can find at the broker — which is the other reason
refusal 4 exists.

### 6.4 A duplicate contract is reported, not swallowed and not raised

`contract` is unique. If the user already holds the option — from a card send, or from a previous
auto-trade — `create_position` raises 409 and O4 books nothing. That is caught like any other failure
(§6.1) and reported as `book_error`.

It is **not** merged into the existing position. The backend has never merged (only the frontend's
`portfolioStore.addPosition` does, locally), and making O4 the first path that does would be a
change to portfolio semantics on every path at once. §9.3.

### 6.5 Every refusal reaches a human — the reporting channel is part of the rule, not a detail

Round 1's sharpest structural finding: as originally written, **every refusal in §6.2, §6.3, §6.4 and
every over-exposure booking in §5.2 was "reported" into a channel with no reader on the two paths
that can actually produce them.** A rule that refuses to book, and then tells nobody, reproduces the
exact O4 defect — a real filled order at the broker, no position, no stop alert, and a backend log
line as the only trace.

Two distinct gaps, two fixes:

**(a) The scan trigger has no frontend surface at all.** §5.3 caller 2 said the booking result "is
logged and nothing else". There is no UI for `maybe_fire_on_scan`; nobody is looking at it.

**ROUND 2 KILLED THIS SECTION'S FIRST ANSWER, AND THE CORRECTION IS THE WHOLE POINT OF THE SECTION.**
Round 1 routed these to `alert_service.broadcast`, calling it "the channel the product already has".
It is not a channel that reaches anyone: `broadcast` (`services/alert_service.py:22-30`) iterates
`self._clients`, populated only by `/ws/alerts` (`routers/ws_alerts.py`) — and **nothing in the
frontend ever connects to it.** The only WebSocket client in the tree is
`frontend/lib/chartWS.ts:39`. In production `_clients` is empty and `broadcast` is a loop over an
empty list. The fix for "a channel with no reader" was a different channel with no reader.

`portfolio_alert_monitor.py` does not rely on it either, and that is what round 1 misread: it calls
**`notify_alert`** (`services/notifications/alert_notifier.py:192` — Gmail + Telegram, deduped across
callers) to reach a human, and broadcasts afterwards as a best-effort extra wrapped in
`except: logger.debug`. Round 1 copied the best-effort half and dropped the half that reaches a phone.

**So the channel is `notify_alert`, and `broadcast` is the optional extra.** A refusal or an
over-exposure booking on either path calls
`await notify_alert(symbol=…, alert_type=…, reason=…, rec_id=…)` — the same dispatch every portfolio
alert already uses, which means it inherits the delivery settings, the dedup and the enabled-types
filter rather than inventing a parallel path. `broadcast` may be called as well, guarded, for the day
a UI subscribes; nothing may depend on it.

**Severity: `Critical` for "order placed, nothing booked".** There is no `Warning` — `AlertKind` is
`Literal['Info', 'Action', 'Critical']` (`schemas/__init__.py:19`), so round 1's "Warning for a
booking that went over the exposure cap" would have raised `ValidationError` **inside a function §6.1
requires never to raise**, silently dropping the very alert it specified. Over-exposure is `Action`.

**Payload shape is named, not assumed.** The two existing broadcasters disagree — a *list* of
`AlertItem` (`portfolio_alert_monitor.py:191`) versus a bare dict with `type`/`message`
(`regime_monitor.py:153-165`). O4 uses `notify_alert`'s keyword signature and, if it broadcasts at
all, the `AlertItem` list form.

This does **not** contradict §9.4. That non-goal is about `maybe_fire_on_scan` swallowing *fire*
failures, which stays exactly as it is. This is about *booking* outcomes, which did not exist before
O4 and therefore cannot be a change to existing behaviour.

**(a2) The §3.2 rejection is covered by this rule too.** §6.3 enumerates four refusals; §3.2 adds a
fifth (a broker-stated rejection). It is named here explicitly because round 2 found §6.5's original
enumeration listed only §6.2/§6.3/§6.4 and §5.2 — which read literally excluded the one refusal that
fires on a **real broker rejection**, while test 22 parametrised over it. Every refusal in §3.2, §6.2,
§6.3 and §6.4, and every over-exposure booking in §5.2, goes through this channel.

**(b) A pre-O4 client cannot read `booked`.** §6.2's claim that a refusal is "strictly louder than a
422 at arm time" was false as specified: the loud version was a JSON key that the only clients able
to trigger it do not read. `handleFireNow` today reads only `res.order_id`
(`AutoTradeArm/index.tsx:262-273`), and a user on a cached pre-deploy bundle — the normal state for
minutes after any Next.js deploy — is precisely the client that omits `stop` and precisely the one
that cannot render §7.2's caution. So the `/fire` path **also** raises the same in-app alert on a
refusal, not only the response key. The alert does not depend on which bundle the browser is running.

**The rule this section establishes, and which must not be softened:** a fired order that does not
become a position is a Critical in-app alert on every path, always. The response key is a
convenience for current clients; the alert is the guarantee.

---

## 7. The frontend

### 7.1 The `/fire` response grows three keys

```
{ order_id, status, broker,
  booked: bool, rec_id: string | null, book_error: string | null,
  over_exposure: bool }
```

Four keys, not three — `over_exposure` is §5.2's, and it is the difference between a post-trade
record and a record that hides a breach.

Additive, so `handleFireNow`'s existing `res.order_id` read is unaffected.
`frontend/lib/api.ts:640` widens `fireAutoTrade`'s return type to match. (**`:640`, not `:634`** —
round 1 caught the stale anchor, though its stated reason was also wrong: `:634` is
`picked_stop_basis?: PickedStopBasis | null;`, a field declaration inside `armAutoTrade`'s request
type, not a doc comment. Round 2.)

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

**And `option_symbol` obeys the same invariant, which round 1 found it had been exempted from.**
`AutoTradeArm` posts `card.contract` verbatim (`index.tsx:185`, `:206`). `buildPaperPosition` writes
`contract: toOptionSymbol(card)` (`step-7-trade-card/page.tsx:947`), which **rebuilds** from
`contractDetails` via `contractId()` (`types/domain.ts:764-766`) — and that **uppercases the symbol**,
falling back to `card.contract` only when `strike`/`expiry`/`right` are missing. §2.6 answers this by
*arguing* the two expressions coincide today, and the argument is sound as far as it goes. But it is
exactly the reasoning §7.2 forbids for five *lesser* fields, applied to the one field that is a
`unique` column and the parsing key for `PREMIUM_STOP` and `TIME_STOP` (§6.3.1). A lowercase symbol,
a fractional strike reaching `contractDetails.strike`, or an incomplete `contractDetails` hitting the
fallback would make one option into two rows, with no 409 and double-counted exposure.

**So `AutoTradeArm` posts the result of `toOptionSymbol(card)` — instead of arguing equivalence with
it. It does NOT call that function, and round 2 is why this distinction is spelled out.**
`toOptionSymbol` is declared at `step-7-trade-card/page.tsx:921`, **inside** `Step7Page` (`:182`,
closing `:1503`). It is a closure: not exported, not module-scope, and `AutoTradeArm` cannot reach it.
Round 1's instruction, taken literally, was unimplementable — and the obvious workaround (have
`AutoTradeArm` call `contractId(...)` itself) is a **second copy of the expression**, which is the
"argue equivalence" failure mode this paragraph exists to close, one level down. Test 17 as originally
worded would have gone green on exactly that broken shape.

**The correct form is a sixth prop**, `optionSymbol={toOptionSymbol(card)}`, resolved at the Step-7
call site precisely as `resolvedInvalidation` is — one derivation, computed where
`buildPaperPosition` computes it, passed down. (Hoisting `toOptionSymbol` to module scope and
exporting it is an acceptable alternative; the prop is preferred because it matches the contract the
other five already follow.) §2.6's table stops being load-bearing and becomes what it should always
have been: an explanation of why this change is safe rather than a reason not to make it.
**§8 test 17.**

**Surfaces:** `handleFireNow` already stores `res.order_id`. It additionally reads `res.booked`, and
when it is `false` renders a **caution**, not an error, beside the order id — the order *worked*;
the record did not. The copy names the consequence in plain words, e.g.
*"Order 888 placed, but no position was recorded — this trade has no stop alert. Add it manually from
the Portfolio page."* Claiming anything less specific here would be the mistake §9.2 of the Phase G
spec warns about. It also renders a caution on `res.over_exposure` (§5.2), naming the cap the booking
went past.

**Write the check as `res.booked === false`, not `!res.booked`** — on the merits, not on the evidence
round 1 gave for it. `undefined` means "this response predates the key", which is a different claim
from "the booking failed", and only the explicit comparison says so.

**Round 1's supporting evidence was false and is withdrawn.** It claimed four existing suites
(`AutoTradeArm/__tests__/AutoTradeArm.test.tsx:24` and `step-7-trade-card/__tests__/`'s
`edited-fields-sync`, `direct-send-stop-gate`, `contracts-sync`) would go red under `!res.booked`.
They mock `fireAutoTrade`, but **none of them ever clicks Fire** — every `it()` in the first drives
`Arm`, and the other three never interact with the fire path at all. `handleFireNow`
(`AutoTradeArm/index.tsx:262-273`) is never reached, so neither branch executes and neither claim
about those suites is testable. Citing them was the same defect round 1 found in the original test 7:
evidence that cannot distinguish the thing it is offered as evidence for.

**The success case needs a refresh, and §7 originally said nothing about it.** Every other send path
books from the client and writes `portfolioStore` in the same action. O4 books **server-side**, so
without an explicit refresh the new position is invisible on the Portfolio page and the trade card
until the next `syncFromBackend`. On `booked: true`, `handleFireNow` triggers that sync. A booking the
user cannot see is only marginally better than one that did not happen. Round 1.

The **six** new props follow `resolvedInvalidation`'s established contract: resolved at the call site
by the same expression `buildPaperPosition` uses, so arming and sending cannot describe the same card
differently. Step 7 is the only call site and it already computes all six — the sixth being
`optionSymbol`, added by round 2.

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
   `check_position_risk` return `approved=False` still books the full ordered quantity, and sets
   `over_exposure`. §5.2.
   **The `adjusted_size` half needs care and round 1 said why:** `_check_exposure` **raises** when
   `result.adjusted_size is not None` (`auto_trader.py:315-321`), so with a portfolio snapshot — which
   both real callers always pass — `fire()` never reaches the broker in that case. Patching
   `check_position_risk` globally makes `fire()` raise and the test passes for the wrong reason. The
   two calls genuinely take different inputs (§5.2's table), so the double must answer per-call:
   approve at the `_check_exposure` call, and answer with the failing shape at the `create_position`
   call. **Both halves need that treatment, not just the `adjusted_size` one** — round 2: `approved=False`
   raises at `auto_trader.py:311-313` exactly as `adjusted_size is not None` raises at `:315-321`, so a
   globally-patched double makes `fire()` raise in both scenarios and the test passes for the wrong
   reason twice. The per-call split is straightforward: `portfolio.py:22` binds `check_position_risk`
   at module level while `_check_exposure` imports it lazily (`auto_trader.py:301`), so the two live in
   separate namespaces. Assert the row carries the **ordered** quantity, not the adjusted one.
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
    `booked: false`, assert the copy naming the missing stop alert is on screen. Second case: a
    response with **no `booked` key at all** renders nothing. **This test must render the component,
    click Fire, and resolve `fireAutoTrade` with a key-less object** — round 2 found the four existing
    suites cited for this never reach `handleFireNow`, so reusing them as the fixture would pin
    nothing and pass identically under either branch. §7.2.

**Round 1 added tests 14–22. Every one of them pins a rule that round 1 found stated but unenforced,
or enforced but unobserved.**

14. **The audit record exists on this path, and a failed one does not poison the session.**
    Fire with a `trade_card_snapshot`, assert an `AuditEventModel` row for the booked `rec_id`. Then
    make `log_approval` raise — **parametrised over BOTH call sites**: on `/fire`, assert the position
    is still booked and the response is still 200; on the **scan** path, assert the scan request still
    returns 200 and `_upsert_session` still completes. Round 2: the scan half is the one that catches
    a guard that swallows without rolling back, and the original test 14 omitted it. §5.1, §6.1, §9.4.
15. **A broker rejection books nothing, and an unknown status books — per broker.** Parametrised over
    §3.2's table, because round 2 found a generic list misses the real strings: IBKR `Inactive`,
    Tradier `error` and `rejected`, Alpaca `rejected`/`canceled`/`expired`, tastytrade's enum form
    once build step 4 confirms it. Each → zero rows, `booked False`, `book_error` naming the status.
    Then `status="some_new_broker_value"` → one row, which pins that this is a rejection test and not
    an allowlist. Plus: **`order_id=""` → zero rows** (§6.3.4). §3.2.
16. **The history back-link finds the right entry.** Fire, and before the booking completes append a
    second history entry (simulating a re-arm inside the window). Assert `rec_id` lands on the entry
    carrying the fired `fire_id`, not on the last one. §5.4.
17. **Frontend — `AutoTradeArm` posts the `optionSymbol` PROP, with no derivation of its own.**
    Render with a card whose `contractDetails` produce a `toOptionSymbol` that differs from
    `card.contract` (a lowercase symbol is cheapest), pass the prop, click Arm, assert the request
    body's `option_symbol` is the prop's value. **And assert the component derives nothing**: render
    with the prop set and `card.contractDetails` absent, and the prop's value must still be posted.
    Round 2: without that second half the test goes green on a second in-component copy of
    `contractId(...)`, which is the failure mode §7.2 exists to close. §7.2, §2.6.
18. **`premium_stop_pct` on the booked row is derived from the dollar stop against the persisted
    entry.** Arm with `premium_stop_dollar` and an `entry_premium` that the live quote then replaces,
    assert the stored fraction is `dollar / persisted_entry` and **not** `dollar / entry_premium`.
    Second case: omit `premium_stop_dollar`, assert the `premium_stop_pct` fallback is stored. §4.4.
    Round 1 found the whole of §4.4 could ship inverted with all thirteen original tests green — this
    is the field that decides when `PREMIUM_STOP` fires.
19. **A re-anchor that would null the stop aborts the booking.** `stop_is_user_set` false, a
    `scan_stock_price` far enough above the live price that `stop + delta <= 0`, assert zero rows and
    a `book_error` — not a row with `stop = NULL`. §6.2. This is the test that would have caught
    round 1's first finding.
20. **An unparseable `option_symbol` books nothing even when `direction` IS sent.** OCC form, explicit
    `direction`, assert zero rows and a `book_error`. §6.3.1.
21. **An over-cap booking reports itself.** A portfolio making `check_position_risk` return
    `approved=False` **with `adjusted_size=None`** (`portfolio_risk.py:69-74` — max concurrent
    positions), assert the row carries the ordered quantity, `over_exposure` is true on the response,
    and the alert was dispatched. The `adjusted_size=None` shape is deliberate: it is the case that
    proves `over_exposure` is read from `approved` and not inferred from `adjusted_size`, which round
    2 found was the unimplementable part. §5.2, §6.5.
22. **Every refusal dispatches a Critical alert through the channel that reaches a human, on both
    paths.** Parametrise over the refusal reasons (no stop, unparseable contract, empty `order_id`,
    duplicate, rejected status, `create_position` raising) and assert **`notify_alert`** was awaited on
    the `/fire` path and on the scan path. **Asserting `alert_service.broadcast` is explicitly NOT
    sufficient** — round 2 found it passes against an empty client list, which is production, making
    it the same class of defect as the original test 7. §6.5.

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
   test 5 change. **§6.5 lowers the stakes of this question considerably** — a refusal is now a
   Critical in-app alert rather than a log line, so "refuse and shout" is no longer "refuse and
   vanish".

3. **KENNETH'S CALL, raised by round 1 — should the auto-trader refuse to FIRE into a contract it
   already holds?** §6.4 answers what the *write* does with a duplicate (reports, does not merge).
   Round 1 pointed out the write is the wrong end of the question on the scan trigger, which fires
   after **every** manual scan while armed (`scan.py:1751-1766`) and has no existing-position lookup
   — `execute_option_order`'s own comment calls auto-trade "structurally entry-only"
   (`auto_trader.py:145-148`). So: hold `AAPL|185|2026-06-20|C` from a card send, arm the same
   contract, scan PASSes → **a second real order at the broker**, added to a real position, which
   Bamendjou then refuses to book. Money moves, the books say it did not, and exposure is understated
   by the whole second order.
   **This is out of O4's scope as specified** — O4 is "a record of a trade that already happened", and
   a pre-trade refusal is a change to what the auto-trader *submits* (§1). §6.5 at least makes it
   loud. But the loudness is a mitigation, not a fix, and whether the fire path should check for a
   held contract before ordering is a real question O4 surfaces and does not answer.

4. **The §6.5 alert channel is a scope addition, and it is the one thing in this revision that grows
   O4 rather than correcting it.** Round 1's case for it is strong: without it, four of O4's own rules
   report into a channel with no reader. But it adds a dependency on `alert_service.broadcast` that
   the original spec did not have. If Kenneth wants O4 kept strictly minimal, §6.5(a) is the part to
   cut — and cutting it means accepting that a scan-triggered refusal is a log line nobody reads.

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
5. **Wire the scan path** (§5.3 caller 2). Test 9. **Steps 4 and 5 land together in one merge.**
   Round 1: between them the product is in a state where "Fire now" books a position and letting the
   scan fire the *same arm* does not. Each step ends green, but green is not coherent, and this is the
   one intermediate state a user could be exposed to if the branch merged mid-sequence.
   Step 5 also threads past a test double that step 4's caller-sweep warning does not cover:
   `tests/test_scan_session.py:293-296` replaces the whole `auto_trader` singleton with a
   `SimpleNamespace` and drives `run_scan` with a `_FakeDb` (`:285-287`) that has **only `execute`** —
   no `commit`, `rollback`, `add` or `refresh`. It survives today only because the substitute returns
   `None` implicitly. The new call must be guarded `if fired is not None`, and that double is the
   reason.
6. **Frontend** (§7). Tests 12–13, 17.

Then one adversarial round on the build, at the `audit_rule` v2 gate, before anything merges.

**Before any of it: one adversarial round on this spec.**

---

## 12. Adversarial round 1 — 2026-09-17

Run against this spec **and** the implementation plan built on it, by an independent reviewer with no
part in writing either, against the real tree at `a6c1883f`. **10 gate-level, 13 below-gate.** Every
claim was re-executed before being accepted; the findings below are the ones that survived that.

**The three that changed the design, not the prose:**

1. **§6.2 was enforced at the door and not at the write.** `create_position`'s re-anchor can null a
   stop that was armed above zero, and the code says so in a comment. The rule now lives in the writer
   (`stop_required`), which is the only place an invariant about the database can be enforced.
2. **§4.1's `trade_card_snapshot` was guaranteed to be discarded**, because the only consumer
   (`log_approval`) stays in the router wrapper that `book_fired_order` bypasses. The one path with no
   human watching would have been the only path with no approval record.
3. **Every refusal reported into a channel with no reader.** Fixed by §6.5, which is also the largest
   scope addition in this revision and is flagged for Kenneth at §10.4.

**Also corrected:** a false justification for disabling the exposure gate (§5.2 — refuted by the
comment sitting directly above the gate); a broker `200` carrying `status: "rejected"` treated as a
submit (§3.2); the `option_symbol` shape check made unconditional, because the shape is load-bearing
for two alert types and the `unique` column, not just for direction (§6.3.1); `option_symbol` brought
under the same "same expression" invariant as five lesser fields (§7.2); transaction ownership on a
borrowed session (§5.3); a `targets` default that would not have imported (§4.1); a history back-link
with no key (§5.4); an `entry_date` parity claim that was false (§4.3); and nine added tests, of which
test 18 covers the whole of §4.4 — which round 1 found could ship inverted with all thirteen original
tests green.

**Not adopted, with reasons:** nothing. Every finding was either fixed or escalated to §10 as
Kenneth's call (§10.3 the pre-trade duplicate question, §10.4 the §6.5 scope addition).

**What round 1 explicitly checked and cleared:** §2.3's two-caller claim (it looked for a third and
found the `stock_scan.py` reference is a comment); §3.1's "`entry_premium` cannot be zero"; §2.1's
post-sizing requirement, which it confirmed got *sharper* after `fc451c2d`; §2.6's `int(strike)` table
at the backend producers; and twelve of the plan's §1 line-number rows. The drift it found was in the
rows §1 did **not** cover — which is why §1 now covers them.

---

## 13. Adversarial round 2 — 2026-09-17

Scoped to round 1's diff alone (`git diff 740aa2b2 8a471de1 -- docs/superpowers/plans/`), per
`audit_rule` (2): round N>1 reviews only what changed. **11 gate-level, 7 below-gate.**

**Seven of the eleven gate-level findings were defects in round 1's own fix text.** That is the
non-convergence signature `audit_rule` describes, and it is recorded plainly rather than buried: the
sibling `2026-09-16-yaml-config-integrity-plan.md` died of exactly this at four rounds, and it showed
up here one round earlier.

**The three round-1 fixes that did not work:**

1. **§6.5 routed every refusal into a channel with no subscriber.** `alert_service.broadcast`
   (`services/alert_service.py:22-30`) iterates a client list populated only by `/ws/alerts`, and
   **nothing in the frontend connects to it** — the tree's only WebSocket client is
   `frontend/lib/chartWS.ts:39`. `_clients` is empty in production. The fix for "a channel with no
   reader" was a different channel with no reader, and test 22 would have passed against it. It also
   specified severity `Warning`, which is not in `AlertKind` (`schemas/__init__.py:19`) and would have
   raised `ValidationError` inside a function §6.1 forbids to raise. Now: `notify_alert`
   (Gmail/Telegram, the call `portfolio_alert_monitor` actually uses to reach a human), severity
   `Critical`/`Action`, `broadcast` demoted to a guarded extra.
2. **`over_exposure` was unimplementable through §5.1's interface.** `approved` and `adjusted_size`
   are independent in `check_position_risk` (`portfolio_risk.py:69-74` vs `:90-97`/`:114-116`), so the
   returned tuple could not express a breach. §5.1 now returns a `WriteOutcome` — which is also where
   `stop_required` belonged and had never been declared.
3. **`toOptionSymbol` is a closure inside `Step7Page`** (`page.tsx:921`, inside `:182`), so "post the
   same expression" could not be implemented, and the obvious workaround is a second copy of the
   expression — the exact failure mode the instruction existed to close. Now a sixth prop.

**Also closed:** the `log_approval` guard had to roll back, or a failed audit write leaves
`run_scan`'s session pending-rollback and 500s the scan at `scan.py:1780` (§5.1); the rejection list
missed the strings the named brokers actually emit — IBKR says `Inactive`, not `Rejected`, and Tradier
adds `error` (§3.2); an IBKR confirmation-question response yields an empty `order_id` that would have
booked a position for an order never transmitted (§6.3.4); §5.3's mitigation guarded a hazard that did
not exist while missing the one that did; **two more wrong line numbers inside the paragraph whose
subject is citing lines precisely** (`:505`/`:514` → `:498`/`:509`); a leftover `auto_trade.py:81`
nineteen lines from the one round 1 fixed, while §12 claimed it corrected; and §7.2's empirical claim
about four test suites, which was simply false — none of them ever clicks Fire.

**Nothing was waved through, and nothing new was escalated** — §10.3 and §10.4 remain Kenneth's.

**Round 3 is the last round `audit_rule` permits.** If it is not clean, the finding is that this
document is too big to audit as one unit, and the remedy is to split it — §5.1/§5.2 (the extraction
and the gate flag) are self-contained and could be built and audited alone, leaving the wire, the
booking rules and the frontend as a second document.

