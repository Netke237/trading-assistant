"""Tests for strategy parameter store and YAML configuration."""

import pytest
from app.services.strategy_param_store import (
    get_active,
    get_search_space,
    get_windows,
    get_costs,
    adopt,
)


def test_get_active_returns_defaults_and_missing_falls_back():
    """Test get_active returns strategy params or empty dict for missing strategies."""
    p = get_active("pullback_ema")
    assert p["ema_period"] == 50
    assert p["trend_ema"] == 100
    assert p["atr_stop_mult"] == 1.5
    assert p["rr_target_mult"] == 2.0
    assert p["tolerance"] == 0.08

    # Unknown strategy -> empty dict (caller then uses signal-fn defaults).
    assert get_active("does_not_exist") == {}


def test_get_active_multiple_strategies():
    """Test get_active for different strategies."""
    breakout = get_active("breakout_base")
    assert breakout["base_lookback"] == 20
    assert breakout["atr_tight_max"] == 1.5

    ma = get_active("ma_crossover")
    assert ma["fast"] == 20
    assert ma["slow"] == 50

    rsi = get_active("mean_reversion_rsi")
    assert rsi["rsi_period"] == 14
    assert rsi["rsi_oversold"] == 30


def test_search_space_present():
    """Test get_search_space returns search hyperparameters."""
    s = get_search_space("pullback_ema")
    assert s["ema_period"] == [20, 50]
    assert s["trend_ema"] == [100, 150, 200]
    assert s["atr_stop_mult"] == [1.0, 1.5, 2.0]
    assert s["rr_target_mult"] == [1.5, 2.0, 2.5, 3.0]
    assert s["tolerance"] == [0.05, 0.08, 0.10]

    breakout = get_search_space("breakout_base")
    assert breakout["base_lookback"] == [15, 20, 30]


def test_search_space_missing_returns_empty():
    """Test get_search_space returns empty dict for missing strategy."""
    assert get_search_space("does_not_exist") == {}


def test_get_windows():
    """Test get_windows returns window configuration."""
    w = get_windows()
    assert w["type"] == "rolling"
    assert w["train_months"] == 12
    assert w["test_months"] == 3


def test_get_costs():
    """Test get_costs returns cost configuration."""
    c = get_costs()
    assert c["fee_pct"] == 0.001
    assert c["slippage_pct"] == 0.001
