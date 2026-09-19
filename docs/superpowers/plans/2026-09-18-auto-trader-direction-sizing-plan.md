# Auto-trader: size bearish trades off the bearish conviction frame

**Date:** 2026-09-18
**Piece:** A — regime conviction sizing is inverted for bearish auto-trades.
**Status:** PLAN, ENGINEERING CONVERGED. Three adversarial rounds. Not implemented.

> **SPLIT 2026-09-18 ON KENNETH'S DECISION, AFTER ROUND 3 FIRED THE HARD CAP.**
> Three rounds, none clean — and audit_rule says that is evidence the batch is too big to
> audit, not that it needs a fourth round. Round 3 recomputed every number here and **all of
> them hold**: the multiplier table, the blast-radius table, all seven rows of the test table,
> the rewritten `:514` fixture, and the inventory (29 grep hits, 5 prose, 24 real constructions
> at exactly the cited lines, zero positional calls by AST walk, nothing missing repo-wide).
> What was **not** converging was two areas that are not about position sizing, each of which
> produced the blocker in consecutive rounds. Both are now their own pieces:
>
> - **Piece B — `2026-09-18-B-armed-strategy-runtime-validation.md`.** The runtime guard on
>   `ArmedStrategy.direction`. Round 2 prescribed a bare `raise ValueError`; round 3 found it
>   lands in `fire()`'s `sizing_data_blocked` bucket with a false log line and a shared
>   `rec_id` that can suppress a genuine config refusal, and that it sits after both full-size
>   early returns — absent exactly where the blast radius is largest.
> - **Piece C — `2026-09-18-C-state-py-gates-for-split-audit-loops.md`.** Round 3's BLOCKER:
>   §4's "exits 0" is unreachable at the fix commit, because `git_max >= 3 and not
>   audit_clean` fires on this branch's round-3 subjects, and the only reconciling value is a
>   bookkeeping falsehood.
>
> **This document is now Piece A alone: the sizing fix proper.** §2.1's `raise` block and §5
> are retained below as the RECORD of what rounds 1-3 established, but they are no longer this
> piece's prescriptions — B and C own them. §4's last bullet cannot be satisfied until C is
> settled.

---

## 1. The defect, as measured

`auto_trader.py:176`:

```python
directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
```

Two independent faults. Only the first is live.

### 1.1 LIVE: `action` does not encode direction, so bearish trades are sized inverted

`conviction` comes from `regime_monitor.get_last_conviction()` (`regime_monitor.py:25-27`),
which caches `compute_omm(closes, direction="Bullish").conviction_pct`
(`regime_monitor.py:184`). That is the **bullish frame**: `conviction()` returns
`signal if direction == "Bullish" else -signal` over `P(Bull) - P(Bear)`
(`regime_omm.py:131-133`), scaled ×100 at `:208`, so the scale is signed `[-100, +100]`.
The `conviction_label` bands at ±15/±40 confirm the sign convention.

`AutoTradeArm/index.tsx:203` is the **only** production caller of `armAutoTrade`, and it
hardcodes `action: 'BUY'` at `:207` with the accurate comment *"long single-leg option (call
or put) is always buy-to-open"*. A bearish options trade in this app is a **long put** —
which is `BUY`. `auto_trader.arm(...)` likewise has exactly one production call site
(`routers/auto_trade.py:83`); there is no scheduler or scan-driven arm path. Therefore:

- `strategy.action` is `"BUY"` for every armed trade, bullish or bearish.
- Every bearish trade takes the `if` branch and is sized off **bullish** conviction.

#### The ramp, computed — not estimated

`conviction_mult` (`conviction_sizing.py:309-341`) is
`lo + (1 - lo) * max(0.0, min(conv / full, 1.0))` (the clamp is at `:339`). With the live
config (`scoring_rules.yaml:463-471` — `min_mult: 0.3`, `full_conviction_pct: 40`) this is a
**one-sided** ramp: every conviction at or below 0 floors at `0.30`.

That one-sidedness is the correction round 1 forced. An earlier draft of this plan claimed
neutral "should get 0.65" and booked a 2.17x error there. It does not: neutral is the floor,
not the mid-ramp. **The error is zero at neutral and grows symmetrically outward.**

For a **bearish** trade at bullish conviction C:

| C (bullish conv) | Regime vs. a long put | SHOULD get `mult(-C)` | Actually gets `mult(C)` | Error |
|---|---|---|---|---|
| +40 | strongly **opposes** | 0.30 (floor) | **1.00** (full) | 3.33x oversized |
| +20 | opposes | 0.30 (floor) | 0.65 | 2.17x oversized |
| 0 | neutral | 0.30 | 0.30 | **none** |
| −20 | favours | 0.65 | 0.30 | 2.17x undersized |
| −40 | strongly **favours** | 1.00 (full) | **0.30** (floor) | 3.33x undersized |

The ramp is **exactly inverted** for bearish trades: largest into the regime that opposes the
trade, smallest into the one that supports it. This is worse than a mis-scale; it is a sign
error on the risk axis, and it has been live since 2e027c76.

#### Blast radius, in order quantities — where it actually bites

The multiplier is not the shipped observable. `auto_trader.py:178` is
`adjusted_qty = max(1, round(strategy.quantity * mult))`, so the realised error is
integer-rounded against a floor of 1. Computed:

| armed qty | C=+40 correct → actual | C=−40 correct → actual |
|---|---|---|
| **1** | 1 → 1 (**no effect**) | 1 → 1 (**no effect**) |
| 2 | 1 → 2 (2x) | 2 → 1 (2x) |
| 3 | 1 → 3 (3x) | 3 → 1 (3x) |
| 4 | 1 → 4 (4x) | 4 → 1 (4x) |
| 10 | 3 → 10 (3.33x) | 10 → 3 (3.33x) |

**At an armed quantity of 1 the defect has no effect at all**, and a single-leg option arm is
commonly qty 1. The "3.33x" figure is multiplier-space and is realised at qty 10. Stated
plainly because an overstated blast radius invites an over-scoped fix — the defect is real,
it reaches live broker order sizes, and it bites from qty 2 upward.

### 1.2 DEAD: `100 - conviction` is not a mirror of a signed scale

On a signed `[-100, +100]` scale the bearish mirror is `-conviction`. `100 - conviction` is a
mirror of an unsigned `[0, 100]` scale, which this is not. Worse, since `full_conviction_pct`
is 40, `100 - conviction >= 60` for every `conviction <= 40`, so the ramp clamps to 1.0 — the
SELL path would fire at **full size for essentially every regime**.

**This branch is unreachable from the UI** (§1.1: `action` is always `"BUY"`). It is reachable
only by hand-rolling a POST to `/auto-trade/arm`. So correcting `100 - conviction` to
`-conviction` — the fix `PROJECT_STATE.json`'s `pending_kenneth[1]` currently prescribes —
**would not change any real trade**. That recorded diagnosis names the wrong branch, and
correcting it on main is a deliverable of this piece (§5).

### 1.3 The existing test encodes the confusion

`test_auto_trader.py:514` (`test_vol_sizing_sell_reduced_in_strongly_bullish_market`) arms
`action="SELL"` on `option_symbol="AAPL260620P00185000"` — a **short put**, which is a
*bullish* position — and asserts it must be *reduced* in a bullish market. The test passes,
and it is asserting the wrong thing about an unreachable branch.

Secondary: that fixture uses OCC format (`AAPL260620P00185000`) while the frontend actually
sends Bamendjou's display id (`AAPL|185|2026-06-20|P`, `domain.ts:764`). The test fixtures and
production disagree on the format of this field.

---

## 2. The fix: thread direction explicitly

Direction is known at arm time and is simply not sent. `AutoTradeArm/index.tsx:303` already
renders `card.direction` on the Arm button's own label. `TradeCardData.direction` is a
required `Direction` (`domain.ts:613`); `Direction = 'Bullish' | 'Bearish'` (`domain.ts:7`).

Inferring direction from `action` is what caused this bug. Inferring it from `option_symbol`'s
right (C/P) was considered and **rejected**: that field is Bamendjou's display id, and
`AutoTradeArm/index.tsx:186-187` records that OCC conversion is a tracked follow-up — so the
format is expected to change under us. Direction becomes an explicit, carried field, exactly
as Phase G threaded the `picked_*` fields.

### 2.1 Changes

**`backend/app/routers/auto_trade.py` — `ArmRequest`**
Add `direction: Literal["Bullish", "Bearish"]`, **required, no default**.

Required is deliberate. A default of `"Bullish"` would reintroduce precisely the silent
mis-direction this change removes, and it is the same failure shape as the documented G5-1
hole (`extra='ignore'` letting a misspelled key arm with NULLs). Required means a body without
`direction` is a **422 at arm time** — loud, before anything is armed — rather than a wrong
size at fire time. This is NOT the rejected "fail closed at fire" option: nothing new refuses
at fire, and no new refusal/alert path is added.

**Rollout constraint (round 1, finding 14):** the two sides must deploy together. A backend
ahead of the frontend — or any cached older client bundle — turns *every* Arm click into a 422
with no fallback. That is the accepted cost of "loud, before anything is armed", but it is a
deployment fact, not a detail to discover in production.

**`backend/app/services/auto_trader.py` — `ArmedStrategy`**
Add `direction: Literal["Bullish", "Bearish"]`, required. It must be placed **before**
`entry_premium` (`:34`), because Python forbids a field without a default after fields with
defaults. Verified: `broker`…`conid` (`:26-33`) are all non-defaulted, `entry_premium` is the
first defaulted field, so inserting immediately after `action` (`:29`) is legal and keeps the
directional fields adjacent. `ArmedStrategy(**req.model_dump())` (`auto_trade.py:83`) keys off
field names, so both sides must use the identical name.

**`backend/app/services/auto_trader.py:174-176` — `_apply_vol_sizing`**

Replace the line **and the two comment lines above it**. `:174-175` currently read
`# Direction-aware: BUY scales with bullish conviction; SELL scales with bearish conviction`
/ `# (bearish conviction = 100 - bullish conviction, capped to full_conviction scale)` —
the exact false reasoning §1.2 dismantles. Left standing above a corrected line it becomes a
trap for the next reader.

