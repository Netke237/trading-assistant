"""O4 step 2: `create_position(..., enforce_pre_trade_gates=...)` (spec section 5.2).

Both branches, called directly. Every call passes the three fetchers
EXPLICITLY: they are bound as keyword defaults, so patching
`app.services.position_writer.fetch_contract_quote_async` would not reach them
(the step-1 open_question on keyword defaults) and the test would go to the
network.

`check_position_risk` IS patched by module name, and that does land: the body
looks it up as a global at call time.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate
from app.services.portfolio_risk import RiskCheckResult
from app.services.position_writer import create_position

_RISK = "app.services.position_writer.check_position_risk"
_LOGGER = "app.services.position_writer"


async def _new_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def Session():
    engine, maker = await _new_db()
    yield maker
    await engine.dispose()


def _body(**overrides) -> PortfolioPositionCreate:
    body = {
        "recId": "REC-G1", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 4,
        "entryDate": "2026-07-17", "stop": 89.89, "targets": [],
        "dteTotal": 547, "portfolioValue": 1_000_000,
    }
    body.update(overrides)
    return PortfolioPositionCreate(**body)


def _fetchers(quote=None, price=None) -> dict:
    return {
        "quote_fetcher": AsyncMock(return_value=quote),
        "price_fetcher": AsyncMock(return_value=price),
        "exit_plan_cfg_loader": lambda: {"target": {"rr_ratios": [1.0, 2.0]}},
    }


async def _rows(Session) -> list[PortfolioPositionModel]:
    async with Session() as db:
        return list((await db.execute(select(PortfolioPositionModel))).scalars().all())


# ── the exposure gate ────────────────────────────────────────────────────────

# `approved=False` in both shapes `check_position_risk` produces. The
# `adjusted_size=None` one (max concurrent positions) is the case that proves
# `over_exposure` is read from `approved` and not inferred from a resize.
_REFUSALS = [
    pytest.param(RiskCheckResult(approved=False, reasons=["max_concurrent_positions_reached"],
                                 adjusted_size=None), id="refused-no-resize"),
    pytest.param(RiskCheckResult(approved=False,
                                 reasons=["size_reduced_to_fit_exposure_limit",
                                          "total_exposure_limit_reached"],
                                 adjusted_size=2), id="refused-with-resize"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", _REFUSALS)
async def test_gates_on_an_unapproved_position_is_refused_and_not_written(Session, refused, caplog):
    with patch(_RISK, return_value=refused) as risk, caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            with pytest.raises(HTTPException) as exc:
                await create_position(_body(), db, **_fetchers())
    assert risk.call_count == 1
    assert caplog.messages == [], "the default path logs nothing new"
    assert exc.value.status_code == 422
    assert exc.value.detail == " ".join(refused.reasons)
    assert await _rows(Session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", _REFUSALS)
async def test_gates_off_an_unapproved_position_is_booked_at_the_ordered_qty_and_flagged(
    Session, refused, caplog,
):
    with patch(_RISK, return_value=refused) as risk, caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(), db, enforce_pre_trade_gates=False, **_fetchers(),
            )

    assert risk.call_count == 1, "the risk check still runs -- over_exposure is read from it"
    assert outcome.over_exposure is True
    assert outcome.adjusted_size == refused.adjusted_size, "reported, not applied"
    assert outcome.position.qty == 4, "the books match the broker, not the gate"
    assert [(r.rec_id, r.qty) for r in await _rows(Session)] == [("REC-G1", 4)]
    assert any("OVER the exposure gate" in m for m in caplog.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("gates, stored_qty, over", [(True, 2, False), (False, 4, True)])
async def test_an_approved_soft_resize_is_applied_with_gates_on_and_flagged_with_gates_off(
    Session, gates, stored_qty, over,
):
    """`approved=True` with an `adjusted_size` is the soft reason. Gates on
    resizes exactly as the card path always has. Gates off books the ordered
    quantity -- and that IS an over-exposure (round 1): the check judged both
    caps on the resized capital, so the booked quantity is over the single-
    position cap and can be over the total cap with `approved` still True."""
    resized = RiskCheckResult(approved=True, reasons=["size_reduced_to_fit_exposure_limit"],
                              adjusted_size=2)
    with patch(_RISK, return_value=resized):
        async with Session() as db:
            outcome = await create_position(
                _body(), db, enforce_pre_trade_gates=gates, **_fetchers(),
            )
    assert outcome.over_exposure is over
    assert outcome.adjusted_size == 2
    assert outcome.position.qty == stored_qty
    assert [r.qty for r in await _rows(Session)] == [stored_qty]


@pytest.mark.asyncio
async def test_gates_off_a_qty_over_the_per_trade_clamp_is_flagged(Session, caplog):
    """The REAL check clamps the quantity to `max_contracts_per_trade` before
    judging anything, so it can approve with no resize while a larger quantity
    is booked (round 1). The clamp is read from config, not assumed."""
    from app.services.portfolio_risk import _load_config
    cap = _load_config()["sizing"]["max_contracts_per_trade"]
    with caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(qty=cap + 3), db, enforce_pre_trade_gates=False, **_fetchers(),
            )
    assert outcome.adjusted_size is None, "precondition: the check approved with no resize"
    assert outcome.over_exposure is True
    assert outcome.position.qty == cap + 3
    assert any(f"max_contracts_per_trade {cap}" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_gates_off_a_clean_approval_is_not_flagged(Session, caplog):
    with caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(), db, enforce_pre_trade_gates=False, **_fetchers(),
            )
    assert (outcome.over_exposure, outcome.adjusted_size, outcome.position.qty) == (False, None, 4)
    assert caplog.messages == []


# ── the wrong-side-stop guard ────────────────────────────────────────────────

# Each against an underlying at 145. For an option the underlying comes from
# `price_fetcher`; for `|STOCK` it is the quote's own price (`price_fetcher`
# is not called), so both sources of `live_price` are exercised.
_WRONG_SIDE = [
    pytest.param(dict(direction="Bullish", stop=150.0), dict(price=145.0),
                 "A bullish stop of 150.00", id="bullish-option"),
    pytest.param(dict(direction="Bearish", stop=140.0), dict(price=145.0),
                 "A bearish stop of 140.00", id="bearish-option"),
    pytest.param(dict(direction="Bullish", stop=150.0, contract="ABT|STOCK",
                      entryPrice=145.0, qty=1),
                 dict(quote={"price": 145.0}), "A bullish stop of 150.00", id="bullish-stock"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("fields, fetched, prefix", _WRONG_SIDE)
async def test_gates_on_a_wrong_side_user_stop_is_refused(Session, fields, fetched, prefix):
    async with Session() as db:
        with pytest.raises(HTTPException) as exc:
            await create_position(_body(stopIsUserSet=True, **fields), db, **_fetchers(**fetched))
    assert exc.value.status_code == 422
    assert exc.value.detail == (
        f"{prefix} is on the wrong side of the underlying at 145.00; it would fire immediately."
    )
    assert await _rows(Session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fields, fetched, prefix", _WRONG_SIDE)
async def test_gates_off_a_wrong_side_user_stop_is_booked_as_sent_with_a_warning(
    Session, caplog, fields, fetched, prefix,
):
    with caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(stopIsUserSet=True, **fields), db, enforce_pre_trade_gates=False,
                **_fetchers(**fetched),
            )
    assert outcome.over_exposure is False
    assert [(r.rec_id, r.stop) for r in await _rows(Session)] == [("REC-G1", fields["stop"])]
    assert any(prefix in m and "wrong side of the underlying at 145.00" in m
               and "anyway" in m for m in caplog.messages)


# ── what gates-off must NOT turn off ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_gates_off_still_raises_the_duplicate_contract_409(Session):
    async with Session() as db:
        await create_position(_body(), db, **_fetchers())
    async with Session() as db:
        with pytest.raises(HTTPException) as exc:
            await create_position(_body(recId="REC-G2"), db,
                                  enforce_pre_trade_gates=False, **_fetchers())
    assert exc.value.status_code == 409
    assert [r.rec_id for r in await _rows(Session)] == ["REC-G1"]


@pytest.mark.asyncio
async def test_gates_off_still_raises_the_rec_id_collision_500(Session):
    """Same recId, different contract: the pre-check passes, the commit trips
    `rec_id`'s unique constraint, and the row genuinely never persisted."""
    async with Session() as db:
        await create_position(_body(), db, **_fetchers())
    async with Session() as db:
        with pytest.raises(HTTPException) as exc:
            await create_position(_body(contract="ABT|99|2027-01-15|C"), db,
                                  enforce_pre_trade_gates=False, **_fetchers())
    assert exc.value.status_code == 500
    assert [r.contract for r in await _rows(Session)] == ["ABT|97|2027-01-15|C"]


