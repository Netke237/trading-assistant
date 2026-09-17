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

Switching `auto_trader` to the ramp **without** the range guard changes the fire
path's failure mode for the worse in two distinct ways, and one of them is a
larger order:

**`min_mult: -2` — the ramp is larger in error.** Executed at conviction 0: the
step returns `max(-2, min(1, 0)) = 0.0`; the ramp returns `-2.0`. A negative
multiplier is a negative `dollar_risk` on the card (§1.2c) and, on the fire path,
`max(1, round(qty * -2))` = **1 contract** silently replacing the armed quantity.

**`min_mult: 5` — the ramp is mis-ORDERED, not larger.** Round 1 of this
document's own audit corrected an earlier claim here, and the correction is kept
in place of the claim. Executed at `lo = 5, full = 40`:

| conviction | step | ramp |
|---|---|---|
| 0 | 5.0 | 5.0 |
| 10 | 5.0 | 4.0 |
| 20 | 5.0 | 3.0 |
| 40 | 5.0 | 1.0 |

The ramp is **≤ the step at every conviction** — so it is not "strictly worse" in
magnitude, and this document no longer says it is. What the ramp adds is a defect
the step does not have: the multiplier *decreases* as conviction rises. Both are
wrong; only the ramp is wrong in the shape that hid the direction-conviction gate
for three months. Neither is acceptable, which is the point.

**Conclusion, which stands on the `min_mult: -2` row alone:** the guard and the
ramp ship in the same change, or neither ships.

---

## 3. The change

### 3.1 One normaliser, one formula — `services/config_loader.py`

Follows the precedent this repo already set for a value both scan paths need:
`load_direction_conviction_min_trend` (`config_loader.py:211`), the shared
resolver built for the bearish-gate fix. A router must not be imported by a
service, so the canonical formula cannot live in `stock_scan.py`.

Three symbols, and **the split between them is the thing to get right**:

```
_normalise_regime_sizing(block) -> (normalised_block, problems)   # pure, no I/O, no logging
load_regime_sizing()            -> dict                           # reads the file, LOGS the problems
conviction_multiplier(pct, sizing) -> float                       # normalises AGAIN, then computes
```

**THE GUARD LIVES AT THE POINT OF USE, NOT AT THE LOADER.** `conviction_multiplier`
runs `_normalise_regime_sizing` on whatever dict it is handed and discards the
problem list (the loader already logged it; normalisation is idempotent, so a
block that came through `load_regime_sizing()` is unchanged by the second pass).
This is not belt-and-braces — it is the only placement that works:

- §3.3 deliberately keeps `_load_scoring_config` as a **mockable named seam**
  returning a raw dict. A guard at the loader is bypassed by every caller that
  supplies the dict — including `tests/test_phase_g_arm_pick.py:287`, which
  patches exactly that seam today.
- Today `auto_trader.py:130` applies its only bound (`max(min_mult, min(1.0, …))`)
  **inline at the point of use**. Moving the sole bound to the loader would be a
  net loss of safety on the fire path, not a gain.
- §5's acceptance clauses call `_conviction_mult` and `_apply_vol_sizing`. If the
  guard sits at the loader those clauses do not exercise it and would pass with
  the hazard intact.

`_normalise_regime_sizing`:

| key | value | normalised to | why |
|---|---|---|---|
| `enabled` | not `True` | block off → multiplier `1.0` | today's behaviour, both paths |
| `min_mult` | anything outside `0 < x <= 1.0` — including absent, non-numeric, `5`, `0` and `-2` | **`0.5`** | ONE rule, both bounds; see the two boxes below |
| `full_conviction_pct` | absent, non-numeric, or `<= 0` | **`40`** | D-A1 |

**`0.5` and `40` are the values in the shipped file** (`scoring_rules.yaml:465-466`),
already `auto_trader.py:124-125`'s `.get` defaults. They are the file's own numbers,
not invented ones. **The rule is FALL BACK, not CLAMP**, and both boxes below are
cases where clamping to a bound is what puts the wrong number on the order.