```python
# Direction-aware: conviction_pct is the SIGNED bullish frame (regime_omm.conviction,
# [-100, +100]), so the bearish mirror is -conviction, NOT 100 - conviction.
# Direction is carried explicitly from the card: `action` is always BUY for a
# long single-leg option and never encoded direction.
if strategy.direction not in ("Bullish", "Bearish"):
    raise ValueError(
        f"ArmedStrategy.direction must be 'Bullish' or 'Bearish', got "
        f"{strategy.direction!r} -- it decides position size and there is no safe default"
    )
directional_conv = conviction if strategy.direction == "Bullish" else -conviction
```

> **MOVED TO PIECE B — NOT THIS PIECE'S PRESCRIPTION.** The `raise` above and the paragraph
> below are kept as the record of what rounds 1-2 established. Round 3 found the raise lands in
> `fire()`'s `sizing_data_blocked` bucket with a false log line and a shared `rec_id`, and sits
> after both full-size early returns. See
> `2026-09-18-B-armed-strategy-runtime-validation.md`. **Piece A ships without it**, and is then
> correct through the HTTP door (pydantic validates `ArmRequest`) and silently bearish-on-
> malformed for direct constructors — the residual risk B exists to close.

**The explicit `raise` is not belt-and-braces; without it this expression fails OPEN to
bearish** (round 2, finding 6). `ArmedStrategy` is a plain `@dataclass` (`auto_trader.py:24-25`),
so its `Literal[...]` annotation is **not enforced at runtime** — only `ArmRequest` validates.
A bare `... if direction == "Bullish" else -conviction` silently maps `"bullish"`, `"Bulish"`,
`""` and `None` to the bearish branch. 23 test sites construct `ArmedStrategy` directly, as
would any future non-HTTP producer. §2.1 spends a paragraph arguing that a `"Bullish"` default
would reintroduce exactly the silent mis-direction this change removes; shipping the same
silent-default shape pointed the other way would make that argument cover only the HTTP door.

