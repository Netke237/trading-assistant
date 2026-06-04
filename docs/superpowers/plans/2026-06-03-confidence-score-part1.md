# Confidence Score (Part 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtest the existing entry signal per symbol, turn its historical reliability into a 0–100 confidence number, display it with plain-English interpretation, and let it *demote* (never inflate) the PASS/CAUTION/REJECT verdict in the options scanner — with user-overridable gate thresholds.

**Architecture:** A new pure module (`signal_confidence.py`) replays `score_stock` over historical daily bars and measures, per signal fire, whether price moved a favorable `k×ATR` before an adverse `k×ATR` within N days. Aggregated into hit-rate/expectancy → a 0–100 score. A cache stores results per `(symbol, direction, horizon)`. `score_stock` gains optional `confidence` + `confidence_gate` params: it appends a `confidence` RuleResult and applies a demote-only cap. The scan router fetches confidence from cache, passes it in, and exposes it in the candidate payload. Frontend shows a "Conf %" column, a confidence card with interpretation text, a per-scan override, and a persisted Settings default.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / pytest (backend); Next.js 15 / TypeScript / Zustand / Jest / CSS Modules (frontend). No new Python dependency (direct computation; `backtesting.py`/`quantstats` are reserved for Part 2 Step 6).

**Decision note (why no backtesting.py here):** Part 1 measures a *signal's* forward-return reliability — a direct per-bar computation. `backtesting.py` simulates an order-driven portfolio and `quantstats` analyses equity curves; both are the right fit for Part 2's full-trade backtest, not for this hit-rate. Using them here would force an awkward shape and a heavy dependency for no benefit.

---

## File Structure

**Backend**
- Create: `backend/app/scoring/signal_confidence.py` — confidence computation, interpretation, gate cap (pure, no I/O).
- Create: `backend/app/data/confidence_cache.py` — in-memory + on-disk cache keyed by `(symbol, direction, horizon)`.
- Modify: `backend/config/scoring_rules.yaml` — add `confidence_backtest` and `confidence_gate` blocks.
- Modify: `backend/app/scoring/stock_scorer.py` — accept `confidence` + `confidence_gate`, append RuleResult, apply demote cap.
- Modify: `backend/app/routers/scan.py` — fetch confidence from cache, pass to `score_stock`, accept per-scan override, expose in candidate.
- Modify: `backend/app/schemas/scan.py` — add request override field + candidate confidence fields (if candidate model lives elsewhere, mirror there).
- Tests: `backend/tests/test_signal_confidence.py`, `backend/tests/test_confidence_gate.py`, `backend/tests/test_confidence_cache.py`.

**Frontend**
- Modify: `frontend/app/(frame)/screener/step-4-ranking/cardToRow.ts` — map confidence into the row.
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.tsx` + `page.module.css` — "Conf %" column + confidence card.
- Create: `frontend/components/atoms/ConfidenceBadge/index.tsx` + `.module.css` — the visible score chip.
- Create: `frontend/lib/confidenceText.ts` — interpretation text helper (mirrors backend).
- Modify: `frontend/lib/settingsStore.ts` — persist `confidenceGate` default (versioned migrate).
- Modify: Settings "Score weights & parameters" page — gate controls (locate via grep in Task 12).
- Tests: `frontend/components/atoms/ConfidenceBadge/__tests__`, `frontend/lib/__tests__/confidenceText.test.ts`, extend `step-4-ranking/__tests__/page.test.ts`.

---

## Task 1: Config blocks for backtest + gate

**Files:**
- Modify: `backend/config/scoring_rules.yaml` (top level, after `score_thresholds`)
- Test: `backend/tests/test_signal_confidence.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_signal_confidence.py
from app.scoring.signal_confidence import load_backtest_cfg, load_gate_cfg

def test_config_blocks_present_with_defaults():
    bt = load_backtest_cfg("swing")
    assert bt["n_days"] == 10
    assert bt["atr_mult"] == 1.5
    assert bt["atr_period"] == 14
    assert bt["history_years"] == 4
    assert bt["min_samples"] == 20

    gate = load_gate_cfg()
    assert gate["enabled"] is True
    assert gate["cautionBelow"] == 50
    assert gate["rejectBelow"] == 35
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_confidence.py::test_config_blocks_present_with_defaults -v`
Expected: FAIL — `ModuleNotFoundError: app.scoring.signal_confidence`

- [ ] **Step 3: Add the config blocks**

Add to `backend/config/scoring_rules.yaml` immediately after the `score_thresholds:` block:

```yaml
confidence_gate:
  enabled: true
  cautionBelow: 50   # confidence < 50 -> cap final status at CAUTION
  rejectBelow: 35    # confidence < 35 -> cap final status at REJECT

