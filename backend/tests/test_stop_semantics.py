# backend/tests/test_stop_semantics.py
"""STOP-SEMANTICS-2026-10-02 (docs/superpowers/plans/2026-10-02-stop-semantics-plan.md).

(a) A SHORT stock position's (Bearish `|STOCK`) percent stop fires when the
    price RISES pct above entry; every other position keeps the fall-side rule.
(b) A per-position premium stop whose threshold is below $0.01 at the entry is
    refused when saved: a late 422 on PATCH, a fallback (never a refusal) on
    create.

The TS twins are pinned in frontend/lib/__tests__/premiumStop.test.ts against
the same shared fixture this module reads.
"""
from __future__ import annotations

import inspect
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.services.alert_generator import generate_alerts
from app.services.premium_stop import (
    is_short_stock_position,
    percent_stop_threshold_price,
    premium_stop_is_sub_cent,
    premium_stop_side,
)

_FIXTURE = (Path(__file__).resolve().parents[2]
            / 'frontend/lib/__tests__/fixtures/premium_stop_subcent.json')


# ── Helpers ──────────────────────────────────────────────────────────────────

def test_short_stock_is_bearish_stock_only_and_case_sensitive():
    assert is_short_stock_position('AAPL|STOCK', 'Bearish') is True
    assert is_short_stock_position('AAPL|STOCK', 'Bullish') is False
    # A Bearish OPTION is a long put, not a short.
    assert is_short_stock_position('AAPL|190|2026-05-16|P', 'Bearish') is False
    # Exactly what the engines test: no upper-casing.
    assert is_short_stock_position('AAPL|stock', 'Bearish') is False
    assert is_short_stock_position('AAPL|STOCK', 'bearish') is False
    assert is_short_stock_position(None, 'Bearish') is False


def test_stop_side():
    assert premium_stop_side('AAPL|STOCK', 'Bearish') == 'short-stock'
    assert premium_stop_side('AAPL|STOCK', 'Bullish') == 'long-stock'
    assert premium_stop_side('AAPL|190|2026-05-16|P', 'Bearish') == 'option'
    assert premium_stop_side('AAPL|190|2026-05-16|C', 'Bullish') == 'option'


def test_threshold_is_direction_aware():
    assert percent_stop_threshold_price(100.0, 0.10, True) == pytest.approx(110.0)
    assert percent_stop_threshold_price(100.0, 0.10, False) == pytest.approx(90.0)


def test_short_flag_has_no_default():
    # No call site can apply the long rule to a short by omission.
    for fn in (percent_stop_threshold_price, premium_stop_is_sub_cent):
        param = inspect.signature(fn).parameters['short_stock']
        assert param.default is inspect.Parameter.empty, fn.__name__


def test_sub_cent_is_the_engine_comparison_at_one_cent():
    assert premium_stop_is_sub_cent(0.05, 0.90, False) is True     # 0.005 < 0.01
    # 0.10 * (1 - 0.9) is 0.009999999999999998: a few ulps under a cent, so
    # the engines never fire it (plan §3.1: today's Settings hint names $0.10
    # as the 90% limit, and it is itself sub-cent).
    assert premium_stop_is_sub_cent(0.10, 0.90, False) is True
    assert premium_stop_is_sub_cent(0.11, 0.90, False) is False
    assert premium_stop_is_sub_cent(5.00, 0.60, False) is False
    # A short fires on a rise and is never sub-cent, even at a sub-penny entry.
    assert premium_stop_is_sub_cent(0.05, 0.90, True) is False
    # A non-positive entry is not "sub-cent" (nothing to refuse against).
    assert premium_stop_is_sub_cent(0.0, 0.90, False) is False


def test_shared_fixture_long_and_dollar_rows():
    data = json.loads(_FIXTURE.read_text())
    for ec, bp, expected in data['long']:
        assert premium_stop_is_sub_cent(ec / 100, bp / 10000, False) is expected, (ec, bp)
    for ec, dc, expected in data['dollar']:
        e = ec / 100
        assert premium_stop_is_sub_cent(e, (dc / 100) / e, False) is expected, (ec, dc)
    # The float-noise family (Q4): e - 1c stops whose threshold lands a few ulps
    # under $0.01 never fire under either engine, so they ARE sub-cent.
    assert sum(1 for *_, s in data['dollar'] if s) == 2878


def test_shared_fixture_short_thresholds():
    data = json.loads(_FIXTURE.read_text())
    for ec, bp, threshold in data['short']:
        assert percent_stop_threshold_price(ec / 100, bp / 10000, True) == threshold, (ec, bp)


# ── (a) The engine ───────────────────────────────────────────────────────────

