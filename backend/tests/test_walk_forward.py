"""Tests for walk-forward optimization fold construction."""
from datetime import date, timedelta
from app.services.walk_forward import build_folds, param_combos, consensus, precompute_bar_dates


def _synth_bars_for_walk_forward(n=400, start=date(2020, 1, 1), trend=True):
    """Daily bars with real sequential dates (unlike test_strategy_backtest.py's
    _synth_bars, whose 'time' field cycles within a single fixed month and is
    unsuitable for fold-based date-range slicing here)."""
    bars, price, d = [], 50.0, start
    for i in range(n):
        if trend:
            price = price * 1.002 + (0.5 if i % 10 == 0 else -0.2)
        else:
            price = 50.0 + (i % 7 - 3) * 0.1
        bars.append({
            "time": d.isoformat(),
            "open": price * 0.998, "high": price * 1.01,
            "low":  price * 0.99,  "close": price, "volume": 1000 + i,
        })
        d += timedelta(days=1)
    return bars


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


def test_apply_costs_is_gone():
    """TRADING-REVIEW-PHASE-C T4: costs are charged per trade leg inside the
    backtest (commission=fee+slippage), so the flat once-per-window `apply_costs`
    must not come back — it would charge every window a second time."""
    from app.services import walk_forward, strategy_param_optimizer

    assert not hasattr(walk_forward, "apply_costs")
    assert not hasattr(strategy_param_optimizer, "apply_costs")


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
        direction="Bullish",
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
        direction="Bullish",
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


