# Pre-Breakout Scanner Parameter Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the pre-breakout scanner so it returns real results on S&P 500 scans by correcting three mathematically broken default parameters and raising the UI slider cap.

**Architecture:** Two-file change — `backend/config/strategy_params.yaml` (server-side defaults) and `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` (UI defaults + slider cap). No new files. No schema changes. No migrations.

**Tech Stack:** Python/FastAPI (backend), Next.js 15 / TypeScript (frontend), pytest (backend tests), Jest (frontend tests).

---

## Root cause summary

`breakout_setup_signal` in `strategy_engine.py` ANDs four gates. Gate 2 is broken:

```python
rng = max(b["high"] for b in recent) - min(b["low"] for b in recent)  # 10-bar range
if rng >= range_atr_mult * current_atr:   # gate: 10-bar range < 0.8 × 1-bar ATR
    return None
```

A 10-bar price range is physically 5–12× a single ATR for any normally-traded stock.
At `range_atr_mult: 0.8` this gate kills every S&P 500 symbol before the others run.

Fix: raise `range_atr_mult` to `3.0` (tight but achievable consolidation).
Also loosen ATR compression from `0.7` → `0.85` and vol compression from `0.8` → `0.9` (both still genuine squeeze conditions, just not extreme).

---

## Files to touch

| File | Change |
|---|---|
| `backend/config/strategy_params.yaml` | `range_atr_mult`, `atr_compression_ratio`, `vol_compression_ratio` in both bullish and bearish blocks |
| `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` | `PREBREAKOUT_DEFAULTS` values + `max` attribute on `rangeAtrMult` input |
| `backend/tests/test_prebreakout_params.py` | New test file — regression tests for the fixed defaults |

---

## Task 1: Fix backend config defaults

**Files:**
- Modify: `backend/config/strategy_params.yaml:137-156`

- [ ] **Step 1: Edit strategy_params.yaml**

Replace the entire `breakout_setup` block (lines 137–157) with:

```yaml
  breakout_setup:
    active:
      bullish:
        atr_compression_ratio: 0.85
        atr_avg_lookback: 20
        range_atr_mult: 3.0
        range_lookback_bars: 10
        vol_compression_ratio: 0.9
        resistance_proximity_pct: 0.08
        swing_lookback: 50
        require_trend: true
      bearish:
        atr_compression_ratio: 0.85
        atr_avg_lookback: 20
        range_atr_mult: 3.0
        range_lookback_bars: 10
        vol_compression_ratio: 0.9
        resistance_proximity_pct: 0.08
        swing_lookback: 50
        require_trend: true
    # no search block — SetupSignal has no entry/stop/target; cannot be backtested
```

- [ ] **Step 2: Verify YAML parses without error**

```bash
cd backend && python -c "import yaml; yaml.safe_load(open('config/strategy_params.yaml'))" && echo OK
```
Expected output: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/config/strategy_params.yaml
git commit -m "fix(prebreakout): loosen range/ATR/vol defaults so scanner returns real results"
```

---

## Task 2: Write a regression test that proves the old defaults produce zero results and the new ones produce at least one

**Files:**
- Create: `backend/tests/test_prebreakout_params.py`

- [ ] **Step 1: Create the test file**

```python
"""Regression tests for breakout_setup_signal default parameters.

The original defaults (range_atr_mult=0.8) made the range compression gate
mathematically impossible: a 10-bar price range cannot be smaller than 0.8×
a single ATR for any normally-traded stock. These tests verify that the fixed
defaults pass real OHLCV data, and that the broken defaults reject it.
"""
import pytest
from app.services.strategy_engine import breakout_setup_signal


def _make_bars(n: int = 60, base: float = 100.0, atr: float = 1.0) -> list[dict]:
    """Synthetic OHLCV bars: gentle uptrend, tight consolidation in last 20 bars.

    Last 10 bars coil within ±0.5 ATR of the base price, sitting ~4% below a
    prior swing high at ~base*1.05. ATR is kept small relative to price so that
    range_atr_mult=3.0 is achievable.
    """
    bars = []
    for i in range(n):
        if i < n - 20:
            # Uptrend phase — establish 50-bar swing high above base
            close = base * (1.0 + i * 0.002)
            high  = close + atr
            low   = close - atr
        else:
            # Consolidation phase — tight coil near (but below) swing high
            close = base * 1.04 + (i % 3 - 1) * atr * 0.2
            high  = close + atr * 0.4
            low   = close - atr * 0.4
        bars.append({
            "open":   close - atr * 0.1,
            "high":   high,
            "low":    low,
            "close":  close,
            "volume": 1_000_000 - (5_000 if i >= n - 20 else 0),  # quiet in coil
        })
    return bars


