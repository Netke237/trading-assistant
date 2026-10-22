"""A5c — the Analysis page flags every filter on which the stock scan would
drop the symbol (decisions A5B-A5C-LOCKED-2026-09-24 and
A5C-SCOPE-SIX-FILTERS-GO-2026-09-25; plan
docs/superpowers/plans/2026-09-25-a5c-analysis-scan-drop-flags-plan.md).

Every test drives BOTH sides of the mirror on one fixture: `_process_stock`
(the scan) and `_analyze_core` (the Analysis page). A drop shows up as a
REJECT gate flag whose detail is "the scan would drop this: " + the scan's own
reason; card.status is never changed by it.

T1 direction-conviction floor   T6 insufficient intraday history
T2 regime headwind + regime_filter   T7 funnel producer set unchanged
T3 no setup (+ require_choppy_regime)   T8 422 for multi + intraday variant
T4 mean_reversion_multi evaluated for real   T9 card status untouched
T5 backtest gate   T10 malformed floor raises
"""
from __future__ import annotations

import dataclasses
import inspect
import re
import types

import pytest
from fastapi import HTTPException

from app.routers import stock_scan as ss
from app.services.strategy_engine import StrategySignal
from app.schemas.stock_scan import StockAnalysisRequest, StockScanRequest

PREFIX = "the scan would drop this: "

# Trending, so a different window of bars gives different levels (T4).
_BARS = [{"time": 1_700_000_000 + i * 86400, "open": 100 + i * 0.1, "high": 101 + i * 0.1,
          "low": 99 + i * 0.1, "close": 100 + i * 0.1, "volume": 1_000_000} for i in range(300)]


def _intraday(n: int) -> list[dict]:
    return [{"time": 1_700_000_000 + i * 900, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 10_000} for i in range(n)]


@dataclasses.dataclass
class _Rule:
    name: str
    score: int


@dataclasses.dataclass
class _Card:
    score: int = 70
    status: str = "PASS"
    rules: list = dataclasses.field(default_factory=list)


def _bt(passes: bool, summary: str = "38% win over 12 trades"):
    return types.SimpleNamespace(passes_gate=passes, summary_text=summary, n_trades=12,
                                 win_rate=0.38, total_return_pct=1.0, max_drawdown_pct=-2.0,
                                 expectancy=0.1, sharpe=0.5, confidence=None,
                                 n_time_exits=0)


def _offline(monkeypatch, *, conviction: int = 10, trend: int = 60, card_status: str = "PASS",
             min_trend=None, intraday=None, bt_passes: bool = False):
    """Offline fakes shared by both legs. Returns a dict of spies."""
    spies: dict = {"bt_keys": [], "cards": []}

    async def _fake_bars(symbol, start, end):
        return _BARS

    async def _fake_name(client, symbol):
        return "Test Co"

    async def _no_fund(*a, **k):
        return None

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "_get_fundamentals", _no_fund)
    if callable(intraday):
        monkeypatch.setattr(ss, "fetch_intraday_candles", intraday)
    else:
        monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: list(intraday or []))
    monkeypatch.setattr(ss, "compute_directional_hmm", lambda bars: None)
    omm = types.SimpleNamespace(
        state="Bull", p_stay=0.8, stability="Stable", regime_age_days=5,
        avg_regime_duration=10.0, conviction_pct=conviction, conviction_label="x",
        interpretation="", transition_row=[], state_order=[])
    monkeypatch.setattr(ss, "compute_omm", lambda *a, **k: omm)

    def _score(**kw):
        card = _Card(status=card_status, rules=[_Rule("trend", trend)])
        spies["cards"].append(card)
        return card

    monkeypatch.setattr(ss, "score_stock", _score)
    monkeypatch.setattr(ss, "load_direction_conviction_min_trend", lambda d, h: min_trend)

    real_key = ss._backtest_key

    def _key(symbol, strategy, direction, bars, params=None, **kw):
        spies["bt_keys"].append((strategy, len(bars), bars[0]["time"], bars[-1]["time"],
                                 real_key(symbol, strategy, direction, bars, params, **kw)))
        return real_key(symbol, strategy, direction, bars, params, **kw)

    monkeypatch.setattr(ss, "_backtest_key", _key)
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: _bt(bt_passes))

    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": None, "sample_size": 0})
    return spies


