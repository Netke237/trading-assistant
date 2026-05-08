---
workstream: WS-36
branch: feat/ws-36-bearish-scoring
phase: 1
depends_on: fix/ws-33-foundation (merged to main)
conflict_class: Zero — only modifies stock_scorer.py; no schema changes, no frontend changes
---

# WS-36: Bearish Direction Scoring

## Mission

All scoring rules in `stock_scorer.py` are currently bullish-only. When `direction: "Bearish"` is passed to the scan, the scorer silently produces bullish-biased scores — which is wrong. This workstream adds proper bearish inversion to all `_rule_*` functions so bearish scans produce direction-appropriate results.

**PRD coverage:** G1, R1, FR-08

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/scoring/stock_scorer.py` | Modify | Add bearish logic to all `_rule_*` functions |
| `backend/tests/test_bearish_scoring.py` | Create | Tests that bearish setups score correctly |

**Do NOT touch any other files.**

---

## Read-Only References

- `backend/app/scoring/stock_scorer.py` — current implementation to extend (read fully before modifying)
- `backend/config/scoring_rules.yaml` — thresholds (no changes needed to YAML)
- `backend/tests/fixtures/AAPL.json` — candle fixture format for test data

---

## Current Code Structure (stock_scorer.py)

The main entry point is `score_stock(symbol, direction, horizon, bars, ...)`. It calls these rule functions:
- `_rule_trend(closes, cfg)` — EMA crossover
- `_rule_pullback(bars, cfg)` — Fib/ATR retracement
- `_rule_trigger(bars, cfg)` — candle pattern reversal
- `_rule_vol(iv_rank, cfg)` — IV positioning (direction-neutral, no change needed)
- `_rule_event(earnings_date, dividend_date, cfg)` — event risk (direction-neutral, no change needed)

`_detect_candle(bars)` is called from `_rule_trigger()`.

---

## Bearish Inversion Rules

Add a `direction: Direction` parameter to `_rule_trend`, `_rule_pullback`, `_rule_trigger`, and `_detect_candle`. All existing call sites default to `"Bullish"`.

### Rule 1: Trend (`_rule_trend`)

```python
# Bullish: fast_ema > slow_ema (already implemented)
# Bearish: fast_ema < slow_ema
# Bullish: slow rising = PASS
# Bearish: slow declining = PASS

if direction == "Bearish":
    above = fast_val < slow_val   # inverted
    slow_falling = slow_slope < 0
    fast_falling = fast_slope < 0
    
    if not above:
        return RuleResult("trend", "REJECT", 10, {"reason": "fast_above_slow_bearish"})
    if slow_required and not slow_falling:
        return RuleResult("trend", "REJECT", 20, {"reason": "slow_ma_rising_bearish"})
    if fast_required and not fast_falling:
        return RuleResult("trend", "REJECT", 20, {"reason": "fast_ma_rising_required_bearish"})
    if not fast_falling:
        return RuleResult("trend", "CAUTION", 60, {"reason": "fast_ma_flat_bearish"})
    return RuleResult("trend", "PASS", 90, {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2)})
```

### Rule 2: Pullback (`_rule_pullback`)

For bearish: instead of "price pulled back from a swing HIGH toward support", check "price rallied from a swing LOW toward resistance then started rejecting".

```python
# Bearish pullback: price bounced above a swing low, then rejected from resistance
# Use swing_low as reference instead of swing_high
# Retracement measured as (current_price - swing_low) / swing_range
# Same fib zones apply but from the low side

if direction == "Bearish":
    swing_low = min(b["low"] for b in window)
    # current retracement upward from the low
    retracement = (current_price - swing_low) / swing_range if swing_range > 0 else 0
    # Same fib thresholds apply — shallow bounce = not ready, golden zone = entry signal
    # (reuse same fib_result logic but from inverted perspective)
```

### Rule 3: Trigger (`_rule_trigger` + `_detect_candle`)

Add bearish candle patterns to `_detect_candle`:

**Shooting star:**
- Small body at the BOTTOM of the candle's range
- Upper wick ≥ 2× body size
- Close near the low: `(b["high"] - b["close"]) / rng >= 0.65`

```python
# Shooting star
if (body >= 0.05 * rng and upper_wick >= 2 * body and
        lower_wick <= 0.10 * rng and (b["high"] - b["close"]) / rng >= 0.65):
    return True, "shooting_star"
```

**Bearish engulfing** (needs prior bar):
```python
# Bearish Engulfing: prior bar was bullish, current bar is bearish and engulfs it
if len(bars) >= 2:
    prev = bars[-2]
    if (prev["close"] > prev["open"] and b["close"] < b["open"] and
            b["open"] >= prev["close"] and b["close"] <= prev["open"] and
            body >= 0.40 * rng):
        return True, "bearish_engulfing"
