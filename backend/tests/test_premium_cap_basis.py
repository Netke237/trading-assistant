"""Audit round 1, F1: the D5 premium cap is judged at the price the order can
actually fill at, not the mid.

LMT  -> max(mid, limit)
MKT  -> the ask when known, else mid + half the spread when the spread is
        known, else the mid
none -> the mid (no order is placed: a tracked basket row)

The auditor's example: account 100k, live mid $3.00, limit typed at $3.60,
12 contracts. Judged at the mid that is $3,600 (3.6%, under the 3.75% cap);
judged at the limit it is $4,320 (4.32%), over it.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.auto_trade import ArmRequest
from app.routers.portfolio import router as portfolio_router
from app.services import portfolio_risk as pr
from app.services.auto_trader import ArmedStrategy, AutoTradeService

CONTRACT = "AAPL|185|2026-12-18|C"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    cfg = {
        "portfolio": {"max_total_exposure_pct": 0.25, "max_concurrent_positions": 10,
                      "max_daily_recommendations": 5, "max_same_symbol_positions": 1,
                      "min_portfolio_value": 5000.0, "max_single_position_pct": 0.05,
                      "max_loss_per_trade_pct": 0.0375},
        # 50, not the shipped 5: this file tests the premium cap, not the
        # contract cap, and 12 contracts must reach the premium cap.
        "sizing": {"max_contracts_per_trade": 50},
    }
    monkeypatch.setattr(pr, "_load_config", lambda: cfg)


# ── The pure basis ──────────────────────────────────────────────────────────

def test_limit_above_mid_is_judged_at_the_limit():
    assert pr.premium_cap_basis(3.00, "LMT", 3.60) == pytest.approx(3.60)


def test_limit_below_mid_is_judged_at_the_mid():
    assert pr.premium_cap_basis(3.00, "LMT", 2.80) == pytest.approx(3.00)


def test_market_uses_the_ask_when_known():
    assert pr.premium_cap_basis(3.00, "MKT", None, ask=3.25, spread=0.40) == pytest.approx(3.25)


def test_market_without_ask_uses_mid_plus_half_spread():
    assert pr.premium_cap_basis(3.00, "MKT", None, spread=0.40) == pytest.approx(3.20)


def test_market_without_ask_or_spread_falls_back_to_mid():
    assert pr.premium_cap_basis(3.00, "MKT", None) == pytest.approx(3.00)


def test_no_order_is_judged_at_the_mid():
    assert pr.premium_cap_basis(3.00, None, 3.60) == pytest.approx(3.00)


def test_auditor_example_at_the_basis_is_not_approved_at_twelve():
    basis = pr.premium_cap_basis(3.00, "LMT", 3.60)
    r = pr.check_position_risk("AAPL", CONTRACT, 12, basis, basis, [], 100_000)
    assert "size_reduced_to_fit_exposure_limit" in r.reasons
    assert r.adjusted_size == 10          # 10 x 360 = 3,600 <= 3,750


# ── The auto-trade fire check ───────────────────────────────────────────────

def _strategy(**over) -> ArmedStrategy:
    body = {
        "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": CONTRACT,
        "action": "BUY", "direction": "Bullish", "horizon": "Swing", "hold_max_days": 15,
        "quantity": 12, "order_type": "LMT", "limit_price": 3.60, "entry_premium": 3.00,
        "stop": 180.0, "conid": None,
    }
    body.update(over)
    return ArmedStrategy(**ArmRequest(**body).model_dump())


def test_fire_check_refuses_the_auditor_example():
    with pytest.raises(RuntimeError) as exc:
        AutoTradeService._check_exposure(_strategy(), [], 100_000.0)
    assert "re-arm with 10" in str(exc.value)


def test_fire_check_passes_when_the_limit_is_at_the_mid():
    AutoTradeService._check_exposure(_strategy(limit_price=3.00), [], 100_000.0)


# ── The direct send: POST /api/portfolio ────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


def _body(**over) -> dict:
    body = {"recId": "REC-F1", "symbol": "AAPL", "contract": CONTRACT,
            "direction": "Bullish", "entryPrice": 3.00, "qty": 12, "entryDate": "2026-10-03",
            "stop": 170.0, "targets": [], "dteTotal": 70, "portfolioValue": 100_000}
    body.update(over)
    return body


_QUOTE = {"price": 3.00, "spread": 0.40, "delta": 0.5, "theta": -0.05, "ivRank": None}


async def _post(client, body):
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=dict(_QUOTE))):
        return await client.post("/api/portfolio", json=body)


@pytest.mark.asyncio
async def test_direct_limit_send_is_resized_at_the_limit(client):
    r = await _post(client, _body(orderType="LMT", orderLimitPrice=3.60))
    assert r.status_code == 201, r.text
    assert r.json()["adjustedQty"] == 10
    # The STORED entry is still the live mid: the basis judges the cap only.
    assert r.json()["entryPrice"] == pytest.approx(3.00)


@pytest.mark.asyncio
async def test_direct_market_send_is_judged_at_mid_plus_half_spread(client):
    # 12 x 320 = 3,840 > 3,750 -> 11 x 320 = 3,520
    r = await _post(client, _body(orderType="MKT"))
    assert r.status_code == 201, r.text
    assert r.json()["adjustedQty"] == 11


@pytest.mark.asyncio
async def test_no_order_fields_keep_the_mid_basis(client):
    # A tracked basket row places no order: judged at the mid, 3,600 fits.
    r = await _post(client, _body())
    assert r.status_code == 201, r.text
    assert r.json().get("adjustedQty") is None


@pytest.mark.asyncio
async def test_one_contract_over_the_cap_at_the_limit_is_refused(client):
    # mid 30 fits one contract (3,000); a limit of 40 does not (4,000 > 3,750).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={**_QUOTE, "price": 30.0})):
        r = await client.post("/api/portfolio",
                              json=_body(qty=1, entryPrice=30.0, orderType="LMT", orderLimitPrice=40.0))
    assert r.status_code == 422, r.text
    assert "single_trade_exposure_too_high" in r.text


# ── The auto-trade booking (gates off) reports over-exposure on the same basis ─

def test_booking_body_carries_the_armed_order():
    from app.services import auto_trade_booking
    from app.services.auto_trader import FiredOrder
    body = auto_trade_booking._build_body(
        FiredOrder(result=None, strategy=_strategy(), attempt_id="A1"), "REC-AT-1",
    )
    assert body.orderType == "LMT"
    assert body.orderLimitPrice == pytest.approx(3.60)


def test_r5f1_a_market_arm_books_no_limit_price():
    """Audit round 5, R5-F1: a MKT order carries no limit at the broker (every
    adapter drops it), so the booking must not record one -- a stray limit on a
    MKT arm (e.g. a non-finite one) would otherwise fail the position's schema
    AFTER the order was placed, leaving a live order with no Portfolio row."""
    from app.services import auto_trade_booking
    from app.services.auto_trader import FiredOrder
    body = auto_trade_booking._build_body(
        FiredOrder(result=None, strategy=_strategy(order_type="MKT", limit_price=3.60),
                   attempt_id="A1"), "REC-AT-1",
    )
    assert body.orderType == "MKT"
    assert body.orderLimitPrice is None


# ── Audit round 2, R2-F6: the fire and the booking judge an arm at ONE basis ──
#
# The fire judged a MKT arm at the armed mid (an arm carries no spread); the
# gates-off booking re-judged it at the BOOKING-time live mid + spread/2, so it
# could flag `over_exposure` -- and page -- on an order the fire had approved.
# Both now call `auto_trader.armed_cap_basis(strategy)`: the same function on
# the same armed inputs. That still holds for an LMT arm (a fill cannot exceed
# the limit). Audit round 3, R3-F1, narrowed it for a MKT arm: its booking is
# judged at max(armed basis, booking-time fill basis) -- see the R3-F1 section.

def test_the_fire_and_the_booking_share_one_basis_function():
    from app.services.auto_trader import armed_cap_basis
    s = _strategy(order_type="MKT", limit_price=None)
    assert armed_cap_basis(s) == pr.premium_cap_basis(3.00, "MKT", None)
    assert armed_cap_basis(_strategy()) == pytest.approx(3.60)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _book(session, mocker, strategy, quote):
    from app.data.ibkr_paper import OrderResult
    from app.services import auto_trade_booking as atb
    from app.services.auto_trader import FiredOrder
    mocker.patch.object(atb, "fetch_contract_quote_async", AsyncMock(return_value=quote))
    mocker.patch.object(atb, "fetch_price_async", AsyncMock(return_value=None))
    mocker.patch("app.services.notifications.alert_notifier.notify_alert",
                 AsyncMock(return_value=True))
    mocker.patch("app.services.notifications.alert_notifier.forget_alerts")
    mocker.patch("app.services.audit.log_event")
    fired = FiredOrder(result=OrderResult("777", "Submitted", "ibkr_paper"),
                       strategy=strategy, attempt_id="A-R2F6")
    return await atb.book_fired_order(fired, session)


@pytest.mark.asyncio
async def test_a_market_arm_with_no_drift_is_not_over_exposure_at_booking(session, mocker):
    """The fire approved 12 x mid 3.00 and nothing moved by the booking: the
    booking does not contradict the fire. (Audit round 3, R3-F1 narrowed
    R2-F6's version of this test, which also carried a 0.40 booking spread --
    see the MKT tests below.)"""
    s = _strategy(order_type="MKT", limit_price=None, portfolio_value=100_000.0)  # 12 x mid 3.00
    AutoTradeService._check_exposure(s, [], s.portfolio_value)  # 3,600 <= 3,750: the fire approves
    out = await _book(session, mocker, s, {**_QUOTE, "spread": None})  # booking: mid 3.00, no spread
    assert out.booked is True, out
    assert out.over_exposure is False


@pytest.mark.asyncio
async def test_a_limit_arm_is_judged_at_the_armed_basis_not_the_booking_mid(session, mocker):
    s = _strategy(limit_price=3.10, portfolio_value=100_000.0)  # basis max(3.00, 3.10) = 3.10
    AutoTradeService._check_exposure(s, [], s.portfolio_value)  # 12 x 310 = 3,720: approved
    out = await _book(session, mocker, s, {**_QUOTE, "price": 3.40})
    assert out.booked is True, out
    assert out.over_exposure is False


@pytest.mark.asyncio
async def test_the_booking_still_flags_an_arm_the_basis_does_not_fit(session, mocker):
    """The shared basis is not a free pass: the booking (gates off) still
    reports a breach judged at it -- here the snapshot the fire never saw.
    An LMT arm, so the armed basis is the ONLY basis (R3-F1 adds a booking-time
    floor for MKT only); the booking quote's mid is below the limit, so the
    flag can come from the armed basis alone."""
    s = _strategy(limit_price=3.00, quantity=13,
                  portfolio_value=100_000.0)                    # 13 x 300 = 3,900
    out = await _book(session, mocker, s, {**_QUOTE, "price": 2.50})
    assert out.booked is True
    assert out.over_exposure is True


# ── Audit round 3, R3-F1: a MKT arm's booking still sees the real fill ──────
#
# R2-F6 judged EVERY armed order at the armed basis at booking. For a MKT arm
# that is the armed mid, so a fill hours later (POST /auto-trade/fire has no
# age bound) at 4.00 x 12 = $4,800 -- 128% of the $3,750 cap -- booked with
# over_exposure False and no page. A MKT booking is now judged at
# max(armed basis, booking-time fill basis), the latter from the live quote via
# premium_cap_basis (ask, else mid + spread/2, else mid). LMT keeps R2-F6's
# one basis: a fill cannot exceed the limit.

@pytest.mark.asyncio
async def test_r3f1_a_market_arm_filled_after_drift_is_flagged_and_pages(session, mocker):
    from app.services import auto_trade_booking as atb
    s = _strategy(order_type="MKT", limit_price=None, portfolio_value=100_000.0)  # 12 x mid 3.00
    AutoTradeService._check_exposure(s, [], s.portfolio_value)  # 3,600 <= 3,750: the fire approves
    page = mocker.spy(atb, "_alert_over_exposure")
    out = await _book(session, mocker, s, {**_QUOTE, "price": 4.00, "spread": None})
    assert out.booked is True, out
    assert out.over_exposure is True, "12 x 4.00 = 4,800 is 128% of the 3,750 cap"
    assert page.call_count == 1
    from sqlalchemy import select
    from app.models import PortfolioPositionModel
    row = (await session.execute(select(PortfolioPositionModel))).scalars().one()
    assert row.entry_price == pytest.approx(4.00) and row.qty == 12


@pytest.mark.asyncio
async def test_r3f1_a_market_arm_is_judged_at_the_booking_ask_when_wider(session, mocker):
    """Booking quote mid 3.00, spread 0.40: a market order fills at the ask
    (3.20), 12 x 320 = 3,840 > 3,750. This is a real over-cap fill the fire's
    mid basis understated (premium_cap_basis documents it), so it is flagged."""
    s = _strategy(order_type="MKT", limit_price=None, portfolio_value=100_000.0)
    AutoTradeService._check_exposure(s, [], s.portfolio_value)
    out = await _book(session, mocker, s, dict(_QUOTE))
    assert out.booked is True, out
    assert out.over_exposure is True


@pytest.mark.asyncio
async def test_r3f1_a_market_arm_is_never_judged_below_its_armed_basis(session, mocker):
    """The armed basis is a floor: a booking quote that fell (mid 2.50) does
    not hide a quantity the armed basis does not fit (13 x 3.00 = 3,900)."""
    s = _strategy(order_type="MKT", limit_price=None, quantity=13, portfolio_value=100_000.0)
    out = await _book(session, mocker, s, {**_QUOTE, "price": 2.50, "spread": None})
    assert out.booked is True, out
    assert out.over_exposure is True


@pytest.mark.asyncio
async def test_r3f1_a_market_arm_whose_quote_fell_is_not_flagged(session, mocker):
    s = _strategy(order_type="MKT", limit_price=None, portfolio_value=100_000.0)  # 12 x 3.00
    out = await _book(session, mocker, s, {**_QUOTE, "price": 2.50, "spread": None})
    assert out.booked is True, out
    assert out.over_exposure is False


@pytest.mark.asyncio
async def test_r3f1_a_market_arm_with_no_live_quote_is_judged_at_its_armed_basis(session, mocker):
    s = _strategy(order_type="MKT", limit_price=None, portfolio_value=100_000.0)  # 12 x 3.00
    out = await _book(session, mocker, s, None)
    assert out.booked is True, out
    assert out.over_exposure is False


@pytest.mark.asyncio
async def test_r3f1_a_limit_arm_keeps_the_one_armed_basis_after_drift(session, mocker):
    """R2-F6 unchanged for LMT: the booking quote drifted to 4.00 with a 0.40
    spread, but an LMT order cannot fill above its 3.10 limit, so the booking
    judges at max(armed mid, limit) = 3.10 -> 12 x 310 = 3,720, not flagged."""
    from app.services import auto_trade_booking as atb
    s = _strategy(limit_price=3.10, portfolio_value=100_000.0)
    AutoTradeService._check_exposure(s, [], s.portfolio_value)
    page = mocker.spy(atb, "_alert_over_exposure")
    out = await _book(session, mocker, s, {**_QUOTE, "price": 4.00})
    assert out.booked is True, out
    assert out.over_exposure is False
    assert page.call_count == 0


@pytest.mark.asyncio
async def test_create_position_refuses_both_a_basis_and_a_floor(session):
    from app.services.position_writer import create_position
    from app.services import auto_trade_booking as atb
    from app.services.auto_trader import FiredOrder
    body = atb._build_body(FiredOrder(result=None, strategy=_strategy(), attempt_id="A1"), "REC-X")
    with pytest.raises(ValueError):
        await create_position(body, session, cap_basis=3.10, cap_basis_floor=3.00,
                              enforce_pre_trade_gates=False)
