"""HISTORY-LATEST-BAR-UNFINALIZED (#574): an unfinished latest-day bar is skipped, not fatal.

The nightly runs at 20:00 ET. The day closed at 16:00 ET, so it counts as settled from 18:00 ET
(``hs.is_settled``), but Yahoo has not finished its daily bar yet: the 2026-11-06 01:00 UTC
nightly refused 85 yfinance-basis symbols (SPY included) and 61 rebuilds with
``invalid open on 2026-11-05``. ``_validated`` now drops just that bar when it is the reply's
latest bar, dated on the latest settled weekday, and only a price field is invalid. Everything
else stays strict. Test ids follow the plan's section 3.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.data.governor import ProviderUnavailable
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs
from app.services import history_backfill as history
from tests import test_history_incremental_writer as w

NIGHTLY = datetime(2026, 11, 6, 1, 0, tzinfo=timezone.utc)   # 20:00 ET on Thu 2026-11-05
LATEST = date(2026, 11, 5)
FIRST = date(2026, 10, 26)
SYMBOL = "TEST"
BAD_VALUES = [float("nan"), 0, None, -1, float("inf")]
BAD_IDS = ["nan", "zero", "none", "negative", "inf"]


def weekdays(a: date, b: date) -> list[date]:
    out = []
    while a <= b:
        if a.weekday() < 5:
            out.append(a)
        a += timedelta(days=1)
    return out


def bar(d: date, source: str = "yfinance", close: float = 100.0) -> dict:
    return {"time": d.isoformat(), "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 1000, "adj_factor": 1.0, "split_factor": 1.0,
            "div_cash": 0.0, "source": source}


def reply(first: date = FIRST, last: date = LATEST, source: str = "yfinance") -> list[dict]:
    return [bar(d, source) for d in weekdays(first, last)]


def at(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr(hs, "_utcnow", lambda: now)


# ── _validated: the drop rule ──────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value", BAD_VALUES, ids=BAD_IDS)
def test_u1_u2_unfinished_latest_bar_is_dropped(monkeypatch, caplog, field, value):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-1][field] = value
    with caplog.at_level(logging.WARNING, logger=history.__name__):
        out = history._validated(bars, FIRST, date(2026, 11, 6))
    assert list(out) == weekdays(FIRST, date(2026, 11, 4))
    assert LATEST not in out
    notes = [r.getMessage() for r in caplog.records if "2026-11-05" in r.getMessage()]
    assert len(notes) == 1 and field in notes[0] and "yfinance" in notes[0]


def test_u1_dst_nightly_also_drops(monkeypatch):
    # 01:00 UTC is 21:00 ET under EDT; the day is still the latest settled weekday.
    at(monkeypatch, datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc))      # Thu 10-01 21:00 ET
    bars = reply(date(2026, 9, 28), date(2026, 10, 1))
    bars[-1]["open"] = float("nan")
    out = history._validated(bars, date(2026, 9, 28), date(2026, 10, 2))
    assert list(out) == weekdays(date(2026, 9, 28), date(2026, 9, 30))


@pytest.mark.parametrize("value", BAD_VALUES, ids=BAD_IDS)
def test_u3_invalid_older_bar_still_rejects(monkeypatch, value):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-2]["open"] = value
    with pytest.raises(history.HistorySeamMismatch, match="invalid open on 2026-11-04"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u3_invalid_older_and_latest_bars_reject(monkeypatch):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[0]["low"] = 0
    bars[-1]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="invalid low on 2026-10-26"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u4_invalid_latest_bar_not_on_the_latest_settled_weekday_rejects(monkeypatch):
    at(monkeypatch, NIGHTLY)
    bars = reply(last=date(2026, 11, 4))          # reply ends early: 11-04 is not 11-05
    bars[-1]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="invalid open on 2026-11-04"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u4_next_night_a_still_bad_bar_rejects(monkeypatch):
    at(monkeypatch, NIGHTLY + timedelta(days=1))  # Fri 11-06 20:00 ET: 11-05 is no longer latest
    bars = reply(last=date(2026, 11, 6))
    bars[-2]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="invalid open on 2026-11-05"):
        history._validated(bars, FIRST, date(2026, 11, 7))


def test_u4_holiday_previous_day_rejects(monkeypatch):
    # Thanksgiving Thu 2026-11-26: the latest settled weekday is the holiday (no bar), so a
    # bad Wednesday bar (fetched settled the night before) is not skipped.
    at(monkeypatch, datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc))
    bars = reply(date(2026, 11, 16), date(2026, 11, 25))
    bars[-1]["open"] = 0
    with pytest.raises(history.HistorySeamMismatch, match="invalid open on 2026-11-25"):
        history._validated(bars, date(2026, 11, 16), date(2026, 11, 27))


@pytest.mark.parametrize("value", BAD_VALUES, ids=BAD_IDS)
def test_u5_invalid_adj_factor_on_the_latest_bar_rejects(monkeypatch, value):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-1]["adj_factor"] = value
    with pytest.raises(history.HistorySeamMismatch, match="invalid adj_factor on 2026-11-05"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u5_invalid_price_and_adj_factor_on_the_latest_bar_rejects(monkeypatch):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-1]["open"] = float("nan")
    bars[-1]["adj_factor"] = 0
    with pytest.raises(history.HistorySeamMismatch, match="on 2026-11-05"):
        history._validated(bars, FIRST, date(2026, 11, 6))


@pytest.mark.parametrize("bad_copy", ["first", "second"])
def test_u6_duplicate_of_the_unfinished_bar_rejects(monkeypatch, bad_copy):
    at(monkeypatch, NIGHTLY)
    bars = reply() + [bar(LATEST)]
    bars[-2 if bad_copy == "first" else -1]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="duplicate provider date"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u7_unfinished_bar_from_another_source_rejects(monkeypatch):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-1]["source"] = "tiingo"
    bars[-1]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="mixes sources"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u8_unfinished_bar_with_unknown_source_rejects(monkeypatch):
    at(monkeypatch, NIGHTLY)
    bars = reply()
    bars[-1]["source"] = "mystery"
    bars[-1]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="unknown adjustment basis"):
        history._validated(bars, FIRST, date(2026, 11, 6))


def test_u9_a_later_weekend_bar_makes_the_unfinished_bar_fatal(monkeypatch):
    at(monkeypatch, datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))   # Sun; latest = Fri 11-06
    bars = reply(last=date(2026, 11, 6)) + [bar(date(2026, 11, 7))]
    bars[-2]["open"] = float("nan")
    with pytest.raises(history.HistorySeamMismatch, match="invalid open on 2026-11-06"):
        history._validated(bars, FIRST, date(2026, 11, 8))


def test_u10_forming_bar_before_the_settle_is_ignored_as_before(monkeypatch):
    at(monkeypatch, datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc))   # 15:00 ET, not settled
    bars = reply()
    bars[-1].update(open=float("nan"), adj_factor=0, source="mystery")
    out = history._validated(bars, FIRST, LATEST)
    assert list(out) == weekdays(FIRST, date(2026, 11, 4))


def test_valid_reply_is_unchanged(monkeypatch):
    at(monkeypatch, NIGHTLY)
    out = history._validated(reply(), FIRST, date(2026, 11, 6))
    assert list(out) == weekdays(FIRST, LATEST)
    assert all(math.isfinite(b["open"]) for b in out.values())


# ── Writers ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    made = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "AsyncSessionLocal", made)
    monkeypatch.setattr(hs, "AsyncSessionLocal", made)
    monkeypatch.setattr(history, "notify_bars_changed", MagicMock())
    at(monkeypatch, NIGHTLY)
    yield made
    await engine.dispose()


@pytest.fixture
def providers(monkeypatch):
    tiingo_fetch = AsyncMock(return_value=[])
    yf_fetch = MagicMock(return_value=[])
    monkeypatch.setattr(tiingo, "fetch_historical_candles", tiingo_fetch)
    monkeypatch.setattr(hs, "_yfinance_fetch", yf_fetch)
    return tiingo_fetch, yf_fetch


async def seed(factory, bars: list[dict], state: State | None = None) -> None:
    async with factory() as db:
        await hs._store_bars(SYMBOL, bars, db)
        if state is not None:
            db.add(state)
        await db.commit()


async def snapshot(factory):
    async with factory() as db:
        rows = (await db.execute(select(M).order_by(M.date))).scalars().all()
        states = (await db.execute(select(State))).scalars().all()
    cols = [c.name for c in M.__table__.columns]
    scols = [c.name for c in State.__table__.columns]
    return ([tuple(getattr(r, c) for c in cols) for r in rows],
            [tuple(getattr(s, c) for c in scols) for s in states])


async def stored_dates(factory) -> list[date]:
    async with factory() as db:
        return list((await db.execute(select(M.date).where(M.symbol == SYMBOL)
                                      .order_by(M.date))).scalars().all())


def yfinance_state(through: date) -> State:
    earlier = NIGHTLY - timedelta(days=3)
    return State(symbol=SYMBOL, basis_provider="yfinance", basis_rebuilt_at=earlier,
                 window_verified_through=through, window_verified_at=earlier,
                 floor_requested_start=FIRST, floor_date=FIRST, floor_provider="yfinance",
                 floor_checked_at=earlier)


async def test_w1_yfinance_basis_symbol_stores_through_the_previous_day(factory, providers):
    """The SPY failure: a yfinance-basis nightly with Yahoo's unfinished 11-05 bar."""
    tiingo_fetch, yf_fetch = providers
    await seed(factory, reply(last=date(2026, 10, 30)), yfinance_state(date(2026, 10, 30)))
    bad = reply()
    bad[-1]["open"] = float("nan")
    yf_fetch.return_value = bad
    result = await history.update_history(SYMBOL, FIRST, date(2026, 11, 6))
    assert result.action == "SINGLE_PROVIDER_FULL" and result.provider == "yfinance"
    assert await stored_dates(factory) == weekdays(FIRST, date(2026, 11, 4))
    async with factory() as db:
        st = await db.get(State, SYMBOL)
    assert st.basis_provider == "yfinance" and st.window_verified_through == date(2026, 11, 4)
    tiingo_fetch.assert_not_awaited()


