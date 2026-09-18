# Auto-trader: size bearish trades off the bearish conviction frame

**Date:** 2026-09-18
**Piece:** Regime conviction sizing is inverted for bearish auto-trades.
**Status:** PLAN — revised after adversarial round 1 (14 findings, all accepted). Not implemented.

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
hardcodes `action: 'BUY'` at `:206` with the accurate comment *"long single-leg option (call
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
directional_conv = conviction if strategy.direction == "Bullish" else -conviction
```

The `action`-based inference is **removed**, not kept alongside. Once direction is explicit,
`action` carries no directional meaning and a second source of truth is how these drift apart.

**`backend/app/routers/auto_trade.py` — `/auto-trade/status`**
Add `"direction": state.strategy.direction if state.strategy else None` to the payload
(`:114-124`, which today returns armed/symbol/option/broker/history_count/last_order and does
not return `action`). Once direction decides position size, a wrong direction on an armed
trade is otherwise undetectable until the fill. One line, and it is the observability half of
the loud-failure argument above.

**`frontend/lib/api.ts` — `armAutoTrade` request type**
Add `direction: 'Bullish' | 'Bearish'` (required, so a caller that forgets fails typecheck
rather than at runtime).

**`frontend/components/organisms/AutoTradeArm/index.tsx:203`**
Add `direction: card.direction` to the payload — **not** `card.direction ?? 'Bullish'`, which
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

Plus: `POST /auto-trade/arm` without `direction` → **422** (the loud-failure guarantee of §2.1).

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

**(a) `ArmedStrategy(...)` — 23 real constructions, not 26.** Three of the original 26 grep
hits are docstring prose (`test_phase_g_arm_pick.py:11`, `:127`,
`test_premium_stop_per_position.py:368`), not code.

| File | Real constructions | Shape |
|---|---|---|
| `test_auto_trader.py` | 20 (`:15,34,55,83,105,126,157,213,236,260,286,302,453,478,503,532,552,568,583,606`) | direct kwargs, except `:302` and `:606` which are helper `return`s |
| `test_phase_g_arm_pick.py` | 1 (`:83`, `ArmedStrategy(**base)`) | edit the `base` dict in `_strategy()` — one edit |
| `test_premium_stop_per_position.py` | 2 (`:293` `ArmedStrategy(**base)`; `:378` `ArmedStrategy(**req.model_dump())`) | `:293` is one dict edit; **`:378` needs no `direction=` at all** — it inherits from the `ArmRequest` at `:373` |

All are keyword-based, so no positional breakage. Each gets the direction its option right
implies, so the fixtures stop being self-contradictory.

**(b) `ArmRequest` / HTTP arm bodies — the half the original plan missed entirely.**

| Site | Count | Effect if not fixed |
|---|---|---|
| `test_auto_trade.py` (**a different file from `test_auto_trader.py`, never mentioned in the original plan**) — POST bodies at `:10`, `:32`, `:44`, `:57` | 4 | `:10` asserts `!= 422` → **fails**. `:44` asserts `== 200` → **fails**, and its `finally` disarm then runs against a never-armed singleton |
| `test_phase_g_arm_pick.py` — `_arm_body()` base dict at `:62-70`, feeding 7 POSTs (`:129,153,170,189,213,229,331`) | 1 edit, 7 sites | `:129,153,170,189,331` assert `200` → **all fail**. One dict edit fixes all seven |
| `test_premium_stop_per_position.py` — `ArmRequest(` at `:373`, `:389`, and the parametrised tuple at `:852` | 3 | `ValidationError` on construction → **fails** |

**(c) Four regression guards that would keep passing for the wrong reason.** A missing required
field raises *before* any other bound is evaluated, so these stay green while what they guard
goes dark. Each body must gain `direction`:

- `test_auto_trade.py:32` `test_arm_rejects_zero_quantity` and `:38`
  `test_arm_rejects_negative_quantity` — both assert 422. Without `direction` in the body they
  422 on the missing field, and `Field(..., ge=1)` on `quantity` could be deleted entirely with
  both still passing.
- `test_premium_stop_per_position.py:389` `test_arm_request_rejects_meaningless_percentages` —
  the `gt=0, lt=1` bound on `premium_stop_pct` stops being tested.
- `test_premium_stop_per_position.py:852` — the non-positive `limit_price` case; `Field(default=None, gt=0)` stops being tested.
- Same shape at `test_phase_g_arm_pick.py:213` and `:229`, which assert 422 on bad `picked_*`
  values — covered by the single `_arm_body()` edit in (b).

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
  | auto-trader (`regime_monitor.py:181-184`) | hardcoded **`"SPX"`** | 600 daily | `compute_omm` **defaults** |
  | scan (`stock_scan.py:403-407`) | **the scanned symbol's own** | 15-min or daily per `rcfg["timeframe"]` | per-horizon `rcfg["lookback"]/["window"]/["min_obs"]` |

  So after this fix the card and the auto-trader can still size the same armed trade
  differently — by a different mechanism than the one being fixed, and the one
  `conviction_sizing.py`'s module docstring exists to prevent. Out of scope here; it needs its
  own piece.

---

## 4. Verification

- `cd backend && python -m pytest -q` — baseline is **2611 collected** (2610 passed / 1 skipped).
  Expect that plus the new cases, with **zero** failures from §2.3's inventory. If any site in
  §2.3 was missed it surfaces here as a 422 or `ValidationError`, not as a subtle wrong number.
- `cd frontend && npm run typecheck` — must be silent. A required `direction` on the
  `armAutoTrade` request type means a forgotten payload field fails here.
- `cd frontend && npm run test` — 134 suites / 1701 tests baseline, plus the new
  `AutoTradeArm` assertions.
- `python3 scripts/state.py` — exits 0, no drift. **See §5: this does not hold for free.**

## 5. Bookkeeping — required, not optional (round 1, finding 5)

`active_phase` in `docs/superpowers/PROJECT_STATE.json` is `null` (verified).
`scripts/state.py`'s `audit_bookkeeping_drift` (`:481-560`) with `_pointer_target() → None`
returns severity `"drift"` — **non-zero exit** — as soon as this branch's commit subjects reach
`UNPHASED_FAIL_ROUND = 3` (`state.py:72`). Today it exits 0 only because the branch carries no
round-numbered subjects for unphased work. This piece is being driven by
`K-adversarial-audit-loop`, which produces exactly such subjects. §4's "exits 0" is therefore
a claim this plan must earn, in a repo whose CLAUDE.md opens with *nothing is done until an
adversarial round comes back clean*.

Two state-file edits belong to this piece:

1. **Register the piece** — add its `phases`/`already_shipped` entry with a `verify` probe
   (pattern `strategy.direction == "Bullish"` against
   `backend/app/services/auto_trader.py`), and set `active_phase` to it, so the round counter
   has a pointer and `state.py` keeps exiting 0.
2. **Correct `pending_kenneth[1]`** — it currently prescribes `-conviction` on the **SELL**
   branch as the fix. §1.2 proves that branch is unreachable from the UI, so that change would
   alter no real trade while appearing to close the bug. This correction is independent of the
   implementation and lands first.
