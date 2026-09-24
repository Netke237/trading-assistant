"""A4b: every Intraday-horizon regime reader measures on COMPLETED 15-minute bars.

Decision A4B-DROP-FORMING-15MIN-BAR-2026-09-24; plan
docs/superpowers/plans/2026-09-24-a4b-intraday-completed-bars-plan.md.

Completed bars close at 50.0; the still-forming last bar closes at 999.0, so a
measurement that saw it is read straight off the closes it was handed. Feed lag
is pinned to 0 everywhere except the lag tests, so the result cannot depend on
this machine's saved Tradier credentials (plan round 2, below-gate 1).
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.data.market as market
import app.services.auto_trader as at
from app.data.market import completed_intraday_bars, intraday_feed_lag_seconds

FORMING = 999.0


def _bars(n: int = 120) -> list[dict]:
    """`n` completed 15-minute bars ending one bar ago, then one still forming."""
    now = int(time.time())
    done = [{"time": now - 900 * (n - i + 1), "open": 50.0, "high": 50.5, "low": 49.5,
             "close": 50.0, "volume": 1_000} for i in range(n)]
    forming = {"time": now - 60, "open": 50.0, "high": 999.0, "low": 50.0,
               "close": FORMING, "volume": 10}
    return done + [forming]


@pytest.fixture(autouse=True)
def _no_feed_lag(request, monkeypatch):
    if "lag" not in request.node.name:
        monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)


# ── the helper ────────────────────────────────────────────────────────────────

def test_a_bar_is_kept_only_once_its_15_minutes_have_elapsed():
    now = 10_000
    bars = [{"time": now - 900}, {"time": now - 899}, {"time": now - 1800}]
    assert completed_intraday_bars(bars, now=now, feed_lag=0) == [{"time": now - 900},
                                                                  {"time": now - 1800}]


@pytest.mark.parametrize("bad", ["2026-01-02 09:30", None, True, 1.5])
def test_a_bar_that_cannot_be_dated_is_dropped(bad):
    assert completed_intraday_bars([{"time": bad}], now=10**10, feed_lag=0) == []


def test_order_is_kept_and_empty_stays_empty():
    bars = [{"time": 1}, {"time": 3}, {"time": 2}]
    assert completed_intraday_bars(bars, now=10**6, feed_lag=0) == bars
    assert completed_intraday_bars([], now=10**6, feed_lag=0) == []


@pytest.mark.parametrize("base,lag", [
    ("https://sandbox.tradier.com", 900),
    ("https://sandbox.tradier.com/", 900),     # trailing slash still counts
    ("https://api.tradier.com", 0),
    ("", 0),
])
def test_feed_lag_is_900_on_the_sandbox_base_only(monkeypatch, base, lag):
    monkeypatch.setattr(market, "_tradier_base", lambda: base)
    assert intraday_feed_lag_seconds() == lag


def test_feed_lag_on_a_delayed_sandbox_feed_drops_a_bar_that_only_looks_complete(monkeypatch):
    """16 minutes old on the wall clock is partial in a 15-minute-delayed feed."""
    monkeypatch.setattr(market, "_tradier_base", lambda: "https://sandbox.tradier.com")
    now = 100_000
    sixteen, thirtyone = {"time": now - 16 * 60}, {"time": now - 31 * 60}
    assert completed_intraday_bars([thirtyone, sixteen], now=now) == [thirtyone]


def test_feed_lag_off_the_sandbox_keeps_a_bar_16_minutes_old(monkeypatch):
    monkeypatch.setattr(market, "_tradier_base", lambda: "https://api.tradier.com")
    now = 100_000
    assert completed_intraday_bars([{"time": now - 16 * 60}], now=now) == [{"time": now - 16 * 60}]


# ── the six readers ───────────────────────────────────────────────────────────

def _assert_completed(closes):
    closes = list(closes)
    assert FORMING not in closes, "the still-forming bar reached the regime measurement"
    assert set(closes) == {50.0}


def test_r1_the_stock_scan_measures_on_completed_bars():
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockScanRequest
    omm = MagicMock(return_value=None)
    daily = [{"time": f"2025-{m:02d}-{d:02d}", "open": 150, "high": 151, "low": 149,
              "close": 150.0, "volume": 1_000_000} for m in range(1, 12) for d in range(1, 21)]
    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Intraday",
                           strategy="pullback_ema")

    async def run():
        with patch("app.routers.stock_scan.get_historical_bars", new=AsyncMock(return_value=daily)), \
             patch("app.routers.stock_scan.fetch_company_name_async", new=AsyncMock(return_value="X")), \
             patch("app.routers.stock_scan.fetch_price_async", new=AsyncMock(return_value=150.0)), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=_bars()), \
             patch("app.routers.stock_scan.compute_omm", omm), \
             patch("app.routers.stock_scan.score_stock",
                   return_value=MagicMock(status="REJECT", score=10, rules=[], components={})), \
             patch("app.routers.stock_scan._get_fundamentals", new=AsyncMock(return_value=None)):
            return await ss._process_stock("AAPL", req, "scan-a4b", {}, [])

    asyncio.run(run())
    _assert_completed(omm.call_args.args[0])


@pytest.mark.asyncio
async def test_r2_the_analysis_page_measures_on_completed_bars_but_keeps_the_whole_series(monkeypatch):
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest
    daily = [{"time": i, "open": 100, "high": 101, "low": 99, "close": 100.0, "volume": 1_000_000}
             for i in range(300)]
    intraday = _bars()

    async def _fake_bars(*a):
        return daily

    async def _fake_name(*a):
        return "X"

    seen = []
    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: intraday)
    monkeypatch.setattr(ss, "compute_omm", lambda closes, **k: seen.append(list(closes)) or None)
    req = StockAnalysisRequest(symbol="TEST", direction="Bullish", horizon="Intraday",
                               strategy="pullback_ema")
    core = await ss._analyze_core("TEST", req)
    _assert_completed(seen[0])
    assert core.intraday_bars[-1]["close"] == FORMING, (
        "only the REGIME copy is filtered; signal/backtest/chart keep the whole series"
    )


def test_r3_the_analysis_horizon_block_measures_on_completed_bars(monkeypatch):
    from app.routers import stock_scan as ss
    seen = []
    monkeypatch.setattr(ss, "compute_omm", lambda closes, **k: seen.append(list(closes)) or None)
    ss._regime_block_for_horizon("TEST", [], "Intraday", "Bullish", intraday_bars=_bars())
    _assert_completed(seen[0])


@pytest.mark.asyncio
async def test_r4_the_options_scan_measures_on_completed_bars():
    from app.routers.scan import _process_symbol
    daily = [{"time": f"2024-{m:02d}-{d:02d}", "open": 180, "high": 182, "low": 179,
              "close": 181.0, "volume": 1_000_000} for m in range(1, 13) for d in range(1, 22)][:252]
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=sem)
    sem.__aexit__ = AsyncMock(return_value=False)
    omm = MagicMock(return_value=None)
    with patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.fetch_intraday_candles", return_value=_bars()), \
         patch("app.routers.scan._compute_omm", omm), \
         patch("app.routers.scan.score_stock",
               return_value=MagicMock(status="REJECT", score=20, rules=[], components={})), \
         patch("app.routers.scan.log_event"):
        await _process_symbol(symbol="AAPL", direction="Bullish", horizon="Intraday",
                              client=AsyncMock(), sem=sem, scan_id="a4b",
                              bars_map={"AAPL": daily})
    _assert_completed(omm.call_args.args[0])


def test_r5_the_fire_path_measures_on_completed_bars(monkeypatch):
    monkeypatch.setattr(market, "fetch_intraday_candles", lambda *a, **k: _bars())
    _assert_completed(b["close"] for b in at._fetch_intraday_regime_bars("AAPL"))


def test_r5_a_series_left_under_min_obs_by_the_drop_is_unmeasured_and_floors(mocker):
    """min_obs is 60: 59 completed + 1 forming used to measure; now it abstains."""
    from app.data.ibkr_paper import OrderResult
    from app.services.auto_trader import ArmedStrategy
    sent = {}
    mocker.patch("app.data.market.fetch_intraday_candles", return_value=_bars(59))
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.setdefault("qty", s.quantity) and OrderResult("x", "ok", "ibkr_paper"))
    svc = at.AutoTradeService()
    svc.arm(ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL", option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT", limit_price=2.5,
        conid=None, entry_premium=2.5, portfolio_value=100_000.0, horizon="Intraday",
    ))
    svc.fire()
    assert sent["qty"] == 1
    row = svc.get_state().history[-1]
    assert row["regime_gate"] == "abstained" and row["sizing"] == "floor:unmeasured"


def test_r6_step_1s_intraday_card_measures_on_completed_bars():
    from fastapi.testclient import TestClient
    from app.main import app
    seen = []

    def _hmm(bars):
        seen.append([b["close"] for b in bars])
        return None

    daily = [{"time": 1_700_000_000 + 86_400 * i, "open": 500, "high": 501, "low": 499,
              "close": 500.0, "volume": 1} for i in range(300)]
    with patch("app.routers.regime.fetch_intraday_candles", return_value=_bars(500)), \
         patch("app.routers.regime.compute_intraday_hmm", _hmm), \
         patch("app.routers.regime.fetch_candles", return_value=daily), \
         patch("app.routers.regime.fetch_price", return_value=None):
        resp = TestClient(app).get("/api/regime")
    assert resp.status_code == 200, resp.text
    if seen:                       # hmmlearn present: the HMM got the completed series
        _assert_completed(seen[0])


def test_r6_the_omm_fallback_sees_the_same_completed_series(monkeypatch):
    """With the HMM unavailable, the OMM fallback runs on the same filtered bars."""
    from fastapi.testclient import TestClient
    from app.main import app
    import app.routers.regime as regime
    seen = []
    real = regime.compute_omm

    def _spy(closes, *a, **k):
        seen.append(list(closes))
        return real(closes, *a, **k)

    daily = [{"time": 1_700_000_000 + 86_400 * i, "open": 500, "high": 501, "low": 499,
              "close": 500.0 + (i % 7), "volume": 1} for i in range(300)]
    monkeypatch.setattr(regime, "compute_omm", _spy)
    with patch("app.routers.regime.fetch_intraday_candles", return_value=_bars(500)), \
         patch("app.routers.regime.compute_intraday_hmm", return_value=None), \
         patch("app.routers.regime.fetch_candles", return_value=daily), \
         patch("app.routers.regime.fetch_price", return_value=None):
        resp = TestClient(app).get("/api/regime")
    assert resp.status_code == 200, resp.text
    intraday_calls = [c for c in seen if FORMING in c or (c and set(c) == {50.0})]
    assert intraday_calls, "the intraday OMM fallback did not run"
    for c in intraday_calls:
        _assert_completed(c)
