"""Stale adjustment-factor detection and refresh (TRADING-REVIEW-PHASE-C T3).

Rows stored in earlier fetch batches keep the ``adj_factor`` the provider reported on
their fetch date. ``find_stale_adjustment`` flags a symbol whose stored series cannot be
on one basis (rules a-d); ``refresh_adjustments`` re-fetches its whole stored window and
upserts it, never deleting a row.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.historical_store as hs
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services.scheduling_tz import MARKET_TZ


# ── Helpers ───────────────────────────────────────────────────────────────────

def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _weekdays(date(2024, 3, 4), 10)


def _evening(d: date) -> datetime:
    """20:00 ET on ``d``: after d's 18:00 ET settle instant, so d's bar is stored."""
    return datetime.combine(d, dtime(20, 0), tzinfo=MARKET_TZ)


def _bar(d: date, close: float, *, adj: float | None = 1.0, split: float | None = 1.0,
         div: float | None = 0.0, source: str | None = "alpaca") -> dict:
    return {
        "time": d.isoformat(),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": 1_000,
        "adj_factor": adj, "split_factor": split, "div_cash": div, "source": source,
    }


@pytest_asyncio.fixture
async def factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(hs, "AsyncSessionLocal", f)
    yield f
    await engine.dispose()


async def _store(factory, monkeypatch, symbol: str, bars: list[dict], now: datetime) -> None:
    """One fetch batch: every row gets ``fetched_at = now``."""
    monkeypatch.setattr(hs, "_utcnow", lambda: now)
    async with factory() as db:
        await hs._store_bars(symbol, bars, db)
        await db.commit()


async def _stale(factory, symbol: str):
    async with factory() as db:
        return await hs.find_stale_adjustment(symbol, db)


async def _count(factory, symbol: str) -> int:
    async with factory() as db:
        res = await db.execute(
            select(func.count()).select_from(OhlcvDailyModel)
            .where(OhlcvDailyModel.symbol == symbol)
        )
        return res.scalar_one()


async def _seed_batch_step(factory, monkeypatch, symbol: str = "SYM") -> None:
    """Two batches, factor 0.98 then 1.0 at the boundary, raw close continuous."""
    await _store(factory, monkeypatch, symbol,
                 [_bar(d, 100.0, adj=0.98) for d in DAYS[:5]], _evening(DAYS[4]))
    await _store(factory, monkeypatch, symbol,
                 [_bar(d, 100.0, adj=1.0) for d in DAYS[5:]], _evening(DAYS[9]))


# ── Detection ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_batch_with_dividend_step_not_flagged(factory, monkeypatch):
    bars = [_bar(d, 100.0, adj=0.995, source="tiingo") for d in DAYS[:5]]
    bars.append(_bar(DAYS[5], 99.5, adj=1.0, div=0.5, source="tiingo"))
    bars += [_bar(d, 99.5, adj=1.0, source="tiingo") for d in DAYS[6:]]
    await _store(factory, monkeypatch, "SYM", bars, _evening(DAYS[9]) + timedelta(days=1))
    assert await _stale(factory, "SYM") is None


@pytest.mark.asyncio
async def test_rule_a_unexplained_jump_flagged(factory, monkeypatch):
    for d in DAYS[:5]:
        await _store(factory, monkeypatch, "GE", [_bar(d, 10.0)], _evening(d))
    # GE 2021-08-02 style 1:8 reverse split arriving as the first row of a new batch.
    await _store(factory, monkeypatch, "GE", [_bar(DAYS[5], 80.0)], _evening(DAYS[5]))
    report = await _stale(factory, "GE")
    assert report is not None
    assert "jump" in report.reasons
    assert report.earliest == DAYS[0]


@pytest.mark.asyncio
async def test_rule_b_fetched_before_later_dividend_flagged(factory, monkeypatch):
    for d in DAYS[:5]:
        await _store(factory, monkeypatch, "SYM", [_bar(d, 100.0, source="tiingo")], _evening(d))
    await _store(factory, monkeypatch, "SYM",
                 [_bar(DAYS[5], 99.5, div=0.5, source="tiingo")], _evening(DAYS[5]))
    report = await _stale(factory, "SYM")
    assert report is not None
    assert report.reasons == ["pre_action_fetch"]
    assert report.earliest == DAYS[0]


@pytest.mark.asyncio
async def test_rule_c_batch_boundary_factor_step_flagged(factory, monkeypatch):
    await _seed_batch_step(factory, monkeypatch)
    report = await _stale(factory, "SYM")
    assert report is not None
    assert report.reasons == ["batch_step"]
    assert report.earliest == DAYS[0]


@pytest.mark.asyncio
async def test_rule_d_mixed_basis_flagged(factory, monkeypatch):
    now = _evening(DAYS[9]) + timedelta(days=1)
    null_then_factored = (
        [_bar(d, 100.0, adj=None, split=None, div=None, source="tiingo") for d in DAYS[:5]]
        + [_bar(d, 100.0, adj=1.0, source="tiingo") for d in DAYS[5:]]
    )
    await _store(factory, monkeypatch, "NUL", null_then_factored, now)
    report = await _stale(factory, "NUL")
    assert report is not None
    assert report.reasons == ["mixed_basis"]

    two_sources = (
        [_bar(d, 100.0, source="yfinance") for d in DAYS[:5]]
        + [_bar(d, 100.0, source="alpaca") for d in DAYS[5:]]
    )
    await _store(factory, monkeypatch, "SRC", two_sources, now)
    report = await _stale(factory, "SRC")
    assert report is not None
    assert report.reasons == ["mixed_basis"]


@pytest.mark.asyncio
async def test_real_fifteen_percent_move_not_flagged(factory, monkeypatch):
    bars = [_bar(d, 100.0) for d in DAYS[:5]] + [_bar(d, 115.0) for d in DAYS[5:]]
    await _store(factory, monkeypatch, "SYM", bars, _evening(DAYS[9]) + timedelta(days=1))
    assert await _stale(factory, "SYM") is None


# ── Refresh ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_fetches_flagged_only_and_upserts(factory, monkeypatch, conf_cache):
    await _seed_batch_step(factory, monkeypatch, "SYM")
    await _store(factory, monkeypatch, "CLEAN",
                 [_bar(d, 50.0) for d in DAYS], _evening(DAYS[9]))

    calls: list[tuple[str, date, date]] = []

    async def fake(symbol, start, end):
        calls.append((symbol, start, end))
        return [_bar(d, 100.0, adj=1.0) for d in DAYS]

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    result = await hs.refresh_adjustments(["SYM", "CLEAN"], fetch=fake)

    assert calls == [("SYM", DAYS[0], DAYS[9])]
    assert result["checked"] == 2
    assert [s["symbol"] for s in result["stale"]] == ["SYM"]
    assert result["refreshed"] == ["SYM"]
    assert result["failed"] == []
    assert await _stale(factory, "SYM") is None


@pytest.mark.asyncio
async def test_refresh_never_deletes_rows(factory, monkeypatch, conf_cache):
    await _seed_batch_step(factory, monkeypatch, "SYM")
    before = await _count(factory, "SYM")

    async def fake(symbol, start, end):
        return [_bar(d, 100.0, adj=1.0) for d in DAYS[-2:]]

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    await hs.refresh_adjustments(["SYM"], fetch=fake)
    assert await _count(factory, "SYM") == before == len(DAYS)


@pytest.mark.asyncio
async def test_refresh_adjustments_endpoint(factory, monkeypatch, conf_cache):
    from app.routers.historical_data import router

    await _seed_batch_step(factory, monkeypatch, "SYM")

    async def fake(symbol, start, end):
        return [_bar(d, 100.0, adj=1.0) for d in DAYS]

    monkeypatch.setattr(hs, "_fetch_window", fake)
    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/historical-data/refresh-adjustments", json={"symbols": ["SYM"]}
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "checked": 1,
        "stale": [{"symbol": "SYM", "reasons": ["batch_step"], "earliest": DAYS[0].isoformat()}],
        "refreshed": ["SYM"],
        "failed": [],
    }


# ── Confidence-cache eviction on refresh (audit finding R1-F1) ────────────────
# The confidence cache key does not depend on the bars, so a refresh that rewrites a
# symbol's adj_factors must evict that symbol's cached confidence, or scans keep serving
# a value computed on the pre-refresh series.

@pytest.fixture
def conf_cache(monkeypatch, tmp_path):
    """Isolate the confidence cache from the real backend/data/confidence_cache.db."""
    import app.data.confidence_cache as cc

    monkeypatch.setattr(cc, "_DB_PATH", str(tmp_path / "confidence_cache.db"))
    monkeypatch.setattr(cc, "_store", {})
    monkeypatch.setattr(cc, "_symbol_generation", {}, raising=False)
    monkeypatch.setattr(cc, "_clear_generation", 0, raising=False)
    cc._init_db()
    return cc


def _db_keys(cc) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(cc._DB_PATH)
    try:
        return {k for (k,) in conn.execute("SELECT cache_key FROM confidence_cache")}
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_refresh_evicts_refreshed_symbols_cached_confidence(factory, monkeypatch, conf_cache):
    cc = conf_cache
    await _seed_batch_step(factory, monkeypatch, "SYM")
    await _store(factory, monkeypatch, "OTHER",
                 [_bar(d, 50.0) for d in DAYS], _evening(DAYS[9]))
    sym_key = cc.cache_key("SYM", "Bullish", "Swing", scoring_mode="stock")
    other_key = cc.cache_key("OTHER", "Bullish", "Swing", scoring_mode="stock")
    await cc.set_cached(sym_key, {"confidence": 70})
    await cc.set_cached(other_key, {"confidence": 60})

    async def fake(symbol, start, end):
        return [_bar(d, 100.0, adj=1.0) for d in DAYS]

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    result = await hs.refresh_adjustments(["SYM", "OTHER"], fetch=fake)

    assert result["refreshed"] == ["SYM"]
    assert cc.get_cached(sym_key) is None
    assert sym_key not in _db_keys(cc)
    assert cc.get_cached(other_key) == {"confidence": 60}
    assert other_key in _db_keys(cc)


@pytest.mark.asyncio
async def test_invalidate_symbol_is_an_exact_prefix_match(conf_cache):
    cc = conf_cache
    aapl = cc.cache_key("AAPL", "Bullish", "Swing", scoring_mode="stock")
    aaplx = cc.cache_key("AAPLX", "Bullish", "Swing", scoring_mode="stock")
    await cc.set_cached(aapl, {"confidence": 70})
    await cc.set_cached(aaplx, {"confidence": 65})

    assert cc.invalidate_symbol("aapl") == 1

    assert cc.get_cached(aapl) is None
    assert cc.get_cached(aaplx) == {"confidence": 65}
    assert _db_keys(cc) == {aaplx}


@pytest.mark.asyncio
async def test_refresh_failed_symbol_keeps_cached_confidence(factory, monkeypatch, conf_cache):
    cc = conf_cache
    await _seed_batch_step(factory, monkeypatch, "SYM")
    sym_key = cc.cache_key("SYM", "Bullish", "Swing", scoring_mode="stock")
    await cc.set_cached(sym_key, {"confidence": 70})

    async def boom(symbol, start, end):
        raise RuntimeError("provider down")

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    result = await hs.refresh_adjustments(["SYM"], fetch=boom)

    assert result["failed"] == ["SYM"]
    assert cc.get_cached(sym_key) == {"confidence": 70}
    assert sym_key in _db_keys(cc)


# ── In-flight computations across a refresh (audit finding R2-F1) ─────────────
# A writer reads bars, computes confidence, then stores it. If a refresh evicts the
# symbol between the read and the store, the store would put the pre-refresh value
# back for the whole TTL. Each writer captures confidence_cache.generation() before
# its bars are read and passes it as bars_generation; set_cached drops the value when
# the symbol was invalidated after that capture.

@pytest.mark.asyncio
async def test_set_cached_drops_value_computed_before_the_symbols_invalidation(conf_cache):
    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    g = cc.generation()
    cc.invalidate_symbol("xyz")

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)

    assert cc.get_cached(key) is None
    assert key not in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_keeps_other_symbols_value_with_the_same_generation(conf_cache):
    cc = conf_cache
    key = cc.cache_key("YYY", "Bullish", "Swing", scoring_mode="stock")
    g = cc.generation()
    cc.invalidate_symbol("XYZ")

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)

    assert cc.get_cached(key) == {"confidence": 70}
    assert key in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_keeps_value_whose_generation_follows_the_invalidation(conf_cache):
    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    cc.invalidate_symbol("XYZ")
    g = cc.generation()

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)

    assert cc.get_cached(key) == {"confidence": 70}
    assert key in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_without_generation_stores_as_before(conf_cache):
    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    cc.invalidate_symbol("XYZ")

    await cc.set_cached(key, {"confidence": 70})

    assert cc.get_cached(key) == {"confidence": 70}
    assert key in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_db_write_does_not_resurrect_row_evicted_mid_write(monkeypatch, conf_cache):
    """The memory write passed the generation check, then invalidate_symbol lands
    before the SQLite write. Its DELETE must not run ahead of the writer's INSERT,
    or the stale row comes back on the next restart's warm load (R2-F1).

    Deterministic interleaving, no sleeps: when the SQLite write for XYZ begins, an
    invalidation thread is started and the write waits until that thread has either
    finished (DELETE already run) or is about to take _db_lock (DELETE held back).
    """
    import threading

    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    other = cc.cache_key("YYY", "Bullish", "Swing", scoring_mode="stock")
    g = cc.generation()

    reached = threading.Event()   # invalidation finished, or is waiting on _db_lock
    inval: dict = {}
    real_db_lock = getattr(cc, "_db_lock", threading.Lock())

    class _ObservedLock:
        def __enter__(self):
            if threading.current_thread() is inval.get("thread"):
                reached.set()
            real_db_lock.acquire()
            return self

        def __exit__(self, *exc):
            real_db_lock.release()
            return False

    monkeypatch.setattr(cc, "_db_lock", _ObservedLock(), raising=False)

    def _invalidate():
        try:
            cc.invalidate_symbol("XYZ")
        finally:
            reached.set()

    real_write_db = cc._write_db

    def _write_db_with_eviction(k, value, expires_at):
        if k == key and "thread" not in inval:
            t = threading.Thread(target=_invalidate)
            inval["thread"] = t
            t.start()
            assert reached.wait(timeout=10), "invalidation thread never progressed"
        real_write_db(k, value, expires_at)

    monkeypatch.setattr(cc, "_write_db", _write_db_with_eviction)

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)
    inval["thread"].join(timeout=10)
    assert not inval["thread"].is_alive()

    assert key not in _db_keys(cc)
    assert cc.get_cached(key) is None

    # An unconditional write for another symbol still reaches SQLite.
    await cc.set_cached(other, {"confidence": 55})
    assert other in _db_keys(cc)
    assert cc.get_cached(other) == {"confidence": 55}


# ── clear_cache invalidates in-flight writes (TRADING-REVIEW-PHASE-C-HYGIENE T2) ──
# clear_cache() is a whole-cache invalidation: a value computed from bars read before
# the clear must not land in memory or SQLite afterwards, exactly as for one symbol's
# invalidate_symbol above.

@pytest.mark.asyncio
async def test_set_cached_drops_value_computed_before_clear_cache(conf_cache):
    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    g = cc.generation()
    cc.clear_cache()

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)

    assert cc.get_cached(key) is None
    assert key not in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_without_generation_stores_after_clear_cache(conf_cache):
    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    cc.clear_cache()

    await cc.set_cached(key, {"confidence": 70})

    assert cc.get_cached(key) == {"confidence": 70}
    assert key in _db_keys(cc)


@pytest.mark.asyncio
async def test_set_cached_db_write_does_not_resurrect_row_cleared_mid_write(monkeypatch, conf_cache):
    """The memory write passed the generation check, then clear_cache lands before
    the SQLite write. Its DELETE must wait for the writer's INSERT (it takes
    _db_lock), or the stale row comes back on the next restart's warm load.

    Same deterministic interleaving as the R2-F1 test above: when the SQLite write
    for XYZ begins, a clear_cache thread is started and the write waits until that
    thread has either finished (DELETE already run) or is about to take _db_lock
    (DELETE held back).
    """
    import threading

    cc = conf_cache
    key = cc.cache_key("XYZ", "Bullish", "Swing", scoring_mode="stock")
    other = cc.cache_key("YYY", "Bullish", "Swing", scoring_mode="stock")
    g = cc.generation()

    reached = threading.Event()   # clear finished, or is waiting on _db_lock
    clearer: dict = {}
    real_db_lock = getattr(cc, "_db_lock", threading.Lock())

    class _ObservedLock:
        def __enter__(self):
            if threading.current_thread() is clearer.get("thread"):
                reached.set()
            real_db_lock.acquire()
            return self

        def __exit__(self, *exc):
            real_db_lock.release()
            return False

    monkeypatch.setattr(cc, "_db_lock", _ObservedLock(), raising=False)

    def _clear():
        try:
            cc.clear_cache()
        finally:
            reached.set()

    real_write_db = cc._write_db

    def _write_db_with_clear(k, value, expires_at):
        if k == key and "thread" not in clearer:
            t = threading.Thread(target=_clear)
            clearer["thread"] = t
            t.start()
            assert reached.wait(timeout=10), "clear_cache thread never progressed"
        real_write_db(k, value, expires_at)

    monkeypatch.setattr(cc, "_write_db", _write_db_with_clear)

    await cc.set_cached(key, {"confidence": 70}, bars_generation=g)
    clearer["thread"].join(timeout=10)
    assert not clearer["thread"].is_alive()

    assert key not in _db_keys(cc)
    assert cc.get_cached(key) is None

    # An unconditional write after the clear still reaches SQLite.
    await cc.set_cached(other, {"confidence": 55})
    assert other in _db_keys(cc)
    assert cc.get_cached(other) == {"confidence": 55}


def _keys_for(cc, symbol: str) -> tuple[list[str], list[str]]:
    """(memory keys, SQLite keys) cached for ``symbol``."""
    prefix = f"{symbol.upper()}|"
    return ([k for k in cc._store if k.startswith(prefix)],
            sorted(k for k in _db_keys(cc) if k.startswith(prefix)))


def _conf_stub(calls: list):
    from types import SimpleNamespace

    def _stub(bars, **kw):
        calls.append(kw)
        return SimpleNamespace(confidence=77, sample_size=40)
    return _stub


@pytest.mark.asyncio
async def test_prefetch_drops_confidence_when_refresh_lands_mid_read(monkeypatch, conf_cache):
    cc = conf_cache
    bars = [_bar(d, 100.0) for d in DAYS]

    async def fake_get_bars(symbol, start, end):
        if symbol == "SYM":
            cc.invalidate_symbol(symbol)   # a refresh commits while this read is in flight
        return bars

    calls: list = []
    monkeypatch.setattr(hs, "get_bars", fake_get_bars)
    monkeypatch.setattr(hs, "compute_confidence", _conf_stub(calls))
    monkeypatch.setattr(hs, "_prefetch_state", {})

    await hs._run_prefetch(["SYM", "OTHER"], 1, 0)

    assert len(calls) == 24                       # 12 combos computed per symbol
    assert _keys_for(cc, "SYM") == ([], [])
    mem, db = _keys_for(cc, "OTHER")
    assert len(mem) == len(db) == 12


async def _drive_process_stock(monkeypatch, cc, symbol: str, invalidate: bool):
    from unittest.mock import AsyncMock, MagicMock

    import app.routers.stock_scan as ss
    from app.schemas.stock_scan import StockScanRequest
    from tests.test_confidence_gate_stocks import (
        _make_fake_bars, _make_fake_bt, _make_fake_card, _make_fake_signal,
    )

    fake_bars = _make_fake_bars()

    async def fake_bars_read(sym, start, end):
        if invalidate:
            cc.invalidate_symbol(sym)
        return fake_bars

    calls: list = []
    monkeypatch.setattr(ss, "get_historical_bars", fake_bars_read)
    monkeypatch.setattr(ss, "fetch_company_name_async", AsyncMock(return_value="Co"))
    monkeypatch.setattr(ss, "fetch_price_async", AsyncMock(return_value=152.0))
    monkeypatch.setattr(ss, "score_stock", MagicMock(return_value=_make_fake_card()))
    monkeypatch.setattr(ss, "compute_omm", MagicMock(return_value=None))
    monkeypatch.setattr(ss, "_get_fundamentals", AsyncMock(return_value=None))
    monkeypatch.setattr(ss, "_SIGNAL_FNS", {"pullback_ema": lambda *a, **kw: _make_fake_signal()})
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: _make_fake_bt())
    monkeypatch.setattr(ss, "compute_confidence", _conf_stub(calls))
    req = StockScanRequest(universe=[symbol], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema")
    await ss._process_stock(symbol, req, "scan-r2f1", {}, [])
    return calls


@pytest.mark.asyncio
async def test_stock_scan_drops_confidence_when_refresh_lands_mid_read(monkeypatch, conf_cache):
    cc = conf_cache
    calls = await _drive_process_stock(monkeypatch, cc, "AAPL", invalidate=True)
    assert len(calls) == 1
    assert _keys_for(cc, "AAPL") == ([], [])

    calls = await _drive_process_stock(monkeypatch, cc, "MSFT", invalidate=False)
    assert len(calls) == 1
    mem, db = _keys_for(cc, "MSFT")
    assert len(mem) == len(db) == 1


async def _drive_analyze_core(monkeypatch, cc, symbol: str, invalidate: bool):
    import types
    from unittest.mock import MagicMock

    import app.routers.stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest
    from tests.test_a5_analysis_mirrors_scan import _BARS, _offline

    _offline(monkeypatch, conviction=10)

    async def fake_bars_read(sym, start, end):
        if invalidate and sym == symbol:
            cc.invalidate_symbol(sym)
        return _BARS

    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy="pullback_ema")
    calls: list = []
    monkeypatch.setattr(ss, "get_historical_bars", fake_bars_read)
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", MagicMock(return_value=sig))
    monkeypatch.setattr(ss, "_get_backtest_cached",
                        lambda key: types.SimpleNamespace(passes_gate=True, summary_text="ok"))
    monkeypatch.setattr(ss, "compute_confidence", _conf_stub(calls))
    await ss._analyze_core(symbol, StockAnalysisRequest(symbol=symbol))
    return calls


@pytest.mark.asyncio
async def test_stock_analysis_drops_confidence_when_refresh_lands_mid_read(monkeypatch, conf_cache):
    cc = conf_cache
    calls = await _drive_analyze_core(monkeypatch, cc, "AAPL", invalidate=True)
    assert len(calls) == 1
    assert _keys_for(cc, "AAPL") == ([], [])

    calls = await _drive_analyze_core(monkeypatch, cc, "MSFT", invalidate=False)
    assert len(calls) == 1
    mem, db = _keys_for(cc, "MSFT")
    assert len(mem) == len(db) == 1


def test_options_scan_drops_confidence_when_refresh_lands_mid_read(client, conf_cache):
    """Through POST /api/scan: every symbol's bars are read up front, so a refresh that
    lands during that read must keep that symbol's confidence out of the cache."""
    from unittest.mock import patch

    from tests.test_scan_endpoint import (
        _MOCK_CANDLES, _enter_mock_patches, _force_passing_stock_score, _rr_test_chain,
    )

    cc = conf_cache

    async def fake_get_bars(symbol, start, end):
        if symbol == "AAPL":
            cc.invalidate_symbol(symbol)
        return list(_MOCK_CANDLES)

    calls: list = []
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Co"), \
         patch("app.routers.scan.fetch_quotes", return_value={}), \
         patch("app.services.historical_store.get_bars", fake_get_bars), \
         patch("app.routers.scan.compute_confidence", _conf_stub(calls)), \
         _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL", "MSFT"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {},
        })

    assert r.status_code == 200, r.text
    assert len(calls) == 2                        # both symbols reached the confidence site
    assert _keys_for(cc, "AAPL") == ([], [])
    mem, db = _keys_for(cc, "MSFT")
    assert len(mem) == len(db) == 1


