# backend/tests/test_phase_g_arm_pick.py
"""Phase G (piece 5) — build step 5, arming.

The spec's §10 test 6: `/auto-trade/arm` carries the pick onto `ArmedStrategy`.
Its sibling file `test_phase_g_method_pick.py` covers tests 1-5 (the CREATE path)
and says in its own docstring that test 6 "belongs with build step 5 and lands
with it, not here" — this is that landing.

WHAT THIS STEP DOES, IN ONE LINE: `ArmRequest` gains the same five `picked_*`
fields `PortfolioPositionCreate` has, flowing into `ArmedStrategy` through the
existing `ArmedStrategy(**req.model_dump())`. The order is unchanged — nothing
submitted to any broker depends on the method (§8). The fields TRAVEL.

TEST 6'S SECOND HALF IS NOT DELIVERABLE AS WRITTEN, and that is recorded here
rather than quietly dropped. It reads "`fire_now()` creates a position carrying
the armed pick, not a live one" — but the auto-trade fire path creates NO
`PortfolioPosition` at all today. That is a pre-existing, separately documented
limitation (CLAUDE.md's integrations table; `phase_g_send_path_wiring_followups`
calls it O4 and puts it explicitly out of scope), not something this step
introduced and not something it closes. So the half that IS deliverable —
"carrying the armed pick, NOT A LIVE ONE" — is tested at the only place the
distinction is observable today: the strategy handed to the broker executor
(`test_the_pick_that_reaches_the_executor_is_the_one_that_was_armed`). And the
gap itself gets a tripwire
(`test_firing_still_creates_no_position_so_the_armed_pick_is_captured_and_unread`)
that fails the day someone wires position creation into the fire path, so
whoever does it is told, by a failing test, that five armed fields are sitting
there waiting to be written.
"""
from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.auto_trade import router as auto_trade_router
from app.services.auto_trader import AutoTradeService, ArmedStrategy, auto_trader

# The same two numbers `test_phase_g_method_pick.py` uses, and for the same
# reason: a $197.50 underlying and a $6.24 premium are far enough apart that a
# units mix-up shows up in the assertion instead of hiding in a plausible value.
STOCK_TARGET = 197.50
OPTION_TARGET = 6.24

PICK = {
    "picked_method":           "monte_carlo",
    "picked_row_stock_price":  STOCK_TARGET,
    "picked_row_option_price": OPTION_TARGET,
    "picked_stop_basis":       "premium",
    "picked_at":               "2026-09-15T09:30:00Z",
}


def _arm_body(**extra) -> dict:
    base = {
        "broker": "tastytrade_paper", "symbol": "AAPL",
        "option_symbol": "AAPL260620C00185000",
        "action": "BUY", "quantity": 1, "order_type": "LMT",
        "limit_price": 2.50, "entry_premium": 2.50,
    }
    base.update(extra)
    return base


def _strategy(**extra) -> ArmedStrategy:
    """An ArmedStrategy carrying the pick, for the service-level tests."""
    base = dict(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
        **{k: v for k, v in PICK.items()},
    )
    base.update(extra)
    return ArmedStrategy(**base)


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
    """The auto-trade router on its own app, with a real (in-memory) db.

    ALWAYS DISARMS ON THE WAY OUT. `auto_trader` is a module-level singleton
    shared with test_auto_trade.py and test_auto_trader.py, so a test that fails
    mid-way would otherwise leak an armed strategy into whichever file runs next
    — the same trap `test_arm_disarm_clears_armed_state` documents with its own
    try/finally.
    """
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


# ── The carry: ArmRequest -> ArmedStrategy ─────────────────────────────────

@pytest.mark.asyncio
async def test_arm_carries_all_five_picked_fields_onto_the_armed_strategy(client):
    """Test 6's first half. The five fields cross `ArmedStrategy(**req.model_dump())`
    with their values intact."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(**PICK))
    assert resp.status_code == 200, resp.text

    armed = auto_trader.get_state().strategy
    assert armed is not None
    assert armed.picked_method == "monte_carlo"
    assert armed.picked_row_stock_price == STOCK_TARGET
    assert armed.picked_row_option_price == OPTION_TARGET
    assert armed.picked_stop_basis == "premium"
    assert armed.picked_at == "2026-09-15T09:30:00Z"


@pytest.mark.asyncio
async def test_the_premium_and_the_underlying_arm_in_their_own_named_slots(client):
    """THE UNITS TEST, the arm-path counterpart of §10 test 2b, and the reason
    the fields carry their units in their names.

    `picked_row_stock_price` is the ONLY one of the two that may ever seed
    `resolved_tp_price`, which `alert_generator.py:181` compares against the
    STOCK quote. A $6.24 premium arriving in that slot makes `price >= 6.24`
    true on the first tick and fires TP_HIT instantly on every bullish option
    position. Swapping the two here is the whole defect, and it is invisible in
    a schema that types both as `Optional[float]` — only an assertion naming
    both values separately catches it."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(**PICK))
    assert resp.status_code == 200, resp.text

    armed = auto_trader.get_state().strategy
    assert armed.picked_row_stock_price == STOCK_TARGET, "the UNDERLYING slot"
    assert armed.picked_row_option_price == OPTION_TARGET, "the PREMIUM slot"
    # Stated the other way round too, because the assertion that matters is that
    # the premium is NOT in the stock slot, not merely that the stock price is.
    assert armed.picked_row_stock_price != OPTION_TARGET
    assert armed.picked_row_option_price != STOCK_TARGET


