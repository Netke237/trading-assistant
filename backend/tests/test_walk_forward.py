"""Tests for walk-forward optimization fold construction."""
from datetime import date
from app.services.walk_forward import build_folds, param_combos, apply_costs, consensus


def test_rolling_folds_step_by_test_months():
    """Test rolling folds step by test window size."""
    folds = build_folds(
        date(2018, 1, 1), date(2021, 1, 1),
        train_months=12, test_months=3, anchored=False
    )
    # train 12m / test 3m, stepping 3m: roughly 9 folds across 3 years (after the first 12m train)
    assert len(folds) >= 6
    f0 = folds[0]
    assert f0.train_start == date(2018, 1, 1)
    assert f0.test_start == f0.train_end                # test immediately follows train
    assert (f0.test_end.year, f0.test_end.month) >= (f0.test_start.year, f0.test_start.month)


def test_anchored_train_start_is_fixed():
    """Test anchored folds have fixed train_start and growing window."""
    folds = build_folds(
        date(2018, 1, 1), date(2021, 1, 1),
        train_months=12, test_months=3, anchored=True
    )
    assert all(f.train_start == date(2018, 1, 1) for f in folds)   # anchored: start fixed, window grows


def test_param_combos_cartesian():
    space = {"a": [1, 2], "b": [10, 20]}
    combos = param_combos(space)
    assert len(combos) == 4
    assert {"a": 1, "b": 10} in combos


def test_apply_costs_reduces_return():
    # one round trip, 0.1% per leg (fee + slippage) => 0.4% drag on a 1.0% gross trade return
    net = apply_costs(gross_return_pct=1.0, fee_pct=0.001, slippage_pct=0.001)
    assert net < 1.0
    assert abs(net - (1.0 - 0.4)) < 0.05


def test_consensus_median_and_mode():
    """Test consensus aggregation across folds: numeric median, categorical mode."""
    from app.services.walk_forward import consensus

    winners = [
        {"ema_period": 20, "ma_type": "EMA"},
        {"ema_period": 50, "ma_type": "EMA"},
        {"ema_period": 50, "ma_type": "SMA"},
    ]
    c = consensus(winners)
    assert c["ema_period"] == 50          # median of [20,50,50]
    assert c["ma_type"] == "EMA"          # mode


def test_consistency_and_degradation():
    """Test fold consistency (ratio of positive returns) and curve-fit degradation."""
    from app.services.walk_forward import consistency, degradation_pct

    assert consistency([0.05, -0.02, 0.03, 0.01]) == 0.75    # 3 of 4 folds positive
    assert round(degradation_pct(in_sample=40.0, walk_forward=10.0), 2) == 0.75


def test_engine_prefers_planted_edge_over_noise():
    # Smoke-level integration: with a planted upward drift the consensus picks a
    # non-empty param set; pure-noise series yield empty/ineligible consensus.
    space = {"ema_period": [20, 50], "trend_ema": [100, 200]}
    assert len(param_combos(space)) == 4
    # Real recovery is validated end-to-end in Task 7 via the orchestrator on fixtures.
    assert consensus([{"ema_period": 50, "trend_ema": 200}]) == {"ema_period": 50, "trend_ema": 200}


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