def _row_state(row: PortfolioPositionModel) -> dict:
    # `created_at` and `resolved_tp_updated_at` are `now()` at write time; the
    # latter's PRESENCE is asserted separately.
    skip = {"id", "created_at", "resolved_tp_updated_at"}
    return {a.key: getattr(row, a.key) for a in sa_inspect(PortfolioPositionModel).column_attrs
            if a.key not in skip}


@pytest.mark.asyncio
async def test_gates_off_writes_the_same_row_as_gates_on_when_no_gate_trips():
    """With no gate tripped the two modes must be indistinguishable, and every
    step that must stay on in both (live entry replacement, re-anchor,
    premium-stop derivation, seed_tp_from_pick) is shown to have RUN -- so the
    equality is not two runs that both skipped them."""
    body = dict(
        scanStockPrice=100.0,                       # re-anchor: live 103 -> delta +3
        stop=95.0, structuralStop=94.0,
        targets=[{"stockPrice": 110.0, "targetPrice": 110.0}],
        premiumStopDollar=2.08,                     # 2.08 / live entry 5.20 = 0.40
        pickedMethod="monte_carlo", pickedRowStockPrice=112.0,
    )
    # One database per mode, so the second write is not refused by the REAL
    # risk check's duplicate-symbol rule because the first one exists.
    states = {}
    for gates in (True, False):
        engine, maker = await _new_db()
        try:
            async with maker() as db:
                outcome = await create_position(
                    _body(**body), db, enforce_pre_trade_gates=gates,
                    **_fetchers(quote={"price": 5.2}, price=103.0),
                )
        finally:
            await engine.dispose()
        # Precondition, not the claim: the real risk check approved with no
        # resize. If config ever changes that, fail HERE, not as a false
        # "the modes diverge".
        assert (outcome.over_exposure, outcome.adjusted_size) == (False, None)
        row = outcome.position
        assert row.entry_price == 5.2, "live entry replacement"
        assert (row.stop, row.structural_stop, row.entry_stock_price) == (98.0, 97.0, 103.0), "re-anchor"
        assert row.targets[0]["stockPrice"] == 113.0, "targets re-anchored"
        assert row.premium_stop_pct == pytest.approx(0.40), "premium-stop derivation"
        assert (row.active_tp_method, row.resolved_tp_price) == ("monte_carlo", 112.0), "seed_tp_from_pick"
        assert row.resolved_tp_updated_at is not None
        states[gates] = _row_state(row)

    assert states[True] == states[False]
