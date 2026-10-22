"""Tuner core (STOCKS-HORIZON-T1 H8): gate mask, signal/gate caches, sector
sample and fire-rate scaling, the ``tuning:`` config block.

The simulator's parity with the backtest is in test_tuning_simulator_parity.py.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

import app.services.strategy_param_store as store
from app.data import universe_exclusions
from app.data.universe_exclusions import Exclusion
from app.routers.stock_scan import _direction_conviction_drop
from app.scoring import stock_scorer
from app.services.config_loader import load_direction_conviction_min_trend
from app.services.horizon_tuning import basket, cache, gates, signals

_FIXTURES = Path(__file__).parent / "fixtures"
_REAL_CFG = Path(__file__).resolve().parents[1] / "config" / "strategy_params.yaml"
_ENGINE = Path(__file__).resolve().parents[1] / "app" / "services" / "strategy_engine.py"


def _aapl() -> list[dict]:
    return json.loads((_FIXTURES / "AAPL_candles.json").read_text(encoding="utf-8"))


def _use_cfg(tmp_path: Path, monkeypatch, data: dict) -> Path:
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    return cfg


def _real_cfg() -> dict:
    return yaml.safe_load(_REAL_CFG.read_text(encoding="utf-8"))


# ── gate mask ────────────────────────────────────────────────────────────────

def test_scoring_horizon_is_swing_for_swing_and_position_for_the_longer_four():
    assert gates.scoring_horizon_for("Swing") == "Swing"
    for h in ("Position", "Quarterly", "SemiAnnual", "Annual"):
        assert gates.scoring_horizon_for(h) == "Position"


def _mask(bars, **kw):
    args = dict(min_price=None, max_price=None, benchmark=None)
    args.update(kw)
    return gates.gate_mask(bars, "Bullish", "Swing", **args)


def test_gate_mask_has_one_entry_per_bar_and_some_bars_pass():
    bars = _aapl()
    mask = _mask(bars)
    assert len(mask) == len(bars)
    assert any(mask) and not all(mask)


def test_gate_mask_scorer_reject_bar_is_false(monkeypatch):
    bars = _aapl()
    base = _mask(bars)
    t = next(i for i in range(200, len(bars)) if base[i])
    real = gates.score_stock

    def _reject_at_t(**kw):
        card = real(**kw)
        if kw["bars"][-1]["time"] == bars[t]["time"]:
            return dataclasses.replace(card, status="REJECT")
        return card

    monkeypatch.setattr(gates, "score_stock", _reject_at_t)
    mask = _mask(bars)
    assert mask[t] is False
    assert [m for i, m in enumerate(mask) if i != t] == [m for i, m in enumerate(base) if i != t]


def test_gate_mask_price_bounds_are_inclusive_and_read_bar_t_close():
    bars = _aapl()
    base = _mask(bars)
    t = next(i for i in range(150, len(bars)) if base[i])
    close = bars[t]["close"]
    assert _mask(bars, min_price=close + 0.01)[t] is False
    assert _mask(bars, max_price=close - 0.01)[t] is False
    assert _mask(bars, min_price=close, max_price=close)[t] is True


def test_gate_mask_conviction_matches_the_scan_helper():
    bars = _aapl()
    mask = _mask(bars)
    min_trend = load_direction_conviction_min_trend("Bullish", "Swing")
    for t in range(len(bars)):
        window = bars[max(0, t - 119): t + 1]
        card = stock_scorer.score_stock(symbol="TUNE", direction="Bullish", horizon="Swing", bars=window,
                                        scoring_mode="stock")
        expected = card.status != "REJECT" and _direction_conviction_drop(
            "TUNE", card, min_trend, "Bullish", "Swing") is None
        assert mask[t] is expected, t


def test_gate_mask_conviction_floor_drops_every_bar_below_it(monkeypatch):
    bars = _aapl()
    monkeypatch.setattr(gates, "load_direction_conviction_min_trend", lambda d, h: 101.0)
    assert not any(_mask(bars))


# ── caches ───────────────────────────────────────────────────────────────────

class _Counter:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, *a, **kw):
        self.calls += 1
        return self.fn(*a, **kw)


def test_signal_cache_second_call_reads_from_disk(tmp_path, monkeypatch):
    counter = _Counter(signals.signal_series)
    monkeypatch.setattr(signals, "signal_series", counter)
    bars = _aapl()
    first = cache.TuningCache(tmp_path).signal_series("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    second = cache.TuningCache(tmp_path).signal_series("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    assert counter.calls == 1
    assert second == first
    assert len(first) == len(bars)
    assert (tmp_path / "signals").is_dir() and any((tmp_path / "signals").iterdir())


def test_signal_cache_recomputes_when_an_old_bar_changes(tmp_path, monkeypatch):
    counter = _Counter(signals.signal_series)
    monkeypatch.setattr(signals, "signal_series", counter)
    bars = _aapl()
    c = cache.TuningCache(tmp_path)
    c.signal_series("AAPL", bars, "pullback_ema", "Bullish", {})
    edited = copy.deepcopy(bars)
    edited[10]["close"] += 0.01          # same last date, one old close differs
    c.signal_series("AAPL", edited, "pullback_ema", "Bullish", {})
    assert counter.calls == 2


def test_signal_cache_recomputes_when_an_exit_value_changes(tmp_path, monkeypatch):
    counter = _Counter(signals.signal_series)
    monkeypatch.setattr(signals, "signal_series", counter)
    bars = _aapl()
    data = _real_cfg()
    _use_cfg(tmp_path, monkeypatch, data)
    c = cache.TuningCache(tmp_path / "cache")
    c.signal_series("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    c.signal_series("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    assert counter.calls == 1
    data["strategies"]["pullback_ema"]["exit"]["rr_target_mult"] = 3.0
    _use_cfg(tmp_path, monkeypatch, data)
    c.signal_series("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    assert counter.calls == 2


def test_signal_key_covers_the_planned_inputs():
    bars = _aapl()
    k = cache.signal_key("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    assert k != cache.signal_key("MSFT", bars, "pullback_ema", "Bullish", {"ema_period": 50})
    assert k != cache.signal_key("AAPL", bars, "pullback_ema", "Bearish", {"ema_period": 50})
    assert k != cache.signal_key("AAPL", bars, "pullback_ema", "Bullish", {"ema_period": 20})
    assert k != cache.signal_key("AAPL", bars[:-1], "pullback_ema", "Bullish", {"ema_period": 50})
    # Canonical JSON: key order does not matter.
    assert cache.signal_key("AAPL", bars, "ma_crossover", "Bullish", {"fast": 20, "slow": 50}) == \
        cache.signal_key("AAPL", bars, "ma_crossover", "Bullish", {"slow": 50, "fast": 20})


def test_ohlcv_hash_covers_every_field_of_every_bar():
    bars = _aapl()
    h = cache.ohlcv_hash(bars)
    for field in ("time", "open", "high", "low", "close", "volume"):
        edited = copy.deepcopy(bars)
        edited[3][field] = edited[3][field] + ("x" if field == "time" else 1)
        assert cache.ohlcv_hash(edited) != h, field


def test_gate_cache_recomputes_when_scoring_rules_change(tmp_path, monkeypatch):
    calls = []

    def _fake_mask(bars, direction, scoring_horizon, *, min_price, max_price, benchmark):
        calls.append(1)
        return [True] * len(bars)

    monkeypatch.setattr(gates, "gate_mask", _fake_mask)
    rules = tmp_path / "scoring_rules.yaml"
    rules.write_bytes(stock_scorer.CONFIG_PATH.read_bytes())
    monkeypatch.setattr(stock_scorer, "CONFIG_PATH", rules)
    bars = _aapl()
    kw = dict(min_price=None, max_price=None, benchmark=None)
    c = cache.TuningCache(tmp_path / "cache")
    first = c.gate_mask("AAPL", bars, "Bullish", "Swing", **kw)
    assert cache.TuningCache(tmp_path / "cache").gate_mask("AAPL", bars, "Bullish", "Swing", **kw) == first
    assert len(calls) == 1
    rules.write_bytes(rules.read_bytes() + b"\n# edited\n")
    c.gate_mask("AAPL", bars, "Bullish", "Swing", **kw)
    assert len(calls) == 2
    # Price bounds and the benchmark are in the key too.
    c.gate_mask("AAPL", bars, "Bullish", "Swing", min_price=5.0, max_price=None, benchmark=None)
    c.gate_mask("AAPL", bars, "Bullish", "Swing", min_price=None, max_price=None, benchmark=bars[:50])
    c.gate_mask("AAPL", bars, "Bullish", "Position", **kw)
    assert len(calls) == 5


# Pinned per SIGNAL_CACHE_VERSION: sha256 of strategy_engine.py (LF line endings).
_ENGINE_SOURCE_PINS = {
    3: "3821eeee4059ad40cc788d94182336c4b2c35f43161116fc2ddb49932f257006",
    1: "a43b311fc33ea5862d212f29c43d430e9be5807c0b3c8641995ede9266aa2519",
    2: "1054b5a87a9142c5db8f45b16181edd0289d551f27dacc6e896f61949d1ed812",
}


def test_signal_cache_version_tracks_strategy_engine_source():
    text = _ENGINE.read_bytes().replace(b"\r\n", b"\n")
    sha = hashlib.sha256(text).hexdigest()
    assert _ENGINE_SOURCE_PINS.get(cache.SIGNAL_CACHE_VERSION) == sha, (
        "strategy_engine.py changed: bump SIGNAL_CACHE_VERSION in "
        "app/services/horizon_tuning/cache.py and pin the new hash here "
        f"({sha}) so cached signal series are recomputed")


# ── sample basket and fire-rate scaling ──────────────────────────────────────

_SECTORS = {"AAA": "Technology", "BBB": "Technology", "CCC": "Technology",
            "DDD": "Energy", "EEE": "Energy", "FFF": None}


def test_sample_basket_takes_top_n_dollar_volume_per_sector_and_lists_the_unsectored(monkeypatch):
    monkeypatch.setattr(basket, "sector_for_symbol", lambda s: (_SECTORS[s], None))
    liquidity = {"AAA": 5.0, "BBB": 9.0, "CCC": 1.0, "DDD": 2.0, "EEE": 3.0, "FFF": 99.0}
    sample = basket.sample_basket(list(_SECTORS), liquidity, per_sector=2)
    assert sample.symbols == ["AAA", "BBB", "DDD", "EEE"]
    assert sample.by_sector == {"Technology": ["AAA", "BBB"], "Energy": ["DDD", "EEE"]}
    assert sample.unsectored == ["FFF"]
    assert basket.SAMPLE_LABEL == "liquidity-selected (dollar volume), equal count per sector"


def test_dollar_volume_is_mean_close_times_volume_before_heldout_start():
    bars = [{"time": "2024-01-02", "close": 10.0, "volume": 100.0},
            {"time": "2024-01-03", "close": 20.0, "volume": 300.0},
            {"time": "2024-01-04", "close": 99.0, "volume": 999.0}]
    assert basket.dollar_volume(bars, date(2024, 1, 4)) == pytest.approx((1000.0 + 6000.0) / 2)
    assert basket.dollar_volume(bars, date(2024, 1, 1)) is None


def test_trade_universe_drops_both_scopes_fire_rate_universe_only_scan(monkeypatch):
    excl = {"SCN": Exclusion("SCN", "scan", "bad bars"), "EVD": Exclusion("EVD", "evidence", "untrusted")}
    monkeypatch.setattr(universe_exclusions, "load_exclusions", lambda *a, **k: excl)
    syms = ["AAA", "SCN", "EVD", "BBB"]
    assert basket.trade_universe(syms) == ["AAA", "BBB"]
    assert basket.fire_rate_universe(syms) == ["AAA", "EVD", "BBB"]


def test_scaled_fire_rate_hand_counted():
    # Technology: 30 fires over 60 scan days in a 10-name sample of a 70-name
    # sector -> 0.5/day x 7 = 3.5. Energy: 6 fires, 5-name sample of 20 -> 0.1 x 4 = 0.4.
    rate = basket.scaled_fire_rate(
        {"Technology": 30, "Energy": 6}, scan_days=60,
        n_universe_by_sector={"Technology": 70, "Energy": 20, "Utilities": 30},
        n_sample_by_sector={"Technology": 10, "Energy": 5, "Utilities": 0},
    )
    assert rate == pytest.approx(3.9)


def test_sector_counts_skip_the_unsectored(monkeypatch):
    monkeypatch.setattr(basket, "sector_for_symbol", lambda s: (_SECTORS[s], None))
    assert basket.sector_counts(list(_SECTORS)) == {"Technology": 3, "Energy": 2}


# ── tuning: config ───────────────────────────────────────────────────────────

def test_tuning_config_reads_the_planned_block():
    cfg = store.get_tuning_config()
    assert cfg["cost_per_leg"] == 0.0005
    assert cfg["stress_cost_per_leg"] == 0.002
    assert cfg["held_out_months"] == 12
    assert cfg["exit_buffer_days"] == 14
    assert cfg["windows"] == {
        "Swing": {"train_months": 12, "test_months": 3},
        "Position": {"train_months": 12, "test_months": 3},
        "Quarterly": {"train_months": 12, "test_months": 4},
        "SemiAnnual": {"train_months": 16, "test_months": 8},
        "Annual": {"train_months": 24, "test_months": 12},
    }
    assert cfg["fire_rate_floor_per_day"] == {"Swing": 2.0, "Position": 1.0, "Quarterly": 0.6,
                                              "SemiAnnual": 0.4, "Annual": 0.2}
    assert cfg["adoption"] == {"ci_level": 0.95, "min_oos_trades": 100, "min_symbols": 20,
                               "bootstrap_resamples": 2000, "seed": 7}
    assert cfg["min_train_trades"] == 30
    assert cfg["min_folds_not_thin"] == 4
    assert cfg["basket"] == {"per_sector": 10}
    assert cfg["gates"] == {"min_price": None, "max_price": None}


@pytest.mark.parametrize("path", [
    ("surprise",),
    ("windows", "Swing", "surprise"),
    ("adoption", "surprise"),
    ("basket", "surprise"),
    ("gates", "surprise"),
    ("windows", "Intraday"),
    ("fire_rate_floor_per_day", "Intraday"),
])
def test_tuning_config_refuses_an_unknown_key(tmp_path, monkeypatch, path):
    data = _real_cfg()
    node = data["tuning"]
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = {"train_months": 1, "test_months": 1} if path[-1] == "Intraday" and path[0] == "windows" else 1
    _use_cfg(tmp_path, monkeypatch, data)
    with pytest.raises(ValueError, match="surprise|Intraday"):
        store.get_tuning_config()


@pytest.mark.parametrize("path", [
    ("cost_per_leg",),
    ("windows", "Annual"),
    ("windows", "Swing", "test_months"),
    ("adoption", "seed"),
    ("basket", "per_sector"),
    ("gates", "max_price"),
    ("fire_rate_floor_per_day", "Quarterly"),
])
def test_tuning_config_refuses_a_missing_key(tmp_path, monkeypatch, path):
    data = _real_cfg()
    node = data["tuning"]
    for p in path[:-1]:
        node = node[p]
    del node[path[-1]]
    _use_cfg(tmp_path, monkeypatch, data)
    with pytest.raises(ValueError, match=path[-1]):
        store.get_tuning_config()


def test_tuning_config_refuses_a_missing_block(tmp_path, monkeypatch):
    data = _real_cfg()
    del data["tuning"]
    _use_cfg(tmp_path, monkeypatch, data)
    with pytest.raises(ValueError, match="tuning"):
        store.get_tuning_config()


@pytest.mark.parametrize("path,value", [
    (("cost_per_leg",), -0.001),
    (("cost_per_leg",), "0.0005"),
    (("held_out_months",), 0),
    (("held_out_months",), True),
    (("windows", "Swing", "train_months"), 2.5),
    (("adoption", "ci_level"), 1.5),
    (("basket", "per_sector"), 0),
    (("gates", "min_price"), "cheap"),
])
def test_tuning_config_refuses_a_bad_value(tmp_path, monkeypatch, path, value):
    data = _real_cfg()
    node = data["tuning"]
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    _use_cfg(tmp_path, monkeypatch, data)
    with pytest.raises(ValueError, match=path[-1]):
        store.get_tuning_config()
