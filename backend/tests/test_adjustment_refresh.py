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
async def test_refresh_fetches_flagged_only_and_upserts(factory, monkeypatch):
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
async def test_refresh_never_deletes_rows(factory, monkeypatch):
    await _seed_batch_step(factory, monkeypatch, "SYM")
    before = await _count(factory, "SYM")

    async def fake(symbol, start, end):
        return [_bar(d, 100.0, adj=1.0) for d in DAYS[-2:]]

    monkeypatch.setattr(hs, "_utcnow", lambda: _evening(DAYS[9]) + timedelta(days=2))
    await hs.refresh_adjustments(["SYM"], fetch=fake)
    assert await _count(factory, "SYM") == before == len(DAYS)


@pytest.mark.asyncio
async def test_refresh_adjustments_endpoint(factory, monkeypatch):
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
