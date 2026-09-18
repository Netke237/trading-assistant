# Auto-trader: size bearish trades off the bearish conviction frame

**Date:** 2026-09-18
**Piece:** Regime conviction sizing is inverted for bearish auto-trades.
**Status:** PLAN — not yet audited, not implemented.

---

## 1. The defect, as measured

`auto_trader.py:176`:

```python
directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
```

Two independent faults. Only the first is live.

### 1.1 LIVE: `action` does not encode direction, so bearish trades are sized inverted

`conviction` comes from `regime_monitor.get_last_conviction()`, which caches
`compute_omm(closes, direction="Bullish").conviction_pct` (`regime_monitor.py:184`).
That is the **bullish frame**: `(P(Bull) - P(Bear)) * 100`, signed, range `[-100, +100]`
(`regime_omm.py:126-133`, scaled at `:208`; the `conviction_label` bands at ±15/±40
confirm the sign convention).

`AutoTradeArm/index.tsx:203` is the **only** production caller of `armAutoTrade`, and it
hardcodes `action: 'BUY'` with the accurate comment *"long single-leg option (call or put)
is always buy-to-open"*. A bearish options trade in this app is a **long put** — which is
`BUY`. Therefore:

- `strategy.action` is `"BUY"` for every armed trade, bullish or bearish.
- Every bearish trade takes the `if` branch and is sized off **bullish** conviction.

With the live config (`scoring_rules.yaml:463-471` — `min_mult: 0.3`, `full_conviction_pct: 40`)
and the ramp `lo + (1 - lo) * clamp(conv/full, 0, 1)` (`conviction_sizing.py:309-380`):

| Regime (bullish conv) | Long put SHOULD get | Actually gets | Error |
|---|---|---|---|
| +40 — strong bull, **opposes** the put | 0.30 (floor) | **1.00 (full)** | 3.33x oversized |
| 0 — neutral | 0.65 | 0.30 | 2.17x undersized |
| -40 — strong bear, **favours** the put | 1.00 (full) | **0.30 (floor)** | 3.33x undersized |

The ramp is **exactly inverted** for bearish trades: largest into the regime that opposes
the trade, smallest into the regime that supports it. This is worse than a mis-scale; it is
a sign error on the risk axis, and it has been live since 2e027c76.

### 1.2 DEAD: `100 - conviction` is not a mirror of a signed scale

On a signed `[-100, +100]` scale the bearish mirror is `-conviction`. `100 - conviction`
is a mirror of an unsigned `[0, 100]` scale, which this is not. Worse, since
`full_conviction_pct` is 40, `100 - conviction >= 60` for every `conviction <= 40`, so the
ramp clamps to 1.0 — the SELL path would fire at **full size for essentially every regime**.

**This branch is unreachable from the UI** (§1.1: `action` is always `"BUY"`). It is
reachable only by hand-rolling a POST to `/auto-trade/arm`. So correcting `100 - conviction`
to `-conviction` — the fix the previous session's handoff prescribed — **would not change
any real trade**. The handoff's diagnosis named the wrong branch.

### 1.3 The existing test encodes the confusion

`test_auto_trader.py:514` (`test_vol_sizing_sell_reduced_in_strongly_bullish_market`) arms
`action="SELL"` on `option_symbol="AAPL260620P00185000"` — a **short put**, which is a
*bullish* position — and asserts it must be *reduced* in a bullish market. The test passes,
and it is asserting the wrong thing about an unreachable branch.

Secondary: that fixture uses OCC format (`AAPL260620P00185000`) while the frontend actually
sends Bamendjou's display id (`AAPL|185|2026-06-20|P`, `domain.ts:764`). The test fixtures
and production disagree on the format of this field.

---

## 2. The fix: thread direction explicitly

Direction is known at arm time and is simply not sent. `AutoTradeArm/index.tsx:303` already
renders `card.direction` on the Arm button's own label. `Direction = 'Bullish' | 'Bearish'`
(`domain.ts:7`).

Inferring direction from `action` is what caused this bug. Inferring it from
`option_symbol`'s right (C/P) was considered and **rejected**: that field is Bamendjou's
display id, and `AutoTradeArm/index.tsx:186-187` records that OCC conversion is a tracked
follow-up — so the format is expected to change under us. Direction becomes an explicit,
carried field, exactly as Phase G threaded the `picked_*` fields.

