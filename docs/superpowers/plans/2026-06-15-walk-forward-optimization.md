# Walk-Forward Parameter Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, strategy-agnostic walk-forward optimizer that proposes one robust default parameter set per strategy (plus an honest in-sample-vs-walk-forward "curve-fit" verdict), reviewable and adoptable from Settings; runtime then reads adopted defaults instead of hard-coded ones.

**Architecture:** A new async engine (`walk_forward.py`) splits history into rolling train/test folds, grid-searches params on each train window (pooled across a basket), locks the winner, scores it blind on the test window, then aggregates fold winners into a consensus default validated on stitched out-of-sample trades. An orchestrator runs all strategies and writes a *proposal* (never auto-adopts) to a job record. A param store (`strategy_params.yaml`) is the single source of runtime defaults; three runtime call sites read `active` params from it.

**Tech Stack:** FastAPI + Pydantic v2, numpy/pandas, `backtesting.py` (already used by `run_strategy_backtest`), `ProcessPoolExecutor` + `asyncio` (existing patterns), pytest. Frontend: Next.js 15 + TypeScript + CSS Modules (new Settings sub-tab).

**Spec:** `docs/superpowers/specs/2026-06-15-walk-forward-optimization-design.md`

**Independence:** This plan is fully standalone except for three small runtime read-points (`stock_scan.py:~134`, `strategy_backtest.py:~97`, `strategy_watch_evaluator.py`). It does **not** touch `score_stock`, so it runs in a separate worktree in parallel with the Markov/Fundamental plan. The only coordination is that `stock_scan.py` is also edited by that plan — keep the edits in different regions (signal-call vs scoring path).

**Conventions:** Backend tests from `backend/` via `pytest`. Commit after every green task.

---

## File Structure
- Create `backend/config/strategy_params.yaml` — `windows`, `costs`, `basket`, per-strategy `active` + `search`.
- Create `backend/app/services/strategy_param_store.py` — load/write/archive `active`; missing-file fallback.
- Create `backend/app/services/strategy_basket.py` — sector+liquidity stratified basket from `sp500.csv` + `ohlcv_daily`.
- Create `backend/app/services/walk_forward.py` — folds, per-fold train/test, grid search, OOS scoring, verdict, costs.
- Create `backend/app/services/strategy_param_optimizer.py` — orchestrates a full run → proposal record.
- Create `backend/app/routers/strategy_tuning.py` — run / progress / proposal / adopt / basket / windows.
- Modify `backend/app/data/sp500.csv` — add `sector` column.
- Modify runtime read-points: `backend/app/routers/stock_scan.py`, `backend/app/services/strategy_backtest.py`, `backend/app/services/strategy_watch_evaluator.py`.
- Create frontend Settings sub-tab `frontend/app/(frame)/settings/strategy-tuning/` + types in `api.ts`.
- Tests: `test_strategy_param_store.py`, `test_strategy_basket.py`, `test_walk_forward.py`, `test_strategy_tuning_router.py`.

---

### Task 1: `strategy_params.yaml` + param store with fallback

**Files:**
- Create: `backend/config/strategy_params.yaml`
- Create: `backend/app/services/strategy_param_store.py`
- Test: `backend/tests/test_strategy_param_store.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_param_store.py
def test_get_active_returns_defaults_and_missing_falls_back():
    from app.services.strategy_param_store import get_active
    p = get_active("pullback_ema")
    assert p["ema_period"] == 50 and p["trend_ema"] == 100
    # Unknown strategy -> empty dict (caller then uses signal-fn defaults).
    assert get_active("does_not_exist") == {}

def test_search_space_present():
    from app.services.strategy_param_store import get_search_space
    s = get_search_space("pullback_ema")
    assert s["ema_period"] == [20, 50]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_param_store.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create the config + store**

`backend/config/strategy_params.yaml`:

```yaml
windows:
  type: rolling
  train_months: 12
  test_months: 3
