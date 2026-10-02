"""Unit tests for strategy_param_optimizer.py — fold loop cost and correctness (M11)."""
from datetime import date, timedelta


def _synth_bars(n=400, start=date(2020, 1, 1)):
    bars, price, d = [], 50.0, start
    for i in range(n):
        price = price * 1.002 + (0.5 if i % 10 == 0 else -0.2)
        bars.append({
            "time": d.isoformat(),
            "open": price * 0.998, "high": price * 1.01,
            "low":  price * 0.99,  "close": price, "volume": 1000 + i,
        })
        d += timedelta(days=1)
    return bars


def test_optimize_strategy_sync_does_not_rerun_backtest_for_is_return(monkeypatch):
    """M11 regression: _optimize_strategy_sync must not call run_strategy_backtest a
    second time for the winning combo's IS return — train_fold's own grid-search run
    must be reused instead.

    Uses a stubbed run_strategy_backtest (patched at both call sites: walk_forward's
    module-level import used by train_fold, and strategy_backtest's own module
    attribute, which _optimize_strategy_sync re-imports fresh for its OOS call) so
    the test exercises the actual call-count logic under test, independent of
    whether the real strategy engines fire trades on synthetic bars.
    """
    from app.services.strategy_backtest import BacktestResult
    from app.services.strategy_param_optimizer import _optimize_strategy_sync
    from app.services.walk_forward import build_folds
    import app.services.walk_forward as wf_module
    import app.services.strategy_backtest as sb_module

    call_count = {"n": 0}

    def fake_backtest(bars, *, strategy, direction, params=None, min_trades=10, min_win_rate=0.0, **kwargs):
        call_count["n"] += 1
        return BacktestResult(
            strategy=strategy, direction=direction, n_trades=15, win_rate=0.6,
            total_return_pct=10.0, max_drawdown_pct=-5.0, expectancy=0.4,
            sharpe=1.0, confidence=70, passes_gate=True, summary_text="ok",
        )

    monkeypatch.setattr(wf_module, "run_strategy_backtest", fake_backtest)
    monkeypatch.setattr(sb_module, "run_strategy_backtest", fake_backtest)

    bars = _synth_bars(400)
    basket_bars = {"AAPL": bars}
    # calendar-day synthetic bars; the warm-up path is covered on trading-day bars in test_walk_forward_warmup.py
    folds = build_folds(date(2020, 1, 1), date(2021, 1, 1), train_months=6, test_months=4)
    assert folds, "fixture must produce at least one fold"

    _optimize_strategy_sync(
        "pullback_ema", "Bullish", basket_bars, folds[:1],
        search_space={"ema_period": [20]},  # single combo: 1 call expected for IS, not 2
        costs={"fee_pct": 0.001, "slippage_pct": 0.001},
        min_trades=1, min_consistency=0.0,
    )

    # 1 combo x 1 symbol for train_fold's grid search + 1 symbol for the OOS window.
    # Before the fix this would be 3 (train_fold + duplicate IS re-run + OOS).
    assert call_count["n"] == 2, (
        f"Expected exactly 2 run_strategy_backtest calls (train_fold's grid search + "
        f"OOS), got {call_count['n']} — IS return must reuse train_fold's result, not "
        f"re-run the backtest"
    )
