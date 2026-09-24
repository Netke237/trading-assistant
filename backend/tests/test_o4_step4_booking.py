# backend/tests/test_o4_step4_booking.py
"""O4 steps 4+5 — a fired auto-trade books its position, on both triggers.

Plan: docs/superpowers/plans/2026-09-24-o4-step-4-5-book-the-fired-order-replan.md,
section 4 (the numbers in the test names' docstrings are that section's).

Harness: `test_phase_g_arm_pick.py`'s — the auto-trade router on its own app
over an in-memory aiosqlite db, `_market_is_open` and `execute_option_order`
patched, the singleton disarmed in `finally`. Additionally `_apply_vol_sizing`
is identity (except where a test sizes), and the three fetchers are patched ON
`app.services.auto_trade_booking` (the names it passes explicitly), so nothing
reaches the network.

THE ALERT IS OBSERVED AT ITS FAR END: `alert_notifier.notify_alert`, reached
through the real `asyncio.to_thread` + `asyncio.run` inside `_alert_refusal`.
A test that only asserted `_alert_refusal` was called would pass against a
direct call from the event loop, which `_alert_refusal`'s running-loop guard
silently drops. `return_value=True` and a patched `forget_alerts` keep the
discrete-alert cleanup off the real dedup file (re-plan section 8, item 4).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.data.ibkr_paper import OrderResult
from app.database import Base, get_db
from app.models.audit_event import AuditEventModel
from app.models.portfolio import PortfolioPositionModel
from app.routers.auto_trade import ArmRequest, router as auto_trade_router
from app.services import auto_trade_booking as atb
from app.services.auto_trader import (
    ArmedStrategy, AutoTradeService, FiredOrder, auto_trader,
)
from app.services.picked_method import seed_tp_from_pick
from app.services.config_loader import load_exit_plan_cfg
from app.services.portfolio_risk import RiskCheckResult
from app.services.position_writer import create_position
from app.services.scheduling_tz import MARKET_TZ

CONTRACT = "AAPL|185|2026-12-18|C"
STOCK_TARGET = 197.50

PICK = {
    "picked_method":           "monte_carlo",
    "picked_row_stock_price":  STOCK_TARGET,
    "picked_row_option_price": 6.24,
    "picked_stop_basis":       "premium",
    "picked_at":               "2026-09-15T09:30:00Z",
}

EXIT_PLAN = {
    "finalStop": 180.0,
    "targets": [
        {"rrRatio": 2.0, "price": STOCK_TARGET},
        {"rrRatio": 3.0, "price": 205.0},
    ],
}
TARGETS = [{"label": "T1", "stockPrice": 196.0, "targetPrice": 3.5}]


def _arm_body(**extra) -> dict:
    base = {
        "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": CONTRACT,
        "action": "BUY", "direction": "Bullish", "horizon": "Swing",
        "quantity": 1, "order_type": "LMT", "limit_price": 2.50, "entry_premium": 2.50,
        "premium_stop_pct": 0.40,
        "stop": 180.0, "stop_is_user_set": False, "scan_stock_price": 190.0,
        "structural_stop": 178.0, "exit_plan": EXIT_PLAN, "targets": TARGETS,
        "dte_total": 45, "max_loss_override": {"dollars": 300.0},
        **PICK,
    }
    base.update(extra)
    return base


def _strategy(**extra) -> ArmedStrategy:
    body = _arm_body(**extra)
    body["broker"] = "ibkr_paper"
    body.setdefault("conid", None)
    return ArmedStrategy(**ArmRequest(**body).model_dump())


def _fired(result: OrderResult | None = None, **extra) -> FiredOrder:
    return FiredOrder(
        result=result or OrderResult("777", "Submitted", "ibkr_paper"),
        strategy=_strategy(**extra),
        attempt_id="attempt-direct",
    )


@pytest_asyncio.fixture
async def engine_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, Session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(engine_and_session) -> AsyncGenerator[AsyncClient, None]:
    """ALWAYS DISARMS ON THE WAY OUT -- `auto_trader` is a shared singleton."""
    _, Session = engine_and_session

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(auto_trade_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        try:
            yield c
        finally:
            auto_trader.disarm()


@pytest.fixture
def env(mocker, monkeypatch):
    """The broker, the sizing, the fetchers and the notifier, all stubbed.

    The singleton's history is swapped for an empty list (restored after):
    every success row carries `premium_at_risk`, and `fire()`'s daily-loss
    breaker sums today's, so rows left by earlier tests would trip it.
    """
    import app.services.auto_trader as at
    monkeypatch.setattr(auto_trader._state, "history", [])
    mocker.patch.object(at, "_market_is_open", return_value=True)
    execute = mocker.patch.object(
        at, "execute_option_order",
        return_value=OrderResult("888", "PreSubmitted", "tastytrade_paper"),
    )
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    quote = mocker.patch.object(atb, "fetch_contract_quote_async",
                                AsyncMock(return_value=None))
    price = mocker.patch.object(atb, "fetch_price_async", AsyncMock(return_value=None))
    notify = mocker.patch("app.services.notifications.alert_notifier.notify_alert",
                          AsyncMock(return_value=True))
    forget = mocker.patch("app.services.notifications.alert_notifier.forget_alerts")
    mocker.patch("app.services.audit.log_event")  # keep off the repo's audit.log
    return SimpleNamespace(execute=execute, quote=quote, price=price,
                           notify=notify, forget=forget)


async def _rows(Session) -> list[PortfolioPositionModel]:
    async with Session() as s:
        return (await s.execute(select(PortfolioPositionModel))).scalars().all()


async def _arm_and_fire(client, **extra):
    arm = await client.post("/auto-trade/arm", json=_arm_body(**extra))
    assert arm.status_code == 200, arm.text
    return await client.post("/auto-trade/fire")


def _alert_types(notify) -> list[str]:
    return [c.kwargs["alert_type"] for c in notify.await_args_list]


# ── 1-5: what a booking writes ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fire_now_books_one_position_from_the_armed_values(
    client, engine_and_session, env,
):
    """1. Replaces Phase G's tripwire: the booked row carries the ARMED pick."""
    _, Session = engine_and_session
    resp = await _arm_and_fire(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["order_id"] == "888" and data["booked"] is True
    assert data["book_error"] is None and data["over_exposure"] is False
    assert data["rec_id"].startswith("REC-AT-")

    [row] = await _rows(Session)
    assert row.rec_id == data["rec_id"]
    assert row.contract == CONTRACT and row.symbol == "AAPL"
    assert row.direction == "Bullish" and row.qty == 1
    assert row.entry_price == 2.50
    assert row.entry_date == datetime.now(MARKET_TZ).date().isoformat()
    assert row.stop == 180.0 and row.structural_stop == 178.0
    assert row.exit_plan == EXIT_PLAN and row.targets == TARGETS
    assert row.dte_total == 45 and row.max_loss_override == {"dollars": 300.0}
    assert row.premium_stop_pct == 0.40
    for k, v in PICK.items():
        assert getattr(row, k) == v, k
    expected = seed_tp_from_pick(
        PICK["picked_method"], STOCK_TARGET, exit_plan=EXIT_PLAN,
        rr_ratios=load_exit_plan_cfg().get("target", {}).get("rr_ratios"),
    )
    assert (row.active_tp_method, row.resolved_tp_price) == tuple(expected)
    assert tuple(expected) != ("ladder", None), "the fixture must seed a real pick"

    last = auto_trader.get_state().history[-1]
    assert last["rec_id"] == data["rec_id"]
    env.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_booked_qty_is_the_post_sizing_qty(client, engine_and_session, env, mocker):
    """2."""
    import app.services.auto_trader as at
    mocker.patch.object(at, "_apply_vol_sizing",
                        lambda s: dataclasses.replace(s, quantity=2))
    _, Session = engine_and_session
    resp = await _arm_and_fire(client, quantity=4)
    assert resp.json()["booked"] is True
    [row] = await _rows(Session)
    assert row.qty == 2
    assert env.execute.call_args.args[0].quantity == 2


@pytest.mark.asyncio
async def test_a_live_quote_replaces_the_armed_entry(client, engine_and_session, env):
    """3."""
    env.quote.return_value = {"price": 3.10}
    _, Session = engine_and_session
    await _arm_and_fire(client)
    [row] = await _rows(Session)
    assert row.entry_price == 3.10


@pytest.mark.asyncio
@pytest.mark.parametrize("user_set, stored", [(False, 185.0), (True, 180.0)])
async def test_the_stop_re_anchors_per_stop_is_user_set(
    client, engine_and_session, env, user_set, stored,
):
    """4. Live 195 against a scan of 190: a plan stop moves by +5, a typed one does not."""
    env.price.return_value = 195.0
    _, Session = engine_and_session
    resp = await _arm_and_fire(client, stop_is_user_set=user_set)
    assert resp.json()["booked"] is True, resp.text
    [row] = await _rows(Session)
    assert row.stop == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("extra, stored", [
    ({"premium_stop_dollar": 1.00}, 0.50),
    ({}, 0.40),
])
async def test_the_premium_stop_is_derived_against_the_persisted_entry(
    client, engine_and_session, env, extra, stored,
):
    """5. Dollar 1.00 over a live 2.00 is 0.50, not 1.00 / 2.50 = 0.40."""
    env.quote.return_value = {"price": 2.00}
    _, Session = engine_and_session
    await _arm_and_fire(client, **extra)
    [row] = await _rows(Session)
    assert row.entry_price == 2.00
    assert row.premium_stop_pct == pytest.approx(stored)


# ── 6-8: refusals ─────────────────────────────────────────────────────────

_REFUSALS = {
    "no stop":            ({"stop": None}, None),
    "stop re-anchored <= 0": ({"stop": 5.0, "structural_stop": None}, ("price", 150.0)),
    "OCC-form contract":  ({"option_symbol": "AAPL261218C00185000"}, None),
    "symbol mismatch":    ({"option_symbol": "MSFT|185|2026-12-18|C"}, None),
    "right vs direction": ({"option_symbol": "AAPL|185|2026-12-18|P"}, None),
    "order id ''":        ({}, ("order", OrderResult("", "Submitted", "ibkr_paper"))),
    "order id None":      ({}, ("order", OrderResult(None, "Submitted", "ibkr_paper"))),
    "order id unknown":   ({}, ("order", OrderResult("unknown", "accepted", "alpaca_paper"))),
    **{
        f"status {st}": ({}, ("order", OrderResult("555", st, "ibkr_paper")))
        for st in ("Inactive", "rejected", "error", "canceled", "Cancelled",
                   "Expired", "Rejected")
    },
    "create_position raises":       ({}, ("patch", "create_position")),
    "PortfolioPositionCreate raises": ({}, ("patch", "PortfolioPositionCreate")),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(_REFUSALS))
async def test_each_refusal_books_nothing_answers_200_and_pages(
    client, engine_and_session, env, mocker, case,
):
    """6 (and 11: the page is asserted on `notify_alert` itself)."""
    extra, how = _REFUSALS[case]
    order = OrderResult("888", "PreSubmitted", "tastytrade_paper")
    if how and how[0] == "price":
        env.price.return_value = how[1]
    elif how and how[0] == "order":
        order = how[1]
        env.execute.return_value = order
    elif how and how[1] == "create_position":
        mocker.patch.object(atb, "create_position",
                            AsyncMock(side_effect=RuntimeError("db down")))
    elif how:
        mocker.patch.object(atb, "PortfolioPositionCreate",
                            side_effect=ValueError("bad body"))
    _, Session = engine_and_session

    resp = await _arm_and_fire(client, **extra)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["booked"] is False and data["rec_id"] is None
    if order.order_id in (None, ""):
        assert "no order id" in data["book_error"]
    else:
        assert str(order.order_id) in data["book_error"]
    assert await _rows(Session) == []
    assert _alert_types(env.notify) == ["AUTO_TRADE_NOT_BOOKED"]
    kwargs = env.notify.await_args.kwargs
    assert kwargs["rec_id"] == "auto-trade-not-booked:AAPL"
    assert "rec_id" not in auto_trader.get_state().history[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["some_new_broker_value", "PreSubmitted"])
async def test_an_unknown_status_books(client, engine_and_session, env, status):
    """7. Refusal 2 is a rejection list, not an allowlist."""
    env.execute.return_value = OrderResult("901", status, "ibkr_paper")
    _, Session = engine_and_session
    resp = await _arm_and_fire(client)
    assert resp.json()["booked"] is True
    assert len(await _rows(Session)) == 1


@pytest.mark.asyncio
async def test_a_duplicate_contract_is_refused_and_leaves_the_session_usable(
    engine_and_session, env,
):
    """8."""
    _, Session = engine_and_session
    async with Session() as s:
        first = await atb.book_fired_order(_fired(), s)
        assert first.booked is True
        second = await atb.book_fired_order(
            _fired(OrderResult("778", "Submitted", "ibkr_paper")), s)
        assert second.booked is False
        assert "778" in second.error and "already exists" in second.error
        # The rollback left the session usable.
        n = (await s.execute(select(func.count(PortfolioPositionModel.id)))).scalar_one()
    assert n == 1
    assert _alert_types(env.notify) == ["AUTO_TRADE_NOT_BOOKED"]


# ── 9-10: over the cap, and the audit record ──────────────────────────────

@pytest.mark.asyncio
async def test_over_the_cap_books_the_ordered_qty_and_says_so(
    client, engine_and_session, env, mocker,
):
    """9. The writer's check refuses; fire()'s own (lazily imported) one approves."""
    mocker.patch("app.services.position_writer.check_position_risk",
                 return_value=RiskCheckResult(approved=False,
                                              reasons=["max concurrent positions"],
                                              adjusted_size=None))
    _, Session = engine_and_session
    resp = await _arm_and_fire(client, quantity=3)
    data = resp.json()
    assert data["booked"] is True and data["over_exposure"] is True
    [row] = await _rows(Session)
    assert row.qty == 3
    assert _alert_types(env.notify) == ["AUTO_TRADE_BOOKED_OVER_EXPOSURE"]
    assert env.notify.await_args.kwargs["rec_id"] == "auto-trade-over-exposure:AAPL"


@pytest.mark.asyncio
async def test_the_audit_record_is_written_and_its_failure_does_not_unbook(
    engine_and_session, env, mocker,
):
    """10."""
    _, Session = engine_and_session
    snap = {"card": "AAPL 185C", "score": 81}
    async with Session() as s:
        out = await atb.book_fired_order(_fired(trade_card_snapshot=snap), s)
        assert out.booked is True
        events = (await s.execute(
            select(AuditEventModel).where(AuditEventModel.rec_id == out.rec_id)
        )).scalars().all()
    assert len(events) == 1 and events[0].payload == snap

    mocker.patch.object(atb, "log_approval", AsyncMock(side_effect=RuntimeError("disk")))
    async with Session() as s:
        out = await atb.book_fired_order(
            _fired(OrderResult("779", "Submitted", "ibkr_paper"),
                   option_symbol="AAPL|190|2026-12-18|C", trade_card_snapshot=snap), s)
        assert out.booked is True
        n = (await s.execute(select(func.count(PortfolioPositionModel.id)))).scalar_one()
    assert n == 2


# ── 12-15: the pieces ─────────────────────────────────────────────────────

def test_record_booking_stamps_only_the_matching_row_with_a_new_dict():
    """12."""
    svc = AutoTradeService()
    target = {"attempt_id": "a1", "status": "PreSubmitted"}
    other = {"attempt_id": "a2", "status": "Submitted"}
    svc._state.history.extend([target, other])

    assert svc.record_booking("a1", "REC-AT-1") is True
    h = svc.get_state().history
    assert h[0] == {**target, "rec_id": "REC-AT-1"}
    assert h[0] is not target and "rec_id" not in target
    assert h[1] is other and "rec_id" not in other
    assert svc.record_booking("missing", "REC-AT-2") is False


def test_the_arms_boundary_values_survive_the_create_schema():
    """13. The smallest values ArmRequest accepts build a PortfolioPositionCreate."""
    tiny = 1e-6
    fired = _fired(
        stop=tiny, scan_stock_price=tiny, structural_stop=tiny, dte_total=0,
        premium_stop_dollar=tiny, premium_stop_pct=tiny, entry_premium=tiny,
        picked_row_stock_price=tiny, picked_row_option_price=tiny,
        exit_plan={}, targets=[], max_loss_override={}, trade_card_snapshot={},
        stop_is_user_set=True,
    )
    body = atb._build_body(fired, "REC-AT-0")
    assert body.stop == tiny and body.dteTotal == 0
    high = _fired(premium_stop_pct=1 - 1e-9)
    assert atb._build_body(high, "REC-AT-1").premiumStopPct == 1 - 1e-9


def test_the_containers_are_copied_not_shared():
    """14. Nested too: pydantic copies the outer dict, not what is inside it."""
    fired = _fired()
    body = atb._build_body(fired, "REC-AT-0")
    s = fired.strategy
    assert body.exitPlan == s.exit_plan and body.exitPlan is not s.exit_plan
    assert body.exitPlan["targets"] is not s.exit_plan["targets"]
    assert body.targets == s.targets and body.targets[0] is not s.targets[0]
    assert body.maxLossOverride == s.max_loss_override
    assert body.maxLossOverride is not s.max_loss_override


@pytest.mark.asyncio
async def test_book_fired_order_never_raises_and_a_post_commit_fault_stays_booked(
    engine_and_session, env, mocker,
):
    """15 (with build rule 1: once the commit has returned, booked=True)."""
    import app.services.auto_trader as at
    mocker.patch.object(at.auto_trader, "record_booking", side_effect=RuntimeError("x"))
    mocker.patch.object(atb, "_alert_over_exposure", AsyncMock(side_effect=RuntimeError("y")))
    mocker.patch("app.services.position_writer.check_position_risk",
                 return_value=RiskCheckResult(approved=False, reasons=["cap"]))
    _, Session = engine_and_session
    async with Session() as s:
        out = await atb.book_fired_order(_fired(), s)
    assert out.booked is True and out.rec_id and out.over_exposure is True
    assert len(await _rows(Session)) == 1
    env.notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refusal_whose_alert_also_fails_still_returns(engine_and_session, env, mocker):
    """15, the refusal side: the thread hop failing is logged, not raised."""
    mocker.patch.object(atb.asyncio, "to_thread", AsyncMock(side_effect=RuntimeError("z")))
    _, Session = engine_and_session
    async with Session() as s:
        out = await atb.book_fired_order(_fired(stop=None), s)
    assert out.booked is False and "777" in out.error


# ── 16: the return values ─────────────────────────────────────────────────

def test_fire_returns_a_fired_order_and_maybe_fire_on_scan_passes_it_on(env, mocker):
    """16."""
    import app.services.auto_trader as at
    mocker.patch.object(at, "_apply_vol_sizing",
                        lambda s: dataclasses.replace(s, quantity=1))
    svc = AutoTradeService()
    armed = _strategy(quantity=3)
    svc.arm(armed)
    fired = svc.fire(attempt_id="a-16")
    assert isinstance(fired, FiredOrder)
    assert fired.strategy.quantity == 1 and fired.strategy is not armed
    assert fired.attempt_id == "a-16"
    assert svc.get_state().history[-1]["attempt_id"] == "a-16"

    svc.arm(_strategy())
    via_scan = svc.maybe_fire_on_scan()
    assert isinstance(via_scan, FiredOrder)
    assert via_scan.attempt_id == svc.get_state().history[-1]["attempt_id"]

    assert svc.maybe_fire_on_scan() is None                    # not armed

    svc.arm(dataclasses.replace(
        _strategy(), armed_at=datetime.now(timezone.utc) - timedelta(days=1)))
    assert svc.maybe_fire_on_scan() is None                    # stale

    env.execute.side_effect = RuntimeError("broker down")
    svc.arm(_strategy())
    assert svc.maybe_fire_on_scan() is None                    # a refusal


# ── 17: the scan path ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("write_fails", [False, True])
async def test_the_scan_trigger_books_and_still_persists_its_session(
    engine_and_session, env, mocker, monkeypatch, write_fails,
):
    """17. Real singleton, real session; `_upsert_session` is reached either way."""
    import app.routers.scan as scan_module
    from app.schemas import ScanRequest

    result = SimpleNamespace(scan_id="REC-S",
                             candidates=[SimpleNamespace(finalStatus="PASS")])
    monkeypatch.setattr(scan_module, "_execute_scan_core",
                        AsyncMock(return_value=result))
    upsert = AsyncMock()
    monkeypatch.setattr(scan_module, "_upsert_session", upsert)
    monkeypatch.setattr(scan_module, "_last_request", None)
    monkeypatch.setattr(scan_module, "_last_result", None)
    if write_fails:
        mocker.patch.object(atb, "create_position",
                            AsyncMock(side_effect=RuntimeError("db down")))
    _, Session = engine_and_session
    req = ScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing")

    auto_trader.arm(_strategy())
    try:
        async with Session() as s:
            out = await scan_module.run_scan(req, s)
    finally:
        auto_trader.disarm()

    assert out is result
    upsert.assert_awaited_once()
    rows = await _rows(Session)
    if write_fails:
        assert rows == []
        assert _alert_types(env.notify) == ["AUTO_TRADE_NOT_BOOKED"]
    else:
        [row] = rows
        assert row.contract == CONTRACT and row.stop == 180.0
        assert row.picked_method == "monte_carlo"
        assert auto_trader.get_state().history[-1]["rec_id"] == row.rec_id
        env.notify.assert_not_awaited()


# ── 18: stop_required, directly ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_required_refuses_a_stopless_body_and_is_off_by_default(
    engine_and_session,
):
    """18. Fetchers passed explicitly (step 1's open question)."""
    from fastapi import HTTPException
    _, Session = engine_and_session
    body = atb._build_body(_fired(stop=None), "REC-AT-18")
    none = AsyncMock(return_value=None)
    kw = dict(quote_fetcher=none, price_fetcher=none,
              exit_plan_cfg_loader=lambda: {})

    async with Session() as s:
        with pytest.raises(HTTPException) as ei:
            await create_position(body, s, stop_required=True, **kw)
    assert ei.value.status_code == 422
    assert await _rows(Session) == []

    async with Session() as s:
        out = await create_position(body, s, **kw)
    assert out.position.stop is None
    assert len(await _rows(Session)) == 1
