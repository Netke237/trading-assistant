"""
conftest.py — pytest fixtures for the Trading Assistant backend.

Fixes:
1. Creates the scan_sessions DB table in an in-memory SQLite test DB,
   and overrides get_db so scan.py can write/read without a real Postgres.
2. Builds a test-specific FastAPI app where the stub routes (watchlist,
   portfolio, alerts, events, tradecards, regime, sectors) return fixture
   data directly, so test_routes.py assertions pass without a live API.
3. Mocks Tradier-calling functions in the contracts and candles routers.
"""
from __future__ import annotations

# ── Test DB safety pin (MUST run before any app import) ───────────────────────
# Several tests import the real app.main:app without overriding get_db, so they
# use the module-level engine built from DATABASE_URL (app/database.py builds it
# once at import time). Pin that to an isolated file during tests so the suite
# can NEVER connect to or mutate a real database.
#
# This used to pin to "sqlite+aiosqlite:///./dev.db" — but that is *also*
# app/config.py's own hardcoded fallback default, and the real backend
# (start-backend.bat runs `uvicorn app.main:app` from backend/ with no .env and
# no DATABASE_URL set) resolves to that exact same relative path when Postgres
# isn't configured. Since `cd backend && pytest` runs from the same directory,
# the two pointed at the identical file. Any code path that reads/writes via the
# raw module-level AsyncSessionLocal instead of the request-scoped, overridable
# get_db dependency (restore_stock_from_db/restore_from_db on startup,
# historical_store.py, fundamentals_store.py, ingestion_job.py,
# portfolio_alert_monitor.py, regime_monitor.py, two spots in scan.py) would
# read or write real local trading data during a test run — confirmed to have
# actually happened, see the (now-removed) xfail on
# test_portfolio_monitor.py::test_master_disabled_skips_all, which reproducibly
# saw a real leftover position (symbol KDP) instead of test data.
#
# Fixed by pinning to a fresh, uniquely-named temp file every test session —
# structurally unable to collide with the real default regardless of whether
# the real backend is on Postgres or the SQLite fallback. An env var takes
# precedence over .env in pydantic-settings; setdefault lets an explicit test
# DATABASE_URL still win if someone sets one.
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEST_DB_DIR = tempfile.mkdtemp(prefix="bamendjou-pytest-db-")
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)
# Path(...).as_posix() normalizes to forward slashes — mkdtemp() returns
# backslash-separated paths on Windows (the real user's dev OS, per
# start-backend.bat), and a bare f-string would mix those with the URL's own
# hardcoded "/", producing a fragile sqlite URL SQLAlchemy doesn't document
# supporting on Windows.
_TEST_DB_PATH = Path(_TEST_DB_DIR, "test.db").as_posix()
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

# ── Credential-store safety pin (MUST run before any app import) ──────────────
# The same class of bug as the DB pin above, and it bites harder.
# credential_store.py builds a module-level singleton at import time whose path
# defaults to the REAL backend/config/local_credentials.yaml, and save() writes
# to it — so any test reaching a code path that calls credential_store.save()
# (broker_router's build_router_from_credentials(), the credentials POST
# endpoint) would overwrite the developer's actual broker tokens.
#
# test_credential_store.py sets this variable for the same reason, but that only
# helps if that module happens to be imported before anything else pulls in
# credential_store — and pytest's collection order decides that, not the test.
# Pinning here removes the ordering dependency entirely, because conftest is
# imported before any test module. Points at a throwaway file rather than ""
# so load()/save() still exercise real persistence, just never against real
# credentials. setdefault lets an explicit override still win.
_TEST_CREDS_PATH = Path(_TEST_DB_DIR, "test_local_credentials.yaml").as_posix()
os.environ.setdefault("BAMENDJOU_CREDS_PATH", _TEST_CREDS_PATH)