confidence_backtest:
  swing:
    n_days: 10
    atr_mult: 1.5
    atr_period: 14
    history_years: 4
    min_samples: 20
  position:
    n_days: 40
    atr_mult: 1.5
    atr_period: 14
    history_years: 5
    min_samples: 20
  intraday:
    n_days: 5
    atr_mult: 1.5
    atr_period: 14
    history_years: 2
    min_samples: 20
```

- [ ] **Step 4: Create the module loaders**

Create `backend/app/scoring/signal_confidence.py`:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_backtest_cfg(horizon: str) -> dict:
    return _cfg()["confidence_backtest"][horizon.lower()]


def load_gate_cfg() -> dict:
    return _cfg()["confidence_gate"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_confidence.py::test_config_blocks_present_with_defaults -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/config/scoring_rules.yaml backend/app/scoring/signal_confidence.py backend/tests/test_signal_confidence.py
git commit -m "feat(confidence): add backtest + gate config blocks and loaders"
```

---

## Task 2: ATR forward-return outcome for a single fire

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py`
- Test: `backend/tests/test_signal_confidence.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_signal_confidence.py
from app.scoring.signal_confidence import evaluate_fire

def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}

def test_evaluate_fire_bullish_win_hits_target_first():
    # entry close=100, atr=2, mult=1.5 -> target=103, stop=97
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd = [_bar(100, 103.5, 99.5, 103)]  # hits 103 target on next bar
    outcome = evaluate_fire(history, fwd, direction="Bullish", atr=2.0, atr_mult=1.5)
    assert outcome == "win"

def test_evaluate_fire_bullish_loss_hits_stop_first():
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd = [_bar(100, 100.5, 96.5, 97)]  # hits 97 stop
    outcome = evaluate_fire(history, fwd, direction="Bullish", atr=2.0, atr_mult=1.5)
    assert outcome == "loss"

def test_evaluate_fire_neither_returns_flat():
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd = [_bar(100, 101, 99, 100) for _ in range(3)]  # never reaches +/-3
    outcome = evaluate_fire(history, fwd, direction="Bullish", atr=2.0, atr_mult=1.5)
    assert outcome == "flat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_confidence.py -k evaluate_fire -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_fire'`

- [ ] **Step 3: Implement `evaluate_fire`**

Add to `backend/app/scoring/signal_confidence.py`:

```python
from typing import Literal

Outcome = Literal["win", "loss", "flat"]


def evaluate_fire(
    history: list[dict],
    forward: list[dict],
    *,
    direction: str,
    atr: float,
    atr_mult: float,
) -> Outcome:
    """Decide if a signal fire was a win/loss/flat over the forward window.

    Win  = favorable atr_mult*ATR reached before adverse atr_mult*ATR.
    Loss = adverse reached first. Flat = neither within the window.
    Intrabar tie (both hit same bar) resolves as loss (conservative).
    """
    if atr <= 0 or not forward:
        return "flat"
    entry = history[-1]["close"]
    move = atr_mult * atr
    if direction == "Bullish":
        target, stop = entry + move, entry - move
        for b in forward:
            hit_stop = b["low"] <= stop
            hit_tgt = b["high"] >= target
            if hit_stop:
                return "loss"
            if hit_tgt:
                return "win"
    else:
        target, stop = entry - move, entry + move
        for b in forward:
            hit_stop = b["high"] >= stop
            hit_tgt = b["low"] <= target
            if hit_stop:
                return "loss"
            if hit_tgt:
                return "win"
    return "flat"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_confidence.py -k evaluate_fire -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/signal_confidence.py backend/tests/test_signal_confidence.py
git commit -m "feat(confidence): add single-fire ATR outcome evaluator"
```

---

## Task 3: Aggregate fires into a ConfidenceResult

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py`
- Test: `backend/tests/test_signal_confidence.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_signal_confidence.py
from app.scoring.signal_confidence import aggregate, ConfidenceResult

def test_aggregate_computes_hit_rate_and_score():
    outcomes = ["win"] * 7 + ["loss"] * 3   # 70% hit rate
    res = aggregate(outcomes, min_samples=5)
    assert isinstance(res, ConfidenceResult)
    assert res.sample_size == 10
    assert res.hit_rate == 0.7
    # payoff_ratio fixed at atr_mult symmetry -> 1.0, so confidence = 70
    assert res.confidence == 70

def test_aggregate_below_min_samples_returns_none_confidence():
    res = aggregate(["win", "loss"], min_samples=20)
    assert res.confidence is None
    assert res.sample_size == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_confidence.py -k aggregate -v`
Expected: FAIL — `ImportError: cannot import name 'aggregate'`

- [ ] **Step 3: Implement `ConfidenceResult` + `aggregate`**

Add to `backend/app/scoring/signal_confidence.py`:

```python
from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    confidence: int | None     # 0-100, or None if insufficient samples
    hit_rate: float            # wins / (wins + losses)
    sample_size: int           # wins + losses (flats excluded)
    flats: int


