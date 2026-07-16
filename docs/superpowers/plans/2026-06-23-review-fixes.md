# Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement seven targeted fixes identified in the Bamendjou trading software review — FVG direction swap, IV hard reject, earnings thresholds, event weight for stock mode, entry-premium guard, regime alert + overnight gap detection, and UI label disambiguation.

**Architecture:** Each fix is self-contained to the backend scoring layer, execution safety layer, or frontend display layer. All backend changes are covered by pytest; frontend label changes are covered by Jest. Tasks are ordered from smallest blast-radius to largest.

**Tech Stack:** Python 3.11 / FastAPI / pytest-asyncio · Next.js 15 / TypeScript / Jest · YAML config

---

## File Map

| File | What changes |
|---|---|
| `backend/app/scoring/stock_scorer.py` | FVG direction swap; event weight zero + renormalize in stock mode; active event scoring in stock mode |
| `backend/config/scoring_rules.yaml` | Swing `event.reject_days` 7 → 21, `event.caution_days` 21 → 45 |
| `backend/config/contract_rules.yaml` | Add `hard_reject.max_iv_rank: 70` |
| `backend/app/scoring/contract_validator.py` | Read `max_iv_rank` and hard-reject in `_hard_reject_reasons` |
| `backend/app/services/auto_trader.py` | Guard in `arm()`: raise if `entry_premium <= 0` |
| `backend/config/risk_rules.yaml` | Add `auto_trade.gap_threshold_pct: 0.05` |
| `backend/app/services/regime_monitor.py` | Add "Consider closing positions" to alert; add `_check_overnight_gaps()` |
| `frontend/components/organisms/TradeCard/index.tsx` | Relabel "Stock confidence" → "Historical accuracy (3×ATR exit)" and "R:R ratio" → "Projected R/R (+8% stock move)" |
| `backend/tests/test_fvg.py` | New — FVG direction tests |
| `backend/tests/test_contract_validator.py` | New — IV rank hard reject tests |
| `backend/tests/test_stock_scorer_events.py` | New — event thresholds in options mode; stock mode shows event but weight-zero |
| `backend/tests/test_auto_trader.py` | Extend — zero entry_premium raises on arm |
| `backend/tests/test_regime_monitor.py` | Extend — alert message text; gap check broadcasts on stop breach |
| `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx` | Extend — UI label text assertions |

---

## Task 1 — FVG Direction Swap

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py:366-398`
- Create: `backend/tests/test_fvg.py`

Current code has the gap_low/gap_high variable assignments swapped between Bullish and Bearish branches. A standard bullish FVG is `prev_bar.high < next_bar.low` (upward gap: older bar's high below newer bar's low). The code currently has the reverse.

- [ ] **Step 1 — Write the failing tests**

Create `backend/tests/test_fvg.py`:

```python
"""Tests that _detect_fvg returns the correct gap direction."""
import pytest
from app.scoring.stock_scorer import _detect_fvg


def _make_bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 1_000_000}


def test_bullish_fvg_detected_when_upward_gap_present():
    """
    3-bar bullish FVG: prev_bar is lower, next_bar is higher — upward gap.
    prev_bar.high (101) < next_bar.low (103) → gap is (101, 103).
    Current price = 102 should be inside.
    """
    bars = [
        _make_bar(98, 101, 97, 100),   # prev_bar (oldest)
        _make_bar(100, 104, 99, 103),  # impulse candle (gap maker)
        _make_bar(103, 106, 103, 105), # next_bar (newest) — close becomes current_price
    ]
    # Override close of last bar so current_price is inside the gap (102)
    bars[-1] = _make_bar(103, 106, 103, 102)
    hit, gap_low, gap_high = _detect_fvg(bars, "Bullish")
    assert hit is True, "Should detect bullish FVG"
    assert gap_low == 101.0
    assert gap_high == 103.0


def test_bullish_fvg_not_detected_when_downward_gap():
    """Downward gap should NOT register as a bullish FVG."""
    bars = [
        _make_bar(105, 108, 104, 107),  # prev_bar (older, higher)
        _make_bar(102, 104, 100, 101),  # impulse down
        _make_bar(97, 100, 97, 99),     # next_bar (newer, lower) — close = current_price
    ]
    # current_price = 99; if gap is bearish the bullish check should miss it
    hit, _, _ = _detect_fvg(bars, "Bullish")
    assert hit is False


def test_bearish_fvg_detected_when_downward_gap_present():
    """
    3-bar bearish FVG: prev_bar is higher, next_bar is lower — downward gap.
    prev_bar.low (104) > next_bar.high (102) → gap is (102, 104).
    Current price = 103 should be inside.
    """
    bars = [
        _make_bar(106, 108, 104, 107),  # prev_bar (oldest)
        _make_bar(104, 105, 100, 101),  # impulse candle
        _make_bar(100, 102, 99, 103),   # next_bar (newest) — close = 103 (inside gap)
    ]
    hit, gap_low, gap_high = _detect_fvg(bars, "Bearish")
    assert hit is True, "Should detect bearish FVG"
    assert gap_low == 102.0
    assert gap_high == 104.0