The `action`-based inference is **removed**, not kept alongside. Once direction is explicit,
`action` carries no directional meaning and a second source of truth is how these drift apart.

**`backend/app/routers/auto_trade.py` — `/auto-trade/status`**
Add `"direction": state.strategy.direction if state.strategy else None` to the payload
(`:114-124`, which today returns armed/symbol/option/broker/history_count/last_order and does
not return `action`). Once direction decides position size, a wrong direction on an armed
trade is otherwise undetectable until the fill. One line, and it is the observability half of
the loud-failure argument above.

**`frontend/lib/api.ts` — `getAutoTradeStatus` response type**
Add `direction` to it as well (`api.ts:643-644` types the response `{ armed; symbol; option;
last_order }`). Round 2, finding 8: adding the field to the endpoint and not to its only
declared reader means nothing in the app can actually read it, which defeats the observability
justification above. **Known gap, deliberately not closed here:** the history entries appended
in `auto_trader.py` (`:379-389` and the fire/cap blocks) carry no `direction`, so a *fired*
trade's direction stays unrecorded and `last_order` will not show it. Recording it there is
O4's territory (that is the path that will book a position); noted so the next reader does not
mistake `last_order` for direction evidence.

**`frontend/lib/api.ts` — `armAutoTrade` request type**
Add `direction: 'Bullish' | 'Bearish'` (required, so a caller that forgets fails typecheck
rather than at runtime).