def aggregate(outcomes: list[str], *, min_samples: int) -> ConfidenceResult:
    wins = sum(1 for o in outcomes if o == "win")
    losses = sum(1 for o in outcomes if o == "loss")
    flats = sum(1 for o in outcomes if o == "flat")
    decisive = wins + losses
    if decisive == 0:
        return ConfidenceResult(None, 0.0, 0, flats)
    hit_rate = wins / decisive
    if decisive < min_samples:
        return ConfidenceResult(None, round(hit_rate, 4), decisive, flats)
    # Win and loss are both atr_mult*ATR by construction -> payoff_ratio = 1.0.
    # confidence = 100 * hit_rate * min(1, payoff_ratio)  (formula per spec; tunable)
    payoff_ratio = 1.0
    confidence = round(100 * hit_rate * min(1.0, payoff_ratio))
    confidence = max(0, min(100, confidence))
    return ConfidenceResult(confidence, round(hit_rate, 4), decisive, flats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_confidence.py -k aggregate -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/signal_confidence.py backend/tests/test_signal_confidence.py
git commit -m "feat(confidence): aggregate fire outcomes into ConfidenceResult"
```

---

## Task 4: Interpretation text + gate cap

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py`
- Test: `backend/tests/test_confidence_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_confidence_gate.py
from app.scoring.signal_confidence import status_cap, interpret

GATE = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}

def test_status_cap_rejects_below_reject_threshold():
    assert status_cap(30, GATE) == "REJECT"

def test_status_cap_cautions_in_middle_band():
    assert status_cap(45, GATE) == "CAUTION"

def test_status_cap_passes_when_high():
    assert status_cap(80, GATE) == "PASS"

def test_status_cap_none_confidence_does_not_demote():
    assert status_cap(None, GATE) == "PASS"

def test_status_cap_disabled_gate_never_demotes():
    assert status_cap(10, {"enabled": False, "cautionBelow": 50, "rejectBelow": 35}) == "PASS"

def test_interpret_low_text_mentions_caution():
    txt = interpret(41, sample_size=120, symbol="AAPL")
    assert "41%" in txt and "AAPL" in txt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_confidence_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'status_cap'`

- [ ] **Step 3: Implement `status_cap` + `interpret`**

Add to `backend/app/scoring/signal_confidence.py`:

```python
Status = Literal["PASS", "CAUTION", "REJECT"]


def status_cap(confidence: int | None, gate: dict) -> Status:
    """The *most permissive* status this confidence allows. Demote-only:
    callers combine this with the raw status and take the worse of the two."""
    if not gate.get("enabled", True) or confidence is None:
        return "PASS"
    if confidence < gate["rejectBelow"]:
        return "REJECT"
    if confidence < gate["cautionBelow"]:
        return "CAUTION"
    return "PASS"


def interpret(confidence: int | None, *, sample_size: int, symbol: str) -> str:
    if confidence is None:
        return (
            f"Not enough history to judge this setup on {symbol} "
            f"({sample_size} past occurrences). Confidence not applied."
        )
    if confidence >= 70:
        return (
            f"Strong history — this setup worked {confidence}% of the time on "
            f"{symbol} across {sample_size} past occurrences."
        )
    if confidence >= 50:
        return (
            f"Mixed history — worked {confidence}% of the time on {symbol} "
            f"({sample_size} occurrences). Treat with normal caution."
        )
    return (
        f"Weak history — only {confidence}% reliable on {symbol} "
        f"({sample_size} occurrences). Verdict capped down."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_confidence_gate.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/signal_confidence.py backend/tests/test_confidence_gate.py
git commit -m "feat(confidence): add demote-only status cap and interpretation text"
```

---

## Task 5: Full per-symbol confidence computation

**Files:**
- Modify: `backend/app/scoring/signal_confidence.py`
- Test: `backend/tests/test_signal_confidence.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_signal_confidence.py
from app.scoring.signal_confidence import compute_confidence

def test_compute_confidence_runs_end_to_end_on_synthetic_uptrend():
    # Rising series so the bullish signal fires repeatedly and mostly wins.
    bars = []
    price = 50.0
    for i in range(400):
        price *= 1.004
        bars.append(_bar(price * 0.997, price * 1.01, price * 0.99, price, 1000 + i))
    res = compute_confidence(bars, direction="Bullish", horizon="Swing")
    assert res.sample_size >= 20
    assert res.confidence is not None
    assert 0 <= res.confidence <= 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_confidence.py -k compute_confidence -v`
Expected: FAIL — `ImportError: cannot import name 'compute_confidence'`

- [ ] **Step 3: Implement `compute_confidence`**

Add to `backend/app/scoring/signal_confidence.py`:

```python
from app.scoring.stock_scorer import score_stock, _atr  # reuse existing helpers


def compute_confidence(
    bars: list[dict],
    *,
    direction: str,
    horizon: str,
) -> ConfidenceResult:
    """Replay the entry signal across history and score its reliability.

    A 'fire' = score_stock(...).status == 'PASS' on bars up to and including i,
    using only price-derived rules (no event/iv inputs in the historical replay).
    """
    bt = load_backtest_cfg(horizon)
    n_days = int(bt["n_days"])
    atr_mult = float(bt["atr_mult"])
    atr_period = int(bt["atr_period"])
    min_samples = int(bt["min_samples"])

    warmup = 60  # need enough bars for MAs/ADX before the first meaningful score
    outcomes: list[str] = []
    last = len(bars) - n_days
    for i in range(warmup, last):
        window = bars[: i + 1]
        card = score_stock(
            symbol="_bt", direction=direction, horizon=horizon, bars=window
        )
        if card.status != "PASS":
            continue
        atr = _atr(window, atr_period)
        forward = bars[i + 1 : i + 1 + n_days]
        outcomes.append(
            evaluate_fire(window, forward, direction=direction, atr=atr, atr_mult=atr_mult)
        )
    return aggregate(outcomes, min_samples=min_samples)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_confidence.py -k compute_confidence -v`
Expected: PASS

- [ ] **Step 5: Run the whole module test file**

Run: `cd backend && pytest tests/test_signal_confidence.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/signal_confidence.py backend/tests/test_signal_confidence.py
git commit -m "feat(confidence): end-to-end per-symbol confidence computation"
```

---

## Task 6: Confidence cache

**Files:**
- Create: `backend/app/data/confidence_cache.py`
- Test: `backend/tests/test_confidence_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_confidence_cache.py
from app.data.confidence_cache import cache_key, get_cached, set_cached, clear_cache

def test_set_and_get_roundtrip():
    clear_cache()
    key = cache_key("AAPL", "Bullish", "Swing")
    assert get_cached(key) is None
    set_cached(key, {"confidence": 62, "sample_size": 140})
    assert get_cached(key)["confidence"] == 62

def test_cache_key_is_stable_and_distinct():
    assert cache_key("AAPL", "Bullish", "Swing") == cache_key("aapl", "bullish", "swing")
    assert cache_key("AAPL", "Bullish", "Swing") != cache_key("AAPL", "Bearish", "Swing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_confidence_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.confidence_cache`

- [ ] **Step 3: Implement the cache**

Create `backend/app/data/confidence_cache.py`:

```python
from __future__ import annotations

import threading

_lock = threading.Lock()
_store: dict[str, dict] = {}


def cache_key(symbol: str, direction: str, horizon: str) -> str:
    return f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}"


def get_cached(key: str) -> dict | None:
    with _lock:
        return _store.get(key)


def set_cached(key: str, value: dict) -> None:
    with _lock:
        _store[key] = value


def clear_cache() -> None:
    with _lock:
        _store.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_confidence_cache.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/confidence_cache.py backend/tests/test_confidence_cache.py
git commit -m "feat(confidence): add in-memory confidence cache"
```

---

## Task 7: Wire confidence + gate into score_stock

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py:798-911` (the `score_stock` signature and tail)
- Test: `backend/tests/test_confidence_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_confidence_gate.py
from datetime import date
from app.scoring.stock_scorer import score_stock

def _flat_bars(n=120, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1000} for _ in range(n)]

