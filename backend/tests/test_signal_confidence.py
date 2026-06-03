from app.scoring.signal_confidence import (
    load_backtest_cfg,
    load_gate_cfg,
    evaluate_fire,
    aggregate,
    ConfidenceResult,
)


def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


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
