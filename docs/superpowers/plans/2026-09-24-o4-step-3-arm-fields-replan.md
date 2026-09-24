# O4 step 3 — the arm request carries the booking fields (re-plan)

Date: 2026-09-24. Re-planned against the tree at `38284f1e` (main), per decision
`O4-ROUTE-AND-ALERT-2026-09-24`. It replaces "Step 3 — grow the wire" in
`2026-09-17-o4-implementation-plan.md` §2, which was written against a ~350-line `auto_trader.py`
(it is 2799 lines today) and whose round 3 is not being run.

Inputs: spec `2026-09-15-o4-auto-trade-books-a-position-spec.md` §2.5, §3.3, §4.1, §4.4, §9.6.
Targets: `backend/app/routers/auto_trade.py` (`ArmRequest`, `arm`) and
`backend/app/services/auto_trader.py` (`ArmedStrategy`).

---

## 1. What the old step 3 got wrong against today's tree

| Old plan / spec said | Today | Consequence for step 3 |
|---|---|---|
| **Eleven** new fields, the first being `direction: Optional[Direction]` (spec §4.1 row 1, §4.2) | `direction` is **already required** on both `ArmRequest` (`auto_trade.py:47`) and `ArmedStrategy` (`auto_trader.py:203`), validated at construction by `__post_init__` → `MalformedDirectionError`. It landed with the SIZING work, for sizing. | **Ten** fields, not eleven. Spec §4.2's derivation table (action × right → direction) is dead for this endpoint: an arm without `direction` is already a 422. Step 4 reads `strategy.direction` and derives nothing. |
| `action` can be `SELL`, so §4.2 writes out the `SELL` rows | `ArmRequest.action` is `Literal["BUY"]` (`auto_trade.py:31`). `ArmedStrategy.action` still says `Literal["BUY","SELL"]` but its only production producer is the narrowed schema. | Nothing in step 3. Recorded so step 4 does not re-add the `SELL` rows. |
| `ArmedStrategy` is a plain `@dataclass`; `targets` needs `field(default_factory=list)` | It is `@dataclass(frozen=True)` (`auto_trader.py:185`), frozen on purpose (the comment above it). | `field(default_factory=list)` is still required. **New:** a frozen dataclass with `eq=True` derives `__hash__` from every field, so an instance carrying a `list`/`dict` field raises `TypeError` on `hash()`. See §4. |
| `ArmedStrategy(**req.model_dump())` at `auto_trade.py:83` | It is at `auto_trade.py:149`. | Line number only. The construction is unchanged and still keys off field names. |
| `_dc_replace` carries fields across vol-sizing (`test_phase_g_arm_pick.py:281`) | Still true; there are now five `_dc_replace` sites in `_apply_vol_sizing` (`auto_trader.py:1399, 1410, 1428, 1437, 1459`). | Carried for free; one test pins it (§5 test 5). |

---

## 2. The ten fields

Added to `ArmRequest` (pydantic) **and** `ArmedStrategy` (dataclass), same names, snake_case, **no
alias**, all optional, all defaulting to "not sent". Placement in the dataclass: one block after
`regime_headwind_reject_pct` and before `regime_gate_outcome` — i.e. with the other arm-time inputs,
before the two fields `_apply_vol_sizing` sets. Every construction site in `app/` and `tests/` uses
keywords (checked), so field order is not observable.

| Field | `ArmRequest` | `ArmedStrategy` | Counterpart on `PortfolioPositionCreate` (by alias) |
|---|---|---|---|
| `stop` | `Optional[float] = Field(None, gt=0)` | `Optional[float] = None` | `stop` (unbounded) |
| `stop_is_user_set` | `Optional[bool] = None` | `Optional[bool] = None` | `stop_is_user_set` |
| `scan_stock_price` | `Optional[float] = Field(None, gt=0)` | `Optional[float] = None` | `scan_stock_price` (unbounded) |
| `structural_stop` | `Optional[float] = Field(None, gt=0)` | `Optional[float] = None` | `structural_stop` (unbounded) |
| `exit_plan` | `Optional[dict] = None` | `Optional[dict] = None` | `exit_plan: Optional[dict]` |
| `targets` | `list[dict] = []` | `list[dict] = field(default_factory=list)` | `targets: list[dict] = []` |
| `dte_total` | `Optional[int] = Field(None, ge=0)` | `Optional[int] = None` | `dte_total` (unbounded) |
| `premium_stop_dollar` | `Optional[float] = Field(None, gt=0)` | `Optional[float] = None` | `premium_stop_dollar` (`gt=0`) |
| `max_loss_override` | `Optional[dict] = None` | `Optional[dict] = None` | `max_loss_override: Optional[dict]` |
| `trade_card_snapshot` | `Optional[dict] = None` | `Optional[dict] = None` | `trade_card_snapshot: Optional[dict]` |

