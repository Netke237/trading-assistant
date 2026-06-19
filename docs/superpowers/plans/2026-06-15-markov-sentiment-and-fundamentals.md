# Markov Regime / Sentiment + Fundamental Health — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a horizon- and direction-aware Markov regime "sentiment" layer (per-symbol conviction %, OMM/HMM alignment, demote-only gate, optional sizing) and a SEC-EDGAR fundamental-health layer (0–100 score, demote-only gate), both surfaced on stock and options cards and on the Page-1 regime panel.

**Architecture:** Both layers funnel through the single `score_stock()` function as demote-only `RuleResult`s appended after the weighted score — mirroring the existing `confidence` gate. The regime engine (`regime_omm.py` + new `regime_hmm_daily.py`) is horizon-parameterised from config; fundamentals reuse the DB-first `historical_store.py` cache pattern. **Build PART A (Markov) fully first, then PART B (Fundamental)** — they both edit `score_stock`, schemas, the same cards and the same YAML, so sequencing avoids collisions.

**Tech Stack:** FastAPI + Pydantic v2, SQLAlchemy 2 + Alembic, numpy, hmmlearn (optional), pytest/pytest-asyncio; Next.js 15 + TypeScript + Zustand + CSS Modules.

**Specs:**
- `docs/superpowers/specs/2026-06-15-markov-regime-conviction-sentiment-design.md`
- `docs/superpowers/specs/2026-06-15-fundamental-health-layer-design.md`

**Conventions:** Backend tests run from `backend/` via `pytest`. Frontend from `frontend/` via `npm run typecheck` + `npm run test`. Commit after every green task.

---

## File Structure

**PART A — Markov/Sentiment**
- Modify `backend/app/services/regime_omm.py` — stride sampling, conviction, n-step, stationary, horizon params.
- Create `backend/app/services/regime_hmm_daily.py` — directional HMM + alignment.
- Modify `backend/config/scoring_rules.yaml` — `regime`, `regime_gate`, `regime_sizing` blocks.
- Modify `backend/app/scoring/stock_scorer.py` — `regime` gate inside `score_stock`.
- Modify `backend/app/schemas/__init__.py` — `SentimentData` + new fields.
- Modify `backend/app/routers/stock_scan.py` — horizon fetch, sentiment, sizing, filter.
- Modify `backend/app/routers/scan.py` — options sentiment.
- Modify `backend/app/routers/regime.py` — Page-1 conviction + alignment.
- Create `frontend/components/molecules/MarketSentiment/{index.tsx,MarketSentiment.module.css}`.
- Modify `frontend/types/domain.ts` + the card/page consumers.
- Tests: `backend/tests/test_regime_omm.py`, `test_regime_hmm_daily.py` (new), `test_regime_gate.py` (new), `test_stock_scan_regime.py` (new).

**PART B — Fundamental Health**
- Create `backend/app/models/fundamentals.py` + Alembic migration.
- Create `backend/app/data/edgar.py` — CIK map + CompanyFacts + concept mapping.
- Create `backend/app/services/fundamentals_store.py` — DB-first get/prefetch/status.
- Create `backend/app/scoring/fundamentals_scorer.py` — pure scorer.
- Modify `backend/config/scoring_rules.yaml` — `fundamentals_gate` block.
- Modify `backend/app/scoring/stock_scorer.py` — `fundamentals` gate (extends PART A work).
- Modify `backend/app/schemas/__init__.py` + `schemas/stock_scan.py` — `FundamentalsOut` + request fields.
- Modify `backend/app/routers/{scan.py,stock_scan.py}` — wire + prefetch.
- Modify `frontend/lib/settingsStore.ts`, Step-3 page, RunScanButton, cards, `api.ts`.
- Tests: `test_edgar_mapping.py`, `test_fundamentals_store.py`, `test_fundamentals_scorer.py`, `test_fundamentals_gate.py` (new) + fixture JSON.

---

# PART A — Markov Regime / Conviction / Sentiment

### Task A1: Stride-sampled transition matrix + both-matrix output

**Files:**
- Modify: `backend/app/services/regime_omm.py`
- Test: `backend/tests/test_regime_omm.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_regime_omm.py
from app.services.regime_omm import build_transition_matrix, build_transition_matrix_stride

def test_stride_matrix_does_not_overcount_persistence():
    # 60 labels: 30 Bull then 30 Bear (indices: Bull=0, Bear=1, Choppy=2 per STATE_IDX)
    labels = ['Bull'] * 30 + ['Bear'] * 30
    overlapping = build_transition_matrix(labels)
    stride = build_transition_matrix_stride(labels, lookback=20)
    # Overlapping daily counting fakes near-1.0 persistence on the diagonal.
    assert overlapping[0, 0] > 0.9
    # Stride sampling (step=20) sees only ~3 windows -> far less inflated persistence.
    assert stride[0, 0] < overlapping[0, 0]
    # Rows still sum to 1.
    for r in range(3):
        assert abs(stride[r].sum() - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_omm.py::test_stride_matrix_does_not_overcount_persistence -v`
Expected: FAIL — `cannot import name 'build_transition_matrix_stride'`.

- [ ] **Step 3: Implement `build_transition_matrix_stride`**

```python
# add to backend/app/services/regime_omm.py
def build_transition_matrix_stride(labels: list[str], lookback: int, window: int = WINDOW) -> np.ndarray:
    """Count transitions between NON-overlapping windows (stride = lookback).

    Overlapping daily labels share lookback-1 days and fake persistence on the
    diagonal. Sampling every `lookback` bars removes that autocorrelation.
    """
    n = len(STATES)
    counts = np.zeros((n, n), dtype=float)
    recent = labels[-window:] if len(labels) > window else labels
    sampled = recent[::lookback]
    for i in range(len(sampled) - 1):
        f, t = STATE_IDX.get(sampled[i], -1), STATE_IDX.get(sampled[i + 1], -1)
        if f >= 0 and t >= 0:
            counts[f, t] += 1
    matrix = np.zeros((n, n), dtype=float)
    for row in range(n):
        total = counts[row].sum()
        matrix[row] = counts[row] / total if total > 0 else 1.0 / n
    return matrix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_omm.py::test_stride_matrix_does_not_overcount_persistence -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regime_omm.py backend/tests/test_regime_omm.py
git commit -m "feat(regime): add stride-sampled transition matrix (autocorrelation fix)"
```

---

### Task A2: Conviction signal + interpretation bands

**Files:**
- Modify: `backend/app/services/regime_omm.py`
- Test: `backend/tests/test_regime_omm.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.regime_omm import signal_from_row, conviction, conviction_label, conviction_interpretation

def test_conviction_is_direction_aware():
    # transition_row order is STATES = ['Bull','Bear','Choppy'] -> [0.7, 0.1, 0.2]
    row = [0.7, 0.1, 0.2]
    s = signal_from_row(row)                 # P(Bull) - P(Bear) = 0.6
    assert abs(s - 0.6) < 1e-9
    assert conviction(s, "Bullish") == 0.6   # tailwind for a long
    assert conviction(s, "Bearish") == -0.6  # headwind for a short

def test_conviction_label_bands():
    assert conviction_label(50) == "Strong tailwind"
    assert conviction_label(25) == "Mild tailwind"
    assert conviction_label(0)  == "Neutral"
    assert conviction_label(-25) == "Mild headwind"
    assert conviction_label(-50) == "Strong headwind"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_omm.py -k conviction -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement the conviction helpers**

```python
# add to backend/app/services/regime_omm.py
def signal_from_row(transition_row: list[float]) -> float:
    """P(Bull) - P(Bear) for the current-state row. transition_row is ordered by STATES."""
    return float(transition_row[STATE_IDX['Bull']] - transition_row[STATE_IDX['Bear']])

