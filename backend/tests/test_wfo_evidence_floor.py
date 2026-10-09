"""TRADING-REVIEW-PHASE-C T5 (review M2, decision D4): the WFO evidence floor is
pooled across the basket.

Before T5, `oos_metrics["n_trades"]` was the per-symbol AVERAGE of OOS trades
(total / contributing symbols), and `build_proposal` compared that average with
`min_trades` (20). The best strategy averaged about 9.6 per symbol, so no
proposal could ever be eligible. Now `n_trades` is the pooled OOS trade count,
the old average survives as `n_trades_per_symbol`, `n_symbols` counts the
contributing symbols, and eligibility also needs `n_symbols >= min_symbols`
(`optimization.min_symbols`, 3 by default).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

import app.services.strategy_backtest as sb
import app.services.strategy_param_optimizer as optimizer
import app.services.walk_forward as wf
from app.services.strategy_backtest import BacktestResult


FOLD = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
REPO_CFG = Path(__file__).resolve().parents[1] / "config" / "strategy_params.yaml"


def _bars(n: int = 400, start: date = date(2020, 1, 1)) -> list[dict]:
    bars = [{"time": (start + timedelta(days=i)).isoformat(), "open": 100.0, "high": 100.0,
             "low": 100.0, "close": 100.0, "volume": 1000} for i in range(n)]
    wf.precompute_bar_dates(bars)
    return bars


def _result(n_trades: int) -> BacktestResult:
    return BacktestResult(strategy="fake", direction="Bullish", n_trades=n_trades, win_rate=0.5,
                          total_return_pct=1.0, max_drawdown_pct=-1.0, expectancy=0.1,
                          sharpe=0.5, confidence=None, passes_gate=False, summary_text="")


def _proposal(n_trades: int, n_symbols: int) -> dict:
    return optimizer.build_proposal(
        strategy="pullback_ema",
        direction="Bullish",
        fold_winners=[{"ema_period": 20}, {"ema_period": 20}],
        fold_test_returns=[1.0, 2.0],  # consistency 1.0 >= min_consistency
        in_sample_return=2.0,
        walk_forward_return=1.5,
        oos_metrics={"sharpe": 0.4, "expectancy": 0.1, "win_rate": 0.5, "total_return": 1.5,
                     "max_drawdown": -2.0, "n_trades": n_trades, "n_symbols": n_symbols},
        min_trades=20,
        min_symbols=3,
        min_consistency=0.5,
    )


def test_too_few_symbols_is_not_eligible():
    assert _proposal(30, 2)["eligible"] is False


def test_enough_pooled_trades_and_symbols_is_eligible():
    assert _proposal(30, 3)["eligible"] is True


def test_too_few_pooled_trades_is_not_eligible():
    assert _proposal(19, 5)["eligible"] is False


def test_oos_n_trades_is_pooled_across_the_basket(monkeypatch):
    """3 symbols x 4 OOS trades: pooled 12, per-symbol 4, 3 symbols."""
    basket = {"A": _bars(), "B": _bars(), "C": _bars()}
    monkeypatch.setattr(optimizer, "train_fold",
                        lambda *args: ({"p": 1}, {sym: _result(4) for sym in basket}))
    monkeypatch.setattr(sb, "run_strategy_backtest", lambda bars, **kwargs: _result(4))
    proposal = optimizer._optimize_strategy_sync(
        "fake", "Bullish", basket, [FOLD], {"p": [1]}, {},
        min_trades=1, min_consistency=0.0,
    )
    assert proposal is not None
    oos = proposal["oos_metrics"]
    assert oos["n_trades"] == 12
    assert oos["n_trades_per_symbol"] == 4
    assert oos["n_symbols"] == 3


@pytest.mark.parametrize("opt_yaml, expected", [
    ("optimization:\n  min_trades: 20\n  min_consistency: 0.5\n  min_symbols: 5\n", 5),
    ("optimization:\n  min_trades: 20\n  min_consistency: 0.5\n", 3),
])
def test_min_symbols_is_read_from_config_with_default_3(tmp_path, monkeypatch, opt_yaml, expected):
    import app.routers.strategy_tuning as rt
    import app.services.strategy_param_store as store

    cfg_path = tmp_path / "strategy_params.yaml"
    cfg_path.write_text(
        "strategies:\n  pullback_ema: {}\nbasket:\n  symbols: [AAA, BBB, CCC]\n" + opt_yaml,
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "CFG", cfg_path)
    store._CACHE = None
    captured: dict = {}

    async def _capture(*args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(optimizer, "run_optimization", _capture)
    monkeypatch.setattr(rt, "_JOBS", {"job": {"status": "running"}})
    asyncio.run(rt._run_optimization_job("job"))
    assert rt._JOBS["job"]["status"] == "completed", rt._JOBS["job"]
    assert captured["min_symbols"] == expected

    # The shipped config carries the key explicitly.
    shipped = yaml.safe_load(REPO_CFG.read_text(encoding="utf-8"))
    assert shipped["optimization"]["min_symbols"] == 3
