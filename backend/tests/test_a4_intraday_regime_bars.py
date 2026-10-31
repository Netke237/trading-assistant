"""A4: the Intraday regime is measured on 15-minute bars on every path.

`regime.intraday.timeframe` is `15min`. The stock scan always measured it on
15-minute bars; the options scan measured it on the DAILY `candles` and only
labelled it 15min, and the auto-trade fire path followed the options scan. Plan:
docs/superpowers/plans/2026-09-24-a4-intraday-regime-15min-plan.md.

Daily bars close at 181.0 and intraday bars at 50.0 throughout, so which series
a measurement ran on is read straight off the closes it was handed.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.auto_trader as at
from app.routers import stock_scan
from app.routers.scan import _process_symbol
from app.services.auto_trader import ArmedStrategy

DAILY = [
    {"time": f"2024-{m:02d}-{d:02d}", "open": 180.0, "high": 182.0, "low": 179.0,
     "close": 181.0, "volume": 1_000_000}
    for m in range(1, 13) for d in range(1, 22)
][:252]
INTRADAY = [
    {"time": 1_700_000_000 + 900 * i, "open": 50.0, "high": 50.5, "low": 49.5,
     "close": 50.0, "volume": 10_000}
    for i in range(400)
]


def _sem():
    """A fake scan semaphore that records whether it is currently held."""
    sem = MagicMock()
    sem.held = False

    async def _enter(*_a):
        sem.held = True
        return sem

    async def _exit(*_a):
        sem.held = False
        return False

    sem.__aenter__ = AsyncMock(side_effect=_enter)
    sem.__aexit__ = AsyncMock(side_effect=_exit)
    return sem


async def _scan(horizon: str, *, intraday, scoring_cfg=None, out=None):
    """Run the options scan's `_process_symbol` far enough to measure the
    regime, and report what the measurement ran on and what the card got.
    `scoring_cfg` replaces `_load_scoring_cfg()`; `out["result"]` receives what
    `_process_symbol` returned."""
    import contextlib
    cfg_patch = (patch("app.routers.scan._load_scoring_cfg", return_value=scoring_cfg)
                 if scoring_cfg is not None else contextlib.nullcontext())
    omm = MagicMock(return_value=None)
    dhmm = MagicMock(return_value=None)
    intraday_fetch = MagicMock(
        side_effect=intraday if isinstance(intraday, Exception) else None,
        return_value=None if isinstance(intraday, Exception) else intraday,
    )
    with patch("app.routers.scan.get_daily_regime_bars", new_callable=AsyncMock, return_value=DAILY), \
         patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.fetch_intraday_candles", intraday_fetch), \
         patch("app.routers.scan._compute_omm", omm), \
         patch("app.routers.scan._compute_dhmm", dhmm), \
         patch("app.routers.scan.score_stock") as score, \
         patch("app.routers.scan.log_event"), \
         cfg_patch:
        score.return_value = MagicMock(status="REJECT", score=20, rules=[], components={})
        result = await _process_symbol(
            symbol="AAPL", direction="Bullish", horizon=horizon, client=AsyncMock(),
            sem=_sem(), scan_id="a4", bars_map={"AAPL": DAILY},
        )
    if out is not None:
        out["result"] = result
    return omm, dhmm, intraday_fetch, score


@pytest.mark.asyncio
async def test_options_scan_measures_intraday_on_15_minute_bars():
    omm, _, fetch, _ = await _scan("Intraday", intraday=INTRADAY)
    assert fetch.call_args.args == ("AAPL", "15min", 55)
    closes = omm.call_args.args[0]
    assert set(closes) == {50.0} and len(closes) == len(INTRADAY), (
        "the Intraday regime must be measured on the 15-minute series, not the daily candles"
    )


@pytest.mark.asyncio
async def test_options_scan_intraday_fetch_runs_under_the_scan_semaphore():
    """The 15-min fetch is a network call per symbol; it must count against
    the scan's concurrency limit like every other fetch in the worker."""
    sem = _sem()
    held_at_fetch: list[bool] = []

    def _fetch(*_a, **_k):
        held_at_fetch.append(sem.held)
        return INTRADAY

    with patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.fetch_intraday_candles", side_effect=_fetch), \
         patch("app.routers.scan._compute_omm", return_value=None), \
         patch("app.routers.scan._compute_dhmm", return_value=None), \
         patch("app.routers.scan.score_stock") as score, \
         patch("app.routers.scan.log_event"):
        score.return_value = MagicMock(status="REJECT", score=20, rules=[], components={})
        await _process_symbol(
            symbol="AAPL", direction="Bullish", horizon="Intraday", client=AsyncMock(),
            sem=sem, scan_id="a4", bars_map={"AAPL": DAILY},
        )
    assert held_at_fetch == [True]