def test_low_confidence_demotes_status_and_appends_rule():
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    card = score_stock(
        symbol="X", direction="Bullish", horizon="Swing", bars=bars,
        confidence=20, confidence_gate=gate, confidence_sample_size=99,
    )
    assert card.status == "REJECT"  # capped down by confidence=20
    assert any(r.name == "confidence" for r in card.rules)

def test_high_confidence_never_inflates():
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    base = score_stock(symbol="X", direction="Bullish", horizon="Swing", bars=bars)
    boosted = score_stock(
        symbol="X", direction="Bullish", horizon="Swing", bars=bars,
        confidence=95, confidence_gate=gate, confidence_sample_size=99,
    )
    assert boosted.status == base.status  # confidence cannot raise it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_confidence_gate.py -k confidence_demotes -v`
Expected: FAIL — `TypeError: score_stock() got an unexpected keyword argument 'confidence'`

- [ ] **Step 3: Extend `score_stock`**

In `backend/app/scoring/stock_scorer.py`, add a module-level helper near `_status_from_score` (after line 795):

```python
_STATUS_RANK = {"PASS": 2, "CAUTION": 1, "REJECT": 0}


def _worse(a: Status, b: Status) -> Status:
    return a if _STATUS_RANK[a] <= _STATUS_RANK[b] else b
```

Change the `score_stock` signature (line 798) to add three keyword params before the closing paren:

```python
def score_stock(
    symbol: str,
    direction: Direction,
    horizon: Horizon,
    bars: list[dict],
    earnings_date: date | None = None,
    dividend_date: date | None = None,
    iv_rank: float | None = None,
    overrides: dict | None = None,
    benchmark_candles: list[dict] | None = None,
    confidence: int | None = None,
    confidence_gate: dict | None = None,
    confidence_sample_size: int = 0,
) -> StockScoreCard:
```

