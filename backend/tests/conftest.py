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
# The app now defaults to PostgreSQL for dev (backend/.env), and several tests
# import the real app.main:app without overriding get_db, so they use the
# module-level engine built from DATABASE_URL. Pin that to the local SQLite file
# during tests so the suite can NEVER connect to or mutate the real Postgres dev
# database. An env var takes precedence over .env in pydantic-settings; setdefault
# lets an explicit test DATABASE_URL still win if someone sets one.
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

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


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="session", autouse=True)
def _db_tables():
    """Create scan_sessions table once per test session."""
    asyncio.run(_create_tables())
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