async def _scan(**kw) -> dict:
    req = StockScanRequest(universe=["TEST"], **{"direction": "Bullish", "horizon": "Swing",
                                                 "strategy": "pullback_ema", **kw})
    return await ss._process_stock("TEST", req, "scan-1", {"TEST": {"last": 130.0}}, [],
                                   fund_gate=None)


async def _analyze(**kw):
    req = StockAnalysisRequest(symbol="TEST", **{"direction": "Bullish", "horizon": "Swing",
                                                 "strategy": "pullback_ema", **kw})
    return await ss._analyze_core("TEST", req)


def _flags(core, gate):
    return [g for g in core.gate_flags if g["gate"] == gate]


def _one_reject(core, gate, scan_reason, *, exact=True):
    fl = _flags(core, gate)
    assert len(fl) == 1, core.gate_flags
    assert fl[0]["status"] == "REJECT"
    if exact:
        assert fl[0]["detail"] == PREFIX + scan_reason
    else:
        assert fl[0]["detail"].startswith(PREFIX + scan_reason)


def _signal_stub(monkeypatch, name, result=None, calls=None):
    def _fn(bars, direction, **kw):
        if calls is not None:
            calls.append({"name": name, "bars": bars, **kw})
        return result
    monkeypatch.setitem(ss._SIGNAL_FNS, name, _fn)


def _firing_signal(strategy):
    return StrategySignal(strategy=strategy, direction="Bullish", entry_price=130.0,
                          stop_price=125.0, target_price=140.0, atr=1.0, targets=[140.0])


# ── T1 direction-conviction floor ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t1_conviction_floor_drop_mirrors_the_scan(monkeypatch):
    _offline(monkeypatch, trend=20, min_trend=40)
    scan = await _scan(direction="Bearish", horizon="Position")
    assert scan["reason"] == "direction_conviction: trend 20 < 40 for Bearish Position"
    core = await _analyze(direction="Bearish", horizon="Position")
    _one_reject(core, "direction_conviction", scan["reason"])
    # Literal pin, hand-written (not built from the helper).
    assert _flags(core, "direction_conviction")[0]["detail"] == \
        "the scan would drop this: direction_conviction: trend 20 < 40 for Bearish Position"
    # The direction-conviction flag does not cap the card; the independent
    # P0B bearish Unvalidated gate now caps this otherwise-PASS verdict.
    assert core.card.status == "CAUTION"


@pytest.mark.asyncio
@pytest.mark.parametrize("trend,min_trend", [(60, 40), (40, 40), (5, None)])
async def test_t1_conviction_no_flag_when_passing_or_exempt(monkeypatch, trend, min_trend):
    _offline(monkeypatch, trend=trend, min_trend=min_trend)
    _signal_stub(monkeypatch, "pullback_ema", None)
    scan = await _scan()
    assert not scan["reason"].startswith("direction_conviction")
    core = await _analyze()
    assert not _flags(core, "direction_conviction")


# ── T2 regime headwind ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("conviction", [-20, -15])   # -15: exactly at the threshold
async def test_t2_headwind_with_regime_filter_is_a_drop(monkeypatch, conviction):
    _offline(monkeypatch, conviction=conviction)
    kw = dict(regime_filter=True, regime_headwind_caution_pct=-15, regime_headwind_reject_pct=-40)
    scan = await _scan(**kw)
    assert scan["reason"] == "regime headwind"
    core = await _analyze(**kw)
    _one_reject(core, "regime_headwind", scan["reason"], exact=False)
    assert _flags(core, "regime_headwind")[0]["detail"] == \
        f"the scan would drop this: regime headwind (conviction {conviction}%)"
    assert core.card.status == "PASS"