def test_bearish_fvg_not_detected_when_upward_gap():
    """Upward gap should NOT register as a bearish FVG."""
    bars = [
        _make_bar(98, 101, 97, 100),
        _make_bar(101, 105, 100, 104),
        _make_bar(104, 107, 104, 106),
    ]
    hit, _, _ = _detect_fvg(bars, "Bearish")
    assert hit is False
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_fvg.py -v
```

Expected: at least `test_bullish_fvg_detected` and `test_bearish_fvg_detected` fail (or pass with wrong gap values) because the direction assignments are currently swapped.

- [ ] **Step 3 — Fix `_detect_fvg` in `stock_scorer.py`**

Replace lines 383-398 (the inner `if direction == "Bullish": / else:` block inside the `for` loop in `_detect_fvg`):

**Old:**
```python
        if direction == "Bullish":
            gap_low  = next_bar["high"]
            gap_high = prev_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
        else:  # Bearish
            gap_low  = prev_bar["high"]
            gap_high = next_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
```

**New:**
```python
        if direction == "Bullish":
            # Bullish FVG: upward gap — prev_bar.high < next_bar.low
            gap_low  = prev_bar["high"]
            gap_high = next_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
        else:  # Bearish
            # Bearish FVG: downward gap — prev_bar.low > next_bar.high
            gap_low  = next_bar["high"]
            gap_high = prev_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
```

Also update the docstring at the top of `_detect_fvg` (lines 367-378):

**Old:**
```
    Bullish FVG (for bullish direction):
        bar[i-1].low > bar[i+1].high  — unfilled gap above bar[i+1]
        gap = (bar[i+1].high, bar[i-1].low)

    Bearish FVG (for bearish direction):
        bar[i-1].high < bar[i+1].low  — unfilled gap below bar[i+1]
        gap = (bar[i-1].high, bar[i+1].low)
```

**New:**
```
    Bullish FVG (for bullish direction):
        bar[i-1].high < bar[i+1].low  — upward gap left by bullish impulse
        gap = (bar[i-1].high, bar[i+1].low)

    Bearish FVG (for bearish direction):
        bar[i-1].low > bar[i+1].high  — downward gap left by bearish impulse
        gap = (bar[i+1].high, bar[i-1].low)
```

- [ ] **Step 4 — Run tests to confirm they pass**

```bash
cd backend && pytest tests/test_fvg.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5 — Run full scorer suite to check for regressions**

```bash
cd backend && pytest tests/test_stock_scorer_stock_mode.py tests/test_fvg.py -v
```

Expected: all pass.

- [ ] **Step 6 — Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_fvg.py
git commit -m "fix(scorer): correct FVG direction — bullish gap is prev.high < next.low"
```

---

## Task 2 — IV Rank Hard Reject for Long Options

**Files:**
- Modify: `backend/config/contract_rules.yaml`
- Modify: `backend/app/scoring/contract_validator.py:48-85`
- Create: `backend/tests/test_contract_validator.py`

`contract_rules.yaml` currently has no `max_iv_rank` in `hard_reject`. We add it at 70 (configurable). `_hard_reject_reasons` in `contract_validator.py` reads it and rejects.

- [ ] **Step 1 — Write the failing test**

Create `backend/tests/test_contract_validator.py`:

```python
"""Tests for contract_validator — hard reject and soft rank."""
import pytest
from app.scoring.contract_validator import validate_contract


def _base_contract(**overrides):
    c = {
        "symbol": "AAPL",
        "strike": 185.0,
        "expiry": "2026-09-19",
        "is_call": True,
        "bid": 2.00,
        "ask": 2.10,
        "volume": 500,
        "open_interest": 2000,
        "delta": 0.45,
        "iv_rank": 30.0,
    }
    c.update(overrides)
    return c