async def test_w2_refused_rebuild_falls_back_to_yfinance_through_the_previous_day(
        factory, providers):
    """The 61 rebuilds: Tiingo's hourly budget refuses, yfinance has the unfinished bar."""
    tiingo_fetch, yf_fetch = providers
    await seed(factory, reply(last=date(2026, 11, 4), source="alpaca"))
    tiingo_fetch.side_effect = ProviderUnavailable(
        "tiingo requests_per_hour budget exhausted (50/50)")
    bad = reply()
    bad[-1]["open"] = 0
    yf_fetch.return_value = bad
    result = await history.rebuild_single_provider(SYMBOL, FIRST, date(2026, 11, 6))
    assert result.provider == "yfinance" and result.last_date_after == date(2026, 11, 4)
    assert await stored_dates(factory) == weekdays(FIRST, date(2026, 11, 4))
    async with factory() as db:
        sources = set((await db.execute(select(M.source))).scalars().all())
        st = await db.get(State, SYMBOL)
    assert sources == {"yfinance"}
    assert st.basis_provider == "yfinance" and st.window_verified_through == date(2026, 11, 4)


async def test_w3_already_stored_latest_date_still_refuses_untouched(factory, providers):
    """A dropped date that is already stored keeps the reply-omits-stored-dates refusal."""
    _, yf_fetch = providers
    await seed(factory, reply(), yfinance_state(LATEST))
    before = await snapshot(factory)
    bad = reply()
    bad[-1]["open"] = float("nan")
    yf_fetch.return_value = bad
    with pytest.raises(history.SingleProviderRefused, match="omits existing stored dates"):
        await history.update_history(SYMBOL, FIRST, date(2026, 11, 6))
    assert await snapshot(factory) == before


