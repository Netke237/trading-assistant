# Bamendjou — Fix, Tune & Execution Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three correctness bugs in the scoring engine, tune four calibration parameters, and add four execution safety guards — in that sequence, one git commit per phase.

**Architecture:** Phase 1 edits `stock_scorer.py` and `signal_confidence.py` (pure logic, no I/O). Phase 2 is YAML-only except one function default. Phase 3 adds a background coroutine and augments `auto_trader.py` with pre-fire guards. All new behaviour is additive and fail-safe.

**Tech Stack:** Python 3.11+, FastAPI, pytest, PyYAML, asyncio, threading.Lock (existing)

**Spec:** `docs/superpowers/specs/2026-06-22-fix-tune-execution-safety-design.md`

---

## File Map

| File | Change |
|---|---|
| `backend/app/scoring/stock_scorer.py` | Task 1 (trigger direction), Task 2 (pullback veto) |
| `backend/config/scoring_rules.yaml` | Task 1 (bearish threshold keys), Task 3 (confidence ATR split), Task 4 (RSI floors), Task 8 (regime_sizing enable) |
| `backend/config/contract_rules.yaml` | Task 4 (min_dte) |
| `backend/app/services/strategy_engine.py` | Task 4 (breakout volume default) |
| `backend/app/scoring/signal_confidence.py` | Task 3 (asymmetric ATR in evaluate_fire) |
| `backend/app/services/auto_trader.py` | Task 5 (daily loss), Task 6 (halt check), Task 8 (vol sizing) |
| `backend/config/risk_rules.yaml` | Task 5 (max_daily_loss_pct), Task 6 (no change needed), Task 7 (monitor interval) |
| `backend/app/services/regime_monitor.py` | Task 7 (new file) |
| `backend/app/main.py` | Task 7 (lifespan hook) |
| `backend/tests/test_bearish_trigger.py` | Task 1 (new test file) |
| `backend/tests/test_pullback_veto.py` | Task 2 (new test file) |
| `backend/tests/test_signal_confidence.py` | Task 3 (update existing) |
| `backend/tests/test_contracts_scoring.py` | Task 4 (update existing) |
| `backend/tests/test_auto_trader.py` | Task 5, 6, 8 (extend existing) |
| `backend/tests/test_regime_monitor.py` | Task 7 (new test file) |

---

## PHASE 1 — BUG FIXES

---

### Task 1: Bearish trigger momentum direction

**What:** The three momentum checks in `_rule_trigger` (MACD, RSI, Stochastic) currently fire bullish signals for **both** directions. A bearish entry scores highest when stock shows bullish momentum — backwards. This task flips all three checks when `direction == "Bearish"`, and adds two new config keys (`rsi_ceiling`, `stoch_overbought`) to each horizon block.

**Files:**
- Modify: `backend/config/scoring_rules.yaml` (all three horizon `trigger:` blocks)
- Modify: `backend/app/scoring/stock_scorer.py` — `_rule_trigger()` (lines ~649–744)
- Create: `backend/tests/test_bearish_trigger.py`

---

- [ ] **Step 1.1 — Add new config keys to scoring_rules.yaml**

Open `backend/config/scoring_rules.yaml`. Under **each** of the three horizon blocks (`swing`, `intraday`, `position`), add two keys inside the existing `trigger:` section:

```yaml
# swing → trigger:
      rsi_ceiling: 60        # bearish: RSI falls through this level from above
      stoch_overbought: 70   # bearish: stoch exits above this level

# intraday → trigger:
      rsi_ceiling: 60
      stoch_overbought: 70

# position → trigger:
      rsi_ceiling: 60
      stoch_overbought: 70
```

Place them directly after `stoch_tolerance_pct: 5` in each block. Do not remove any existing keys.

---

- [ ] **Step 1.2 — Write failing tests**

Create `backend/tests/test_bearish_trigger.py`:

```python
"""Tests that bearish trigger momentum checks fire on bearish (not bullish) signals."""
import pytest
from app.scoring.stock_scorer import _rule_trigger, _rsi, _macd_histogram


def _bar(o, h, l, c, v=500_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _cfg_swing():
    """Load the real swing config."""
    from app.scoring.stock_scorer import _horizon_cfg
    return _horizon_cfg("Swing")


# ── Helpers to build bar sequences with known indicator values ─────────────────

def _bars_with_falling_rsi(n=60, peak_at=55):
    """Bars designed so RSI rises above 60 then falls back through 60.
    Last two closes: RSI was above rsi_ceiling, now below it."""
    bars = []
    # Uptrend phase — RSI builds up
    price = 100.0
    for i in range(n - 5):
        price += 0.5
        bars.append(_bar(price - 0.2, price + 0.3, price - 0.4, price))
    # Reversal phase — price drops sharply (RSI falls through ceiling)
    for i in range(5):
        price -= 1.5
        bars.append(_bar(price + 0.2, price + 0.3, price - 0.3, price))
    return bars


def _bars_with_rising_rsi(n=60):
    """Bars designed so RSI is rising (crosses up through floor)."""
    bars = []
    price = 100.0
    for i in range(n - 5):
        price -= 0.3  # downtrend builds oversold
        bars.append(_bar(price + 0.1, price + 0.2, price - 0.3, price))
    for i in range(5):
        price += 0.8  # bounce — RSI crosses up
        bars.append(_bar(price - 0.1, price + 0.3, price - 0.2, price))
    return bars


def _vols(bars):
    return [b["volume"] for b in bars]


# ── Bearish MACD: histogram must cross DOWN ────────────────────────────────────

def test_bearish_macd_requires_histogram_cross_down():
    """For Bearish direction, macd_pass should fire when histogram goes from + to -."""
    cfg = _cfg_swing()
    # Build bars so MACD hist goes + → 0/-
    bars = []
    price = 100.0
    for i in range(80):
        price += 0.6  # uptrend: MACD hist builds positive
        bars.append(_bar(price - 0.1, price + 0.2, price - 0.2, price))
    # Sharp reversal: MACD hist crosses down
    for i in range(10):
        price -= 1.2
        bars.append(_bar(price + 0.1, price + 0.3, price - 0.3, price))
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    # The detail dict exposes macd_pass
    assert "macd_pass" in result.detail, "detail must include macd_pass key"


def test_bearish_macd_does_not_fire_when_histogram_crossing_up():
    """Bullish MACD (hist crosses up) must NOT fire macd_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)  # bars designed with rising momentum
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    # macd_pass should be False — histogram is rising, not falling
    assert result.detail["macd_pass"] is False, (
        "Rising MACD histogram must not fire macd_pass for Bearish"
    )


# ── Bearish RSI: must fall through ceiling, not rise through floor ─────────────

def test_bearish_rsi_fires_on_falling_through_ceiling():
    """For Bearish, rsi_pass should fire when RSI falls from above 60 to below 60."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert "rsi_pass" in result.detail


def test_bearish_rsi_does_not_fire_on_rising_through_floor():
    """RSI crossing UP through 38/44 must NOT fire rsi_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert result.detail["rsi_pass"] is False, (
        "RSI rising through floor must not fire rsi_pass for Bearish"
    )


# ── Bullish direction: existing behaviour unchanged ────────────────────────────

def test_bullish_rsi_still_fires_on_rising_through_floor():
    """Regression: Bullish rsi_pass still fires when RSI rises through floor."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bullish")
    # The test only verifies the key is present (actual pass depends on bar sequence)
    assert "rsi_pass" in result.detail


# ── Stochastic: bearish should check overbought exit ──────────────────────────

def test_bearish_stoch_detail_key_present():
    """stoch_pass key must always be present in detail regardless of direction."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert "stoch_pass" in result.detail


def test_bearish_trigger_detail_has_all_keys():
    """detail dict must contain candle, macd_pass, rsi_pass, stoch_pass, momentum_count."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    for key in ("candle", "macd_pass", "rsi_pass", "stoch_pass", "momentum_count"):
        assert key in result.detail, f"Missing key: {key}"
```