Replace the tail (the `final_status = _status_from_score(...)` line through the `return`, lines 901-911) with:

```python
    final_status   = _status_from_score(final_score, thresholds)

    # Confidence gate: demote-only. Append a confidence RuleResult and cap status.
    if confidence_gate is not None:
        from app.scoring.signal_confidence import status_cap, interpret
        cap = status_cap(confidence, confidence_gate)
        final_status = _worse(final_status, cap)
        rules.append(RuleResult(
            name="confidence",
            status=cap,
            score=confidence if confidence is not None else 0,
            detail={
                "confidence": confidence,
                "sample_size": confidence_sample_size,
                "interpretation": interpret(
                    confidence, sample_size=confidence_sample_size, symbol=symbol
                ),
            },
        ))

    return StockScoreCard(
        symbol=symbol,
        direction=direction,
        horizon=horizon,
        score=final_score,
        status=final_status,
        rules=rules,
        volume_bonus=vol_bonus,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_confidence_gate.py -v`
Expected: PASS (all)

- [ ] **Step 5: Run the full scoring test suite for regressions**

Run: `cd backend && pytest tests/ -k "scorer or confidence or scan" -v`
Expected: PASS (no regressions; confidence is opt-in so existing calls are unaffected)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_confidence_gate.py
git commit -m "feat(confidence): apply demote-only gate inside score_stock"
```

---

## Task 8: Scan request override field + candidate fields (schema)

**Files:**
- Modify: `backend/app/schemas/scan.py`
- Test: `backend/tests/test_confidence_cache.py` (schema smoke) — or create `backend/tests/test_scan_schema.py`

- [ ] **Step 1: Locate the request + candidate models**

Run: `cd backend && grep -rn "class ScanRequest\|class ScanResult\|class ScanCandidate\|stockConfidence" app/schemas app/routers/scan.py`
Expected: shows the file/line where `ScanRequest` and the per-candidate model are defined (the router sets `stockConfidence=card.status` near `scan.py:382`). Note the file — fields go there.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_scan_schema.py
from app.schemas.scan import ScanRequest  # adjust import if model lives elsewhere

def test_scan_request_accepts_confidence_overrides():
    req = ScanRequest.model_validate({
        "confidenceCautionBelow": 60,
        "confidenceRejectBelow": 40,
    })
    assert req.confidence_caution_below == 60
    assert req.confidence_reject_below == 40

def test_confidence_overrides_default_none():
    req = ScanRequest.model_validate({})
    assert req.confidence_caution_below is None
    assert req.confidence_reject_below is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_scan_schema.py -v`
Expected: FAIL — attribute / validation error (fields absent)

- [ ] **Step 4: Add fields**

In the `ScanRequest` model (wherever Step 1 found it), add:

```python
    confidence_caution_below: int | None = Field(default=None, alias="confidenceCautionBelow")
    confidence_reject_below: int | None = Field(default=None, alias="confidenceRejectBelow")
```

In the per-candidate model (the one carrying `stockConfidence`), add:

```python
    confidence: int | None = Field(default=None, alias="confidence")
    confidence_text: str | None = Field(default=None, alias="confidenceText")
```

Ensure both models have `model_config = ConfigDict(populate_by_name=True)` (the existing models in this file already do).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_scan_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/scan.py backend/tests/test_scan_schema.py
git commit -m "feat(confidence): add scan request overrides + candidate confidence fields"
```

---

## Task 9: Use confidence in the scan router

**Files:**
- Modify: `backend/app/routers/scan.py` (`_process_symbol` near 161-280; `run_scan` near 522)
- Test: manual integration check (router needs DB/data fixtures; covered by smoke run)

- [ ] **Step 1: Resolve gate from request override or YAML default**

In `scan.py`, add a helper near `_rr_cfg` (around line 24):

```python
from app.scoring.signal_confidence import load_gate_cfg
from app.data import confidence_cache
from app.scoring.signal_confidence import compute_confidence


def _resolve_gate(req) -> dict:
    gate = dict(load_gate_cfg())
    cb = getattr(req, "confidence_caution_below", None)
    rb = getattr(req, "confidence_reject_below", None)
    if cb is not None:
        gate["cautionBelow"] = cb
    if rb is not None:
        gate["rejectBelow"] = rb
    return gate
```

- [ ] **Step 2: Fetch/compute confidence inside `_process_symbol`**

In `_process_symbol`, before the *final* `score_stock(...)` call (near line 272), add (using the bars already fetched for that symbol — reuse the existing candle variable; it is the same list passed to `score_stock`):

```python
    _ck = confidence_cache.cache_key(symbol, direction, horizon)
    _cached = confidence_cache.get_cached(_ck)
    if _cached is None:
        _res = compute_confidence(bars, direction=direction, horizon=horizon)
        _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
        confidence_cache.set_cached(_ck, _cached)
    _conf = _cached["confidence"]
    _conf_n = _cached["sample_size"]