`portfolio_value` is not in the list: it already travels (`auto_trade.py:58`, `auto_trader.py:209`).
Step 4 must pass it through (spec §4.4); step 3 has nothing to do for it.

### 2.1 Why the arm bounds are tighter than the create schema's, and why that is safe

`stop`, `scan_stock_price`, `structural_stop` and `dte_total` are unbounded on
`PortfolioPositionCreate` and bounded here. That is deliberate:

- **The arm door is the only refusal that costs no order.** A refusal at booking (step 4) happens after
  a real order has gone to a broker; a 422 at arm happens before anything is armed. A non-positive
  stop or stock price is never valid input, so refusing it here is strictly better than refusing it —
  or worse, storing it — after the fill.
- **It cannot make the arm refuse a body today's client sends**, because today's client
  (`AutoTradeArm`) sends none of the ten. The one place the tighter bound could bite is step 6, when
  the frontend starts sending them: step 6 must send `null`, not `0`, for an absent value. That
  obligation is written into step 6 here (§6) so it is not rediscovered.
- It does not create an arm-accepts/create-refuses gap in the other direction: every value the arm
  accepts for these ten, `PortfolioPositionCreate` also accepts (its bounds are equal or looser on
  every one).

### 2.2 The dicts are validated no deeper than the create path validates them

`exit_plan`, `targets`, `max_loss_override` and `trade_card_snapshot` are untyped `dict` on
`PortfolioPositionCreate`. They are untyped here too. Typing them at arm would be stricter than the card
path, and the card path is the reference; it is not step 3's job to tighten it. No size cap either,
for the same reason (the create path has none).

---

## 3. What step 3 does not do

- **Nothing reads the ten fields.** They travel and are unread at the end of this step, exactly like the
  five `picked_*` fields did after Phase G step 5. The commit message and the `PROJECT_STATE.json`
  phase note say so plainly.
- No `fire()` change, no `FiredOrder`, no booking, no `rec_id`, no `entry_date` (step 4).
- No `/status` or history-row change. `trade_card_snapshot` must not leak into `/auto-trade/status`;
  it does not, because `/status` names its keys explicitly (`auto_trade.py:202-222`) and the history
  rows are built key by key (`auto_trader.py:2175-2403`), not from `asdict(strategy)`.
- No `extra='forbid'` (G5-1, spec §9.6). The camelCase-key-is-silently-dropped hole documented at
  `auto_trade.py:88-95` therefore also applies to the ten; step 6's frontend mapping is where that is
  guarded (as `armPickedFieldsFrom` did for the pick).
- No frontend change (step 6).
- The tripwire `test_phase_g_arm_pick.py::test_firing_still_creates_no_position_...` stays green and
  untouched; step 4 replaces it.
- The comment at `auto_trader.py:228-232` ("THE FIRE PATH CREATES NO PortfolioPosition TODAY") stays
  true and is left alone; step 4 rewrites it.

---

## 4. The frozen-dataclass consequence (new since the old plan)

`ArmedStrategy` is `@dataclass(frozen=True)` with default `eq=True`, so Python generates `__hash__`
from all fields. Once `targets` (a `list`) and the four `dict` fields exist, `hash(strategy)` raises
`TypeError: unhashable type`. Checked in `app/` and `tests/`: nothing hashes an `ArmedStrategy`, puts
one in a `set`, or uses one as a dict key; `fire()`'s `expect` check compares by identity (`is not`,
`auto_trader.py:2118, 2142`), not by hash or `==`. `==` still works (dicts compare by value).

**Decision: leave `__hash__` as generated, and pin it** — one test asserts
`hash(ArmedStrategy(...))` raises `TypeError` once the lists and dicts are present, with a message saying
why. That is louder than `unsafe_hash`/`eq=False` (which would change `==` semantics for every existing
caller) and it tells the next person who reaches for `set()` what they are about to break.