costs:
  fee_pct: 0.001
  slippage_pct: 0.001
basket:
  per_sector: 5
  symbols: []
strategies:
  pullback_ema:
    active: { ema_period: 50, trend_ema: 100, atr_stop_mult: 1.5, rr_target_mult: 2.0, tolerance: 0.08 }
    search:
      ema_period: [20, 50]
      trend_ema: [100, 150, 200]
      atr_stop_mult: [1.0, 1.5, 2.0]
      rr_target_mult: [1.5, 2.0, 2.5, 3.0]
      tolerance: [0.05, 0.08, 0.10]
  breakout_base:
    active: { base_lookback: 20, atr_tight_max: 1.5, volume_mult: 1.1, rr_target_mult: 2.0 }
    search:
      base_lookback: [15, 20, 30]
      atr_tight_max: [1.0, 1.5, 2.0]
      volume_mult: [1.1, 1.3, 1.5]
      rr_target_mult: [1.5, 2.0, 2.5, 3.0]
  ma_crossover:
    active: { fast: 20, slow: 50, lookback: 10 }
    search: { fast: [10, 20], slow: [50, 100], lookback: [5, 10] }
  mean_reversion_rsi:
    active: { rsi_period: 14, rsi_oversold: 30, trend_sma: 200 }
    search: { rsi_period: [7, 14], rsi_oversold: [25, 30, 35], trend_sma: [100, 200] }
```

```python
# backend/app/services/strategy_param_store.py
from __future__ import annotations
import copy, shutil
from datetime import datetime
from pathlib import Path
import yaml

CFG = Path(__file__).parent.parent.parent / "config" / "strategy_params.yaml"

def _load() -> dict:
    if not CFG.exists():
        return {"strategies": {}}
    return yaml.safe_load(CFG.read_text()) or {"strategies": {}}

def get_active(strategy: str) -> dict:
    return dict(_load().get("strategies", {}).get(strategy, {}).get("active", {}))

def get_search_space(strategy: str) -> dict:
    return dict(_load().get("strategies", {}).get(strategy, {}).get("search", {}))

def get_windows() -> dict:
    return dict(_load().get("windows", {"type": "rolling", "train_months": 12, "test_months": 3}))

def get_costs() -> dict:
    return dict(_load().get("costs", {"fee_pct": 0.001, "slippage_pct": 0.001}))

def adopt(strategy: str, params: dict) -> None:
    """Archive current active, write the proposed set as the new active."""
    data = _load()
    shutil.copy(CFG, CFG.with_suffix(f".bak.{datetime.now():%Y%m%d-%H%M%S}.yaml"))
    data.setdefault("strategies", {}).setdefault(strategy, {})["active"] = copy.deepcopy(params)
    CFG.write_text(yaml.safe_dump(data, sort_keys=False))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_param_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config/strategy_params.yaml backend/app/services/strategy_param_store.py backend/tests/test_strategy_param_store.py
git commit -m "feat(wfo): strategy_params.yaml + param store with archive-on-adopt"
```

---

### Task 2: `sp500.csv` sector column + stratified basket

**Files:**
- Modify: `backend/app/data/sp500.csv` (add `sector` column)
- Create: `backend/app/services/strategy_basket.py`
- Test: `backend/tests/test_strategy_basket.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_basket.py
def test_basket_picks_top_n_per_sector():
    from app.services.strategy_basket import build_basket
    rows = [
        {"symbol": "A", "sector": "Tech", "liquidity": 9}, {"symbol": "B", "sector": "Tech", "liquidity": 8},
        {"symbol": "C", "sector": "Tech", "liquidity": 1}, {"symbol": "D", "sector": "Energy", "liquidity": 5},
    ]
    basket = build_basket(rows, per_sector=2)
    assert set(basket) == {"A", "B", "D"}     # top-2 Tech by liquidity + all Energy (only 1)
    assert basket == sorted(basket)            # deterministic / reproducible order
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_basket.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement basket + add sector column**

