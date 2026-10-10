"""GET /api/contracts `expiry` and `strikes` (WATCHLIST-SCAN-CONTRACT-RULES).

The Watchlist asks for a starred contract's own expiry and strikes. Before
this, it made one default call per (symbol, right) and matched stars against
the result: `limit` 10, `max_price` 50 and the moving first->=21-day expiry
made stars silently vanish. Both parameters absent = unchanged behaviour.
"""

import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest

from tests.test_step6_contract_rules import _LOOSE

_E = (date.today() + timedelta(days=45)).isoformat()
_OTHER = (date.today() + timedelta(days=52)).isoformat()


def _row(strike, expiry=_E, *, price=2.50, spread=0.10, iv=True, volume=47, oi=162):
    dte = (date.fromisoformat(expiry) - date.today()).days
    row = {
        "id": f"XOM|{strike}|{expiry}|C", "symbol": "XOM", "strike": strike, "expiry": expiry,
        "right": "C", "dte": dte, "dteTotal": dte, "price": price, "spread": spread,
        "delta": 0.45, "theta": -0.05, "volume": volume, "open_interest": oi,
    }
    if iv:
        row["ivRank"] = 40
    return row


def _patches(chain, price=185.0):
    """Returns (stack, chain_mock): every case stubs the price, so the existing
    no-price 503 can never stand in for the new empty-chain one."""
    stack = ExitStack()
    chain_mock = AsyncMock(side_effect=lambda *a, **k: [dict(c) for c in chain])
    stack.enter_context(patch("app.routers.contracts.fetch_option_chain_async", chain_mock))
    stack.enter_context(patch("app.routers.contracts.fetch_price_async", AsyncMock(return_value=price)))
    return stack, chain_mock


def _get(client, chain, query):
    stack, chain_mock = _patches(chain)
    with stack:
        r = client.get("/api/contracts?symbol=XOM&right=C&stock_score=80&direction=Bullish" + query)
    return r, chain_mock


def _rules_q(rules=_LOOSE):
    return "&contract_rules=" + quote(json.dumps(rules))


# ── 6b: expiry is forwarded and filters ───────────────────────────────────────

def test_expiry_reaches_the_chain_fetch_and_filters_other_expiries(client):
    chain = [_row(185), _row(190, _OTHER)]
    r, m = _get(client, chain, f"&expiry={_E}")
    assert r.status_code == 200
    assert m.call_args.kwargs["expiry"] == _E
    assert [c["expiry"] for c in r.json()] == [_E]


def test_absent_expiry_leaves_the_call_unchanged(client):
    chain = [_row(185), _row(190, _OTHER)]
    r, m = _get(client, chain, "")
    assert r.status_code == 200
    assert "expiry" not in m.call_args.kwargs
    assert {c["expiry"] for c in r.json()} == {_E, _OTHER}


def test_empty_expiry_is_absent(client):
    chain = [_row(185)]
    r_empty, m = _get(client, chain, "&expiry=")
    r_none, _ = _get(client, chain, "")
    assert "expiry" not in m.call_args.kwargs
    assert r_empty.json() == r_none.json()


# ── 6c: parity with the call without expiry/strikes ───────────────────────────

def _by_id(rows):
    return {c["id"]: (c["score"], c["contractConfidence"], c["iv"]) for c in rows}


def test_expiry_and_strikes_grade_exactly_as_the_plain_call(client):
    chain = [_row(k) for k in (175, 180, 185, 190, 195)]
    q = _rules_q() + "&hold_min_days=20&hold_max_days=25"
    plain, _ = _get(client, chain, q)
    pinned, _ = _get(client, chain, q + f"&expiry={_E}&strikes=175,180,185,190,195")
    assert plain.status_code == pinned.status_code == 200
    assert len(plain.json()) == 5
    assert _by_id(pinned.json()) == _by_id(plain.json())


def test_strike_filter_runs_after_the_atm_iv_fill(client):
    """No vendor IV: the ATM Black-Scholes inversion fills every strike. A
    filter before it would leave a non-ATM star with iv None and a neutral
    IV sub-score."""
    chain = [_row(k, iv=False) for k in (175, 180, 185, 190, 195)]
    q = _rules_q() + "&hold_min_days=20&hold_max_days=25"
    plain, _ = _get(client, chain, q)
    pinned, _ = _get(client, chain, q + f"&expiry={_E}&strikes=195")
    want = next(c for c in plain.json() if c["strike"] == 195)
    (got,) = pinned.json()
    assert want["iv"] is not None
    assert (got["iv"], got["score"]) == (want["iv"], want["score"])


# ── 6d: strikes disables limit and max_price ──────────────────────────────────

def _wide_chain():
    """150 strikes that all score the same; those priced above max_price keep
    spread/mid constant by scaling the spread with the price."""
    rows = []
    for i in range(150):
        price = 2.50 if i < 120 else 60.0
        rows.append(_row(100 + i, price=price, spread=0.04 * price))
    return rows


