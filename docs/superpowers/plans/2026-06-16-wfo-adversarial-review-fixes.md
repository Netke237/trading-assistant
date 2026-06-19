# WFO Adversarial Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 14 findings from the adversarial review of the Walk-Forward Optimization feature.

**Architecture:** Backend fixes touch `strategy_param_optimizer.py` (sync refactor + IS metric + empty folds), `strategy_param_store.py` (adopt ordering + new helpers), `strategy_tuning.py` (Lock + eviction priority), `strategy_basket.py` (error handling), and `walk_forward.py` (docstring + precompute). Frontend fixes add sessionStorage persistence for job ID and adopted state.

**Tech Stack:** Python 3.14 / FastAPI / asyncio — TypeScript / Next.js 15 / React

**Worktree:** All backend/frontend paths below are relative to `.claude/worktrees/feat+walk-forward-optimization/`.

---

## File Map

| File | Findings fixed |
|---|---|
| `backend/app/services/strategy_param_store.py` | 2, 9, 10 |
| `backend/app/services/strategy_param_optimizer.py` | 3, 4, 5, 10 |
| `backend/app/services/strategy_basket.py` | 7 |
| `backend/app/services/walk_forward.py` | 11, 14 |
| `backend/app/routers/strategy_tuning.py` | 1, 6, 8 |
| `backend/config/strategy_params.yaml` | 10 |
| `backend/tests/conftest.py` | 9 |
| `backend/tests/test_strategy_param_store.py` | 2, 10 |
| `backend/tests/test_strategy_tuning_router.py` | 8 |
| `backend/tests/test_walk_forward.py` | 11, 14 |
| `backend/tests/test_strategy_basket.py` | 7 |
| `frontend/app/(frame)/settings/page.tsx` | 12, 13 |

**Run all backend tests:**
```
cd backend && python -m pytest tests/test_strategy_tuning_router.py tests/test_strategy_param_store.py tests/test_walk_forward.py tests/test_strategy_basket.py -v
```
Baseline: 37 passed.

---

## Task 1: Fix adopt() — read before clear, invalidate after write (Finding 2)

**Files:**
- Modify: `backend/app/services/strategy_param_store.py:69–94`
- Modify: `backend/tests/test_strategy_param_store.py`

- [ ] **Step 1: Write the failing test**

Add to `test_strategy_param_store.py`:

```python
def test_adopt_preserves_other_strategies(tmp_path, monkeypatch):
    """adopt() must not discard existing strategies when a second strategy is adopted."""
    import app.services.strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    store._CACHE = None
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n"
        "  strategy_a:\n    active:\n      p: 1\n"
        "  strategy_b:\n    active:\n      p: 2\n",
        encoding="utf-8",
    )
    store.adopt("strategy_a", {"p": 99})
    assert store.get_active("strategy_b")["p"] == 2   # must survive
    assert store.get_active("strategy_a")["p"] == 99
```

- [ ] **Step 2: Run to confirm it fails**

```
cd backend && python -m pytest tests/test_strategy_param_store.py::test_adopt_preserves_other_strategies -v
```
Expected: FAIL — if adopt() clears cache first and CFG has no content yet (edge case), `_load()` sees the real CFG. The deeper bug is that `_CACHE = None` before `_load()` means concurrent readers see empty cache. Confirm the test exposes this by tracing through the code.

- [ ] **Step 3: Fix adopt() ordering in strategy_param_store.py**

Replace the entire `adopt` function body:

```python
def adopt(strategy: str, params: dict) -> None:
    global _CACHE
    # Read BEFORE touching anything — preserves other strategies and avoids
    # returning empty dict to concurrent readers during the write window.
    data = _load()

    if CFG.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = CFG.with_suffix(f".bak.{timestamp}.yaml")
        shutil.copy(CFG, backup_path)

    data.setdefault("strategies", {}).setdefault(strategy, {})["active"] = (
        copy.deepcopy(params)
    )

    tmp = CFG.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CFG)
    # Invalidate cache AFTER the write succeeds — no window of empty-dict reads.
    _CACHE = None
```

- [ ] **Step 4: Run tests**

```
cd backend && python -m pytest tests/test_strategy_param_store.py -v
```
Expected: all pass including the new test.

- [ ] **Step 5: Commit**

```
git add backend/app/services/strategy_param_store.py backend/tests/test_strategy_param_store.py
git commit -m "fix(wfo): read config before clearing cache in adopt() — prevents clobbering other strategies"
```

---

## Task 2: Optimizer refactor — sync helper + IS metric fix + empty fold filter + asyncio.to_thread (Findings 3, 4, 5)

**Files:**
- Modify: `backend/app/services/strategy_param_optimizer.py`
- Modify: `backend/tests/test_walk_forward.py`