**`frontend/components/organisms/AutoTradeArm/index.tsx:203`**
Add `direction: card.direction` to the payload (the `action: 'BUY'` line is `:207`) — **not** `card.direction ?? 'Bullish'`, which
typechecks and silently reinstates this exact defect. Update the `action: 'BUY'` comment: it
stays `BUY` and that remains correct, but it no longer implies bullishness.

### 2.2 Test changes

Every assertion below is a **quantity**, because quantity is the only observable:
`_apply_vol_sizing` returns an `ArmedStrategy`, and nothing in the changed code returns a
multiplier for a direction. Calling `conviction_mult` directly would not exercise this fix at
all — the negation lives in `auto_trader.py`, not in `conviction_sizing.py`.

**Every new test arms `quantity=4`.** This is load-bearing. At `quantity=1` the multipliers
0.30 / 0.65 / 1.00 all round to 1, so every assertion would read `1` and **the whole suite
would pass with the bug still in place**. At qty 4 they separate cleanly: 0.30→1, 0.65→3,
1.00→4.

**Rewrite** `test_vol_sizing_sell_reduced_in_strongly_bullish_market` (`test_auto_trader.py:514`)
as the coherent case it was reaching for: a bearish long put (`action="BUY"`,
`direction="Bearish"`) in a strongly bullish regime, cut to the floor. Its existing fixture is
qty 4 at conviction 80; rewritten, `-80` clamps to 0 → 0.30 → `round(1.2)` = **1** (not the 3
the old assertion carried). Rename it accordingly.

**New tests** (all `quantity=4`, all `action="BUY"`):

| # | direction | conviction | expect qty | bug gives | discriminates? |
|---|---|---|---|---|---|
| 1 | Bearish | +40 | 1 (floor) | 4 | yes |
| 2 | Bearish | +20 | 1 (floor) | 3 | yes |
| 3 | Bearish | −20 | 3 (0.65) | 1 | yes — **and this is the only case inside the ramp**, so it is the one that detects a later change to `full_conviction_pct` |
| 4 | Bearish | −40 | 4 (full) | 1 | yes |
| 5 | Bearish | 0 | 1 | 1 | **no** — boundary pin only; labelled as such in its docstring so nobody reads it as bug coverage |
| 6 | Bullish | +40 | 4 | 4 | regression guard: bullish behaviour unchanged |
| 7 | Bullish | −40 | 1 | 1 | regression guard |