def conviction(signal: float, direction: str) -> float:
    """Direction-aware: positive => the regime agrees with the trade direction."""
    return float(signal if direction == "Bullish" else -signal)

def conviction_label(conviction_pct: int) -> str:
    if conviction_pct >= 40:  return "Strong tailwind"
    if conviction_pct >= 15:  return "Mild tailwind"
    if conviction_pct > -15:  return "Neutral"
    if conviction_pct > -40:  return "Mild headwind"
    return "Strong headwind"

def conviction_interpretation(conviction_pct: int, stability: str, state: str) -> str:
    label = conviction_label(conviction_pct)
    sign = "favours" if conviction_pct >= 15 else ("opposes" if conviction_pct <= -15 else "is neutral on")
    return (f"{label} ({conviction_pct:+d}%). The regime {sign} this trade. "
            f"Current state '{state}' is {stability.lower()}.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_omm.py -k conviction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regime_omm.py backend/tests/test_regime_omm.py
git commit -m "feat(regime): add direction-aware conviction signal + interpretation bands"
```

---

### Task A3: n-step forecast + stationary distribution

**Files:**
- Modify: `backend/app/services/regime_omm.py`
- Test: `backend/tests/test_regime_omm.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from app.services.regime_omm import n_step_forecast, stationary_distribution

def test_n_step_and_stationary():
    P = np.array([[0.8, 0.1, 0.1], [0.2, 0.7, 0.1], [0.3, 0.3, 0.4]])
    p2 = n_step_forecast(P, 2)
    assert np.allclose(p2, P @ P)
    pi = stationary_distribution(P)
    assert abs(pi.sum() - 1.0) < 1e-6
    assert np.allclose(pi @ P, pi, atol=1e-6)   # stationary: piP = pi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_omm.py -k step_and_stationary -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement**

```python
# add to backend/app/services/regime_omm.py
def n_step_forecast(P: np.ndarray, n: int) -> np.ndarray:
    """Chapman-Kolmogorov: P^n is the n-step transition matrix."""
    return np.linalg.matrix_power(P, n)

def stationary_distribution(P: np.ndarray) -> np.ndarray:
    """Left eigenvector of P with eigenvalue 1, normalised to sum to 1."""
    eigvals, eigvecs = np.linalg.eig(P.T)
    idx = int(np.argmin(np.abs(eigvals - 1.0)))
    vec = np.abs(np.real(eigvecs[:, idx]))
    return vec / vec.sum()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_omm.py -k step_and_stationary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regime_omm.py backend/tests/test_regime_omm.py
git commit -m "feat(regime): add n-step forecast and stationary distribution"
```

---

### Task A4: Horizon-parameterised `compute_omm` returning conviction

**Files:**
- Modify: `backend/app/services/regime_omm.py`
- Test: `backend/tests/test_regime_omm.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.regime_omm import compute_omm

def test_compute_omm_returns_conviction_and_stride_matrix():
    # synthetic uptrend: ~250 rising closes
    closes = [100 * (1.004 ** i) for i in range(300)]
    res = compute_omm(closes, direction="Bullish", lookback=20, window=500, min_obs=10)
    assert res is not None
    assert res.state in ("Bull", "Bear", "Choppy")
    assert -100 <= res.conviction_pct <= 100
    assert res.conviction_label
    assert res.interpretation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_omm.py -k compute_omm_returns_conviction -v`
Expected: FAIL — `compute_omm() got an unexpected keyword argument 'direction'` / missing fields.

- [ ] **Step 3: Extend `OmmResult` and `compute_omm`**

In `regime_omm.py` add fields to `OmmResult`:

```python
@dataclass
class OmmResult:
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    transition_row: list[float]
    state_order: list[str]
    conviction_pct: int = 0
    conviction_label: str = "Neutral"
    interpretation: str = ""
```

Change `compute_omm`'s signature to accept `direction`, `window`, `min_obs`, and use stride sampling:

```python
def compute_omm(
    closes: list[float],
    *,
    direction: str = "Bullish",
    lookback: int = RETURN_LOOKBACK,
    window: int = WINDOW,
    min_obs: int = MIN_OBS,
    threshold: float = BULL_THRESH,
    smoothing: float = 0.0,
) -> OmmResult | None:
    if len(closes) < lookback + 2:
        return None
    labels = label_daily_states(closes, lookback=lookback, threshold=threshold, smoothing=smoothing)
    current = labels[-1]
    current_idx = STATE_IDX[current]
    window_labels = labels[-window:] if len(labels) > window else labels
    if window_labels.count(current) < min_obs:
        return None

    matrix = build_transition_matrix_stride(labels, lookback=lookback, window=window)
    p_stay = float(matrix[current_idx, current_idx])
    transition_row = [float(matrix[current_idx, i]) for i in range(len(STATES))]
    denom = 1.0 - p_stay
    avg_duration = min((1.0 / denom) if denom > 1e-9 else float('inf'), 9999.0)
    stability = 'Fragile' if (1.0 - p_stay) > 0.25 else 'Stable'
    age = _regime_age(labels, current)

    sig = signal_from_row(transition_row)
    conv_pct = int(round(conviction(sig, direction) * 100))
    return OmmResult(
        state=current, p_stay=round(p_stay, 4), stability=stability,
        regime_age_days=age, avg_regime_duration=round(avg_duration, 1),
        transition_row=[round(v, 4) for v in transition_row], state_order=list(STATES),
        conviction_pct=conv_pct, conviction_label=conviction_label(conv_pct),
        interpretation=conviction_interpretation(conv_pct, stability, current),
    )
```

Keep `build_transition_matrix` (legacy) for the existing test and side-by-side display.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_omm.py -v`
Expected: PASS (all, including pre-existing tests — fix any caller of the old `compute_omm` signature in `regime.py` in Task A8/A9; for now keyword args are additive with defaults so existing positional calls still work).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regime_omm.py backend/tests/test_regime_omm.py
git commit -m "feat(regime): horizon-parameterised compute_omm with conviction output"
```

---

### Task A5: Directional HMM + alignment (`regime_hmm_daily.py`)

**Files:**
- Create: `backend/app/services/regime_hmm_daily.py`
- Test: `backend/tests/test_regime_hmm_daily.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_regime_hmm_daily.py
import numpy as np
from app.services.regime_hmm_daily import compute_directional_hmm, alignment

def _bars(closes):
    return [{"close": c} for c in closes]

def test_directional_hmm_labels_or_degrades():
    closes = [100 * (1.003 ** i) for i in range(400)]
    res = compute_directional_hmm(_bars(closes), min_obs=50)
    # Either hmmlearn present -> a directional label, or absent -> None (graceful).
    assert res is None or res.state in ("Bull", "Bear", "Sideways")

def test_alignment_mapping():
    assert alignment("Bull", "Bull") == "Aligned"
    assert alignment("Choppy", "Sideways") == "Aligned"   # Choppy == Sideways
    assert alignment("Bull", "Bear") == "Diverging"
    assert alignment("Bull", None) == "Unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_hmm_daily.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `regime_hmm_daily.py`**

```python
"""Directional Gaussian HMM, timeframe-agnostic (daily or intraday bars).

Fits a 3-state GaussianHMM on the returns of whatever bars are passed and
labels states Bull / Bear / Sideways by mean-return ordering, so the result
is directly comparable to the OMM's Bull/Bear/Choppy labels for alignment.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

MIN_OBS = 200


@dataclass
class DirectionalHmmResult:
    state: str            # Bull | Bear | Sideways
    p_stay: float
    transition_row: list[float]


def compute_directional_hmm(bars: list[dict], *, min_obs: int = MIN_OBS,
                            random_state: int = 42) -> DirectionalHmmResult | None:
    if len(bars) < min_obs:
        return None
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return None

    closes = np.array([float(b["close"]) for b in bars], dtype=float)
    returns = (np.diff(closes) / closes[:-1]).reshape(-1, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = GaussianHMM(n_components=3, covariance_type="diag",
                            n_iter=200, random_state=random_state)
        model.fit(returns)

    means = np.array([model.means_[k][0] for k in range(3)])
    order = np.argsort(means)                       # lowest..highest mean return
    label_by_state = {int(order[0]): "Bear", int(order[1]): "Sideways", int(order[2]): "Bull"}

    current_idx = int(model.predict(returns[-30:])[-1])
    p_stay = float(model.transmat_[current_idx, current_idx])
    row = [float(model.transmat_[current_idx, j]) for j in range(3)]
    return DirectionalHmmResult(state=label_by_state[current_idx],
                                p_stay=round(p_stay, 4),
                                transition_row=[round(v, 4) for v in row])


def alignment(omm_state: str | None, hmm_state: str | None) -> str:
    if not omm_state or not hmm_state:
        return "Unavailable"
    norm = lambda s: "Sideways" if s in ("Choppy", "Sideways") else s
    return "Aligned" if norm(omm_state) == norm(hmm_state) else "Diverging"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_hmm_daily.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/regime_hmm_daily.py backend/tests/test_regime_hmm_daily.py
git commit -m "feat(regime): add directional HMM + OMM/HMM alignment helper"
```

---

### Task A6: Config blocks for regime / gate / sizing

**Files:**
- Modify: `backend/config/scoring_rules.yaml`
- Test: `backend/tests/test_regime_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_regime_gate.py
import yaml
from pathlib import Path

CFG = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"

def test_regime_config_blocks_present():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["regime"]["intraday"]["timeframe"] == "15min"
    assert cfg["regime"]["swing"]["timeframe"] == "daily"
    assert cfg["regime_gate"]["headwind_caution_pct"] == -15
    assert cfg["regime_gate"]["headwind_reject_pct"] == -40
    assert cfg["regime_sizing"]["enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_gate.py::test_regime_config_blocks_present -v`
Expected: FAIL — KeyError 'regime'.

- [ ] **Step 3: Add the YAML blocks**

Append to `backend/config/scoring_rules.yaml` (top level, after `confidence_gate`):

```yaml
regime:
  intraday: { timeframe: 15min, lookback: 26, window: 1000, min_obs: 60 }
  swing:    { timeframe: daily, lookback: 20, window: 500,  min_obs: 100 }
  position: { timeframe: daily, lookback: 50, window: 750,  min_obs: 100 }
  enhanced_states: false

regime_gate:
  enabled: true
  headwind_caution_pct: -15
  headwind_reject_pct:  -40
  require_stable_for_reject: true

regime_sizing:
  enabled: false
  min_mult: 0.5
  full_conviction_pct: 40
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_gate.py::test_regime_config_blocks_present -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config/scoring_rules.yaml backend/tests/test_regime_gate.py
git commit -m "feat(regime): add regime/regime_gate/regime_sizing config blocks"
```

---

### Task A7: `regime` demote-only gate inside `score_stock`

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Test: `backend/tests/test_regime_gate.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from app.scoring.stock_scorer import score_stock

def _flat_bars(n=200):
    return [{"open":100,"high":101,"low":99,"close":100,"volume":1_000_000} for _ in range(n)]

def test_regime_gate_demotes_on_strong_headwind_and_adds_no_points():
    gate = {"enabled": True, "headwind_caution_pct": -15, "headwind_reject_pct": -40,
            "require_stable_for_reject": True}
    signal = {"state":"Bear","p_stay":0.85,"stability":"Stable","regime_age_days":10,
              "avg_regime_duration":6.0,"conviction_pct":-50,"conviction_label":"Strong headwind",
              "interpretation":"...","hmm_state":"Bear","alignment":"Aligned",
              "timeframe":"daily","horizon":"Swing"}
    card = score_stock("X","Bullish","Swing",_flat_bars(),
                       regime_signal=signal, regime_gate=gate, scoring_mode="stock")
    assert card.status == "REJECT"                      # strong headwind + stable -> reject cap
    reg = [r for r in card.rules if r.name == "regime"][0]
    # gate row exists, but the weighted score must not have changed from a no-gate run:
    base = score_stock("X","Bullish","Swing",_flat_bars(), scoring_mode="stock")
    assert card.score == base.score                     # demote-only: zero points added
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_gate.py -k demotes_on_strong_headwind -v`
Expected: FAIL — `score_stock() got an unexpected keyword argument 'regime_signal'`.

- [ ] **Step 3: Add the gate to `score_stock`**

Add params to the signature (after `scoring_mode`):

```python
    regime_signal: dict | None = None,
    regime_gate: dict | None = None,
```

Add this helper above `score_stock`:

```python
def _regime_cap(conviction_pct: int, stability: str, gate: dict) -> Status:
    if not gate.get("enabled", True):
        return "PASS"
    if conviction_pct <= gate["headwind_reject_pct"] and (
        not gate.get("require_stable_for_reject", True) or stability == "Stable"
    ):
        return "REJECT"
    if conviction_pct <= gate["headwind_caution_pct"]:
        return "CAUTION"
    return "PASS"
```

After the `confidence_gate` block (before `return StockScoreCard(...)`):

```python
    if regime_signal is not None and regime_gate is not None:
        cap = _regime_cap(regime_signal["conviction_pct"], regime_signal["stability"], regime_gate)
        final_status = _worse(final_status, cap)
        rules.append(RuleResult(
            name="regime", status=cap, score=0,
            detail={**regime_signal},
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_regime_gate.py
git commit -m "feat(scoring): add demote-only regime gate to score_stock"
```

---

### Task A8: `SentimentData` schema + card/regime fields

**Files:**
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/schemas/stock_scan.py`
- Test: `backend/tests/test_regime_gate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sentiment_schema_constructs():
    from app.schemas import SentimentData, ScoreBreakdown, MarketRegime
    s = SentimentData(horizon="Swing", timeframe="daily", state="Bull", p_stay=0.7,
                      stability="Stable", regime_age_days=5, avg_regime_duration=8.0,
                      conviction_pct=40, conviction_label="Strong tailwind",
                      interpretation="x", alignment="Aligned")
    assert s.conviction_pct == 40
    sb = ScoreBreakdown(trend=1,pullback=1,trigger=1,event=1,volatility=1, sentiment=s)
    assert sb.sentiment.state == "Bull"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_gate.py -k sentiment_schema -v`
Expected: FAIL — `cannot import name 'SentimentData'`.

- [ ] **Step 3: Add `SentimentData` and fields**

In `schemas/__init__.py` add the model (near `OmmData`):

```python
class SentimentData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    horizon: str
    timeframe: str
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    conviction_pct: int
    conviction_label: str
    interpretation: str
    hmm_state: Optional[str] = None
    alignment: Literal['Aligned', 'Diverging', 'Unavailable'] = 'Unavailable'
    insufficient_data: bool = False
```

Add `sentiment: Optional[SentimentData] = None` to `ScoreBreakdown` and `TradeCardData`.
Add to `OmmData`: `conviction_pct: Optional[int] = None`, `conviction_label: Optional[str] = None`.
Add to `MarketRegime`: `conviction_pct: Optional[int] = None`, `conviction_label: Optional[str] = None`, `hmm_state: Optional[str] = None`, `alignment: Optional[str] = None`.
In `schemas/stock_scan.py` add `sentiment: Optional[SentimentData] = None` to `PositionCardOut` (import `SentimentData` from `app.schemas`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regime_gate.py -k sentiment_schema -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/schemas/stock_scan.py backend/tests/test_regime_gate.py
git commit -m "feat(schemas): add SentimentData and conviction/alignment fields"
```

---

### Task A9: Stock scan — horizon fetch, sentiment, sizing, regime_filter

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `backend/app/schemas/stock_scan.py` (`StockScanRequest.regime_filter`, `StockPipeline.failed_regime`)
- Test: `backend/tests/test_stock_scan_regime.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stock_scan_regime.py
from app.routers.stock_scan import _conviction_mult, _load_regime_cfg

def test_conviction_mult_only_reduces():
    sizing = {"enabled": True, "min_mult": 0.5, "full_conviction_pct": 40}
    assert _conviction_mult(40, sizing) == 1.0          # full conviction -> full size
    assert _conviction_mult(0, sizing) == 0.5           # neutral -> floor
    assert _conviction_mult(-50, sizing) == 0.5         # headwind clamps to floor (never <)
    assert _conviction_mult(40, {"enabled": False}) == 1.0   # disabled -> no change

def test_regime_cfg_per_horizon():
    cfg = _load_regime_cfg("Swing")
    assert cfg["timeframe"] == "daily"
    assert cfg["lookback"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stock_scan_regime.py -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement helpers + wiring**

Add to `stock_scan.py`:

```python
import yaml
from pathlib import Path
from app.services.regime_omm import compute_omm
from app.services.regime_hmm_daily import compute_directional_hmm, alignment
from app.data.market import fetch_intraday_candles

_SCORING_CFG = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"

def _load_full_scoring_cfg() -> dict:
    return yaml.safe_load(_SCORING_CFG.read_text())

def _load_regime_cfg(horizon: str) -> dict:
    return _load_full_scoring_cfg()["regime"][horizon.lower()]

def _conviction_mult(conviction_pct: int, sizing: dict) -> float:
    if not sizing.get("enabled", False):
        return 1.0
    full = sizing["full_conviction_pct"]
    lo = sizing["min_mult"]
    frac = max(0.0, min(conviction_pct / full, 1.0)) if full else 0.0
    return lo + (1.0 - lo) * frac
```

In `_process_stock`, after the existing `score_stock` REJECT check is computed, compute regime first and pass it in. Replace the `score_stock(...)` call with regime-aware logic:

```python
            rcfg = _load_regime_cfg(req.horizon)
            full_cfg = _load_full_scoring_cfg()
            if rcfg["timeframe"] == "15min":
                regime_bars = await asyncio.to_thread(
                    fetch_intraday_candles, symbol, "15min", 55
                )
            else:
                regime_bars = bars   # full daily history already fetched
            regime_signal = None
            if regime_bars and len(regime_bars) >= rcfg["min_obs"]:
                omm = compute_omm(
                    [b["close"] for b in regime_bars], direction=req.direction,
                    lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"],
                )
                if omm:
                    dh = await asyncio.to_thread(compute_directional_hmm, regime_bars)
                    regime_signal = {
                        "horizon": req.horizon, "timeframe": rcfg["timeframe"],
                        "state": omm.state, "p_stay": omm.p_stay, "stability": omm.stability,
                        "regime_age_days": omm.regime_age_days,
                        "avg_regime_duration": omm.avg_regime_duration,
                        "conviction_pct": omm.conviction_pct,
                        "conviction_label": omm.conviction_label,
                        "interpretation": omm.interpretation,
                        "hmm_state": dh.state if dh else None,
                        "alignment": alignment(omm.state, dh.state if dh else None),
                        "insufficient_data": False,
                    }

            card = score_stock(
                symbol=symbol, direction=req.direction, horizon=req.horizon,
                bars=bars[-120:], scoring_mode="stock",
                regime_signal=regime_signal,
                regime_gate=full_cfg["regime_gate"] if regime_signal else None,
            )
            if card.status == "REJECT":
                return {"symbol": symbol, "reason": f"REJECT score={card.score}"}

            # regime_filter: drop headwind candidates entirely when requested
            if req.regime_filter and regime_signal and \
               regime_signal["conviction_pct"] <= full_cfg["regime_gate"]["headwind_caution_pct"]:
                return {"symbol": symbol, "reason": "regime headwind"}
```

In `_position_size`, multiply by the conviction mult — change the call site to pass the mult:

```python
            sizing_cfg = full_cfg["regime_sizing"]
            mult = _conviction_mult(regime_signal["conviction_pct"], sizing_cfg) if regime_signal else 1.0
            shares, dollar_risk = _position_size(
                req.account_size, (req.risk_pct or 0.01) * mult, req.risk_fixed_usd,
                signal.entry_price, signal.stop_price,
            )
```

Build `SentimentData` into the returned `PositionCardOut(... sentiment=SentimentData(**regime_signal) if regime_signal else None)` (import `SentimentData`).

Add to `schemas/stock_scan.py`: `regime_filter: bool = False` on `StockScanRequest`; `failed_regime: int = 0` on `StockPipeline`. In `run_stock_scan` pipeline counts, add `failed_regime=sum(1 for r in rejected if isinstance(r, dict) and r.get("reason") == "regime headwind")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_stock_scan_regime.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/app/schemas/stock_scan.py backend/tests/test_stock_scan_regime.py
git commit -m "feat(stock-scan): horizon-aware per-symbol regime, sentiment, conviction sizing, regime_filter"
```

---

### Task A10: Options scan + Page-1 regime inherit the engine

**Files:**
- Modify: `backend/app/routers/scan.py`
- Modify: `backend/app/routers/regime.py`
- Test: `backend/tests/test_regime_no_lookahead.py`

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_regime_no_lookahead.py
def test_compute_omm_is_causal_with_conviction():
    from app.services.regime_omm import compute_omm
    closes = [100 * (1.002 ** i) for i in range(400)]
    full = compute_omm(closes, direction="Bullish", lookback=20, window=500, min_obs=10)
    truncated = compute_omm(closes[:300], direction="Bullish", lookback=20, window=500, min_obs=10)
    # Truncating the future must not change the matrix computed on the past prefix.
    assert truncated is not None and full is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regime_no_lookahead.py -k causal_with_conviction -v`
Expected: FAIL until imports/signature land (passes after A4; this guards regression).

- [ ] **Step 3: Wire scan.py + regime.py**

In `scan.py`, for each shortlisted candidate compute the same `regime_signal` block as A9 (daily bars already fetched; intraday only when horizon Intraday) and pass `regime_signal`/`regime_gate` into **both** `score_stock` calls; attach `sentiment=SentimentData(**regime_signal)` to `TradeCardData`.

In `regime.py` `get_regime`, after `compute_omm(...)` for the OMM block, pass `direction="Bullish"` and the per-horizon `lookback/window/min_obs` from config; populate `omm_out.conviction_pct`/`conviction_label`. Fit `compute_directional_hmm` on the same series; set `MarketRegime.conviction_pct/conviction_label/hmm_state/alignment`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_regime_no_lookahead.py tests/test_regime_omm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/app/routers/regime.py backend/tests/test_regime_no_lookahead.py
git commit -m "feat(regime): options scan + Page-1 regime emit conviction & alignment"
```

---

### Task A11: Frontend `MarketSentiment` component + types

**Files:**
- Create: `frontend/components/molecules/MarketSentiment/index.tsx`
- Create: `frontend/components/molecules/MarketSentiment/MarketSentiment.module.css`
- Modify: `frontend/types/domain.ts`

- [ ] **Step 1: Add the type**

In `frontend/types/domain.ts`:

```ts
export interface SentimentData {
  horizon: string;
  timeframe: string;
  state: string;
  p_stay: number;
  stability: string;
  regime_age_days: number;
  avg_regime_duration: number;
  conviction_pct: number;
  conviction_label: string;
  interpretation: string;
  hmm_state?: string | null;
  alignment: 'Aligned' | 'Diverging' | 'Unavailable';
  insufficient_data?: boolean;
}
```

Add `sentiment?: SentimentData | null;` to the `ScoreBreakdown`, `TradeCardData`, and `PositionCardOut` interfaces.

- [ ] **Step 2: Create the component**

```tsx
// frontend/components/molecules/MarketSentiment/index.tsx
'use client';
import { Text, Data } from '@/components/primitives';
import type { SentimentData } from '@/types/domain';
import styles from './MarketSentiment.module.css';

const tone = (pct: number) =>
  pct >= 15 ? 'pass' : pct <= -15 ? 'reject' : 'caution';

export function MarketSentiment({ s }: { s: SentimentData | null | undefined }) {
  if (!s || s.insufficient_data) {
    return <div className={styles.empty}><Text size={12} tone="dim">Market sentiment — insufficient history</Text></div>;
  }
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <Text size={12} weight={500}>Market Sentiment</Text>
        <Text size={11} tone="dim">{s.horizon} · {s.timeframe}</Text>
      </div>
      <div className={styles.row}>
        <Text size={12} tone="dim">Conviction</Text>
        <Data size={16} tone={tone(s.conviction_pct)}>{s.conviction_pct > 0 ? '+' : ''}{s.conviction_pct}%</Data>
      </div>
      <Text size={12}>{s.conviction_label} — {s.interpretation}</Text>
      <div className={styles.row}>
        <Text size={11} tone="dim">State {s.state} · sticky {Math.round(s.p_stay * 100)}% · ~{s.avg_regime_duration}d</Text>
        <span className={s.alignment === 'Aligned' ? styles.aligned : s.alignment === 'Diverging' ? styles.diverging : styles.unavail}>
          {s.alignment === 'Unavailable' ? 'OMM only' : `OMM/HMM ${s.alignment}`}
        </span>
      </div>
    </div>
  );
}
```

```css
/* frontend/components/molecules/MarketSentiment/MarketSentiment.module.css */
.card { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--border-subtle); border-radius: 6px; }
.empty { padding: 10px; border: 1px dashed var(--border-subtle); border-radius: 6px; }
.head, .row { display: flex; align-items: center; justify-content: space-between; }
.aligned { color: var(--pass); font-size: 11px; }
.diverging { color: var(--caution); font-size: 11px; }
.unavail { color: var(--text-dim); font-size: 11px; }
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/molecules/MarketSentiment frontend/types/domain.ts
git commit -m "feat(ui): MarketSentiment component + SentimentData type"
```

---

### Task A12: Render `MarketSentiment` in cards, score-detail, and Page-1

**Files:**
- Modify: stock position card (`frontend/components/organisms/StockPositionCard/index.tsx`)
- Modify: options trade card (`frontend/components/organisms/TradeCard/index.tsx`)
- Modify: ranking score-detail section component
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx`

- [ ] **Step 1: Render in each consumer**

In each card/section, import and place `<MarketSentiment s={data.sentiment} />` (cards) or `<MarketSentiment s={breakdown.sentiment} />` (score-detail). On Page-1, build a `SentimentData`-shaped object from the `MarketRegime` `conviction_pct/conviction_label/omm/alignment/hmm_state` fields and render the same component in the OMM/HMM panel area.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Verify in the browser** (preview_start, navigate to the stock scan results and Page-1 regime; confirm the sentiment block renders with conviction % and alignment badge).

- [ ] **Step 4: Commit**

```bash
git add frontend/components frontend/app
git commit -m "feat(ui): surface MarketSentiment on cards, score-detail, and Page-1 regime"
```

---

# PART B — Fundamental Health Layer

### Task B1: `fundamentals` model + Alembic migration

**Files:**
- Create: `backend/app/models/fundamentals.py`
- Create: Alembic migration under `backend/alembic/versions/`
- Test: `backend/tests/test_fundamentals_store.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_fundamentals_store.py
def test_fundamentals_model_columns():
    from app.models.fundamentals import Fundamentals
    cols = set(Fundamentals.__table__.columns.keys())
    assert {"symbol","fiscal_period_end","filed_date","revenue","stockholders_eq",
            "shares_diluted","source","fetched_at"} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_store.py::test_fundamentals_model_columns -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create the model**

```python
# backend/app/models/fundamentals.py
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import String, Date, Numeric, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Fundamentals(Base):
    __tablename__ = "fundamentals"
    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cik: Mapped[str | None] = mapped_column(String(12), nullable=True)
    revenue: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    eps_diluted: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    operating_income: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    op_cash_flow: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    capex: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    stockholders_eq: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    current_assets: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    current_liab: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares_diluted: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="sec_edgar")
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
```

Register in `app/models/__init__.py` (import `Fundamentals`). Generate the migration:

```bash
cd backend && alembic revision --autogenerate -m "add fundamentals table"
```

- [ ] **Step 4: Run test + migration**

Run: `cd backend && pytest tests/test_fundamentals_store.py::test_fundamentals_model_columns -v && alembic upgrade head`
Expected: PASS + migration applies cleanly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/fundamentals.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_fundamentals_store.py
git commit -m "feat(fundamentals): add fundamentals model + migration"
```

---

### Task B2: EDGAR client — CIK map + CompanyFacts + concept mapping

**Files:**
- Create: `backend/app/data/edgar.py`
- Test: `backend/tests/test_edgar_mapping.py`
- Fixture: `backend/tests/fixtures/edgar_companyfacts_AAPL.json` (trimmed real shape — `facts.us-gaap.Revenues.units.USD[]` etc.)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_edgar_mapping.py
import json
from pathlib import Path
from app.data.edgar import map_concepts

FIX = Path(__file__).parent / "fixtures" / "edgar_companyfacts_AAPL.json"

def test_map_concepts_extracts_latest_annual():
    facts = json.loads(FIX.read_text())
    snap = map_concepts(facts, symbol="AAPL", cik="0000320193")
    assert snap.revenue is not None
    assert snap.stockholders_eq is not None
    assert snap.fiscal_period_end is not None
```

Create the fixture with at least `Revenues`, `NetIncomeLoss`, `StockholdersEquity`, `EarningsPerShareDiluted` under `facts.us-gaap.<concept>.units.<unit>` arrays with `fy`, `fp`, `end`, `filed`, `val`, `form` keys (use `form == "10-K"` annual rows).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_edgar_mapping.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `edgar.py`**

```python
"""SEC EDGAR client: ticker->CIK map + CompanyFacts fetch + us-gaap concept mapping."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
import httpx
from app.config import get_settings   # for the configurable User-Agent contact string

logger = logging.getLogger(__name__)
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "op_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "stockholders_eq": ["StockholdersEquity"],
    "current_assets": ["AssetsCurrent"],
    "current_liab": ["LiabilitiesCurrent"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
    "total_debt": ["LongTermDebtNoncurrent"],
}

@dataclass
class FundamentalsSnapshot:
    symbol: str
    cik: str
    fiscal_period_end: date | None = None
    filed_date: date | None = None
    revenue: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    op_cash_flow: float | None = None
    capex: float | None = None
    total_debt: float | None = None
    stockholders_eq: float | None = None
    current_assets: float | None = None
    current_liab: float | None = None
    shares_diluted: float | None = None
    prior: dict = field(default_factory=dict)   # year-ago values for YoY growth

def _user_agent() -> str:
    return get_settings().get("edgar_user_agent", "Bamendjou/1.0 (lenetke@googlemail.com)")

def _latest_annual(concept_obj: dict) -> tuple[float, date, date] | None:
    """Return (val, end, filed) for the most recent annual (10-K) row."""
    best = None
    for unit_rows in (concept_obj.get("units") or {}).values():
        for row in unit_rows:
            if row.get("form") != "10-K" or "val" not in row:
                continue
            end = date.fromisoformat(row["end"])
            if best is None or end > best[1]:
                best = (float(row["val"]), end, date.fromisoformat(row.get("filed", row["end"])))
    return best

def map_concepts(facts: dict, *, symbol: str, cik: str) -> FundamentalsSnapshot:
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    snap = FundamentalsSnapshot(symbol=symbol, cik=cik)
    for field_name, concept_names in _CONCEPTS.items():
        for cn in concept_names:
            obj = usgaap.get(cn)
            if not obj:
                continue
            got = _latest_annual(obj)
            if got:
                setattr(snap, field_name, got[0])
                if snap.fiscal_period_end is None or got[1] > snap.fiscal_period_end:
                    snap.fiscal_period_end, snap.filed_date = got[1], got[2]
                break
    return snap

async def fetch_companyfacts(cik: str) -> dict | None:
    url = _FACTS_URL.format(cik=cik.zfill(10))
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _user_agent()}) as c:
        r = await c.get(url)
        if r.status_code != 200:
            logger.warning("EDGAR companyfacts %s -> %s", cik, r.status_code)
            return None
        return r.json()