# ── Backtest-cache eviction on refresh (TRADING-REVIEW-PHASE-C-HYGIENE T6) ────
# stock_scan._backtest_key hashes only the last 20 (time, close) pairs, so a refresh
# that rewrites older adj_factors leaves the key unchanged and the pre-refresh
# BacktestResult would be served for _BACKTEST_TTL (24 h). refresh_adjustments evicts
# the refreshed symbol's entries (through the endpoint's on_refreshed callback), and a
# backtest in flight across the refresh is used for its own request but not stored.

@pytest.fixture
def bt_cache(monkeypatch):
    """An empty, isolated stock_scan._BACKTEST_CACHE."""
    import app.routers.stock_scan as ss

    cache: dict = {}
    monkeypatch.setattr(ss, "_BACKTEST_CACHE", cache)
    return cache


def _bt_entry():
    import time as _time

    return (object(), _time.time() + 3600)


def test_evict_backtest_cache_is_an_exact_prefix_match(bt_cache):
    import app.routers.stock_scan as ss

    bt_cache["AAPL|pullback_ema|bullish|h1|b2|p|0.002000|None|None"] = _bt_entry()
    bt_cache["AAPLX|pullback_ema|bullish|h1|b2|p|0.002000|None|None"] = _bt_entry()

    assert ss.evict_backtest_cache(["aapl"]) == 1

    assert list(bt_cache) == ["AAPLX|pullback_ema|bullish|h1|b2|p|0.002000|None|None"]


