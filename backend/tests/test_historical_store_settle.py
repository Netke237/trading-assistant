"""WATCH-RULE-BAR-PARITY unit A (plan 2.10): never store an unsettled daily row.

Every scenario pins a weekday clock through ``historical_store._utcnow`` (so
``_host_today``, ``most_recent_trading_day`` and ``_prev_trading_day`` follow), runs
``get_bars`` against an in-memory SQLite store, and stubs the three providers with
recorded ``(start, end)`` calls. The provider universe returns, for every weekday up
to the clock's own date, the FINAL bar once that day has settled and a visibly
different FORMING bar before -- so a stored forming bar is a wrong number, not a
coincidence.

D = Wednesday 2026-06-10 (EDT: 16:00 ET = 20:00 UTC, settle 18:00 ET = 22:00 UTC).
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services import historical_store as hs

ET = ZoneInfo("America/New_York")
D = date(2026, 6, 10)            # Wednesday
D1 = date(2026, 6, 9)            # D-1 (Tue)
D2 = date(2026, 6, 8)            # D-2 (Mon)
D3 = date(2026, 6, 5)            # D-3 (Fri)
D4 = date(2026, 6, 4)            # D-4 (Thu)
D5 = date(2026, 6, 3)            # D-5 (Wed)
START = D - timedelta(days=30)


def _et(d: date, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=ET)


def _final_close(d: date) -> float:
    return 100.0 + d.toordinal() % 97


def _forming_close(d: date) -> float:
    return _final_close(d) - 50.0


def _weekdays(a: date, b: date) -> list[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class _World:
    """Clock + provider universe + recorded calls."""

    def __init__(self) -> None:
        self.now = _et(D, 11)
        self.calls: list[tuple[str, date, date]] = []
        self.alpaca_enabled = True
        # provider name -> None (serve the universe) or a callable(start, end) -> bars
        self.override: dict[str, object] = {}

    def bar(self, d: date) -> dict:
        settled = hs.is_settled(d, self.now)
        c = _final_close(d) if settled else _forming_close(d)
        return {"time": d.isoformat(), "open": c, "high": c + 1, "low": c - 1,
                "close": c, "volume": 1000}

    def serve(self, name: str, start: date, end: date, *, end_exclusive: bool) -> list[dict]:
        self.calls.append((name, start, end))
        if name in self.override:
            return self.override[name](start, end)  # type: ignore[operator]
        today = self.now.astimezone(ET).date()
        last = end - timedelta(days=1) if end_exclusive else end
        return [self.bar(d) for d in _weekdays(start, min(last, today))]


@pytest_asyncio.fixture
async def world(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)

    w = _World()
    w.factory = factory
    monkeypatch.setattr(hs, "_utcnow", lambda: w.now.astimezone(timezone.utc))

    import app.data.alpaca as alpaca

    async def _client():
        return object() if w.alpaca_enabled else None

    async def _alpaca(symbol, start, end, client=None):
        return w.serve("alpaca", start, end, end_exclusive=False)

    monkeypatch.setattr(alpaca, "get_alpaca_client", _client)
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", _alpaca)
    async def _tiingo(symbol, start, end):
        return w.serve("tiingo", start, end, end_exclusive=False)

    monkeypatch.setattr(hs, "fetch_historical_candles", _tiingo)
    monkeypatch.setattr(hs, "_yfinance_fetch",
                        lambda symbol, start, end: w.serve("yfinance", start, end, end_exclusive=True))
    yield w
    await engine.dispose()


async def _seed(w: _World, rows: list[tuple[date, datetime]], *, forming: set[date] = frozenset()):
    """Insert rows directly (bypassing the settle filter), as legacy writers did."""
    async with w.factory() as db:
        for d, fetched_at in rows:
            c = _forming_close(d) if d in forming else _final_close(d)
            db.add(OhlcvDailyModel(symbol="AAPL", date=d, open=c, high=c + 1, low=c - 1,
                                   close=c, volume=1000,
                                   fetched_at=fetched_at.astimezone(timezone.utc)))
        await db.commit()


def _nightly(d: date) -> datetime:
    """The nightly ingestion's fetched_at: 02:00 UTC the next day (well after settle)."""
    return datetime.combine(d + timedelta(days=1), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=2)