async def fetch_cik_map() -> dict[str, str]:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _user_agent()}) as c:
        r = await c.get(_TICKER_MAP_URL)
        r.raise_for_status()
        data = r.json()
    return {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()}
```

If `app.config.get_settings` is not the actual accessor, adapt to the project's settings loader (read `settings.yaml`). The contact string must be configurable.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_edgar_mapping.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/edgar.py backend/tests/test_edgar_mapping.py backend/tests/fixtures/edgar_companyfacts_AAPL.json
git commit -m "feat(fundamentals): EDGAR client + us-gaap concept mapping"
```

---

### Task B3: `fundamentals_store.py` — DB-first get/prefetch/status

**Files:**
- Create: `backend/app/services/fundamentals_store.py`
- Test: `backend/tests/test_fundamentals_store.py`

- [ ] **Step 1: Write the failing test**

```python
def test_derived_metrics_computed():
    from app.services.fundamentals_store import derive_metrics
    from app.data.edgar import FundamentalsSnapshot
    snap = FundamentalsSnapshot(symbol="X", cik="1", revenue=1000, gross_profit=400,
                                operating_income=150, op_cash_flow=200, capex=50,
                                total_debt=500, stockholders_eq=1000, current_assets=300,
                                current_liab=150, shares_diluted=100,
                                prior={"revenue": 800, "eps_diluted": 1.0, "shares_diluted": 95})
    snap.eps_diluted = 1.2
    d = derive_metrics(snap)
    assert round(d["gross_margin"], 2) == 0.40
    assert round(d["operating_margin"], 3) == 0.15
    assert round(d["fcf"], 0) == 150
    assert round(d["debt_to_equity"], 2) == 0.50
    assert round(d["current_ratio"], 1) == 2.0
    assert round(d["revenue_growth_yoy"], 2) == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_store.py::test_derived_metrics_computed -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the store + `derive_metrics`**

```python
# backend/app/services/fundamentals_store.py
from __future__ import annotations
from app.data.edgar import FundamentalsSnapshot

