"""BacktestOut carries the time exits and the hold (STOCKS-T1-FOLLOWUPS F2).

`n_time_exits` comes from the BacktestResult; `hold_max_days` is the hold
actually passed to that backtest (hold_for_backtest). A NEW result always
carries `n_time_exits` as an int, even with no hold; `None` means unknown
(a result saved before this change).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import json
import types
from unittest.mock import MagicMock, patch

import pytest

from tests.test_stock_scan_backtest_commission import _fake_signal, _measured_trend


def _bt(n_time_exits: int = 3):
    return types.SimpleNamespace(
        passes_gate=True, n_trades=18, win_rate=0.6, total_return_pct=5.0,
        max_drawdown_pct=2.0, expectancy=1.5, sharpe=1.2, confidence=65,
        summary_text="ok", n_time_exits=n_time_exits)


def _signal(strategy: str):
    sig = _fake_signal()
    sig.strategy = strategy
    return sig


def _card(horizon: str = "Swing"):
    # A real card: the scan caps the status with dataclasses.replace().
    from app.scoring.stock_scorer import StockScoreCard
    return StockScoreCard(symbol="AAPL", direction="Bullish", horizon=horizon,
                          score=70, status="PASS", rules=[_measured_trend()])


def _bars(n: int = 130):
    return [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
             "volume": 1_000_000, "date": "2024-01-01", "time": i} for i in range(n)]


def _run_process_stock(req, strategy: str, bt):
    from app.routers import stock_scan as ss

    ss._BACKTEST_CACHE.clear()

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=_card(req.horizon)), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=_bars()), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=_bars(300)), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", return_value=bt), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_active", return_value={}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": None, "sample_size": 0}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch("app.routers.stock_scan._BACKTEST_POOL", concurrent.futures.ThreadPoolExecutor(max_workers=1)), \
             patch.dict(ss._SIGNAL_FNS, {strategy: lambda *a, **k: _signal(strategy)}):
            return await ss._process_stock("AAPL", req, "test-scan-id", {}, [])

    return asyncio.run(run())


@pytest.mark.parametrize("horizon, strategy, n_time_exits, expected_hold", [
    ("Swing", "pullback_ema", 3, 15),
    ("Intraday", "pullback_ema", 0, None),
    ("Swing", "mean_reversion_vwap", 0, None),
])
def test_process_stock_backtest_carries_time_exits_and_hold(horizon, strategy, n_time_exits,
                                                            expected_hold):
    from app.schemas.stock_scan import PositionCardOut, StockScanRequest

    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon=horizon,
                           strategy=strategy)
    out = _run_process_stock(req, strategy, _bt(n_time_exits))

    assert isinstance(out, PositionCardOut), f"expected a card, got {out}"
    assert out.backtest.n_time_exits == n_time_exits
    assert isinstance(out.backtest.n_time_exits, int)
    assert out.backtest.hold_max_days == expected_hold


def test_old_stock_current_result_without_the_fields_reloads_with_none():
    from app.schemas.stock_scan import StockScanRequest, StockScanResult

    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema")
    card = _run_process_stock(req, "pullback_ema", _bt(3))
    doc = json.loads(StockScanResult(scan_id="s", timestamp="t", candidates=[card],
                                     rejected=[]).model_dump_json())
    bt = doc["candidates"][0]["backtest"]
    bt.pop("n_time_exits")
    bt.pop("hold_max_days")

    reloaded = StockScanResult.model_validate_json(json.dumps(doc))
    assert reloaded.candidates[0].backtest.n_time_exits is None
    assert reloaded.candidates[0].backtest.hold_max_days is None


# ── /analyze-stock ───────────────────────────────────────────────────────────

_ABARS = [{"time": 1_700_000_000 + i * 86400, "open": 100, "high": 101, "low": 99,
           "close": 100 + (i % 3), "volume": 1_000_000} for i in range(300)]


@dataclasses.dataclass
class _Card:
    score: int = 70
    status: str = "PASS"
    rules: list = dataclasses.field(default_factory=list)


def _offline_analysis(monkeypatch, strategy: str, bt):
    from app.routers import stock_scan as ss

    async def _fake_bars(symbol, start, end):
        return _ABARS

    async def _fake_name(client, symbol):
        return "Test Co"

    async def _none():
        return None

    async def _earn(*a, **k):
        return 90

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: _ABARS)
    monkeypatch.setattr(ss, "compute_directional_hmm", lambda bars: None)
    monkeypatch.setattr(ss, "_market_backdrop", _none)
    monkeypatch.setattr(ss, "_earnings_days_for", _earn)
    omm = types.SimpleNamespace(
        state="Bull", p_stay=0.8, stability="Stable", regime_age_days=5,
        avg_regime_duration=10.0, conviction_pct=10, conviction_label="Tailwind",
        interpretation="", transition_row=[], state_order=[])
    monkeypatch.setattr(ss, "compute_omm", lambda *a, **k: omm)
    monkeypatch.setattr(ss, "score_stock", lambda **kw: _Card())
    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy=strategy)
    monkeypatch.setitem(ss._SIGNAL_FNS, strategy, MagicMock(return_value=sig))
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: bt)
    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": 70, "sample_size": 50})


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon, strategy, n_time_exits, expected_hold", [
    ("Swing", "pullback_ema", 3, 15),
    ("Intraday", "pullback_ema", 0, None),
    ("Swing", "mean_reversion_vwap", 0, None),
])
async def test_analyze_stock_backtest_carries_time_exits_and_hold(
        monkeypatch, horizon, strategy, n_time_exits, expected_hold):
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    _offline_analysis(monkeypatch, strategy, _bt(n_time_exits))
    out = await ss.analyze_stock(StockAnalysisRequest(symbol="TEST", horizon=horizon,
                                                      strategy=strategy))

    assert out.backtest is not None
    assert out.backtest.n_time_exits == n_time_exits
    assert isinstance(out.backtest.n_time_exits, int)
    assert out.backtest.hold_max_days == expected_hold