@pytest.mark.asyncio
async def test_refresh_calls_on_refreshed_once_per_refreshed_symbol(factory, monkeypatch, conf_cache):
    cc = conf_cache
    await _seed_batch_step(factory, monkeypatch, "SYM")
    await _seed_batch_step(factory, monkeypatch, "FAIL")
    await _store(factory, monkeypatch, "CLEAN",
                 [_bar(d, 50.0) for d in DAYS], _evening(DAYS[9]))

    async def fake(symbol, start, end):
        if symbol == "FAIL":
            raise RuntimeError("provider down")
        return [_bar(d, 100.0, adj=1.0) for d in DAYS]

    g = cc.generation()
    seen: list[tuple[str, bool]] = []

    def spy(symbol):
        # Called after invalidate_symbol, so an in-flight writer's generation is stale.
        seen.append((symbol, cc.invalidated_since(symbol, g)))

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    result = await hs.refresh_adjustments(["SYM", "FAIL", "CLEAN"], fetch=fake, on_refreshed=spy)

    assert result["refreshed"] == ["SYM"]
    assert result["failed"] == ["FAIL"]
    assert seen == [("SYM", True)]


@pytest.mark.asyncio
async def test_refresh_adjustments_endpoint_evicts_refreshed_symbols_backtests(
        factory, monkeypatch, conf_cache, bt_cache):
    from app.routers.historical_data import router

    await _seed_batch_step(factory, monkeypatch, "AAPL")
    aapl = ["AAPL|pullback_ema|bullish|h1|b2|p|0.002000|None|None",
            "AAPL|breakout_base|bearish|h2|b2|p|0.002000|5|0.5"]
    others = ["AAPLX|pullback_ema|bullish|h1|b2|p|0.002000|None|None",
              "MSFT|pullback_ema|bullish|h1|b2|p|0.002000|None|None"]
    for k in aapl + others:
        bt_cache[k] = _bt_entry()

    async def fake(symbol, start, end):
        return [_bar(d, 100.0, adj=1.0) for d in DAYS]

    monkeypatch.setattr(hs, "_fetch_window", fake)
    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/historical-data/refresh-adjustments", json={"symbols": ["AAPL", "MSFT"]}
        )

    assert resp.status_code == 200
    assert resp.json()["refreshed"] == ["AAPL"]
    assert not [k for k in bt_cache if k.startswith("AAPL|")]
    assert sorted(bt_cache) == sorted(others)


