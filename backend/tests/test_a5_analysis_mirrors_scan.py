"""A5 — the Analysis page mirrors the stock scan (decisions
A5-ANALYSIS-MIRRORS-SCAN / A5-MIRROR-LAST-SCAN-RUN, 2026-09-24).

B1 _analyze_core resolves the regime gate with the Step-3 overrides.
B2 the confidence CAUTION cap the scan applies.
B3 the backtest cache key carries the gate thresholds.
B4 GET /stock-scan/last-request serves the request only when it produced the
   result on record.
"""
from __future__ import annotations

import asyncio
import dataclasses
import types
from unittest.mock import MagicMock

import pytest

from app.routers import stock_scan as ss
from app.schemas.stock_scan import StockAnalysisRequest, StockScanRequest, StockScanResult


_BARS = [{"time": 1_700_000_000 + i * 86400, "open": 100, "high": 101, "low": 99,
          "close": 100 + (i % 3), "volume": 1_000_000} for i in range(300)]


@dataclasses.dataclass
class _Card:
    score: int = 70
    status: str = "PASS"
    rules: list = dataclasses.field(default_factory=list)


def _offline(monkeypatch, *, conviction: int = -12, card_status: str = "PASS"):
    async def _fake_bars(symbol, start, end):
        return _BARS

    async def _fake_name(client, symbol):
        return "Test Co"

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    async def _daily(symbol, count):
        return _BARS
    monkeypatch.setattr(ss, "get_daily_regime_bars", _daily)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: [])
    monkeypatch.setattr(ss, "compute_directional_hmm", lambda bars: None)
    omm = types.SimpleNamespace(
        state="Bull", p_stay=0.8, stability="Stable", regime_age_days=5,
        avg_regime_duration=10.0, conviction_pct=conviction, conviction_label="Headwind",
        interpretation="", transition_row=[], state_order=[])
    monkeypatch.setattr(ss, "compute_omm", lambda *a, **k: omm)
    seen: dict = {}

    def _score(**kw):
        seen.update(kw)
        return _Card(status=card_status)

    monkeypatch.setattr(ss, "score_stock", _score)
    return seen


def _flags(core, gate):
    return [g for g in core.gate_flags if g["gate"] == gate]


# ── B1 ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b1_step3_headwind_overrides_reach_the_analysis_gate(monkeypatch):
    seen = _offline(monkeypatch, conviction=-12)
    req = StockAnalysisRequest(symbol="TEST", regime_headwind_caution_pct=-10,
                               regime_headwind_reject_pct=-11)
    core = await ss._analyze_core("TEST", req)
    assert seen["regime_gate"]["headwind_caution_pct"] == -10
    assert seen["regime_gate"]["headwind_reject_pct"] == -11
    # -12 <= -10: the overridden caution threshold raises the headwind flag.
    assert _flags(core, "regime_headwind")


@pytest.mark.asyncio
async def test_b1_without_overrides_the_yaml_gate_stands(monkeypatch):
    seen = _offline(monkeypatch, conviction=-12)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(symbol="TEST"))
    yaml_gate = ss._load_full_scoring_cfg()["regime_gate"]
    assert seen["regime_gate"] == dict(yaml_gate)
    assert not _flags(core, "regime_headwind")      # -12 > YAML -15


# ── B2 ───────────────────────────────────────────────────────────────────────

def _with_signal_and_confidence(monkeypatch, confidence: int):
    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy="pullback_ema")
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", MagicMock(return_value=sig))
    bt = types.SimpleNamespace(passes_gate=True, summary_text="ok")
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: bt)
    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": confidence, "sample_size": 50})


@pytest.mark.asyncio
async def test_b2_confidence_below_caution_caps_pass_at_caution(monkeypatch):
    _offline(monkeypatch, conviction=10, card_status="PASS")
    _with_signal_and_confidence(monkeypatch, 40)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_caution_below=50, confidence_reject_below=30))
    assert core.card.status == "CAUTION"
    assert [f["status"] for f in _flags(core, "confidence")] == ["CAUTION"]


@pytest.mark.asyncio
async def test_b2_caution_cap_never_lowers_a_reject(monkeypatch):
    _offline(monkeypatch, conviction=10, card_status="REJECT")
    _with_signal_and_confidence(monkeypatch, 40)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_caution_below=50))
    assert core.card.status == "REJECT"


@pytest.mark.asyncio
async def test_b2_below_reject_keeps_the_single_reject_flag(monkeypatch):
    _offline(monkeypatch, conviction=10, card_status="PASS")
    _with_signal_and_confidence(monkeypatch, 20)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_caution_below=50, confidence_reject_below=30))
    assert [f["status"] for f in _flags(core, "confidence")] == ["REJECT"]


@pytest.mark.asyncio
async def test_r3_1_below_reject_caps_pass_at_caution(monkeypatch):
    # Round 3: 35% (below reject) read PASS while 50% (below caution) read
    # CAUTION -- worse confidence, better verdict. The scan drops it outright.
    _offline(monkeypatch, conviction=10, card_status="PASS")
    _with_signal_and_confidence(monkeypatch, 35)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_caution_below=55, confidence_reject_below=40))
    assert core.card.status == "CAUTION"
    assert [f["status"] for f in _flags(core, "confidence")] == ["REJECT"]