> **The lower bound — clamping to `0` DOUBLES the card.** The admitted range
> `0 < x <= 1` has an *exclusive* lower bound, so "clamp into range" names no
> value at all for `min_mult <= 0`, and the obvious reading — clamp to the
> written `0` — produces a **larger** position than no scaling at all. `stock_scan.py:683` is
> `dollar_risk = risk_fixed if risk_fixed else (account * (risk_pct or 0.01))`;
> `req.risk_pct * 0.0` is `0.0`, which is falsy, so it falls through to the
> hardcoded 1% default. Executed, account $100,000, `risk_pct` 0.005, entry 100 /
> stop 95:
>
> | multiplier | `sized_risk_pct` | shares | dollar risk |
> |---|---|---|---|
> | none (1.0) | 0.005 | 100 | $500 |
> | floor (0.5) | 0.0025 | 50 | $250 |
> | **clamped to 0** | **0.0** | **200** | **$1,000** |
>
> A "shrink to nothing" multiplier doubles the share count on
> `StockPositionCard` → `StockSendDialog` → broker. `0.5` cannot trip the falsy
> fall-through.

> **The upper bound — clamping to `1.0` DOUBLES it too, and this was caught by
> running the prescription rather than reading it.** `min_mult > 1.0` *does* have
> an obvious clamp target, and `1.0` was this row's first draft. Executed, it is
> wrong in the same direction: `min_mult: 5` clamped to `1.0` returns **`1.0` at
> every conviction**, so a decimal typo silently sizes every position at FULL
> size — `1.000` where the shipped config gives `0.500` at conviction 0. The
> guard would be the thing putting the wrong number on the order. Falling back to
> `0.5` returns the shipped curve instead — `[0.5, 0.625, 0.75, 0.875, 1.0]` over
> conviction `0…40` (executed) — monotone, never above `1.0`, and never above
> what a correct config would have given.

`conviction_multiplier`, after normalisation:

```python
if not sizing.get("enabled"):
    return 1.0
frac = max(0.0, min(pct / full, 1.0)) if full else 0.0
return lo + (1.0 - lo) * frac
```

Two clauses here are load-bearing and neither may be dropped:

- `max(0.0, …)` — conviction is legitimately negative
  (`regime_gate.headwind_reject_pct: -40`). Without it, conviction `-50` on the
  shipped config returns `-0.125` instead of the floor `0.5` (executed).
- `if full else 0.0` — kept from `stock_scan.py:143` even though normalisation
  guarantees `full > 0`, so that no future caller can reintroduce §1.2(d). An
  earlier draft of this document called its snippet "the card's formula verbatim"
  while having dropped this clause, which reconstructed §1.2(e)'s empty scan with
  a zero in place of a missing key.

**`load_regime_sizing()` wraps the read in `try/except`**, logs at `ERROR`, and
returns `{"enabled": False}` on a missing or unparseable file. This is not
optional — see §3.3.

### 3.2 `routers/stock_scan.py`

`_conviction_mult` (`:138-144`) becomes a one-line delegation to
`config_loader.conviction_multiplier`, and `:967` resolves its block through
`load_regime_sizing()` instead of bare-indexing `full_cfg`. **The name
`_conviction_mult` is kept** — `tests/test_stock_scan_regime.py:2` imports it,
so that test now pins the canonical function rather than a copy.

No numeric behaviour changes on this path **for any config the normaliser leaves
untouched**. It does change for the out-of-range values, and D-A1 states that cost.

### 3.3 `services/auto_trader.py`

`:124-130` is replaced by a call to `conviction_multiplier` on
`directional_conv`. The direction derivation at `:129` **stays in
`auto_trader`** — it is the fire path's own concern (§2.1), not the formula's.

`_load_scoring_config` (`:97-106`) is **kept as a named seam** delegating to
`load_regime_sizing()`, because `tests/test_phase_g_arm_pick.py:287` patches it
by name. Its `@functools.lru_cache` is dropped — `load_scoring_cfg()` is already
cached, there is exactly one caller (`:115`) and no `cache_clear()` anywhere, so
collapsing it removes one of the parent plan's six independent caches over the
same file. **This is the only cache this document touches.**

> **The `try/except` that goes with that cache must NOT be dropped with it, and
> the reason is the disarm ordering.** Today `_load_scoring_config` catches a
> malformed or missing `scoring_rules.yaml`, logs a warning and returns `{}` —
> sizing disabled, the order fires at the typed quantity.
> `config_loader.load_scoring_cfg()` (`:15-19`) has **no error handling at all**.
> If the exception propagates it surfaces at `_apply_vol_sizing`
> (`auto_trader.py:115`), called from `fire()` at `:228` — which runs **after**
> the disarm at `:223-225`:
>
> ```
> 223:             strategy = self._state.strategy
> 224:             self._state.armed = False
> 225:             self._state.strategy = None
> ...
> 228:         strategy = _apply_vol_sizing(strategy)
> ```
>
> The armed pick is destroyed, no order is placed, and there is no retry path.
> `load_regime_sizing()` catching it (§3.1) preserves today's fire-path behaviour
> exactly and gives both paths the same rule, which is this document's thesis.