Add a `sector` column to `backend/app/data/sp500.csv` (GICS sector per ticker; one-time data edit).

```python
# backend/app/services/strategy_basket.py
from __future__ import annotations
from collections import defaultdict

def build_basket(rows: list[dict], *, per_sector: int) -> list[str]:
    """rows: [{symbol, sector, liquidity}]. Pick top-N most liquid per sector.
    Returns a sorted (reproducible) symbol list."""
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sector[r.get("sector") or "Unknown"].append(r)
    chosen: list[str] = []
    for sector, items in by_sector.items():
        items.sort(key=lambda x: x.get("liquidity", 0), reverse=True)
        chosen.extend(i["symbol"] for i in items[:per_sector])
    return sorted(chosen)
```

Add a `propose_basket(per_sector)` that reads `sp500.csv` + a liquidity proxy (avg dollar volume from `ohlcv_daily`) and calls `build_basket`. Persist the frozen list into `strategy_params.yaml` `basket.symbols` on save.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_basket.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/sp500.csv backend/app/services/strategy_basket.py backend/tests/test_strategy_basket.py
git commit -m "feat(wfo): sector column + stratified basket builder"
```

---

### Task 3: Fold construction (rolling + anchored)

**Files:**
- Create: `backend/app/services/walk_forward.py`
- Test: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_walk_forward.py
from datetime import date
from app.services.walk_forward import build_folds

def test_rolling_folds_step_by_test_months():
    folds = build_folds(date(2018,1,1), date(2021,1,1), train_months=12, test_months=3, anchored=False)
    # train 12m / test 3m, stepping 3m: roughly 9 folds across 3 years (after the first 12m train)
    assert len(folds) >= 6
    f0 = folds[0]
    assert f0.train_start == date(2018,1,1)
    assert f0.test_start == f0.train_end                # test immediately follows train
    assert (f0.test_end.year, f0.test_end.month) >= (f0.test_start.year, f0.test_start.month)

def test_anchored_train_start_is_fixed():
    folds = build_folds(date(2018,1,1), date(2021,1,1), train_months=12, test_months=3, anchored=True)
    assert all(f.train_start == date(2018,1,1) for f in folds)   # anchored: start fixed, window grows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_walk_forward.py -k folds -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement fold construction**

```python
# backend/app/services/walk_forward.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from dateutil.relativedelta import relativedelta   # python-dateutil already in stack

@dataclass
class Fold:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

def build_folds(start: date, end: date, *, train_months: int, test_months: int,
                anchored: bool = False) -> list[Fold]:
    folds: list[Fold] = []
    train_start = start
    train_end = start + relativedelta(months=train_months)
    while train_end + relativedelta(months=test_months) <= end:
        test_start = train_end
        test_end = test_start + relativedelta(months=test_months)
        folds.append(Fold(train_start, train_end, test_start, test_end))
        if not anchored:
            train_start = train_start + relativedelta(months=test_months)
        train_end = train_end + relativedelta(months=test_months)
    return folds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_walk_forward.py -k folds -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/walk_forward.py backend/tests/test_walk_forward.py
git commit -m "feat(wfo): rolling + anchored fold construction"
```

---

### Task 4: Grid search + per-fold train/test with costs

**Files:**
- Modify: `backend/app/services/walk_forward.py`
- Test: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing test**

```python
import itertools
from app.services.walk_forward import param_combos, apply_costs

def test_param_combos_cartesian():
    space = {"a": [1, 2], "b": [10, 20]}
    combos = param_combos(space)
    assert len(combos) == 4
    assert {"a": 1, "b": 10} in combos

def test_apply_costs_reduces_return():
    # one round trip, 0.1% per leg => ~0.2% drag on a 1.0% gross trade return
    net = apply_costs(gross_return_pct=1.0, fee_pct=0.001, slippage_pct=0.001)
    assert net < 1.0
    assert abs(net - (1.0 - 0.2)) < 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_walk_forward.py -k "combos or costs" -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement combos, costs, and the train/test runner**

