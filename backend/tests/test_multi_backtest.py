"""STOCKS-HORIZON-T1 H3: mean_reversion_multi has one params shape
(``{"variants", "min_confirmations", "variant_params"}``) built by
``merge_multi_params`` and used by the live loop and the backtest, and the
backtest trades multi's own vote at ``resolve_multi_signal``'s combined levels
instead of the old ``mean_reversion_rsi`` stand-in.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

import app.services.strategy_engine as se
from app.schemas.stock_scan import StockScanRequest
from app.services.strategy_backtest import run_strategy_backtest_trades
from app.services.strategy_engine import StrategySignal

_RSI, _BB, _VWD = "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap_daily"


# ── a stubbed vote on a hand-built series ────────────────────────────────────
# Each variant reads a flag off the window's last bar (its volume): 1001 = only
# rsi fires, 1002 = rsi and bb fire. vwap_daily never fires.
#   rsi alone: entry 100, stop 98, target 102.
#   bb:        entry 100, stop 97, target 104.
#   resolved (rsi + bb): widest stop 97, tightest rung >= 0.5R 102.

_DOUBLE = (80, 120)   # signal bars where two variants fire
_SINGLE = (100, 140)  # signal bars where only rsi fires


def _stub(name: str, fires_on: set[float], stop_off: float, target_off: float):
    def _fn(bars, direction="Bullish", **kw):
        if bars[-1]["volume"] not in fires_on:
            return None
        entry = bars[-1]["close"]
        return StrategySignal(strategy=name, direction="Bullish", entry_price=entry,
                              stop_price=entry - stop_off, target_price=entry + target_off,
                              atr=1.0, targets=[entry + target_off])
    return _fn


def _vote_series() -> list[dict]:
    d0 = date(2023, 1, 2)
    bars = [{"time": (d0 + timedelta(days=i)).isoformat(), "open": 100.0, "high": 100.3,
             "low": 99.9, "close": 100.0, "volume": 1000.0} for i in range(200)]
    for s in _DOUBLE + _SINGLE:
        bars[s]["volume"] = 1002.0 if s in _DOUBLE else 1001.0
        bars[s + 1].update(open=100.0, high=100.5, low=99.8, close=100.0)   # entry fills at 100
        bars[s + 2].update(open=99.0, high=100.0, low=97.5, close=99.0)     # under 98, over 97
        bars[s + 3].update(open=100.0, high=102.5, low=99.5, close=101.0)   # through 102
    return bars


@pytest.fixture
def stub_variants(monkeypatch):
    monkeypatch.setattr(se, "mean_reversion_rsi_signal", _stub(_RSI, {1001.0, 1002.0}, 2.0, 2.0))
    monkeypatch.setattr(se, "mean_reversion_bb_signal", _stub(_BB, {1002.0}, 3.0, 4.0))
    monkeypatch.setattr(se, "mean_reversion_vwap_daily_signal", _stub(_VWD, set(), 1.0, 1.0))


def _shape(min_confirmations: int) -> dict:
    return {"variants": [_RSI, _BB, _VWD], "min_confirmations": min_confirmations,
            "variant_params": {_RSI: {}, _BB: {}, _VWD: {}}}


def _trades(params: dict):
    result, trades = run_strategy_backtest_trades(
        _vote_series(), strategy="mean_reversion_multi", direction="Bullish",
        min_trades=1, params=params)
    return result, trades


# ── (1) trades only where the vote passes, at the combined levels ────────────

def test_backtest_trades_only_on_confirmed_bars_at_the_resolved_levels(stub_variants):
    bars = _vote_series()
    result, trades = _trades(_shape(2))
    assert result.strategy == "mean_reversion_multi"
    assert result.n_trades == len(_DOUBLE) == len(trades)
    assert [t.entry_date.isoformat() for t in trades] == [bars[s + 1]["time"] for s in _DOUBLE]
    for t in trades:
        assert t.entry_price == pytest.approx(100.0)
        # Survived the 97.5 low (resolved stop 97, not rsi's 98), exited at the
        # resolved target 102 (not bb's 104).
        assert t.exit_reason == "target"
        assert t.exit_price == pytest.approx(102.0)


def test_one_confirmation_also_trades_the_single_variant_bars(stub_variants):
    bars = _vote_series()
    _, trades = _trades(_shape(1))
    assert [t.entry_date.isoformat() for t in trades] == \
        [bars[s + 1]["time"] for s in sorted(_DOUBLE + _SINGLE)]
    singles = [t for t in trades if t.entry_date.isoformat() in {bars[s + 1]["time"] for s in _SINGLE}]
    # rsi alone keeps its own stop 98: the 97.5 low takes it (open 99 > 98, fills at 98).
    assert all(t.exit_reason == "stop" and t.exit_price == pytest.approx(98.0) for t in singles)


# ── (2) a vote that cannot pass places no trade ──────────────────────────────

def test_three_confirmations_with_a_variant_that_never_fires_trades_nothing(stub_variants):
    result, trades = _trades(_shape(3))
    assert result.n_trades == 0 and trades == []
    result2, _ = _trades(_shape(2))
    assert result2.n_trades > 0          # the same series does trade at 2


def test_multi_signal_rejects_the_intraday_vwap_variant():
    with pytest.raises(ValueError):
        se.multi_signal([], direction="Bullish",
                        params={"variants": [_RSI, "mean_reversion_vwap"], "min_confirmations": 1,
                                "variant_params": {}})


# ── (3) scan parity and the backtest key ─────────────────────────────────────

def _req(**kw) -> StockScanRequest:
    return StockScanRequest(universe=["AAA"], direction="Bullish", horizon="Swing",
                            strategy="mean_reversion_multi", **kw)


def test_scan_signal_equals_multi_signal_on_the_same_window_and_shape():
    from app.routers import stock_scan as ss
    from tests.test_signal_window import _mean_reversion_series

    bars = _mean_reversion_series()
    req = _req()
    shape = ss._multi_params(req)
    sig, drop = ss._multi_signal("AAA", req, bars, shape)
    assert drop is None and sig is not None
    direct = se.multi_signal(bars[-se.SIGNAL_WINDOW_BARS:], direction="Bullish", params=shape)
    assert direct is not None
    assert (sig.entry_price, sig.stop_price, sig.target_price, sig.targets) == \
        (direct.entry_price, direct.stop_price, direct.target_price, direct.targets)


def test_backtest_key_changes_with_any_nested_value_and_ignores_key_order():
    from app.routers import stock_scan as ss
    from tests.test_signal_window import _mean_reversion_series

    bars = _mean_reversion_series()
    shape = ss._multi_params(_req())

    def key(p):
        return ss._backtest_key("AAA", "mean_reversion_multi", "Bullish", bars, p)

    base = key(shape)
    edits = [
        lambda p: p.__setitem__("min_confirmations", 3),
        lambda p: p.__setitem__("variants", [_RSI, _BB]),
        lambda p: p["variant_params"][_RSI].__setitem__("rsi_oversold", 25.0),
        lambda p: p["variant_params"][_BB].__setitem__("bb_std", 2.5),
        lambda p: p["variant_params"][_VWD].__setitem__("vwap_lookback", 30),
    ]
    for edit in edits:
        changed = copy.deepcopy(shape)
        edit(changed)
        assert key(changed) != base

    # Canonical JSON: the same values in another insertion order hash the same.
    reordered = {"variant_params": {v: dict(reversed(list(shape["variant_params"][v].items())))
                                    for v in reversed(list(shape["variant_params"]))},
                 "min_confirmations": shape["min_confirmations"],
                 "variants": list(shape["variants"])}
    assert reordered == shape
    assert key(reordered) == base


# ── (4) the YAML baseline reproduces today's live result ─────────────────────

def test_yaml_baseline_is_todays_frontend_values():
    from app.services.strategy_param_store import get_active, get_exit
    expected = {"variants": [_RSI, _BB, _VWD], "min_confirmations": 2,
                "variant_params": {_VWD: {"vwap_lookback": 20, "vwap_deviation_pct": 0.02}}}
    assert get_active("mean_reversion_multi", "Bullish") == expected
    assert get_active("mean_reversion_multi", "Bearish") == expected
    assert get_exit("mean_reversion_multi") == {}


def test_yaml_baseline_reproduces_the_pre_h3_live_signal():
    """Pinned before H3 from ``_multi_signal`` on this fixture (default
    request, min_confirmations 2): rsi and bb fire, vwap_daily does not."""
    from app.routers import stock_scan as ss
    from tests.test_signal_window import _mean_reversion_series

    bars = _mean_reversion_series()
    req = _req()
    sig, drop = ss._multi_signal("AAA", req, bars, ss._multi_params(req))
    assert drop is None
    assert (sig.entry_price, sig.stop_price, sig.target_price, sig.targets) == \
        (355.9, 348.47, 382.49, [382.49, 409.4])
    assert sig.detail["fired"] == [_BB, _RSI]


def test_scan_shape_per_variant_params_equal_the_pre_h3_merge():
    """Live behaviour is unchanged by the move: each variant's effective params
    are today's exit < active(direction) < request merge."""
    from app.routers import stock_scan as ss

    for direction in ("Bullish", "Bearish"):
        req = StockScanRequest(universe=["AAA"], direction=direction, horizon="Swing",
                               strategy="mean_reversion_multi")
        shape = ss._multi_params(req)
        assert shape["variants"] == [_RSI, _BB, _VWD]
        assert shape["min_confirmations"] == 2
        for v in shape["variants"]:
            extra = ({"vwap_lookback": 20, "vwap_deviation_pct": 0.02} if v == _VWD else {})
            assert shape["variant_params"][v] == ss._merge_strategy_params(
                v, direction, {**ss._SIGNAL_KWARGS.get(v, lambda r: {})(req), **extra})