@pytest.mark.asyncio
async def test_options_scan_swing_uses_daily_reader_and_never_fetches_intraday():
    omm, dhmm, fetch, _ = await _scan("Swing", intraday=INTRADAY)
    fetch.assert_not_called()
    assert set(omm.call_args.args[0]) == {181.0}


def _cfg_gate_and_sizing_off() -> dict:
    """A copy of the shipped scoring config with regime gate AND regime sizing
    off -- the only configuration in which P3c item 1 lets an Intraday name
    with no 15-min bars continue."""
    import copy
    from app.services.config_loader import load_scoring_cfg
    cfg = copy.deepcopy(load_scoring_cfg())
    cfg["regime_gate"]["enabled"] = False
    cfg["regime_sizing"]["enabled"] = False
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("intraday", [RuntimeError("tradier down"), []])
async def test_options_scan_leaves_intraday_unmeasured_rather_than_falling_back_to_daily(intraday):
    # P3c item 1: on shipped config (gate + sizing on) a failed/empty 15-min
    # fetch is now a drop, so the old "unmeasured, no daily fallback" behaviour
    # is pinned with both off.
    omm, dhmm, _, score = await _scan("Intraday", intraday=intraday,
                                      scoring_cfg=_cfg_gate_and_sizing_off())
    omm.assert_not_called()
    dhmm.assert_not_called()
    assert score.call_args.kwargs["regime_signal"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intraday", [RuntimeError("tradier down"), []])
async def test_options_scan_drops_intraday_with_no_15_minute_bars_on_shipped_config(intraday):
    from app.schemas import RejectedCandidate
    out: dict = {}
    omm, dhmm, _, score = await _scan("Intraday", intraday=intraday, out=out)
    assert isinstance(out["result"], RejectedCandidate)
    assert out["result"].reason.startswith("regime data unavailable:")
    score.assert_not_called()
    omm.assert_not_called()


@pytest.mark.asyncio
async def test_options_scan_leaves_a_short_intraday_series_unmeasured():
    omm, dhmm, _, score = await _scan("Intraday", intraday=INTRADAY[:10])
    omm.assert_not_called()
    dhmm.assert_not_called()
    assert score.call_args.kwargs["regime_signal"] is None


@pytest.mark.asyncio
async def test_options_scan_runs_the_hmm_on_the_same_15_minute_series():
    real_omm = MagicMock(return_value=MagicMock(
        state="Bull", p_stay=0.5, stability="Fragile", regime_age_days=1,
        avg_regime_duration=2.0, conviction_pct=10, conviction_label="x",
        interpretation="", ))
    dhmm = MagicMock(return_value=None)
    with patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.fetch_intraday_candles", return_value=INTRADAY), \
         patch("app.routers.scan._compute_omm", real_omm), \
         patch("app.routers.scan._compute_dhmm", dhmm), \
         patch("app.routers.scan.score_stock") as score, \
         patch("app.routers.scan.log_event"):
        score.return_value = MagicMock(status="REJECT", score=20, rules=[], components={})
        await _process_symbol(
            symbol="AAPL", direction="Bullish", horizon="Intraday", client=AsyncMock(),
            sem=_sem(), scan_id="a4", bars_map={"AAPL": DAILY},
        )
    # A4b: a filtered COPY now (completed bars); every INTRADAY bar is long past.
    assert dhmm.call_args.args[0] == INTRADAY
    assert score.call_args.kwargs["regime_signal"]["timeframe"] == "15min"


def _armed(horizon: str) -> ArmedStrategy:
    return ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL", option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.5, conid=None, entry_premium=2.5, portfolio_value=100_000.0,
        horizon=horizon,
    )