# ── scan_schedule_store safety pin (MUST run before any app import) ───────────
# Same class of bug as the two pins above: scan_schedule_store.py (Part 3 of
# the scheduler-timezone-awareness plan) builds a module-level singleton at
# import time whose path defaults to the real backend/config/scan_schedule.yaml,
# and its router (routers/scan_schedule.py) calls upsert()/delete() on that
# singleton directly — any test exercising those endpoints via the `client`
# fixture (not just a test that builds its own ScanScheduleStore(path=tmp_path))
# would otherwise write real schedule entries into the repo's actual config
# directory. Confirmed to actually happen during this change's own test
# development. Pinned to a throwaway file for the same reason as the
# credentials pin — setdefault lets an explicit override still win.
_TEST_SCAN_SCHEDULE_PATH = Path(_TEST_DB_DIR, "test_scan_schedule.yaml").as_posix()
os.environ.setdefault("BAMENDJOU_SCAN_SCHEDULE_PATH", _TEST_SCAN_SCHEDULE_PATH)

import asyncio
from typing import AsyncGenerator
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_db
from app.models.scan_session import ScanSessionBase
from app.models.scheduled_scan_run import ScheduledScanRunBase

# ── Strategy-param cache isolation ────────────────────────────────────────────

_KNOWN_STRATEGY_PARAMS_YAML = """\
direction: bullish
windows:
  type: rolling
  train_months: 12
  test_months: 3
costs:
  fee_pct: 0.001
  slippage_pct: 0.001
optimization:
  min_trades: 20
  min_consistency: 0.5
job_retention:
  max_completed: 100
strategies:
  pullback_ema:
    active:
      ema_period: 50
      trend_ema: 100
      atr_stop_mult: 1.5
      rr_target_mult: 2.0
      tolerance: 0.08
    search:
      ema_period: [20, 50]
      trend_ema: [100, 150, 200]
      atr_stop_mult: [1.0, 1.5, 2.0]
      rr_target_mult: [1.5, 2.0, 2.5, 3.0]
      tolerance: [0.05, 0.08, 0.10]
  breakout_base:
    active:
      base_lookback: 20
      atr_tight_max: 1.5
    search:
      base_lookback: [15, 20, 30]
  ma_crossover:
    active:
      fast: 20
      slow: 50
  mean_reversion_rsi:
    active:
      rsi_period: 14
      rsi_oversold: 30
"""


@pytest.fixture
def strategy_cfg(tmp_path, monkeypatch):
    """Pin strategy_params.yaml to a known-good fixture so tests don't depend on production config.

    Use this for any test that asserts specific active-param or search-space values —
    without it, a developer who has run adopt() will see different values in the YAML
    and the test will fail.
    """
    import app.services.strategy_param_store as store
    cfg_path = tmp_path / "strategy_params.yaml"
    cfg_path.write_text(_KNOWN_STRATEGY_PARAMS_YAML, encoding="utf-8")
    monkeypatch.setattr(store, "CFG", cfg_path)


@pytest.fixture(autouse=True)
def _reset_strategy_param_cache():
    """Clear the module-level YAML cache before and after every test.

    Without this, a test that calls _load() or adopt() warms the cache, and the
    next test (which may monkeypatch CFG to a different path) still reads stale
    data from the previous test's cache entry.
    """
    from app.services import strategy_param_store as sps
    sps._CACHE = None
    yield
    sps._CACHE = None


@pytest.fixture(autouse=True)
def _reset_market_data_caches():
    """Clear market.py's module-level day-scoped caches before and after every
    test.

    Without this, a test that calls fetch_candles_async / fetch_company_name_async
    / fetch_fundamentals_calendar / fetch_option_chain_async with a real symbol
    (most commonly "AAPL", reused across dozens of tests) warms one of these
    caches as a side effect. The next test to use the same symbol then gets a
    cache hit instead of hitting its own mocked HTTP response, silently
    consuming a mocked side_effect list out of order or skipping an assertion's
    expected call entirely. Caught directly: test_fetch_option_chain_async_falls_back_to_tastytrade_when_ibkr_unavailable
    passed in isolation but failed when run after other AAPL-using tests, once
    _expirations_cache/_fundamentals_calendar_cache were added.
    """
    from app.data import market as mkt
    mkt._candles_cache.clear()
    mkt._company_cache.clear()
    mkt._fundamentals_calendar_cache.clear()
    mkt._expirations_cache.clear()
    yield
    mkt._candles_cache.clear()
    mkt._company_cache.clear()
    mkt._fundamentals_calendar_cache.clear()
    mkt._expirations_cache.clear()


