"""Tests for strategy parameter store and YAML configuration."""

import pytest
from app.services.strategy_param_store import (
    get_active,
    get_search_space,
    get_windows,
    get_costs,
    get_direction,
    get_job_retention,
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


def test_adopt_round_trips(tmp_path, monkeypatch):
    """Test adopt archives and updates active parameters correctly."""
    import app.services.strategy_param_store as store

    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  pullback_ema:\n    active:\n      ema_period: 50\n",
        encoding="utf-8"
    )
    store.adopt("pullback_ema", {"ema_period": 20})
    assert store.get_active("pullback_ema")["ema_period"] == 20


def test_adopt_creates_backup_when_file_exists(tmp_path, monkeypatch):
    """Test adopt creates a backup of the existing config file."""
    import app.services.strategy_param_store as store

    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  test_strategy:\n    active:\n      param: 10\n",
        encoding="utf-8"
    )
    store.adopt("test_strategy", {"param": 20})

    # Check that at least one backup was created
    backups = list(tmp_path.glob("strategy_params.bak.*.yaml"))
    assert len(backups) > 0


def test_adopt_handles_missing_file_gracefully(tmp_path, monkeypatch):
    """Test adopt does not crash when YAML file does not exist yet."""
    import app.services.strategy_param_store as store

    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    # File doesn't exist
    assert not (tmp_path / "strategy_params.yaml").exists()

    # Should not raise FileNotFoundError
    store.adopt("new_strategy", {"param": 30})

    # File should now exist with the new data
    assert (tmp_path / "strategy_params.yaml").exists()
    assert store.get_active("new_strategy")["param"] == 30


def test_get_direction_default():
    assert get_direction() == "bullish"


def test_get_direction_custom(tmp_path, monkeypatch):
    import app.services.strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text("direction: bearish\n", encoding="utf-8")
    assert store.get_direction() == "bearish"


def test_get_job_retention_default():
    r = get_job_retention()
    assert r["max_completed"] == 100


def test_get_job_retention_custom(tmp_path, monkeypatch):
    import app.services.strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "job_retention:\n  max_completed: 50\n", encoding="utf-8"
    )
    assert store.get_job_retention()["max_completed"] == 50


def test_signal_kwargs_merge_request_over_store(monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr("app.routers.stock_scan.get_active", lambda s: {"ema_period": 50, "trend_ema": 100})
    # request override should win over the adopted default
    from app.routers.stock_scan import _merge_strategy_params
    merged = _merge_strategy_params("pullback_ema", {"ema_period": 20})
    assert merged["ema_period"] == 20      # request wins
    assert merged["trend_ema"] == 100      # store default fills the rest
