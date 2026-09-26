"""P4b T4: HMM-INTRADAY-4H-HISTORY -- a 4h composite watch (and the dialog's
regime snapshot) fetch ~180 days, enough completed 4h bars for the HMM; the
snapshot reads the watch's series (D4/D5)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.data.market as market
from app.services.composite_trigger_evaluator import intraday_history_days, watch_fetch_interval

_EV = "app.services.strategy_watch_evaluator"


def test_history_days_per_interval():
    assert intraday_history_days("4h") == 180
    for iv in ("1h", "15m", "15min", "5m", "5min", "1min", "30min"):
        assert intraday_history_days(iv) == 55


def test_watch_fetch_interval_maps_the_dialog_spellings():
    assert [watch_fetch_interval(i) for i in ("1m", "5m", "15m", "30m")] == ["1min", "5min", "15min", "30min"]
    for iv in ("1h", "4h", "1D", "1W", "15min"):
        assert watch_fetch_interval(iv) == iv


def _daily(n=260):
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.0, "volume": 1_000_000} for i in range(n)]


@pytest.mark.asyncio
@pytest.mark.parametrize("interval, days", [("4h", 180), ("15m", 55), ("1h", 55)])
async def test_hmm_intraday_watch_requests_enough_history(interval, days):
    from app.services.strategy_watch_evaluator import evaluate_all
    store = MagicMock()
    store.list_watches.return_value = [{
        "id": "c1", "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
        "enabled": True, "interval": interval, "last_state": {"phase": "idle"},
        "trigger_def": {"primary": {"model": "HMM_intraday"}},
    }]
    fetch = MagicMock(return_value=[])
    with patch(f"{_EV}.strategy_watch_store", store), \
            patch(f"{_EV}.get_bars", new_callable=AsyncMock, return_value=_daily()), \
            patch.object(market, "fetch_intraday_candles", fetch):
        await evaluate_all()
    fetch.assert_called_once()
    assert fetch.call_args.kwargs["days"] == days


@pytest.mark.asyncio
@pytest.mark.parametrize("interval, fetched_as, days", [
    ("4h", "4h", 180), ("15m", "15min", 55), ("30m", "30min", 55), ("1h", "1h", 55),
])
async def test_regime_snapshot_reads_the_watch_series(monkeypatch, interval, fetched_as, days):
    import app.routers.composite_watch as cw
    import app.services.historical_store as hs
    import app.services.regime_hmm as regime_hmm

    monkeypatch.setattr(hs, "get_bars", AsyncMock(return_value=_daily()))
    calls = []
    monkeypatch.setattr(market, "fetch_intraday_candles",
                        lambda symbol, interval, days: calls.append((interval, days)) or [])
    completed = []
    monkeypatch.setattr(market, "completed_bars_for_interval",
                        lambda bars, iv, now=None: completed.append(iv) or bars)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm",
                        lambda b: MagicMock(state="Trending", p_stay=0.9, p_transition=[]))
    await cw.get_regime_snapshot(symbol="AAPL", model="HMM_intraday", direction="Bullish", interval=interval)
    assert calls == [(fetched_as, days)]
    assert completed == [fetched_as]
