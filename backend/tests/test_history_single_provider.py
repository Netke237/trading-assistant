import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs

START = date(2015, 12, 21)
SEAM = date(2016, 1, 4)
END = date(2016, 1, 11)
NOW = datetime(2026, 10, 9, 23, tzinfo=timezone.utc)


def days(start, end):
    result = []
    while start <= end:
        if start.weekday() < 5:
            result.append(start)
        start += timedelta(days=1)
    return result


def bars(start=START, end=END, *, source="tiingo", factor=1.0, close=100.0, skip=()):
    return [{"time": d.isoformat(), "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": 100,
             "adj_factor": factor, "split_factor": 1.0, "div_cash": 0.0,
             "source": source} for d in days(start, end) if d not in skip]


@pytest_asyncio.fixture
async def factory(monkeypatch):
    from app.services import history_backfill as history
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
    yield factory
    await engine.dispose()


@pytest.fixture
def providers(monkeypatch):
    tiingo_fetch = AsyncMock(return_value=[])
    yf_fetch = MagicMock(return_value=[])
    monkeypatch.setattr(tiingo, "fetch_historical_candles", tiingo_fetch)
    monkeypatch.setattr(hs, "_yfinance_fetch", yf_fetch)
    return tiingo_fetch, yf_fetch


async def seed_alpaca(factory, start=SEAM, end=END, **kw):
    async with factory() as db:
        await hs._store_bars("TEST", bars(start, end, source="alpaca", **kw), db)
        db.add(State(symbol="TEST", floor_requested_start=START, floor_date=SEAM,
                     floor_provider="alpaca", floor_checked_at=NOW - timedelta(days=60)))
        await db.commit()


async def snapshot(factory):
    async with factory() as db:
        rows = (await db.execute(select(M).order_by(M.date))).scalars().all()
        states = (await db.execute(select(State))).scalars().all()
        cols = [c.name for c in M.__table__.columns]
        scols = [c.name for c in State.__table__.columns]
        return ([tuple(getattr(r, c) for c in cols) for r in rows],
                [tuple(getattr(s, c) for c in scols) for s in states])


async def rows(factory):
    async with factory() as db:
        return (await db.execute(select(M).order_by(M.date))).scalars().all()


async def state(factory):
    async with factory() as db:
        return await db.get(State, "TEST")


@pytest.mark.asyncio
async def test_seam_refused_symbol_is_rebuilt_from_tiingo(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_alpaca(factory)
    tiingo_fetch.return_value = bars(factor=0.9)
    with pytest.raises(history.HistorySeamMismatch):
        await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    yf_fetch.reset_mock()
    result = await history.rebuild_single_provider("TEST", START, END)
    stored = await rows(factory)
    assert [r.date for r in stored] == days(START, END)
    assert {r.source for r in stored} == {"tiingo"}
    assert {float(r.adj_factor) for r in stored} == {0.9}
    st = await state(factory)
    assert st.basis_provider == "tiingo" and st.basis_rebuilt_at is not None
    assert st.seam_date is None and st.old_source is None and st.seam_signature is None
    assert st.floor_date == START and st.floor_provider == "tiingo"
    assert st.floor_requested_start == START
    assert result.provider == "tiingo"
    assert result.rows_before == len(days(SEAM, END))
    assert result.rows_after == len(days(START, END))
    assert result.first_date_before == SEAM
    assert result.first_date_after == START and result.last_date_after == END
    assert result.backfilled and not result.floor_reached
    yf_fetch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "empty", "invalid"])
async def test_tiingo_failure_falls_back_to_yfinance(factory, providers, failure):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_alpaca(factory)
    if failure == "raises":
        tiingo_fetch.side_effect = RuntimeError("tiingo down")
    elif failure == "invalid":
        bad = bars()
        bad[3]["close"] = 0
        tiingo_fetch.return_value = bad
    yf_fetch.return_value = bars(source="yfinance")
    result = await history.rebuild_single_provider("TEST", START, END)
    assert result.provider == "yfinance"
    assert {r.source for r in await rows(factory)} == {"yfinance"}
    assert (await state(factory)).basis_provider == "yfinance"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, reason", [
    ("omits_existing", "omits existing"), ("internal_gap", "internal gap"),
    ("identity_mismatch", "close differs"), ("mixed_source", "mixes sources"),
])
async def test_refusal_leaves_rows_and_state_untouched(factory, providers, reply, reason):
    from app.services import history_backfill as history
    tiingo_fetch, _ = providers
    await seed_alpaca(factory)
    if reply == "omits_existing":
        tiingo_fetch.return_value = bars(skip={date(2016, 1, 6)})
    elif reply == "internal_gap":
        tiingo_fetch.return_value = bars(skip=set(days(date(2015, 12, 22), date(2015, 12, 31))))
    elif reply == "identity_mismatch":
        tiingo_fetch.return_value = bars(close=102.0)
    else:
        mixed = bars()
        mixed[2]["source"] = "alpaca"
        tiingo_fetch.return_value = mixed
    before = await snapshot(factory)
    with pytest.raises(history.SingleProviderRefused) as info:
        await history.rebuild_single_provider("TEST", START, END)
    assert not isinstance(info.value, history.HistorySeamMismatch)
    assert isinstance(info.value, ValueError)
    assert "tiingo:" in str(info.value) and "yfinance:" in str(info.value)
    assert reason in str(info.value)
    assert await snapshot(factory) == before


