# Document A — `regime-sizing-fix`

> **One layer, backend only.** `config_loader.py`, `auto_trader.py`,
> `stock_scan.py`. No frontend, no new endpoint, no `config_health` holder, no
> startup call site. Those belong to Documents B and C (§7).
>
> **Lifted out of** `2026-09-16-yaml-config-integrity-plan.md` per its §12, which
> stopped at `audit_rule`'s hard cap after four non-converging rounds and
> recommended a split rather than a fifth round. This document carries that
> plan's §2 and §9.7 — the verified diagnosis and Kenneth's confirmed decision —
> and nothing else. **The parent plan's §3–§8 staging is deliberately not carried
> forward.**

**Goal, in one sentence:** the scan card and the auto-trade fire path size the
same setup identically, and a `regime_sizing` value outside its usable range can
no longer multiply a broker order or invert the position it produces.

---

## 1. The defect, executed rather than argued

`regime_sizing` has exactly two consumers (`grep -rn regime_sizing backend/app/`),
and they compute **different multipliers over the same config block**.

| | path | line | formula |
|---|---|---|---|
| card | `routers/stock_scan.py` `_conviction_mult` | `:138-144` | `lo + (1.0 - lo) * frac` — a **linear ramp** |
| fire | `services/auto_trader.py` `_apply_vol_sizing` | `:124-131` | `max(lo, min(1.0, frac))` — a **step floor** |

On the **shipped, valid** config — `scoring_rules.yaml:463-466`,
`enabled: true, min_mult: 0.5, full_conviction_pct: 40` — executed against both
real functions:

| conviction | fire (step) | card (ramp) | ratio |
|---|---|---|---|
| 0 | 0.500 | 0.500 | 1.00× |
| 10 | 0.500 | 0.625 | 1.25× |
| 15 | 0.500 | 0.688 | 1.38× |
| **20** | **0.500** | **0.750** | **1.50×** |
| 30 | 0.750 | 0.875 | 1.17× |
| 40 | 1.000 | 1.000 | 1.00× |

**This needs no config edit and no typo.** It is a wrong number on a broker order
on `main` today, under `audit_rule`'s gate.

### 1.1 What flows from each multiplier

- **Card:** `stock_scan.py:967-970` multiplies `req.risk_pct` **and**
  `req.risk_fixed_usd` by `mult`, feeds `_position_size` (`:972`, defined
  `:678-685`) → share count on `StockPositionCard` → `StockSendDialog` → broker.
- **Fire:** `auto_trader.py:131` → `adjusted_qty = max(1, round(quantity * mult))`
  → `_dc_replace(strategy, quantity=…)` (`:140`), consumed by `fire()` at `:228`.

### 1.2 The two range defects in the same arithmetic

**(a) `min_mult` is not bounded above.** `auto_trader.py:130`'s outer `max` takes
a config value, so the multiplier is bounded above by `min_mult`, not by `1.0`.
Executed: `min_mult: 5` (the obvious decimal typo for `0.5`), conviction 10,
full 40 → `mult = 5` → **quantity 10 becomes 50**.

**(b) `min_mult > 1` INVERTS the ramp.** With `lo = 5`,
`lo + (1-lo)·frac` is monotonically *decreasing* in conviction — executed:
`0 → 5.00, 10 → 4.00, 20 → 3.00, 40 → 1.00`. The strongest signal gets the
smallest position. **Same shape as the inverted direction-conviction gate that
motivated the parent plan.** Today this is card-only; §2 moves it onto the fire
path too, which is why the guard is not optional (§2.2).

**(c) `min_mult` negative.** `min_mult: -2`, conviction 0 → the ramp returns
`-2.0` → `dollar_risk` negative → `_position_size:684` returns
`max(1, int(negative))` = **1 share against a negative dollar risk shown on the
card**. The step formula absorbs this (`max(-2, min(1, 0)) = 0.0`); the ramp does
not.

**(d) `full_conviction_pct: 0` is an uncaught `ZeroDivisionError`** on the fire
path (`auto_trader.py:130`). The card guards it (`stock_scan.py:143`,
`if full else 0.0`).

**(e) C3 — `min_mult` or `full_conviction_pct` absent empties a whole scan.**
`stock_scan.py:141-142` bare-indexes both. The call at `:968` sits inside the
`try:` at `:706`, whose `except Exception` at `:1030-1032` returns
`{"symbol": symbol, "reason": str(exc)}` — per symbol. So a missing key makes
**every symbol** reject with `reason: "'min_mult'"`, HTTP 200, zero candidates,
nothing naming the file.

---

## 2. The decision, already made

**§9.7 CONFIRMED BY KENNETH 2026-09-17 — THE LINEAR RAMP.** Both paths unify on
`lo + (1.0 - lo) * frac`. `auto_trader`'s step floor is what changes; the card
does not move.