async def _make_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _stock(direction: str, **overrides) -> PortfolioPositionModel:
    base = dict(
        id=uuid.uuid4(), rec_id="rec-s", symbol="AAPL", contract="AAPL|STOCK",
        direction=direction, entry_price=100.0, qty=10, entry_date="2024-01-01",
        # Stops far away so only PREMIUM_STOP can fire.
        stop=(1000.0 if direction == "Bearish" else 1.0), targets=[], dte_total=30,
        entry_stock_price=100.0, alert_state={}, premium_stop_pct=0.10,
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


async def _premium_alerts(position, price):
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(position)
        await db.commit()
        alerts = await generate_alerts(
            db, {position.symbol: price}, {position.contract: price})
    return [a for a in alerts if a.alertType == "PREMIUM_STOP"]


@pytest.mark.asyncio
async def test_short_stock_fires_on_a_rise_at_the_computed_threshold():
    threshold = percent_stop_threshold_price(100.0, 0.10, True)   # 110.00000000000001
    [alert] = await _premium_alerts(_stock("Bearish"), threshold)
    assert alert.referenceValue == round(threshold, 4)
    assert alert.stopSide == "short-stock"
    assert alert.reason == "Stock stop — AAPL at $110.00"


@pytest.mark.asyncio
async def test_short_stock_does_not_fire_just_below_its_threshold_or_on_a_fall():
    threshold = percent_stop_threshold_price(100.0, 0.10, True)
    assert await _premium_alerts(_stock("Bearish"), threshold - 0.01) == []
    assert await _premium_alerts(_stock("Bearish"), 80.0) == []   # fall-side: old rule


@pytest.mark.asyncio
async def test_long_stock_unchanged_regression_guard():
    [alert] = await _premium_alerts(_stock("Bullish"), 90.0)
    assert alert.stopSide == "long-stock"
    assert alert.reason == "Premium stop — AAPL stock at $90.00"
    assert await _premium_alerts(_stock("Bullish"), 120.0) == []


@pytest.mark.asyncio
async def test_bearish_option_still_fires_on_a_fall_regression_guard():
    pos = _stock("Bearish", contract="AAPL|190|2026-05-16|P", entry_price=5.0,
                 stop=1000.0)
    [alert] = await _premium_alerts(pos, 4.50)
    assert alert.stopSide == "option"
    assert await _premium_alerts(
        _stock("Bearish", contract="AAPL|190|2026-05-16|P", entry_price=5.0, stop=1000.0),
        5.50) == []


@pytest.mark.asyncio
async def test_a_zero_quote_fires_nothing():
    # Fails on main: `0.0 <= threshold` fired a long's stop on a quote that
    # rounded to $0.00. The frontend engine already required currentPrice > 0.
    pos = _stock("Bullish", contract="AAPL|190|2026-05-16|C", entry_price=5.0)
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(pos)
        await db.commit()
        alerts = await generate_alerts(db, {"AAPL": 150.0}, {pos.contract: 0.0})
    assert [a for a in alerts if a.alertType == "PREMIUM_STOP"] == []


# ── (b) Refusal at save ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_client():
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


async def _create(client, *, live_price=None, rec="REC-SS", entry=5.20,
                  contract="AAPL|190|2026-05-16|C", direction="Bullish",
                  symbol="AAPL", **extra):
    body = {
        "recId": rec, "symbol": symbol, "contract": contract,
        "direction": direction, "horizon": "Swing", "entryPrice": entry, "qty": 1,
        "entryDate": "2026-05-01", "targets": [], "dteTotal": 30,
        "portfolioValue": 1_000_000,
    }
    body.update(extra)
    quote = None if live_price is None else {"price": live_price}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=quote)), \
         patch("app.services.position_writer.fetch_contract_quote_async",
               new=AsyncMock(return_value=quote)), \
         patch("app.services.position_writer.fetch_price_async",
               new=AsyncMock(return_value=live_price)):
        return await client.post("/api/portfolio", json=body)


@pytest.mark.asyncio
async def test_patch_refuses_a_sub_cent_stop_but_saves_the_stop_sent_alongside(api_client):
    created = await _create(api_client, entry=0.05, rec="REC-P1")
    assert created.status_code == 201, created.text
    r = await api_client.patch("/api/portfolio/REC-P1",
                               json={"premiumStopPct": 0.90, "stop": 150.0})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "premium_stop_below_one_cent"
    rows = (await api_client.get("/api/portfolio")).json()
    row = next(p for p in rows if p["recId"] == "REC-P1")
    assert row["premiumStopPct"] is None          # unchanged
    assert row["stop"] == 150.0                   # the co-sent field WAS saved