@pytest.fixture(autouse=True)
def _default_fast_heston_calibration():
    """calibrate_heston became a real, callable name in app.routers.scan once
    the scan pipeline started calibrating it. Default it to an instant canned
    result for every test so pre-existing tests with 3+-contract mock chains
    (test_alternatives.py, test_scan_router_spreads.py, test_shortlist.py)
    don't silently start doing real scipy numerical integration. Tests that
    specifically exercise the calibration wiring (test_scan_endpoint.py's
    Heston tests) override this locally with their own patch(...) inside a
    `with` block, which correctly takes precedence for its duration and
    reverts to this default afterward."""
    from app.models.heston import HestonParams, CalibrationResult
    fake = CalibrationResult(
        params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
        rmse=0.01, method="heston_grid",
    )
    with patch("app.routers.scan.calibrate_heston", return_value=fake):
        yield


# ── Test DB ───────────────────────────────────────────────────────────────────

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
)
_TestSession = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def _create_tables() -> None:
    async with _test_engine.begin() as conn:
        await conn.run_sync(ScanSessionBase.metadata.create_all)
        await conn.run_sync(ScheduledScanRunBase.metadata.create_all)


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="session", autouse=True)
def _db_tables():
    """Create scan_sessions table once per test session (against the separate
    in-memory `_test_engine` used only by the `client` fixture below)."""
    asyncio.run(_create_tables())
    yield