# ── merge_multi_params: precedence; the variant base is the direction baseline ─

_MERGE_YAML = """
strategies:
  mean_reversion_rsi:
    active:
      bullish: {rsi_oversold: 30, trend_sma: 200, rsi_period: 14}
      bearish: {rsi_oversold: 25, trend_sma: 100, rsi_period: 14}
    exit: {exit_sma_period: 20, atr_target_mult: 2.5}
  mean_reversion_bb:
    active:
      bullish: {bb_std: 2.0}
      bearish: {bb_std: 2.5}
    exit: {rr_target_mult: 2.0}
"""


@pytest.fixture
def merge_cfg(tmp_path, monkeypatch):
    import app.services.strategy_param_store as store
    p = tmp_path / "strategy_params.yaml"
    p.write_text(_MERGE_YAML, encoding="utf-8")
    monkeypatch.setattr(store, "CFG", p)


def test_merge_multi_params_precedence(merge_cfg):
    profile = {"variants": [_RSI, _BB], "min_confirmations": 2,
               "variant_params": {_RSI: {"rsi_period": 7, "atr_target_mult": 3.0}}}
    before = copy.deepcopy(profile)
    out = se.merge_multi_params(
        "Bearish", profile,
        {"variants": None, "min_confirmations": 1,
         "variant_params": {_RSI: {"trend_sma": 150, "rsi_oversold": None}}})
    assert out == {
        "variants": [_RSI, _BB],
        "min_confirmations": 1,
        "variant_params": {
            # exit < bearish baseline < profile < request (None = not set)
            _RSI: {"exit_sma_period": 20, "atr_target_mult": 3.0, "rsi_oversold": 25,
                   "trend_sma": 150, "rsi_period": 7},
            _BB: {"rr_target_mult": 2.0, "bb_std": 2.5},
        },
    }
    assert profile == before                          # inputs not mutated
    out["variant_params"][_BB]["bb_std"] = 9.9
    assert se.merge_multi_params("Bearish", profile, {})["variant_params"][_BB]["bb_std"] == 2.5