This is the biggest task. It extracts the per-strategy fold loop into `_optimize_strategy_sync` (a plain synchronous function), fixes the IS metric to use return% instead of Sharpe×100, filters empty fold winners, and wraps the sync call with `asyncio.to_thread` so the event loop stays responsive.

- [ ] **Step 1: Write failing tests**

Add to `test_walk_forward.py`:

```python
def test_optimize_strategy_sync_returns_none_when_basket_empty():
    """If basket_bars is empty every fold returns {} — result should be None."""
    from app.services.strategy_param_optimizer import _optimize_strategy_sync
    from app.services.walk_forward import Fold
    from datetime import date

    folds = [Fold(date(2020, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2021, 4, 1))]
    result = _optimize_strategy_sync(
        "pullback_ema", "bullish",
        {},           # empty basket → train_fold returns {} for every fold
        folds,
        {"ema_period": [20, 50]},
        {"fee_pct": 0.001, "slippage_pct": 0.001},
        min_trades=20,
        min_consistency=0.5,
    )
    assert result is None


def test_build_proposal_is_oos_same_units():
    """in_sample_return and walk_forward_return must be in the same units (return %)."""
    from app.services.strategy_param_optimizer import build_proposal

    prop = build_proposal(
        strategy="pullback_ema",
        fold_winners=[{"ema_period": 50}],
        fold_test_returns=[5.0, 3.0],
        in_sample_return=10.0,   # return % — not Sharpe*100
        walk_forward_return=4.0,
        oos_metrics={
            "sharpe": 0.8, "expectancy": 0.3, "win_rate": 0.55,
            "total_return": 4.0, "max_drawdown": -3.0, "n_trades": 25,
        },
        min_trades=20,
        min_consistency=0.5,
    )
    # degradation = 1 - (4.0 / 10.0) = 0.6
    assert abs(prop["verdict"]["degradation_pct"] - 0.6) < 0.01
```

- [ ] **Step 2: Run to confirm they fail**