async def test_w4_alpaca_suffix_with_unfinished_latest_bar_is_suffix_only(monkeypatch,
                                                                         w_engines):
    """An Alpaca-suffix symbol: tonight's unfinished bar is skipped, the prefix is kept."""
    env = await w.make_env(monkeypatch, w_engines)
    await env.night(w.SEED)
    prefix_before = await env.rows(before=w.SEAM)
    env.tiingo.reset_mock()
    env.yfinance.reset_mock()
    day = w.wd(w.SEED, 1)
    env.at(day)
    alpaca = env.world.alpaca()
    assert alpaca[-1]["time"] == day.isoformat()
    alpaca[-1]["open"] = float("nan")
    result = await history.update_history(w.SYMBOL, w.START, day, alpaca_bars=alpaca)
    assert result.action == "SUFFIX_ONLY"
    env.tiingo.assert_not_awaited()
    env.yfinance.assert_not_called()
    assert await env.rows(before=w.SEAM) == prefix_before
    rowmap = await env.rowmap()
    assert day not in rowmap and w.SEED in rowmap
    assert sorted(d for d in rowmap if d >= w.SEAM) == w.weekdays(w.SEAM, w.SEED)


@pytest_asyncio.fixture
async def w_engines():
    made = []

    async def new():
        engine, made_factory = await w.make_factory()
        made.append(engine)
        return made_factory

    yield new
    for engine in made:
        await engine.dispose()
