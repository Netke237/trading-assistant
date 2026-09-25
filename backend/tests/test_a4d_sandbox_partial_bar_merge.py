"""A4d: a partial Tradier-sandbox bar no longer wins the intraday merge.

Decision A4C-FOLLOWUPS-LOCKED-2026-09-24 item (1) + Kenneth's no-yfinance
choice A4D-NO-YFINANCE-KEEP-IF-NEWEST-2026-09-24. Plan:
docs/superpowers/plans/2026-09-24-a4d-sandbox-partial-bar-merge-plan.md (§6).

Tradier and yfinance stamps are built from the same ET wall time; at every
shared timestamp the closes differ (Tradier 1xx, yfinance 2xx), so each
assertion shows which source won.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import app.data.market as market
from app.data.market import fetch_intraday_candles

_ET = ZoneInfo("America/New_York")
SANDBOX = "https://sandbox.tradier.com"
LIVE = "https://api.tradier.com"
TOKEN = "tok-a4d"


def ts(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=_ET).timestamp())


def trow(s: str, close: float) -> dict:
    return {"time": s, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100}


def ybar(s: str, close: float) -> dict:
    return {"time": ts(s), "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 200}


def _run(fetch_start: str | int, tradier: list[dict], yf: list[dict], *, base: str = SANDBOX,
         interval: str = "15min", ibkr: list[dict] | None = None):
    """Run fetch_intraday_candles with every source stubbed. Returns (result, creds, get)."""
    start = ts(fetch_start) if isinstance(fetch_start, str) else fetch_start
    creds = MagicMock(return_value=(TOKEN, base))
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"series": {"data": tradier}} if tradier else {"series": None}
    with (
        patch("app.data.market._now", return_value=start),
        patch("app.data.market.get_tradier_creds", creds),
        patch("app.data.market.httpx.get", return_value=resp) as get,
        patch("app.data.market._fetch_intraday_yf", return_value=list(yf)),
        patch("app.data.ibkr.fetch_intraday_ibkr", return_value=list(ibkr or [])),
    ):
        result = fetch_intraday_candles("SPY", interval=interval, days=5)
    return result, creds, get


def by_time(result: list[dict]) -> dict[int, float]:
    return {b["time"]: b["close"] for b in result}


D = "2026-09-23"  # a Wednesday

# The §1 table: 15min, T = 10:20 ET, sandbox data to 10:05.
T1_TRADIER = [trow(f"{D} 09:45", 145.0), trow(f"{D} 10:00", 100.0)]
T1_YF = [ybar(f"{D} 09:45", 245.0), ybar(f"{D} 10:00", 200.0), ybar(f"{D} 10:15", 215.0)]


# 1 ─────────────────────────────────────────────────────────────────────────────
def test_1_sandbox_partial_bar_yields_to_yfinance():
    result, creds, get = _run(f"{D} 10:20", T1_TRADIER, T1_YF)
    closes = by_time(result)
    assert closes[ts(f"{D} 10:00")] == 200.0          # yfinance's complete bar
    assert closes[ts(f"{D} 09:45")] == 145.0          # older Tradier precedence unchanged
    assert closes[ts(f"{D} 10:15")] == 215.0
    assert result[-2]["time"] == ts(f"{D} 10:00") and result[-2]["close"] == 200.0
    assert creds.call_count == 1
    url = get.call_args.args[0]
    assert url.startswith(SANDBOX + "/")
    assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"


# 2 ─────────────────────────────────────────────────────────────────────────────
def test_2_premarket_partial_bar_with_no_counterpart_is_kept_as_newest():
    yf = [ybar("2026-09-22 15:30", 230.0), ybar("2026-09-22 15:45", 231.0)]
    tradier = [trow(f"{D} 07:45", 107.0), trow(f"{D} 08:00", 108.0)]
    result, _, _ = _run(f"{D} 08:20", tradier, yf)
    assert result[-1]["time"] == ts(f"{D} 08:00")
    assert result[-1]["close"] == 108.0
    assert by_time(result)[ts(f"{D} 07:45")] == 107.0


# 3 ─────────────────────────────────────────────────────────────────────────────
T3_TRADIER = [trow(f"{D} 09:45", 145.0), trow(f"{D} 10:00", 100.0)]
T3_YF = [ybar(f"{D} 09:45", 245.0), ybar(f"{D} 10:15", 215.0)]   # no 10:00 bar


def test_3_partial_bar_without_counterpart_behind_a_newer_bar_is_dropped():
    result, _, _ = _run(f"{D} 10:20", T3_TRADIER, T3_YF)
    times = [b["time"] for b in result]
    assert ts(f"{D} 10:00") not in times
    assert times == [ts(f"{D} 09:45"), ts(f"{D} 10:15")]


# 4 ─────────────────────────────────────────────────────────────────────────────
def test_4_live_base_keeps_tradier_precedence():
    result, _, get = _run(f"{D} 10:20", T1_TRADIER, T1_YF, base=LIVE)
    assert by_time(result)[ts(f"{D} 10:00")] == 100.0
    assert get.call_args.args[0].startswith(LIVE + "/")


# 5 ─────────────────────────────────────────────────────────────────────────────
def test_5_p_is_the_greatest_time_not_the_last_row():
    tradier = [trow(f"{D} 10:00", 100.0), trow(f"{D} 09:45", 145.0)]
    result, _, _ = _run(f"{D} 10:20", tradier, T1_YF)
    closes = by_time(result)
    assert closes[ts(f"{D} 10:00")] == 200.0
    assert closes[ts(f"{D} 09:45")] == 145.0


# 6 ─────────────────────────────────────────────────────────────────────────────
def test_6_no_tradier_rows_returns_yfinance_unchanged():
    result, _, _ = _run(f"{D} 10:20", [], T1_YF)
    assert result == sorted(T1_YF, key=lambda b: b["time"])


# 7 ─────────────────────────────────────────────────────────────────────────────
def test_7_stale_sandbox_p_outside_window_keeps_precedence():
    fri = "2026-09-18"
    mon = "2026-09-21"
    tradier = [trow(f"{fri} 19:30", 193.0), trow(f"{fri} 19:45", 194.0), trow(f"{fri} 15:45", 155.0)]
    yf = [ybar(f"{fri} 15:45", 255.0), ybar(f"{mon} 09:30", 230.0), ybar(f"{mon} 09:45", 245.0)]
    result, _, _ = _run(f"{mon} 10:20", tradier, yf)
    closes = by_time(result)
    assert closes[ts(f"{fri} 19:45")] == 194.0
    assert closes[ts(f"{fri} 19:30")] == 193.0
    assert closes[ts(f"{fri} 15:45")] == 155.0
    assert closes[ts(f"{mon} 09:45")] == 245.0


# 8 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("offset,expected", [(1860, 101.0), (1859, 201.0)])
def test_8_window_edge_on_1min(offset, expected):
    p = f"{D} 10:00"
    tradier = [trow(f"{D} 09:59", 159.0), trow(p, 101.0)]
    yf = [ybar(f"{D} 09:59", 259.0), ybar(p, 201.0)]
    result, _, _ = _run(ts(p) + offset, tradier, yf, interval="1min")
    assert by_time(result)[ts(p)] == expected


# 9 ─────────────────────────────────────────────────────────────────────────────
def test_9_nonfinite_yfinance_bar_at_p_and_p_newest_p_fills():
    bad = ybar(f"{D} 10:00", 200.0)
    bad["close"] = float("inf")
    yf = [ybar(f"{D} 09:45", 245.0), bad]
    result, _, _ = _run(f"{D} 10:20", T1_TRADIER, yf)
    assert result[-1]["time"] == ts(f"{D} 10:00")
    assert result[-1]["close"] == 100.0
    assert [b["time"] for b in result] == [ts(f"{D} 09:45"), ts(f"{D} 10:00")]


# 10 ────────────────────────────────────────────────────────────────────────────
def test_10_nonfinite_yfinance_bar_at_p_with_newer_bar_drops_p():
    bad = ybar(f"{D} 10:00", 200.0)
    bad["close"] = float("inf")
    yf = [ybar(f"{D} 09:45", 245.0), bad, ybar(f"{D} 10:15", 215.0)]
    result, _, _ = _run(f"{D} 10:20", T1_TRADIER, yf)
    times = [b["time"] for b in result]
    assert ts(f"{D} 10:00") not in times
    assert times[-1] == ts(f"{D} 10:15")


# 11 ────────────────────────────────────────────────────────────────────────────
def test_11_rule_3_runs_on_the_filtered_result():
    # yfinance lacks P's timestamp; its only newer bar is non-finite.
    bad = ybar(f"{D} 10:15", 215.0)
    bad["high"] = float("nan")
    yf = [ybar(f"{D} 09:45", 245.0), bad]
    result, _, _ = _run(f"{D} 10:20", T1_TRADIER, yf)
    assert ts(f"{D} 10:00") not in {b["time"] for b in yf}   # rule 2 did not fire; rule 3 decides
    assert result[-1]["time"] == ts(f"{D} 10:00")
    assert result[-1]["close"] == 100.0


# 12 ────────────────────────────────────────────────────────────────────────────
def test_12_duplicate_tradier_rows_at_p_both_yield():
    tradier = [trow(f"{D} 09:45", 145.0), trow(f"{D} 10:00", 100.0), trow(f"{D} 10:00", 102.0)]
    result, _, _ = _run(f"{D} 10:20", tradier, T1_YF)
    assert by_time(result)[ts(f"{D} 10:00")] == 200.0


def test_12b_duplicate_tradier_rows_at_p_without_counterpart_last_row_wins():
    tradier = [trow(f"{D} 09:45", 145.0), trow(f"{D} 10:00", 100.0), trow(f"{D} 10:00", 102.0)]
    yf = [ybar(f"{D} 09:45", 245.0)]
    result, _, _ = _run(f"{D} 10:20", tradier, yf)
    assert result[-1]["time"] == ts(f"{D} 10:00")
    assert result[-1]["close"] == 102.0


# 13 ────────────────────────────────────────────────────────────────────────────
def test_13_the_open_drops_the_last_premarket_partial_bar():
    tradier = [trow(f"{D} 08:45", 145.0), trow(f"{D} 09:00", 190.0), trow(f"{D} 09:15", 115.0)]
    yf = [ybar("2026-09-22 15:45", 231.0), ybar(f"{D} 09:30", 230.0)]
    result, _, _ = _run(f"{D} 09:35", tradier, yf)
    times = [b["time"] for b in result]
    assert ts(f"{D} 09:15") not in times
    assert result[-1]["time"] == ts(f"{D} 09:30")
    assert result[-2]["time"] == ts(f"{D} 09:00") and result[-2]["close"] == 190.0


# 14 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("interval", ["30min", "daily", "1D"])
def test_14_non_tradier_intervals_on_the_sandbox(interval):
    yf = [ybar(f"{D} 09:30", 230.0), ybar(f"{D} 10:00", 200.0)]
    result, _, get = _run(f"{D} 10:20", T1_TRADIER, yf, interval=interval)
    assert get.call_count == 0
    assert result == yf


def test_14b_widened_tradier_set_with_unmapped_interval_keeps_precedence():
    tradier = [trow(f"{D} 10:00", 100.0)]
    yf = [ybar(f"{D} 10:00", 200.0)]
    with patch("app.data.market._TRADIER_INTRADAY_INTERVALS", {"1min", "5min", "15min", "daily"}):
        result, _, get = _run(f"{D} 10:20", tradier, yf, interval="daily")
    assert get.call_count == 1
    assert by_time(result)[ts(f"{D} 10:00")] == 100.0


# 15 ────────────────────────────────────────────────────────────────────────────
def test_15_is_sandbox_base_and_the_a4b_lag_are_unchanged():
    assert market._is_sandbox_base("https://sandbox.tradier.com/")
    assert market._is_sandbox_base(SANDBOX)
    assert not market._is_sandbox_base(LIVE)
    assert not market._is_sandbox_base("")
    with patch("app.data.market._tradier_base", return_value=SANDBOX + "/"):
        assert market.intraday_feed_lag_seconds() == 900
    with patch("app.data.market._tradier_base", return_value=LIVE):
        assert market.intraday_feed_lag_seconds() == 0


# 16 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("case,expect", [
    ("1", "yielded=1 dropped=0"),
    ("3", "yielded=0 dropped=1"),
    ("4", "yielded=0 dropped=0"),
])
def test_16_merge_log_line(caplog, case, expect):
    caplog.set_level(logging.INFO, logger="app.data.market")
    if case == "1":
        _run(f"{D} 10:20", T1_TRADIER, T1_YF)
    elif case == "3":
        _run(f"{D} 10:20", T3_TRADIER, T3_YF)
    else:
        _run(f"{D} 10:20", T1_TRADIER, T1_YF, base=LIVE)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Merged ")]
    assert len(lines) == 1
    assert "→" in lines[0]
    assert f"(sandbox partial bar: {expect})" in lines[0]


# 17 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_17_scheduler_evaluates_yfinance_closed_candle(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.data.chart_cache as cc
    import app.services.chart_alert_scheduler as sched
    from app.database import Base
    from app.models.alert import AlertRuleModel

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as db:
        db.add(AlertRuleModel(
            id="a4d", user_id="default", name="R", symbol="SPY", interval="15min", enabled=True,
            rule_json=json.dumps({"logic": "AND", "conditions": []}), cooldown_minutes=0,
            expiry_date=None, created_at="2024-01-01T00:00:00Z", last_triggered_at=None,
            condition_state="{}",
        ))
        await db.commit()
    monkeypatch.setattr(sched, "AsyncSessionLocal", Session)
    monkeypatch.setattr("app.routers.chart_alerts.closed_candle_structure", lambda *a, **kw: [])  # A4e: the scheduler's structure call
    ev = AsyncMock(return_value=[])
    monkeypatch.setattr("app.routers.chart_alerts.evaluate_and_notify_for_symbol", ev)
    cc._INTRADAY_CACHE.clear()
    sched._last_seen_candle.clear()

    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"series": {"data": T1_TRADIER}}
    monkeypatch.setattr("app.data.market._now", lambda: ts(f"{D} 10:20"))
    monkeypatch.setattr("app.data.market.get_tradier_creds", lambda: (TOKEN, SANDBOX))
    monkeypatch.setattr("app.data.market.httpx.get", lambda *a, **kw: resp)
    monkeypatch.setattr("app.data.market._fetch_intraday_yf", lambda *a, **kw: list(T1_YF))
    try:
        await sched._tick()
    finally:
        cc._INTRADAY_CACHE.clear()
        sched._last_seen_candle.clear()
    closed = ev.await_args.args[2]
    assert closed["time"] == ts(f"{D} 10:00")
    assert closed["close"] == 200.0