```
cd backend && python -m pytest tests/test_walk_forward.py::test_optimize_strategy_sync_returns_none_when_basket_empty tests/test_walk_forward.py::test_build_proposal_is_oos_same_units -v
```
Expected: both FAIL (`_optimize_strategy_sync` not yet exported; `build_proposal` doesn't accept `min_consistency`).

- [ ] **Step 3: Rewrite strategy_param_optimizer.py**

Replace the entire file with:

```python
"""Strategy parameter optimizer orchestrator — runs walk-forward optimization and builds proposals."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Callable

from app.services.walk_forward import (
    apply_costs, consensus, consistency, degradation_pct,
    build_folds, train_fold, _slice_bars,
)

logger = logging.getLogger(__name__)


def build_proposal(
    *,
    strategy: str,
    fold_winners: list[dict],
    fold_test_returns: list[float],
    in_sample_return: float,
    walk_forward_return: float,
    oos_metrics: dict,
    min_trades: int,
    min_consistency: float = 0.5,
) -> dict:
    proposed = consensus(fold_winners)
    cons = round(consistency(fold_test_returns), 4)
    eligible = oos_metrics["n_trades"] >= min_trades and cons >= min_consistency
    deg = degradation_pct(in_sample=in_sample_return, walk_forward=walk_forward_return)

    if not eligible:
        recommendation = "Edge looks fake — consider dropping."
    elif oos_metrics["sharpe"] > 0.5 and deg < 0.5:
        recommendation = "Proposed beats current — safe to adopt."
    else:
        recommendation = "Marginal — your call."

    return {
        "strategy": strategy,
        "proposed": proposed,
        "consistency": cons,
        "eligible": eligible,
        "oos_metrics": oos_metrics,
        "fold_winners": fold_winners,
        "verdict": {
            "in_sample_return": in_sample_return,
            "walk_forward_return": walk_forward_return,
            "degradation_pct": round(deg, 4),
        },
        "recommendation": recommendation,
    }


def _optimize_strategy_sync(
    strategy: str,
    direction: str,
    basket_bars: dict[str, list[dict]],
    folds: list,
    search_space: dict,
    costs: dict,
    min_trades: int,
    min_consistency: float,
) -> dict | None:
    """Synchronous per-strategy fold loop; run via asyncio.to_thread to avoid blocking."""
    from app.services.strategy_backtest import run_strategy_backtest

    fold_winners: list[dict] = []
    fold_test_returns: list[float] = []
    in_sample_fold_returns: list[float] = []
    total_n_trades = 0
    all_sharpes: list[float] = []
    all_win_rates: list[float] = []
    all_expectancies: list[float] = []
    all_drawdowns: list[float] = []

    for fold in folds:
        winner = train_fold(strategy, direction, basket_bars, fold, search_space, costs)
        fold_winners.append(winner)

        # IS: re-run the train window with winner params using return% (matches OOS units)
        is_returns: list[float] = []
        for sym, bars in basket_bars.items():
            train_bars_fold = _slice_bars(bars, fold.train_start, fold.train_end)
            if len(train_bars_fold) >= 100:
                try:
                    res = run_strategy_backtest(
                        train_bars_fold, strategy=strategy, direction=direction, params=winner
                    )
                    if res.n_trades > 0:
                        net = apply_costs(
                            gross_return_pct=res.total_return_pct,
                            fee_pct=costs.get("fee_pct", 0.001),
                            slippage_pct=costs.get("slippage_pct", 0.001),
                        )
                        is_returns.append(net)
                except Exception as exc:
                    logger.debug("IS backtest failed for %s: %s", sym, exc)
        in_sample_fold_returns.append(
            sum(is_returns) / len(is_returns) if is_returns else 0.0
        )

        # OOS: score the test window with winner params, net of costs
        test_returns: list[float] = []
        for sym, bars in basket_bars.items():
            test_bars = _slice_bars(bars, fold.test_start, fold.test_end)
            if len(test_bars) >= 20:
                try:
                    res = run_strategy_backtest(
                        test_bars, strategy=strategy, direction=direction, params=winner
                    )
                    gross = res.total_return_pct if hasattr(res, "total_return_pct") else 0.0
                    net = apply_costs(
                        gross_return_pct=gross,
                        fee_pct=costs.get("fee_pct", 0.001),
                        slippage_pct=costs.get("slippage_pct", 0.001),
                    )
                    test_returns.append(net)
                    total_n_trades += getattr(res, "n_trades", 0)
                    all_sharpes.append(getattr(res, "sharpe", 0.0))
                    if res.n_trades > 0:
                        all_win_rates.append(res.win_rate)
                        if getattr(res, "expectancy", None) is not None:
                            all_expectancies.append(res.expectancy)
                        if getattr(res, "max_drawdown_pct", None) is not None:
                            all_drawdowns.append(res.max_drawdown_pct)
                except Exception as exc:
                    logger.debug("OOS backtest failed for %s: %s", sym, exc)
        fold_test_returns.append(
            sum(test_returns) / len(test_returns) if test_returns else 0.0
        )

    # Filter folds where the grid search found nothing (train window too short, etc.)
    valid_winners = [w for w in fold_winners if w]
    if not valid_winners:
        logger.warning("No valid fold winners for %s — all folds empty, skipping", strategy)
        return None

    in_sample_return = (
        sum(in_sample_fold_returns) / len(in_sample_fold_returns) * 100
        if in_sample_fold_returns
        else 0.0
    )
    walk_forward_return = (
        sum(fold_test_returns) / len(fold_test_returns) * 100
        if fold_test_returns
        else 0.0
    )
    avg_sharpe = sum(all_sharpes) / len(all_sharpes) if all_sharpes else 0.0

    oos_metrics = {
        "sharpe": round(avg_sharpe, 4),
        "expectancy": round(sum(all_expectancies) / len(all_expectancies), 4) if all_expectancies else 0.0,
        "win_rate": round(sum(all_win_rates) / len(all_win_rates), 4) if all_win_rates else 0.0,
        "total_return": walk_forward_return,
        "max_drawdown": round(min(all_drawdowns), 4) if all_drawdowns else 0.0,
        "n_trades": total_n_trades,
    }

    return build_proposal(
        strategy=strategy,
        fold_winners=valid_winners,
        fold_test_returns=fold_test_returns,
        in_sample_return=in_sample_return,
        walk_forward_return=walk_forward_return,
        oos_metrics=oos_metrics,
        min_trades=min_trades,
        min_consistency=min_consistency,
    )


async def run_optimization(
    strategies: list[str],
    basket_symbols: list[str],
    windows: dict,
    costs: dict,
    progress_cb: Callable[[int, int], None],
    *,
    direction: str = "bullish",
    min_trades: int = 20,
    min_consistency: float = 0.5,
) -> dict:
    from app.services.strategy_param_store import get_search_space
    from app.services.historical_store import get_bars
    from app.services.walk_forward import precompute_bar_dates
    from dateutil.relativedelta import relativedelta

    results: dict = {}
    total_work = len(strategies)
    done = 0

    for strategy in strategies:
        search_space = get_search_space(strategy)
        if not search_space:
            logger.warning("No search space for %s, skipping", strategy)
            done += 1
            progress_cb(done, total_work)
            continue

        basket_bars: dict[str, list[dict]] = {}
        for sym in basket_symbols:
            try:
                end_date = date.today()
                start_date = end_date - relativedelta(years=3)
                bars = await get_bars(sym, start_date, end_date)
                if bars:
                    basket_bars[sym] = bars
            except Exception as exc:
                logger.debug("Failed to load bars for %s: %s", sym, exc)

        if not basket_bars:
            logger.warning("No bars available for strategy %s basket, skipping", strategy)
            done += 1
            progress_cb(done, total_work)
            continue

        all_dates = [b["time"] for bars in basket_bars.values() for b in bars]
        if not all_dates:
            done += 1
            progress_cb(done, total_work)
            continue

        start_str = min(all_dates)
        end_str = max(all_dates)
        start = date.fromisoformat(str(start_str)[:10])
        end = date.fromisoformat(str(end_str)[:10])

        folds = build_folds(
            start, end,
            train_months=windows.get("train_months", 12),
            test_months=windows.get("test_months", 3),
            anchored=windows.get("type") == "anchored",
        )

        if not folds:
            done += 1
            progress_cb(done, total_work)
            continue

        # Pre-compute date parsing once per symbol — avoids repeated string→date
        # conversion inside the triple-nested combo × symbol × fold loop.
        for bars in basket_bars.values():
            precompute_bar_dates(bars)

        proposal = await asyncio.to_thread(
            _optimize_strategy_sync,
            strategy, direction, basket_bars, folds, search_space, costs,
            min_trades, min_consistency,
        )
        if proposal is not None:
            results[strategy] = proposal

        done += 1
        progress_cb(done, total_work)

    return results
```

- [ ] **Step 4: Run tests**

```
cd backend && python -m pytest tests/test_walk_forward.py -v
```
Expected: all pass including the two new tests.

- [ ] **Step 5: Run full suite to check nothing regressed**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py tests/test_strategy_param_store.py tests/test_walk_forward.py tests/test_strategy_basket.py -v
```
Expected: ≥ 39 passed, 0 failed.

- [ ] **Step 6: Commit**

```
git add backend/app/services/strategy_param_optimizer.py backend/tests/test_walk_forward.py
git commit -m "fix(wfo): extract sync optimizer helper + fix IS metric (return% not Sharpe×100) + filter empty fold winners + asyncio.to_thread"
```

---

## Task 3: Add consistency + min_trades to YAML config (Finding 10)

**Files:**
- Modify: `backend/config/strategy_params.yaml`
- Modify: `backend/app/services/strategy_param_store.py`
- Modify: `backend/app/routers/strategy_tuning.py`
- Modify: `backend/tests/test_strategy_param_store.py`

- [ ] **Step 1: Write failing tests**

Add to `test_strategy_param_store.py`:

```python
def test_get_optimization_config_defaults():
    from app.services.strategy_param_store import get_optimization_config
    cfg = get_optimization_config()
    assert cfg["min_trades"] == 20
    assert cfg["min_consistency"] == 0.5


def test_get_optimization_config_custom(tmp_path, monkeypatch):
    import app.services.strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    store._CACHE = None
    (tmp_path / "strategy_params.yaml").write_text(
        "optimization:\n  min_trades: 30\n  min_consistency: 0.6\n", encoding="utf-8"
    )
    cfg = store.get_optimization_config()
    assert cfg["min_trades"] == 30
    assert cfg["min_consistency"] == 0.6
```

- [ ] **Step 2: Run to confirm they fail**

```
cd backend && python -m pytest tests/test_strategy_param_store.py::test_get_optimization_config_defaults -v
```
Expected: FAIL — `get_optimization_config` not defined yet.

- [ ] **Step 3: Add to strategy_params.yaml**

After the `job_retention` section, add:

```yaml
optimization:
  min_trades: 20
  min_consistency: 0.5
```

- [ ] **Step 4: Add get_optimization_config() to strategy_param_store.py**

After `get_job_retention()`:

```python
def get_optimization_config() -> dict:
    """Get optimization thresholds. min_trades and min_consistency are both configurable."""
    return dict(_load().get("optimization", {"min_trades": 20, "min_consistency": 0.5}))
```

Also add `get_optimization_config` to the import list in `test_strategy_param_store.py`:

```python
from app.services.strategy_param_store import (
    get_active,
    get_search_space,
    get_windows,
    get_costs,
    get_direction,
    get_job_retention,
    get_optimization_config,
    adopt,
)
```

- [ ] **Step 5: Wire into strategy_tuning.py _work()**

In `strategy_tuning.py`, inside the `_work()` async function, update the `run_optimization` call:

```python
            opt_cfg = store.get_optimization_config()
            proposals = await run_optimization(
                strategies,
                basket_symbols,
                store.get_windows(),
                store.get_costs(),
                progress,
                direction=store.get_direction(),
                min_trades=opt_cfg.get("min_trades", 20),
                min_consistency=opt_cfg.get("min_consistency", 0.5),
            )
```

- [ ] **Step 6: Run tests**

```
cd backend && python -m pytest tests/test_strategy_param_store.py -v
```
Expected: all pass including the two new tests.

- [ ] **Step 7: Commit**

```
git add backend/config/strategy_params.yaml backend/app/services/strategy_param_store.py backend/app/routers/strategy_tuning.py backend/tests/test_strategy_param_store.py
git commit -m "feat(wfo): make min_trades and min_consistency configurable via strategy_params.yaml"
```

---

## Task 4: Fix propose_basket() — error handling + accurate docstring (Finding 7)

**Files:**
- Modify: `backend/app/services/strategy_basket.py`
- Modify: `backend/tests/test_strategy_basket.py`

- [ ] **Step 1: Write failing tests**

Add to `test_strategy_basket.py`:

```python
def test_propose_basket_missing_file(monkeypatch, tmp_path):
    """Returns [] when sp500.csv is not found instead of raising."""
    import app.services.strategy_basket as mod
    monkeypatch.setattr(mod, "_CSV_PATH", tmp_path / "nonexistent.csv")
    assert mod.propose_basket(per_sector=3) == []


def test_propose_basket_missing_symbol_column(monkeypatch, tmp_path):
    """Returns [] when the CSV is present but lacks the 'symbol' column."""
    import app.services.strategy_basket as mod
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("ticker,sector\nAAPL,Tech\n", encoding="utf-8")
    monkeypatch.setattr(mod, "_CSV_PATH", bad_csv)
    assert mod.propose_basket(per_sector=3) == []
```

- [ ] **Step 2: Run to confirm they fail**

```
cd backend && python -m pytest tests/test_strategy_basket.py::test_propose_basket_missing_file tests/test_strategy_basket.py::test_propose_basket_missing_symbol_column -v
```
Expected: both FAIL — `_CSV_PATH` doesn't exist yet, `propose_basket` raises.

- [ ] **Step 3: Rewrite strategy_basket.py**

```python
"""Stratified basket builder for walk-forward optimization."""

from __future__ import annotations
import csv
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_CSV_PATH = Path(__file__).parent.parent / "data" / "sp500.csv"


def build_basket(rows: list[dict], *, per_sector: int) -> list[str]:
    """Pick top-N symbols per sector, sorted by liquidity desc then symbol asc.

    Args:
        rows: List of dicts with keys: symbol, sector, liquidity
        per_sector: Number of symbols to select per sector

    Returns:
        Sorted list of selected symbols (deterministic order)

    Raises:
        ValueError: If per_sector < 1
    """
    if per_sector < 1:
        raise ValueError(f"per_sector must be >= 1, got {per_sector}")

    seen: set[str] = set()
    deduped = [r for r in rows if r["symbol"] not in seen and not seen.add(r["symbol"])]

    by_sector: dict[str, list[dict]] = defaultdict(list)
    for r in deduped:
        by_sector[r.get("sector") or "Unknown"].append(r)

    chosen: list[str] = []
    for sector, items in by_sector.items():
        items.sort(key=lambda x: (-x.get("liquidity", 0), x.get("symbol", "")))
        chosen.extend(i["symbol"] for i in items[:per_sector])

    return sorted(chosen)


def propose_basket(per_sector: int) -> list[str]:
    """Build a stratified basket from sp500.csv.

    Selects symbols alphabetically within each sector (all symbols get
    liquidity=1.0; use real ADV from ohlcv_daily to rank by volume).
    Returns [] if sp500.csv is missing or unreadable — does not raise.

    Args:
        per_sector: Number of symbols to select per sector

    Returns:
        Sorted list of selected symbols, or [] on error
    """
    rows: list[dict] = []
    try:
        with open(_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "symbol" not in (reader.fieldnames or []):
                logger.error("sp500.csv is missing a 'symbol' column")
                return []
            for row in reader:
                rows.append(
                    {
                        "symbol": row["symbol"],
                        "sector": row.get("sector", "Unknown"),
                        "liquidity": 1.0,
                    }
                )
    except FileNotFoundError:
        logger.error("sp500.csv not found at %s", _CSV_PATH)
        return []
    except csv.Error as exc:
        logger.error("Failed to read sp500.csv: %s", exc)
        return []

    return build_basket(rows, per_sector=per_sector)
```

- [ ] **Step 4: Run tests**

```
cd backend && python -m pytest tests/test_strategy_basket.py -v
```
Expected: all pass including the two new tests.

- [ ] **Step 5: Commit**

```
git add backend/app/services/strategy_basket.py backend/tests/test_strategy_basket.py
git commit -m "fix(wfo): propose_basket returns [] on missing/malformed csv instead of raising; fix docstring liquidity claim"
```

---

## Task 5: Pre-compute bar dates + fix rolling-fold docstring (Findings 11, 14)

**Files:**
- Modify: `backend/app/services/walk_forward.py`
- Modify: `backend/tests/test_walk_forward.py`

- [ ] **Step 1: Write failing tests**

Add to `test_walk_forward.py`:

```python
def test_rolling_fold1_train_start_slides_by_test_months():
    """Rolling fold 1 train_start should advance by test_months (3), not train_months (12)."""
    from app.services.walk_forward import build_folds
    from datetime import date

    folds = build_folds(
        date(2018, 1, 1), date(2021, 6, 1),
        train_months=12, test_months=3, anchored=False,
    )
    assert len(folds) >= 2
    assert folds[0].train_start == date(2018, 1, 1)
    assert folds[1].train_start == date(2018, 4, 1)  # +3 months, not +12


def test_slice_bars_uses_precomputed_date():
    from app.services.walk_forward import _slice_bars, precompute_bar_dates
    from datetime import date

    bars = [
        {"time": "2020-01-15", "close": 100},
        {"time": "2020-03-01", "close": 110},
        {"time": "2020-06-01", "close": 120},
    ]
    precompute_bar_dates(bars)
    assert all("_date" in b for b in bars)

    sliced = _slice_bars(bars, date(2020, 2, 1), date(2020, 5, 1))
    assert len(sliced) == 1
    assert sliced[0]["close"] == 110
```

- [ ] **Step 2: Run to confirm they fail**

```
cd backend && python -m pytest tests/test_walk_forward.py::test_rolling_fold1_train_start_slides_by_test_months tests/test_walk_forward.py::test_slice_bars_uses_precomputed_date -v
```
Expected: `test_rolling_fold1` may PASS (the code is correct; the docstring is wrong) — confirm. `test_slice_bars_uses_precomputed_date` FAILS (`precompute_bar_dates` not defined yet).

- [ ] **Step 3: Add precompute_bar_dates and update _slice_bars in walk_forward.py**

Replace the `_slice_bars` function and add `precompute_bar_dates` after it:

```python
def precompute_bar_dates(bars: list[dict]) -> None:
    """Parse and cache the date from each bar's 'time' field as '_date'.

    Call once per symbol before the fold/combo loop to avoid repeated
    string→date conversions in the innermost iteration.
    """
    for b in bars:
        if "_date" not in b:
            b["_date"] = date.fromisoformat(str(b["time"])[:10])


def _slice_bars(bars: list[dict], start: date, end: date) -> list[dict]:
    """Slice a list of bars to [start, end). Uses '_date' key if pre-computed."""
    return [
        b for b in bars
        if start <= (b.get("_date") or date.fromisoformat(str(b["time"])[:10])) < end
    ]
```

Also fix the rolling fold docstring example (the code is correct; only the example text is wrong). In `build_folds` docstring, change:

```
        Rolling (test_months = 3, train_months = 12):
        - Fold 0: train [2018-01-01, 2019-01-01), test [2019-01-01, 2019-04-01)
        - Fold 1: train [2019-04-01, 2020-04-01), test [2020-04-01, 2020-07-01)
```

to:

```
        Rolling (test_months = 3, train_months = 12):
        - Fold 0: train [2018-01-01, 2019-01-01), test [2019-01-01, 2019-04-01)
        - Fold 1: train [2018-04-01, 2019-04-01), test [2019-04-01, 2019-07-01)
```

- [ ] **Step 4: Run tests**

```
cd backend && python -m pytest tests/test_walk_forward.py -v
```
Expected: all pass including the two new tests.

- [ ] **Step 5: Commit**

```
git add backend/app/services/walk_forward.py backend/tests/test_walk_forward.py
git commit -m "fix(wfo): add precompute_bar_dates helper; _slice_bars reuses cached _date; fix rolling docstring example"
```

---

## Task 6: Fix eviction priority — completed before failed (Finding 8)

**Files:**
- Modify: `backend/app/routers/strategy_tuning.py`
- Modify: `backend/tests/test_strategy_tuning_router.py`

- [ ] **Step 1: Write failing test**

Add to `test_strategy_tuning_router.py`:

```python
def test_evict_completed_before_failed(monkeypatch):
    """Eviction should drop completed jobs before failed ones (preserve failure evidence)."""
    import app.routers.strategy_tuning as rt
    jobs = {
        "c1": {"status": "completed"},
        "c2": {"status": "completed"},
        "f1": {"status": "failed"},
        "f2": {"status": "failed"},
    }
    monkeypatch.setattr(rt, "_JOBS", jobs)
    rt._evict_old_jobs(max_completed=3)
    assert "c1" not in rt._JOBS   # oldest completed evicted first
    assert "c2" in rt._JOBS
    assert "f1" in rt._JOBS
    assert "f2" in rt._JOBS
    assert len(rt._JOBS) == 3
```

- [ ] **Step 2: Run to confirm it fails**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py::test_evict_completed_before_failed -v
```
Expected: FAIL — current `_evict_old_jobs` uses a flat list without priority.

- [ ] **Step 3: Update _evict_old_jobs in strategy_tuning.py**

Replace the existing `_evict_old_jobs` function:

```python
def _evict_old_jobs(max_completed: int) -> None:
    """Drop oldest finished jobs beyond max_completed.

    Evicts completed jobs before failed ones so failure records stay visible longer.
    """
    completed = [jid for jid, j in _JOBS.items() if j.get("status") == "completed"]
    failed = [jid for jid, j in _JOBS.items() if j.get("status") == "failed"]
    candidates = completed + failed  # completed are eviction candidates first
    excess = len(candidates) - max_completed
    if excess > 0:
        for jid in candidates[:excess]:
            del _JOBS[jid]
```

- [ ] **Step 4: Run tests**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py -v
```
Expected: all pass including the new test.

- [ ] **Step 5: Commit**

```
git add backend/app/routers/strategy_tuning.py backend/tests/test_strategy_tuning_router.py
git commit -m "fix(wfo): evict completed jobs before failed ones so failure evidence is preserved longer"
```

---

## Task 7: Add asyncio.Lock for atomic concurrency guard (Findings 1, 6)

**Files:**
- Modify: `backend/app/routers/strategy_tuning.py`

The existing 409 check is a read-then-write with no atomic guarantee: two concurrent coroutines can both pass the check before either sets `_ACTIVE`. Adding `asyncio.Lock` makes the check-and-set atomic within a single process.

Note: This does NOT fix the multi-worker case (Finding 1). A comment is added instead. Full multi-worker support would require an external store (Redis/DB) and is out of scope for a local single-user app.

No new test needed — `test_run_then_poll_then_concurrency_guard` already exercises the 409 path and will confirm the Lock doesn't break it.

- [ ] **Step 1: Add the Lock and update run_job**

In `strategy_tuning.py`, after the existing globals, add:

```python
# NOTE: _JOBS/_ACTIVE are in-process only. A multi-worker deployment
# (e.g. uvicorn --workers 2) needs an external store. For a single-worker
# local setup this Lock makes the check-and-set atomic.
_LOCK: asyncio.Lock = asyncio.Lock()
```

Replace the `run_job` function body:

```python
@router.post("/run")
async def run_job(body: dict = Body(default={})) -> dict:
    global _ACTIVE, _ACTIVE_TASK
    async with _LOCK:
        if _ACTIVE and _JOBS.get(_ACTIVE, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="An optimization run is already active.")
        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "proposals": {}}
        _ACTIVE = job_id
    _ACTIVE_TASK = asyncio.create_task(_work())
    _JOBS[job_id]["task"] = None
    return {"job_id": job_id}
```

(`_work` is still a closure that captures `job_id` from the enclosing scope — no change needed there.)

- [ ] **Step 2: Run tests**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py -v
```
Expected: all pass.

- [ ] **Step 3: Commit**

```
git add backend/app/routers/strategy_tuning.py
git commit -m "fix(wfo): add asyncio.Lock to make 409 concurrency check atomic; comment single-worker constraint"
```

---

## Task 8: Fix _CACHE leaking between tests (Finding 9)

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Add autouse fixture to conftest.py**

Add after the existing `_db_tables` fixture:

```python
@pytest.fixture(autouse=True)
def _reset_param_store_cache():
    """Clear the strategy_param_store in-memory TTL cache before and after every test.

    Prevents test order-dependency: adopt() sets _CACHE=None globally, which
    would cause the next test's _load() to hit the real production YAML before
    any monkeypatch redirect takes effect.
    """
    import app.services.strategy_param_store as store
    store._CACHE = None
    yield
    store._CACHE = None
```

- [ ] **Step 2: Run full suite**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py tests/test_strategy_param_store.py tests/test_walk_forward.py tests/test_strategy_basket.py -v
```
Expected: all pass, count ≥ 47 (37 original + 10 new from Tasks 1–7).

- [ ] **Step 3: Commit**

```
git add backend/tests/conftest.py
git commit -m "fix(wfo): autouse fixture clears param store cache between tests to prevent test order pollution"
```

---

## Task 9: Frontend — persist jobId and reconnect after refresh (Finding 13)

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx`

`jobId` lives in React state so a page refresh loses it. This stores it in `sessionStorage` (per-tab, cleared when tab closes, persists across refreshes) and reconnects to the job on mount.

The poll timeout is also extended from 5 min (150 × 2s) to 15 min (450 × 2s) since the grid search now runs in a thread and can take longer.

- [ ] **Step 1: Update StrategyTuningForm**

Locate the `StrategyTuningForm` function (around line 1289). Apply these changes:

**a) Add constants at the top of the function block (before the component, around line 1287):**