```

**Evening star** (needs 3 bars):
```python
# Evening star: large bullish candle, small body (gap up or near gap), large bearish candle
if len(bars) >= 3:
    b1, b2, b3 = bars[-3], bars[-2], bars[-1]
    b1_body = abs(b1["close"] - b1["open"])
    b2_body = abs(b2["close"] - b2["open"])
    b3_body = abs(b3["close"] - b3["open"])
    rng3 = b3["high"] - b3["low"]
    if (b1["close"] > b1["open"] and         # b1 bullish
            b2_body < b1_body * 0.4 and       # b2 small body (doji/spinning top)
            b3["close"] < b3["open"] and       # b3 bearish
            b3_body >= b1_body * 0.5 and       # b3 substantial body
            b3["close"] < (b1["open"] + b1["close"]) / 2):  # b3 closes into b1's body
        return True, "evening_star"
```

In `_rule_trigger`, when `direction == "Bearish"`, look for bearish patterns:
```python
if direction == "Bearish":
    found, pattern = _detect_candle_bearish(bars)  # or pass direction to _detect_candle
```

### `score_stock()` wiring

Pass `direction` down to all rule functions that need it. The function signature `score_stock(symbol, direction, horizon, bars, ...)` already has `direction` — just pass it through.

---

## Tests (`backend/tests/test_bearish_scoring.py`)

```python
import pytest
from app.scoring.stock_scorer import score_stock

def _make_candles(n=60, trend="down") -> list[dict]:
    """Generate synthetic candle sequence."""
    import random
    random.seed(42)
    price = 100.0
    bars = []
    for i in range(n):
        if trend == "down":
            price *= (1 - random.uniform(0.001, 0.008))  # steady downtrend
        else:
            price *= (1 + random.uniform(0.001, 0.008))  # steady uptrend
        o = price * (1 + random.uniform(-0.002, 0.002))
        c = price
        h = max(o, c) * (1 + random.uniform(0, 0.005))
        l = min(o, c) * (1 - random.uniform(0, 0.005))
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1_000_000})
    return bars

def test_bearish_setup_scores_above_50():
    """Clean downtrend with fast_ema < slow_ema should score > 50 for Bearish direction."""
    bars = _make_candles(60, trend="down")
    card = score_stock("TEST", "Bearish", "Swing", bars)
    assert card.score > 30, f"Expected score > 30 for bearish setup, got {card.score}"
    assert card.direction == "Bearish"

def test_bullish_candles_score_lower_as_bearish():
    """Uptrend candles should score lower when evaluated as Bearish."""
    uptrend = _make_candles(60, trend="up")
    downtrend = _make_candles(60, trend="down")
    card_up = score_stock("TEST", "Bearish", "Swing", uptrend)
    card_down = score_stock("TEST", "Bearish", "Swing", downtrend)
    assert card_down.score > card_up.score, (
        f"Downtrend ({card_down.score}) should score higher than uptrend ({card_up.score}) for Bearish"
    )

def test_bullish_scan_unaffected():
    """Existing bullish scoring still works correctly."""
    bars = _make_candles(60, trend="up")
    card = score_stock("TEST", "Bullish", "Swing", bars)
    assert card.direction == "Bullish"
    assert card.score >= 0

def test_direction_tag_propagates():
    """Score card must carry the direction tag."""
    bars = _make_candles(60, trend="down")
    card = score_stock("TEST", "Bearish", "Swing", bars)
    assert card.direction == "Bearish"
```

Run: `cd backend && pytest tests/test_bearish_scoring.py -v` — all pass.

Also run the full suite to check for regressions:
`cd backend && pytest -x --tb=short` — no regressions.

---

## Acceptance Criteria

- [ ] A clean bearish downtrend (fast_ema < slow_ema) produces `direction == "Bearish"` in the returned card
- [ ] Same candles scored as "Bullish" produce a different result than "Bearish"
- [ ] All existing bullish tests still pass (no regressions)
- [ ] `pytest tests/test_bearish_scoring.py` — all pass
- [ ] `pytest` full suite — pass
- [ ] No files outside the Owned Files table were modified

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-36 (Bearish Direction Scoring) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-36-bearish-scoring (already created — checkout before starting)
Base: main (WS-33 merged)

Read the full context doc before writing any code:
F:\Git\GitHub\Trading assistant\llm-contexts\03-ws36-bearish.md

Key file to read fully before modifying:
- backend/app/scoring/stock_scorer.py  (understand all rule functions before touching anything)

Tasks in order:
1. Read stock_scorer.py fully
2. Add direction parameter to _rule_trend(), _rule_pullback(), _rule_trigger(), _detect_candle()
3. Implement bearish EMA check (fast < slow) in _rule_trend()
4. Implement bearish pullback check (bounce toward resistance) in _rule_pullback()
5. Add shooting_star, bearish_engulfing, evening_star to _detect_candle()
6. Add bearish trigger check in _rule_trigger()
7. Write test_bearish_scoring.py
8. Run: cd backend && pytest tests/test_bearish_scoring.py -v  (must pass)
9. Run: cd backend && pytest -x --tb=short  (no regressions)

Return: one-paragraph summary of changes and full pytest output.
```