**Plus two tests that are not in the table, and the first is the one round 2 caught missing:**

- **`action` no longer influences sizing.** `test_auto_trader.py:514` is repo-wide the *only*
  sizing test that constructs `action="SELL"`, and §2.2 rewrites it to `"BUY"`. After that,
  **nothing pins that `action` has stopped affecting size** — someone reinstating
  `strategy.action` in that expression would break no test, which is precisely the drift §2.1
  removes the inference to prevent. Add: `action="SELL"`, `direction="Bullish"`,
  conviction `+80`, `quantity=4` → after the fix `mult(+80) = 1.00` → **4**; before the fix
  `mult(100 − 80 = 20) = 0.65` → `round(2.6)` = **3**. Discriminating in both directions.
- `POST /auto-trade/arm` without `direction` → **422** (the loud-failure guarantee of §2.1).

**Frontend test** (round 1, finding 6 — the change exists to make the browser send this field,
and nothing in the original plan pinned that). `AutoTradeArm/__tests__/AutoTradeArm.test.tsx`
already inspects `(api.armAutoTrade as jest.Mock).mock.calls[0][0]` for `entry_premium`,
`premium_stop_pct` and the `picked_*` fields — follow that pattern and assert the armed payload
carries `direction` matching the card's, for a Bearish card **and** a Bullish one. Without it,
a missing `direction` is caught only by `tsc`, and only until someone writes `?? 'Bullish'`.

Verified and **not** a required change: the two `toHaveBeenCalledWith` arm assertions
(`step-7-trade-card/__tests__/edited-fields-sync.test.tsx:363`, `contracts-sync.test.tsx:189`)
both use `expect.objectContaining`, so an extra payload key does not break them.

### 2.3 Mechanical inventory — every construction a required field breaks

The original plan counted only `ArmedStrategy(...)` and got the count wrong, and it never
mentioned the request side at all. Both are enumerated here. **A required field with no
default breaks every site that omits it**, and the HTTP sites fail as 422s.

**(a) `ArmedStrategy(...)` — 24 real constructions repo-wide.** Scope stated, because round 1's
"26" and round 2's correction of it were both scope errors as much as counting errors.
`grep -rn "ArmedStrategy(" --include=*.py .` over the **whole repo** yields 29 hits: **5 are
prose** in comments/docstrings (`test_phase_g_arm_pick.py:11`, `:127`,
`test_premium_stop_per_position.py:368`, `backend/app/services/auto_trader.py:43`,
`backend/app/routers/auto_trade.py:48`) and **24 are real constructions** — 23 in
`backend/tests/`, plus **one in production**.

| File | Real constructions | Shape |
|---|---|---|
| `test_auto_trader.py` | 20 (`:15,34,55,83,105,126,157,213,236,260,286,302,453,478,503,532,552,568,583,606`) | direct kwargs, except `:302` and `:606` which are helper `return`s |
| `test_phase_g_arm_pick.py` | 1 (`:83`, `ArmedStrategy(**base)`) | edit the `base` dict in `_strategy()` — one edit |
| `test_premium_stop_per_position.py` | 2 (`:293` `ArmedStrategy(**base)`; `:378` `ArmedStrategy(**req.model_dump())`) | `:293` is one dict edit; **`:378` needs no `direction=` at all** — it inherits from the `ArmRequest` at `:373` |
| **`backend/app/routers/auto_trade.py` (production)** | 1 (`:83`, `ArmedStrategy(**req.model_dump())`) | **needs no `direction=`** — same inheritance as `:378`. Listed because a section headed "every construction a required field breaks" that names the test twin and omits the production original is not an inventory |

All are keyword-based or `**`-unpacked — a scripted check for positional `ArmedStrategy(...)`
calls returns zero — so no positional breakage. Each test fixture gets the direction its option
right implies, so they stop being self-contradictory.