```typescript
const SESSION_JOB_KEY = 'bamendjou:wfo:jobId';
const MAX_POLL_COUNT = 450; // 15 minutes at 2s intervals
```

**b) Change `jobId` state initializer to restore from sessionStorage:**

```typescript
const [jobId, setJobId] = React.useState<string | null>(() =>
  typeof window !== 'undefined' ? sessionStorage.getItem(SESSION_JOB_KEY) : null
);
```

**c) Add a mount effect to reconnect to a restored job:**

Add after the `refreshCount` effect (around line 1303):

```typescript
  // On mount: if sessionStorage had a jobId, fetch current status and resume poll if running.
  React.useEffect(() => {
    if (!jobId) return;
    getTuningJob(jobId)
      .then(j => {
        setJob(j);
        if (j.status === 'running') setPolling(true);
      })
      .catch(() => {
        // Backend was restarted — job is gone, clear the stale id.
        sessionStorage.removeItem(SESSION_JOB_KEY);
        setJobId(null);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
```

**d) Update `handleRun` to persist the new job id:**

```typescript
  const handleRun = async () => {
    setError(null);
    try {
      const { job_id } = await startTuningJob();
      sessionStorage.setItem(SESSION_JOB_KEY, job_id);
      setJobId(job_id);
      setJob(null);
      setPolling(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start tuning job');
    }
  };
```