### 2.1 Changes

**`backend/app/routers/auto_trade.py` — `ArmRequest`**
Add `direction: Literal["Bullish", "Bearish"]`, **required, no default**.

Required is deliberate. A default of `"Bullish"` would reintroduce precisely the silent
mis-direction this change removes, and it is the same failure shape as the documented G5-1
hole (`extra='ignore'` letting a misspelled key arm with NULLs). Required means a body
without `direction` is a **422 at arm time** — loud, before anything is armed — rather than
a wrong size at fire time. This is NOT the rejected "fail closed at fire" option: nothing new
refuses at fire, and no new refusal/alert path is added.

**`backend/app/services/auto_trader.py` — `ArmedStrategy`**
Add `direction: Literal["Bullish", "Bearish"]`, required. It must be placed **before**
`entry_premium` (`:34`), because Python forbids a field without a default after fields with
defaults. Placing it immediately after `action` keeps the directional fields adjacent.
`ArmedStrategy(**req.model_dump())` (`auto_trade.py:83`) keys off field names, so both sides
must use the identical name.

**`backend/app/services/auto_trader.py:176` — `_apply_vol_sizing`**

```python
directional_conv = conviction if strategy.direction == "Bullish" else -conviction
```

The `action`-based inference is **removed**, not kept alongside. Once direction is explicit,
`action` carries no directional meaning and a second source of truth is how these drift apart.

**`frontend/lib/api.ts` — `armAutoTrade` request type**
Add `direction: 'Bullish' | 'Bearish'` (required, so a caller that forgets fails typecheck
rather than at runtime).

**`frontend/components/organisms/AutoTradeArm/index.tsx:203`**
Add `direction: card.direction` to the payload. Update the `action: 'BUY'` comment: it stays
`BUY` and that remains correct, but it no longer implies bullishness.

### 2.2 Test changes

- **Rewrite** `test_vol_sizing_sell_reduced_in_strongly_bullish_market` (`:514`). Replace
  with the coherent case it was reaching for: a **bearish long put** (`action="BUY"`,
  `direction="Bearish"`) in a strongly bullish regime must be cut to the floor.
- **New tests**, each asserting a specific quantity, not a direction of change:
  - Bearish @ conviction +40 (regime opposes) -> mult 0.30, floor.
  - Bearish @ conviction -40 (regime favours) -> mult 1.00, full size.
  - Bearish @ conviction 0 -> mult 0.65.
  - Bullish @ conviction +40 -> 1.00 (regression guard: existing bullish behaviour unchanged).
  - `POST /auto-trade/arm` without `direction` -> 422 (the loud-failure guarantee of §2.1).
- **Mechanical:** 26 existing `ArmedStrategy(...)` constructions across
  `test_auto_trader.py` (20), `test_phase_g_arm_pick.py` (3) and
  `test_premium_stop_per_position.py` (3) gain `direction=`. All are keyword-based
  (verified), so no positional breakage. Each gets the direction its option right implies,
  so the fixtures stop being self-contradictory.

---

## 3. Explicitly out of scope

- **O4** — `fire_now()` still books no `PortfolioPosition`. Untouched.
- **G5-1** — `ArmRequest` gets no `model_config = ConfigDict(extra='forbid')`. That is a
  behaviour change to a live endpoint and is its own decided piece; the agreed order is O4
  before G5-1. Note: making `direction` required does NOT depend on `extra='forbid'` — a
  *missing* required field is a 422 regardless of the extra-key policy.
- **OCC conversion** of `option_symbol`. Tracked separately; this change deliberately stops
  depending on that field's format.
- The scan path (`stock_scan.py:970`). It passes `regime_signal["conviction_pct"]`, which
  `stock_scan.py:418` computes via `compute_omm` with the **scan's own direction**, so it is
  already direction-aware and correctly framed. Verified, unchanged.

## 4. Verification

- `cd backend && python -m pytest -q` — expect 2610 passed / 1 skipped baseline, plus the new cases.
- `cd frontend && npm run typecheck` — must be silent.
- `cd frontend && npm run test` — 134 suites / 1701 tests baseline.
- `python3 scripts/state.py` — exits 0, no drift.