def test_invalidated_since(conf_cache):
    cc = conf_cache
    g = cc.generation()
    cc.invalidate_symbol("AAPL")

    assert cc.invalidated_since("AAPL", g) is True
    assert cc.invalidated_since("aapl", g) is True
    assert cc.invalidated_since("MSFT", g) is False
    assert cc.invalidated_since("AAPL", cc.generation()) is False

    cc.clear_cache()

    assert cc.invalidated_since("AAPL", g) is True
    assert cc.invalidated_since("MSFT", g) is True


# The interleaving (plan round 1, HYG-P1-F2): a request read the bars, then awaits its
# backtest; a refresh invalidates + evicts the symbol while the backtest runs. The
# result must not be stored afterwards. _BACKTEST_POOL is a ProcessPoolExecutor and a
# stub in a child process cannot touch this process's caches, so the pool is replaced
# by the loop's default thread executor (None) and the stubbed backtest runs the
# refresh's two steps itself, in this process, before it returns.

def _in_flight_backtest(monkeypatch, cc, refresh_symbol: str | None, n_trades: int):
    import app.routers.stock_scan as ss
    from tests.test_confidence_gate_stocks import _make_fake_bt

    calls: list[str] = []

    def fake_backtest(bars, **kw):
        calls.append(kw["strategy"])
        if refresh_symbol is not None:
            cc.invalidate_symbol(refresh_symbol)        # refresh_adjustments, then
            ss.evict_backtest_cache([refresh_symbol])   # the endpoint's on_refreshed
        bt = _make_fake_bt()
        bt.n_trades = n_trades
        return bt

    monkeypatch.setattr(ss, "_BACKTEST_POOL", None)
    monkeypatch.setattr(ss, "run_strategy_backtest", fake_backtest)
    return calls