async def _stored(w: _World) -> dict[date, float]:
    async with w.factory() as db:
        res = await db.execute(select(OhlcvDailyModel.date, OhlcvDailyModel.close)
                               .where(OhlcvDailyModel.symbol == "AAPL"))
        return {d: float(c) for d, c in res.all()}


# ── 13. New writes never store the forming row ───────────────────────────────

@pytest.mark.asyncio
async def test_13_in_session_stale_fetch_stores_settled_rows_only(world):
    await _seed(world, [(d, _nightly(d)) for d in _weekdays(START, D2)])
    world.now = _et(D, 11)
    bars = await hs.get_bars("AAPL", START, D)
    stored = await _stored(world)
    assert D1 in stored and D not in stored
    assert stored[D1] == _final_close(D1)
    assert bars[-1]["time"] == D1.isoformat()
    assert world.calls == [("alpaca", D1, D)]


@pytest.mark.parametrize("clock,expect_d", [((17, 59, 59), False), ((18, 0, 0), True)])
@pytest.mark.asyncio
async def test_13_settle_boundary_is_1800_inclusive(world, clock, expect_d):
    await _seed(world, [(d, _nightly(d)) for d in _weekdays(START, D2)])
    world.now = _et(D, *clock)
    bars = await hs.get_bars("AAPL", START, D)
    stored = await _stored(world)
    assert D1 in stored
    assert (D in stored) is expect_d
    assert bars[-1]["time"] == (D if expect_d else D1).isoformat()
    if expect_d:
        assert stored[D] == _final_close(D)


# ── 14. The writer every caller shares (ingestion_job uses it directly) ─────

@pytest.mark.asyncio
async def test_14_store_bars_drops_todays_forming_row(world):
    world.now = _et(D, 11)
    batch = [world.bar(d) for d in _weekdays(D3, D)]
    async with world.factory() as db:
        stored_dates = await hs._store_bars("AAPL", batch, db)
        await db.commit()
    assert stored_dates == {D3, D2, D1}
    assert set(await _stored(world)) == {D3, D2, D1}


# ── 15. Legacy provisional row, heal-only mode ───────────────────────────────

@pytest.mark.asyncio
async def test_15_legacy_provisional_row_is_healed_length_unchanged(world):
    rows = [(d, _nightly(d)) for d in _weekdays(START, D2)] + [(D1, _et(D1, 11))]
    await _seed(world, rows, forming={D1})
    world.now = _et(D, 11)
    before = await _stored(world)
    assert before[D1] == _forming_close(D1)

    bars = await hs.get_bars("AAPL", START, D)
    after = await _stored(world)
    assert world.calls == [("alpaca", D1, D + timedelta(days=1))]
    assert after[D1] == _final_close(D1)
    assert D not in after
    assert len(bars) == len(before)
    assert (bars[-1]["time"], bars[-1]["close"]) == (D1.isoformat(), _final_close(D1))


# ── 16. A buried legacy row is reached by the stale fetch ────────────────────

@pytest.mark.asyncio
async def test_16_buried_provisional_row_moves_stale_fetch_start(world):
    rows = [(d, _nightly(d)) for d in _weekdays(START, D3) if d != D5] + [(D5, _et(D5, 11))]
    await _seed(world, rows, forming={D5})
    world.now = _et(D, 11)
    await hs.get_bars("AAPL", START, D)
    assert world.calls == [("alpaca", D5, D)]
    after = await _stored(world)
    assert after[D5] == _final_close(D5)
    assert D2 in after and D1 in after and D not in after


# ── 17. Heal success is the heal date stored; retry bound ────────────────────