**(b) `ArmRequest` / HTTP arm bodies — the half the original plan missed entirely.**

Every site here must gain `direction`. But **only some of them go red if you forget** — the
rest pass, wrongly, and §2.3(c) is about those. Round 2 caught the round-1 rewrite getting this
split backwards on three lines and transposing two more, so each site below is labelled with
its *actual* verified behaviour:

| Site | Test | Assertion | If `direction` is omitted |
|---|---|---|---|
| `test_auto_trade.py:10` (**a different file from `test_auto_trader.py`, absent from the original plan**) | `test_arm_accepts_tastytrade_paper_broker_key` | `!= 422` (`:15`) | **FAILS** — red |
| `test_auto_trade.py:32` | `test_arm_rejects_zero_quantity` (def `:26`) | `== 422` (`:37`) | passes silently → see (c) |
| `test_auto_trade.py:44` | `test_arm_rejects_negative_quantity` (def `:41`) | `== 422` (`:49`) | passes silently → see (c) |
| `test_auto_trade.py:57` | `test_arm_disarm_clears_armed_state` (def `:53`) | `== 200` (`:62`) | **FAILS** — red, and its `try/finally` disarm (`:72`) then runs against a never-armed singleton |
| `test_phase_g_arm_pick.py:62-70` — `_arm_body()` base dict, feeding 7 POSTs (`:129,153,170,189,213,229,331`) | — | `:129,153,170,189,331` assert `200`; `:213,229` assert `422` | the five 200s **FAIL**; the two 422s pass silently → see (c). **One dict edit fixes all seven** |
| `test_premium_stop_per_position.py:373` | `test_arm_request_carries_the_pct_into_the_strategy` | bare `ArmRequest(...)` | **FAILS** — `ValidationError` |
| `test_premium_stop_per_position.py:389` | `test_arm_request_rejects_meaningless_percentages` | `with pytest.raises(ValidationError)` (`:387-393`) | passes silently → see (c) |
| `test_premium_stop_per_position.py:852` | `test_order_schemas_reject_a_non_positive_limit_price` | `with pytest.raises(ValidationError)` (`:858`) | passes silently → see (c) |

**`:389` and `:852` do not fail.** They wrap construction in `pytest.raises(ValidationError)`,
and a missing required field raises exactly that — so they go green on the wrong exception.
An earlier draft of this section predicted red tests there; a reader working it top-to-bottom
would have waited for a failure that never comes.

**(c) Six regression guards that would keep passing for the wrong reason.** A missing required
field raises *before* any other bound is evaluated, so these stay green while what they guard
goes dark — this is the silent half of (b), and the dangerous one. Each body must gain
`direction`:

- `test_auto_trade.py:32` `test_arm_rejects_zero_quantity` (def `:26`) and `:44`
  `test_arm_rejects_negative_quantity` (def `:41`) — both assert 422. Without `direction` in the
  body they 422 on the missing field, and `Field(..., ge=1)` on `quantity` could be deleted
  entirely with both still passing.
- `test_premium_stop_per_position.py:389` `test_arm_request_rejects_meaningless_percentages` —
  the `gt=0, lt=1` bound on `premium_stop_pct` stops being tested.
- `test_premium_stop_per_position.py:852` — the non-positive `limit_price` case; `Field(default=None, gt=0)` stops being tested.
- Same shape at `test_phase_g_arm_pick.py:213` and `:229`, which assert 422 on bad `picked_*`
  values (parametrised into 6 and 4 cases respectively) — covered by the single `_arm_body()`
  edit in (b).

Not a finding, but worth stating so the implementer does not re-derive it:
`test_premium_stop_per_position.py:849-853` shares one `base` dict across `StockOrderRequest`,
`OptionOrderRequest` and `ArmRequest`. Neither broker schema declares `model_config`
(`backend/app/routers/broker.py` has zero `extra=` hits), so they inherit pydantic's default
`extra='ignore'` and adding `direction` to the shared base is harmless to the two that do not
declare it.

Silently removing regression guards while the suite stays green is precisely the failure mode
§2.1 invokes G5-1 to argue against.