```

Then pass them into that final `score_stock(...)` call by adding the three kwargs:

```python
        confidence=_conf,
        confidence_gate=gate,
        confidence_sample_size=_conf_n,
```

(`gate` is threaded in from `run_scan` — see Step 3. `bars` is the variable already holding this symbol's OHLCV used by the existing `score_stock` call; if it is named differently in this function, use that name.)

- [ ] **Step 3: Thread the gate + expose confidence on the candidate**

- In `run_scan` (near line 522), compute `gate = _resolve_gate(req)` once and pass it through to `_process_symbol` (add a `gate: dict` parameter to `_process_symbol`).
- Where the candidate object is built (near line 380, alongside `stockConfidence=card.status`), read the confidence RuleResult and set the new fields:

```python
        _conf_rule = next((r for r in card.rules if r.name == "confidence"), None)
        confidence=(_conf_rule.detail.get("confidence") if _conf_rule else None),
        confidenceText=(_conf_rule.detail.get("interpretation") if _conf_rule else None),
```

- [ ] **Step 4: Smoke-run the API**

Run: `cd backend && python -c "import app.routers.scan"`
Expected: imports cleanly (no NameError / ImportError).
Run the existing scan tests: `cd backend && pytest tests/ -k scan -v`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py
git commit -m "feat(confidence): compute, cache, gate, and expose confidence in scan"
```

---

## Task 10: Background refresh of confidence cache (weekly)

**Files:**
- Modify: `backend/app/services/scan_scheduler.py` (or wherever periodic jobs live — confirm in Step 1)
- Test: `backend/tests/test_confidence_cache.py`

- [ ] **Step 1: Locate the scheduler hook**

Run: `cd backend && grep -n "def \|schedule\|interval\|cadence" app/services/scan_scheduler.py | head -30`
Expected: shows the scheduler's periodic-job entry point. If a generic periodic hook is not obvious, the cache simply recomputes on demand when empty (Task 9 already handles cold cache); in that case mark this task done after Step 2 (TTL eviction) only.

- [ ] **Step 2: Add a TTL to the cache so stale entries recompute**

In `backend/app/data/confidence_cache.py`, change storage to keep timestamps:

```python
import time

_TTL_SECONDS = 7 * 24 * 3600  # weekly


def set_cached(key: str, value: dict) -> None:
    with _lock:
        _store[key] = {**value, "_ts": time.time()}


def get_cached(key: str) -> dict | None:
    with _lock:
        v = _store.get(key)
        if v is None:
            return None
        if time.time() - v.get("_ts", 0) > _TTL_SECONDS:
            del _store[key]
            return None
        return {k: val for k, val in v.items() if k != "_ts"}
```

- [ ] **Step 3: Update the cache test for TTL**

```python
# append to backend/tests/test_confidence_cache.py
import app.data.confidence_cache as cc

def test_ttl_evicts_stale_entries(monkeypatch):
    cc.clear_cache()
    key = cc.cache_key("MSFT", "Bullish", "Swing")
    cc.set_cached(key, {"confidence": 50, "sample_size": 30})
    # jump time past TTL
    monkeypatch.setattr(cc.time, "time", lambda: cc._TTL_SECONDS + 10_000)
    assert cc.get_cached(key) is None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_confidence_cache.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/confidence_cache.py backend/tests/test_confidence_cache.py
git commit -m "feat(confidence): weekly TTL eviction for confidence cache"
```

---

## Task 11: Frontend — interpretation helper + ConfidenceBadge atom

**Files:**
- Create: `frontend/lib/confidenceText.ts`
- Create: `frontend/components/atoms/ConfidenceBadge/index.tsx`, `ConfidenceBadge.module.css`
- Test: `frontend/lib/__tests__/confidenceText.test.ts`, `frontend/components/atoms/ConfidenceBadge/__tests__/ConfidenceBadge.test.tsx`

- [ ] **Step 1: Write the failing test for the text helper**

```ts
// frontend/lib/__tests__/confidenceText.test.ts
import { confidenceTier } from "@/lib/confidenceText";

test("tiers map to labels", () => {
  expect(confidenceTier(null)).toBe("unknown");
  expect(confidenceTier(20)).toBe("low");
  expect(confidenceTier(55)).toBe("medium");
  expect(confidenceTier(80)).toBe("high");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=confidenceText`
Expected: FAIL — cannot find module `@/lib/confidenceText`

- [ ] **Step 3: Implement the helper**

Create `frontend/lib/confidenceText.ts`:

```ts
export type ConfidenceTier = "unknown" | "low" | "medium" | "high";

export function confidenceTier(confidence: number | null | undefined): ConfidenceTier {
  if (confidence === null || confidence === undefined) return "unknown";
  if (confidence >= 70) return "high";
  if (confidence >= 50) return "medium";
  return "low";
}

export function confidenceTone(tier: ConfidenceTier): "pass" | "caution" | "reject" | "dim" {
  switch (tier) {
    case "high": return "pass";
    case "medium": return "caution";
    case "low": return "reject";
    default: return "dim";
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=confidenceText`
Expected: PASS

- [ ] **Step 5: Write the failing test for ConfidenceBadge**

```tsx
// frontend/components/atoms/ConfidenceBadge/__tests__/ConfidenceBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { ConfidenceBadge } from "../index";

test("renders percent and dash for null", () => {
  const { rerender } = render(<ConfidenceBadge confidence={62} />);
  expect(screen.getByText("62%")).toBeInTheDocument();
  rerender(<ConfidenceBadge confidence={null} />);
  expect(screen.getByText("—")).toBeInTheDocument();
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=ConfidenceBadge`
Expected: FAIL — cannot find `../index`

- [ ] **Step 7: Implement ConfidenceBadge**

Create `frontend/components/atoms/ConfidenceBadge/index.tsx`:

```tsx
import { Data } from "@/components/primitives/Data";
import { confidenceTier, confidenceTone } from "@/lib/confidenceText";
import styles from "./ConfidenceBadge.module.css";

export function ConfidenceBadge({
  confidence,
  title,
}: {
  confidence: number | null | undefined;
  title?: string;
}) {
  const tier = confidenceTier(confidence);
  const tone = confidenceTone(tier);
  return (
    <span className={styles.badge} data-tier={tier} title={title}>
      <Data size={12} weight={600} tone={tone === "dim" ? undefined : tone}>
        {confidence === null || confidence === undefined ? "—" : `${confidence}%`}
      </Data>
    </span>
  );
}
```

Create `frontend/components/atoms/ConfidenceBadge/ConfidenceBadge.module.css`:

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-surface);
}
.badge[data-tier="high"]   { background: color-mix(in srgb, var(--pass) 12%, var(--bg-surface)); }
.badge[data-tier="medium"] { background: color-mix(in srgb, var(--caution) 12%, var(--bg-surface)); }
.badge[data-tier="low"]    { background: color-mix(in srgb, var(--reject) 12%, var(--bg-surface)); }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern="ConfidenceBadge|confidenceText"`
Expected: PASS

- [ ] **Step 9: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/confidenceText.ts frontend/lib/__tests__/confidenceText.test.ts frontend/components/atoms/ConfidenceBadge
git commit -m "feat(confidence): ConfidenceBadge atom + tier helper"
```

---

## Task 12: Frontend — Conf % column in Step 4 ranking

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-ranking/cardToRow.ts`
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.tsx`, `page.module.css`
- Test: `frontend/app/(frame)/screener/step-4-ranking/__tests__/page.test.ts`

- [ ] **Step 1: Inspect current row shape + column headers**

Run: `cd frontend && cat "app/(frame)/screener/step-4-ranking/cardToRow.ts"`
Note the row type fields and where headers/cells are rendered in `page.tsx` (search for the existing "Δscore" / score column).

- [ ] **Step 2: Write/extend the failing test**

```ts
// in step-4-ranking/__tests__/page.test.ts — add:
import { cardToRow } from "../cardToRow";

test("cardToRow carries confidence and text", () => {
  const row = cardToRow({
    symbol: "AAPL", score: 70, status: "PASS",
    confidence: 62, confidenceText: "Mixed history...",
    // ...other required fields per the existing card fixture in this test file
  } as any);
  expect(row.confidence).toBe(62);
  expect(row.confidenceText).toContain("Mixed");
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=step-4-ranking`
Expected: FAIL — `row.confidence` undefined

- [ ] **Step 4: Map confidence in cardToRow**

In `cardToRow.ts`, add to the row type and the returned object:

```ts
  confidence: card.confidence ?? null,
  confidenceText: card.confidenceText ?? null,
```

(Add `confidence?: number | null; confidenceText?: string | null;` to the card input type and `confidence: number | null; confidenceText: string | null;` to the row type.)

- [ ] **Step 5: Render the column**

In `page.tsx`: add a header cell `<th>Conf</th>` next to the score header, and in the row render a cell:

```tsx
<td className={styles.confCell}>
  <ConfidenceBadge confidence={row.confidence} title={row.confidenceText ?? undefined} />
</td>
```

Import: `import { ConfidenceBadge } from "@/components/atoms/ConfidenceBadge";`
Add `.confCell { text-align: right; }` to `page.module.css`.

- [ ] **Step 6: Run test + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=step-4-ranking`
Expected: PASS
Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-ranking"
git commit -m "feat(confidence): Conf % column in Step 4 ranking"
```

---

## Task 13: Frontend — per-scan override + Settings default