@pytest.mark.asyncio
async def test_both_providers_fail_refuses_without_changes(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_alpaca(factory)
    tiingo_fetch.side_effect = RuntimeError("tiingo down")
    yf_fetch.side_effect = RuntimeError("yfinance down")
    before = await snapshot(factory)
    with pytest.raises(history.SingleProviderRefused) as info:
        await history.rebuild_single_provider("TEST", START, END)
    assert "tiingo down" in str(info.value) and "yfinance down" in str(info.value)
    assert await snapshot(factory) == before


@pytest.mark.asyncio
async def test_tiingo_identity_compares_raw_closes_against_alpaca(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, _ = providers
    await seed_alpaca(factory, factor=1.0)
    tiingo_fetch.return_value = bars(factor=0.95)
    result = await history.rebuild_single_provider("TEST", START, END)
    assert result.provider == "tiingo"


@pytest.mark.asyncio
async def test_yfinance_identity_compares_adjusted_closes(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_alpaca(factory, factor=0.9)
    yf_fetch.return_value = bars(source="yfinance", close=90.0)
    result = await history.rebuild_single_provider("TEST", START, END)
    assert result.provider == "yfinance"


@pytest.mark.asyncio
async def test_store_failure_on_second_chunk_rolls_back_and_tries_next_provider(factory, providers, monkeypatch):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    long_start = date(2013, 1, 1)
    assert len(days(long_start, END)) > 500
    await seed_alpaca(factory)
    tiingo_fetch.return_value = bars(long_start, END, factor=0.9)
    real_store = hs._store_bars
    calls = []

    async def failing_store(symbol, items, db):
        calls.append(len(items))
        if len(calls) == 1:
            await real_store(symbol, items[:500], db)
            raise RuntimeError("synthetic chunk failure")
        return await real_store(symbol, items, db)

    monkeypatch.setattr(hs, "_store_bars", failing_store)
    before = await snapshot(factory)
    with pytest.raises(history.SingleProviderRefused) as info:
        await history.rebuild_single_provider("TEST", long_start, END)
    assert "synthetic chunk failure" in str(info.value)
    assert await snapshot(factory) == before

    calls.clear()
    yf_fetch.return_value = bars(long_start, END, source="yfinance")
    result = await history.rebuild_single_provider("TEST", long_start, END)
    assert result.provider == "yfinance"
    stored = await rows(factory)
    assert {r.source for r in stored} == {"yfinance"}
    assert len(stored) == len(days(long_start, END))
    assert (await state(factory)).basis_provider == "yfinance"


@pytest.mark.asyncio
async def test_update_history_routes_single_provider_symbol_away_from_seam(factory, providers, monkeypatch):
    from app.services import history_backfill as history
    from app.data import alpaca
    tiingo_fetch, yf_fetch = providers
    await seed_alpaca(factory, end=date(2016, 1, 8))
    tiingo_fetch.return_value = bars(end=date(2016, 1, 8), factor=0.9)
    await history.rebuild_single_provider("TEST", START, END)
    fallback = AsyncMock(return_value=[])
    client = AsyncMock(return_value=object())
    single = AsyncMock(return_value=bars(SEAM, source="alpaca"))
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    monkeypatch.setattr(alpaca, "get_alpaca_client", client)
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", single)
    tiingo_fetch.return_value = bars(factor=0.9)
    result = await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    assert result.provider == "tiingo"
    assert result.stored == len(days(START, END))
    stored = await rows(factory)
    assert stored[-1].date == END and stored[-1].source == "tiingo"
    assert {r.source for r in stored} == {"tiingo"}
    result = await history.update_history("TEST", START, END)
    assert result.provider == "tiingo"
    fallback.assert_not_awaited()
    client.assert_not_awaited()
    single.assert_not_awaited()

    tiingo_fetch.return_value = []
    tiingo_fetch.side_effect = RuntimeError("tiingo down")
    yf_fetch.return_value = bars(source="yfinance")
    before = await snapshot(factory)
    with pytest.raises(history.SingleProviderRefused):
        await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    yf_fetch.assert_not_called()
    assert await snapshot(factory) == before
    assert (await state(factory)).basis_provider == "tiingo"


@pytest.mark.asyncio
async def test_normal_path_result_has_no_provider(factory, monkeypatch):
    from app.services import history_backfill as history
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()))
    result = await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    assert result.provider is None
    assert (await state(factory)).basis_provider is None


@pytest.mark.asyncio
async def test_rebuild_holds_the_history_lock(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, _ = providers
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def fetch(symbol, start, end, **kw):
        calls.append(symbol)
        if len(calls) == 1:
            started.set()
            await release.wait()
        return bars(factor=0.9)

    tiingo_fetch.side_effect = fetch
    rebuild = asyncio.create_task(history.rebuild_single_provider("TEST", START, END))
    await started.wait()
    update = asyncio.create_task(
        history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca")))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not update.done() and len(calls) == 1
    release.set()
    await rebuild
    result = await update
    assert len(calls) == 2
    assert result.provider == "tiingo"


# ── HISTORY-INCREMENTAL-NIGHTLY B0: the nightly-only window anchor ────────────

ANCHOR_THROUGH = date(2015, 12, 31)
ANCHOR_AT = datetime(2026, 9, 1, 23, tzinfo=timezone.utc)


async def seed_single_provider(factory, provider, end=date(2016, 1, 8), *, anchored=True):
    async with factory() as db:
        await hs._store_bars("TEST", bars(START, end, source=provider), db)
        db.add(State(symbol="TEST", basis_provider=provider,
                     window_verified_through=ANCHOR_THROUGH if anchored else None,
                     window_verified_at=ANCHOR_AT if anchored else None))
        await db.commit()


@pytest.mark.asyncio
async def test_rebuild_sets_window_anchor_to_newest_stored_date(factory, providers):
    from app.services import history_backfill as history
    tiingo_fetch, _ = providers
    last = date(2016, 1, 8)
    await seed_alpaca(factory, end=last)
    tiingo_fetch.return_value = bars(end=last, factor=0.9)
    result = await history.rebuild_single_provider("TEST", START, END)
    st = await state(factory)
    assert result.last_date_after == last
    assert st.window_verified_through == last  # the newest stored date, not `end`
    assert hs._as_utc(st.window_verified_at) == NOW
    assert hs._as_utc(st.window_verified_at) == hs._as_utc(st.basis_rebuilt_at)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["tiingo", "yfinance"])
@pytest.mark.parametrize("anchored", [False, True])
async def test_nightly_single_provider_path_sets_window_anchor(factory, providers, monkeypatch,
                                                               provider, anchored):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_single_provider(factory, provider, anchored=anchored)
    later = NOW + timedelta(days=1)
    monkeypatch.setattr(hs, "_utcnow", lambda: later)
    (tiingo_fetch if provider == "tiingo" else yf_fetch).return_value = bars(source=provider)
    result = await history.update_history("TEST", START, END)
    assert result.provider == provider
    st = await state(factory)
    assert st.window_verified_through == END
    assert hs._as_utc(st.window_verified_at) == later
    assert hs._as_utc(st.basis_rebuilt_at) == later


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["rebuild", "nightly"])
async def test_refused_single_provider_write_leaves_window_anchor_unchanged(factory, providers, path):
    from app.services import history_backfill as history
    tiingo_fetch, yf_fetch = providers
    await seed_single_provider(factory, "tiingo")
    tiingo_fetch.return_value = bars(skip={date(2016, 1, 6)})
    yf_fetch.return_value = bars(source="yfinance", skip={date(2016, 1, 6)})
    before = await snapshot(factory)
    with pytest.raises(history.SingleProviderRefused):
        if path == "rebuild":
            await history.rebuild_single_provider("TEST", START, END)
        else:
            await history.update_history("TEST", START, END)
    assert await snapshot(factory) == before
    st = await state(factory)
    assert st.window_verified_through == ANCHOR_THROUGH
    assert hs._as_utc(st.window_verified_at) == ANCHOR_AT


@pytest.mark.asyncio
async def test_refresh_adjustments_injected_fetch_clears_window_anchor(factory, monkeypatch):
    """The test-only ``fetch=`` branch clears the anchor with the other state fields."""
    first = [{**b, "adj_factor": 0.98} for b in bars(START, date(2015, 12, 31), source="alpaca")]
    second = bars(date(2016, 1, 1), END, source="alpaca")
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW - timedelta(days=30))
    async with factory() as db:
        await hs._store_bars("TEST", first, db)
        await db.commit()
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
    async with factory() as db:
        await hs._store_bars("TEST", second, db)
        db.add(State(symbol="TEST", seam_date=SEAM, old_source="tiingo", seam_signature="abc",
                     window_verified_through=ANCHOR_THROUGH, window_verified_at=ANCHOR_AT))
        await db.commit()
    async with factory() as db:
        assert await hs.find_stale_adjustment("TEST", db) is not None

    async def fake(symbol, start, end):
        return bars(start, end, source="alpaca")

    result = await hs.refresh_adjustments(["TEST"], fetch=fake)
    assert result["refreshed"] == ["TEST"]
    st = await state(factory)
    assert st.seam_date is None and st.seam_signature is None
    assert st.window_verified_through is None
    assert st.window_verified_at is None