# ── App DB tables (for tests that import app.main:app directly) ───────────────
# The `client` fixture below is fully self-isolated (its own in-memory engine,
# get_db overridden locally) and doesn't need any of this. But several test
# files do `from app.main import app` and hit the real `get_db` — i.e. the
# real `app.database.engine`, now pointed at the isolated file DB pinned above
# instead of dev.db. Those tables need to actually exist in that file.
#
# This codebase has FIVE independent SQLAlchemy declarative-base/metadata
# registries, not one:
#   1. app.models.base.Base       — dead code, nothing registers against it.
#      Deliberately NOT used below — it's the obvious-looking name to import,
#      but create_all() against it silently creates zero tables.
#   2. app.database.Base          — the real one; every actual model
#      (PortfolioPositionModel, AlertRuleModel, ClosedPositionModel, etc.)
#      inherits from this.
#   3. ScanSessionBase            — ScanSessionModel only.
#   4. OhlcvBase                  — OhlcvDailyModel only.
#   5. ScheduledScanRunBase       — ScheduledScanRunModel only (Part 3).
# (backend/migrations/env.py's target_metadata list is the reference for this
# — it already has to name all five separately, because they don't merge.)
async def _create_app_db_tables() -> None:
    # Import app.main so every router — and therefore every model module — is
    # loaded and registered against its Base before create_all runs. In
    # practice this is already true by the time this fixture executes (pytest
    # collection imports every test module, many of which import app.main,
    # before any fixture runs) — importing it explicitly here too is a cheap,
    # self-contained belt-and-suspenders measure that doesn't rely on that
    # import-order side effect.
    import app.main  # noqa: F401
    from app.database import engine, Base as AppBase
    from app.models.scan_session import ScanSessionBase
    from app.models.ohlcv_daily import OhlcvBase
    from app.models.scheduled_scan_run import ScheduledScanRunBase
    async with engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
        await conn.run_sync(ScanSessionBase.metadata.create_all)
        await conn.run_sync(OhlcvBase.metadata.create_all)
        await conn.run_sync(ScheduledScanRunBase.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def _app_db_tables():
    """Create every real table against the isolated test DB file once per
    session, so any test importing app.main:app directly gets working tables
    instead of "no such table" errors — or, before this fixture existed,
    instead of silently reading/writing the real local dev.db."""
    asyncio.run(_create_app_db_tables())
    yield


# ── Main client fixture ───────────────────────────────────────────────────────

@pytest.fixture
def client():
    """
    Synchronous TestClient backed by a test-specific FastAPI app that:
    - Overrides all empty-stub routes with fixture data.
    - Keeps the scan, candles, and contracts routers intact (with Tradier mocked).
    - Uses an in-memory SQLite DB via the get_db override.
    """
    # ── Import fixtures ───────────────────────────────────────────────────────
    from app.fixtures.watchlist  import MOCK_WATCHLIST
    from app.fixtures.portfolio  import MOCK_PORTFOLIO
    from app.fixtures.alerts     import MOCK_ALERTS
    from app.fixtures.events     import MOCK_EVENTS
    from app.fixtures.tradecards import MOCK_CANDIDATE_CARDS
    from app.fixtures.regime     import MOCK_REGIME
    from app.fixtures.sectors    import MOCK_SECTORS
    from app.fixtures.contracts  import MOCK_CONTRACTS
    from app.fixtures.candles    import candles_for
    from app.schemas import (
        WatchlistRow, PortfolioPosition, AlertItem, UpcomingEvent,
        TradeCardData, MarketRegime, SectorTile, OptionContract, Candle,
    )

    # ── Routers that stay "real" (we mock their data sources separately) ──────
    from app.routers.health    import router as health_router
    from app.routers.contracts import router as contracts_router
    from app.routers.candles   import router as candles_router
    from app.routers.scan      import router as scan_router
    from app.routers.news      import router as news_router
    from app.routers.ws_alerts import router as ws_alerts_router
    from app.routers.notification_settings import router as notification_settings_router
    from app.routers.scan_schedule import router as scan_schedule_router

    # ── Build test app ────────────────────────────────────────────────────────
    test_app = FastAPI(title="Test App", debug=True)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Stub router: fixture-backed replacements for routes that return []
    stub = APIRouter(prefix='/api', tags=['test-stubs'])

    @stub.get('/watchlist', response_model=list[WatchlistRow])
    async def _watchlist():
        return MOCK_WATCHLIST

    @stub.get('/portfolio', response_model=list[PortfolioPosition])
    async def _portfolio():
        return MOCK_PORTFOLIO

    @stub.get('/alerts', response_model=list[AlertItem])
    async def _alerts():
        return MOCK_ALERTS

    @stub.get('/events', response_model=list[UpcomingEvent])
    async def _events():
        return MOCK_EVENTS

    @stub.get('/tradecards', response_model=list[TradeCardData])
    async def _tradecards():
        return MOCK_CANDIDATE_CARDS

    @stub.get('/regime', response_model=MarketRegime)
    async def _regime():
        return MOCK_REGIME

    @stub.get('/sectors', response_model=list[SectorTile])
    async def _sectors():
        return MOCK_SECTORS

    test_app.include_router(stub)          # stubs FIRST — FastAPI matches first registered
    test_app.include_router(health_router)
    test_app.include_router(contracts_router)
    test_app.include_router(candles_router)
    test_app.include_router(scan_router)
    test_app.include_router(news_router)
    test_app.include_router(ws_alerts_router)
    test_app.include_router(notification_settings_router)
    test_app.include_router(scan_schedule_router)

    # Override get_db with the in-memory SQLite session
    test_app.dependency_overrides[get_db] = _override_get_db

    # Mock Tradier API calls used by the "real" routers
    _contract_dicts = [c.model_dump(by_alias=False) for c in MOCK_CONTRACTS]

    def _candles_for_symbol(symbol: str):
        return [c.model_dump(by_alias=False) for c in candles_for(symbol)]

    with (
        patch("app.routers.contracts.fetch_option_chain_async",
              new_callable=AsyncMock, return_value=_contract_dicts),
        patch("app.routers.contracts.fetch_price_async",
              new_callable=AsyncMock, return_value=190.0),
        patch("app.routers.candles.fetch_candles",
              side_effect=_candles_for_symbol),
    ):
        yield TestClient(test_app)
