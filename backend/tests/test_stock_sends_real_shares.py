# backend/tests/test_stock_sends_real_shares.py
"""STOCK-SENDS Part B (phase STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES; decisions
P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25, STOCK-SENDS-STOCK-CAPS-2026-09-27):
a stock is judged at its REAL share count against its own caps (20% single / 100%
total of portfolio value, on price x shares), each kind's total counts only its
own rows, a resized stock row's rung shares follow the resize, and the stock caps
are readable/editable through /settings/risk.

Plan: docs/superpowers/plans/2026-09-27-stock-sends-save-first-real-shares-plan.md
Part B.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.auto_trade import ArmRequest
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionCreate
from app.services.auto_trader import ArmedStrategy, AutoTradeService
from app.services.portfolio_risk import (
    EXCEEDS_MAX_CONTRACTS, PortfolioPosition, _load_config, check_position_risk,
)
from app.services.position_writer import _rescale_rung_shares, create_position

STOCK = "AAPL|STOCK"
OPTION = "MSFT|300|2026-12-18|C"


def _row(symbol, contract, qty, price):
    mult = 1 if contract.endswith("|STOCK") else 100
    return PortfolioPosition(symbol=symbol, contract_id=contract, contracts=qty,
                             entry_premium=price, current_price=price,
                             capital_at_risk=price * qty * mult)


def _check(qty, price, contract=STOCK, portfolio=(), value=100_000.0, symbol="AAPL"):
    return check_position_risk(symbol=symbol, contract_id=contract, proposed_contracts=qty,
                               entry_premium=price, current_price=price,
                               portfolio=list(portfolio), portfolio_value=value)


def test_config_carries_the_decided_stock_caps():
    rules = _load_config()["portfolio"]
    assert rules["max_single_stock_position_pct"] == 0.20
    assert rules["max_total_stock_exposure_pct"] == 1.00
    assert rules["max_single_position_pct"] == 0.05, "option caps unchanged"
    assert rules["max_total_exposure_pct"] == 0.25


# ── the check ────────────────────────────────────────────────────────────────

def test_a_stock_is_judged_at_its_real_count_and_resized_to_the_20pct_cap():
    # 300 sh x $200 = $60,000 on $100k (60%) -> resized to 100 sh ($20,000, 20%).
    r = _check(300, 200.0)
    assert r.judged_size == 300
    assert r.approved is True
    assert r.adjusted_size == 100
    assert r.reasons == ["size_reduced_to_fit_exposure_limit"]


def test_a_stock_within_20pct_passes_at_full_size():
    r = _check(90, 200.0)  # $18,000 = 18%
    assert (r.approved, r.adjusted_size, r.reasons) == (True, None, [])


def test_a_stock_is_never_refused_for_max_contracts_per_trade():
    r = _check(10, 50.0)
    assert EXCEEDS_MAX_CONTRACTS not in r.reasons
    assert r.judged_size == 10


def test_stock_total_counts_only_stock_rows():
    # $30k of OPTIONS open (way past the 25% option total) does not block a stock.
    options = [_row("MSFT", OPTION, 5, 60.0)]  # 5 x 60 x 100 = $30,000
    r = _check(50, 200.0, portfolio=options)   # $10,000 stock
    assert (r.approved, r.reasons) == (True, [])
    # The stock total is 100%, not the option 25%: $50k of stock + $10k = 60% passes.
    half = [_row(f"H{i}", f"H{i}|STOCK", 50, 200.0) for i in range(5)]  # 5 x $10,000
    r = _check(50, 200.0, portfolio=half)
    assert (r.approved, r.reasons) == (True, [])
    # Stock rows DO count: $95k of stock + $10k more is past the 100% stock total.
    stocks = [_row(f"S{i}", f"S{i}|STOCK", 95, 200.0) for i in range(5)]  # 5 x $19,000
    r = _check(50, 200.0, portfolio=stocks)
    assert r.approved is False
    assert "total_exposure_limit_reached" in r.reasons


def test_option_total_counts_only_option_rows():
    # A $60k stock row no longer blocks an option (it used to push the combined
    # total past 25% and refuse every option trade).
    stocks = [_row("AAPL", STOCK, 300, 200.0)]
    r = _check(2, 10.0, contract=OPTION, portfolio=stocks, symbol="MSFT")  # $2,000
    assert (r.approved, r.reasons) == (True, [])
    # Option rows still count against the option total.
    options = [_row("X", "X|1|2026-12-18|C", 5, 48.0)]  # $24,000
    r = _check(2, 10.0, contract=OPTION, portfolio=options, symbol="MSFT")
    assert "total_exposure_limit_reached" in r.reasons


def test_option_single_cap_is_the_loss_limit():
    # $10,000 = 10% > both caps. Review fix #4 (D5): the option cap is
    # min(5% single, 3.75% loss limit), so the shipped config resizes to 3.75%.
    r = _check(5, 20.0, contract=OPTION, symbol="MSFT")
    assert r.adjusted_size == int(100_000 * 0.0375 / (20.0 * 100))


def test_shared_checks_still_count_every_row():
    # Duplicate symbol and concurrent positions are not split by kind.
    r = _check(10, 100.0, portfolio=[_row("AAPL", "AAPL|185|2026-12-18|C", 1, 1.0)])
    assert r.reasons == ["duplicate_symbol_already_open"]


def test_missing_stock_keys_fall_back_to_the_decided_defaults():
    cfg = _load_config()
    trimmed = {**cfg, "portfolio": {k: v for k, v in cfg["portfolio"].items()
                                    if "stock" not in k}}
    with patch("app.services.portfolio_risk._load_config", return_value=trimmed):
        r = _check(300, 200.0)
    assert r.adjusted_size == 100


def test_auto_trader_exposure_ignores_stock_rows():
    body = {"broker": "ibkr_paper", "symbol": "MSFT", "option_symbol": OPTION,
            "action": "BUY", "direction": "Bullish", "horizon": "Swing", "quantity": 2,
            "order_type": "LMT", "limit_price": 10.0, "entry_premium": 10.0,
            "stop": 280.0, "conid": None}
    strategy = ArmedStrategy(**ArmRequest(**body).model_dump())
    # $60k of stock open: under the old combined total this refused the fire.
    AutoTradeService._check_exposure(strategy, [_row("AAPL", STOCK, 300, 200.0)], 100_000.0)


# ── rung rescale ─────────────────────────────────────────────────────────────

def _t(*shares):
    return [{"targetPrice": 200.0 + i, "stockPrice": 200.0 + i, "contractsToSell": c}
            for i, c in enumerate(shares)]


@pytest.mark.parametrize("before, asked, stored, after", [
    ((50, 30, 20), 100, 40, (20, 12, 8)),     # full ladder stays full
    ((33, 33), 100, 40, (13, 13)),            # partial ladder keeps its runner (R1-4)
    ((34, 33, 33), 100, 10, (4, 3, 3)),       # leftover to the largest fraction
    ((1, 1, 1), 3, 1, (1, 0, 0)),             # ties: the earlier rung
    ((5, 5), 10, 10, (5, 5)),                 # no resize: untouched
])
def test_rescale_rung_shares(before, asked, stored, after):
    out = _rescale_rung_shares(_t(*before), asked, stored)
    assert tuple(t["contractsToSell"] for t in out) == after
    assert [t["targetPrice"] for t in out] == [t["targetPrice"] for t in _t(*before)]


def test_rescale_leaves_rungs_without_shares_alone():
    targets = [{"targetPrice": 210.0}, {"targetPrice": 220.0, "contractsToSell": 10}]
    out = _rescale_rung_shares(targets, 20, 10)
    assert out == [{"targetPrice": 210.0}, {"targetPrice": 220.0, "contractsToSell": 5}]


# ── the writer ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def Session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _fetchers(price):
    return {
        "quote_fetcher": AsyncMock(return_value={"price": price}),
        "price_fetcher": AsyncMock(return_value=price),
        "exit_plan_cfg_loader": lambda: {"target": {"rr_ratios": [1.0, 2.0]}},
    }


def _stock_body(qty, targets, contract=STOCK, symbol="AAPL"):
    return PortfolioPositionCreate(
        recId=f"REC-{symbol}", symbol=symbol, contract=contract, direction="Bullish",
        entryPrice=200.0, qty=qty, entryDate="2026-09-27", stop=190.0,
        targets=targets, dteTotal=0, portfolioValue=100_000,
    )


@pytest.mark.asyncio
async def test_writer_resizes_a_stock_and_its_rung_shares(Session):
    async with Session() as db:
        outcome = await create_position(
            _stock_body(250, _t(125, 75, 50)), db, **_fetchers(200.0))
    # $50,000 on $100k -> 100 sh; rungs 125/75/50 of 250 -> 50/30/20 of 100.
    assert outcome.adjusted_size == 100
    async with Session() as db:
        [row] = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert row.qty == 100
    assert [t["contractsToSell"] for t in row.targets] == [50, 30, 20]


@pytest.mark.asyncio
async def test_writer_leaves_an_unresized_stock_ladder_alone(Session):
    async with Session() as db:
        await create_position(_stock_body(50, _t(25, 15, 10)), db, **_fetchers(200.0))
    async with Session() as db:
        [row] = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert row.qty == 50
    assert [t["contractsToSell"] for t in row.targets] == [25, 15, 10]


# ── the drawer PATCH ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with maker() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_drawer_stock_qty_raise_is_judged_at_real_shares(client):
    body = {"recId": "REC-S", "symbol": "AAPL", "contract": STOCK, "direction": "Bullish",
            "entryPrice": 200.0, "qty": 20, "entryDate": "2026-09-27", "stop": 190.0,
            "targets": [], "dteTotal": 0, "portfolioValue": 100_000}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    # 300 sh x $200 = $60k -> the drawer's raise is resized to 100 sh (20%).
    r = await client.patch("/api/portfolio/REC-S", json={"qty": 300, "portfolioValue": 100_000})
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 100
    assert r.json()["adjustedQty"] == 100


@pytest.mark.asyncio
async def test_drawer_increase_never_saves_a_smaller_stock_position(client):
    # Code round 1 on Part B: 100 sh x $200 = $20k booked at $100k (20%). At a
    # $90k portfolio the cap allows 90 sh, so "increase to 101" must be REFUSED
    # and leave 100 -- never soft-resize to 90 below what is held.
    body = {"recId": "REC-C", "symbol": "AAPL", "contract": STOCK, "direction": "Bullish",
            "entryPrice": 200.0, "qty": 100, "entryDate": "2026-09-27", "stop": 190.0,
            "targets": [], "dteTotal": 0, "portfolioValue": 100_000}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    r = await client.patch("/api/portfolio/REC-C",
                           json={"qty": 101, "stop": 185.0, "portfolioValue": 90_000})
    assert r.status_code == 422, r.text
    assert "Quantity not increased" in r.text
    rows = (await client.get("/api/portfolio")).json()
    [row] = [p for p in rows if p["recId"] == "REC-C"]
    assert row["qty"] == 100
    assert row["stop"] == 185.0, "the other fields in the same PATCH still save"


# ── /settings/risk ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settings_round_trip_the_stock_caps(tmp_path, monkeypatch):
    import app.routers.risk_settings as rs
    from app.main import app as main_app
    fake_yaml = tmp_path / "risk_rules.yaml"
    fake_yaml.write_text("portfolio:\n  max_concurrent_positions: 10\n"
                         "reward_risk:\n  premium_stop_pct: 0.60\n")
    monkeypatch.setattr(rs, "_RISK_PATH", fake_yaml)
    async with AsyncClient(transport=ASGITransport(app=main_app), base_url="http://test") as ac:
        got = (await ac.get("/settings/risk")).json()
        assert (got["maxSingleStockPositionPct"], got["maxTotalStockExposurePct"]) == (0.20, 1.00)
        r = await ac.post("/settings/risk", json={
            "premiumStopPct": 0.60, "maxSingleStockPositionPct": 0.15, "maxTotalStockExposurePct": 0.8,
        })
        assert r.status_code == 200, r.text
        got = (await ac.get("/settings/risk")).json()
    assert (got["maxSingleStockPositionPct"], got["maxTotalStockExposurePct"]) == (0.15, 0.8)
    saved = yaml.safe_load(fake_yaml.read_text())["portfolio"]
    assert (saved["max_single_stock_position_pct"], saved["max_total_stock_exposure_pct"]) == (0.15, 0.8)


@pytest.mark.asyncio
async def test_settings_refuse_a_stock_cap_above_one():
    from app.main import app as main_app
    async with AsyncClient(transport=ASGITransport(app=main_app), base_url="http://test") as ac:
        r = await ac.post("/settings/risk", json={"premiumStopPct": 0.60, "maxSingleStockPositionPct": 1.5})
    assert r.status_code == 422