**He was told the cost and took it:** live auto-trades get **bigger at mid
conviction** — `0.500 → 0.750` at conviction 20, a 50% increase in position size
on those fires. The step is what produced his auto-trade history to date. The ramp
wins because it is what the card has shown him all along, and because the step
gives no gradation at all between floor and full (conviction 10 and 20 size
identically).

### 2.1 What unification does NOT unify — read this before claiming parity

The two paths will share the **function**. They do not share the **argument**, and
this document does not change that:

| | conviction source | direction handling |
|---|---|---|
| card | per-symbol `compute_omm(closes, direction=req.direction)` (`stock_scan.py:763-769`) — already direction-aware | none needed |
| fire | market-wide cached `regime_monitor.get_last_conviction()`, computed as `compute_omm(closes, direction="Bullish")` (`regime_monitor.py:184-189`) | `auto_trader.py:129` negates for SELL: `100 - conviction` |

So after this change the same *conviction number* still produces the same
multiplier on both paths — which is the defect being fixed — but the two paths
continue to *derive different conviction numbers* for the same trade. **Nothing in
this document closes that**, and `100 - conviction` is not equivalent to
`compute_omm(direction="Bearish")`. Logged for a later document; out of scope here
(§7).

### 2.2 The guard is a precondition of the ramp, not a follow-up

Switching `auto_trader` to the ramp **without** the range guard makes the fire
path strictly worse than today: the step formula with `lo = 5` is a flat
overshoot (constant 5), while the ramp with `lo = 5` is *inverted* (§1.2b), and
the ramp with a negative `lo` produces a negative multiplier where the step
produced `0.0` (§1.2c). **The guard and the ramp ship in the same change or
neither ships.**

---

## 3. The change

### 3.1 One resolver, one formula — `services/config_loader.py`

Follows the precedent this repo already set for a value both scan paths need:
`load_direction_conviction_min_trend` (`config_loader.py:211`), the shared
resolver built for the bearish-gate fix. A router must not be imported by a
service, so the canonical formula cannot live in `stock_scan.py`.

```
load_regime_sizing() -> dict          # validated block, or {"enabled": False}
conviction_multiplier(directional_conviction_pct, sizing) -> float
```

`load_regime_sizing()` reads through the existing `load_scoring_cfg()` cache
(`config_loader.py:15-19`) and validates:

| key | admitted range | out of range → |
|---|---|---|
| `min_mult` | `0 < min_mult <= 1.0` | **clamp into range**, log at `ERROR` naming `regime_sizing.min_mult`, the offending value and the clamped value |
| `full_conviction_pct` | `> 0` | **treat the whole block as disabled** (`mult = 1.0`), log at `ERROR` — see D-A1 |
| either absent | — | the shipped defaults `0.5` / `40` via `.get`, logged at `WARNING`; no `KeyError` can reach `:1030` (closes §1.2e) |
| not a number | — | same as out of range for that key |

`conviction_multiplier` is the card's formula with the card's clamp, verbatim:

```python
frac = max(0.0, min(pct / full, 1.0))
return lo + (1.0 - lo) * frac
```

The `max(0.0, …)` is load-bearing and must not be dropped: conviction is
legitimately negative (`regime_gate.headwind_reject_pct: -40`), and without it
conviction `-50` on the shipped config returns `-0.125` instead of the floor.

### 3.2 `routers/stock_scan.py`

`_conviction_mult` (`:138-144`) becomes a one-line delegation to
`config_loader.conviction_multiplier`, and `:967` resolves its block through
`load_regime_sizing()` instead of bare-indexing `full_cfg`. **The name
`_conviction_mult` is kept** — `tests/test_stock_scan_regime.py:2` imports it,
and keeping it means that test now pins the canonical function rather than a
copy. No numeric behaviour changes on this path for any in-range config.

### 3.3 `services/auto_trader.py`

`:124-130` is replaced by a call to `conviction_multiplier` on
`directional_conv`. The direction derivation at `:129` **stays in
`auto_trader`** — it is the fire path's own concern (§2.1), not the formula's.

`_load_scoring_config` (`:97-106`) is **kept as a named seam** delegating to
`load_regime_sizing()`, because `tests/test_phase_g_arm_pick.py:287` patches it
by name (`mocker.patch.object(at, "_load_scoring_config", …)`). Its
`@functools.lru_cache` is dropped — `load_scoring_cfg()` is already cached, and
collapsing this removes one of the parent plan's six independent caches over the
same file. **This is the only cache this document touches.**

### 3.4 Size

~70 source, ~120 test. Well inside `audit_rule`'s ~500-line one-layer batch.

---

## 4. Decision this change forces — NOT yet Kenneth's

**D-A1 — what does `full_conviction_pct: 0` do?** There is no natural value to
clamp it to (unlike `min_mult`, which clamps to its own bounds), so the guard has
to choose:

- **(a) Disable the block — RECOMMENDED, and what §3.1 above is written for.**
  `mult = 1.0`, log at `ERROR`. It is the block's own documented off-state and the
  only option that invents no number: the user's `risk_pct` / `quantity` is used
  exactly as typed. **Cost, stated plainly: on the fire path this turns today's
  crash into a full-size fire.** Today a `ZeroDivisionError` means no order at
  all; under (a) the order goes out unsized. That is a real loosening and Kenneth
  owns it.
- **(b) Refuse.** Fire path keeps failing (but with a message naming
  `regime_sizing.full_conviction_pct` instead of a traceback); scan path must
  *not* refuse, or §1.2e's empty scan returns by another name. Asymmetric
  by construction, which is the thing this document exists to remove.

**Also still open and inherited: §9.9** (is a silently clamped multiplier
acceptable?). This document implements its recommendation — **clamp and record** —
with the record being a **log at `ERROR` only**. §9.9's "mark the affected card"
and "write to `config_health`" are cross-layer and depend on a holder this
document does not build; they are Document C's (§7). If Kenneth answers §9.9 with
"refuse the scan outright" instead, §3.1's `min_mult` row is what changes.

---

## 5. Acceptance — each clause checkable on this branch alone

1. **Both paths return the same multiplier for the same conviction** on the
   shipped config: the §1 table collapses to a single column. Test asserts the
   equality directly, over conviction `0, 10, 20, 30, 40`, by calling both
   `stock_scan._conviction_mult` and `auto_trader._apply_vol_sizing` — not by
   asserting two copies of the same expected numbers.
2. **`min_mult: 5` cannot enlarge an order on either path.** Test executes
   `_apply_vol_sizing` with a mocked config and asserts `quantity` never exceeds
   the input, and that an `ERROR` naming `regime_sizing.min_mult` was logged
   (`caplog`).
3. **`min_mult: 5` cannot invert the card.** `_conviction_mult` is
   monotonically non-decreasing in conviction for `min_mult ∈ {5, -2, 0, 0.5, 1}`.
4. **`min_mult: -2` never yields a negative multiplier** on either path.
5. **`full_conviction_pct: 0` raises no `ZeroDivisionError` on either path**, and
   behaves per D-A1's answer.
6. **`test_conviction_mult_only_reduces`
   (`tests/test_stock_scan_regime.py:5-11`) holds for every value the guard
   admits.** Its name is a claim the code did not honour; after this change it
   does, and the test is extended to say so rather than left as-is.
7. **A `regime_sizing` block missing `min_mult` does not empty a scan** (§1.2e):
   test asserts `_conviction_mult` returns a number rather than raising, and that
   no `KeyError` can reach the per-symbol handler.
8. **The two existing tests that exercise this code still pass unmodified in
   intent.** `test_phase_g_arm_pick.py:280-300` (qty 4, BUY, conviction 20)
   goes from `4 → 2` to `4 → 3`; its assertion is `resized.quantity != 4`, so it
   passes — **verify this by running it, do not assume it.**
9. `cd backend && .venv/bin/python -m pytest -q` — full suite green. Baseline to
   beat: **2516 passed, 1 skipped**.

---

## 6. Rollback

Additive and local. Reverting the three files restores today's behaviour exactly,
including the step formula on the fire path. No migration, no persisted state, no
config file is written by this change.

**Branch:** `claude/regime-sizing-fix`.

---

## 7. What this document deliberately does NOT do

Named here so none of it is silently dropped — this is the parent plan's
"diagnosed then orphaned" failure, which round 3 caught and round 4 caught again
in the fix for it.

| deferred | where it goes |
|---|---|
| Startup validation, the `config_health` holder, the pre-scheduler call site (`main.py:172-177`) | Document C |
| `GET /api/config/health`, the banner, marking the affected card | Document C (§9.11 confirmed its payload shape) |
| The **options-path C3 twin** — `scan.py:593`/`:682` bare-index `regime_gate`, and `stock_scorer.py:58` via `scan.py:586`/`:671`; `scan.py:1543` gathers with `return_exceptions=True` and `:1550-1553` converts each to a `RejectedCandidate` | **Document A′**, a sibling of this one. Parent §12 assigned it here; it is a **different config block in a different file** and folding it in doubles the batch the hard cap already fired on. Same shape, same one-layer size, its own document. |
| The three threshold stores rendering fabricated `FALLBACK` numbers on a 500 (`eventThresholdsStore.ts:38`, `ivThresholdsStore.ts:44`, `stopPremiumThresholdsStore.ts:63`) | Document C — frontend layer |
| Non-atomic YAML writes (D2) | Document B |
| §2.1's **divergent conviction inputs** (per-symbol OMM vs market-wide cached, and `100 - conviction` ≠ `direction="Bearish"`) | New, logged against `main`. Not a formula defect; a trading-semantics question for Kenneth. |
| §9.1 (does a config failure disarm auto-trade?), §9.4, §9.5, §9.6, §9.8 | Still awaiting Kenneth; none of them block this change. |