@pytest.mark.asyncio
async def test_17_heal_falls_through_and_is_retried_every_6h(world):
    rows = [(d, _nightly(d)) for d in _weekdays(START, D2)] + [(D1, _et(D1, 11))]
    await _seed(world, rows, forming={D1})
    # Alpaca answers with another date but never the heal date; nobody has D-1.
    world.override["alpaca"] = lambda s, e: [world.bar(D2)]
    world.override["tiingo"] = lambda s, e: []
    world.override["yfinance"] = lambda s, e: []
    world.now = _et(D, 11)

    await hs.get_bars("AAPL", START, D)
    assert [c[0] for c in world.calls] == ["alpaca", "tiingo", "yfinance"]

    world.calls.clear()
    world.now = _et(D, 11) + timedelta(hours=5, minutes=59)
    await hs.get_bars("AAPL", START, D)
    assert world.calls == []

    world.now = _et(D, 17)
    await hs.get_bars("AAPL", START, D)
    assert [c[0] for c in world.calls] == ["alpaca", "tiingo", "yfinance"]
    assert (await _stored(world))[D1] == _forming_close(D1)


# ── 18. Fresh DB: no heal, no fetch ─────────────────────────────────────────

@pytest.mark.parametrize("clock", [(11, 0), (17, 0)])
@pytest.mark.asyncio
async def test_18_fresh_db_makes_zero_provider_calls(world, clock):
    await _seed(world, [(d, _nightly(d)) for d in _weekdays(START, D1)])
    world.now = _et(D, *clock)
    bars = await hs.get_bars("AAPL", START, D)
    assert world.calls == []
    assert bars[-1]["time"] == D1.isoformat()


# ── 19. fetched_at normalisation on a non-UTC host ───────────────────────────

@pytest.fixture
def la_host(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    _time.tzset()
    yield
    monkeypatch.undo()
    _time.tzset()


def test_19_as_utc_naive_is_utc_wall_clock_and_aware_is_converted(la_host):
    naive = datetime(2026, 6, 10, 20, 0)
    assert hs._as_utc(naive) == datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)
    aware = _et(D, 16)
    assert hs._as_utc(aware) == datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)
    assert hs._as_utc(aware).tzinfo == timezone.utc
    # A naive SQLite value of 21:59 UTC is provisional for D (settle 22:00 UTC) ...
    assert hs._is_provisional(D, datetime(2026, 6, 10, 21, 59)) is True
    # ... and 22:00 UTC is not. Read as LA local it would be 05:00 UTC next day.
    assert hs._is_provisional(D, datetime(2026, 6, 10, 22, 0)) is False


# ── 20. yfinance-only chain heals today's own legacy row after the settle ────

@pytest.mark.asyncio
async def test_20_yfinance_only_heals_todays_legacy_row(world):
    rows = [(d, _nightly(d)) for d in _weekdays(START, D1)] + [(D, _et(D, 11))]
    await _seed(world, rows, forming={D})
    world.alpaca_enabled = False
    world.override["tiingo"] = lambda s, e: []
    world.now = _et(D, 18)

    bars = await hs.get_bars("AAPL", START, D)
    assert ("yfinance", D, D + timedelta(days=1)) in world.calls
    assert (await _stored(world))[D] == _final_close(D)
    assert bars[-1]["close"] == _final_close(D)


@pytest.mark.asyncio
async def test_20b_todays_legacy_row_waits_for_its_own_settle(world):
    rows = [(d, _nightly(d)) for d in _weekdays(START, D1)] + [(D, _et(D, 11))]
    await _seed(world, rows, forming={D})
    world.now = _et(D, 17, 59, 59)
    await hs.get_bars("AAPL", START, D)
    assert world.calls == []


# ── 22. Q-H: the fetch rule is unchanged ────────────────────────────────────

@pytest.mark.asyncio
async def test_22_fetch_rule_unchanged_day_d_waits_for_nightly(world):
    await _seed(world, [(d, _nightly(d)) for d in _weekdays(START, D2)])
    world.now = _et(D, 11)
    await hs.get_bars("AAPL", START, D)
    assert world.calls == [("alpaca", D1, D)]

    world.calls.clear()
    world.now = _et(D, 17)
    bars = await hs.get_bars("AAPL", START, D)
    assert world.calls == []
    assert bars[-1]["time"] == D1.isoformat()


# ── host-date clock ─────────────────────────────────────────────────────────

def test_prev_trading_day_follows_utcnow(monkeypatch):
    monkeypatch.setattr(hs, "_utcnow", lambda: _et(D, 11).astimezone(timezone.utc))
    assert hs.most_recent_trading_day() == D
    assert hs._prev_trading_day() == D1