### 3.4 Size

~95 source, ~170 test. Inside `audit_rule`'s ~500-line one-layer batch.

## 4. Decision this change forces — NOT yet Kenneth's

**D-A1 — what does `full_conviction_pct: 0` (or negative) do?** There is no
natural value to clamp it to, so the normaliser has to choose. Today's behaviour
differs by path: the card returns the floor (`stock_scan.py:143`'s
`if full else 0.0` → `frac = 0.0` → `mult = 0.5`); the fire path raises an
uncaught `ZeroDivisionError` (`auto_trader.py:130`) and places no order at all.

| | card at conviction 20 | fire path | verdict |
|---|---|---|---|
| **today** | `0.500` | crash, no order | the divergence this document exists to remove |
| **(a) treat the block as disabled** (`mult = 1.0`) | `1.000` — **doubles** | full-size fire | invents no number, but doubles a live card |
| **(b) fall back to the shipped `40`** | `0.750` | `0.750` | **RECOMMENDED** |
| **(c) refuse** | must not refuse, or §1.2(e)'s empty scan returns by another name | refuses | asymmetric by construction |

**Recommendation is (b), and it changed from (a) because round 1 found (a)'s
card cost.** An earlier draft recommended (a) and stated its cost for the fire
path only — "turns today's crash into a full-size fire" — while `0.500 → 1.000`
on the card went unmentioned. Kenneth would have been asked to own half a
loosening.

(b) is the smaller move and the consistent one — it is the same fall-back-to-the-
shipped-value rule §3.1 applies to `min_mult`, for the same reason: the shipped
default is the file's own number, not an invented one. Its card cost is `0.500 → 0.750`, which is **exactly the
1.5× the ramp produces everywhere else** at conviction 20 — so it introduces no
new magnitude of change, where (a) introduces a 2×. On the fire path it replaces
a crash with the same `0.750` the card shows, which is the parity this document
is for.

**Also still open and inherited: §9.9** (is a silently clamped multiplier
acceptable?). §9.9's live alternatives were "clamp and record" versus "refuse the
scan outright"; this document takes the first — **never refuse, always record** —
but delivers it as a **fall back to the shipped value** rather than a clamp to a
bound, because §3.1's two boxes show that clamping to either bound is itself a
wrong number on an order. The record is a **log at `ERROR` only**. §9.9's "mark the affected card"
and "write to `config_health`" are cross-layer and depend on a holder this
document does not build; they are Document C's (§7).

**What "log at `ERROR` only" is worth on the stocks path, stated rather than
assumed:** nothing on screen. `lib/stockScan.ts:103-105` is `catch { … }` with no
error binding at all, so a stocks-mode scan failure is already completely silent
in the UI (§7). A clamped multiplier is therefore visible to Kenneth **only in
the server log** until Document C ships. That is the honest reach of the record
this document delivers, and it is a reason to sequence Document C soon, not a
reason to widen this one.

## 5. Acceptance — each clause checkable on this branch alone

Every clause below was run against a verbatim implementation of §3 before being
written down. The five that an earlier draft got wrong failed that run, which is
how they were found.

1. **Both paths return the same multiplier for the same conviction**, and the
   §1 table collapses to a single column. Two assertions, because one is not
   enough:
   - the table itself, against `config_loader.conviction_multiplier` directly;
   - **that the fire path actually routes through it** — `_apply_vol_sizing`,
     BUY, conviction 10, **`quantity=100` → 62** (the step gives 50).
     **The quantity matters and 4 will not do.** `_apply_vol_sizing` returns an
     `ArmedStrategy`, not a multiplier, and returns it *unchanged* when
     `adjusted_qty == quantity` (`:133-134`), so the only observable is
     `round(quantity * mult)` — quantised, with banker's rounding. Executed at
     conviction 10, the 1.25× row of the §1 table:

     | quantity | step | ramp |
     |---|---|---|
     | 4 | 2 | **2** — divergence invisible |
     | 10 | 5 | 6 |
     | 100 | 50 | 62 |

     A clause-1 test written at `quantity=4` passes with the step formula still
     shipped.
2. **`min_mult: 5` cannot enlarge an order on either path**, including through
   the mocked seam: `_apply_vol_sizing` with `_load_scoring_config` patched to
   the raw `{"enabled": True, "min_mult": 5, "full_conviction_pct": 40}` — the
   exact shape `tests/test_phase_g_arm_pick.py:287` uses — asserts `quantity`
   never exceeds the input. This clause is why §3.1 puts the guard at the point
   of use: with the guard at the loader it fails (executed: qty 10, conviction
   10 → **40**).