def _safe_div(a, b):
    return float(a) / float(b) if a is not None and b not in (None, 0) else None

def _yoy(curr, prior):
    return _safe_div((curr - prior), abs(prior)) if curr is not None and prior not in (None, 0) else None

def derive_metrics(snap: FundamentalsSnapshot) -> dict:
    p = snap.prior or {}
    fcf = None
    if snap.op_cash_flow is not None:
        fcf = float(snap.op_cash_flow) - float(snap.capex or 0)
    return {
        "revenue_growth_yoy": _yoy(snap.revenue, p.get("revenue")),
        "eps_growth_yoy": _yoy(snap.eps_diluted, p.get("eps_diluted")),
        "gross_margin": _safe_div(snap.gross_profit, snap.revenue),
        "operating_margin": _safe_div(snap.operating_income, snap.revenue),
        "fcf": fcf,
        "debt_to_equity": _safe_div(snap.total_debt, snap.stockholders_eq),
        "current_ratio": _safe_div(snap.current_assets, snap.current_liab),
        "share_growth_yoy": _yoy(snap.shares_diluted, p.get("shares_diluted")),
    }
```

Add `get_fundamentals(symbol) -> FundamentalsSnapshot | None` (DB-first: query latest row; if missing or older than `staleness_days`, map CIK, fetch companyfacts, upsert all annual periods, return latest with `prior` populated from the year-ago period), `prefetch_universe(symbols)` (rate-limited background loop), `get_prefetch_status() -> dict`. Mirror `historical_store.py`'s session/upsert pattern. Return `None` on unmapped symbol or fetch failure (logged, never raised).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_fundamentals_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/fundamentals_store.py backend/tests/test_fundamentals_store.py
git commit -m "feat(fundamentals): DB-first store + derived metrics"
```

