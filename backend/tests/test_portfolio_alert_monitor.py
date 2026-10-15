# backend/tests/test_portfolio_alert_monitor.py
from __future__ import annotations

import app.services.portfolio_alert_monitor as monitor


def test_check_interval_seconds_uses_configured_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 90})
    assert monitor._check_interval_seconds() == 90


def test_check_interval_seconds_falls_back_to_default_when_missing(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL


def test_check_interval_seconds_enforces_floor_of_15(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 1})
    assert monitor._check_interval_seconds() == 15


def test_check_interval_seconds_handles_garbage_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 'oops'})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL


# ── T8: the alert the monitor dispatches, against a quote that is not entry ─
#
# generate_alerts is the comparison _run_once passes the live quote into.
# Entry is 100 throughout. The bullish quote is 120 and the bearish quote is
# 80, so a stop above the bullish entry is not, by itself, a breach. Equality
# with the quote fires (`price <= stop` bullish, `price >= stop` bearish).
# A missing quote fires nothing. Zero is not a stored value on the create or
# PATCH path (those floor it to NULL); NULL does not fire.

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers portfolio and alert-history tables)
from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.services.alert_generator import generate_alerts


@pytest_asyncio.fixture
async def Session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


# rec_id, direction, entry, stop, structural, quote or None, alert types
_STOP_QUOTES = [
    ("B-TRAIL", "Bullish", 100.0, 110.0, None, 120.0, set()),
    ("B-EQUAL", "Bullish", 100.0, 120.0, None, 120.0, {"STOP_REACHED"}),
    ("B-ABOVE", "Bullish", 100.0, 130.0, None, 120.0, {"STOP_REACHED"}),
    ("B-BELOW", "Bullish", 100.0, 90.0, None, 120.0, set()),
    ("B-NONE", "Bullish", 100.0, None, None, 120.0, set()),
    ("B-NOQUOTE", "Bullish", 100.0, 130.0, None, None, set()),
    ("B-STRUCT", "Bullish", 100.0, 110.0, 130.0, 120.0, {"STRUCTURAL_STOP_BREACHED"}),
    ("B-BOTH", "Bullish", 100.0, 130.0, 125.0, 120.0, {"STOP_REACHED", "STRUCTURAL_STOP_BREACHED"}),
    ("R-TRAIL", "Bearish", 100.0, 90.0, None, 80.0, set()),
    ("R-EQUAL", "Bearish", 100.0, 80.0, None, 80.0, {"STOP_REACHED"}),
    ("R-BELOW", "Bearish", 100.0, 70.0, None, 80.0, {"STOP_REACHED"}),
    ("R-ABOVE", "Bearish", 100.0, 110.0, None, 80.0, set()),
    ("R-STRUCT", "Bearish", 100.0, 110.0, 70.0, 80.0, {"STRUCTURAL_STOP_BREACHED"}),
    ("R-NONE", "Bearish", 100.0, None, None, 80.0, set()),
]


@pytest.mark.asyncio
async def test_stop_alerts_follow_the_quote_not_the_stored_entry(Session):
    prices = {}
    async with Session() as db:
        for rec, direction, entry, stop, structural, quote, _expect in _STOP_QUOTES:
            db.add(PortfolioPositionModel(
                rec_id=rec,
                symbol=rec,
                contract=f"{rec}|STOCK",
                direction=direction,
                entry_price=entry,
                qty=1,
                entry_date="2026-05-01",
                stop=stop,
                structural_stop=structural,
                targets=[],
            ))
            if quote is not None:
                prices[rec] = quote
        await db.commit()
        alerts = await generate_alerts(db, prices)

    fired: dict[str, set[str]] = {}
    for alert in alerts:
        fired.setdefault(alert.recId, set()).add(alert.alertType)
    for rec, _direction, _entry, _stop, _structural, _quote, expect in _STOP_QUOTES:
        assert fired.get(rec, set()) == expect, rec

    equal = next(a for a in alerts if a.recId == "B-EQUAL")
    assert equal.referenceValue == 120.0
    assert equal.price == 120.0
    assert "below" in equal.reason
    bear_equal = next(a for a in alerts if a.recId == "R-EQUAL")
    assert bear_equal.referenceValue == 80.0
    assert "above" in bear_equal.reason and "below" not in bear_equal.reason