@pytest.mark.asyncio
async def test_patch_allows_a_valid_stop_and_an_explicit_null(api_client):
    await _create(api_client, entry=0.05, rec="REC-P2")
    ok = await api_client.patch("/api/portfolio/REC-P2", json={"premiumStopPct": 0.50})
    assert ok.status_code == 200, ok.text
    assert ok.json()["premiumStopPct"] == pytest.approx(0.50)
    cleared = await api_client.patch("/api/portfolio/REC-P2", json={"premiumStopPct": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["premiumStopPct"] is None


@pytest.mark.asyncio
async def test_patch_never_refuses_a_short_at_a_sub_penny_entry(api_client):
    await _create(api_client, entry=0.05, rec="REC-P3", contract="AAPL|STOCK",
                  direction="Bearish")
    r = await api_client.patch("/api/portfolio/REC-P3", json={"premiumStopPct": 0.90})
    assert r.status_code == 200, r.text
    assert r.json()["premiumStopPct"] == pytest.approx(0.90)


@pytest.mark.asyncio
@pytest.mark.parametrize("qty_body, expected_qty_error", [
    ({"qty": 0}, "qty must be an integer of at least 1."),
    ({"qty": 5}, "portfolioValue is required to increase qty."),
])
async def test_patch_joins_a_free_text_qty_error_and_the_premium_code(
        api_client, qty_body, expected_qty_error):
    await _create(api_client, entry=0.05, rec="REC-P4")
    r = await api_client.patch("/api/portfolio/REC-P4",
                               json={"premiumStopPct": 0.90, **qty_body})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == f"{expected_qty_error} | premium_stop_below_one_cent"


@pytest.mark.asyncio
async def test_patch_qty_only_failure_detail_is_unchanged(api_client):
    await _create(api_client, entry=0.05, rec="REC-P5")
    r = await api_client.patch("/api/portfolio/REC-P5", json={"qty": 0})
    assert r.status_code == 422
    assert r.json()["detail"] == "qty must be an integer of at least 1."


@pytest.mark.asyncio
async def test_patch_risk_code_qty_error_is_joined_too(api_client):
    await _create(api_client, entry=0.05, rec="REC-P6")
    with patch("app.routers.portfolio.check_position_risk") as risk:
        risk.return_value.approved = False
        risk.return_value.reasons = ["single_trade_exposure_too_high", "total_exposure_limit_reached"]
        risk.return_value.adjusted_size = None
        r = await api_client.patch("/api/portfolio/REC-P6", json={
            "premiumStopPct": 0.90, "qty": 5, "portfolioValue": 1000})
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "single_trade_exposure_too_high total_exposure_limit_reached | premium_stop_below_one_cent")


@pytest.mark.asyncio
async def test_patch_reports_a_trimmed_qty_that_was_saved(api_client):
    await _create(api_client, entry=0.05, rec="REC-P7")
    with patch("app.routers.portfolio.check_position_risk") as risk:
        risk.return_value.approved = True
        risk.return_value.reasons = []
        risk.return_value.adjusted_size = 3
        r = await api_client.patch("/api/portfolio/REC-P7", json={
            "premiumStopPct": 0.90, "qty": 5, "portfolioValue": 1000})
    assert r.status_code == 422
    assert r.json()["detail"] == "premium_stop_below_one_cent | qty_saved_as_3"
    rows = (await api_client.get("/api/portfolio")).json()
    assert next(p for p in rows if p["recId"] == "REC-P7")["qty"] == 3


@pytest.mark.asyncio
async def test_create_drops_a_sub_cent_dollar_stop_to_the_global(api_client, caplog):
    # $0.02 on a $0.03 entry: the e - 1c float-noise family (Q4).
    r = await _create(api_client, entry=0.03, rec="REC-C1", premiumStopDollar=0.02)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] is None
    assert any("fires below $0.01" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_create_drops_a_sub_cent_client_fraction(api_client):
    r = await _create(api_client, entry=0.05, rec="REC-C2", premiumStopPct=0.90)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] is None


@pytest.mark.asyncio
async def test_create_keeps_a_valid_client_fraction_when_the_dollar_is_sub_cent(api_client):
    # $0.02 on $0.03 is sub-cent (float noise, Q4). The client's 0.50 ($0.015)
    # is independently valid and is kept, exactly as for a ratio >= 1.
    r = await _create(api_client, entry=0.03, rec="REC-C3",
                      premiumStopDollar=0.02, premiumStopPct=0.50)
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPct"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_create_keeps_a_valid_stop_and_a_short_at_a_sub_penny_entry(api_client):
    ok = await _create(api_client, entry=5.20, rec="REC-C4", premiumStopDollar=2.60)
    assert ok.json()["premiumStopPct"] == pytest.approx(0.50)
    short = await _create(api_client, entry=0.05, rec="REC-C5", contract="MSFT|STOCK",
                          symbol="MSFT", direction="Bearish", premiumStopPct=0.90)
    assert short.status_code == 201, short.text
    assert short.json()["premiumStopPct"] == pytest.approx(0.90)