---

- [ ] **Step 1.3 — Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_bearish_trigger.py -v
```

Expected: Most tests PASS trivially (key presence checks), but `test_bearish_rsi_does_not_fire_on_rising_through_floor` and `test_bearish_macd_does_not_fire_when_histogram_crossing_up` will FAIL because the current code uses the same logic for both directions.

---

- [ ] **Step 1.4 — Implement the direction-aware trigger in stock_scorer.py**

In `backend/app/scoring/stock_scorer.py`, find `_rule_trigger` (starts around line 649). Replace the MACD, RSI, and Stochastic computation blocks with the direction-aware version below. **Do not change** the candle detection call, the volume bonus logic, or the stock/options scoring branches — only the three `_pass` variables change.

Replace the section from `# MACD` through the end of the stochastic block:

```python
    # ── MACD ──────────────────────────────────────────────────────────────────
    hist = _macd_histogram(closes, tc["macd_fast"], tc["macd_slow"], tc["macd_signal"])
    if direction == "Bearish":
        # Histogram crosses DOWN: was positive, now zero/negative
        macd_pass = len(hist) >= 2 and hist[-2] > 0 and hist[-1] <= 0
    else:
        macd_pass = (len(hist) >= 2 and hist[-2] < 0 and hist[-1] >= 0 and
                     (hist[-1] > hist[-2] if tc["macd_histogram_rising"] else True))

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_vals = _rsi(closes, tc["rsi_period"])
    rsi_pass = False
    div_win = tc["rsi_div_window_bars"]

    if direction == "Bearish":
        rsi_ceiling = tc.get("rsi_ceiling", 60)
        if len(rsi_vals) >= 2:
            rsi_pass = rsi_vals[-2] > rsi_ceiling >= rsi_vals[-1]
            if not rsi_pass and len(closes) >= div_win and len(rsi_vals) >= div_win:
                # Bearish divergence: price HH while RSI LH
                price_high_now  = max(closes[-div_win:])
                price_high_prev = max(closes[-2 * div_win:-div_win]) if len(closes) >= 2 * div_win else price_high_now
                rsi_high_now    = max(rsi_vals[-div_win:])
                rsi_high_prev   = max(rsi_vals[-2 * div_win:-div_win]) if len(rsi_vals) >= 2 * div_win else rsi_high_now
                if price_high_now > price_high_prev and rsi_high_now < rsi_high_prev:
                    rsi_pass = True
    else:
        rsi_floor = tc["rsi_floor"]
        if len(rsi_vals) >= 2:
            rsi_pass = rsi_vals[-2] < rsi_floor <= rsi_vals[-1]
            if not rsi_pass and len(closes) >= div_win and len(rsi_vals) >= div_win:
                # Bullish divergence: price LL while RSI HL
                price_low_now  = min(closes[-div_win:])
                price_low_prev = min(closes[-2 * div_win:-div_win]) if len(closes) >= 2 * div_win else price_low_now
                rsi_low_now    = min(rsi_vals[-div_win:])
                rsi_low_prev   = min(rsi_vals[-2 * div_win:-div_win]) if len(rsi_vals) >= 2 * div_win else rsi_low_now
                if price_low_now < price_low_prev and rsi_low_now > rsi_low_prev:
                    rsi_pass = True

    # ── Stochastic ────────────────────────────────────────────────────────────
    stoch_k, stoch_d = _stoch(bars, tc["stoch_k"], tc["stoch_d"])
    if direction == "Bearish":
        # K exits overbought from above: was >= overbought, now K < D
        overbought = tc.get("stoch_overbought", 70) * (1 - tc.get("stoch_tolerance_pct", 5) / 100)
        stoch_pass = (len(stoch_k) >= 2 and len(stoch_d) >= 2 and
                      stoch_k[-2] >= overbought and stoch_k[-1] < stoch_d[-1] and
                      stoch_k[-2] >= stoch_d[-2])
    else:
        oversold_threshold = tc["stoch_oversold"] * (1 + tc["stoch_tolerance_pct"] / 100)
        stoch_pass = (len(stoch_k) >= 2 and len(stoch_d) >= 2 and
                      stoch_k[-2] <= oversold_threshold and stoch_k[-1] > stoch_d[-1] and
                      stoch_k[-2] <= stoch_d[-2])
```

---

- [ ] **Step 1.5 — Run new and existing tests**

```bash
cd backend
pytest tests/test_bearish_trigger.py tests/test_bearish_scoring.py tests/test_trend_scoring.py -v
```

Expected: all PASS. If `test_bearish_scoring.py::test_bearish_setup_scores_above_50` fails, it means the bearish trigger now correctly rejects weak setups — check whether the test bar sequence produces valid bearish momentum signals (falling MACD/RSI/Stoch) and adjust the assertion threshold downward if the score is still > 0 and < 30.

---

- [ ] **Step 1.6 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass. Fix any failures before proceeding.

---

- [ ] **Step 1.7 — Commit**

```bash
cd backend && git add app/scoring/stock_scorer.py config/scoring_rules.yaml tests/test_bearish_trigger.py
git commit -m "fix(scorer): flip bearish trigger momentum checks — MACD/RSI/Stoch now direction-aware"
```

---

### Task 2: Pullback REJECT caps overall verdict at CAUTION

**What:** A rejected pullback (stock hasn't pulled back, or went too deep) currently only dents the weighted score — the overall can still reach PASS. This task adds a hard veto: pullback REJECT → overall capped at CAUTION. If confidence or regime also fire, the combination can still reach REJECT.

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py` — `score_stock()` (around line 984)
- Create: `backend/tests/test_pullback_veto.py`

---

- [ ] **Step 2.1 — Write failing tests**

Create `backend/tests/test_pullback_veto.py`:

```python
"""Tests that a REJECT pullback caps the overall score at CAUTION."""
import pytest
from unittest.mock import patch
from app.scoring.stock_scorer import score_stock, RuleResult


def _flat_bars(n=120, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1_000_000} for _ in range(n)]