def test_fire_path_measures_intraday_on_the_same_15_minute_series(mocker):
    fetch = mocker.patch("app.data.market.fetch_intraday_candles", return_value=INTRADAY)
    daily = mocker.patch.object(at, "_fetch_scan_window_bars",
                                side_effect=AssertionError("daily bars read for Intraday"))
    omm = mocker.patch("app.services.regime_omm.compute_omm", return_value=None)
    assert at._measure_trade_regime(_armed("Intraday")) is None
    assert fetch.call_args.args == ("AAPL", "15min", 55)
    daily.assert_not_called()
    assert set(omm.call_args.args[0]) == {50.0}


def test_fire_path_swing_stays_on_the_daily_window(mocker):
    fetch = mocker.patch("app.data.market.fetch_intraday_candles",
                         side_effect=AssertionError("intraday bars read for Swing"))
    mocker.patch.object(at, "_fetch_scan_window_bars", return_value=DAILY)
    omm = mocker.patch("app.services.regime_omm.compute_omm", return_value=None)
    at._measure_trade_regime(_armed("Swing"))
    fetch.assert_not_called()
    assert set(omm.call_args.args[0]) == {181.0}


# `[]` left this list with P3b: no bars at all now REFUSES the fire
# (P3B-REGIME-BARS-MISSING-REFUSES-2026-09-25, pinned in test_auto_trader.py).
@pytest.mark.parametrize("intraday", [INTRADAY[:10]])
def test_an_unmeasurable_intraday_fire_sizes_at_the_floor_never_full(mocker, intraday):
    """The gate abstains on the same input; SIZING-4's floor still bounds it."""
    from app.data.ibkr_paper import OrderResult
    sent = {}
    mocker.patch("app.data.market.fetch_intraday_candles", return_value=intraday)
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader.execute_option_order",
                 side_effect=lambda s: sent.setdefault("qty", s.quantity) and OrderResult("a4", "ok", "ibkr_paper"))
    mocker.patch("app.services.regime_monitor.get_last_conviction",
                 side_effect=AssertionError("SPX cache read"))
    svc = at.AutoTradeService()
    svc.arm(_armed("Intraday"))
    svc.fire()
    assert sent["qty"] == 1, "4 x min_mult 0.30 -> 1, never the full 4"
    assert svc.get_state().history[-1]["sizing"] == "floor:unmeasured"
    assert svc.get_state().history[-1]["regime_gate"] == "abstained"


def test_the_three_readers_fetch_the_same_15_minute_series():
    """Stock scan, options scan and fire path must ask for the same bars, or
    Stocks mode, Options mode and the auto-trader drift apart again."""
    spec = 'fetch_intraday_candles, symbol, "15min", 55'
    # The stock scan reads one module constant on all three of its paths
    # (P3a): pin the constant and that each path uses it.
    assert stock_scan._INTRADAY_FETCH_DAYS == 55, (
        "the stock scan's reader changed -- move the other two with it"
    )
    ss_spec = 'fetch_intraday_candles, symbol, "15min", _INTRADAY_FETCH_DAYS'
    # ONE fetch in _process_stock since P3a item 12 (signal + regime share it).
    assert inspect.getsource(stock_scan._process_stock).count(ss_spec) == 1
    assert ss_spec in inspect.getsource(stock_scan._analyze_core)
    import app.routers.scan as scan_mod
    assert spec in inspect.getsource(scan_mod._process_symbol)
    assert 'fetch_intraday_candles(symbol, "15min", 55)' in inspect.getsource(
        at._fetch_intraday_regime_bars)
