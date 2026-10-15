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
        "action": "BUY", "direction": "Bullish", "horizon": "Swing", "hold_max_days": 15,
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
        # P1a: the duplicate-contract refusal names its own remedy.
        assert "778" in second.error and "already open" in second.error
        assert "Close the extra 1 at the broker" in second.error
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
    # P1a (O4 residual item 4): the list itself and the nested snapshot too.
    assert body.targets is not s.targets
    nested = _fired(trade_card_snapshot={"card": {"score": 81}})
    nb = atb._build_body(nested, "REC-AT-1")
    snap = nested.strategy.trade_card_snapshot
    assert nb.tradeCardSnapshot == snap and nb.tradeCardSnapshot["card"] is not snap["card"]


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



# ── P1a: Q12 page, post-commit recovery, 409 text, residual pins ──────────

import logging  # noqa: E402



def _fired_with(fired: FiredOrder, **strategy_changes) -> FiredOrder:
    return dataclasses.replace(
        fired, strategy=dataclasses.replace(fired.strategy, **strategy_changes))


@pytest.mark.asyncio
async def test_p1a_14_a_gates_off_wrong_side_user_stop_pages_and_stays_booked(
    engine_and_session, env,
):
    """Q12: a user stop of 190 on a bullish trade with the underlying at 185."""
    env.price.return_value = 185.0
    _, Session = engine_and_session
    async with Session() as s:
        out = await atb.book_fired_order(_fired(stop=190.0, stop_is_user_set=True), s)
    assert out.booked is True and out.wrong_side_stop is True
    [row] = await _rows(Session)
    assert row.stop == 190.0
    assert "AUTO_TRADE_BOOKED_WRONG_SIDE_STOP" in _alert_types(env.notify)
    call = next(c for c in env.notify.await_args_list
                if c.kwargs["alert_type"] == "AUTO_TRADE_BOOKED_WRONG_SIDE_STOP")
    assert call.kwargs["rec_id"] == "auto-trade-wrong-side-stop:AAPL"
    assert out.rec_id in call.kwargs["reason"] and "wrong side" in call.kwargs["reason"]
    assert "it would fire immediately" in call.kwargs["reason"]
    assert "It will fire STOP_REACHED" not in call.kwargs["reason"]
    assert "verify the stop in Portfolio" in call.kwargs["reason"]


@pytest.mark.asyncio
async def test_booking_stop_warning_composition_preserves_an_unset_warning(
    engine_and_session, env,
):
    """The existing paging wrapper must not promise an alert for persisted NULL.

    Auto-booking requires a stop; its shared warning wrapper can nevertheless
    receive the writer's gates-off warning, so exercise that composition with
    a real committed row and real writer detail.
    """
    _, Session = engine_and_session
    fired = _fired()
    body = atb._build_body(fired, "REC-UNSET-WARNING").model_copy(update={
        "stop": 0.0, "stopIsUserSet": True,
    })
    async with Session() as s:
        outcome = await create_position(
            body, s, enforce_pre_trade_gates=False,
            quote_fetcher=env.quote, price_fetcher=env.price,
            exit_plan_cfg_loader=lambda: {},
        )
    [row] = await _rows(Session)
    assert row.stop is None
    assert outcome.wrong_side_stop is not None
    await atb._alert_wrong_side_stop(fired, row.rec_id, outcome.wrong_side_stop)
    assert _alert_types(env.notify) == ["AUTO_TRADE_BOOKED_WRONG_SIDE_STOP"]
    call = env.notify.await_args
    assert call.kwargs["rec_id"] == "auto-trade-wrong-side-stop:AAPL"
    assert "no stop set; STOP_REACHED cannot fire" in call.kwargs["reason"]
    assert "It will fire" not in call.kwargs["reason"]
    assert "with a stop on the wrong side" not in call.kwargs["reason"]
    assert "verify the stop in Portfolio" in call.kwargs["reason"]


async def _commit_then_fail(body, db, **kw):
    await create_position(body, db, **kw)
    raise RuntimeError("post-commit failure")


@pytest.mark.asyncio
async def test_p1a_15_a_fault_after_the_writers_commit_is_booked_and_pages_unverified(
    engine_and_session, env, mocker,
):
    """15 + 15b. A NON-HTTP exception after the commit: the row is found by its
    rec_id, so the order is booked, and the lost flags are paged."""
    mocker.patch.object(atb, "create_position", _commit_then_fail)
    _, Session = engine_and_session
    async with Session() as s:
        out = await atb.book_fired_order(_fired(), s)
    [row] = await _rows(Session)
    assert out.booked is True and out.rec_id == row.rec_id and out.error is None
    assert _alert_types(env.notify) == ["AUTO_TRADE_BOOKED_UNVERIFIED"]
    kw = env.notify.await_args.kwargs
    assert kw["rec_id"] == "auto-trade-booked-unverified:AAPL"
    assert row.rec_id in kw["reason"] and "NOT checked" in kw["reason"]