@pytest.mark.asyncio
async def test_a_body_with_no_picked_keys_still_arms_with_all_five_null(client):
    """The arm-path counterpart of §10 test 4 (D11): a pre-G client, or any
    caller that predates this step, must go on arming exactly as before. NULL is
    a real state here — "nobody picked" — not a missing value."""
    resp = await client.post("/auto-trade/arm", json=_arm_body())
    assert resp.status_code == 200, resp.text

    armed = auto_trader.get_state().strategy
    assert armed.picked_method is None
    assert armed.picked_row_stock_price is None
    assert armed.picked_row_option_price is None
    assert armed.picked_stop_basis is None
    assert armed.picked_at is None


@pytest.mark.asyncio
async def test_explicit_nulls_arm_exactly_as_omission_does(client):
    """This is the shape the FRONTEND actually sends when there is no pick:
    `armPickedFieldsFrom(null)` maps to five explicit nulls rather than omitting
    the keys, deliberately (see its doc — unlike `premium_stop_pct` one line
    above it in the same request body, an omission here has no global to mean
    "inherit"). If the schema treated an explicit null differently from an
    absent key, that mapping would be a 422 generator."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(
        picked_method=None, picked_row_stock_price=None,
        picked_row_option_price=None, picked_stop_basis=None, picked_at=None,
    ))
    assert resp.status_code == 200, resp.text

    armed = auto_trader.get_state().strategy
    assert armed.picked_method is None
    assert armed.picked_row_stock_price is None
    assert armed.picked_row_option_price is None
    assert armed.picked_stop_basis is None
    assert armed.picked_at is None


# ── The bounds ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["picked_row_stock_price", "picked_row_option_price"])
@pytest.mark.parametrize("value", [0, -1, -197.50])
async def test_a_non_positive_picked_row_price_is_refused_rather_than_armed(client, field, value):
    """The arm-path counterpart of §10 test 5, and it is not symmetry for its own
    sake: this endpoint reaches the same trade without ever passing through
    `PortfolioPositionCreate`, so its `gt=0` does not cover this door. Zero is
    never a price, and a `?? 0` fallback upstream is exactly how one arrives."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(**{field: value}))
    assert resp.status_code == 422, resp.text
    assert auto_trader.get_state().armed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"picked_method": "heston"},          # an rrModel PRICER, not a method (§9.4/§2.1)
    {"picked_method": "ladder_2r"},       # a TpMethod, a different vocabulary again (§2.6)
    {"picked_stop_basis": "option"},      # the field is 'stock' | 'premium'
    {"picked_stop_basis": "structural"},
])
async def test_an_unknown_method_or_stop_basis_is_refused_rather_than_armed(client, body):
    """The Literals are the point. `picked_method` sits one namespace away from
    two others this codebase also spells in snake_case — `rrModel`'s pricers and
    `TpMethod`'s rows — and a plain `Optional[str]` would arm any of them."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(**body))
    assert resp.status_code == 422, resp.text
    assert auto_trader.get_state().armed is False


# ── Frozen at arm (Q2, §3.2) ──────────────────────────────────────────────

def test_the_pick_that_reaches_the_executor_is_the_one_that_was_armed(mocker):
    """Test 6's second half, in the form that IS observable today: "carrying the
    armed pick, not a live one".

    `fire_now()` takes no body and re-reads nothing, so the strategy handed to
    `execute_option_order` is byte-for-byte the one `arm()` stored. This is the
    mechanism behind Q2 — not a new guard added for the pick, but the same one
    `quantity` and `premium_stop_pct` already rely on."""
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="777", status="PreSubmitted", broker="ibkr_paper"),
    )
    svc.arm(_strategy())
    svc.fire()

    forwarded = mock_execute.call_args.args[0]
    assert forwarded.picked_method == "monte_carlo"
    assert forwarded.picked_row_stock_price == STOCK_TARGET
    assert forwarded.picked_row_option_price == OPTION_TARGET
    assert forwarded.picked_stop_basis == "premium"
    assert forwarded.picked_at == "2026-09-15T09:30:00Z"


def test_re_arming_replaces_the_pick_rather_than_merging_it():
    """A second arm is a whole new strategy. A partial pick on the second call
    must not leave the first call's values showing through — that would be a
    card's pick surviving onto a trade it was never made for."""
    svc = AutoTradeService()
    svc.arm(_strategy())
    svc.arm(_strategy(picked_method="ladder", picked_row_stock_price=None,
                      picked_row_option_price=None, picked_stop_basis="stock",
                      picked_at="2026-09-15T14:00:00Z"))

    armed = svc.get_state().strategy
    assert armed.picked_method == "ladder"
    assert armed.picked_row_stock_price is None
    assert armed.picked_row_option_price is None
    assert armed.picked_stop_basis == "stock"
    assert armed.picked_at == "2026-09-15T14:00:00Z"