**Frozen is shallow.** `strategy.targets.append(...)` or `strategy.exit_plan["x"] = ...` is not
refused. That weakens "frozen at arm" only for in-process code that mutates the containers; production
does not (the containers are fresh per request from `model_dump()`, and `_dc_replace` shares, not
copies, them — so a mutation would also reach the pre-sizing object). Recorded, not guarded, for the
same reason the existing comment at `auto_trader.py:178-184` records `object.__setattr__` as
private-surface abuse.

---

## 5. Tests — new file `backend/tests/test_o4_step3_arm_fields.py`

1. **All ten land.** `POST /auto-trade/arm` with every one of the ten set to a distinct, non-default
   value → 200, and each lands on `auto_trader.get_state().strategy` with the value sent (asserted on
   the dataclass, not the response — the silent-drop reason at `test_auto_trade.py:247`). Disarm in
   `finally`.
2. **Omitted is a real state.** A body with none of the ten (today's client body) → 200; the nine
   Optionals are `None` and `targets == []`.
3. **Bounds, one parametrised test.** `stop` 0 and −1, `scan_stock_price` 0, `structural_stop` 0,
   `dte_total` −1, `premium_stop_dollar` 0 → 422 whose text names the field; the same body with the
   field removed → 200. So each 422 is the bound, not something else in the body.
4. **The name contract, structurally.** `set(ArmRequest.model_fields) <= {f.name for f in
   dataclasses.fields(ArmedStrategy)}` — every wire field has a dataclass field of the same name, so
   `ArmedStrategy(**req.model_dump())` cannot `TypeError`. And for each of the ten, some field of
   `PortfolioPositionCreate` has `alias == name` or `name == name` — the mapping step 4 will write
   exists on the other side.
5. **Vol-sizing carries them.** `_apply_vol_sizing` on the resize branch (same stubs as
   `test_phase_g_arm_pick.py`'s `test_vol_sizing_rewrites_the_quantity_without_dropping_the_pick`)
   returns a strategy whose ten fields equal the input's.
6. **`targets` defaults are not shared.** Two `ArmedStrategy(...)` built without `targets` have `[]`
   and `a.targets is not b.targets`.
7. **Unhashable, pinned.** §4.

Existing tests: no edits expected. Every existing construction site omits the ten and gets the defaults.

---

## 6. Obligations handed forward (recorded so later steps do not rediscover them)

- **Step 4:** direction comes from `strategy.direction` (never derived); pass `portfolio_value`; map
  the ten onto `PortfolioPositionCreate` by alias (test 4 pins that the aliases exist).
- **Step 6:** send `null`, never `0`, for an absent `stop` / `scan_stock_price` / `structural_stop` /
  `premium_stop_dollar`, and never a negative `dte_total`, or the arm 422s (§2.1). Send snake_case keys
  through a dedicated mapping (the `extra='ignore'` silence, §3).

## 7. Done means

- Backend suite: 2869 + the new file's count passed, 1 skipped, no existing test edited.
- `python3 scripts/state.py` exit 0, with an `already_shipped` phase entry for O4 step 3 whose probe
  pins one of the new `ArmRequest` fields.
- An adversarial round on the **code** comes back clean at `audit_rule`'s gate before merge.

---

## 8. Adversarial round 1 — 2026-09-24: CLEAN

An independent reviewer ran `bmad-review-adversarial-general` on this plan against the tree at
`38284f1e`, under `audit_rule`'s gate. **Zero gate-level findings.** It verified by AST walk that
every `ArmedStrategy(...)` site in `app/` and `tests/` passes keywords (four unpack a dict of real
field names: `auto_trade.py:149`, `test_premium_stop_per_position.py:293, 379`,
`test_phase_g_arm_pick.py:87`); that nothing hashes, sets, deep-copies, pickles, JSON-dumps or logs
a whole strategy; that every history row (including one at `auto_trader.py:2513` this plan did not
list) is built key by key; and that `AutoTradeArm/index.tsx:234` is the only caller of
`armAutoTrade` and sends none of the ten.

Below the gate, logged and not fixed (per `audit_rule`):

- Stale line numbers in §1: `direction` is at `auto_trade.py:58` (not 47), `action` at `:33` (not 31).
- `targets` is `list[dict]`, not Optional, so a step-6 body with `targets: null` would 422 at arm —
  same as `PortfolioPositionCreate`, and before anything is armed. Step 6 sends `[]` for no targets.