---

## 3. Explicitly out of scope

- **O4** — `fire_now()` still books no `PortfolioPosition`. Untouched.
- **G5-1** — `ArmRequest` gets no `model_config = ConfigDict(extra='forbid')`. That is a
  behaviour change to a live endpoint and is its own decided piece; the agreed order is O4
  before G5-1. Note: making `direction` required does NOT depend on `extra='forbid'` — a
  *missing* required field is a 422 regardless of the extra-key policy.
- **OCC conversion** of `option_symbol`. Tracked separately; this change deliberately stops
  depending on that field's format.
- **The scan path's sign handling** (`stock_scan.py:970`). It passes
  `regime_signal["conviction_pct"]`, which `stock_scan.py:406-407` computes via `compute_omm`
  with the **scan's own direction**, so it is already in the trade's own frame and needs no
  mirror. Verified, unchanged.
- **The scan/auto-trader INPUT divergence — named, not closed** (round 1, finding 8). Fixing
  the sign does not make the two paths agree, and §3 must not read as though it does. They
  read conviction from different data entirely:

  | | symbol | bars | lookback/window |
  |---|---|---|---|
  | auto-trader (`regime_monitor.py:180`, `:184`) | hardcoded **`"SPX"`** | 600 daily | `compute_omm` **defaults** |
  | scan (`stock_scan.py:403-407`) | **the scanned symbol's own** | 15-min or daily per `rcfg["timeframe"]` | per-horizon `rcfg["lookback"]/["window"]/["min_obs"]` |

  So after this fix the card and the auto-trader can still size the same armed trade
  differently — by a different mechanism than the one being fixed, and the one
  `conviction_sizing.py`'s module docstring exists to prevent. Out of scope here; it needs its
  own piece.

- **`regime_gate` IS NOT WIRED INTO THE FIRE PATH — named, not closed** (ROUND 1 of the code
  audit, finding 4). `scoring_rules.yaml` carries `regime_gate: {headwind_caution_pct: -15,
  headwind_reject_pct: -40}` directly above `regime_sizing`, and the **scan path enforces it**
  (`stock_scan.py` — CAUTION, then a hard `"regime headwind"` drop). `_apply_vol_sizing` reads
  **only** `regime_sizing`. Post-fix, a Bearish trade at bullish conviction +80 — i.e. −80 in
  its own frame, twice past `headwind_reject_pct` — is sized to `min_mult` and **still fires**,
  because `max(1, round(qty * mult))` guarantees at least one contract. The scan would have
  refused the identical setup.

  This became reachable *because of* this piece: before it, the auto-trader could not evaluate
  headwind for a bearish trade at all, having no direction to evaluate it against. It is left
  open deliberately — wiring the gate makes trades that fire today stop firing, which is a
  real-money behaviour change and Kenneth's decision, not an audit fix. Recorded at the call
  site in `auto_trader.py` as well as here.

- **The corrected ramp is one-sided** (same round, finding 12 — a property of unchanged code
  that bounds what this piece buys). `conviction_mult`'s `frac = max(0.0, min(conv/full, 1.0))`
  collapses the entire opposed half of the domain onto a single multiplier. A Bearish trade is
  therefore sized **identically** at bullish conviction +1 and +100, and identically at +40 and
  +80. The defect this piece fixes was "the ramp is inverted"; what replaces it is a two-state
  function — floor when opposed, graded only when favoured. That is arguably correct (you do
  not want to *increase* size into a headwind), but it means the `regime_gate` above is the
  only thing that could distinguish a mild headwind from a severe one, and it is not wired.
  The two findings are one decision.

---

## 4. Verification