def test_vol_sizing_rewrites_the_quantity_without_dropping_the_pick(mocker):
    """`_apply_vol_sizing` returns `_dc_replace(strategy, quantity=...)` — a NEW
    ArmedStrategy. `dataclasses.replace` carries every other field across, so
    the pick survives; this pins that, because the alternative failure is
    silent. Regime sizing fires on an ordinary armed trade whenever
    `regime_sizing.enabled` is true, so this is not an exotic path."""
    from app.services import auto_trader as at
    mocker.patch.object(at, "_load_scoring_config", return_value={
        "enabled": True, "min_mult": 0.5, "full_conviction_pct": 40,
    })
    mocker.patch("app.services.regime_monitor.get_last_conviction", return_value=20.0)

    resized = at._apply_vol_sizing(_strategy(quantity=4))
    assert resized.quantity != 4, "the fixture must actually exercise the resize branch"
    assert resized.picked_method == "monte_carlo"
    assert resized.picked_row_stock_price == STOCK_TARGET
    assert resized.picked_row_option_price == OPTION_TARGET
    assert resized.picked_stop_basis == "premium"
    assert resized.picked_at == "2026-09-15T09:30:00Z"


# ── The tripwire on the gap this step does NOT close ──────────────────────

@pytest.mark.asyncio
async def test_firing_still_creates_no_position_so_the_armed_pick_is_captured_and_unread(
    client, engine_and_session, mocker,
):
    """A TRIPWIRE, NOT AN ENDORSEMENT — read the failure message before "fixing"
    this test.

    The auto-trade fire path creates no `PortfolioPosition` at all: `fire_now()`
    reads the positions table for an exposure snapshot and writes nothing back.
    That is pre-existing (CLAUDE.md's integrations table) and explicitly out of
    Phase G's scope (`phase_g_send_path_wiring_followups` calls it O4), which is
    why §10 test 6's second half — "creates a position carrying the armed pick"
    — cannot be written against today's code.

    So this asserts the gap instead. The day someone wires position creation into
    the fire path this test goes red, and whoever is holding it learns from the
    failure that `ArmedStrategy` has been carrying five `picked_*` fields all
    along and they are the ones that belong on the position — rather than
    shipping yet another send path that writes `picked_method = NULL`, which is
    the exact defect c41145ba had to go back and close for the other seven."""
    from app.data.ibkr_paper import OrderResult
    _, Session = engine_and_session
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="888", status="PreSubmitted", broker="tastytrade_paper"),
    )

    arm_resp = await client.post("/auto-trade/arm", json=_arm_body(**PICK))
    assert arm_resp.status_code == 200, arm_resp.text
    fire_resp = await client.post("/auto-trade/fire")
    assert fire_resp.status_code == 200, fire_resp.text
    assert fire_resp.json()["order_id"] == "888"

    async with Session() as s:
        rows = (await s.execute(select(PortfolioPositionModel))).scalars().all()
    assert rows == [], (
        "The auto-trade fire path now creates a position. That is a REAL "
        "improvement and this test is the wrong thing to delete: the armed "
        "strategy carries picked_method / picked_row_stock_price / "
        "picked_row_option_price / picked_stop_basis / picked_at (Phase G build "
        "step 5), and the new position must be built from THOSE, not from a "
        "freshly-read live pick and not with the five left NULL. Wire them, then "
        "replace this tripwire with the spec's §10 test 6 second half as "
        "originally written."
    )