3. **`min_mult: 5` cannot invert the card.** `_conviction_mult` is monotonically
   non-decreasing in conviction for `min_mult ∈ {5, -2, 0, 0.5, 1}`. Executed
   against §3: every out-of-range value returns the shipped curve
   `[0.5, 0.625, 0.75, 0.875, 1.0]` over conviction `0…40`.
4. **`min_mult: -2` and `min_mult: 0` never yield a multiplier `<= 0`** on
   either path — and specifically never `0.0`, which §3.1's box shows doubles
   the card.
5. **`full_conviction_pct: 0` raises no `ZeroDivisionError` on either path** and
   behaves per D-A1's answer. Executed against the §3 implementation: without
   the `if full else 0.0` clause **both** paths raise.
6. **`test_conviction_mult_only_reduces` (`tests/test_stock_scan_regime.py:5-11`)
   holds for every value the normaliser admits** — and its line 10 case,
   `_conviction_mult(40, {"enabled": False})`, still returns `1.0`. That dict
   carries no `min_mult` and no `full_conviction_pct`, so a *literal* one-line
   delegation to an unguarded formula raises `KeyError` there. The test's name is
   a claim the code did not honour; after this change it does.
7. **A `regime_sizing` block missing `min_mult` or `full_conviction_pct` does not
   empty a scan** (§1.2e): `_conviction_mult` returns a number rather than
   raising, so no `KeyError` can reach the per-symbol handler at `:1030-1032`.
8. **A malformed or missing `scoring_rules.yaml` does not destroy an armed
   pick** (§3.3): with `load_scoring_cfg` raising, `_apply_vol_sizing` returns
   the strategy unchanged and `fire()` proceeds at the typed quantity, as it does
   today. The disarm at `:223-225` precedes `_apply_vol_sizing` at `:228`, so a
   propagating exception loses the pick with no order and no retry.
9. **The two existing tests that exercise this code still pass.**
   `test_phase_g_arm_pick.py:280-300` (qty 4, BUY, conviction 20) goes from
   `4 → 2` to `4 → 3`; its assertion is `resized.quantity != 4`, so it survives.
   Verified by running, not assumed: `pytest -q tests/test_stock_scan_regime.py
   tests/test_phase_g_arm_pick.py` → **20 passed** on `main` today.
10. `cd backend && .venv/bin/python -m pytest -q` — full suite green. Baseline to
    beat, measured: **2516 passed, 1 skipped**.

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
| **GATE, and this document leans on it** — a stocks-mode scan failure is completely silent on screen. `lib/stockScan.ts:103-105` is `catch { store.setScanState('FAILED'); return null; }`, **no error binding at all**; `RunScanButton/index.tsx:90-91` returns early for stocks mode so its toast never runs. Two further submit sites are also unaddressed: `step-5-strategy/page.tsx:247-248` (raw `String(e)`, transport prefix included) and `step-4-prebreakout/page.tsx` | Document C — frontend layer. **Named here because §4's record for a clamped multiplier is a log at `ERROR` only, and §1.2(e) is a stocks-path scan failure — so on that path the user-visible record for both is nil until this closes.** An earlier draft of §7 omitted this item, which is the parent's own "diagnosed then orphaned" failure repeated in the table written to prevent it. |
| The three threshold stores rendering fabricated `FALLBACK` numbers on a 500 (`eventThresholdsStore.ts:38`, `ivThresholdsStore.ts:44`, `stopPremiumThresholdsStore.ts:63`) | Document C — frontend layer |
| **NEW, found by round 1** — `stock_scan.py:683`'s `(risk_pct or 0.01)` makes `sized_risk_pct == 0.0` fall through to a hardcoded 1%, so a multiplier of zero **enlarges** the position (§3.1's box: 200 shares / $1,000 against an unscaled 100 / $500). §3.1's normaliser guarantees `mult` can never be the trigger, but `req.risk_pct = 0` reaching `:969` still is | Logged against `main`. Not closed here — closing it is a change to `_position_size`'s contract, not to `regime_sizing`. |
| Non-atomic YAML writes (D2) | Document B |
| §2.1's **divergent conviction inputs** (per-symbol OMM vs market-wide cached, and `100 - conviction` ≠ `direction="Bearish"`) | New, logged against `main`. Not a formula defect; a trading-semantics question for Kenneth. |
| §9.1 (does a config failure disarm auto-trade?), §9.4, §9.5, §9.6, §9.8 | Still awaiting Kenneth; none of them block this change. |