@pytest.mark.asyncio
async def test_p1a_16_the_duplicate_contract_page_names_its_own_remedy(
    engine_and_session, env,
):
    _, Session = engine_and_session
    async with Session() as s:
        assert (await atb.book_fired_order(_fired(), s)).booked is True
        env.notify.reset_mock()
        second = await atb.book_fired_order(
            _fired(OrderResult("778", "Submitted", "ibkr_paper"), quantity=3), s)
    assert second.booked is False
    assert _alert_types(env.notify) == ["AUTO_TRADE_NOT_BOOKED"]
    text = env.notify.await_args.kwargs["reason"]
    assert text.startswith(f"Order 778 for {CONTRACT}: ")
    assert "NOT booked as a second row" in text
    assert "Close the extra 3 at the broker" in text
    # Code round 1: raising the existing row's Contracts would store the added
    # lot at that row's entry price, so it must never be offered as a remedy.
    assert "raise that position's Contracts by" not in text
    assert "Do not raise that position's Contracts" in text
    assert "Add it by hand" not in text
    rest = text.replace(CONTRACT, "").replace("Order 778", "")
    assert [ch for ch in rest if ch.isdigit()] == ["3", "3"], "no number but {qty}"


@pytest.mark.parametrize("option_symbol", ["AAPL|185|20261218|C", "AAPL|185|2026-13-40|C"])
def test_p1a_17_an_unusable_expiry_is_refused(option_symbol):
    with pytest.raises(atb._Refused) as exc:
        atb._check_refusals(_fired_with(_fired(), option_symbol=option_symbol))
    assert "no usable expiry" in exc.value.reason


@pytest.mark.parametrize("strike", ["0", "abc", "inf"])
def test_p1a_17_an_unusable_strike_is_refused(strike):
    with pytest.raises(atb._Refused) as exc:
        atb._check_refusals(_fired_with(_fired(), option_symbol=f"AAPL|{strike}|2026-12-18|C"))
    assert "no usable strike" in exc.value.reason


def test_p1a_17_a_dotted_symbol_still_passes_the_expiry_check():
    fired = _fired_with(_fired(), symbol="BRK.B", option_symbol="BRK.B|185|2026-12-18|C")
    atb._check_refusals(fired)  # does not raise


def test_p1a_17_refusal_5_no_entry_premium():
    with pytest.raises(atb._Refused) as exc:
        atb._check_refusals(_fired_with(_fired(), entry_premium=0.0))
    assert "no entry premium" in exc.value.reason


def test_p1a_18_a_whitespace_order_id_reads_as_no_order_id():
    fired = _fired(OrderResult("  ", "Submitted", "ibkr_paper"))
    assert atb._order_label(fired) == "an order with no order id"
    with pytest.raises(atb._Refused):
        atb._check_refusals(fired)