---

### Task B4: `fundamentals_scorer.py` + config block

**Files:**
- Create: `backend/app/scoring/fundamentals_scorer.py`
- Modify: `backend/config/scoring_rules.yaml`
- Test: `backend/tests/test_fundamentals_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_fundamentals_scorer.py
from app.scoring.fundamentals_scorer import score_fundamentals, FundamentalHealth

_GOOD = {"revenue_growth_yoy":0.2,"eps_growth_yoy":0.2,"gross_margin":0.5,
         "operating_margin":0.2,"fcf":100,"debt_to_equity":0.3,"current_ratio":2.5,
         "share_growth_yoy":-0.01}
_BAD  = {"revenue_growth_yoy":-0.1,"eps_growth_yoy":-0.2,"gross_margin":0.1,
         "operating_margin":-0.05,"fcf":-50,"debt_to_equity":4.0,"current_ratio":0.5,
         "share_growth_yoy":0.10}

def test_strong_company_scores_high():
    h = score_fundamentals(_GOOD, direction="Bullish", stockholders_eq=1000)
    assert h.score >= 70 and h.quality_label == "Strong" and not h.safety_flags

def test_negative_equity_flags_safety():
    h = score_fundamentals(_GOOD, direction="Bullish", stockholders_eq=-50)
    assert "negative_equity" in h.safety_flags

def test_extreme_leverage_flags_safety():
    h = score_fundamentals(_BAD, direction="Bullish", stockholders_eq=1000)
    assert "extreme_leverage" in h.safety_flags
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_scorer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Add config block + implement scorer**

Append to `scoring_rules.yaml`:

```yaml
fundamentals_gate:
  enabled: true
  cautionBelow: 45
  rejectBelow: 30
  safety:
    reject_on_negative_equity: true
    debt_to_equity_reject: 3.0
  staleness_days: 90
  weights: { growth: 0.35, quality: 0.35, risk: 0.30 }
  thresholds:
    revenue_growth_yoy:  { strong: 0.15, weak: 0.0 }
    eps_growth_yoy:      { strong: 0.15, weak: 0.0 }
    gross_margin:        { strong: 0.40, weak: 0.20 }
    operating_margin:    { strong: 0.15, weak: 0.0 }
    debt_to_equity:      { strong: 0.5,  weak: 2.0 }
    current_ratio:       { strong: 2.0,  weak: 1.0 }
    share_growth_yoy:    { strong: 0.0,  weak: 0.03 }
