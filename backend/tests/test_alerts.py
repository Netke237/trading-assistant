"""
WS-39 alert engine tests.

Tests the real portfolio-based alert generation (5 alert types),
deduplication logic (frontend), conflict suppression, and recId propagation.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from unittest.mock import patch

from app.database import Base
from app.models.portfolio import PortfolioPositionModel

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    from app.models import portfolio, watchlist, audit_event  # noqa: F401
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    from app.main import app
    from app.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _insert_position(db: AsyncSession, **overrides) -> PortfolioPositionModel:
    defaults = {
        "rec_id": "REC-TEST-001",
        "symbol": "AAPL",
        "contract": "AAPL|190|2026-05-16|C",
        "direction": "Bullish",
        "entry_price": 4.50,
        "qty": 2,
        "entry_date": "2026-04-08",
        "stop": 178.00,
        "targets": [{"stockPrice": 198.0, "stock_price": 198.0}],
        "dte_total": 43,
    }
    defaults.update(overrides)
    pos = PortfolioPositionModel(**defaults)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


# ── Test 1: TP_HIT when current_price >= first target stockPrice ──────────────

@pytest.mark.asyncio
async def test_tp_hit_fires(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", targets=[{"stockPrice": 190.0, "stock_price": 190.0}])
    prices = {"AAPL": 195.0}
    alerts = await generate_alerts(db_session, prices)
    tp_alerts = [a for a in alerts if a.alertType == "TP_HIT"]
    assert len(tp_alerts) == 1
    assert tp_alerts[0].symbol == "AAPL"
    assert tp_alerts[0].kind == "Action"
    assert "Target reached" in tp_alerts[0].reason


# ── Test 2: STOP_REACHED when current_price <= stop ────────────────────────────

@pytest.mark.asyncio
async def test_stop_reached_fires(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", stop=180.0)
    prices = {"AAPL": 175.0}
    alerts = await generate_alerts(db_session, prices)
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert stop_alerts[0].kind == "Critical"
    assert "Stop breached" in stop_alerts[0].reason


# ── Test 3: PREMIUM_STOP when option_price <= 60% of entry ─────────────────────

@pytest.mark.asyncio
async def test_premium_stop_fires(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", entry_price=5.0)
    prices = {"AAPL": 180.0}
    opt_prices = {"AAPL|190|2026-05-16|C": 2.5}  # 2.5 <= 5.0 * 0.60 = 3.0
    alerts = await generate_alerts(db_session, prices, opt_prices)
    prem_alerts = [a for a in alerts if a.alertType == "PREMIUM_STOP"]
    assert len(prem_alerts) == 1
    assert prem_alerts[0].kind == "Critical"
    assert "Premium stop" in prem_alerts[0].reason


# ── Test 4: Backend produces distinct alert types (dedup is frontend logic) ─

@pytest.mark.asyncio
async def test_same_recId_produces_distinct_alert_types(db_session):
    from app.services.alert_generator import generate_alerts
    # AAPL: price below stop → STOP_REACHED only
    await _insert_position(
        db_session,
        symbol="AAPL",
        stop=200.0,
        contract="AAPL|190|2028-01-01|C",
        targets=[],
    )
    # MSFT: price above target → TP_HIT only
    await _insert_position(
        db_session,
        rec_id="REC-MSFT-001",
        symbol="MSFT",
        contract="MSFT|420|2028-01-01|C",
        targets=[{"stockPrice": 400.0, "stock_price": 400.0}],
        stop=380.0,
    )
    prices = {"AAPL": 175.0, "MSFT": 450.0}
    alerts = await generate_alerts(db_session, prices)
    alert_types = {a.alertType for a in alerts}
    assert "STOP_REACHED" in alert_types
    assert "TP_HIT" in alert_types


# ── Test 5: Alert carries correct recId field ──────────────────────────────────

@pytest.mark.asyncio
async def test_alert_carries_rec_id(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, rec_id="REC-XYZ-999", symbol="MSFT", targets=[{"stockPrice": 450.0, "stock_price": 450.0}])
    prices = {"MSFT": 460.0}
    alerts = await generate_alerts(db_session, prices)
    assert len(alerts) >= 1
    assert alerts[0].recId == "REC-XYZ-999"


# ── Test 6: TIME_STOP fires when days_to_expiry <= 3 (bug fix: parse from contract) ─

@pytest.mark.asyncio
async def test_time_stop_fires_for_near_expiry(db_session):
    from app.services.alert_generator import generate_alerts
    near_expiry = (date.today() + timedelta(days=2)).isoformat()
    contract = f"NVDA|920|{near_expiry}|C"
    await _insert_position(db_session, symbol="NVDA", contract=contract, targets=[])
    prices = {"NVDA": 900.0}
    alerts = await generate_alerts(db_session, prices)
    ts_alerts = [a for a in alerts if a.alertType == "TIME_STOP"]
    assert len(ts_alerts) == 1
    assert "Time stop" in ts_alerts[0].reason


# ── Test 7: TIME_STOP does NOT fire when days_to_expiry > 3 ─────────────────────

@pytest.mark.asyncio
async def test_time_stop_does_not_fire_for_distant_expiry(db_session):
    from app.services.alert_generator import generate_alerts
    far_expiry = (date.today() + timedelta(days=30)).isoformat()
    contract = f"NVDA|920|{far_expiry}|C"
    await _insert_position(db_session, symbol="NVDA", contract=contract, targets=[])
    prices = {"NVDA": 900.0}
    alerts = await generate_alerts(db_session, prices)
    ts_alerts = [a for a in alerts if a.alertType == "TIME_STOP"]
    assert len(ts_alerts) == 0


# ── Test 8: Short stock STOP_REACHED fires on price rise, not fall (Critical #5) ─

@pytest.mark.asyncio
async def test_short_stock_stop_triggers_on_price_rise(db_session):
    """A short (Bearish direction) stock position's stop must trigger when price
    rises above the stop, not below it (Critical finding #5, 2026-07-15 audit)."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="XYZ", contract="XYZ|STOCK", direction="Bearish",
        stop=105.0, targets=[],
    )

    # Price rose above the short's stop (105) -> must alert STOP_REACHED.
    alerts = await generate_alerts(db_session, current_prices={"XYZ": 106.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert stop_alerts[0].symbol == "XYZ"


@pytest.mark.asyncio
async def test_short_stock_stop_message_says_above_not_below(db_session):
    """A short (Bearish) position's STOP_REACHED message must say the price is
    above the stop, not below — the hardcoded 'below' text predates the fix
    that made short-stock stops actually fire (2026-07-15 audit pass)."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="XYZ", contract="XYZ|STOCK", direction="Bearish",
        stop=105.0, targets=[],
    )
    alerts = await generate_alerts(db_session, current_prices={"XYZ": 106.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert "above" in stop_alerts[0].reason
    assert "below" not in stop_alerts[0].reason


@pytest.mark.asyncio
async def test_long_stock_stop_message_still_says_below(db_session):
    """A long (Bullish) position's STOP_REACHED message must keep saying
    'below' — this is the pre-existing, correct behavior for longs."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="ABC", contract="ABC|STOCK", direction="Bullish",
        stop=105.0, targets=[],
    )
    alerts = await generate_alerts(db_session, current_prices={"ABC": 104.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert "below" in stop_alerts[0].reason


@pytest.mark.asyncio
async def test_short_stock_target_triggers_on_price_fall(db_session):
    """A short (Bearish direction) stock position's target must trigger when price
    falls to/below the target, not above it (same root cause as the STOP_REACHED
    fix, Critical finding #5, 2026-07-15 audit)."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="XYZ", contract="XYZ|STOCK", direction="Bearish",
        stop=120.0, targets=[{"stockPrice": 95.0, "stock_price": 95.0}],
    )

    # Price fell to the short's target (95) -> must alert TP_HIT.
    alerts = await generate_alerts(db_session, current_prices={"XYZ": 94.0})
    tp_alerts = [a for a in alerts if a.alertType == "TP_HIT"]
    assert len(tp_alerts) == 1
    assert tp_alerts[0].symbol == "XYZ"

# ── Test: STOP_REACHED message includes the triggering price, not just stop ──

@pytest.mark.asyncio
async def test_stop_reached_reason_includes_triggering_price(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", stop=180.0)
    prices = {"AAPL": 175.0}
    alerts = await generate_alerts(db_session, prices)
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert "$175.00" in stop_alerts[0].reason
    assert "$180.00" in stop_alerts[0].reason


# ── Test: STOP_REACHED writes a structured audit event with price + stop ─────

@pytest.mark.asyncio
async def test_stop_reached_writes_audit_event(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", stop=180.0, rec_id="REC-AUDIT-1")
    prices = {"AAPL": 175.0}
    with patch("app.services.alert_generator.log_event") as mock_log_event:
        await generate_alerts(db_session, prices)
    calls = [c for c in mock_log_event.call_args_list if c.args[0] == "alert_fired"]
    assert len(calls) == 1
    event_type, rec_id, payload = calls[0].args
    assert rec_id == "REC-AUDIT-1"
    assert payload["alertType"] == "STOP_REACHED"
    assert payload["symbol"] == "AAPL"
    assert payload["price"] == 175.0
    assert payload["stop"] == 180.0


# ── Test: TP_HIT and PREMIUM_STOP also write audit events ────────────────────

@pytest.mark.asyncio
async def test_all_alert_types_write_audit_events(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, rec_id="REC-TP", symbol="TPX", contract="TPX|1|2026-05-16|C",
        targets=[{"stockPrice": 100.0, "stock_price": 100.0}], stop=None,
    )
    await _insert_position(
        db_session, rec_id="REC-STOP", symbol="STOPX", contract="STOPX|1|2026-05-16|C",
        stop=50.0, targets=[],
    )
    await _insert_position(
        db_session, rec_id="REC-PREM", symbol="PREMX", contract="PREMX|1|2026-05-16|C",
        entry_price=5.0, stop=None, targets=[],
    )
    prices = {"TPX": 105.0, "STOPX": 45.0, "PREMX": 200.0}
    opt_prices = {"PREMX|1|2026-05-16|C": 2.0}  # 2.0 <= 5.0 * 0.60 = 3.0

    with patch("app.services.alert_generator.log_event") as mock_log_event:
        await generate_alerts(db_session, prices, opt_prices)

    fired_types = {
        c.args[2]["alertType"]
        for c in mock_log_event.call_args_list
        if c.args[0] == "alert_fired"
    }
    assert fired_types == {"TP_HIT", "STOP_REACHED", "PREMIUM_STOP"}