def test_low_iv_rank_passes():
    card = validate_contract(_base_contract(iv_rank=30), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_iv_rank_at_threshold_passes():
    """IV rank exactly at the limit (70) should still pass."""
    card = validate_contract(_base_contract(iv_rank=70), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_iv_rank_above_threshold_hard_rejects():
    """IV rank > 70 must hard-reject — buying expensive premium is the worst options mistake."""
    card = validate_contract(_base_contract(iv_rank=71), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_rank_too_high" in card.reject_reasons


def test_iv_rank_very_high_hard_rejects():
    card = validate_contract(_base_contract(iv_rank=90), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_rank_too_high" in card.reject_reasons


def test_iv_rank_none_is_not_rejected():
    """Missing IV rank data must not hard-reject (data gap ≠ bad contract)."""
    card = validate_contract(_base_contract(iv_rank=None), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_override_raises_max_iv_rank():
    """Caller can override the threshold to 80 via overrides dict."""
    card = validate_contract(
        _base_contract(iv_rank=75),
        stock_score=70,
        overrides={"max_iv_rank": 80},
    )
    assert "iv_rank_too_high" not in card.reject_reasons
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_contract_validator.py -v
```

Expected: the `iv_rank_too_high` tests fail (no such reject reason exists yet).

- [ ] **Step 3 — Add `max_iv_rank` to `contract_rules.yaml`**

In `backend/config/contract_rules.yaml`, add one line to the `hard_reject` block:

**Old:**
```yaml
hard_reject:
  min_volume: 50
  min_open_interest: 200
  max_bid_ask_spread_pct: 0.20
  min_delta: 0.20
  max_delta: 0.85
  min_dte: 21
  max_dte: 90
  max_soft_fail_count: 3
```

**New:**
```yaml
hard_reject:
  min_volume: 50
  min_open_interest: 200
  max_bid_ask_spread_pct: 0.20
  min_delta: 0.20
  max_delta: 0.85
  min_dte: 21
  max_dte: 90
  max_iv_rank: 70            # long-premium strategy: never buy when IV rank > 70
  max_soft_fail_count: 3
```

- [ ] **Step 4 — Add IV rank check in `_hard_reject_reasons` and wire override**

In `backend/app/scoring/contract_validator.py`:

1. In `_hard_reject_reasons` (after the `dte` check, before the closing `return reasons`):

```python
    iv_rank = contract.get("iv_rank")
    max_iv = hr.get("max_iv_rank")
    if max_iv is not None and iv_rank is not None and iv_rank > max_iv:
        reasons.append("iv_rank_too_high")
```

2. In `validate_contract`, inside the `if ov:` override block, add:

```python
            elif key == "max_iv_rank":          hr["max_iv_rank"]              = float(val)
```

Full updated `_hard_reject_reasons` function (replace existing):

```python
def _hard_reject_reasons(contract: dict, cfg: dict) -> list[str]:
    """Return list of hard-reject reason strings. Empty = no hard reject."""
    hr = cfg["hard_reject"]
    reasons = []

    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    delta = abs(contract.get("delta") or 0)
    iv_rank = contract.get("iv_rank")

    expiry_str = contract.get("expiry", "")
    try:
        expiry_date = date.fromisoformat(expiry_str)
        dte = (expiry_date - date.today()).days
    except (ValueError, TypeError):
        dte = 0

    if volume < hr["min_volume"] and not (volume == 0 and oi >= hr["min_open_interest"]):
        reasons.append("volume_too_low")
    if oi < hr["min_open_interest"]:
        reasons.append("open_interest_too_low")
    if spread_pct > hr["max_bid_ask_spread_pct"]:
        reasons.append("spread_too_wide")
    if delta < hr["min_delta"]:
        reasons.append("delta_too_low_far_otm")
    if delta > hr["max_delta"]:
        reasons.append("delta_too_high_deep_itm")
    if dte < hr["min_dte"]:
        reasons.append("dte_too_short")
    if dte > hr["max_dte"]:
        reasons.append("dte_too_long")

    max_iv = hr.get("max_iv_rank")
    if max_iv is not None and iv_rank is not None and iv_rank > max_iv:
        reasons.append("iv_rank_too_high")

    return reasons
```

In `validate_contract`, extend the override block:

```python
    if ov:
        hr = cfg["hard_reject"]
        for key, val in ov.items():
            if key == "max_bid_ask_spread_pct": hr["max_bid_ask_spread_pct"] = float(val)
            elif key == "max_delta":            hr["max_delta"]              = float(val)
            elif key == "min_delta":            hr["min_delta"]              = float(val)
            elif key == "min_volume":           hr["min_volume"]             = int(val)
            elif key == "min_open_interest":    hr["min_open_interest"]      = int(val)
            elif key == "min_dte":              hr["min_dte"]                = int(val)
            elif key == "max_dte":              hr["max_dte"]                = int(val)
            elif key == "max_iv_rank":          hr["max_iv_rank"]            = float(val)
```

- [ ] **Step 5 — Run tests**

```bash
cd backend && pytest tests/test_contract_validator.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6 — Commit**

```bash
git add backend/config/contract_rules.yaml backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py
git commit -m "fix(contracts): hard-reject options with IV rank > 70 (configurable)"
```

---

## Task 3 — Earnings Thresholds + Event Handling Refactor

**Files:**
- Modify: `backend/config/scoring_rules.yaml` (swing event thresholds)
- Modify: `backend/app/scoring/stock_scorer.py` (`_rule_event`, `score_stock`)
- Create: `backend/tests/test_stock_scorer_events.py`

Two changes combined here because they both touch `_rule_event`:
1. Options mode: swing reject_days 7 → 21, caution_days 21 → 45.
2. Stock mode: apply event rules (no longer always PASS/90) but with weight = 0 so the score is unaffected, and detail carries an explanatory note.

- [ ] **Step 1 — Write the failing tests**

Create `backend/tests/test_stock_scorer_events.py`:

```python
"""Tests for event rule thresholds (options and stock modes)."""
import pytest
from datetime import date, timedelta
from app.scoring.stock_scorer import _rule_event


def test_options_earnings_within_21_days_is_reject():
    """Options: reject within 21 days — 7-day threshold was too tight."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=15),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "REJECT"


def test_options_earnings_22_days_away_is_caution():
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=22),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "CAUTION"


def test_options_earnings_beyond_45_days_is_pass():
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=50),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "PASS"


def test_stock_mode_earnings_close_is_caution_not_pass():
    """Stock mode must no longer auto-return PASS — event proximity is shown."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=5),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    # Status should NOT be PASS when earnings are imminent
    assert result.status != "PASS"
    assert result.detail.get("note") is not None


def test_stock_mode_no_event_is_pass():
    """Stock mode with no upcoming events should still PASS."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=None,
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    assert result.status == "PASS"


def test_stock_mode_note_in_detail():
    """The detail dict must include the 'note' key in stock mode."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=30),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    assert "note" in result.detail
    assert "weight" in result.detail["note"].lower() or "score" in result.detail["note"].lower()
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_stock_scorer_events.py -v
```

Expected: options threshold tests fail (config still has reject_days=7), stock mode test fails (still returns PASS/90).

- [ ] **Step 3 — Update `scoring_rules.yaml` swing event thresholds**

In `backend/config/scoring_rules.yaml`, update the `swing` horizon's `event` block:

**Old:**
```yaml
    event:
      reject_days: 7
      caution_days: 21
```

**New:**
```yaml
    event:
      reject_days: 21
      caution_days: 45
```

- [ ] **Step 4 — Update `_rule_event` in `stock_scorer.py`**

Replace the existing `_rule_event` function (lines 776-811):

```python
def _rule_event(
    earnings_date: date | None,
    dividend_date: date | None,
    cfg: dict,
    scoring_mode: str = "options",
) -> RuleResult:
    ec = cfg["event"]
    today = date.today()
    worst_days: int | None = None
    event_label = "none"

    for label, ev_date in [("earnings", earnings_date), ("dividend", dividend_date)]:
        if ev_date is None:
            continue
        days = (ev_date - today).days
        if days < 0:
            continue
        if worst_days is None or days < worst_days:
            worst_days = days
            event_label = label

    if worst_days is None:
        detail: dict = {"event": "none"}
        if scoring_mode == "stock":
            detail["note"] = "Event weight is zero — shown for context only, does not affect stock score."
        return RuleResult("event", "PASS", 90, detail)

    detail = {
        "event": event_label,
        "days_to_event": worst_days,
    }

    if scoring_mode == "stock":
        # Apply thresholds for display — but weight is zero so score is unaffected.
        detail["note"] = "Event weight is zero — shown for context only, does not affect stock score."
        if worst_days < ec["reject_days"]:
            return RuleResult("event", "REJECT", 5, detail)
        elif worst_days < ec["caution_days"]:
            return RuleResult("event", "CAUTION", 55, detail)
        return RuleResult("event", "PASS", 90, detail)

    # ── Options mode ──────────────────────────────────────────────────────────
    if worst_days < ec["reject_days"]:
        return RuleResult("event", "REJECT", 5, detail)
    elif worst_days < ec["caution_days"]:
        return RuleResult("event", "CAUTION", 55, detail)
    return RuleResult("event", "PASS", 90, detail)
```

- [ ] **Step 5 — Run tests**

```bash
cd backend && pytest tests/test_stock_scorer_events.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6 — Run full scorer suite for regressions**

```bash
cd backend && pytest tests/test_stock_scorer_stock_mode.py tests/test_fvg.py tests/test_stock_scorer_events.py -v
```

Expected: all pass.

- [ ] **Step 7 — Commit**

```bash
git add backend/config/scoring_rules.yaml backend/app/scoring/stock_scorer.py backend/tests/test_stock_scorer_events.py
git commit -m "fix(scorer): options earnings reject→21d; stock event active with weight=0"
```

---

## Task 4 — Event Weight = 0 for Stock Mode (Score Renormalization)

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py` (`score_stock` function, weights section)
- Extend: `backend/tests/test_stock_scorer_events.py`

When `scoring_mode == "stock"`, zero the event weight and renormalize remaining weights so the total is still 1.0 and scores stay in the 0–100 range.

- [ ] **Step 1 — Write the failing tests**

Add to `backend/tests/test_stock_scorer_events.py`:

```python
from datetime import date, timedelta
from app.scoring.stock_scorer import score_stock


def _bars_up(n=120):
    bars, price = [], 100.0
    for _ in range(n):
        price += 0.4
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 2_000_000})
    return bars


def test_event_weight_zero_in_stock_mode():
    """
    A candidate with upcoming earnings (5 days) should score differently in
    options vs stock mode because stock mode zeroes the event weight.
    The event rule result should be in the rules list but contribute 0.
    """
    bars = _bars_up()
    earnings = date.today() + timedelta(days=5)

    card_options = score_stock(
        "X", "Bullish", "Swing", bars,
        earnings_date=earnings,
        scoring_mode="options",
    )
    card_stock = score_stock(
        "X", "Bullish", "Swing", bars,
        earnings_date=earnings,
        scoring_mode="stock",
    )

    # Event rule exists in both
    ev_stock = next((r for r in card_stock.rules if r.name == "event"), None)
    assert ev_stock is not None

    # In stock mode, the event REJECT should not pull the final score down
    # because its weight is 0. Stock score must be >= options score when event
    # would otherwise trigger a REJECT in options mode.
    assert card_stock.score >= card_options.score


def test_stock_mode_score_in_range():
    """Renormalized weights must keep final score in [0, 100]."""
    bars = _bars_up()
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    assert 0 <= card.score <= 100
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_stock_scorer_events.py::test_event_weight_zero_in_stock_mode -v
```

Expected: FAIL — currently stock mode uses same weights as options, so earnings REJECT still suppresses the score.

- [ ] **Step 3 — Add weight renormalization in `score_stock`**

In `backend/app/scoring/stock_scorer.py`, inside `score_stock()`, after `weights = cfg["weights"]` (around line 1000), add:

```python
    weights = cfg["weights"]

    # Stock mode: event proximity is displayed but does not count toward score.
    # Zero the event weight and renormalize so other weights still sum to 1.0.
    if scoring_mode == "stock":
        weights = dict(weights)   # don't mutate the cached config
        weights["event"] = 0.0
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}
```

- [ ] **Step 4 — Run tests**

```bash
cd backend && pytest tests/test_stock_scorer_events.py -v
```

Expected: all tests PASS.

- [ ] **Step 5 — Regression check**

```bash
cd backend && pytest tests/ -v -k "scorer or fvg or contract"
```

Expected: all pass.

- [ ] **Step 6 — Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_stock_scorer_events.py
git commit -m "fix(scorer): zero event weight in stock mode and renormalize remaining weights"
```

---

## Task 5 — Entry Premium Guard in Auto Trader

**Files:**
- Modify: `backend/app/services/auto_trader.py:139-143` (`arm()` method)
- Extend: `backend/tests/test_auto_trader.py`

`arm()` currently accepts `entry_premium=0.0` silently. The downstream `fire()` then silently skips the exposure check with a warning log. Fix: raise `ValueError` in `arm()` if `entry_premium <= 0`.

- [ ] **Step 1 — Write the failing test**

Add to `backend/tests/test_auto_trader.py`:

```python
def test_arm_raises_if_entry_premium_is_zero():
    """arm() must refuse a zero entry_premium — exposure check would be silently bypassed."""
    import pytest
    svc = AutoTradeService()
    with pytest.raises(ValueError, match="entry_premium"):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol="AAPL260620C00185000",
            action="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=2.50,
            conid=None,
            entry_premium=0.0,   # <- the problem
        ))


def test_arm_raises_if_entry_premium_negative():
    import pytest
    svc = AutoTradeService()
    with pytest.raises(ValueError, match="entry_premium"):
        svc.arm(ArmedStrategy(
            broker="ibkr_paper",
            symbol="AAPL",
            option_symbol="AAPL260620C00185000",
            action="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=2.50,
            conid=None,
            entry_premium=-1.0,
        ))


def test_arm_succeeds_with_positive_entry_premium():
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper",
        symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
        entry_premium=2.50,
    ))
    assert svc.get_state().armed is True
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_auto_trader.py::test_arm_raises_if_entry_premium_is_zero -v
```

Expected: FAIL — currently `arm()` does not validate `entry_premium`.

- [ ] **Step 3 — Add guard in `arm()`**

In `backend/app/services/auto_trader.py`, replace the `arm` method:

```python
    def arm(self, strategy: ArmedStrategy) -> None:
        if strategy.entry_premium <= 0:
            raise ValueError(
                f"entry_premium must be > 0 before arming (got {strategy.entry_premium}). "
                "Set it from the contract's mid price so the exposure check can run."
            )
        with self._lock:
            self._state.armed = True
            self._state.strategy = strategy
        logger.info("AutoTrader armed: %s %s", strategy.action, strategy.symbol)
```

- [ ] **Step 4 — Run tests**

```bash
cd backend && pytest tests/test_auto_trader.py -v
```

Expected: all tests PASS.

- [ ] **Step 5 — Commit**

```bash
git add backend/app/services/auto_trader.py backend/tests/test_auto_trader.py
git commit -m "fix(auto-trader): refuse to arm when entry_premium is zero or negative"
```

---

## Task 6 — Regime Alert Message + Overnight Gap Detection

**Files:**
- Modify: `backend/config/risk_rules.yaml` (add `gap_threshold_pct`)
- Modify: `backend/app/services/regime_monitor.py`
- Extend: `backend/tests/test_regime_monitor.py`

Two changes:
1. Add "Consider closing positions before next session." to the existing REGIME_FLIP_WARNING payload.
2. Add `_check_overnight_gaps()`: at each tick, query open positions (symbol + direction + stop), fetch current stock price, and broadcast OVERNIGHT_GAP_RISK if stock price has crossed through the position's stop level.

- [ ] **Step 1 — Write the failing tests**

Add to `backend/tests/test_regime_monitor.py`:

```python
@pytest.mark.asyncio
async def test_regime_flip_alert_includes_close_advice(mocker):
    """The REGIME_FLIP_WARNING payload must tell the trader to consider closing."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=True),
    )
    mocker.patch(
        "app.services.regime_monitor._check_overnight_gaps",
        new=AsyncMock(),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    payload = broadcast_mock.call_args[0][0]
    assert "Consider closing" in payload["message"] or "closing" in payload.get("action", "")


@pytest.mark.asyncio
async def test_gap_check_broadcasts_when_stop_breached(mocker):
    """When a position's stop level is breached by current price, broadcast OVERNIGHT_GAP_RISK."""
    positions = [
        {"symbol": "AAPL", "direction": "Bullish", "stop": 180.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    from unittest.mock import MagicMock
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=175.0),  # below stop of 180
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_called_once()
    payload = broadcast_mock.call_args[0][0]
    assert payload["type"] == "OVERNIGHT_GAP_RISK"
    assert payload["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_gap_check_no_alert_when_stop_not_breached(mocker):
    """No alert when price is above stop for a bullish position."""
    positions = [
        {"symbol": "NVDA", "direction": "Bullish", "stop": 100.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=120.0),  # above stop — safe
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_not_called()


@pytest.mark.asyncio
async def test_gap_check_bearish_stop_breached(mocker):
    """For bearish positions, a stop breach means price went ABOVE the stop level."""
    positions = [
        {"symbol": "SPY", "direction": "Bearish", "stop": 450.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=460.0),  # above bearish stop
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_called_once()
    assert broadcast_mock.call_args[0][0]["type"] == "OVERNIGHT_GAP_RISK"


@pytest.mark.asyncio
async def test_gap_check_skips_position_with_no_stop(mocker):
    """Positions without a stop value must be skipped (can't check without a reference level)."""
    positions = [
        {"symbol": "MSFT", "direction": "Bullish", "stop": None},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_not_called()
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_regime_monitor.py -v
```

Expected: the new tests fail (`_check_overnight_gaps` and `_fetch_stock_price` and `_get_open_positions` don't exist yet; alert message doesn't include "Consider closing").

- [ ] **Step 3 — Add `gap_threshold_pct` to `risk_rules.yaml`**

In `backend/config/risk_rules.yaml`, inside the `auto_trade` block:

**Old:**
```yaml
auto_trade:
  max_arm_age_minutes: 30
  max_daily_loss_pct: 0.02
  premium_stop_pct: 0.60
  regime_monitor_interval_minutes: 15
```

**New:**
```yaml
auto_trade:
  max_arm_age_minutes: 30
  max_daily_loss_pct: 0.02
  premium_stop_pct: 0.60
  regime_monitor_interval_minutes: 15
  gap_threshold_pct: 0.05       # alert when position's stock crosses its stop level
```

- [ ] **Step 4 — Update `regime_monitor.py`**

Replace the full content of `backend/app/services/regime_monitor.py` with the following (adds `_get_open_positions`, `_fetch_stock_price`, `_check_overnight_gaps`; updates alert message; calls gap check from `_tick`):

```python
"""Lightweight regime-flip monitor.

Runs as an asyncio background task. Every N minutes:
  1. Checks overall market regime.
  2. If REJECT and open positions exist → broadcasts a WebSocket warning.
  3. Updates the module-level conviction cache (used by auto_trader vol sizing).
  4. Checks each open position for overnight stop-breach gaps.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

# ── Module-level conviction cache (read by auto_trader._apply_vol_sizing) ─────
_last_conviction: float | None = None


def get_last_conviction() -> float | None:
    """Return cached OMM conviction_pct (bullish frame). None = not yet computed."""
    return _last_conviction


def set_last_conviction(pct: float) -> None:
    global _last_conviction
    _last_conviction = float(pct)


# ── Internal helpers (thin wrappers so tests can mock them easily) ─────────────

async def _get_overall_regime() -> str:
    """Return 'PASS', 'CAUTION', 'REJECT', or 'PENDING'."""
    loop = asyncio.get_running_loop()
    from app.routers.regime import compute_overall_regime
    return await loop.run_in_executor(None, compute_overall_regime)


async def _has_open_positions() -> bool:
    """Return True if any open positions exist in the DB."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM portfolio_positions"))
            count = result.scalar()
            return (count or 0) > 0
    except Exception as exc:
        logger.debug("regime_monitor: position count failed: %s", exc)
        return False


async def _get_open_positions() -> list[dict]:
    """Return list of {symbol, direction, stop} for all open positions."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("SELECT symbol, direction, stop FROM portfolio_positions")
            )
            rows = result.fetchall()
            return [
                {"symbol": row[0], "direction": row[1], "stop": row[2]}
                for row in rows
            ]
    except Exception as exc:
        logger.debug("regime_monitor: get_open_positions failed: %s", exc)
        return []


async def _fetch_stock_price(symbol: str) -> float | None:
    """Fetch current stock price. Returns None on failure."""
    try:
        loop = asyncio.get_running_loop()
        from app.data.market import fetch_price
        price = await loop.run_in_executor(None, fetch_price, symbol)
        return float(price) if price else None
    except Exception as exc:
        logger.debug("regime_monitor: price fetch failed for %s: %s", symbol, exc)
        return None


async def _broadcast_alert(payload: dict) -> None:
    """Send a WebSocket alert via the alert_service broadcast mechanism."""
    try:
        from app.services.alert_service import alert_service
        await alert_service.broadcast(payload)
    except Exception as exc:
        logger.warning("regime_monitor: broadcast failed: %s", exc)


async def _update_conviction_cache() -> None:
    """Refresh the module-level conviction cache from the current OMM result."""
    try:
        loop = asyncio.get_running_loop()

        def _compute():
            from app.data.market import fetch_candles
            from app.services.regime_omm import compute_omm
            candles = fetch_candles("SPX", bars=600)
            if not candles:
                return None
            closes = [c["close"] for c in candles]
            result = compute_omm(closes, direction="Bullish")
            return result.conviction_pct if result else None

        pct = await loop.run_in_executor(None, _compute)
        if pct is not None:
            set_last_conviction(pct)
    except Exception as exc:
        logger.debug("regime_monitor: conviction cache update failed: %s", exc)


async def _check_overnight_gaps() -> None:
    """Broadcast OVERNIGHT_GAP_RISK for any position whose stock has crossed its stop level.

    Uses the `stop` column (a stock price level) as the reference point.
    Bullish: alert if current_price <= stop.
    Bearish: alert if current_price >= stop.
    Positions with stop=None are skipped.
    """
    positions = await _get_open_positions()
    if not positions:
        return

    seen_symbols: set[str] = set()
    for pos in positions:
        symbol = pos.get("symbol")
        direction = pos.get("direction", "Bullish")
        stop = pos.get("stop")

        if not symbol or stop is None:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)

        price = await _fetch_stock_price(symbol)
        if price is None:
            continue

        breached = (
            (direction == "Bullish" and price <= stop) or
            (direction == "Bearish" and price >= stop)
        )
        if not breached:
            continue

        payload = {
            "type": "OVERNIGHT_GAP_RISK",
            "symbol": symbol,
            "direction": direction,
            "current_price": price,
            "stop_level": stop,
            "message": (
                f"{symbol} has gapped through its stop level (stop={stop}, current={price}). "
                "Consider closing this position before the next session."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning(
            "regime_monitor: gap risk — %s current=%.2f stop=%.2f (%s)",
            symbol, price, stop, direction,
        )


# ── Tick ──────────────────────────────────────────────────────────────────────

async def _tick() -> None:
    """One monitoring cycle."""
    try:
        await _update_conviction_cache()
        await _check_overnight_gaps()

        regime = await _get_overall_regime()
        if regime != "REJECT":
            return

        has_pos = await _has_open_positions()
        if not has_pos:
            return

        payload = {
            "type": "REGIME_FLIP_WARNING",
            "regime": "REJECT",
            "message": (
                "Market regime has turned REJECT while positions are open. "
                "Consider closing positions before next session."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning("regime_monitor: REJECT regime with open positions — alert broadcast")

    except Exception as exc:
        logger.error("regime_monitor _tick failed: %s", exc)


# ── Long-running coroutine ─────────────────────────────────────────────────────

async def run_regime_monitor() -> None:
    """Asyncio coroutine: runs forever, ticking then sleeping."""
    while True:
        await _tick()
        try:
            loop = asyncio.get_running_loop()

            def _read_interval() -> int:
                with open(_RISK_CONFIG_PATH) as f:
                    cfg = yaml.safe_load(f)
                return int(cfg.get("auto_trade", {}).get("regime_monitor_interval_minutes", 15))

            interval = await loop.run_in_executor(None, _read_interval)
        except Exception:
            interval = 15
        await asyncio.sleep(interval * 60)
```

- [ ] **Step 5 — Update existing regime monitor tests to mock `_check_overnight_gaps`**

The three original tests in `test_regime_monitor.py` must mock `_check_overnight_gaps` so they don't try to hit the database. Add this patch to each existing test that calls `_tick()`:

```python
mocker.patch(
    "app.services.regime_monitor._check_overnight_gaps",
    new=AsyncMock(),
)
```

Apply this to `test_no_alert_when_regime_is_pass`, `test_alert_sent_when_regime_reject_with_positions`, and `test_no_alert_when_regime_reject_but_no_positions`.

- [ ] **Step 6 — Run tests**

```bash
cd backend && pytest tests/test_regime_monitor.py -v
```

Expected: all tests PASS.

- [ ] **Step 7 — Commit**

```bash
git add backend/config/risk_rules.yaml backend/app/services/regime_monitor.py backend/tests/test_regime_monitor.py
git commit -m "fix(monitor): 'Consider closing' in regime alert; overnight gap check vs stop level"
```

---

## Task 7 — UI Label Disambiguation (R/R and Confidence)

**Files:**
- Modify: `frontend/components/organisms/TradeCard/index.tsx:469-484`
- Extend: `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`

Two label changes in the Final Recommendation Scorecard section:
- `"Stock confidence"` → `"Historical accuracy (3×ATR exit)"`
- `"R:R ratio"` → `"Projected R/R (+8% stock move)"`

These are display-only changes — no logic, no prop changes.

- [ ] **Step 1 — Write the failing tests**

Read the existing test file first to find the right import and render pattern:

```bash
cat frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx | head -30
```

Then add to `frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx`:

```typescript
it('shows historical accuracy label for confidence row', () => {
  render(<TradeCard data={mockData} />);
  expect(screen.getByText('Historical accuracy (3×ATR exit)')).toBeInTheDocument();
  expect(screen.queryByText('Stock confidence')).not.toBeInTheDocument();
});

it('shows projected RR label with method note', () => {
  render(<TradeCard data={mockData} />);
  expect(screen.getByText('Projected R/R (+8% stock move)')).toBeInTheDocument();
  expect(screen.queryByText('R:R ratio')).not.toBeInTheDocument();
});
```

- [ ] **Step 2 — Run tests to confirm they fail**

```bash
cd frontend && npm run test -- --testPathPattern=TradeCard --verbose 2>&1 | tail -30
```

Expected: the two new assertions fail because the labels still read "Stock confidence" and "R:R ratio".

- [ ] **Step 3 — Update label text in `TradeCard/index.tsx`**

In `frontend/components/organisms/TradeCard/index.tsx`, replace the two label strings in the Final Recommendation Scorecard section (around lines 469 and 477):

**Old (line ~469):**
```tsx
              <Text size={12} tone="secondary">Stock confidence</Text>
```
**New:**
```tsx
              <Text size={12} tone="secondary">Historical accuracy (3×ATR exit)</Text>
```

**Old (line ~477):**
```tsx
              <Text size={12} tone="secondary">R:R ratio</Text>
```
**New:**
```tsx
              <Text size={12} tone="secondary">Projected R/R (+8% stock move)</Text>
```

- [ ] **Step 4 — Run tests**

```bash
cd frontend && npm run test -- --testPathPattern=TradeCard --verbose 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 5 — Typecheck**

```bash
cd frontend && npm run typecheck 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 6 — Commit**

```bash
git add frontend/components/organisms/TradeCard/index.tsx frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx
git commit -m "fix(ui): relabel confidence as 'Historical accuracy (3×ATR exit)' and R/R as 'Projected R/R (+8% stock move)'"
```

---

## Self-Review Checklist

**Spec coverage:**

| Requested fix | Task |
|---|---|
| Exposure check bypass (entry_premium guard) | Task 5 |
| "Consider closing positions" in regime alert | Task 6 |
| R/R vs confidence label disambiguation | Task 7 |
| PASS threshold/event weight to 0 for stock mode | Tasks 3 & 4 |
| Options earnings reject → 21 days | Task 3 |
| Consider earnings for stocks | Task 3 |
| FVG direction swap | Task 1 |
| Overnight gap detection | Task 6 |
| IV rank hard reject > 70 | Task 2 |

All 9 items covered. ✓

**Placeholder scan:** No TBD, TODO, or "similar to Task N" patterns. Every step has concrete code. ✓

**Type consistency:** `ArmedStrategy`, `RuleResult`, `_rule_event`, `_detect_fvg` — all function signatures and return types match across tasks. ✓

**Config reload note:** `contract_validator.py` uses `@lru_cache(maxsize=1)` on `_load_config`. The new `max_iv_rank` field will be read on first call and cached. No restart needed if config changes are deployed before the process starts. If changing at runtime, process restart is required (same as existing behavior for all other config values). ✓
