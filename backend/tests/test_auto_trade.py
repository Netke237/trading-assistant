import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_arm_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auto-trade/arm", json={
            "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL240119C00150000",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
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
async def test_arm_disarm_clears_armed_state():
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auto-trade/arm", json={
                "broker": "tastytrade_paper", "symbol": "MSFT", "option_symbol": "MSFT240119C00400000",
                "action": "BUY", "quantity": 1, "order_type": "MKT",
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