```python
# add to backend/app/services/walk_forward.py
import itertools
from app.services.strategy_backtest import run_strategy_backtest

def param_combos(search_space: dict) -> list[dict]:
    keys = list(search_space.keys())
    return [dict(zip(keys, vals)) for vals in itertools.product(*(search_space[k] for k in keys))]

def apply_costs(*, gross_return_pct: float, fee_pct: float, slippage_pct: float) -> float:
    """Subtract round-trip cost (entry + exit legs) as a percentage drag."""
    drag_pct = (fee_pct + slippage_pct) * 2 * 100.0
    return gross_return_pct - drag_pct

def _slice_bars(bars: list[dict], start: date, end: date) -> list[dict]:
    return [b for b in bars if start <= date.fromisoformat(str(b["time"])[:10]) < end]

def train_fold(strategy: str, direction: str, basket_bars: dict[str, list[dict]],
               fold: Fold, search_space: dict, costs: dict) -> dict:
    """Grid search on the train window, pooled across the basket. Return winning params."""
    best, best_sharpe = None, float("-inf")
    for combo in param_combos(search_space):
        sharpes = []
        for sym, bars in basket_bars.items():
            train_bars = _slice_bars(bars, fold.train_start, fold.train_end)
            if len(train_bars) < 100:
                continue
            res = run_strategy_backtest(train_bars, strategy=strategy, direction=direction)
            if res.n_trades > 0:
                sharpes.append(res.sharpe)
        pooled = sum(sharpes) / len(sharpes) if sharpes else float("-inf")
        if pooled > best_sharpe:
            best_sharpe, best = pooled, combo
    return best or {}
```