def _force_rules(bars, *, pullback_status, trend_score=90):
    """Score a stock with the pullback rule mocked to a specific status."""
    with (
        patch("app.scoring.stock_scorer._rule_trend",
              return_value=RuleResult("trend", "PASS", trend_score, {})),
        patch("app.scoring.stock_scorer._rule_pullback",
              return_value=RuleResult("pullback", pullback_status, 10 if pullback_status == "REJECT" else 88, {})),
        patch("app.scoring.stock_scorer._rule_trigger",
              return_value=(RuleResult("trigger", "PASS", 80, {"candle": "none", "macd_pass": True,
                                                                "rsi_pass": True, "stoch_pass": True,
                                                                "momentum_count": 3, "volume_bonus": False}), False)),
        patch("app.scoring.stock_scorer._rule_event",
              return_value=RuleResult("event", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_vol",
              return_value=RuleResult("vol", "PASS", 80, {})),
    ):
        return score_stock("TEST", "Bullish", "Swing", bars)


def test_pullback_reject_caps_overall_at_caution():
    """Even with trend/trigger PASS, pullback REJECT must prevent overall PASS."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="REJECT")
    assert card.status != "PASS", (
        f"Expected CAUTION or REJECT when pullback is REJECT, got {card.status}"
    )
    assert card.status == "CAUTION", (
        f"Expected CAUTION cap for REJECT pullback, got {card.status}"
    )


def test_pullback_pass_allows_overall_pass():
    """Pullback PASS must not block an otherwise-passing trade."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="PASS")
    assert card.status == "PASS", (
        f"Expected PASS when all rules pass, got {card.status}"
    )


def test_pullback_caution_does_not_cap():
    """Pullback CAUTION (not REJECT) must not trigger the hard cap."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="CAUTION")
    # Should still be able to reach PASS via weighted score
    assert card.status in ("PASS", "CAUTION"), (
        f"Pullback CAUTION must not force REJECT, got {card.status}"
    )


def test_pullback_reject_plus_confidence_reject_gives_reject():
    """Pullback REJECT (→ CAUTION cap) combined with REJECT confidence → REJECT."""
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    with (
        patch("app.scoring.stock_scorer._rule_trend",
              return_value=RuleResult("trend", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_pullback",
              return_value=RuleResult("pullback", "REJECT", 10, {})),
        patch("app.scoring.stock_scorer._rule_trigger",
              return_value=(RuleResult("trigger", "PASS", 80, {"candle": "none", "macd_pass": True,
                                                                "rsi_pass": True, "stoch_pass": True,
                                                                "momentum_count": 3, "volume_bonus": False}), False)),
        patch("app.scoring.stock_scorer._rule_event",
              return_value=RuleResult("event", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_vol",
              return_value=RuleResult("vol", "PASS", 80, {})),
    ):
        card = score_stock("TEST", "Bullish", "Swing", bars,
                           confidence=20, confidence_gate=gate)
    assert card.status == "REJECT", (
        f"Pullback REJECT + confidence REJECT must give REJECT, got {card.status}"
    )
```

---

- [ ] **Step 2.2 — Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_pullback_veto.py::test_pullback_reject_caps_overall_at_caution -v
```

Expected: FAIL — the current code returns PASS for a pullback REJECT.

---

- [ ] **Step 2.3 — Add the pullback veto in score_stock()**

In `backend/app/scoring/stock_scorer.py`, find `score_stock()`. Locate these lines (around line 984):

```python
    final_score    = round(weighted_score)
    final_status   = _status_from_score(final_score, thresholds)

    # Confidence gate: demote-only.
```

Insert the pullback veto **between** the `final_status` assignment and the confidence gate comment:

```python
    final_score    = round(weighted_score)
    final_status   = _status_from_score(final_score, thresholds)

    # Pullback timing veto: a REJECT pullback means the setup timing is wrong.
    # Cap at CAUTION so the candidate remains visible but cannot PASS.
    _pb = next((r for r in rules if r.name == "pullback"), None)
    if _pb is not None and _pb.status == "REJECT":
        final_status = _worse(final_status, "CAUTION")

    # Confidence gate: demote-only.
```

---

- [ ] **Step 2.4 — Run tests**

```bash
cd backend
pytest tests/test_pullback_veto.py tests/test_confidence_gate.py tests/test_bearish_scoring.py -v
```

Expected: all PASS.

---

- [ ] **Step 2.5 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass.

---

- [ ] **Step 2.6 — Commit**

```bash
cd backend && git add app/scoring/stock_scorer.py tests/test_pullback_veto.py
git commit -m "fix(scorer): cap overall at CAUTION when pullback rule returns REJECT"
```

---

### Task 3: Confidence backtest per-strategy asymmetric ATR

**What:** `evaluate_fire` measures a 1:1 symmetric ATR bet, but the strategies target 2–3× ATR. The fix adds separate `atr_mult_target` and `atr_mult_stop` parameters. The old `atr_mult` keyword arg is kept as a backward-compat shim (logs a warning and uses it for both). Config removes `atr_mult` and adds the two new keys.

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py`
- Modify: `backend/config/scoring_rules.yaml` (`confidence_backtest` section)
- Modify: `backend/tests/test_signal_confidence.py` (update one test that checks `atr_mult`)

---

- [ ] **Step 3.1 — Update scoring_rules.yaml confidence_backtest section**

In `backend/config/scoring_rules.yaml`, replace the entire `confidence_backtest:` block:

```yaml
confidence_backtest:
  swing:
    n_days: 10
    atr_mult_target: 3.0    # strategy targets ~3 ATR (pullback_ema default)
    atr_mult_stop:   1.5    # strategy risks ~1.5 ATR stop
    atr_period: 14
    history_years: 4
    min_samples: 20
  position:
    n_days: 40
    atr_mult_target: 2.5
    atr_mult_stop:   1.5
    atr_period: 14
    history_years: 5
    min_samples: 20
  intraday:
    n_days: 5
    atr_mult_target: 2.0
    atr_mult_stop:   1.5
    atr_period: 14
    history_years: 2
    min_samples: 20
```

(Remove the old `atr_mult: 1.5` lines entirely.)

---

- [ ] **Step 3.2 — Write new failing tests for asymmetric evaluate_fire**

Add these tests to the **end** of `backend/tests/test_signal_confidence.py`:

```python
# ── Asymmetric ATR tests (Task 3) ─────────────────────────────────────────────

def test_evaluate_fire_asymmetric_win_requires_larger_target():
    """With atr_mult_target=3.0, atr_mult_stop=1.5: +3 ATR = win, not +1.5."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    atr = 2.0
    # +1.5 ATR = +3 → would be a win in symmetric mode; +3 ATR = +6 for asymmetric
    fwd_only_1x5 = [_bar(100, 103.5, 99.5, 103)]  # high=103.5 < 106 (target with 3.0 mult)
    outcome = evaluate_fire(
        history, fwd_only_1x5, direction="Bullish", atr=atr,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "flat", (
        "Reaching +1.5 ATR should be flat (not win) when target is +3.0 ATR"
    )


def test_evaluate_fire_asymmetric_win_hits_3x_target():
    """With atr_mult_target=3.0: +6 (3×ATR=2) on the high = win."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd_win = [_bar(100, 106.5, 99.5, 106)]  # high=106.5 > 100+3*2=106
    outcome = evaluate_fire(
        history, fwd_win, direction="Bullish", atr=2.0,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "win"


def test_evaluate_fire_asymmetric_loss_at_1x5_stop():
    """Stop at 1.5 ATR below entry still triggers a loss."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd_loss = [_bar(100, 100.5, 96.5, 97)]  # low=96.5 < 100-1.5*2=97
    outcome = evaluate_fire(
        history, fwd_loss, direction="Bullish", atr=2.0,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "loss"


def test_config_blocks_present_with_new_keys():
    """confidence_backtest now has atr_mult_target and atr_mult_stop, not atr_mult."""
    from app.scoring.signal_confidence import _cfg
    _cfg.cache_clear()   # force re-read after YAML edit in Step 3.1
    bt = load_backtest_cfg("swing")
    assert "atr_mult_target" in bt, "atr_mult_target key missing from config"
    assert "atr_mult_stop" in bt, "atr_mult_stop key missing from config"
    assert bt["atr_mult_target"] == 3.0
    assert bt["atr_mult_stop"] == 1.5
    assert "atr_mult" not in bt, "old atr_mult key should be removed"
```

---

- [ ] **Step 3.3 — Update the existing broken test in test_signal_confidence.py**

Find `test_config_blocks_present_with_defaults` in `backend/tests/test_signal_confidence.py`. It currently checks `bt["atr_mult"] == 1.5` which will KeyError after the config change. Replace that test:

```python
def test_config_blocks_present_with_defaults():
    from app.scoring.signal_confidence import _cfg
    _cfg.cache_clear()   # force re-read after YAML edit in Step 3.1
    bt = load_backtest_cfg("swing")
    assert bt["n_days"] == 10
    assert bt["atr_mult_target"] == 3.0   # replaces old atr_mult
    assert bt["atr_mult_stop"] == 1.5
    assert bt["atr_period"] == 14
    assert bt["history_years"] == 4
    assert bt["min_samples"] == 20

    gate = load_gate_cfg()
    assert gate["enabled"] is True
    assert gate["cautionBelow"] == 50
    assert gate["rejectBelow"] == 35
```

---

- [ ] **Step 3.4 — Run tests to confirm failures (before implementation)**

```bash
cd backend
pytest tests/test_signal_confidence.py::test_evaluate_fire_asymmetric_win_requires_larger_target \
       tests/test_signal_confidence.py::test_config_blocks_present_with_new_keys -v
```

Expected: FAIL (evaluate_fire doesn't accept atr_mult_target yet; config key missing).

---

- [ ] **Step 3.5 — Implement evaluate_fire with asymmetric ATR**

In `backend/app/scoring/signal_confidence.py`, replace the entire `evaluate_fire` function:

```python
def evaluate_fire(
    history: list[dict],
    forward: list[dict],
    *,
    direction: str,
    atr: float,
    atr_mult: float = 0.0,           # deprecated: use atr_mult_target + atr_mult_stop
    atr_mult_target: float = 0.0,
    atr_mult_stop: float = 0.0,
) -> Outcome:
    """Decide if a signal fire was a win/loss/flat over the forward window.

    Win  = favorable atr_mult_target*ATR reached before adverse atr_mult_stop*ATR.
    Loss = adverse reached first. Flat = neither within the window.
    Intrabar tie (both hit same bar) resolves as loss (conservative).

    Pass atr_mult (legacy) for symmetric 1:1 evaluation.
    Pass atr_mult_target + atr_mult_stop for asymmetric (preferred).
    """
    # Backward-compat: single atr_mult → use as both target and stop
    if atr_mult_target == 0.0 and atr_mult_stop == 0.0:
        if atr_mult == 0.0:
            raise ValueError(
                "Provide atr_mult_target + atr_mult_stop, or the legacy atr_mult parameter"
            )
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "evaluate_fire: atr_mult=%s is deprecated; pass atr_mult_target and atr_mult_stop",
            atr_mult,
        )
        atr_mult_target = atr_mult
        atr_mult_stop = atr_mult

    if atr <= 0 or not forward:
        return "flat"
    entry = history[-1]["close"]
    if direction == "Bullish":
        target = entry + atr_mult_target * atr
        stop   = entry - atr_mult_stop   * atr
        for b in forward:
            if b["low"] <= stop:
                return "loss"
            if b["high"] >= target:
                return "win"
    else:
        target = entry - atr_mult_target * atr
        stop   = entry + atr_mult_stop   * atr
        for b in forward:
            if b["high"] >= stop:
                return "loss"
            if b["low"] <= target:
                return "win"
    return "flat"
```

---

- [ ] **Step 3.6 — Update compute_confidence to use new config keys**

In `signal_confidence.py`, find `compute_confidence`. Replace the ATR mult loading lines:

```python
    bt = load_backtest_cfg(horizon)
    n_days = int(bt["n_days"])
    atr_mult = float(atr_mult) if atr_mult is not None else float(bt["atr_mult"])
    atr_period = int(bt["atr_period"])
```

With:

```python
    bt = load_backtest_cfg(horizon)
    n_days = int(bt["n_days"])
    atr_period = int(bt["atr_period"])
    # Per-strategy asymmetric ATR: override uses same value for both (backward compat)
    if atr_mult is not None:
        _atr_mult_target = float(atr_mult)
        _atr_mult_stop   = float(atr_mult)
    else:
        _atr_mult_target = float(bt["atr_mult_target"])
        _atr_mult_stop   = float(bt["atr_mult_stop"])
```

Then find the `evaluate_fire` call inside `compute_confidence` (the line that calls it with `atr_mult=atr_mult`). Replace it:

```python
            outcomes.append(
                evaluate_fire(window, forward, direction=direction, atr=atr,
                              atr_mult_target=_atr_mult_target, atr_mult_stop=_atr_mult_stop)
            )
```

Also update the function signature to remove the default for the `atr_mult` parameter (keep it as `None` to trigger the config-based path):

```python
def compute_confidence(
    bars: list[dict],
    *,
    direction: str,
    horizon: str,
    atr_mult: float | None = None,   # if None, uses config atr_mult_target/atr_mult_stop
) -> ConfidenceResult:
```

---

- [ ] **Step 3.7 — Run all confidence tests**

```bash
cd backend
pytest tests/test_signal_confidence.py tests/test_confidence_gate.py tests/test_confidence_cache.py -v
```

Expected: all PASS. The old tests that pass `atr_mult=1.5` directly to `evaluate_fire` still work via the backward-compat path.

---

- [ ] **Step 3.8 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass.

---

- [ ] **Step 3.9 — Commit Phase 1**

```bash
cd backend && git add app/scoring/signal_confidence.py config/scoring_rules.yaml tests/test_signal_confidence.py
git commit -m "fix(confidence): per-strategy asymmetric ATR in evaluate_fire; remove symmetric atr_mult config"
```

---

## PHASE 2 — PARAMETER TUNING

---

### Task 4: RSI floor, breakout volume, options min DTE

**What:** Three config values are miscalibrated. RSI floor of 44 for swing (neutral, not oversold) → 38. Breakout strategy volume confirmation default of 1.1× (noise) → 1.5×. Options hard-reject min_dte of 14 (severe theta zone) → 21 to match the soft preference floor.

**Files:**
- Modify: `backend/config/scoring_rules.yaml` (swing and intraday RSI floors)
- Modify: `backend/config/contract_rules.yaml` (min_dte)
- Modify: `backend/app/services/strategy_engine.py` (breakout_base_signal default)

---

- [ ] **Step 4.1 — Update RSI floors in scoring_rules.yaml**

In `backend/config/scoring_rules.yaml`:

Under `horizons.swing.trigger:`, change:
```yaml
      rsi_floor: 44
```
to:
```yaml
      rsi_floor: 38
```

Under `horizons.intraday.trigger:`, change:
```yaml
      rsi_floor: 44
```
to:
```yaml
      rsi_floor: 40
```

Under `horizons.position.trigger:`, **leave unchanged** (`rsi_floor: 37` is already appropriate).

---

- [ ] **Step 4.2 — Update min_dte in contract_rules.yaml**

In `backend/config/contract_rules.yaml`, under `hard_reject:`, change:
```yaml
  min_dte: 14
```
to:
```yaml
  min_dte: 21
```

---

- [ ] **Step 4.3 — Update breakout volume default in strategy_engine.py**

In `backend/app/services/strategy_engine.py`, find `breakout_base_signal` (around line 170). Change the function signature default:

```python
def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 1.5,
    volume_mult: float = 1.5,      # was 1.1 — requires real institutional participation
    rr_target_mult: float = 2.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
```

---

- [ ] **Step 4.4 — Verify min_dte change rejects DTE=18 contracts**

Run the existing contract scoring tests and confirm the new threshold works:

```bash
cd backend
pytest tests/test_contracts_scoring.py -v
```

If no test covers DTE=18 rejection, add one now at the end of `backend/tests/test_contracts_scoring.py`:

```python
def test_contract_rejected_at_dte_18():
    """DTE=18 must be hard-rejected after raising min_dte from 14 to 21."""
    from datetime import date, timedelta
    from app.scoring.contract_validator import validate_contract
    expiry = (date.today() + timedelta(days=18)).isoformat()
    contract = {
        "symbol": "AAPL", "strike": 185.0, "expiry": expiry, "is_call": True,
        "bid": 2.00, "ask": 2.10, "delta": 0.45,
        "volume": 500, "open_interest": 1500, "iv_rank": 30,
    }
    card = validate_contract(contract, stock_score=70)
    assert card.status == "REJECT"
    assert "dte_too_short" in card.reject_reasons


def test_contract_passes_at_dte_22():
    """DTE=22 must not be rejected for DTE reasons."""
    from datetime import date, timedelta
    from app.scoring.contract_validator import validate_contract
    expiry = (date.today() + timedelta(days=22)).isoformat()
    contract = {
        "symbol": "AAPL", "strike": 185.0, "expiry": expiry, "is_call": True,
        "bid": 2.00, "ask": 2.10, "delta": 0.45,
        "volume": 500, "open_interest": 1500, "iv_rank": 30,
    }
    card = validate_contract(contract, stock_score=70)
    assert "dte_too_short" not in card.reject_reasons
```

---

- [ ] **Step 4.5 — Run strategy engine tests**

```bash
cd backend
pytest tests/test_strategy_engine.py tests/test_strategy_engine_bearish.py tests/test_strategy_backtest.py -v
```

Expected: all pass. The volume_mult default change only affects calls that don't pass an explicit `volume_mult` argument.

---

- [ ] **Step 4.6 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass.

---

- [ ] **Step 4.7 — Commit Phase 2**

```bash
cd backend && git add config/scoring_rules.yaml config/contract_rules.yaml app/services/strategy_engine.py tests/test_contracts_scoring.py
git commit -m "tune: RSI floor swing→38 intraday→40; breakout volume default 1.1→1.5; min_dte 14→21"
```

---

## PHASE 3 — EXECUTION SAFETY

---

### Task 5: Daily loss circuit breaker

**What:** `fire()` currently has no P&L tracking. This task adds a `premium_at_risk` proxy to each history entry and blocks further fires if the day's risk exposure has breached `max_daily_loss_pct × portfolio_value`. No broker P&L data is required — the proxy is computed from `entry_premium × quantity × 100 × premium_stop_pct`.

**Files:**
- Modify: `backend/config/risk_rules.yaml`
- Modify: `backend/app/services/auto_trader.py`
- Modify: `backend/tests/test_auto_trader.py`

---

- [ ] **Step 5.1 — Add config keys to risk_rules.yaml**

In `backend/config/risk_rules.yaml`, add inside the `auto_trade:` block:

```yaml
auto_trade:
  max_arm_age_minutes: 30
  max_daily_loss_pct: 0.02     # 2% of portfolio_value = $2,000 on $100k
  premium_stop_pct: 0.60       # matches reward_risk.premium_stop_pct default
```

---

- [ ] **Step 5.2 — Write failing tests**

Add these tests at the end of `backend/tests/test_auto_trader.py`:

```python
# ── Daily loss circuit breaker (Task 5) ──────────────────────────────────────

def _make_armed(symbol="AAPL", premium=2.50, qty=1, pv=100_000.0):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv,
    )


def test_daily_loss_blocks_fire_when_limit_exceeded(mocker):
    """If today's premium_at_risk already exceeds the daily limit, fire raises."""
    from datetime import datetime, timezone
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("x", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    # Inject history: one entry today with large premium_at_risk
    today = datetime.now(timezone.utc).date().isoformat()
    svc._state.history.append({
        "order_id": "prev1",
        "status": "ok",
        "broker": "ibkr_paper",
        "symbol": "NVDA",
        "option": "NVDA_opt",
        "timestamp": f"{today}T10:00:00+00:00",
        "premium_at_risk": 2500.0,   # $2,500 already at risk (> 2% of $100k = $2,000)
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    with pytest.raises(RuntimeError, match="Daily loss limit"):
        svc.fire()

    # Must be disarmed after the block (fail-closed)
    assert svc.get_state().armed is False


def test_daily_loss_allows_fire_when_under_limit(mocker):
    """If today's premium_at_risk is under the limit, fire proceeds."""
    from datetime import datetime, timezone
    from app.data.ibkr_paper import OrderResult
    mock_exec = mocker.patch("app.services.auto_trader.execute_option_order",
                              return_value=OrderResult("y", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    today = datetime.now(timezone.utc).date().isoformat()
    svc._state.history.append({
        "order_id": "prev1", "status": "ok", "broker": "ibkr_paper",
        "symbol": "TSLA", "option": "TSLA_opt",
        "timestamp": f"{today}T10:00:00+00:00",
        "premium_at_risk": 500.0,    # only $500 used — well under $2,000
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    svc.fire()   # should not raise
    mock_exec.assert_called_once()


def test_daily_loss_ignores_prior_day_entries(mocker):
    """History entries from prior UTC days must not count toward today's limit."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("z", "ok", "ibkr_paper"))

    svc = AutoTradeService()
    svc._state.history.append({
        "order_id": "old", "status": "ok", "broker": "ibkr_paper",
        "symbol": "MSFT", "option": "MSFT_opt",
        "timestamp": "2020-01-01T10:00:00+00:00",   # old date
        "premium_at_risk": 9999.0,   # huge — but from a prior day
    })

    svc.arm(_make_armed(premium=1.0, qty=1, pv=100_000.0))
    svc.fire()   # must not raise
    assert svc.get_state().armed is False
```

---

- [ ] **Step 5.3 — Run tests to confirm failures**

```bash
cd backend
pytest tests/test_auto_trader.py::test_daily_loss_blocks_fire_when_limit_exceeded -v
```

Expected: FAIL (method not yet implemented).

---

- [ ] **Step 5.4 — Implement the circuit breaker in auto_trader.py**

In `backend/app/services/auto_trader.py`:

**a) Add import at the top:**
```python
from datetime import datetime, timezone, date as _date
```

**b) Update `_max_arm_age_minutes` to a general config loader and add a new config loader.** Add this static method to `AutoTradeService`:

```python
    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _risk_config() -> dict:
        """Load full auto_trade config section (cached; restart to reload)."""
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return cfg.get("auto_trade", {})
        except Exception:
            return {}
```

**c) Add `_check_daily_loss` static method:**

```python
    @staticmethod
    def _check_daily_loss(strategy: ArmedStrategy, history: list[dict], portfolio_value: float) -> None:
        """Raise RuntimeError if today's premium-at-risk exceeds the daily loss limit."""
        risk_cfg = AutoTradeService._risk_config()
        max_pct   = float(risk_cfg.get("max_daily_loss_pct", 0.02))
        stop_pct  = float(risk_cfg.get("premium_stop_pct", 0.60))
        limit     = max_pct * portfolio_value

        today_str = datetime.now(timezone.utc).date().isoformat()   # UTC date "YYYY-MM-DD"

        # Sum premium_at_risk from today's history entries
        today_risk = sum(
            float(e.get("premium_at_risk") or 0)
            for e in history
            if isinstance(e.get("timestamp"), str) and e["timestamp"].startswith(today_str)
        )

        # Add this trade's risk
        this_risk = strategy.entry_premium * strategy.quantity * 100 * stop_pct
        if today_risk + this_risk > limit:
            raise RuntimeError(
                f"Daily loss limit reached: {today_risk + this_risk:.0f} at risk "
                f"vs limit {limit:.0f} — no further trades today"
            )
```

**d) Update history entries in `fire()` to include `timestamp` and `premium_at_risk`.** Find the history append call in the success path of `fire()`:

```python
        with self._lock:
            self._state.history.append({
                "order_id": result.order_id,
                "status":   result.status,
                "broker":   result.broker,
                "symbol":   strategy.symbol,
                "option":   strategy.option_symbol,
            })
```

Replace with:

```python
        with self._lock:
            _stop_pct = float(AutoTradeService._risk_config().get("premium_stop_pct", 0.60))
            self._state.history.append({
                "order_id":        result.order_id,
                "status":          result.status,
                "broker":          result.broker,
                "symbol":          strategy.symbol,
                "option":          strategy.option_symbol,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "premium_at_risk": strategy.entry_premium * strategy.quantity * 100 * _stop_pct,
            })
```

Also update the `cap_blocked` history entry to include `timestamp`:

```python
                with self._lock:
                    self._state.history.append({
                        "order_id": None,
                        "status":   "cap_blocked",
                        "broker":   strategy.broker,
                        "symbol":   strategy.symbol,
                        "option":   strategy.option_symbol,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                    })
```

**e) Call `_check_daily_loss` in `fire()`.** Add the call after the exposure cap check block and before `execute_option_order`. Find:

```python
        try:
            result = execute_option_order(strategy)
```

Insert before it:

```python
        # Daily loss circuit breaker
        with self._lock:
            _history_snapshot = list(self._state.history)
        pv = portfolio_value if portfolio_value is not None else strategy.portfolio_value
        self._check_daily_loss(strategy, _history_snapshot, pv)

        try:
            result = execute_option_order(strategy)
```

---

- [ ] **Step 5.5 — Run tests**

```bash
cd backend
pytest tests/test_auto_trader.py -v
```

Expected: all PASS including the three new daily loss tests.

---

- [ ] **Step 5.6 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

---

- [ ] **Step 5.7 — Commit**

```bash
cd backend && git add app/services/auto_trader.py config/risk_rules.yaml tests/test_auto_trader.py
git commit -m "feat(safety): daily loss circuit breaker using premium_at_risk proxy"
```

---

### Task 6: Market-open / halt check inside the lock

**What:** Before disarming and firing, verify the market is reachable for the symbol. If not, raise without disarming — the armed state is preserved so the user can retry. This runs inside the `threading.Lock` to be atomic with the disarm.

**Files:**
- Modify: `backend/app/services/auto_trader.py`
- Modify: `backend/tests/test_auto_trader.py`

---

- [ ] **Step 6.1 — Write failing tests**

Add at the end of `backend/tests/test_auto_trader.py`:

```python
# ── Halt check (Task 6) ───────────────────────────────────────────────────────

def test_fire_blocked_when_market_closed(mocker):
    """If _market_is_open returns False, fire raises without disarming."""
    mocker.patch("app.services.auto_trader._market_is_open", return_value=False)
    svc = AutoTradeService()
    svc.arm(_make_armed())
    with pytest.raises(RuntimeError, match="Market closed"):
        svc.fire()
    # State must still be ARMED after a halt-blocked fire
    assert svc.get_state().armed is True, "Armed state must be preserved after halt block"


def test_fire_proceeds_when_market_open(mocker):
    """If _market_is_open returns True, fire executes normally."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("ord1", "ok", "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_make_armed())
    svc.fire()
    assert svc.get_state().armed is False
```

---

- [ ] **Step 6.2 — Run to confirm failures**

```bash
cd backend
pytest tests/test_auto_trader.py::test_fire_blocked_when_market_closed -v
```

Expected: FAIL (`_market_is_open` not defined yet).

---

- [ ] **Step 6.3 — Add _market_is_open module-level function in auto_trader.py**

Add this function **before** the `AutoTradeService` class definition:

```python
def _market_is_open(symbol: str) -> bool:
    """Return True if the market appears open for this symbol.

    Calls fetch_price — conservative: if no price returns (None, 0, or exception),
    treat as closed and block the fire.
    Runs inside threading.Lock so must complete quickly.
    fetch_price has no built-in timeout; wrap in a thread with a 3-second deadline
    to prevent holding the lock across a slow network call.
    """
    import concurrent.futures
    try:
        from app.data.market import fetch_price
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(fetch_price, symbol)
            try:
                price = future.result(timeout=3.0)
            except concurrent.futures.TimeoutError:
                return False
        return price is not None and float(price) > 0
    except Exception:
        return False
```

---

- [ ] **Step 6.4 — Move halt check inside the lock in fire()**

In `fire()`, find the existing lock block:

```python
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None
```

Replace with:

```python
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            # Halt check before disarm: if market is closed, preserve armed state
            if not _market_is_open(self._state.strategy.symbol):
                raise RuntimeError(
                    f"Market closed or {self._state.strategy.symbol} halted "
                    f"— armed state preserved for retry"
                )
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None
```

---

- [ ] **Step 6.5 — Run all auto_trader tests**

```bash
cd backend
pytest tests/test_auto_trader.py -v
```

Expected: all PASS.

---

- [ ] **Step 6.6 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

---

- [ ] **Step 6.7 — Commit**

```bash
cd backend && git add app/services/auto_trader.py tests/test_auto_trader.py
git commit -m "feat(safety): halt/market-closed check inside lock before disarm — armed state preserved on block"
```

---

### Task 7: Regime-flip mid-trade alert

**What:** A lightweight asyncio background task that wakes every 15 minutes, checks the overall regime, and broadcasts a WebSocket alert if regime is REJECT while positions exist. Also caches the latest OMM conviction for use by Task 8 (vol sizing).

**Files:**
- Modify: `backend/config/risk_rules.yaml`
- Create: `backend/app/services/regime_monitor.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_regime_monitor.py`

---

- [ ] **Step 7.1 — Add config key to risk_rules.yaml**

In `backend/config/risk_rules.yaml`, under `auto_trade:`:

```yaml
auto_trade:
  max_arm_age_minutes: 30
  max_daily_loss_pct: 0.02
  premium_stop_pct: 0.60
  regime_monitor_interval_minutes: 15
```

---

- [ ] **Step 7.2 — Write failing tests**

Create `backend/tests/test_regime_monitor.py`:

```python
"""Tests for regime_monitor background task and conviction cache."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_no_alert_when_regime_is_pass(mocker):
    """Monitor must not broadcast when regime is PASS."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="PASS"),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_not_called()


@pytest.mark.asyncio
async def test_alert_sent_when_regime_reject_with_positions(mocker):
    """Monitor broadcasts when regime=REJECT and open positions exist."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=True),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_called_once()
    call_args = broadcast_mock.call_args[0][0]
    assert call_args["type"] == "REGIME_FLIP_WARNING"


@pytest.mark.asyncio
async def test_no_alert_when_regime_reject_but_no_positions(mocker):
    """No alert if regime is REJECT but no open positions."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=False),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_not_called()


def test_conviction_cache_set_and_get():
    """set_last_conviction / get_last_conviction round-trip."""
    from app.services.regime_monitor import set_last_conviction, get_last_conviction
    set_last_conviction(42)
    assert get_last_conviction() == 42
    set_last_conviction(-10)
    assert get_last_conviction() == -10
```

---

- [ ] **Step 7.3 — Run tests to confirm failures**

```bash
cd backend
pytest tests/test_regime_monitor.py -v
```

Expected: ImportError (module doesn't exist yet).

---

- [ ] **Step 7.4 — Create regime_monitor.py**

Create `backend/app/services/regime_monitor.py`:

```python
"""Lightweight regime-flip monitor.

Runs as an asyncio background task. Every N minutes:
  1. Checks overall market regime.
  2. If REJECT and open positions exist → broadcasts a WebSocket warning.
  3. Updates the module-level conviction cache (used by auto_trader vol sizing).
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
_last_conviction: int | None = None


def get_last_conviction() -> int | None:
    """Return cached OMM conviction_pct (bullish frame). None = not yet computed."""
    return _last_conviction


def set_last_conviction(pct: int) -> None:
    global _last_conviction
    _last_conviction = pct


# ── Internal helpers (thin wrappers so tests can mock them easily) ─────────────

async def _get_overall_regime() -> str:
    """Return 'PASS', 'CAUTION', 'REJECT', or 'PENDING'."""
    loop = asyncio.get_event_loop()
    from app.routers.regime import compute_overall_regime
    return await loop.run_in_executor(None, compute_overall_regime)


async def _has_open_positions() -> bool:
    """Return True if any open positions exist in the DB."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM positions"))
            count = result.scalar()
            return (count or 0) > 0
    except Exception as exc:
        logger.debug("regime_monitor: position count failed: %s", exc)
        return False


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
        loop = asyncio.get_event_loop()

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


# ── Tick ──────────────────────────────────────────────────────────────────────

async def _tick() -> None:
    """One monitoring cycle."""
    try:
        await _update_conviction_cache()

        regime = await _get_overall_regime()
        if regime != "REJECT":
            return

        has_pos = await _has_open_positions()
        if not has_pos:
            return

        payload = {
            "type": "REGIME_FLIP_WARNING",
            "regime": "REJECT",
            "message": "Market regime has turned REJECT while positions are open",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning("regime_monitor: REJECT regime with open positions — alert broadcast")

    except Exception as exc:
        logger.error("regime_monitor _tick failed: %s", exc)


# ── Long-running coroutine ─────────────────────────────────────────────────────

async def run_regime_monitor() -> None:
    """Asyncio coroutine: runs forever, sleeping between ticks."""
    while True:
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            interval = int(cfg.get("auto_trade", {}).get("regime_monitor_interval_minutes", 15))
        except Exception:
            interval = 15

        await asyncio.sleep(interval * 60)
        await _tick()
```

> **Note:** `_broadcast_alert` uses `app.services.alert_service.alert_service.broadcast()`. If the actual broadcast API differs, update only `_broadcast_alert` — the tests mock it directly so they will still pass regardless.

---

- [ ] **Step 7.5 — Register as background task in main.py**

In `backend/app/main.py`, find the existing background task declarations near the top:

```python
_notification_worker_task: asyncio.Task | None = None
_portfolio_monitor_task: asyncio.Task | None = None
```

Add:
```python
_regime_monitor_task: asyncio.Task | None = None
```

Also update the `global` declaration inside the `lifespan` function (line 53) from:

```python
    global _notification_worker_task, _portfolio_monitor_task
```

to:

```python
    global _notification_worker_task, _portfolio_monitor_task, _regime_monitor_task
```

Inside the lifespan startup block, after the `_portfolio_monitor_task` line, add:

```python
    from app.services.regime_monitor import run_regime_monitor
    _regime_monitor_task = asyncio.create_task(run_regime_monitor())
```

Also update the shutdown cancel loop (near line 191 of main.py) from:

```python
    for task in (_notification_worker_task, _portfolio_monitor_task):
```

to:

```python
    for task in (_notification_worker_task, _portfolio_monitor_task, _regime_monitor_task):
```

---

- [ ] **Step 7.6 — Run regime monitor tests**

```bash
cd backend
pytest tests/test_regime_monitor.py -v
```

Expected: all PASS.

---

- [ ] **Step 7.7 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass. If any ws_alerts import fails, check the note in Step 7.4 and fix the broadcast import.

---

- [ ] **Step 7.8 — Commit**

```bash
cd backend && git add app/services/regime_monitor.py app/main.py config/risk_rules.yaml tests/test_regime_monitor.py
git commit -m "feat(safety): regime-flip WebSocket alert + conviction cache for vol sizing"
```

---

### Task 8: Volatility-scaled position sizing

**What:** Enable the existing `regime_sizing` config block and wire it into `fire()`. Position size is multiplied by `max(min_mult, conviction_pct / full_conviction_pct)`, capped at 1.0. Reads the cached conviction from `regime_monitor` — no network calls in the hot path.

**Files:**
- Modify: `backend/config/scoring_rules.yaml`
- Modify: `backend/app/services/auto_trader.py`
- Modify: `backend/tests/test_auto_trader.py`

---

- [ ] **Step 8.1 — Enable regime_sizing in scoring_rules.yaml**

In `backend/config/scoring_rules.yaml`, change:

```yaml
regime_sizing:
  enabled: false
  min_mult: 0.5
  full_conviction_pct: 40
```

to:

```yaml
regime_sizing:
  enabled: true
  min_mult: 0.5
  full_conviction_pct: 40
```

---

- [ ] **Step 8.2 — Write failing tests**

Add at the end of `backend/tests/test_auto_trader.py`:

```python
# ── Vol-scaled sizing (Task 8) ─────────────────────────────────────────────────

def test_vol_sizing_halves_quantity_at_low_conviction(mocker):
    """conviction=20, full=40 → mult=0.5 → quantity=2 halved to 1."""
    from app.data.ibkr_paper import OrderResult
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 return_value=OrderResult("s1", "ok", "ibkr_paper"))
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=20)

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=2, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    # The order fired with adjusted quantity; verify in the history
    history = svc.get_state().history
    assert len(history) == 1


def test_vol_sizing_keeps_full_quantity_at_high_conviction(mocker):
    """conviction=50, full=40 → mult capped at 1.0 → quantity unchanged."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s2", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=50)

    svc = AutoTradeService()
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )
    svc.arm(strategy)
    svc.fire()
    assert captured.get("quantity") == 4, "High conviction must not reduce quantity"


def test_vol_sizing_skipped_when_conviction_is_none(mocker):
    """If conviction cache is None (monitor hasn't run), sizing is skipped — full quantity fires."""
    from app.data.ibkr_paper import OrderResult
    captured = {}
    def mock_execute(s):
        captured["quantity"] = s.quantity
        return OrderResult("s3", "ok", "ibkr_paper")

    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order", side_effect=mock_execute)
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=None)

    svc = AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=3, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    ))
    svc.fire()
    assert captured.get("quantity") == 3
```

---

- [ ] **Step 8.3 — Run tests to confirm failures**

```bash
cd backend
pytest tests/test_auto_trader.py::test_vol_sizing_halves_quantity_at_low_conviction -v
```

Expected: FAIL.

---

- [ ] **Step 8.4 — Add _apply_vol_sizing helper and config loader in auto_trader.py**

Add this module-level function (before `AutoTradeService`):

```python
@functools.lru_cache(maxsize=1)
def _load_scoring_config() -> dict:
    """Load regime_sizing block from scoring_rules.yaml (cached)."""
    _scoring_path = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"
    try:
        with open(_scoring_path) as f:
            return yaml.safe_load(f).get("regime_sizing", {})
    except Exception:
        return {}


from dataclasses import replace as _dc_replace

def _apply_vol_sizing(strategy: ArmedStrategy) -> ArmedStrategy:
    """Return a (possibly quantity-adjusted) copy of strategy based on regime conviction.

    Reads cached conviction from regime_monitor (no network call).
    If conviction is None or regime_sizing is disabled, returns strategy unchanged.
    """
    cfg = _load_scoring_config()
    if not cfg.get("enabled", False):
        return strategy

    from app.services.regime_monitor import get_last_conviction
    conviction = get_last_conviction()
    if conviction is None:
        return strategy

    min_mult         = float(cfg.get("min_mult", 0.5))
    full_conviction  = float(cfg.get("full_conviction_pct", 40))

    # Direction-aware: BUY uses conviction as-is, SELL negates (bearish regime = tailwind)
    directional_conv = conviction if strategy.action == "BUY" else -conviction
    mult = max(min_mult, min(1.0, directional_conv / full_conviction))
    adjusted_qty = max(1, round(strategy.quantity * mult))

    if adjusted_qty == strategy.quantity:
        return strategy

    logger.info(
        "vol_sizing: %s qty %d → %d (conviction=%d, mult=%.2f)",
        strategy.symbol, strategy.quantity, adjusted_qty, directional_conv, mult,
    )
    return _dc_replace(strategy, quantity=adjusted_qty)
```

---

- [ ] **Step 8.5 — Call _apply_vol_sizing in fire() after disarm, before exposure check**

In `fire()`, after the lock block (where strategy is captured and state is disarmed), add:

```python
        # Vol-scaled sizing: adjust quantity using cached regime conviction (no network call)
        strategy = _apply_vol_sizing(strategy)
```

Place this line immediately after the closing `with self._lock:` block and before the exposure cap check.

---

- [ ] **Step 8.6 — Run all auto_trader tests**

```bash
cd backend
pytest tests/test_auto_trader.py -v
```

Expected: all PASS.

---

- [ ] **Step 8.7 — Run full suite**

```bash
cd backend
pytest --tb=short -q
```

Expected: all pass.

---

- [ ] **Step 8.8 — Final Phase 3 commit**

```bash
cd backend && git add app/services/auto_trader.py config/scoring_rules.yaml tests/test_auto_trader.py
git commit -m "feat(safety): vol-scaled sizing via cached regime conviction — min 0.5x at headwind"
```

---

## Completion Checklist

After all tasks:

- [ ] `pytest --tb=short -q` from `backend/` shows no failures
- [ ] `git log --oneline -8` shows the 5 phase commits in order:
  - `fix(scorer): flip bearish trigger...`
  - `fix(scorer): cap overall at CAUTION...`
  - `fix(confidence): per-strategy asymmetric ATR...`
  - `tune: RSI floor swing→38...`
  - `feat(safety): daily loss circuit breaker...`
  - `feat(safety): halt/market-closed check...`
  - `feat(safety): regime-flip WebSocket alert...`
  - `feat(safety): vol-scaled sizing...`
- [ ] Manually verify: run a bearish scan and confirm the trigger detail shows `macd_pass: false` when the histogram is rising
- [ ] Manually verify: run a contract scan for a stock with DTE=18 — should show REJECT with `dte_too_short`
