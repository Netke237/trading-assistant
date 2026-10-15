"""O4 step 2: `create_position(..., enforce_pre_trade_gates=...)` (spec section 5.2).

Both branches, called directly. Every call passes the three fetchers
EXPLICITLY. (Since P1a the defaults resolve at call time, so a module patch
would also land -- see test_position_writer.py -- but explicit is what these
tests were written against.)

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
from app.services.alert_generator import generate_alerts
from app.services.portfolio_risk import RiskCheckResult
from app.services.position_writer import create_position


@pytest.fixture(autouse=True)
def _server_account_for_legacy_risk_scenarios(monkeypatch):
    """Server account supplies the intended cap; payload values are ignored."""
    from copy import deepcopy
    from app.services import portfolio_risk
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1_000_000
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)


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


async def _stop_alerts(Session, quote):
    """Run the real alert engine on the committed row, without external audit IO."""
    with patch("app.services.alert_generator.log_event"):
        async with Session() as db:
            alerts = await generate_alerts(db, {"ABT": quote})
    return {
        alert.alertType: alert.referenceValue for alert in alerts
        if alert.alertType in {"STOP_REACHED", "STRUCTURAL_STOP_BREACHED"}
    }


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
    """P1a: the REAL check no longer clamps an OPTION quantity to
    `max_contracts_per_trade` -- it refuses it with a hard reason. Gates off
    books the ordered quantity anyway and flags it, naming the reason. The cap
    is read from config, not assumed."""
    from app.services.portfolio_risk import _load_config
    cap = _load_config()["sizing"]["max_contracts_per_trade"]
    with caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(qty=cap + 3), db, enforce_pre_trade_gates=False, **_fetchers(),
            )
    assert outcome.adjusted_size is None, "precondition: no resize -- the cap reason alone refuses"
    assert outcome.over_exposure is True
    assert outcome.position.qty == cap + 3
    assert any("exceeds_max_contracts_per_trade" in m and "OVER the exposure gate" in m
               for m in caplog.messages)


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


# ── P1a: the source-level contract cap, judged_size, Q12 ─────────────────────
# Plan: docs/superpowers/plans/2026-09-25-p1a-backend-contract-cap-plan.md s5 5-11.

from app.services.portfolio_risk import EXCEEDS_MAX_CONTRACTS  # noqa: E402


@pytest.mark.asyncio
async def test_p1a_5_gates_on_a_six_lot_is_refused_with_a_sentence_and_no_row(Session):
    async with Session() as db:
        with pytest.raises(HTTPException) as exc:
            await create_position(_body(qty=6), db, **_fetchers())
    assert exc.value.status_code == 422
    assert exc.value.detail.startswith(
        "6 contracts is above the 5-contract limit per trade (max_contracts_per_trade). "
        "Lower Contracts to 5 or fewer and send again.")
    assert "Also:" not in exc.value.detail
    assert await _rows(Session) == []
    async with Session() as db:
        outcome = await create_position(_body(qty=5), db, **_fetchers())
    assert outcome.position.qty == 5


@pytest.mark.asyncio
async def test_p1a_5_the_cap_and_another_hard_reason_both_appear(Session):
    both = RiskCheckResult(
        approved=False,
        reasons=[EXCEEDS_MAX_CONTRACTS, "size_reduced_to_fit_exposure_limit",
                 "total_exposure_limit_reached"],
        adjusted_size=4, judged_size=6, max_contracts=5)
    with patch(_RISK, return_value=both):
        async with Session() as db:
            with pytest.raises(HTTPException) as exc:
                await create_position(_body(qty=6), db, **_fetchers())
    assert "6 contracts is above the 5-contract limit" in exc.value.detail
    assert exc.value.detail.endswith(" Also: total_exposure_limit_reached")


@pytest.mark.asyncio
async def test_p1a_6_gates_off_a_six_lot_is_booked_at_six_and_flagged(Session):
    async with Session() as db:
        outcome = await create_position(
            _body(qty=6), db, enforce_pre_trade_gates=False, **_fetchers())
    assert (outcome.position.qty, outcome.over_exposure) == (6, True)


@pytest.mark.asyncio
async def test_p1a_6b_a_stock_within_its_caps_is_not_over_exposure(Session, caplog):
    """STOCK-SENDS flipped this test. 20 shares at $10 on 1M fit every cap and,
    with the |STOCK clamp gone, the check judges the REAL 20 -- so a gates-off
    booking of 20 is no longer flagged as over the exposure gate."""
    with caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(
                _body(contract="ABT|STOCK", entryPrice=10.0, qty=20, stop=9.0), db,
                enforce_pre_trade_gates=False, **_fetchers(quote={"price": 10.0}))
    assert outcome.adjusted_size is None, "precondition: no resize"
    assert (outcome.position.qty, outcome.over_exposure) == (20, False)
    assert not any("the check judged" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_p1a_7_gates_off_both_gates_in_one_call(Session):
    refused = RiskCheckResult(approved=False, reasons=["max_concurrent_positions_reached"])
    with patch(_RISK, return_value=refused):
        async with Session() as db:
            outcome = await create_position(
                _body(stopIsUserSet=True, direction="Bullish", stop=150.0), db,
                enforce_pre_trade_gates=False, **_fetchers(price=145.0))
    assert outcome.over_exposure is True
    assert outcome.wrong_side_stop is not None
    assert "A bullish stop of 150.00" in outcome.wrong_side_stop
    assert [r.stop for r in await _rows(Session)] == [150.0]


@pytest.mark.asyncio
async def test_p1a_7b_no_live_price_gates_off_checks_against_the_scan_price(Session):
    async with Session() as db:
        outcome = await create_position(
            _body(stopIsUserSet=True, stop=150.0, scanStockPrice=145.0), db,
            enforce_pre_trade_gates=False, **_fetchers(price=None))
    assert outcome.wrong_side_stop is not None
    assert "at 145.00" in outcome.wrong_side_stop
    assert "against the scan price 145.00; the live fetch failed" in outcome.wrong_side_stop


@pytest.mark.asyncio
async def test_p1a_7b_no_live_price_gates_on_is_unchanged(Session):
    """With gates on, only a live price refuses -- as before P1a."""
    async with Session() as db:
        outcome = await create_position(
            _body(stopIsUserSet=True, stop=150.0, scanStockPrice=145.0), db,
            **_fetchers(price=None))
    assert outcome.wrong_side_stop is None
    assert [r.stop for r in await _rows(Session)] == [150.0]


@pytest.mark.asyncio
async def test_p1a_8_gates_on_an_approved_resize_logs_no_breach(Session, caplog):
    resized = RiskCheckResult(approved=True, reasons=["size_reduced_to_fit_exposure_limit"],
                              adjusted_size=2, judged_size=4, max_contracts=5)
    with patch(_RISK, return_value=resized), caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            outcome = await create_position(_body(), db, **_fetchers())
    assert (outcome.position.qty, outcome.over_exposure) == (2, False)
    assert not any("OVER" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_p1a_9_a_bearish_stock_wrong_side_stop(Session):
    fields = dict(contract="ABT|STOCK", direction="Bearish", entryPrice=145.0, qty=1,
                  stop=140.0, stopIsUserSet=True)
    async with Session() as db:
        with pytest.raises(HTTPException) as exc:
            await create_position(_body(**fields), db, **_fetchers(quote={"price": 145.0}))
    assert exc.value.status_code == 422 and "A bearish stop of 140.00" in exc.value.detail
    async with Session() as db:
        outcome = await create_position(
            _body(**fields), db, enforce_pre_trade_gates=False,
            **_fetchers(quote={"price": 145.0}))
    assert outcome.wrong_side_stop is not None and "A bearish stop" in outcome.wrong_side_stop


@pytest.mark.asyncio
async def test_p1a_10_a_refusal_with_a_resize_names_the_resize_once(Session, caplog):
    refused = RiskCheckResult(
        approved=False,
        reasons=["size_reduced_to_fit_exposure_limit", "total_exposure_limit_reached"],
        adjusted_size=2)
    with patch(_RISK, return_value=refused), caplog.at_level(logging.WARNING, _LOGGER):
        async with Session() as db:
            await create_position(_body(), db, enforce_pre_trade_gates=False, **_fetchers())
    [msg] = [m for m in caplog.messages if "OVER the exposure gate" in m]
    assert msg.count("resize") == 1 and "size_reduced_to_fit_exposure_limit" not in msg
    assert "total_exposure_limit_reached" in msg


@pytest.mark.asyncio
async def test_p1a_11_the_writer_reads_no_risk_config_of_its_own(Session, mocker):
    mocker.patch("app.services.portfolio_risk._load_config",
                 side_effect=AssertionError("the writer read the risk config"))
    refused = RiskCheckResult(approved=False, reasons=["total_exposure_limit_reached"])
    with patch(_RISK, return_value=refused):
        async with Session() as db:
            outcome = await create_position(
                _body(qty=9), db, enforce_pre_trade_gates=False, **_fetchers())
    assert (outcome.position.qty, outcome.over_exposure) == (9, True)


# ── T8: stop direction against a quote that is not the stored entry ──────────
#
# The live underlying is 120 for a bullish position and 80 for a bearish one.
# The client entry is 100 on a stock (or the option premium, 10.45 / stored
# 8.25). A bullish stop of 110 is above that entry and still below the quote:
# that is a profitable trailing stop, not a wrong-side stop. Equality with the
# quote is wrong-side for a user-set stop (`>=` / `<=`), because the alert
# fires on the same comparison. Gates off is an order already at the broker:
# the stop is booked and the warning is returned. A generated stop is
# re-anchored and is not direction-checked. Generated nonpositive levels stay
# unset; user nonpositive levels still reach the existing gates-on check.

def _user_live_cases():
    rows = []
    specs = (
        ("Bullish", 120.0, ((110.0, "ok"), (120.0, "wrong"), (130.0, "wrong"), (90.0, "ok"))),
        ("Bearish", 80.0, ((90.0, "ok"), (80.0, "wrong"), (70.0, "wrong"), (110.0, "ok"))),
    )
    for direction, quote, stops in specs:
        for instrument in ("stock", "option"):
            for gates_on in (True, False):
                for stop, kind in stops:
                    rows.append(pytest.param(
                        direction, instrument, quote, stop, gates_on, kind,
                        id=f"{direction.lower()}-{instrument}-{stop:.0f}-{'on' if gates_on else 'off'}-{kind}",
                    ))
    return rows


def _direction_fields(direction, instrument, stop, **extra):
    fields = {
        "direction": direction,
        "stop": stop,
        "stopIsUserSet": True,
        "scanStockPrice": 100.0,
        "entryPrice": 100.0,
    }
    if instrument == "stock":
        fields.update(contract="ABT|STOCK", qty=1)
    else:
        # Premium entry, so the stored entry cannot be confused with the
        # underlying quote the stop is checked against.
        fields["entryPrice"] = 10.45
    fields.update(extra)
    return fields


def _underlying_fetch(instrument, underlying):
    if instrument == "stock":
        return _fetchers(quote={"price": underlying})
    return _fetchers(quote={"price": 8.25}, price=underlying)


def _wrong_side_detail(direction, stop, price, suffix=""):
    return (
        f"A {direction.lower()} stop of {stop:.2f} is on the wrong side of the "
        f"underlying at {price:.2f}; it would fire immediately.{suffix}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction, instrument, quote, stop, gates_on, kind", _user_live_cases(),
)
async def test_user_set_stop_is_judged_against_the_live_quote_not_the_entry(
    Session, direction, instrument, quote, stop, gates_on, kind,
):
    """Gates off books a wrong-side user stop (already filled) and pages it.
    Gates on refuses it. Neither path treats "above the client entry" as the
    violation, and a user-set stop is stored as sent — not re-anchored off
    scanStockPrice 100."""
    body = _body(**_direction_fields(direction, instrument, stop))
    fetched = _underlying_fetch(instrument, quote)
    detail = _wrong_side_detail(direction, stop, quote)
    async with Session() as db:
        if kind == "wrong" and gates_on:
            with pytest.raises(HTTPException) as exc:
                await create_position(body, db, enforce_pre_trade_gates=True, **fetched)
            assert exc.value.status_code == 422
            assert exc.value.detail == detail
            assert await _rows(Session) == []
            return
        outcome = await create_position(
            body, db, enforce_pre_trade_gates=gates_on, **fetched,
        )
    assert outcome.position.stop == stop
    assert outcome.position.entry_price == (quote if instrument == "stock" else 8.25)
    if kind == "wrong":
        assert outcome.wrong_side_stop == detail
    else:
        assert outcome.wrong_side_stop is None
    assert [(r.stop, r.entry_price) for r in await _rows(Session)] == [
        (stop, quote if instrument == "stock" else 8.25),
    ]
    assert await _stop_alerts(Session, quote) == (
        {"STOP_REACHED": stop} if kind == "wrong" else {}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("gates_on", [True, False])
async def test_no_live_quote_user_stop_uses_the_scan_price_only_when_gates_are_off(Session, gates_on):
    """No live quote. Client entry 100 stays stored. Scan 120 is a different
    number from that entry. Stop 110 is above the entry and below the scan
    quote, so it is not wrong-side. Stop 130 is above the scan quote: gates
    off pages it, gates on still stores it and does not check."""
    stored = []
    for rec, stop, scan, direction in (
        ("REC-G1", 110.0, 120.0, "Bullish"),
        ("REC-G2", 130.0, 100.0, "Bullish"),
        ("REC-G3", 90.0, 80.0, "Bearish"),
        ("REC-G4", 70.0, 80.0, "Bearish"),
    ):
        body = _body(**_direction_fields(
            direction, "stock", stop, recId=rec, symbol=rec, contract=f"{rec}|STOCK",
            scanStockPrice=scan,
        ))
        async with Session() as db:
            outcome = await create_position(
                body, db, enforce_pre_trade_gates=gates_on, **_fetchers(),
            )
        assert outcome.position.entry_price == 100.0
        assert outcome.position.stop == stop
        if gates_on or stop in (110.0, 90.0):
            assert outcome.wrong_side_stop is None
        else:
            assert outcome.wrong_side_stop == _wrong_side_detail(
                direction, stop, scan,
                f" (against the scan price {scan:.2f}; the live fetch failed)",
            )
        stored.append((rec, stop, 100.0, outcome.wrong_side_stop is not None))
    rows = sorted((r.rec_id, r.stop, r.entry_price) for r in await _rows(Session))
    assert rows == sorted((rec, stop, entry) for rec, stop, entry, _warned in stored)


@pytest.mark.asyncio
async def test_no_live_quote_and_no_scan_price_does_not_direction_check(Session):
    body = _body(**_direction_fields(
        "Bullish", "stock", 130.0, scanStockPrice=None,
    ))
    async with Session() as db:
        outcome = await create_position(
            body, db, enforce_pre_trade_gates=False, **_fetchers(),
        )
    assert outcome.wrong_side_stop is None
    assert (outcome.position.stop, outcome.position.entry_price) == (130.0, 100.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction, quote", [("Bullish", 120.0), ("Bearish", 80.0)])
@pytest.mark.parametrize("instrument", ["stock", "option"])
@pytest.mark.parametrize("sent", [0, -1, None])
@pytest.mark.parametrize("gates_on", [True, False])
async def test_zero_and_unset_user_stops_are_floored_after_the_direction_check(
    Session, direction, quote, instrument, sent, gates_on,
):
    """Preserve the gates-on policy; gates off describes the persisted NULL."""
    body = _body(**_direction_fields(direction, instrument, sent))
    refused = gates_on and direction == "Bearish" and sent is not None
    async with Session() as db:
        if refused:
            with pytest.raises(HTTPException) as exc:
                await create_position(body, db, enforce_pre_trade_gates=True, **_underlying_fetch(instrument, quote))
            assert exc.value.status_code == 422
            assert exc.value.detail == _wrong_side_detail(direction, sent, quote)
            assert await _rows(Session) == []
            return
        outcome = await create_position(
            body, db, enforce_pre_trade_gates=gates_on, **_underlying_fetch(instrument, quote),
        )
    assert outcome.position.stop is None
    assert [r.stop for r in await _rows(Session)] == [None]
    assert await _stop_alerts(Session, quote) == {}
    if not gates_on and sent is not None:
        assert "no stop set; STOP_REACHED cannot fire" in outcome.wrong_side_stop
        assert "fire immediately" not in outcome.wrong_side_stop
    else:
        assert outcome.wrong_side_stop is None


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("instrument", ["stock", "option"])
@pytest.mark.parametrize("sent", [0, -1])
async def test_unset_user_stop_warning_does_not_require_a_checking_quote(
    Session, direction, instrument, sent,
):
    body = _body(**_direction_fields(direction, instrument, sent, scanStockPrice=None))
    async with Session() as db:
        outcome = await create_position(
            body, db, enforce_pre_trade_gates=False, **_fetchers(),
        )
    assert outcome.position.stop is None
    assert "no stop set; STOP_REACHED cannot fire" in outcome.wrong_side_stop
    assert "fire immediately" not in outcome.wrong_side_stop
    assert await _stop_alerts(Session, 120.0) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction, scan, live, sent, stored, structural_sent, structural_stored, gates_on",
    [
        ("Bullish", 100.0, 120.0, 105.0, 125.0, 102.0, 122.0, True),
        ("Bullish", 100.0, 120.0, 105.0, 125.0, 102.0, 122.0, False),
        ("Bullish", 100.0, 120.0, 90.0, 110.0, 95.0, 115.0, True),
        ("Bearish", 100.0, 80.0, 110.0, 90.0, 115.0, 95.0, True),
        ("Bearish", 100.0, 80.0, 95.0, 75.0, 90.0, 70.0, True),
    ],
)
async def test_a_generated_stop_reanchors_and_is_not_direction_checked(
    Session, direction, scan, live, sent, stored, structural_sent, structural_stored, gates_on,
):
    """No stopIsUserSet. Delta is live minus scan. A result on the wrong side
    of the quote (bullish 125 vs 120, bearish 75 vs 80) is still stored, with
    gates on or off, and no wrong-side warning. The re-anchored bullish 110
    is above the client entry 100 and below the quote."""
    body = _body(**_direction_fields(
        direction, "stock", sent, stopIsUserSet=None, scanStockPrice=scan,
        structuralStop=structural_sent,
    ))
    async with Session() as db:
        outcome = await create_position(
            body, db, enforce_pre_trade_gates=gates_on, **_underlying_fetch("stock", live),
        )
    assert outcome.wrong_side_stop is None
    assert (outcome.position.stop, outcome.position.structural_stop) == (stored, structural_stored)
    assert outcome.position.entry_price == live
    breached = (lambda level: live >= level) if direction == "Bearish" else (lambda level: live <= level)
    assert await _stop_alerts(Session, live) == {
        alert_type: level for alert_type, level in (
            ("STOP_REACHED", stored), ("STRUCTURAL_STOP_BREACHED", structural_stored),
        ) if breached(level)
    }


@pytest.mark.asyncio
async def test_an_option_generated_stop_above_the_underlying_is_stored(Session):
    """Underlying quote 120 comes from price_fetcher, not the premium. The
    stored entry stays 8.25. Stop 125 is above both, and is not refused."""
    async with Session() as db:
        outcome = await create_position(
            _body(stop=105.0, structuralStop=102.0, scanStockPrice=100.0, entryPrice=10.45),
            db, **_fetchers(quote={"price": 8.25}, price=120.0),
        )
    assert outcome.wrong_side_stop is None
    assert (outcome.position.stop, outcome.position.structural_stop, outcome.position.entry_price) == (
        125.0, 122.0, 8.25,
    )
    assert await _stop_alerts(Session, 120.0) == {
        "STOP_REACHED": 125.0, "STRUCTURAL_STOP_BREACHED": 122.0,
    }


@pytest.mark.asyncio
async def test_a_user_set_stop_does_not_exempt_the_structural_stop_from_reanchor(Session):
    """Stop 110 is kept (below the quote, above the client entry). Structural
    105 moves by +20 to 125, which is above the quote, and is still stored."""
    body = _body(**_direction_fields(
        "Bullish", "stock", 110.0, structuralStop=105.0,
    ))
    async with Session() as db:
        outcome = await create_position(body, db, **_underlying_fetch("stock", 120.0))
    assert outcome.wrong_side_stop is None
    assert (outcome.position.stop, outcome.position.structural_stop, outcome.position.entry_price) == (
        110.0, 125.0, 120.0,
    )
    assert await _stop_alerts(Session, 120.0) == {"STRUCTURAL_STOP_BREACHED": 125.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("sent", [0, -1])
@pytest.mark.parametrize("instrument", ["stock", "option"])
@pytest.mark.parametrize("gates_on", [True, False])
async def test_generated_unset_stops_stay_null_with_a_positive_reanchor(
    Session, sent, instrument, gates_on,
):
    """Delta +20 cannot turn the unset sentinel into a real main/structural stop."""
    body = _body(**_direction_fields(
        "Bullish", instrument, sent, stopIsUserSet=None, structuralStop=sent,
    ))
    async with Session() as db:
        moved = await create_position(
            body, db, enforce_pre_trade_gates=gates_on, **_underlying_fetch(instrument, 120.0),
        )
    assert moved.wrong_side_stop is None
    assert (moved.position.stop, moved.position.structural_stop) == (None, None)
    assert [(row.stop, row.structural_stop) for row in await _rows(Session)] == [(None, None)]
    # A low quote would breach an incorrectly manufactured 19/20 stop.
    assert await _stop_alerts(Session, 10.0) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("sent", [0, -1])
@pytest.mark.parametrize("instrument", ["stock", "option"])
@pytest.mark.parametrize("gates_on", [True, False])
async def test_stop_required_refuses_generated_unset_even_with_a_positive_delta(
    Session, sent, instrument, gates_on,
):
    body = _body(**_direction_fields(
        "Bullish", instrument, sent, stopIsUserSet=None,
    ))
    with patch(_RISK, return_value=RiskCheckResult(approved=True)) as risk:
        async with Session() as db:
            with pytest.raises(HTTPException) as exc:
                await create_position(
                    body, db, stop_required=True, enforce_pre_trade_gates=gates_on,
                    **_underlying_fetch(instrument, 120.0),
                )
    assert exc.value.status_code == 422
    assert "No usable stop" in exc.value.detail
    risk.assert_not_called()
    assert await _rows(Session) == []