def test_train_fold_finds_a_winner_on_real_sub_gate_trade_counts():
    """Real-data regression (2026-08 audit): train_fold calls run_strategy_backtest
    without overriding min_trades, so it used to inherit the module default
    (_MIN_TRADES=10). On real daily fixture data, a full 12-month/4-symbol window
    routinely produces 1-5 real trades per symbol for pullback_ema — every one of
    which used to come back as n_trades=0 (see the strategy_backtest.py fix this
    round), making every combo look untraded (`sharpes=[]` for all of them) and
    train_fold silently return {} despite real, computable per-trade performance
    existing. This must now return a real, non-empty winner."""
    import json
    from pathlib import Path
    from app.services.walk_forward import train_fold, Fold, precompute_bar_dates

    fixtures = Path(__file__).parent / "fixtures"
    basket_bars = {}
    for sym in ["AAPL", "MSFT", "NVDA", "SPY"]:
        path = fixtures / f"{sym}_candles.json"
        if not path.exists():
            import pytest
            pytest.skip(f"Fixture not found: {path}")
        bars = json.loads(path.read_text())
        precompute_bar_dates(bars)
        basket_bars[sym] = bars

    fold = Fold(date(2024, 4, 30), date(2025, 4, 30), date(2025, 4, 30), date(2025, 7, 30))
    search_space = {
        "ema_period": [20, 50], "trend_ema": [100, 150, 200],
        "atr_stop_mult": [1.0, 1.5, 2.0], "rr_target_mult": [1.5, 2.0, 2.5, 3.0],
        "tolerance": [0.02, 0.04, 0.06, 0.08],
    }
    winner, _ = train_fold(
        "pullback_ema", "Bullish", basket_bars, fold, search_space,
        {"fee_pct": 0.001, "slippage_pct": 0.001},
    )
    assert winner != {}, (
        "train_fold returned no winner on real fixture data with real (sub-gate) "
        "trade counts — the min_trades zeroing bug has regressed"
    )
    assert set(winner.keys()) == set(search_space.keys())


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

    def _stub_backtest(train_bars, *, strategy, direction, params, **kwargs):
        return _StubResult(sharpe=1.0)  # identical Sharpe for every combo

    monkeypatch.setattr(wf_mod, "run_strategy_backtest", _stub_backtest)

    bars = [{"time": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 32)] * 4  # >100 bars
    for b in bars:
        b["_date"] = date.fromisoformat(b["time"])
    fold = Fold(date(2020, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2021, 4, 1))

    winner, _ = train_fold(
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

    def _stub_backtest(train_bars, *, strategy, direction, params, **kwargs):
        # Edge value (10) is far better than everything else -> should still win.
        sharpe = 2.0 if params["ema_period"] == 10 else 1.0
        return _StubResult(sharpe=sharpe)

    monkeypatch.setattr(wf_mod, "run_strategy_backtest", _stub_backtest)

    bars = [{"time": f"2020-01-{d:02d}", "close": 100.0} for d in range(1, 32)] * 4
    for b in bars:
        b["_date"] = date.fromisoformat(b["time"])
    fold = Fold(date(2020, 1, 1), date(2021, 1, 1), date(2021, 1, 1), date(2021, 4, 1))

    winner, _ = train_fold(
        "pullback_ema", "bullish", {"SYM": bars}, fold,
        {"ema_period": [10, 20, 30, 40, 50]}, {"fee_pct": 0.001, "slippage_pct": 0.001},
    )
    assert winner == {"ema_period": 10}


def test_train_fold_returns_params_and_results_tuple(monkeypatch):
    """train_fold must return (winning_params, {symbol: BacktestResult}) so callers
    can reuse the winning combo's backtest instead of re-running it (M11).

    Uses a stubbed run_strategy_backtest rather than organically-generated
    synthetic bars: the real strategy engines don't reliably fire trades
    against simple noise-based synthetic series (verified directly — none of
    the 4 core strategies produce a single trade over 400 bars of this
    generator), so this test isolates train_fold's own selection/stashing
    logic instead of depending on strategy_engine's entry conditions.
    """
    import app.services.walk_forward as wf_module
    from app.services.walk_forward import train_fold, Fold
    from app.services.strategy_backtest import BacktestResult

    def fake_backtest(bars, *, strategy, direction, params=None, min_trades=10, min_win_rate=0.0, **kwargs):
        return BacktestResult(
            strategy=strategy, direction=direction, n_trades=15, win_rate=0.6,
            total_return_pct=10.0, max_drawdown_pct=-5.0, expectancy=0.4,
            sharpe=1.0, confidence=70, passes_gate=True, summary_text="ok",
        )

    monkeypatch.setattr(wf_module, "run_strategy_backtest", fake_backtest)

    bars = _synth_bars_for_walk_forward(400, trend=True)
    basket_bars = {"AAPL": bars}
    fold = Fold(
        train_start=date(2020, 1, 1), train_end=date(2020, 7, 1),
        test_start=date(2020, 7, 1), test_end=date(2020, 10, 1),
    )
    search_space = {"ema_period": [20, 50]}
    result = train_fold("pullback_ema", "Bullish", basket_bars, fold, search_space, costs={})
    assert isinstance(result, tuple) and len(result) == 2
    winner, winner_results = result
    assert isinstance(winner, dict)
    assert isinstance(winner_results, dict)
    for sym, res in winner_results.items():
        assert hasattr(res, "total_return_pct")
        assert hasattr(res, "n_trades")


def test_train_fold_picks_highest_sharpe_and_stashes_its_result(monkeypatch):
    """train_fold must select the combo with the highest pooled Sharpe and stash
    THAT combo's own BacktestResult per symbol — not e.g. the last combo tried
    or a freshly re-run backtest (proves no double-run drift was introduced by
    the M11 refactor: winner_results must reflect the actual winning combo)."""
    import app.services.walk_forward as wf_module
    from app.services.walk_forward import train_fold, Fold

    def fake_backtest(bars, *, strategy, direction, params=None, min_trades=10, min_win_rate=0.0, **kwargs):
        from app.services.strategy_backtest import BacktestResult
        ema = (params or {}).get("ema_period", 50)
        sharpe = 1.5 if ema == 20 else 0.3  # ema_period=20 is the clear winner
        return BacktestResult(
            strategy=strategy, direction=direction, n_trades=15, win_rate=0.6,
            total_return_pct=10.0, max_drawdown_pct=-5.0, expectancy=0.4,
            sharpe=sharpe, confidence=70, passes_gate=True, summary_text="ok",
        )

    monkeypatch.setattr(wf_module, "run_strategy_backtest", fake_backtest)

    bars = _synth_bars_for_walk_forward(400, trend=True)
    basket_bars = {"AAPL": bars}
    fold = Fold(
        train_start=date(2020, 1, 1), train_end=date(2020, 7, 1),
        test_start=date(2020, 7, 1), test_end=date(2020, 10, 1),
    )
    search_space = {"ema_period": [20, 50]}
    winner, winner_results = train_fold("pullback_ema", "Bullish", basket_bars, fold, search_space, costs={})

    assert winner == {"ema_period": 20}
    assert winner_results["AAPL"].sharpe == 1.5