def test_fixed_defaults_return_signal():
    """With the corrected defaults the scanner must return a SetupSignal."""
    bars = _make_bars(n=60, base=100.0, atr=0.5)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=3.0,
        range_lookback_bars=10,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
        require_trend=True,
    )
    assert result is not None, (
        "Fixed defaults should pass a coiling stock near resistance, got None"
    )
    assert 0 <= result.confidence <= 100


def test_broken_range_mult_returns_none():
    """The original range_atr_mult=0.8 must reject the same bars (documents the bug)."""
    bars = _make_bars(n=60, base=100.0, atr=0.5)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=0.8,   # broken original default
        range_lookback_bars=10,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
        require_trend=True,
    )
    assert result is None, (
        "range_atr_mult=0.8 should kill the range gate for any real stock, got a signal"
    )


def test_confidence_within_bounds():
    """Confidence must always be clamped to [0, 100]."""
    bars = _make_bars(n=60, base=200.0, atr=1.0)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        range_atr_mult=3.0,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
    )
    if result is not None:
        assert 0 <= result.confidence <= 100
```

- [ ] **Step 2: Run the new tests — expect them to PASS**

```bash
cd backend && pytest tests/test_prebreakout_params.py -v
```

Expected:
```
PASSED tests/test_prebreakout_params.py::test_fixed_defaults_return_signal
PASSED tests/test_prebreakout_params.py::test_broken_range_mult_returns_none
PASSED tests/test_prebreakout_params.py::test_confidence_within_bounds
```

If `test_fixed_defaults_return_signal` fails, the synthetic bars may not satisfy the trend or proximity gate — adjust `base * 1.04` up toward `base * 1.07` (farther below the swing high) or reduce `atr` to `0.3` to tighten the coil.

- [ ] **Step 3: Run the full existing test suite to catch regressions**

```bash
cd backend && pytest --tb=short -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_prebreakout_params.py
git commit -m "test(prebreakout): regression tests for range_atr_mult fix"
```

---

## Task 3: Fix frontend defaults and slider cap

**Files:**
- Modify: `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx:7-24,94`

- [ ] **Step 1: Update PREBREAKOUT_DEFAULTS and the slider cap**

In `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`, make three edits:

**Edit 1** — interface comment for rangeAtrMult (line 9):
```ts
  rangeAtrMult: number;           // 0.1–5.0,  default 3.0
```

**Edit 2** — PREBREAKOUT_DEFAULTS (lines 17-24):
```ts
export const PREBREAKOUT_DEFAULTS: PreBreakoutParams = {
  atrCompressionRatio: 0.85,
  atrAvgLookback: 20,
  rangeAtrMult: 3.0,
  rangeLookbackBars: 10,
  volCompressionRatio: 0.9,
  resistanceProximityPct: 0.08,
  swingLookback: 50,
};
```

**Edit 3** — slider max on rangeAtrMult input (line 94):
```tsx
              min={0.1} max={5.0} step={0.1}
```

- [ ] **Step 2: Run TypeScript typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/PreBreakoutParamsPanel/index.tsx
git commit -m "fix(prebreakout): update UI defaults and slider cap to match backend fix"
```

---

## Task 4: Adversarial audit + iterative error fixing

This task is executed by a subagent using the `bmad-adversarial-review` skill. The subagent should:

1. Read every file changed in Tasks 1–3.
2. Run the full backend test suite: `cd backend && pytest --tb=short -q`
3. Run the frontend typecheck: `cd frontend && npm run typecheck`
4. Apply the adversarial review lens from the skill.
5. Fix any errors found, re-run tests, and repeat until clean.
6. Report what was fixed and what was confirmed sound.

---

## Definition of done

- [ ] `cd backend && pytest --tb=short -q` — all tests pass, including the three new regression tests
- [ ] `cd frontend && npm run typecheck` — no TypeScript errors
- [ ] A manual scan of any S&P 500 or DOW30 universe in Pre-Breakout mode returns at least one result
- [ ] "Reset to defaults" in the UI panel shows `Range/ATR multiplier: 3` (not 0.8)