def test_merge_multi_params_variant_base_is_always_the_direction_baseline(merge_cfg, monkeypatch):
    """The variant base is get_exit(v) | get_active(v, direction) and nothing
    else, so a later tuned profile of the standalone strategy cannot reach multi."""
    import app.services.strategy_param_store as store
    seen: list = []
    real = store.get_active

    def _spy(strategy, direction="Bullish"):
        seen.append((strategy, direction))
        return real(strategy, direction)
    monkeypatch.setattr(store, "get_active", _spy)

    profile = {"variants": [_RSI, _BB], "min_confirmations": 2, "variant_params": {}}
    bull = se.merge_multi_params("Bullish", profile, {})
    bear = se.merge_multi_params("Bearish", profile, {})
    assert bull["variant_params"][_RSI] == {"exit_sma_period": 20, "atr_target_mult": 2.5,
                                             "rsi_oversold": 30, "trend_sma": 200, "rsi_period": 14}
    assert bear["variant_params"][_RSI]["rsi_oversold"] == 25
    assert bear["variant_params"][_BB] == {"rr_target_mult": 2.0, "bb_std": 2.5}
    assert set(seen) == {(_RSI, "Bullish"), (_BB, "Bullish"), (_RSI, "Bearish"), (_BB, "Bearish")}