def _assert_all_150_tie(client, chain):
    """Every row scores the same, so a leftover [:limit] would cut in strike
    order. Asked through `strikes` itself: `limit` caps at 100 and would hide
    the last 50."""
    every = ",".join(str(100 + i) for i in range(150))
    rows = _get(client, chain, f"&expiry={_E}&strikes={every}")[0].json()
    assert len(rows) == 150
    assert len({c["score"] for c in rows}) == 1


def test_a_starred_strike_last_in_order_and_above_max_price_is_returned(client):
    chain = _wide_chain()
    _assert_all_150_tie(client, chain)
    r, _ = _get(client, chain, f"&expiry={_E}&strikes=249")
    assert r.status_code == 200
    assert [c["strike"] for c in r.json()] == [249]


def test_twelve_tied_strikes_are_all_returned(client):
    chain = _wide_chain()
    _assert_all_150_tie(client, chain)
    last12 = list(range(238, 250))
    r, _ = _get(client, chain, f"&expiry={_E}&strikes=" + ",".join(map(str, last12)))
    assert sorted(c["strike"] for c in r.json()) == last12


@pytest.mark.parametrize("bad", ["185,abc", "185,-5", "185,+5", "1_85", "185.0", "1" * 10, "1" * 4301],
                         ids=["abc", "neg", "plus", "underscore", "float", "10-digits", "4301-digits"])
def test_a_non_int_strike_is_a_422(client, bad):
    r, _ = _get(client, [_row(185)], "&strikes=" + bad.replace("+", "%2B"))
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["query", "strikes"]


@pytest.mark.parametrize("q", ["&strikes=", "&strikes=,", "&strikes=%20"])
def test_an_empty_strike_list_is_absent(client, q):
    chain = [_row(185), _row(190)]
    assert _get(client, chain, q)[0].json() == _get(client, chain, "")[0].json()


@pytest.mark.parametrize("raw", ["187,", "187,%20190"])
def test_strike_lists_tolerate_spaces_and_trailing_commas(client, raw):
    chain = [_row(187), _row(190), _row(195)]
    r, _ = _get(client, chain, "&strikes=" + raw)
    assert r.status_code == 200
    want = {187} if raw == "187," else {187, 190}
    assert {c["strike"] for c in r.json()} == want


# ── 6f: a star's DTE decays into its hold-days floor ──────────────────────────

@pytest.mark.parametrize("dte,rejected", [(79, True), (95, False)])
def test_hold_days_set_the_floor_a_star_decays_into(client, monkeypatch, dte, rejected):
    monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier", lambda: 2.0)
    e = (date.today() + timedelta(days=dte)).isoformat()
    chain = [_row(185, e, volume=5000, oi=10000)]
    r, _ = _get(client, chain, f"&expiry={e}&hold_min_days=45&hold_max_days=60&strikes=185")
    assert r.status_code == 200
    (row,) = r.json()
    assert row["breakdown"]["dteDetail"]["preferred_min"] == 81
    assert (row["contractConfidence"] == "REJECT") is rejected, row


# ── 6g: empty chains and the fetch's expiry choice ────────────────────────────

def test_expiry_with_an_empty_chain_is_a_503(client):
    r, _ = _get(client, [], f"&expiry={_E}")
    assert r.status_code == 503
    assert r.json()["detail"].startswith("Option chain unavailable")


def test_expiry_with_a_chain_of_another_expiry_is_an_empty_200(client):
    """An unlisted expiry falls back to the default chain: not the star's rows."""
    r, _ = _get(client, [_row(185, _OTHER)], f"&expiry={_E}")
    assert r.status_code == 200
    assert r.json() == []


def test_expiry_ignores_the_hold_window_for_the_fetch_but_not_for_grading(client, monkeypatch):
    monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier", lambda: 2.0)
    e = (date.today() + timedelta(days=95)).isoformat()
    r, m = _get(client, [_row(185, e)], f"&expiry={e}&hold_min_days=45&hold_max_days=60")
    assert r.status_code == 200
    assert m.call_args.kwargs["dte_bounds"] is None
    assert m.call_args.kwargs.get("min_dte_floor") is None
    assert r.json()[0]["breakdown"]["dteDetail"]["preferred_min"] == 81


def test_without_expiry_an_empty_chain_is_still_an_empty_200(client):
    r, _ = _get(client, [], "")
    assert r.status_code == 200
    assert r.json() == []


# ── NO-LIVE-QUOTE NLQ-1 (plan 3a): the single-contract quote's expiry ────────
#
# fetch_contract_quote_async re-fetches the chain with `expiry=`; when that
# expiry is not listed the chain builder falls back to another one. T4: that
# row is not this contract's quote, so it returns None. T5: the quote's
# consumers, given that None, take their existing "unavailable" path. Run
# through the REAL fetch_contract_quote_async with only the chain fetch below
# it stubbed, so the consumers see exactly what the shared function returns.