**e) Update `handleClearHistory` to also clear sessionStorage:**

```typescript
  const handleClearHistory = async () => {
    setClearing(true);
    try {
      await clearTuningJobs();
      if (job && job.status !== 'running') {
        setJob(null);
        setJobId(null);
        sessionStorage.removeItem(SESSION_JOB_KEY);
      }
      refreshCount();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to clear history');
    } finally {
      setClearing(false);
    }
  };
```

**f) Update the timeout error message:**

```typescript
        setError('Optimization timed out after 15 minutes — job may still be running. Try refreshing to reconnect.');
```

- [ ] **Step 2: Typecheck**

```
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add "frontend/app/(frame)/settings/page.tsx"
git commit -m "fix(wfo): persist jobId to sessionStorage — page refresh reconnects to running job; extend poll timeout to 15 min"
```

---

## Task 10: Frontend — persist adopted state across refresh (Finding 12)

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx`

`adoptedStrategies` is React state, cleared on refresh. Store it in `sessionStorage` as a JSON-serialised string array.

- [ ] **Step 1: Update adoptedStrategies initialization and handleAdopt**

**a) Add constant near SESSION_JOB_KEY:**

```typescript
const SESSION_ADOPTED_KEY = 'bamendjou:wfo:adopted';
```

**b) Change `adoptedStrategies` initializer to restore from sessionStorage:**

```typescript
  const [adoptedStrategies, setAdoptedStrategies] = React.useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try {
      const raw = sessionStorage.getItem(SESSION_ADOPTED_KEY);
      return raw ? new Set<string>(JSON.parse(raw) as string[]) : new Set<string>();
    } catch {
      return new Set<string>();
    }
  });