@pytest.mark.asyncio
async def test_p1a_19a_a_failed_write_is_rolled_back_before_anything_else(
    engine_and_session, env, mocker, caplog,
):
    """A real IntegrityError (a duplicate rec_id) leaves the session in
    pending-rollback. The write `except` rolls it back FIRST, so the recovery
    lookup runs on a usable session and the caller can SELECT afterwards."""
    _, Session = engine_and_session
    async with Session() as s:
        first = await atb.book_fired_order(_fired(), s)
    assert first.booked is True

    async def collide(body, db, **kw):
        db.add(PortfolioPositionModel(
            rec_id=first.rec_id, symbol="AAPL", contract="AAPL|999|2026-12-18|C",
            direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-09-15"))
        await db.flush()

    mocker.patch.object(atb, "create_position", collide)
    with caplog.at_level(logging.ERROR, "app.services.auto_trade_booking"):
        async with Session() as s:
            out = await atb.book_fired_order(
                _fired(OrderResult("779", "Submitted", "ibkr_paper")), s)
            n = (await s.execute(select(func.count(PortfolioPositionModel.id)))).scalar_one()
    assert out.booked is False and n == 1
    assert not any("could not check whether" in m for m in caplog.messages), (
        "the recovery lookup ran on a session that was not rolled back")


@pytest.mark.asyncio
async def test_p1a_19b_a_failed_audit_record_is_rolled_back_and_the_row_stays(
    engine_and_session, env, mocker,
):
    _, Session = engine_and_session
    snap = {"card": "AAPL 185C"}
    async with Session() as s:
        first = await atb.book_fired_order(_fired(trade_card_snapshot=snap), s)
        event_id = (await s.execute(select(AuditEventModel.id))).scalar_one()
    assert first.booked is True

    async def dup_audit(rec_id, payload, db):
        db.add(AuditEventModel(id=event_id, event_type="approval", rec_id=rec_id,
                               recommendation_id=rec_id, payload=payload))
        await db.flush()

    mocker.patch.object(atb, "log_approval", dup_audit)
    async with Session() as s:
        out = await atb.book_fired_order(
            _fired(OrderResult("779", "Submitted", "ibkr_paper"),
                   option_symbol="AAPL|190|2026-12-18|C", trade_card_snapshot=snap), s)
        rows = (await s.execute(select(PortfolioPositionModel.rec_id))).scalars().all()
    assert out.booked is True
    assert sorted(rows) == sorted([first.rec_id, out.rec_id])


def test_p1a_20_the_entry_date_is_the_market_date_not_utc(mocker):
    real = datetime

    class _Frozen(real):
        @classmethod
        def now(cls, tz=None):
            t = real(2026, 9, 16, 1, 30, tzinfo=timezone.utc)   # 21:30 ET on the 15th
            return t.astimezone(tz) if tz else t

    mocker.patch.object(atb, "datetime", _Frozen)
    assert atb._build_body(_fired(), "REC-AT-0").entryDate == "2026-09-15"


@pytest.mark.asyncio
async def test_p1a_22_every_booking_page_is_discrete(engine_and_session, env, mocker):
    import app.services.auto_trader as at
    spy = mocker.patch.object(at, "_alert_refusal")
    _, Session = engine_and_session
    async with Session() as s:
        await atb.book_fired_order(_fired(stop=None), s)
    assert spy.call_count == 1
    assert spy.call_args.kwargs == {"discrete": True}


# ── PREMIUM-STOP-FALLBACK-ALIGN: an unapplied dollar stop pages ───────────

@pytest.mark.asyncio
async def test_an_armed_dollar_stop_at_or_above_the_fill_pages_and_keeps_the_arm_fraction(
    engine_and_session, env,
):
    """Armed at $2.50 with a $2.25 stop (90%), filled at $2.00: $2.25 is a
    total loss there, so the arm-time 0.90 is stored and the booking pages."""
    env.quote.return_value = {"price": 2.00}
    _, Session = engine_and_session
    fired = _fired(premium_stop_dollar=2.25, premium_stop_pct=0.90)
    async with Session() as s:
        out = await atb.book_fired_order(fired, s)
    assert out.booked is True and out.premium_stop_unapplied is True
    [row] = await _rows(Session)
    assert row.entry_price == 2.00
    assert row.premium_stop_pct == pytest.approx(0.90)
    call = next(c for c in env.notify.await_args_list
                if c.kwargs["alert_type"] == "AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED")
    assert call.kwargs["rec_id"] == "auto-trade-premium-stop-unapplied:AAPL"
    reason = call.kwargs["reason"]
    assert out.rec_id in reason and "$2.25" in reason and "$2.00" in reason
    assert "total loss" in reason and "90.00%" in reason


@pytest.mark.asyncio
async def test_an_applied_dollar_stop_does_not_page_unapplied(engine_and_session, env):
    env.quote.return_value = {"price": 2.00}
    _, Session = engine_and_session
    async with Session() as s:
        out = await atb.book_fired_order(_fired(premium_stop_dollar=1.00), s)
    assert out.booked is True and out.premium_stop_unapplied is False
    assert "AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED" not in _alert_types(env.notify)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry, dollar, pct, stored, why, kept", [
    # total loss at the entry, client fraction kept
    (2.00, 2.25, 0.90, 0.90, "total loss", "90.00%"),
    # total loss, no client fraction: inherits the global
    (2.00, 2.25, None, None, "total loss", "inherits the global"),
    # the dollar's ratio is sub-cent at the entry ($0.03 - $0.025 < $0.01)
    (0.03, 0.025, None, None, "below $0.01", "inherits the global"),
])
async def test_the_writer_reports_an_unapplied_dollar_stop(
    engine_and_session, entry, dollar, pct, stored, why, kept,
):
    _, Session = engine_and_session
    body = atb._build_body(
        _fired(entry_premium=entry, premium_stop_dollar=dollar, premium_stop_pct=pct),
        "REC-AT-PS",
    )
    none = AsyncMock(return_value=None)
    async with Session() as s:
        out = await create_position(body, s, quote_fetcher=none, price_fetcher=none,
                                    exit_plan_cfg_loader=lambda: {})
    assert out.position.premium_stop_pct == (pytest.approx(stored) if stored else None)
    assert out.premium_stop_unapplied is not None
    assert why in out.premium_stop_unapplied and kept in out.premium_stop_unapplied


@pytest.mark.asyncio
async def test_the_writer_reports_nothing_when_the_dollar_applies_or_is_absent(engine_and_session):
    _, Session = engine_and_session
    none = AsyncMock(return_value=None)
    kw = dict(quote_fetcher=none, price_fetcher=none, exit_plan_cfg_loader=lambda: {})
    async with Session() as s:
        out = await create_position(
            atb._build_body(_fired(premium_stop_dollar=1.00), "REC-AT-A"), s, **kw)
    assert out.position.premium_stop_pct == pytest.approx(0.40)
    assert out.premium_stop_unapplied is None
    async with Session() as s:
        await s.execute(PortfolioPositionModel.__table__.delete())
        await s.commit()
        out = await create_position(atb._build_body(_fired(), "REC-AT-B"), s, **kw)
    assert out.premium_stop_unapplied is None