@pytest.mark.asyncio
async def test_r3_1_below_reject_with_caution_unset_still_caps(monkeypatch):
    _offline(monkeypatch, conviction=10, card_status="PASS")
    _with_signal_and_confidence(monkeypatch, 35)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_reject_below=40))
    assert core.card.status == "CAUTION"


@pytest.mark.asyncio
async def test_b2_unset_caution_is_a_no_op(monkeypatch):
    _offline(monkeypatch, conviction=10, card_status="PASS")
    _with_signal_and_confidence(monkeypatch, 40)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(symbol="TEST"))
    assert core.card.status == "PASS"
    assert not _flags(core, "confidence")


# ── B3 ───────────────────────────────────────────────────────────────────────

def test_b3_key_differs_on_each_gate_threshold():
    base = ss._backtest_key("AAPL", "pullback_ema", "Bullish", _BARS, {"a": 1}, commission=0.001,
                            min_trades=5, min_win_rate=0.45)
    assert base != ss._backtest_key("AAPL", "pullback_ema", "Bullish", _BARS, {"a": 1},
                                    commission=0.001, min_trades=10, min_win_rate=0.45)
    assert base != ss._backtest_key("AAPL", "pullback_ema", "Bullish", _BARS, {"a": 1},
                                    commission=0.001, min_trades=5, min_win_rate=0.55)


@pytest.mark.asyncio
async def test_b3_analysis_caches_under_its_own_thresholds(monkeypatch):
    """A later scan at other thresholds must miss, not be served this verdict."""
    _offline(monkeypatch, conviction=10)
    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy="pullback_ema")
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", MagicMock(return_value=sig))
    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": 60, "sample_size": 50})
    bt = types.SimpleNamespace(passes_gate=True, summary_text="ok")
    keys: list[str] = []
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: keys.append(key) or None)

    loop = asyncio.get_running_loop()

    real = loop.run_in_executor

    async def _bt():
        return bt

    def _rie(executor, fn, *args):
        # Only the backtest pool is stubbed; asyncio.to_thread uses this too.
        return _bt() if executor is ss._BACKTEST_POOL else real(executor, fn, *args)
    monkeypatch.setattr(loop, "run_in_executor", _rie)
    monkeypatch.setattr(ss, "_BACKTEST_CACHE", {})

    await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", bt_min_trades=10, bt_min_win_rate=0.55))
    assert keys and keys[0].endswith("|10|0.55|hold=15")  # H2: Swing hold in the key
    assert list(ss._BACKTEST_CACHE) == keys


# ── B4 ───────────────────────────────────────────────────────────────────────

def _result(scan_id: str) -> StockScanResult:
    return StockScanResult(scan_id=scan_id, timestamp="t", candidates=[], rejected=[])


def _req(**kw) -> StockScanRequest:
    return StockScanRequest(universe=["SP500"], direction="Bearish", horizon="Position",
                            strategy="ma_crossover", **kw)


@pytest.mark.asyncio
async def test_b4_complete_serves_the_pair(monkeypatch):
    monkeypatch.setattr(ss, "_last_stock_status", "complete")
    monkeypatch.setattr(ss, "_last_stock_request",
                        _req(regime_headwind_reject_pct=-11, overrides={"weight_trend": 0.5}))
    monkeypatch.setattr(ss, "_last_stock_result", _result("s1"))
    out = await ss.get_last_stock_scan_request()
    assert out["scan_id"] == "s1"
    r = out["request"]
    assert r["regime_headwind_reject_pct"] == -11
    assert r["overrides"] == {"weight_trend": 0.5}
    assert "min_price" not in r                      # exclude_none
    # What the frontend replays (universe/symbols dropped, symbol added) validates.
    replay = {k: v for k, v in r.items() if k not in ("universe", "symbols")}
    a = StockAnalysisRequest(symbol="AAPL", **replay)
    assert (a.direction, a.horizon, a.strategy) == ("Bearish", "Position", "ma_crossover")
    assert a.regime_headwind_reject_pct == -11


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "idle", "error"])
async def test_b4_not_complete_serves_nothing(monkeypatch, status):
    # "running" pairs the NEW request with the PREVIOUS result.
    monkeypatch.setattr(ss, "_last_stock_status", status)
    monkeypatch.setattr(ss, "_last_stock_request", _req())
    monkeypatch.setattr(ss, "_last_stock_result", _result("old"))
    assert await ss.get_last_stock_scan_request() is None


@pytest.mark.asyncio
async def test_b4_complete_without_a_result_serves_nothing(monkeypatch):
    monkeypatch.setattr(ss, "_last_stock_status", "complete")
    monkeypatch.setattr(ss, "_last_stock_request", _req())
    monkeypatch.setattr(ss, "_last_stock_result", None)
    assert await ss.get_last_stock_scan_request() is None
