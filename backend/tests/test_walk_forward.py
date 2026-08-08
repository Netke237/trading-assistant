"""Tests for walk-forward optimization fold construction."""
from datetime import date
from app.services.walk_forward import build_folds, param_combos, apply_costs, consensus, precompute_bar_dates


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


def test_rolling_fold1_train_start_slides_by_test_months():
    """Rolling fold 1 train_start should advance by test_months (3), not train_months (12)."""
    from datetime import date
    folds = build_folds(
        date(2018, 1, 1), date(2021, 6, 1),
        train_months=12, test_months=3, anchored=False,
    )
    assert len(folds) >= 2
    assert folds[0].train_start == date(2018, 1, 1)
    assert folds[1].train_start == date(2018, 4, 1)  # +3 months not +12


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


# ── Complexity penalty (grid-search overfitting guard) ───────────────────────

def test_complexity_penalty_zero_at_grid_center():
    from app.services.walk_forward import _complexity_penalty
    space = {"ema_period": [10, 20, 30, 40, 50]}  # center index = 2 -> value 30
    assert _complexity_penalty({"ema_period": 30}, space) == 0.0


def test_complexity_penalty_max_at_grid_edge():
    from app.services.walk_forward import _complexity_penalty
    space = {"ema_period": [10, 20, 30, 40, 50]}
    edge_penalty = _complexity_penalty({"ema_period": 10}, space, weight=0.05)
    mid_penalty = _complexity_penalty({"ema_period": 20}, space, weight=0.05)
    assert edge_penalty == 0.05          # full weight at the edge
    assert 0.0 < mid_penalty < edge_penalty


def test_complexity_penalty_sums_across_params():
    from app.services.walk_forward import _complexity_penalty
    space = {"a": [1, 2, 3], "b": [10, 20, 30]}
    # both params at their edge -> two full penalties
    penalty = _complexity_penalty({"a": 1, "b": 30}, space, weight=0.05)
    assert abs(penalty - 0.10) < 1e-9


def test_complexity_penalty_ignores_single_value_or_missing_key():
    from app.services.walk_forward import _complexity_penalty
    space = {"a": [5], "b": [1, 2]}
    assert _complexity_penalty({"a": 5}, space) == 0.0   # single-value grid, no penalty
    assert _complexity_penalty({}, space) == 0.0          # combo missing keys entirely


def test_complexity_penalty_skips_categorical_and_boolean_grids():
    """A categorical/boolean param has no ordinal 'center' — penalizing by its
    arbitrary YAML list position would be meaningless, so it's skipped."""
    from app.services.walk_forward import _complexity_penalty
    space = {"ma_type": ["EMA", "SMA"], "use_filter": [True, False], "ema_period": [10, 20, 30]}
    # ema_period=10 is at the numeric grid's edge; ma_type/use_filter contribute nothing
    penalty = _complexity_penalty({"ma_type": "SMA", "use_filter": False, "ema_period": 10}, space, weight=0.05)
    assert penalty == 0.05  # only the numeric param's edge-penalty counts


def test_train_fold_breaks_sharpe_tie_toward_grid_center(monkeypatch):
    """Equal in-sample Sharpe across combos -> the complexity penalty should
    make train_fold prefer the more central grid value, not silently default
    to whichever combo itertools.product happens to enumerate first."""
    from app.services import walk_forward as wf_mod
    from app.services.walk_forward import train_fold, Fold

    class _StubResult:
        def __init__(self, sharpe):
            self.sharpe = sharpe
            self.n_trades = 5

    def _stub_backtest(train_bars, *, strategy, direction, params):
        return _StubResult(sharpe=1.0)  # identical Sharpe for every combo

    monkeypatch.setattr(wf_mod, "run_strategy_backtest", _stub_backtest)

    bars = [{"time": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 32)] * 4  # >100 bars
    for b in bars:
        b["_date"] = date.fromisoformat(b["time"])
    fold = Fold(date(2020, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2021, 4, 1))

    winner = train_fold(
        "pullback_ema", "bullish", {"SYM": bars}, fold,
        {"ema_period": [10, 20, 30, 40, 50]}, {"fee_pct": 0.001, "slippage_pct": 0.001},
    )
    assert winner == {"ema_period": 30}, (
        f"expected the grid-center value to win an exact Sharpe tie, got {winner}"
    )


def test_train_fold_lets_a_clear_edge_winner_through(monkeypatch):
    """The penalty is a tie-breaker, not a hard ban — a combo with a large
    enough genuine Sharpe advantage should still win even at the grid edge."""
    from app.services import walk_forward as wf_mod
    from app.services.walk_forward import train_fold, Fold

    class _StubResult:
        def __init__(self, sharpe):
            self.sharpe = sharpe
            self.n_trades = 5

    def _stub_backtest(train_bars, *, strategy, direction, params):
        # Edge value (10) is far better than everything else -> should still win.
        sharpe = 2.0 if params["ema_period"] == 10 else 1.0
        return _StubResult(sharpe=sharpe)

    monkeypatch.setattr(wf_mod, "run_strategy_backtest", _stub_backtest)

    bars = [{"time": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 32)] * 4
    for b in bars:
        b["_date"] = date.fromisoformat(b["time"])
    fold = Fold(date(2020, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2021, 4, 1))

    winner = train_fold(
        "pullback_ema", "bullish", {"SYM": bars}, fold,
        {"ema_period": [10, 20, 30, 40, 50]}, {"fee_pct": 0.001, "slippage_pct": 0.001},
    )
    assert winner == {"ema_period": 10}
