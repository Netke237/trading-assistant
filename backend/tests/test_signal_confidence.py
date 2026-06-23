from app.scoring.signal_confidence import (
    load_backtest_cfg,
    load_gate_cfg,
    evaluate_fire,
    aggregate,
    ConfidenceResult,
    compute_confidence,
)


def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_config_blocks_present_with_defaults():
    from app.scoring.signal_confidence import _cfg
    _cfg.cache_clear()   # force re-read after YAML edit in Step 3.1
    bt = load_backtest_cfg("swing")
    assert bt["n_days"] == 10
    assert bt["atr_mult_target"] == 3.0   # replaces old atr_mult
    assert bt["atr_mult_stop"] == 1.5
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


def test_compute_confidence_runs_end_to_end_on_synthetic_uptrend():
    # Rising series so the bullish signal fires repeatedly and mostly wins.
    # Use atr_mult=1.5 (symmetric override / legacy path) so the tight bar range
    # reaches the target within n_days=10.  The asymmetric config defaults
    # (atr_mult_target=3.0) require wider-ranging bars — covered by the unit tests.
    bars = []
    price = 50.0
    for i in range(400):
        price *= 1.004
        bars.append(_bar(price * 0.997, price * 1.01, price * 0.99, price, 1000 + i))
    res = compute_confidence(bars, direction="Bullish", horizon="Swing", atr_mult=1.5)
    assert res.sample_size >= 20
    assert res.confidence is not None
    assert 0 <= res.confidence <= 100


# ── Asymmetric ATR tests (Task 3) ─────────────────────────────────────────────

def test_evaluate_fire_asymmetric_win_requires_larger_target():
    """With atr_mult_target=3.0, atr_mult_stop=1.5: +3 ATR = win, not +1.5."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    atr = 2.0
    # +1.5 ATR = +3 → would be a win in symmetric mode; +3 ATR = +6 for asymmetric
    fwd_only_1x5 = [_bar(100, 103.5, 99.5, 103)]  # high=103.5 < 106 (target with 3.0 mult)
    outcome = evaluate_fire(
        history, fwd_only_1x5, direction="Bullish", atr=atr,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "flat", (
        "Reaching +1.5 ATR should be flat (not win) when target is +3.0 ATR"
    )


def test_evaluate_fire_asymmetric_win_hits_3x_target():
    """With atr_mult_target=3.0: +6 (3×ATR=2) on the high = win."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd_win = [_bar(100, 106.5, 99.5, 106)]  # high=106.5 > 100+3*2=106
    outcome = evaluate_fire(
        history, fwd_win, direction="Bullish", atr=2.0,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "win"


def test_evaluate_fire_asymmetric_loss_at_1x5_stop():
    """Stop at 1.5 ATR below entry still triggers a loss."""
    history = [_bar(100, 101, 99, 100) for _ in range(20)]
    fwd_loss = [_bar(100, 100.5, 96.5, 97)]  # low=96.5 < 100-1.5*2=97
    outcome = evaluate_fire(
        history, fwd_loss, direction="Bullish", atr=2.0,
        atr_mult_target=3.0, atr_mult_stop=1.5,
    )
    assert outcome == "loss"


def test_config_blocks_present_with_new_keys():
    """confidence_backtest now has atr_mult_target and atr_mult_stop, not atr_mult."""
    from app.scoring.signal_confidence import _cfg
    _cfg.cache_clear()   # force re-read after YAML edit in Step 3.1
    bt = load_backtest_cfg("swing")
    assert "atr_mult_target" in bt, "atr_mult_target key missing from config"
    assert "atr_mult_stop" in bt, "atr_mult_stop key missing from config"
    assert bt["atr_mult_target"] == 3.0
    assert bt["atr_mult_stop"] == 1.5
    assert "atr_mult" not in bt, "old atr_mult key should be removed"
