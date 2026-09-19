import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_arm_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "direction": "Bullish", "quantity": 1, "order_type": "MKT",
            "entry_premium": 3.50,
        })
    assert resp.status_code != 422, (
        f"auto_trade.py's ArmRequest.broker Literal still rejects 'tastytrade_paper' "
        f"(got {resp.status_code}, body: {resp.text})"
    )
    # Disarm immediately so this test doesn't leave a real armed strategy for
    # any other test in the suite to trip over.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.delete("/auto-trade/arm")


@pytest.mark.asyncio
async def test_arm_rejects_zero_quantity():
    """Regression: ArmRequest.quantity had no lower-bound validation, unlike
    broker.py's equivalent fields (Field(ge=1)) — a 0 or negative quantity
    was accepted and would reach the broker. Must 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "direction": "Bullish", "quantity": 0, "order_type": "MKT",
            "entry_premium": 3.50,
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_arm_rejects_negative_quantity():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "direction": "Bullish", "quantity": -1, "order_type": "MKT",
            "entry_premium": 3.50,
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_arm_disarm_clears_armed_state():
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auto-trade/arm", json={
                "broker": "tastytrade_paper", "symbol": "MSFT", "option_symbol": "MSFT240119C00400000",
                "action": "BUY", "direction": "Bullish", "quantity": 1, "order_type": "MKT",
                "entry_premium": 2.00,
            })
            assert resp.status_code == 200

            status_resp = await client.get("/auto-trade/status")
            assert status_resp.json()["armed"] is True

            disarm_resp = await client.delete("/auto-trade/arm")
            assert disarm_resp.status_code == 200

            status_resp = await client.get("/auto-trade/status")
            assert status_resp.json()["armed"] is False
    finally:
        # If any assertion above fails, the module-level auto_trader singleton
        # could be left armed and leak into other test files (e.g.
        # test_auto_trader.py) that share it — always disarm, even on failure.
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.delete("/auto-trade/arm")


@pytest.mark.asyncio
async def test_arm_refuses_a_body_with_no_direction():
    """THE LOUD-FAILURE GUARANTEE, and the reason `direction` is required with no
    default.

    A default of "Bullish" would have been the easy choice and it would have
    reintroduced precisely the silent mis-direction this field exists to remove:
    every bearish trade armed by a caller that forgot the field would be sized
    off the wrong frame, invisibly, at fire time. Required means the mistake is a
    422 at ARM time instead — before anything is armed, with the field named.

    Note this does not depend on the extra-key policy: ArmRequest inherits
    pydantic's default `extra='ignore'`, but a MISSING required field is a 422
    regardless.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL",
            "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
            "entry_premium": 3.50,
        })
    assert resp.status_code == 422, resp.text
    assert "direction" in resp.text


@pytest.mark.asyncio
async def test_arm_carries_direction_through_to_the_armed_strategy_and_status():
    """THE SEAM. ROUND 1 finding 2.

    Three things were already pinned: the browser sends `direction`
    (AutoTradeArm.test.tsx), `_apply_vol_sizing` consumes it
    (test_auto_trader.py), and a body omitting it 422s (above). The join
    between them was not — no test asserted that a POST carrying
    `direction: "Bearish"` produces an ArmedStrategy that actually HOLDS
    "Bearish". Every piece could pass while the router dropped the value on the
    floor, and sizing would silently read the dataclass default... except there
    is no default, so it would raise — which is precisely the kind of thing a
    test should establish rather than a reader infer.

    Phase G wrote exactly this test for its five picked_* fields
    (test_phase_g_arm_pick.py, "The carry: ArmRequest -> ArmedStrategy") and
    premium_stop_pct has one too. This follows those precedents.

    "Bearish" is the discriminating value: it is the direction the old
    `action`-inference could never produce, since `action` is always BUY.
    """
    from app.services.auto_trader import auto_trader

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auto-trade/arm", json={
                "broker": "tastytrade_paper", "symbol": "NVDA",
                # A bearish trade is a long PUT — action stays BUY. That is the
                # whole reason `action` could never encode direction.
                "option_symbol": "NVDA240119P00400000",
                "action": "BUY", "direction": "Bearish", "quantity": 1,
                "order_type": "MKT", "entry_premium": 2.00,
            })
            assert resp.status_code == 200, resp.text

            # The carry itself.
            assert auto_trader._state.strategy is not None
            assert auto_trader._state.strategy.direction == "Bearish"
            # ...and that `action` did NOT become the source of truth again.
            assert auto_trader._state.strategy.action == "BUY"

            # The status endpoint's new key. Without this assertion the whole
            # `"direction": ...` line could be deleted from the router and the
            # entire suite would stay green.
            body = (await client.get("/auto-trade/status")).json()
            assert body["armed"] is True
            assert body["direction"] == "Bearish"

            await client.delete("/auto-trade/arm")
            # Cleared with the strategy, not left stale on a disarmed trader.
            assert (await client.get("/auto-trade/status")).json()["direction"] is None
    finally:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.delete("/auto-trade/arm")


@pytest.mark.asyncio
async def test_arm_refuses_sell_because_it_would_be_a_naked_short():
    """ROUND 1 finding 3. `action` is narrowed to Literal["BUY"].

    `effect` is not a field on this endpoint — `execute_option_order` hardcodes
    effect="OPEN" — so "SELL" here was a SELL-TO-OPEN: a naked short option.
    Nothing in this app intends that; the frontend has only ever sent "BUY".

    It mattered more after the sizing fix than before it. The old expression
    incidentally damped the SELL branch (`100 - conviction`); once sizing
    stopped reading `action` entirely, a naked short would have gone out at
    FULL conviction size. Declaring `action` meaningless for sizing while
    leaving it able to open an unintended position was the worst of both.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL",
            "option_symbol": "AAPL240119C00150000",
            "action": "SELL", "direction": "Bullish", "quantity": 1,
            "order_type": "MKT", "entry_premium": 3.50,
        })
    assert resp.status_code == 422, resp.text
    assert "action" in resp.text
