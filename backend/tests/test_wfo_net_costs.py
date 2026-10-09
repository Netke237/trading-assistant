"""TRADING-REVIEW-PHASE-C T4 (review M1): WFO selects and scores folds net of
per-trade costs.

Before T4, `train_fold` ranked combos on a gross (commission=0) Sharpe, and the
optimizer then subtracted one flat round trip ((fee+slippage)x2) from each
fold-window return, however many trades the window made. Now both the train
grid search and the OOS run pass `commission = fee_pct + slippage_pct` (per
leg, the same per-leg cost the live Step-6 gate uses), and the window returns
are read as already net.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.services.strategy_backtest as sb
import app.services.strategy_param_optimizer as optimizer
import app.services.walk_forward as wf
from app.services.strategy_backtest import BacktestResult


FOLD = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))


def _bars(n: int = 400, start: date = date(2020, 1, 1)) -> list[dict]:
    bars = [{"time": (start + timedelta(days=i)).isoformat(), "open": 100.0, "high": 100.0,
             "low": 100.0, "close": 100.0, "volume": 1000} for i in range(n)]
    wf.precompute_bar_dates(bars)
    return bars


def _result(n_trades: int = 3, total_return_pct: float = 1.0) -> BacktestResult:
    return BacktestResult(strategy="fake", direction="Bullish", n_trades=n_trades, win_rate=0.5,
                          total_return_pct=total_return_pct, max_drawdown_pct=-1.0,
                          expectancy=0.1, sharpe=0.5, confidence=None, passes_gate=False,
                          summary_text="")


@pytest.mark.parametrize("costs, expected", [
    ({"fee_pct": 0.0007, "slippage_pct": 0.0005}, 0.0012),
    ({}, 0.002),  # the optimizer's own defaults: 0.001 + 0.001
])
def test_train_fold_passes_per_leg_commission(monkeypatch, costs, expected):
    seen: list[float | None] = []

    def recorder(bars, *, strategy, direction, params=None, entry_start=None, **kwargs):
        seen.append(kwargs.get("commission"))
        return _result()

    monkeypatch.setattr(wf, "run_strategy_backtest", recorder)
    winner, _ = wf.train_fold("fake", "Bullish", {"A": _bars(), "B": _bars()}, FOLD,
                              {"p": [1, 2]}, costs)
    assert winner
    assert seen and all(c == pytest.approx(expected) for c in seen), seen


@pytest.mark.parametrize("costs, expected", [
    ({"fee_pct": 0.0007, "slippage_pct": 0.0005}, 0.0012),
    ({}, 0.002),
])
def test_oos_call_passes_per_leg_commission(monkeypatch, costs, expected):
    monkeypatch.setattr(optimizer, "train_fold",
                        lambda *args: ({"p": 1}, {"A": _result()}))
    seen: list[float | None] = []

    def recorder(bars, *, strategy, direction, params=None, entry_start=None, **kwargs):
        seen.append(kwargs.get("commission"))
        return _result()

    monkeypatch.setattr(sb, "run_strategy_backtest", recorder)
    proposal = optimizer._optimize_strategy_sync(
        "fake", "Bullish", {"A": _bars(), "B": _bars()}, [FOLD], {"p": [1]}, costs,
        min_trades=1, min_consistency=0.0,
    )
    assert proposal is not None
    assert seen and all(c == pytest.approx(expected) for c in seen), seen


def _engine_like_backtest(bars, *, strategy, direction, params=None, entry_start=None,
                          commission: float = 0.0, **kwargs):
    """Stand-in that charges `commission` per leg on every trade, as backtesting.py
    does, and makes every trade gross-flat (0% before costs). `params['turnover']`
    is the number of trades the window makes."""
    n = int((params or {})["turnover"])
    per_trade = (1.0 - commission) / (1.0 + commission)  # one entry leg + one exit leg
    total = (per_trade ** n - 1.0) * 100.0
    return _result(n_trades=n, total_return_pct=total)


def _oos_total_return(monkeypatch, turnover: int, costs: dict) -> dict:
    winner = {"turnover": turnover}
    # IS results come from train_fold; keep them engine-like too, net of the same cost.
    is_res = _engine_like_backtest(None, strategy="fake", direction="Bullish", params=winner,
                                   commission=costs["fee_pct"] + costs["slippage_pct"])
    monkeypatch.setattr(optimizer, "train_fold", lambda *args: (winner, {"A": is_res}))
    monkeypatch.setattr(sb, "run_strategy_backtest", _engine_like_backtest)
    proposal = optimizer._optimize_strategy_sync(
        "fake", "Bullish", {"A": _bars()}, [FOLD], {"turnover": [turnover]}, costs,
        min_trades=1, min_consistency=0.0,
    )
    assert proposal is not None
    return {"oos": proposal["oos_metrics"]["total_return"],
            "is": proposal["verdict"]["in_sample_return"], "is_res": is_res.total_return_pct}


def test_net_cost_scales_with_trade_count(monkeypatch):
    """Identical gross per-trade returns (flat): the 10-trade combo must come out
    lower than the 1-trade combo by about 9 extra round trips, not by zero (the old
    one-round-trip-per-window charge hit both windows identically)."""
    costs = {"fee_pct": 0.001, "slippage_pct": 0.001}
    one_round_trip_pct = (costs["fee_pct"] + costs["slippage_pct"]) * 2 * 100.0  # 0.4
    high = _oos_total_return(monkeypatch, 10, costs)
    low = _oos_total_return(monkeypatch, 1, costs)
    assert low["oos"] - high["oos"] > one_round_trip_pct
    # The window return is already net: read straight through, no second charge.
    assert high["is"] == pytest.approx(high["is_res"])
    assert low["is"] == pytest.approx(low["is_res"])