async def _scan_path_with_backtest(monkeypatch, symbol: str):
    """_process_stock (its _BACKTEST_CACHE store); returns the n_trades it reports."""
    from unittest.mock import AsyncMock, MagicMock

    import app.routers.stock_scan as ss
    from app.schemas.stock_scan import StockScanRequest
    from tests.test_confidence_gate_stocks import (
        _make_fake_bars, _make_fake_card, _make_fake_signal,
    )

    fake_bars = _make_fake_bars()

    async def bars_read(sym, start, end):
        return fake_bars

    monkeypatch.setattr(ss, "get_historical_bars", bars_read)
    monkeypatch.setattr(ss, "fetch_company_name_async", AsyncMock(return_value="Co"))
    monkeypatch.setattr(ss, "fetch_price_async", AsyncMock(return_value=152.0))
    monkeypatch.setattr(ss, "score_stock", MagicMock(return_value=_make_fake_card()))
    monkeypatch.setattr(ss, "compute_omm", MagicMock(return_value=None))
    monkeypatch.setattr(ss, "_get_fundamentals", AsyncMock(return_value=None))
    monkeypatch.setattr(ss, "_SIGNAL_FNS", {"pullback_ema": lambda *a, **kw: _make_fake_signal()})
    monkeypatch.setattr(ss, "compute_confidence", _conf_stub([]))
    req = StockScanRequest(universe=[symbol], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema")
    out = await ss._process_stock(symbol, req, "scan-t6", {}, [])
    assert not isinstance(out, dict), out
    return out.backtest.n_trades


async def _analysis_path_with_backtest(monkeypatch, symbol: str):
    """_analyze_core (its _BACKTEST_CACHE store); returns the n_trades it uses."""
    from unittest.mock import MagicMock

    import app.routers.stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest
    from tests.test_a5_analysis_mirrors_scan import _offline

    _offline(monkeypatch, conviction=10)
    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy="pullback_ema")
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", MagicMock(return_value=sig))
    monkeypatch.setattr(ss, "compute_confidence", _conf_stub([]))
    core = await ss._analyze_core(symbol, StockAnalysisRequest(symbol=symbol))
    return core.bt_result.n_trades


@pytest.mark.asyncio
@pytest.mark.parametrize("drive", [_scan_path_with_backtest, _analysis_path_with_backtest],
                         ids=["process_stock", "analyze_core"])
async def test_backtest_in_flight_across_a_refresh_is_used_but_not_stored(
        drive, monkeypatch, conf_cache, bt_cache):
    cc = conf_cache

    # The refresh lands while AAPL's backtest is in flight.
    calls = _in_flight_backtest(monkeypatch, cc, refresh_symbol="AAPL", n_trades=17)
    assert await drive(monkeypatch, "AAPL") == 17     # this request still uses it
    assert calls == ["pullback_ema"]
    assert not [k for k in bt_cache if k.startswith("AAPL|")]

    # Control: no refresh, the computed backtest is cached as before.
    calls = _in_flight_backtest(monkeypatch, cc, refresh_symbol=None, n_trades=11)
    assert await drive(monkeypatch, "MSFT") == 11
    assert calls == ["pullback_ema"]
    assert len([k for k in bt_cache if k.startswith("MSFT|")]) == 1