- `cd backend && python -m pytest -q` — baseline is **2611 collected** (2610 passed / 1 skipped).
  Expect that plus the new cases. Of §2.3's sites, exactly **four go red** if a site is missed
  (`test_auto_trade.py:10`, `:57`, `test_premium_stop_per_position.py:373`, and the five 200-asserting
  POSTs behind `test_phase_g_arm_pick.py`'s `_arm_body`). The rest **pass silently on the wrong
  exception** — so a green suite does NOT prove §2.3 was worked through. Check (c)'s six guards
  by reading them, not by running them.
- `cd frontend && npm run typecheck` — must be silent. A required `direction` on the
  `armAutoTrade` request type means a forgotten payload field fails here.
- `cd frontend && npm run test` — 134 suites / 1701 tests baseline, plus the new
  `AutoTradeArm` assertions.
- `python3 scripts/state.py` — exits 0, no drift. **This does not hold for free, and it does
  not hold at all unless §5's step 3 is done in the same commit as the fix.**

## 5. Bookkeeping — MOVED TO PIECE C

> **NOT THIS PIECE'S PRESCRIPTION.** Round 3's BLOCKER is that steps 3 and 4 below **cannot
> both be satisfied**: flipping `status` to `shipped` is necessary but not sufficient, because
> `git_max >= 3 and not audit_clean` also fires on this branch's round-3 subjects, and the only
> combination that exits 0 asserts `audit_clean=TRUE` at a commit where the CODE has had zero
> rounds. See `2026-09-18-C-state-py-gates-for-split-audit-loops.md`. The section is kept below
> verbatim as the record of what rounds 1-2 established and acted on.

Round 1 found that `scripts/state.py` would block on this piece. That has been **acted on, not
just planned**, so this section now records live state rather than prescribing what it
prescribed in round 1 — round 2 caught it asserting three repo facts that its own execution had
already falsified.

**Done (committed on this branch):**

1. **`AUTOTRADE-DIRECTION-SIZING` is registered** in `docs/superpowers/PROJECT_STATE.json`'s
   `phases`, `status: in_progress`, `audit_clean: false`, with a presence probe for
   `strategy.direction == "Bullish"` against `backend/app/services/auto_trader.py`.
   `active_phase` points at it. It is **no longer null** — the `target is None` branch
   (`state.py:533-560`) that round 1 reasoned about is unreachable today.
2. **`pending_kenneth[1]` is corrected.** It had prescribed `-conviction` on the unreachable
   `SELL` branch; the correction is prepended and the original entry preserved verbatim
   beneath it, per this file's convention. (The original's own mis-citation of the mis-pinning
   test as `:513` — the def is at `:514` — is left as written, because the preserved text is a
   record of what was believed, not a live claim.)

**Still required, and both are easy to lose:**

3. **Flip `status` to `shipped` in the same commit that lands the fix.** This is the blocker
   round 2 found and it is not optional. `state.py:625-635` computes
   `declared_shipped = ph["status"] in SHIPPED` (`SHIPPED = {"shipped","shipped_unaudited"}`,
   `:65`), and `"in_progress"` is not in it. The probe is a regex presence test, so **the
   moment §2.1's line lands, the pattern is found**, `declared_shipped != actual_shipped`, the
   phase joins `drift`, and **`state.py` exits 1**. The absent-by-design probe is a deliberate
   trip-wire; a plan that trips it and never says to reset it fails its own §4.
4. **Bump `audit_rounds` every round, in the round's own commit.**
   `audit_bookkeeping_drift` falls through to `if git_max > declared: return "drift"`, where
   `git_max` is the highest round number in this branch's commit subjects
   (`_round_numbers_in_branch_subjects`, `:157-167`, regex `\bround\s+(\d+)`,
   case-insensitive). A commit saying "round 2" against a declared `audit_rounds: 1` is drift
   and exits 1 on its own, independently of step 3.

   Note the hard cap that sits behind this: at `git_max >= 3` with `audit_clean` still false,
   `state.py` reports audit_rule's HARD CAP — **three rounds without going clean means stop and
   tell Kenneth**, not run a fourth. This plan is at round 2. If round 3 does not come back
   clean, that is the rule to follow, and the round-4 precedent set on the Step-5 gate banner
   (crossed knowingly, on a shrinking target, with the justification written down) is the only
   shape in which it has ever been crossed.