import asyncio  # noqa: E402
from copy import deepcopy  # noqa: E402
from typing import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import app.models  # noqa: E402,F401  (registers all tables on Base.metadata)
from app.data.market import fetch_contract_quote_async  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.models.portfolio import PortfolioPositionModel  # noqa: E402
from app.schemas import PortfolioPositionCreate  # noqa: E402
from app.services.position_writer import create_position  # noqa: E402

_HELD = "ABT|97|2027-01-15|C"
_FALLBACK = "2027-02-19"     # the expiry the chain builder fell back to


def _abt_row(expiry, strike=97, price=55.0):
    return {"id": f"ABT|{strike}|{expiry}|C", "symbol": "ABT", "strike": strike, "expiry": expiry,
            "right": "C", "dte": 120, "dteTotal": 120, "price": price, "spread": 0.2,
            "delta": 0.9, "theta": -0.01, "volume": 500, "open_interest": 900,
            "quoteState": "live", "quoteLive": True, "quoteAgeS": 3.0}


def _chain_patch(rows):
    return patch("app.data.market.fetch_option_chain_async",
                 AsyncMock(side_effect=lambda *a, **k: [dict(r) for r in rows]))


def _quote(contract_id, rows):
    with _chain_patch(rows) as m:
        q = asyncio.run(fetch_contract_quote_async(object(), contract_id))
    return q, m


# T4

def test_quote_is_none_when_the_chain_came_back_for_another_expiry():
    q, m = _quote(_HELD, [_abt_row(_FALLBACK)])
    assert m.call_args.kwargs["expiry"] == "2027-01-15"
    assert q is None


def test_quote_is_the_row_for_the_requested_strike_and_expiry():
    rows = [_abt_row("2027-01-15", strike=95, price=7.0), _abt_row("2027-01-15", price=5.0)]
    q, _ = _quote(_HELD, rows)
    assert (q["strike"], q["expiry"], q["price"]) == (97, "2027-01-15", 5.0)


def test_quote_is_none_when_the_strike_has_no_row():
    # The builder drops a row whose ask is 0 (Q-C), so such a contract has no row.
    assert _quote(_HELD, [_abt_row("2027-01-15", strike=95)])[0] is None
    assert _quote(_HELD, [])[0] is None


# T5

@pytest_asyncio.fixture
async def Session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


@pytest.fixture
def _risk_ok(monkeypatch):
    from app.services import portfolio_risk
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1_000_000
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)


def _held_body(**overrides):
    body = {"recId": "REC-NLQ1", "symbol": "ABT", "contract": _HELD, "direction": "Bullish",
            "entryPrice": 10.45, "qty": 4, "entryDate": "2026-07-17", "stop": 89.89,
            "targets": [], "dteTotal": 547, "portfolioValue": 1_000_000}
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_position_writer_keeps_the_sent_entry_when_the_quote_is_another_expirys(Session, _risk_ok):
    """position_writer's save-time refetch, through its default fetcher (the
    real fetch_contract_quote_async): a None quote keeps the frontend's
    entryPrice. Before the expiry check it stored the other expiry's 55.00."""
    with _chain_patch([_abt_row(_FALLBACK)]):
        async with Session() as db:
            await create_position(PortfolioPositionCreate(**_held_body()), db)
    async with Session() as db:
        rows = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert [(r.contract, r.entry_price) for r in rows] == [(_HELD, 10.45)]


@pytest.mark.asyncio
async def test_portfolio_positions_show_no_quote_when_the_quote_is_another_expirys(Session, _risk_ok):
    """GET /api/portfolio enriches each row with fetch_contract_quote_async; a
    None quote leaves the row exactly as the no-quote path leaves it, flagged
    quoteUnavailable (round-1 F2)."""
    from app.routers.portfolio import router as portfolio_router

    with patch("app.services.position_writer.fetch_contract_quote_async", AsyncMock(return_value=None)):
        async with Session() as db:
            await create_position(PortfolioPositionCreate(**_held_body()), db)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db

    async def _positions(**patches):
        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.portfolio.fetch_price_async", AsyncMock(return_value=None)))
            for target, new in patches.items():
                stack.enter_context(patch(target, new))
            async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
                r = await c.get("/api/portfolio")
        assert r.status_code == 200, r.text
        return r.json()

    with _chain_patch([_abt_row(_FALLBACK)]):
        fell_back = await _positions()
    unavailable = await _positions(**{
        "app.routers.portfolio.fetch_contract_quote_async": AsyncMock(return_value=None)})

    assert fell_back == unavailable
    (row,) = fell_back
    assert row["currentPrice"] != 55.0
    assert row["delta"] is None
    assert row["quoteUnavailable"] is True