@pytest.mark.asyncio
async def test_t2_headwind_without_regime_filter_stays_caution(monkeypatch):
    _offline(monkeypatch, conviction=-20)
    _signal_stub(monkeypatch, "pullback_ema", None)
    kw = dict(regime_filter=False, regime_headwind_caution_pct=-15, regime_headwind_reject_pct=-40)
    scan = await _scan(**kw)
    assert scan["reason"] == "no pullback_ema setup"      # went past the headwind
    core = await _analyze(**kw)
    fl = _flags(core, "regime_headwind")
    assert fl == [{"gate": "regime_headwind", "status": "CAUTION", "detail": "conviction -20%"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("regime_filter", [True, False])
async def test_t2_no_headwind_no_flag(monkeypatch, regime_filter):
    _offline(monkeypatch, conviction=-5)
    _signal_stub(monkeypatch, "pullback_ema", None)
    kw = dict(regime_filter=regime_filter, regime_headwind_caution_pct=-15,
              regime_headwind_reject_pct=-40)
    scan = await _scan(**kw)
    assert scan["reason"] != "regime headwind"
    core = await _analyze(**kw)
    assert not _flags(core, "regime_headwind")


# ── T3 no setup ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t3_no_setup_is_a_drop(monkeypatch):
    _offline(monkeypatch)
    _signal_stub(monkeypatch, "pullback_ema", None)
    scan = await _scan()
    assert scan["reason"] == "no pullback_ema setup"
    core = await _analyze()
    _one_reject(core, "signal", scan["reason"])
    assert _flags(core, "signal")[0]["detail"] == "the scan would drop this: no pullback_ema setup"
    assert core.card.status == "PASS"


@pytest.mark.asyncio
async def test_t3_require_choppy_regime_reaches_the_signal_in_both_paths(monkeypatch):
    _offline(monkeypatch)
    calls: list = []
    _signal_stub(monkeypatch, "mean_reversion_rsi", None, calls)
    scan = await _scan(strategy="mean_reversion_rsi", require_choppy_regime=True)
    core = await _analyze(strategy="mean_reversion_rsi", require_choppy_regime=True)
    assert [c["require_choppy_regime"] for c in calls] == [True, True]
    _one_reject(core, "signal", scan["reason"])


@pytest.mark.asyncio
async def test_t3_a_raising_signal_fn_is_a_drop_on_both_sides(monkeypatch):
    _offline(monkeypatch)

    def _boom(bars, direction, **kw):
        raise ValueError("bad bars")
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", _boom)
    scan = await _scan()
    assert scan["reason"] == "bad bars"            # the scan's outer `except`
    core = await _analyze()
    _one_reject(core, "signal", "no pullback_ema setup")


# ── T4 mean_reversion_multi ──────────────────────────────────────────────────

def _multi_stubs(monkeypatch, fire: set[str], calls: list):
    """Variant stubs whose levels are derived from the bars they receive, so a
    different window gives a different signal."""
    def _make(name):
        def _fn(bars, direction, **kw):
            calls.append({"name": name, "bars": bars, "kw": kw})
            if name not in fire:
                return None
            entry = bars[-1]["close"]
            stop = min(b["low"] for b in bars)
            return StrategySignal(strategy=name, direction="Bullish", entry_price=entry,
                                  stop_price=stop, target_price=entry + 2 * (entry - stop),
                                  atr=1.0, targets=[entry + 2 * (entry - stop)])
        return _fn
    for v in ("mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap_daily"):
        monkeypatch.setitem(ss._SIGNAL_FNS, v, _make(v))


_MULTI = dict(strategy="mean_reversion_multi",
              mean_reversion_variants=["mean_reversion_rsi", "mean_reversion_bb",
                                       "mean_reversion_vwap_daily"],
              mean_reversion_min_confirmations=2)


@pytest.mark.asyncio
async def test_t4_multi_is_evaluated_for_real_and_backtested_like_the_scan(monkeypatch):
    spies = _offline(monkeypatch, bt_passes=False)
    calls: list = []
    _multi_stubs(monkeypatch, {"mean_reversion_rsi", "mean_reversion_bb"}, calls)
    resolved: list = []
    real_multi = ss._multi_signal

    def _spy_multi(symbol, req, bars, params=None):
        out = real_multi(symbol, req, bars, params)
        resolved.append(out[0])
        return out
    monkeypatch.setattr(ss, "_multi_signal", _spy_multi)

    scan = await _scan(**_MULTI)
    assert scan["reason"] == "backtest gate: 38% win over 12 trades"   # got past the signal
    n_scan_calls = len(calls)
    core = await _analyze(**_MULTI)

    # Both legs hand every variant the identical last SIGNAL_WINDOW_BARS daily
    # bars (STOCKS-HORIZON-T1 H1; all 300 here), no current_price.
    from app.services.strategy_engine import SIGNAL_WINDOW_BARS
    assert len(_BARS) < SIGNAL_WINDOW_BARS
    assert n_scan_calls == 3 and len(calls) == 6
    for c in calls:
        assert len(c["bars"]) == len(_BARS)
        assert c["bars"][0] is _BARS[0] and c["bars"][-1] is _BARS[-1]
        assert "current_price" not in c["kw"]
    assert [c["name"] for c in calls[:3]] == [c["name"] for c in calls[3:]]

    # Real multi signal, identical levels on both sides.
    assert core.signal is not None and core.signal.strategy == "mean_reversion_multi"
    assert len(resolved) == 2 and resolved[0] == resolved[1] == core.signal
    assert not _flags(core, "signal")

    # Backtested as multi's own vote on the daily bars, same cache key as the
    # scan (STOCKS-HORIZON-T1 H3; was the mean_reversion_rsi proxy).
    assert len(spies["bt_keys"]) == 2
    (s_strat, s_n, s_t0, s_t1, s_key), (a_strat, a_n, a_t0, a_t1, a_key) = spies["bt_keys"]
    assert s_strat == a_strat == "mean_reversion_multi"
    assert (s_n, s_t0, s_t1) == (a_n, a_t0, a_t1) == (300, _BARS[0]["time"], _BARS[-1]["time"])
    assert s_key == a_key
    assert core.bt_result is not None
    _one_reject(core, "backtest", scan["reason"])


@pytest.mark.asyncio
async def test_t4_multi_cache_miss_runs_the_multi_backtest_in_both_legs(monkeypatch):
    """Code round 1 (F1): the cache stub above always answers, so nothing
    exercised the run_strategy_backtest CALL. On a miss, a wrong strategy there
    would be cached under the scan's key and poison later scans too."""
    _offline(monkeypatch)
    _multi_stubs(monkeypatch, {"mean_reversion_rsi", "mean_reversion_bb"}, [])
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: None)
    monkeypatch.setattr(ss, "_BACKTEST_CACHE", {})
    monkeypatch.setattr(ss, "_BACKTEST_POOL", None)        # default thread pool
    runs: list = []

    def _spy_run(bars, *, strategy, direction, min_trades, min_win_rate, params, commission,
                 hold_max_days, detail_collector=None):
        runs.append({"strategy": strategy, "bars": bars, "params": params})
        return _bt(False)
    monkeypatch.setattr(ss, "run_strategy_backtest", _spy_run)

    scan = await _scan(**_MULTI)
    assert scan["reason"] == "backtest gate: 38% win over 12 trades"
    core = await _analyze(**_MULTI)
    _one_reject(core, "backtest", scan["reason"])

    # STOCKS-HORIZON-T1 H3: multi's own vote over its params shape (was the
    # mean_reversion_rsi proxy with the rsi params).
    expected_params = ss._multi_params(StockScanRequest(
        universe=["TEST"], direction="Bullish", horizon="Swing", **_MULTI))
    assert len(runs) == 2
    for r in runs:
        assert r["strategy"] == "mean_reversion_multi"
        assert r["bars"] is _BARS
        assert r["params"] == expected_params


@pytest.mark.asyncio
async def test_t4_multi_too_few_confirmations(monkeypatch):
    _offline(monkeypatch)
    _multi_stubs(monkeypatch, {"mean_reversion_rsi"}, [])
    scan = await _scan(**_MULTI)
    assert scan["reason"] == "no mean_reversion_multi: 1/3 signals fired"
    core = await _analyze(**_MULTI)
    _one_reject(core, "signal", scan["reason"])
    assert _flags(core, "signal")[0]["detail"] == \
        "the scan would drop this: no mean_reversion_multi: 1/3 signals fired"
    assert core.signal is None and core.bt_result is None
    assert core.card.status == "PASS"


@pytest.mark.asyncio
async def test_t4_multi_no_valid_combined_levels(monkeypatch):
    _offline(monkeypatch)
    _multi_stubs(monkeypatch, {"mean_reversion_rsi", "mean_reversion_bb"}, [])
    # The vote resolves inside strategy_engine.multi_signal (STOCKS-HORIZON-T1 H3).
    import app.services.strategy_engine as se
    monkeypatch.setattr(se, "resolve_multi_signal", lambda fired, strategy: None)
    scan = await _scan(**_MULTI)
    assert scan["reason"] == "mean_reversion_multi: variants produced no valid combined levels"
    core = await _analyze(**_MULTI)
    _one_reject(core, "signal", scan["reason"])


# ── T5 backtest gate ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t5_backtest_gate_is_a_drop(monkeypatch):
    _offline(monkeypatch, bt_passes=False)
    # A measured confidence: this test pins that the drop flag leaves the card
    # PASS, and a missing one now caps it at CAUTION (STOCKS-HORIZON-P0A A5).
    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": 70, "sample_size": 30})
    _signal_stub(monkeypatch, "pullback_ema", _firing_signal("pullback_ema"))
    scan = await _scan()
    assert scan["reason"] == "backtest gate: 38% win over 12 trades"
    core = await _analyze()
    _one_reject(core, "backtest", scan["reason"])
    assert _flags(core, "backtest")[0]["detail"] == \
        "the scan would drop this: backtest gate: 38% win over 12 trades"
    assert core.card.status == "PASS"


@pytest.mark.asyncio
async def test_t5_backtest_passing_no_flag(monkeypatch):
    _offline(monkeypatch, bt_passes=True)
    _signal_stub(monkeypatch, "pullback_ema", _firing_signal("pullback_ema"))
    scan = await _scan()
    assert not str(scan.get("reason", "") if isinstance(scan, dict) else "").startswith("backtest gate")
    core = await _analyze()
    assert not _flags(core, "backtest")


# ── T6 insufficient intraday history ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_t6_intraday_history_29_bars_is_a_drop(monkeypatch):
    _offline(monkeypatch, intraday=_intraday(29))
    _signal_stub(monkeypatch, "mean_reversion_vwap", None)
    scan = await _scan(strategy="mean_reversion_vwap")
    assert scan["reason"] == "insufficient intraday history"
    core = await _analyze(strategy="mean_reversion_vwap")
    _one_reject(core, "intraday_history", scan["reason"])
    assert _flags(core, "intraday_history")[0]["detail"] == \
        "the scan would drop this: insufficient intraday history"
    assert core.card.status == "PASS"


@pytest.mark.asyncio
async def test_t6_intraday_history_30_bars_no_flag(monkeypatch):
    _offline(monkeypatch, intraday=_intraday(30))
    _signal_stub(monkeypatch, "mean_reversion_vwap", None)
    scan = await _scan(strategy="mean_reversion_vwap")
    assert scan["reason"] == "no mean_reversion_vwap setup"
    core = await _analyze(strategy="mean_reversion_vwap")
    assert not _flags(core, "intraday_history")


@pytest.mark.asyncio
async def test_t6_intraday_fetch_failure_is_a_drop_on_both_sides(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("feed down")
    _offline(monkeypatch, intraday=_raise)
    scan = await _scan(strategy="mean_reversion_vwap")
    assert scan["reason"] == "insufficient intraday history"
    core = await _analyze(strategy="mean_reversion_vwap")
    _one_reject(core, "intraday_history", scan["reason"])


@pytest.mark.asyncio
async def test_t6_daily_strategy_ignores_intraday_history(monkeypatch):
    _offline(monkeypatch, intraday=[])
    _signal_stub(monkeypatch, "pullback_ema", None)
    scan = await _scan()
    assert scan["reason"] == "no pullback_ema setup"
    core = await _analyze()
    assert not _flags(core, "intraday_history")


# ── T7 funnel producer set ───────────────────────────────────────────────────

def test_t7_reason_producer_set_is_unchanged():
    """The funnel guard finds reason producers by regex over the module source
    (test_stock_scan_funnel.py). The A5c helpers return the scan's rejection
    dict so every literal stays visible to it; the set is pinned here so a
    helper returning a bare string (hiding its literal) turns this red."""
    src = inspect.getsource(ss)
    emitted = {s.strip() for s in re.findall(r'"reason":\s*\(?\s*f?"([^"{]*)', src)} - {""}
    assert emitted == {
        "REJECT score=", "backtest gate:", "confidence gate REJECT:",
        "direction_conviction: trend", "direction_conviction_unmeasured: no trend measurement for",
        "insufficient history", "insufficient intraday history",
        "mean_reversion_multi: variants produced no valid combined levels", "no",
        "no mean_reversion_multi:", "no price data", "price $", "regime headwind",
        "unknown strategy",
        # Not a gate: a candidate ranked below the shortlist cap (bucket failed_shortlist).
        "Shortlist cap:",
        # STOCKS-HORIZON-P0A A2: a `scope: scan` symbol from universe_exclusions.yaml
        # (bucket failed_history).
        "Excluded (data):",
    }


# ── T8 422 for multi with the intraday variant ───────────────────────────────

_BAD_MULTI = dict(strategy="mean_reversion_multi",
                  mean_reversion_variants=["mean_reversion_rsi", "mean_reversion_vwap"],
                  mean_reversion_min_confirmations=2)


@pytest.mark.asyncio
async def test_t8_analysis_refuses_multi_with_the_intraday_variant(monkeypatch):
    called = []

    async def _never(*a, **k):
        called.append(1)
    monkeypatch.setattr(ss, "_analyze_core", _never)
    with pytest.raises(HTTPException) as a_exc:
        await ss.analyze_stock(StockAnalysisRequest(symbol="TEST", **_BAD_MULTI))
    with pytest.raises(HTTPException) as s_exc:
        await ss.run_stock_scan(StockScanRequest(universe=["SP500"], direction="Bullish",
                                                 horizon="Swing", **_BAD_MULTI), db=None)
    assert a_exc.value.status_code == s_exc.value.status_code == 422
    assert a_exc.value.detail == s_exc.value.detail
    assert "mean_reversion_vwap (intraday) is not supported" in a_exc.value.detail
    assert not called


# ── T9 card status untouched ─────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("card_status", ["PASS", "CAUTION"])
async def test_t9_every_drop_at_once_leaves_the_card_alone(monkeypatch, card_status):
    _offline(monkeypatch, trend=10, min_trend=40, conviction=-30, card_status=card_status,
             intraday=_intraday(5))
    _signal_stub(monkeypatch, "mean_reversion_vwap", None)
    core = await _analyze(strategy="mean_reversion_vwap", regime_filter=True,
                          regime_headwind_caution_pct=-15, regime_headwind_reject_pct=-40)
    gates = {g["gate"]: g["status"] for g in core.gate_flags}
    for gate in ("intraday_history", "direction_conviction", "regime_headwind", "signal"):
        assert gates[gate] == "REJECT", core.gate_flags
    assert core.card.status == card_status


# ── T10 malformed floor ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t10_malformed_floor_raises_not_a_flag(monkeypatch):
    _offline(monkeypatch)

    def _bad(d, h):
        raise ValueError("direction_conviction malformed")
    monkeypatch.setattr(ss, "load_direction_conviction_min_trend", _bad)
    with pytest.raises(ValueError, match="malformed"):
        await _analyze()