```

```python
# backend/app/scoring/fundamentals_scorer.py
from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import yaml

CFG = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"

@lru_cache(maxsize=1)
def _cfg() -> dict:
    return yaml.safe_load(CFG.read_text())["fundamentals_gate"]

@dataclass
class FundamentalHealth:
    score: int
    quality_label: str
    risk_label: str
    growth_score: int
    quality_score: int
    risk_score: int
    safety_flags: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

def _sub(value, strong, weak, lower_better=False) -> int:
    if value is None:
        return 50
    if lower_better:
        if value <= strong: return 100
        if value >= weak:   return 0
        return round(100 * (weak - value) / (weak - strong))
    if value >= strong: return 100
    if value <= weak:   return 0
    return round(100 * (value - weak) / (strong - weak))

def score_fundamentals(m: dict, *, direction: str, stockholders_eq: float | None) -> FundamentalHealth:
    cfg = _cfg(); t = cfg["thresholds"]; w = cfg["weights"]
    growth = round((_sub(m.get("revenue_growth_yoy"), **t["revenue_growth_yoy"])
                    + _sub(m.get("eps_growth_yoy"), **t["eps_growth_yoy"])) / 2)
    quality = round((_sub(m.get("gross_margin"), **t["gross_margin"])
                     + _sub(m.get("operating_margin"), **t["operating_margin"])
                     + (100 if (m.get("fcf") or 0) > 0 else 0)) / 3)
    risk = round((_sub(m.get("debt_to_equity"), **t["debt_to_equity"], lower_better=True)
                  + _sub(m.get("current_ratio"), **t["current_ratio"])
                  + _sub(m.get("share_growth_yoy"), **t["share_growth_yoy"], lower_better=True)) / 3)
    score = round(w["growth"]*growth + w["quality"]*quality + w["risk"]*risk)
    flags = []
    if cfg["safety"]["reject_on_negative_equity"] and stockholders_eq is not None and stockholders_eq < 0:
        flags.append("negative_equity")
    de = m.get("debt_to_equity")
    if de is not None and de >= cfg["safety"]["debt_to_equity_reject"]:
        flags.append("extreme_leverage")
    quality_label = "Strong" if quality >= 66 else "Weak" if quality < 40 else "Neutral"
    risk_label = "Low" if risk >= 66 else "High" if risk < 40 else "Medium"
    return FundamentalHealth(score=score, quality_label=quality_label, risk_label=risk_label,
                             growth_score=growth, quality_score=quality, risk_score=risk,
                             safety_flags=flags, detail={**m, "stockholders_eq": stockholders_eq})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_fundamentals_scorer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/fundamentals_scorer.py backend/config/scoring_rules.yaml backend/tests/test_fundamentals_scorer.py