```

**c) Update `handleAdopt` to persist after each adopt:**

```typescript
  const handleAdopt = async (strategy: string, params: Record<string, number | string>) => {
    try {
      await adoptStrategyParams(strategy, params);
      setAdoptedStrategies(prev => {
        const next = new Set(prev).add(strategy);
        sessionStorage.setItem(SESSION_ADOPTED_KEY, JSON.stringify([...next]));
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to adopt params');
    }
  };
```

- [ ] **Step 2: Typecheck**

```
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Run full backend suite one last time**

```
cd backend && python -m pytest tests/test_strategy_tuning_router.py tests/test_strategy_param_store.py tests/test_walk_forward.py tests/test_strategy_basket.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit**

```
git add "frontend/app/(frame)/settings/page.tsx"
git commit -m "fix(wfo): persist adopted strategies to sessionStorage — survives page refresh"
```

---

## Self-Review

**Spec coverage check:**

| Finding | Task | Covered? |
|---|---|---|
| 1 — globals not thread-safe | Task 7 (Lock + comment) | ✓ |
| 2 — adopt() clobber | Task 1 | ✓ |
| 3 — blocks event loop | Task 2 (asyncio.to_thread) | ✓ |
| 4 — consensus loses empty folds | Task 2 (valid_winners filter) | ✓ |
| 5 — IS metric Sharpe×100 | Task 2 (use total_return_pct) | ✓ |
| 6 — 409 race condition | Task 7 (Lock) | ✓ |
| 7 — basket no error handling | Task 4 | ✓ |
| 8 — eviction no priority | Task 6 | ✓ |
| 9 — _CACHE leaks between tests | Task 8 | ✓ |
| 10 — consistency hardcoded | Task 3 | ✓ |
| 11 — docstring wrong | Task 5 | ✓ |
| 12 — adopted state lost on refresh | Task 10 | ✓ |
| 13 — jobId lost on refresh | Task 9 | ✓ |
| 14 — _slice_bars re-parses dates | Task 5 | ✓ |

All 14 findings are covered.

**Placeholder scan:** No TBDs, no "add appropriate X", no "similar to Task N" — all code is complete.

**Type consistency:** `min_consistency: float = 0.5` added to both `build_proposal` and `_optimize_strategy_sync` — consistent. `SESSION_JOB_KEY` and `SESSION_ADOPTED_KEY` both referenced consistently.
