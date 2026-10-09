"""Per-horizon parameter profiles (STOCKS-HORIZON-T1 H4).

``strategies.<s>.active.<direction>`` holds the direction BASELINE plus, under a
key in ``TUNED_HORIZONS``, that horizon's profile. ``get_active`` returns the
baseline only; ``get_profile`` overlays a horizon's profile; the request's
strategy fields are Optional so an omitted field takes the profile value.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import itertools
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.services.strategy_param_store as store
from app.services.horizon_profiles import TUNED_HORIZONS
from app.services.strategy_engine import SIGNAL_WINDOW_BARS, bars_needed

_REAL_CFG = Path(__file__).resolve().parents[1] / "config" / "strategy_params.yaml"
_RSI, _BB, _VWD = "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap_daily"
_TUNED = ("pullback_ema", "breakout_base", "ma_crossover", _RSI, _BB, "mean_reversion_multi")


def _use_cfg(tmp_path: Path, monkeypatch, data: dict) -> Path:
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    return cfg


def _real_cfg() -> dict:
    return yaml.safe_load(_REAL_CFG.read_text(encoding="utf-8"))


_FLAT = {
    "strategies": {
        "pullback_ema": {
            "active": {
                "bullish": {"ema_period": 50, "tolerance": 0.04,
                            "Swing": {"ema_period": 20, "tolerance": 0.02}},
                "bearish": {"ema_period": 35, "tolerance": 0.04},
            },
        },
        "mean_reversion_multi": {
            "active": {
                "bullish": {
                    "variants": [_RSI, _BB],
                    "min_confirmations": 2,
                    "variant_params": {_RSI: {"rsi_oversold": 30, "rsi_period": 14},
                                       _BB: {"bb_std": 2.0}},
                    "Swing": {"min_confirmations": 1,
                              "variant_params": {_RSI: {"rsi_oversold": 25}}},
                },
            },
        },
    },
}


# ── (1) get_active hides horizon sub-dicts ───────────────────────────────────

def test_get_active_hides_horizon_subdicts(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _FLAT)
    assert store.get_active("pullback_ema", "Bullish") == {"ema_period": 50, "tolerance": 0.04}
    assert "Swing" not in store.get_active("mean_reversion_multi", "Bullish")


# ── (2) get_profile: tuned / baseline / None, flat and multi ─────────────────

def test_get_profile_flat(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _FLAT)
    assert store.get_profile("pullback_ema", "Bullish", "Swing") == (
        {"ema_period": 20, "tolerance": 0.02}, "tuned")
    assert store.get_profile("pullback_ema", "Bullish", "Annual") == (
        {"ema_period": 50, "tolerance": 0.04}, "baseline")
    assert store.get_profile("pullback_ema", "Bullish", None) == (
        {"ema_period": 50, "tolerance": 0.04}, "baseline")
    assert store.get_profile("pullback_ema", "Bearish", "Swing") == (
        {"ema_period": 35, "tolerance": 0.04}, "baseline")
    assert store.get_profile("does_not_exist", "Bullish", "Swing") == ({}, "baseline")


def test_get_profile_multi_is_nested(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _FLAT)
    params, source = store.get_profile("mean_reversion_multi", "Bullish", "Swing")
    assert source == "tuned"
    assert params == {
        "variants": [_RSI, _BB],
        "min_confirmations": 1,
        "variant_params": {_RSI: {"rsi_oversold": 25, "rsi_period": 14}, _BB: {"bb_std": 2.0}},
    }
    base, source = store.get_profile("mean_reversion_multi", "Bullish", None)
    assert source == "baseline"
    assert base["min_confirmations"] == 2
    assert base["variant_params"][_RSI] == {"rsi_oversold": 30, "rsi_period": 14}


def test_get_profile_returns_copies(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _FLAT)
    params, _ = store.get_profile("mean_reversion_multi", "Bullish", "Swing")
    params["variant_params"][_RSI]["rsi_oversold"] = 99
    again, _ = store.get_profile("mean_reversion_multi", "Bullish", "Swing")
    assert again["variant_params"][_RSI]["rsi_oversold"] == 25


# ── (3) adopt keeps sub-dicts / writes only the horizon ──────────────────────

def test_adopt_without_horizon_keeps_horizon_subdicts(tmp_path, monkeypatch):
    cfg = _use_cfg(tmp_path, monkeypatch, _FLAT)
    store.adopt("pullback_ema", {"ema_period": 20, "tolerance": 0.06}, "Bullish")
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    bull = raw["strategies"]["pullback_ema"]["active"]["bullish"]
    assert bull == {"ema_period": 20, "tolerance": 0.06,
                    "Swing": {"ema_period": 20, "tolerance": 0.02}}
    assert store.get_active("pullback_ema", "Bullish") == {"ema_period": 20, "tolerance": 0.06}


def test_adopt_with_horizon_writes_only_that_horizon(tmp_path, monkeypatch):
    cfg = _use_cfg(tmp_path, monkeypatch, _FLAT)
    store.adopt("pullback_ema", {"ema_period": 100}, "Bullish", horizon="Annual")
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    active = raw["strategies"]["pullback_ema"]["active"]
    assert active["bullish"] == {"ema_period": 50, "tolerance": 0.04,
                                 "Swing": {"ema_period": 20, "tolerance": 0.02},
                                 "Annual": {"ema_period": 100}}
    assert active["bearish"] == {"ema_period": 35, "tolerance": 0.04}
    assert store.get_profile("pullback_ema", "Bullish", "Annual") == (
        {"ema_period": 100, "tolerance": 0.04}, "tuned")


# ── (4) grids: counts per cell, bars_needed, bearish rsi ─────────────────────

_GRID_N = {
    "pullback_ema": {"Swing": 72, "Position": 108, "Quarterly": 72, "SemiAnnual": 48, "Annual": 36},
    "breakout_base": {"Swing": 108, "Position": 108, "Quarterly": 108, "SemiAnnual": 54, "Annual": 54},
    "ma_crossover": {"Swing": 54, "Position": 54, "Quarterly": 81, "SemiAnnual": 24, "Annual": 24},
    _RSI: {"Swing": 108, "Position": 72, "Quarterly": 24, "SemiAnnual": 18, "Annual": 18},
    _BB: {"Swing": 54, "Position": 36, "Quarterly": 24, "SemiAnnual": 12, "Annual": 12},
    "mean_reversion_multi": {"Swing": 108, "Position": 48, "Quarterly": 72, "SemiAnnual": 72,
                             "Annual": 72},
}

# Spot checks of the plan table's bullish values (one row per strategy).
_GRID_SPOT = {
    ("pullback_ema", "Position"): {"ema_period": [20, 35, 50], "trend_ema": [100, 150, 200],
                                   "atr_stop_mult": [1.5, 2.0, 2.5],
                                   "exit_swing_lookback": [20, 30], "tolerance": [0.03, 0.06]},
    ("breakout_base", "Annual"): {"base_lookback": [40, 60, 90], "atr_tight_max": [4.0, 5.0, 6.0],
                                  "volume_mult": [1.1, 1.3],
                                  "measured_move_mult": [2.0, 3.0, 4.0]},
    ("ma_crossover", "Quarterly"): {"fast": [20, 30, 50], "slow": [100, 150, 200],
                                    "lookback": [5, 10, 20], "atr_target_mult": [3.0, 4.0, 5.0]},
    (_RSI, "Swing"): {"rsi_period": [2, 7, 14], "rsi_oversold": [10, 20, 30, 35],
                      "trend_sma": [50, 100, 200], "exit_sma_period": [5, 10, 20]},
    (_BB, "SemiAnnual"): {"bb_period": [50, 100], "bb_std": [2.0, 2.5], "trend_sma": [200],
                          "stop_atr_mult": [1.5, 2.0, 3.0]},
    ("mean_reversion_multi", "Position"): {
        "min_confirmations": [2, 3],
        f"{_VWD}.vwap_lookback": [20, 50], f"{_VWD}.vwap_deviation_pct": [0.02, 0.03, 0.05],
        f"{_RSI}.rsi_oversold": [30, 35], f"{_BB}.bb_std": [2.0, 2.5]},
}


def _combos(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def _n(grid: dict) -> int:
    n = 1
    for v in grid.values():
        n *= len(v)
    return n


def _effective(strategy: str, direction: str, combo: dict) -> dict:
    """A grid combination over the direction baseline (dotted keys -> variant_params)."""
    from app.services.strategy_engine import merge_multi_params
    if strategy != "mean_reversion_multi":
        return {**store.get_active(strategy, direction), **combo}
    top = {k: v for k, v in combo.items() if "." not in k}
    vp: dict = {}
    for k, v in combo.items():
        if "." in k:
            variant, name = k.split(".", 1)
            vp.setdefault(variant, {})[name] = v
    return merge_multi_params(direction, store.get_active(strategy, direction),
                              {**top, "variant_params": vp})


@pytest.mark.parametrize("strategy", _TUNED)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_grid_counts_match_the_plan_table(strategy, direction):
    for h in TUNED_HORIZONS:
        grid = store.get_search_by_horizon(strategy, direction, h)
        assert grid, f"{strategy} {direction} {h}: no grid"
        assert _n(grid) == _GRID_N[strategy][h], (strategy, direction, h)
        assert _n(grid) <= 150


@pytest.mark.parametrize("cell, grid", list(_GRID_SPOT.items()))
def test_bullish_grid_values_match_the_plan_table(cell, grid):
    assert store.get_search_by_horizon(cell[0], "Bullish", cell[1]) == grid


@pytest.mark.parametrize("strategy", _TUNED)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_every_grid_combination_fits_the_signal_window(strategy, direction):
    for h in TUNED_HORIZONS:
        for combo in _combos(store.get_search_by_horizon(strategy, direction, h)):
            need = bars_needed(strategy, _effective(strategy, direction, combo))
            assert need <= SIGNAL_WINDOW_BARS, (strategy, direction, h, combo, need)


def test_bearish_rsi_grids_tune_overbought_mirrored():
    for h in TUNED_HORIZONS:
        bull = store.get_search_by_horizon(_RSI, "Bullish", h)
        bear = store.get_search_by_horizon(_RSI, "Bearish", h)
        assert "rsi_overbought" in bear and "rsi_oversold" not in bear
        assert bear["rsi_overbought"] == [100 - v for v in bull["rsi_oversold"]]
        assert {k: v for k, v in bear.items() if k != "rsi_overbought"} == \
            {k: v for k, v in bull.items() if k != "rsi_oversold"}
        mbull = store.get_search_by_horizon("mean_reversion_multi", "Bullish", h)
        mbear = store.get_search_by_horizon("mean_reversion_multi", "Bearish", h)
        assert f"{_RSI}.rsi_overbought" in mbear and f"{_RSI}.rsi_oversold" not in mbear
        assert mbear[f"{_RSI}.rsi_overbought"] == [100 - v for v in mbull[f"{_RSI}.rsi_oversold"]]


@pytest.mark.parametrize("strategy", ["pullback_ema", "breakout_base", "ma_crossover", _BB])
def test_other_bearish_grids_equal_bullish(strategy):
    for h in TUNED_HORIZONS:
        assert store.get_search_by_horizon(strategy, "Bearish", h) == \
            store.get_search_by_horizon(strategy, "Bullish", h)


def test_grid_parameter_names_are_signal_keywords():
    import inspect
    import app.services.strategy_engine as se
    fns = {"pullback_ema": se.pullback_ema_signal, "breakout_base": se.breakout_base_signal,
           "ma_crossover": se.ma_crossover_signal, _RSI: se.mean_reversion_rsi_signal,
           _BB: se.mean_reversion_bb_signal, _VWD: se.mean_reversion_vwap_daily_signal}
    for strategy in _TUNED:
        for direction in ("Bullish", "Bearish"):
            for h in TUNED_HORIZONS:
                for key in store.get_search_by_horizon(strategy, direction, h):
                    if strategy == "mean_reversion_multi":
                        if key == "min_confirmations":
                            continue
                        variant, key = key.split(".", 1)
                        fn = fns[variant]
                    else:
                        fn = fns[strategy]
                    assert key in inspect.signature(fn).parameters, (strategy, h, key)


def test_production_yaml_writes_no_profile():
    for strategy in _TUNED:
        for direction in ("Bullish", "Bearish"):
            for h in TUNED_HORIZONS:
                assert store.get_profile(strategy, direction, h)[1] == "baseline"


# ── (5) endpoint shape ───────────────────────────────────────────────────────

def test_strategy_profiles_endpoint_shape(tmp_path, monkeypatch):
    data = _real_cfg()
    data["strategies"]["pullback_ema"]["active"]["bullish"]["Quarterly"] = {"tolerance": 0.07}
    _use_cfg(tmp_path, monkeypatch, data)
    from app.routers.config import router
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get("/api/config/strategy-profiles").json()
    assert set(body) == set(_TUNED)
    for strategy in _TUNED:
        assert set(body[strategy]) == {"Bullish", "Bearish"}
        for direction in ("Bullish", "Bearish"):
            block = body[strategy][direction]
            assert block["baseline"] == store.get_active(strategy, direction)
            assert set(block["horizons"]) == set(TUNED_HORIZONS)
    pe = body["pullback_ema"]["Bullish"]
    assert pe["horizons"]["Quarterly"] == {
        "params": {**pe["baseline"], "tolerance": 0.07}, "source": "tuned"}
    assert pe["horizons"]["Swing"] == {"params": pe["baseline"], "source": "baseline"}
    assert pe["baseline"]["tolerance"] == 0.04


# ── (6) scan: omitted fields take the profile ────────────────────────────────

def _card():
    from tests.test_stock_scan_backtest_commission import _measured_trend
    card = MagicMock()
    card.status = "CAUTION"   # no dataclasses.replace on the mock card
    card.score = 70
    card.rules = [_measured_trend()]
    return card


def _bars(n: int = 130):
    return [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
             "volume": 1_000_000, "date": "2024-01-01", "time": i} for i in range(n)]


def _scan_one(req, strategy: str = "pullback_ema"):
    """Run _process_stock with a recording signal function; return (kwargs, card)."""
    from app.routers import stock_scan as ss
    from tests.test_stock_scan_backtest_commission import _fake_bt_result

    ss._BACKTEST_CACHE.clear()
    seen: dict = {}

    bt = _fake_bt_result()
    bt.confidence = None

    def _sig(bars, **kw):
        from app.services.strategy_engine import StrategySignal
        seen.update(kw)
        return StrategySignal(strategy=strategy, direction=req.direction, entry_price=150.0,
                              stop_price=145.0 if req.direction == "Bullish" else 155.0,
                              target_price=160.0 if req.direction == "Bullish" else 140.0,
                              atr=2.0)

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=_card()), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=_bars()), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=_bars(300)), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", return_value=bt), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": 80, "sample_size": 50}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._earnings_days_for", new_callable=AsyncMock, return_value=None), \
             patch("app.routers.stock_scan._stock_earnings_veto", return_value=("CAUTION", None)), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {strategy: _sig}):
            return await ss._process_stock("AAPL", req, "test-scan-id", {}, [])

    card = asyncio.run(run())
    return seen, card


def _req(**kw):
    from app.schemas.stock_scan import StockScanRequest
    base = dict(universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema")
    base.update(kw)
    return StockScanRequest(**base)


_STRATEGY_FIELDS = (
    "pullback_tolerance_pct", "pullback_ema_period", "pullback_trend_ema", "pullback_ma_type",
    "ma_crossover_fast", "ma_crossover_slow", "ma_crossover_lookback", "breakout_volume_mult",
    "rsi_period", "rsi_oversold", "rsi_overbought", "rsi_trend_sma", "require_choppy_regime",
    "mean_reversion_variants", "mean_reversion_min_confirmations", "vwap_lookback",
    "vwap_deviation_pct",
)


def test_request_strategy_fields_default_to_none():
    req = _req()
    for f in _STRATEGY_FIELDS:
        assert getattr(req, f) is None, f
    assert req.params_horizon is None
    assert req.pullback_require_reversal is False


def test_scan_without_strategy_fields_uses_the_yaml_baseline(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _real_cfg())
    seen, card = _scan_one(_req())
    assert seen["tolerance"] == 0.04          # the YAML value, not the old 0.08 default
    assert seen["ema_period"] == 50
    assert card.params_source == "baseline"
    assert card.params_horizon is None


def test_scan_bearish_without_fields_uses_the_bearish_baseline(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _real_cfg())
    seen, _ = _scan_one(_req(direction="Bearish"))
    assert seen["ema_period"] == 35


def _quarterly_cfg() -> dict:
    data = _real_cfg()
    data["strategies"]["pullback_ema"]["active"]["bullish"]["Quarterly"] = {
        "tolerance": 0.07, "ema_period": 35}
    data["strategies"]["pullback_ema"]["active"]["bullish"]["Annual"] = {"tolerance": 0.09}
    return data


def test_scan_uses_the_tuned_profile_for_params_horizon(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _quarterly_cfg())
    seen, card = _scan_one(_req(params_horizon="Quarterly"))
    assert seen["tolerance"] == 0.07
    assert seen["ema_period"] == 35
    assert seen["trend_ema"] == 100           # baseline value not in the profile
    assert card.params_horizon == "Quarterly"
    assert card.params_source == "tuned"


def test_explicit_request_value_still_wins(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _quarterly_cfg())
    seen, _ = _scan_one(_req(params_horizon="Quarterly", pullback_tolerance_pct=0.05))
    assert seen["tolerance"] == 0.05
    assert seen["ema_period"] == 35


def test_hold_without_params_horizon_reads_the_nearest_tuned_horizon(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _quarterly_cfg())
    seen, card = _scan_one(_req(horizon="Position", hold_max_days=185))
    assert seen["tolerance"] == 0.09
    assert card.params_horizon == "Annual"
    assert card.params_source == "tuned"


def test_untuned_horizon_reports_baseline_source(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _quarterly_cfg())
    seen, card = _scan_one(_req(hold_max_days=15))
    assert seen["tolerance"] == 0.04
    assert card.params_horizon == "Swing"
    assert card.params_source == "baseline"


def test_intraday_hold_takes_no_params_horizon(tmp_path, monkeypatch):
    _use_cfg(tmp_path, monkeypatch, _quarterly_cfg())
    seen, card = _scan_one(_req(horizon="Intraday", hold_max_days=60))
    assert seen["tolerance"] == 0.04
    assert card.params_horizon is None


def test_multi_shape_reads_the_multi_profile(tmp_path, monkeypatch):
    from app.routers.stock_scan import _multi_params
    data = _real_cfg()
    data["strategies"]["mean_reversion_multi"]["active"]["bullish"]["Swing"] = {
        "min_confirmations": 3,
        "variant_params": {_VWD: {"vwap_lookback": 10}}}
    _use_cfg(tmp_path, monkeypatch, data)
    shape = _multi_params(_req(strategy="mean_reversion_multi", params_horizon="Swing"))
    assert shape["min_confirmations"] == 3
    assert shape["variant_params"][_VWD]["vwap_lookback"] == 10
    assert shape["variant_params"][_VWD]["vwap_deviation_pct"] == 0.02
    base = _multi_params(_req(strategy="mean_reversion_multi"))
    assert base["min_confirmations"] == 2
    assert base["variant_params"][_VWD]["vwap_lookback"] == 20


# ── (7) watch reversal uses the profile ──────────────────────────────────────

def _watch_bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


@pytest.mark.asyncio
async def test_watch_entry_and_reversal_read_the_profile(tmp_path, monkeypatch):
    data = _real_cfg()
    act = data["strategies"]["pullback_ema"]["active"]
    act["bullish"]["Quarterly"] = {"tolerance": 0.07}
    act["bearish"]["Quarterly"] = {"tolerance": 0.06}
    _use_cfg(tmp_path, monkeypatch, data)
    from app.services.strategy_watch_evaluator import evaluate_all

    calls: list[tuple[str, float]] = []

    def _sig(bars, direction="Bullish", **kw):
        calls.append((direction, kw.get("tolerance")))
        return None

    state = {"phase": "armed", "direction": "Bullish", "entry_price": 100.0,
             "stop_price": 50.0, "target_price": 500.0,
             "last_event": "entry", "last_event_at": None}
    w = {"id": "wch_profile_1", "symbol": "SPY", "strategy_key": "pullback_ema",
         "direction": "Bullish", "params_horizon": "Quarterly",
         "params_override": {}, "enabled": True, "last_state": state}
    st = MagicMock()
    st.list_watches.return_value = [w]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", st), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_watch_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS", {"pullback_ema": _sig}):
        await evaluate_all()
    assert ("Bullish", 0.07) in calls
    assert ("Bearish", 0.06) in calls


# ── (8) multi validation on the merged shape ─────────────────────────────────

def _multi_cfg(tmp_path, monkeypatch, **bullish):
    data = _real_cfg()
    data["strategies"]["mean_reversion_multi"]["active"]["bullish"].update(bullish)
    _use_cfg(tmp_path, monkeypatch, data)


def test_two_variants_against_profile_min_confirmations_3_is_refused(tmp_path, monkeypatch):
    from app.routers.stock_scan import _reject_unsupported_multi_variants
    _multi_cfg(tmp_path, monkeypatch, min_confirmations=3)
    req = _req(strategy="mean_reversion_multi", mean_reversion_variants=[_RSI, _BB])
    with pytest.raises(HTTPException) as ei:
        _reject_unsupported_multi_variants(req)
    assert ei.value.status_code == 422


def test_request_min_confirmations_above_variants_is_refused(tmp_path, monkeypatch):
    from app.routers.stock_scan import _reject_unsupported_multi_variants
    _use_cfg(tmp_path, monkeypatch, _real_cfg())
    req = _req(strategy="mean_reversion_multi", mean_reversion_variants=[_RSI, _BB],
               mean_reversion_min_confirmations=3)
    with pytest.raises(HTTPException) as ei:
        _reject_unsupported_multi_variants(req)
    assert ei.value.status_code == 422


def test_intraday_vwap_in_the_effective_variants_is_refused(tmp_path, monkeypatch):
    from app.routers.stock_scan import _reject_unsupported_multi_variants
    _multi_cfg(tmp_path, monkeypatch, variants=[_RSI, "mean_reversion_vwap"])
    with pytest.raises(HTTPException) as ei:
        _reject_unsupported_multi_variants(_req(strategy="mean_reversion_multi"))
    assert ei.value.status_code == 422
    _use_cfg(tmp_path, monkeypatch, _real_cfg())
    with pytest.raises(HTTPException):
        _reject_unsupported_multi_variants(_req(
            strategy="mean_reversion_multi", mean_reversion_variants=[_RSI, "mean_reversion_vwap"]))


def test_multi_request_without_multi_fields_validates(tmp_path, monkeypatch):
    from app.routers.stock_scan import _reject_unsupported_multi_variants
    _use_cfg(tmp_path, monkeypatch, _real_cfg())
    _reject_unsupported_multi_variants(_req(strategy="mean_reversion_multi"))


# ── (9) saved requests migrate once ──────────────────────────────────────────

_OLD_STOCK_REQUEST = {
    "universe": ["SP500"], "direction": "Bullish", "horizon": "Position",
    "strategy": "pullback_ema", "pullback_tolerance_pct": 0.08, "pullback_ema_period": 50,
    "pullback_require_reversal": True, "breakout_volume_mult": 1.5,
    "mean_reversion_variants": [_RSI, _BB, _VWD], "mean_reversion_min_confirmations": 2,
    "vwap_lookback": 20, "vwap_deviation_pct": 0.02, "hold_max_days": 60,
}


def test_migrate_saved_stock_request_strips_fields_and_sets_params_horizon():
    from app.services.horizon_profiles import migrate_saved_stock_request
    out = migrate_saved_stock_request(copy.deepcopy(_OLD_STOCK_REQUEST))
    for f in _STRATEGY_FIELDS:
        assert f not in out, f
    assert out["params_horizon"] == "Quarterly"
    assert out["pullback_require_reversal"] is True
    assert out["hold_max_days"] == 60
    assert migrate_saved_stock_request(copy.deepcopy(out)) == out


def test_migrate_saved_stock_request_intraday_and_no_hold():
    from app.services.horizon_profiles import migrate_saved_stock_request
    intraday = migrate_saved_stock_request({**_OLD_STOCK_REQUEST, "horizon": "Intraday"})
    assert "params_horizon" not in intraday
    no_hold = {k: v for k, v in _OLD_STOCK_REQUEST.items() if k != "hold_max_days"}
    assert "params_horizon" not in migrate_saved_stock_request(no_hold)


def _entry(mode: str, request: dict) -> dict:
    return {"id": f"e-{mode}", "label": "x", "mode": mode, "profile_id": "p",
            "profile_name": "p", "profile_synced_at": "2026-10-01T00:00:00+00:00",
            "resolved_request": request, "pattern": "fixed_time", "enabled": True,
            "days_of_week": [0], "fire_time": "09:00"}


def test_schedule_store_migrates_stock_requests_once(tmp_path):
    from app.services.scan_schedule_store import ScanScheduleStore
    path = tmp_path / "scan_schedule.yaml"
    options_req = {"universe": ["SP500"], "pullback_tolerance_pct": 0.08}
    path.write_text(yaml.dump({"entries": [_entry("stocks", copy.deepcopy(_OLD_STOCK_REQUEST)),
                                           _entry("options", options_req)]}))
    ScanScheduleStore(path=path)
    first = path.read_text()
    backups = list(tmp_path.glob("scan_schedule.bak.*"))
    assert len(backups) == 1
    raw = yaml.safe_load(first)
    stock = next(e for e in raw["entries"] if e["mode"] == "stocks")["resolved_request"]
    assert "pullback_tolerance_pct" not in stock
    assert stock["params_horizon"] == "Quarterly"
    options = next(e for e in raw["entries"] if e["mode"] == "options")["resolved_request"]
    assert options == options_req                     # options requests are not touched
    store2 = ScanScheduleStore(path=path)
    assert path.read_text() == first                  # second load changes nothing
    assert len(list(tmp_path.glob("scan_schedule.bak.*"))) == 1
    got = store2.get("e-stocks")["resolved_request"]
    assert got == stock
    from app.schemas.stock_scan import StockScanRequest
    assert StockScanRequest.model_validate(got).params_horizon == "Quarterly"


def test_restored_last_stock_request_is_migrated():
    import json
    from app.routers import stock_scan as ss

    row = MagicMock()
    row.last_result_json = None
    row.last_request_json = json.dumps(_OLD_STOCK_REQUEST)
    row.status = "complete"
    row.updated_at = None
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    prev = ss._last_stock_request
    try:
        with patch("app.routers.stock_scan.AsyncSessionLocal", return_value=session_cm):
            asyncio.run(ss.restore_stock_from_db())
        req = ss._last_stock_request
        assert req is not None
        assert req.pullback_tolerance_pct is None
        assert req.params_horizon == "Quarterly"
    finally:
        ss._last_stock_request = prev