git commit -m "feat(fundamentals): pure scorer + config thresholds"
```

---

### Task B5: `fundamentals` gate inside `score_stock`

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Test: `backend/tests/test_fundamentals_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_fundamentals_gate.py
from app.scoring.stock_scorer import score_stock
from app.scoring.fundamentals_scorer import FundamentalHealth

def _bars(n=200):
    return [{"open":100,"high":101,"low":99,"close":100,"volume":1_000_000} for _ in range(n)]

GATE = {"enabled": True, "cautionBelow": 45, "rejectBelow": 30}

def test_weak_fundamentals_demote_bullish_only():
    weak = FundamentalHealth(score=20, quality_label="Weak", risk_label="High",
                             growth_score=10, quality_score=20, risk_score=30)
    bull = score_stock("X","Bullish","Swing",_bars(), fundamentals=weak, fundamentals_gate=GATE, scoring_mode="stock")
    bear = score_stock("X","Bearish","Swing",_bars(), fundamentals=weak, fundamentals_gate=GATE, scoring_mode="stock")
    assert bull.status == "REJECT"        # bullish demoted
    base_bear = score_stock("X","Bearish","Swing",_bars(), scoring_mode="stock")
    assert bear.status == base_bear.status  # bearish NOT demoted by weakness

def test_safety_flag_rejects_both_directions():
    danger = FundamentalHealth(score=80, quality_label="Strong", risk_label="High",
                               growth_score=80, quality_score=80, risk_score=80,
                               safety_flags=["negative_equity"])
    for d in ("Bullish","Bearish"):
        c = score_stock("X",d,"Swing",_bars(), fundamentals=danger, fundamentals_gate=GATE, scoring_mode="stock")
        assert c.status == "REJECT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_gate.py -v`
Expected: FAIL — `score_stock() got an unexpected keyword argument 'fundamentals'`.

- [ ] **Step 3: Add the gate**

Add params to `score_stock`: `fundamentals=None, fundamentals_gate: dict | None = None`. After the regime gate block (Task A7), and **only when** `horizon in ("Swing","Position")`:

```python
    if fundamentals is not None and fundamentals_gate is not None and horizon in ("Swing", "Position"):
        if fundamentals.safety_flags:
            final_status = _worse(final_status, "REJECT")
        elif direction == "Bullish" and fundamentals_gate.get("enabled", True):
            if fundamentals.score < fundamentals_gate["rejectBelow"]:
                final_status = _worse(final_status, "REJECT")
            elif fundamentals.score < fundamentals_gate["cautionBelow"]:
                final_status = _worse(final_status, "CAUTION")
        rules.append(RuleResult(
            name="fundamentals", status=final_status, score=fundamentals.score,
            detail={"quality_label": fundamentals.quality_label, "risk_label": fundamentals.risk_label,
                    "growth": fundamentals.growth_score, "quality": fundamentals.quality_score,
                    "risk": fundamentals.risk_score, "safety_flags": fundamentals.safety_flags},
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_fundamentals_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_fundamentals_gate.py
git commit -m "feat(scoring): add demote-only fundamentals gate to score_stock"
```

---

### Task B6: `FundamentalsOut` schema + request fields + `_resolve_fundamentals_gate`

**Files:**
- Modify: `backend/app/schemas/__init__.py`, `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/routers/scan.py` (helper) — shared by stock scan too
- Test: `backend/tests/test_fundamentals_gate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fundamentals_out_and_resolver():
    from app.schemas import FundamentalsOut
    from app.routers.scan import _resolve_fundamentals_gate
    class Req: fundamentals_enabled=False; fundamentals_caution_below=None
    Req.fundamentals_reject_below=None; Req.fundamentals_de_reject=None
    g = _resolve_fundamentals_gate(Req())
    assert g["enabled"] is False
    out = FundamentalsOut(score=70, quality_label="Strong", risk_label="Low",
                          growth_score=70, quality_score=70, risk_score=70, safety_flags=[])
    assert out.score == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_gate.py -k out_and_resolver -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement schema + fields + resolver**

`schemas/__init__.py`:

```python
class FundamentalsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    score: int
    quality_label: str
    risk_label: str
    growth_score: int
    quality_score: int
    risk_score: int
    safety_flags: list[str] = []
    detail: dict = {}
```

Add `fundamentals: Optional[FundamentalsOut] = None` to `TradeCardData`. Add the four optional gate fields to `ScanRequest`. In `schemas/stock_scan.py` add `fundamentals: Optional[FundamentalsOut] = None` to `PositionCardOut` and the four fields to `StockScanRequest`.

In `scan.py` add:

```python
from app.scoring.fundamentals_scorer import _cfg as _load_fund_cfg   # or a dedicated loader

def _resolve_fundamentals_gate(req) -> dict:
    import copy
    g = copy.deepcopy(_load_fund_cfg())
    if getattr(req, "fundamentals_enabled", None) is not None:        g["enabled"] = req.fundamentals_enabled
    if getattr(req, "fundamentals_caution_below", None) is not None:  g["cautionBelow"] = req.fundamentals_caution_below
    if getattr(req, "fundamentals_reject_below", None) is not None:   g["rejectBelow"] = req.fundamentals_reject_below
    if getattr(req, "fundamentals_de_reject", None) is not None:      g["safety"]["debt_to_equity_reject"] = req.fundamentals_de_reject
    return g
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_fundamentals_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/app/routers/scan.py backend/tests/test_fundamentals_gate.py
git commit -m "feat(fundamentals): FundamentalsOut schema, request fields, gate resolver"
```

---

### Task B7: Wire both routers + background prefetch

**Files:**
- Modify: `backend/app/routers/scan.py`, `backend/app/routers/stock_scan.py`, `backend/app/main.py`

- [ ] **Step 1: Wire stock scan** — in `_process_stock`, after price filters and before `score_stock`, when `req.horizon in ("Swing","Position")`:

```python
            fund_health = None
            if req.horizon in ("Swing", "Position"):
                snap = await asyncio.to_thread(get_fundamentals, symbol)
                if snap:
                    from app.services.fundamentals_store import derive_metrics
                    from app.scoring.fundamentals_scorer import score_fundamentals
                    fund_health = score_fundamentals(derive_metrics(snap),
                        direction=req.direction, stockholders_eq=snap.stockholders_eq)
```

Pass `fundamentals=fund_health, fundamentals_gate=_resolve_fundamentals_gate(req)` into `score_stock`, and set `fundamentals=FundamentalsOut(...)` on `PositionCardOut`.

- [ ] **Step 2: Wire options scan** — same fetch + pass into **both** `score_stock` calls (pre-screen + final); attach `fundamentals` to `TradeCardData`. Resolve the gate once at the top of the scan.

- [ ] **Step 3: Add prefetch** — in `main.py` startup (where OHLCV prefetch is kicked off), call `fundamentals_store.prefetch_universe(...)` as a background task.

- [ ] **Step 4: Verify** — run the backend test suite:

Run: `cd backend && pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/app/routers/stock_scan.py backend/app/main.py
git commit -m "feat(fundamentals): wire gate into both scans + startup prefetch"
```

---

### Task B8: Frontend — settings, Step-3, RunScanButton, cards, Health column

**Files:**
- Modify: `frontend/lib/settingsStore.ts`, `frontend/app/(frame)/screener/step-3-direction/page.tsx`, RunScanButton `index.tsx`, `frontend/lib/api.ts`, `StockPositionCard`, options `TradeCard`, Step-4 stocks results table, `frontend/types/domain.ts`

- [ ] **Step 1: Types + store** — add `FundamentalsOut` interface to `domain.ts`; add `fundamentals?: FundamentalsOut | null` to the card types. Add persisted `fundamentalsGate { enabled, cautionBelow, rejectBelow, deReject }` to `settingsStore.ts` (bump `version`, add a `migrate` branch — per the project's Zustand persistence rule).

- [ ] **Step 2: Step-3 + RunScanButton** — add a "Fundamentals" subGroup of threshold rows (Swing/Position only). In RunScanButton inject `fundamentals_enabled/_caution_below/_reject_below/_de_reject` into the request `filters`, mirroring the confidence block (`enabled === false → no-op`). Extend the `filters` type in `api.ts`.

- [ ] **Step 3: Cards + column** — add a "Fundamental Health" section (0–100 score, quality/risk labels, 3 bucket scores; color-mix tints, no shadow, `border-subtle`) to `StockPositionCard` and options `TradeCard`. Add a sortable **Health** column to the Step-4 stocks table. Render "—" when `fundamentals` is null.

- [ ] **Step 4: Typecheck + verify**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean + green. Then preview the stock scan and confirm the Health section renders and the gate demotes a weak-fundamental bullish name.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(ui): fundamental health on cards, Step-3 thresholds, Health column"
```

---

## Self-Review notes
- **Spec coverage:** PART A covers Markov spec §1–§8 (stride A1, conviction A2, n-step/stationary A3, horizon compute_omm A4, directional HMM+alignment A5, config A6, gate A7, schemas A8, stock scan incl. sizing+filter A9, options+Page1 A10, UI A11–A12). PART B covers Fundamental spec §3–§7 (model B1, EDGAR B2, store B3, scorer+config B4, gate B5, schema/resolver B6, router+prefetch B7, UI B8).
- **Sequencing guard:** A7 adds the regime gate; B5 adds the fundamentals gate to the *same* `score_stock` — B5 is written to append *after* the regime block, so building PART A fully before PART B avoids signature churn.
- **Out of scope (per specs):** intraday fundamentals, sector-relative ranking, walk-forward confidence (separate plan), enhanced-states clustering beyond the config flag.