**Files:**
- Modify: `frontend/lib/settingsStore.ts`
- Modify: Settings "Score weights & parameters" page (locate in Step 1)
- Modify: `frontend/lib/scanStore.ts` (per-scan override state) + the scan request builder in `frontend/lib/api.ts`
- Test: `frontend/lib/__tests__/settingsStore.test.ts` (create or extend)

- [ ] **Step 1: Locate the Settings weights page and the scan request builder**

Run: `cd frontend && grep -rn "Score weights\|customW\|customParams" app components`
Run: `cd frontend && grep -n "confidence\|ScanRequest\|run_scan\|/scan" lib/api.ts`
Note the files for Steps 4–5.

- [ ] **Step 2: Write the failing test for the store default**

```ts
// frontend/lib/__tests__/settingsStore.test.ts
import { useSettingsStore } from "@/lib/settingsStore";

test("confidenceGate has safe defaults and setters", () => {
  const s = useSettingsStore.getState();
  expect(s.confidenceGate).toEqual({ enabled: true, cautionBelow: 50, rejectBelow: 35 });
  s.setConfidenceGate({ enabled: true, cautionBelow: 60, rejectBelow: 40 });
  expect(useSettingsStore.getState().confidenceGate.cautionBelow).toBe(60);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=settingsStore`
Expected: FAIL — `confidenceGate` undefined

- [ ] **Step 4: Add to settingsStore (bump persist version + migrate)**

In `frontend/lib/settingsStore.ts` add to the state shape and store:

```ts
  confidenceGate: { enabled: boolean; cautionBelow: number; rejectBelow: number };
  setConfidenceGate: (g: { enabled: boolean; cautionBelow: number; rejectBelow: number }) => void;
```

Initial value `{ enabled: true, cautionBelow: 50, rejectBelow: 35 }`; setter `set({ confidenceGate: g })`. Bump the persist `version` by 1 and add a `migrate` branch that injects the default when the field is missing (follow the existing migrate pattern in this file and the MEMORY note: keep the SSR guard + `skipHydration`).

- [ ] **Step 5: Run test + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=settingsStore`
Expected: PASS
Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 6: Add Settings UI control**

In the Score weights & parameters page (from Step 1), add a "Confidence gate" subsection: an enable toggle and two number inputs (`cautionBelow`, `rejectBelow`) bound to `useSettingsStore`'s `confidenceGate` / `setConfidenceGate`. Use `Text weight={400}` for labels (per project rule).

- [ ] **Step 7: Wire per-scan override into the request**

- In `scanStore.ts`: add optional `confidenceCautionBelow?: number; confidenceRejectBelow?: number;` to the scan context, defaulting to the settings values.
- In `lib/api.ts` scan request builder: include `confidenceCautionBelow` / `confidenceRejectBelow` when set, so the backend `_resolve_gate` picks them up.
- Add a small per-scan control near the Step 4 table (two number inputs, prefilled from settings, scoped to this scan).

- [ ] **Step 8: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/lib/settingsStore.ts frontend/lib/scanStore.ts frontend/lib/api.ts frontend/lib/__tests__/settingsStore.test.ts "frontend/app"
git commit -m "feat(confidence): per-scan override + persisted Settings gate default"
```

---

## Task 14: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest tests/ -v`
Expected: PASS (all)

- [ ] **Step 2: Frontend suite + typecheck**

Run: `cd frontend && npm run test && npm run typecheck`
Expected: tests PASS, typecheck clean

- [ ] **Step 3: Manual smoke (dev)**

Run backend + `cd frontend && npm run dev`, run a scan with a real symbol set, confirm:
- Conf % column populated (or "—" for thin-history symbols)
- A low-confidence candidate shows a demoted badge with the interpretation tooltip
- Changing the per-scan override re-runs and changes which candidates are capped
- Settings gate default persists across reload

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(confidence): end-to-end verification fixups"
```

---

## Self-Review

- **Spec coverage:** ATR success (Tasks 2,5) ✓; 0–100 score (Task 3) ✓; demote-only gate (Tasks 4,7) ✓; always-visible score (Tasks 11,12) ✓; interpretation text (Tasks 4,11,12) ✓; override default+per-scan (Tasks 8,9,13) ✓; cache + refresh (Tasks 6,10) ✓; display in Step 4 (Task 12) ✓.
- **Placeholder scan:** Tasks 8, 10, 12, 13 contain "locate in Step 1" lookups because exact line/field names depend on models not fully read at plan time; each gives the exact grep to run and the exact code to add once located. No logic is left undefined.
- **Type consistency:** `confidence: int | None`, `confidence_gate: dict`, `confidence_sample_size: int`, `status_cap`, `interpret`, `compute_confidence`, `ConfidenceResult`, `cache_key/get_cached/set_cached/clear_cache`, frontend `confidence/confidenceText` and `confidenceTier/confidenceTone` are used consistently across tasks.