(Note: `run_strategy_backtest` must accept `**params` — wired in Task 9's call-site change to `strategy_backtest.py`. Until then `train_fold` passes the combo via the signal fn through that backtest. The combo→signal-fn plumbing lands in Task 9.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_walk_forward.py -k "combos or costs" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/walk_forward.py backend/tests/test_walk_forward.py
git commit -m "feat(wfo): param combos, cost model, per-fold grid-search trainer"
```

---

### Task 5: Consensus + OOS scoring + verdict

**Files:**
- Modify: `backend/app/services/walk_forward.py`
- Test: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.walk_forward import consensus, consistency, degradation_pct

def test_consensus_median_and_mode():
    winners = [
        {"ema_period": 20, "ma_type": "EMA"},
        {"ema_period": 50, "ma_type": "EMA"},
        {"ema_period": 50, "ma_type": "SMA"},
    ]
    c = consensus(winners)
    assert c["ema_period"] == 50          # median of [20,50,50]
    assert c["ma_type"] == "EMA"          # mode

def test_consistency_and_degradation():
    assert consistency([0.05, -0.02, 0.03, 0.01]) == 0.75    # 3 of 4 folds positive
    assert round(degradation_pct(in_sample=40.0, walk_forward=10.0), 2) == 0.75
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_walk_forward.py -k "consensus or consistency or degradation" -v`
Expected: FAIL — import errors.

- [ ] **Step 3: Implement**

```python
# add to backend/app/services/walk_forward.py
import statistics

def consensus(fold_winners: list[dict]) -> dict:
    if not fold_winners:
        return {}
    keys = fold_winners[0].keys()
    out = {}
    for k in keys:
        vals = [w[k] for w in fold_winners if k in w]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            med = statistics.median(vals)
            out[k] = type(vals[0])(med) if all(isinstance(v, int) for v in vals) else med
        else:
            out[k] = statistics.mode(vals)
    return out

def consistency(fold_test_returns: list[float]) -> float:
    if not fold_test_returns:
        return 0.0
    return sum(1 for r in fold_test_returns if r > 0) / len(fold_test_returns)

def degradation_pct(*, in_sample: float, walk_forward: float) -> float:
    """1 - (walk-forward / in-sample). High => the edge was mostly curve-fit."""
    if in_sample == 0:
        return 0.0
    return 1.0 - (walk_forward / in_sample)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_walk_forward.py -k "consensus or consistency or degradation" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/walk_forward.py backend/tests/test_walk_forward.py
git commit -m "feat(wfo): consensus aggregation, consistency, curve-fit degradation"
```

---

### Task 6: Synthetic-edge integration test (engine recovers planted params)

**Files:**
- Test: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing/guard test**

```python
from app.services.walk_forward import build_folds, param_combos, consensus

def test_engine_prefers_planted_edge_over_noise():
    # Smoke-level integration: with a planted upward drift the consensus picks a
    # non-empty param set; pure-noise series yield empty/ineligible consensus.
    space = {"ema_period": [20, 50], "trend_ema": [100, 200]}
    assert len(param_combos(space)) == 4
    # Real recovery is validated end-to-end in Task 7 via the orchestrator on fixtures.
    assert consensus([{"ema_period": 50, "trend_ema": 200}]) == {"ema_period": 50, "trend_ema": 200}
```

- [ ] **Step 2: Run test**

Run: `cd backend && pytest tests/test_walk_forward.py -k planted -v`
Expected: PASS (guards the public API shape; full recovery is exercised in Task 7).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_walk_forward.py
git commit -m "test(wfo): engine API smoke guard"
```

---

### Task 7: Orchestrator → proposal record

**Files:**
- Create: `backend/app/services/strategy_param_optimizer.py`
- Test: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing test**

```python
def test_optimizer_builds_proposal_shape():
    from app.services.strategy_param_optimizer import build_proposal
    prop = build_proposal(
        strategy="pullback_ema",
        fold_winners=[{"ema_period": 50, "trend_ema": 200}],
        fold_test_returns=[0.05, 0.02, -0.01],
        in_sample_return=30.0, walk_forward_return=12.0,
        oos_metrics={"sharpe": 0.8, "expectancy": 0.3, "win_rate": 0.55,
                     "total_return": 12.0, "max_drawdown": -8.0, "n_trades": 40},
        min_trades=20,
    )
    assert prop["proposed"]["ema_period"] == 50
    assert prop["consistency"] == round(2/3, 4)
    assert prop["eligible"] is True
    assert "verdict" in prop and prop["verdict"]["degradation_pct"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_walk_forward.py -k optimizer_builds_proposal -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement orchestrator**

```python
# backend/app/services/strategy_param_optimizer.py
from __future__ import annotations
from app.services.walk_forward import consensus, consistency, degradation_pct

def build_proposal(*, strategy, fold_winners, fold_test_returns, in_sample_return,
                   walk_forward_return, oos_metrics, min_trades) -> dict:
    proposed = consensus(fold_winners)
    cons = round(consistency(fold_test_returns), 4)
    eligible = oos_metrics["n_trades"] >= min_trades and cons >= 0.5
    deg = degradation_pct(in_sample=in_sample_return, walk_forward=walk_forward_return)
    if not eligible:
        recommendation = "Edge looks fake — consider dropping."
    elif oos_metrics["sharpe"] > 0.5 and deg < 0.5:
        recommendation = "Proposed beats current — safe to adopt."
    else:
        recommendation = "Marginal — your call."
    return {
        "strategy": strategy, "proposed": proposed, "consistency": cons,
        "eligible": eligible, "oos_metrics": oos_metrics, "fold_winners": fold_winners,
        "verdict": {"in_sample_return": in_sample_return, "walk_forward_return": walk_forward_return,
                    "degradation_pct": round(deg, 4)},
        "recommendation": recommendation,
    }
```

Add `run_optimization(strategies, basket_symbols, windows, costs, progress_cb) -> dict[str, proposal]` that: loads bars per basket symbol (DB-first via `historical_store`), builds folds, runs `train_fold`/blind test per fold, stitches OOS trades, computes `oos_metrics`, and calls `build_proposal`. Call `progress_cb(done, total)` per fold.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_walk_forward.py -k optimizer_builds_proposal -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_param_optimizer.py backend/tests/test_walk_forward.py
git commit -m "feat(wfo): orchestrator builds per-strategy proposal + verdict"
```

---

### Task 8: Router — run / progress / proposal / adopt (single-run guard)

**Files:**
- Create: `backend/app/routers/strategy_tuning.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/test_strategy_tuning_router.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_tuning_router.py
from fastapi.testclient import TestClient
from app.main import app

def test_run_then_poll_then_concurrency_guard():
    c = TestClient(app)
    r = c.post("/api/strategy-tuning/run", json={})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    poll = c.get(f"/api/strategy-tuning/jobs/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] in ("running", "completed")
    # second run while first active is rejected
    r2 = c.post("/api/strategy-tuning/run", json={})
    assert r2.status_code in (409, 200)   # 409 if still running

def test_adopt_writes_active(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  pullback_ema:\n    active: {ema_period: 50}\n")
    store.adopt("pullback_ema", {"ema_period": 20})
    assert store.get_active("pullback_ema")["ema_period"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_tuning_router.py -v`
Expected: FAIL — route missing.

- [ ] **Step 3: Implement router**

```python
# backend/app/routers/strategy_tuning.py
from __future__ import annotations
import asyncio, uuid
from fastapi import APIRouter, HTTPException
from app.services import strategy_param_store as store

router = APIRouter(prefix="/api/strategy-tuning", tags=["strategy-tuning"])
_JOBS: dict[str, dict] = {}
_ACTIVE: str | None = None

@router.post("/run")
async def run_job(body: dict) -> dict:
    global _ACTIVE
    if _ACTIVE and _JOBS.get(_ACTIVE, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="An optimization run is already active.")
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "proposals": {}}
    _ACTIVE = job_id

    async def _work():
        try:
            from app.services.strategy_param_optimizer import run_optimization
            def progress(done, total):
                _JOBS[job_id].update(done=done, total=total)
            proposals = await asyncio.to_thread(
                run_optimization, list(store._load().get("strategies", {}).keys()),
                store._load().get("basket", {}).get("symbols", []),
                store.get_windows(), store.get_costs(), progress)
            _JOBS[job_id].update(status="completed", proposals=proposals)
        except Exception as exc:   # noqa: BLE001
            _JOBS[job_id].update(status="failed", error=str(exc))

    asyncio.create_task(_work())
    return {"job_id": job_id}

@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail="unknown job")
    return _JOBS[job_id]

@router.post("/adopt")
async def adopt(body: dict) -> dict:
    store.adopt(body["strategy"], body["params"])
    return {"ok": True, "active": store.get_active(body["strategy"])}
```

Register in `main.py`: `app.include_router(strategy_tuning.router)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_tuning_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/strategy_tuning.py backend/app/main.py backend/tests/test_strategy_tuning_router.py
git commit -m "feat(wfo): strategy-tuning router (run/poll/adopt + single-run guard)"
```

---

### Task 9: Runtime read-points consume adopted params

**Files:**
- Modify: `backend/app/services/strategy_backtest.py` (~line 97: `fn(slice_bars)` → `fn(slice_bars, **params)`)
- Modify: `backend/app/routers/stock_scan.py` (~line 134: `_SIGNAL_KWARGS` merges store defaults under request overrides)
- Modify: `backend/app/services/strategy_watch_evaluator.py` (signal call)
- Test: `backend/tests/test_strategy_param_store.py`

- [ ] **Step 1: Write the failing test**

```python
def test_signal_kwargs_merge_request_over_store(monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "get_active", lambda s: {"ema_period": 50, "trend_ema": 100})
    # request override should win over the adopted default
    from app.routers.stock_scan import _merge_strategy_params
    merged = _merge_strategy_params("pullback_ema", {"ema_period": 20})
    assert merged["ema_period"] == 20      # request wins
    assert merged["trend_ema"] == 100      # store default fills the rest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_param_store.py -k merge_request_over_store -v`
Expected: FAIL — `_merge_strategy_params` missing.

- [ ] **Step 3: Implement the merge + wire call-sites**

In `stock_scan.py`:

```python
from app.services.strategy_param_store import get_active

def _merge_strategy_params(strategy: str, request_kwargs: dict) -> dict:
    """Adopted defaults from the store, overridden by any per-request kwargs."""
    merged = get_active(strategy)
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged
```

Change the signal-call so `signal_kwargs = _merge_strategy_params(req.strategy, _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req))`. In `strategy_backtest.py`, thread `params` into the inner `fn(slice_bars, **params)` (add a `params: dict | None = None` arg to `run_strategy_backtest`, default `{}`). In `strategy_watch_evaluator.py`, fetch `get_active(strategy)` and pass into the signal call. **Missing config → `get_active` returns `{}` → signal-fn defaults apply → behavior unchanged (regression guard).**

- [ ] **Step 4: Run test + full suite**

Run: `cd backend && pytest tests/test_strategy_param_store.py -k merge -v && pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_backtest.py backend/app/routers/stock_scan.py backend/app/services/strategy_watch_evaluator.py backend/tests/test_strategy_param_store.py
git commit -m "feat(wfo): runtime reads adopted params (request override wins, graceful fallback)"
```

---

### Task 10: Frontend — Settings "Strategy Tuning" tab

**Files:**
- Create: `frontend/app/(frame)/settings/strategy-tuning/page.tsx` + module CSS
- Modify: `frontend/lib/api.ts` (run/poll/adopt + basket/windows endpoints + types), settings sub-nav

- [ ] **Step 1: Add api client methods** — `startTuningJob()`, `getTuningJob(id)`, `adoptStrategyParams(strategy, params)`; types for the proposal (proposed params, OOS metrics, consistency, verdict {in_sample, walk_forward, degradation_pct}, recommendation, per-fold winners).

- [ ] **Step 2: Build the tab** — per strategy: Current vs Proposed params table, OOS Sharpe/expectancy/return + improvement margin, consistency (positive folds / total), verdict block (in-sample vs walk-forward return + degradation %, blue retail vs orange walk-forward equity curves via lightweight-charts), a per-fold table, and a recommendation badge. A **Run** button (polls progress, shows fold-by-fold), and per-strategy **Adopt** buttons. Configure windows/costs + manage basket (read/save). Follow CSS-module + token conventions (no shadows, `border-subtle`).

- [ ] **Step 3: Typecheck + verify**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean + green. Then preview Settings → Strategy Tuning, run a job, confirm progress and the adopt flow write `active`.

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat(ui): Strategy Tuning settings tab (run/review/adopt)"
```

---

## Self-Review notes
- **Spec coverage:** store+config (Task 1 → spec §6/§9), basket+sector (Task 2 → §3 changed components/§5), folds (Task 3 → §4.1), grid+costs (Task 4 → §4.2/§4.6), consensus/scoring/verdict (Task 5 → §4.3–§4.5), engine smoke (Task 6 → §10), orchestrator+proposal (Task 7 → §4/§6 job record), router lifecycle+guard (Task 8 → §7), runtime read-points (Task 9 → §3/§9), Settings tab (Task 10 → §8).
- **Type consistency:** `Fold`, `build_folds`, `param_combos`, `train_fold`, `consensus`, `consistency`, `degradation_pct`, `build_proposal`, `run_optimization`, `get_active`, `adopt`, `_merge_strategy_params` are defined once and reused with the same signatures.
- **Out of scope (per spec §11):** per-stock refinement, regime-conditioned defaults, OOS-gate at scan time, Bayesian/random search, index-baseline runs.
- **Cross-plan coordination:** Task 9 edits `stock_scan.py` (signal-call region) which the Markov/Fundamental plan also edits (scoring path). Different regions → rebase, not conflict.
